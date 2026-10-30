"""保存来源观测；重复并不意味着可以丢掉新的退款状态。"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from bill_pipeline.migrations import bump_revision
from bill_pipeline.rules import classify


def refresh_rules(conn):
    from bill_pipeline.rules import RULESET_VERSION
    old=conn.execute('SELECT ruleset_version FROM data_state WHERE id=1').fetchone()[0]
    if old==RULESET_VERSION:return
    with conn:
        for row in conn.execute('SELECT source,tx_id,direction,tx_type,status,amount_cents FROM transactions').fetchall():
            source,tid,direction,kind,status,cents=row
            c=classify(direction,kind,status,cents,source=source)
            conn.execute('UPDATE transactions SET result=?,reason=?,category=?,counted_cents=? WHERE source=? AND tx_id=?',(*c,source,tid))
            if '退款' in status or '退款' in kind:
                if not(direction=='支出' and status=='已全额退款'):issue(conn,(source,tid),'退款待核查')
        conn.execute('UPDATE data_state SET ruleset_version=? WHERE id=1',(RULESET_VERSION,))
        bump_revision(conn)


@dataclass
class ImportChanges:
    new: int = 0
    updated: int = 0
    duplicate: int = 0
    conflicts: int = 0


def issue(conn, key, kind, detail=None):
    conn.execute('INSERT INTO review_issues(source,tx_id,kind,details_json) VALUES(?,?,?,?) '
                 'ON CONFLICT(source,tx_id,kind) DO UPDATE SET details_json=excluded.details_json,resolved_at=CASE WHEN review_issues.details_json=excluded.details_json THEN review_issues.resolved_at ELSE NULL END',
                 (*key, kind, json.dumps(detail or {}, ensure_ascii=False)))


def _dict_row(cursor):
    row = cursor.fetchone()
    return dict(zip([c[0] for c in cursor.description], row)) if row else None


def _record(conn, row, exported):
    fields = ('source','tx_id','tx_time','tx_type','counterparty','item','direction','amount_cents','method','status','merchant_order','note')
    fingerprint = hashlib.sha256(json.dumps({k: row[k] for k in fields}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    conn.execute('INSERT INTO transaction_observations(source,tx_id,import_id,exported_at,fingerprint,payload_json) '
                 'VALUES(?,?,?,?,?,?) ON CONFLICT(source,tx_id,fingerprint) DO UPDATE SET exported_at='
                 'CASE WHEN excluded.exported_at > COALESCE(exported_at,\'\') THEN excluded.exported_at ELSE exported_at END',
                 (row['source'],row['tx_id'],row['import_id'],exported,fingerprint,json.dumps(row,ensure_ascii=False)))
    return conn.execute('SELECT id FROM transaction_observations WHERE source=? AND tx_id=? AND fingerprint=?',
                        (row['source'],row['tx_id'],fingerprint)).fetchone()[0]


def _select(conn, observation_id):
    row = conn.execute('SELECT source,tx_id,payload_json FROM transaction_observations WHERE id=?',(observation_id,)).fetchone()
    if row is None:
        raise ValueError('找不到这份交易观测')
    source, tx_id, payload = row
    data = json.loads(payload)
    current=_dict_row(conn.execute('SELECT * FROM transactions WHERE source=? AND tx_id=?',(source,tx_id)))
    if current and any(current[k]!=data[k] for k in ('tx_time','amount_cents','direction','counterparty')):
        if conn.execute('SELECT 1 FROM category_overrides WHERE source=? AND tx_id=?',(source,tx_id)).fetchone():issue(conn,(source,tx_id),'分类来源变更')
        if conn.execute('SELECT 1 FROM advance_groups WHERE source=? AND tx_id=? AND revoked_at IS NULL',(source,tx_id)).fetchone():issue(conn,(source,tx_id),'垫款来源变更')
    if current and any(current[k]!=data[k] for k in ('tx_time','amount_cents','direction','counterparty')):
        if conn.execute('SELECT 1 FROM refund_events f WHERE f.revoked_at IS NULL AND ((f.expense_source=? AND f.expense_id=?) OR EXISTS(SELECT 1 FROM refund_evidence e WHERE e.event_id=f.id AND e.source=? AND e.tx_id=?))',(source,tx_id,source,tx_id)).fetchone():issue(conn,(source,tx_id),'退款来源变更')
    c = classify(data['direction'],data['tx_type'],data['status'],data['amount_cents'],source=source)
    data.update(zip(c._fields,c))
    fields = [k for k in data if k not in ('source','tx_id')]
    conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in fields)+' WHERE source=? AND tx_id=?',
                 [data[k] for k in fields]+[source,tx_id])
    conn.execute('INSERT INTO transaction_selection VALUES(?,?,?) ON CONFLICT(source,tx_id) DO UPDATE SET observation_id=excluded.observation_id',
                 (source,tx_id,observation_id))


def select_observation(conn, observation_id: int):
    with conn:
        _select(conn, observation_id)
        conn.execute("UPDATE review_issues SET resolved_at=? WHERE kind='快照冲突' AND (source,tx_id)=(SELECT source,tx_id FROM transaction_observations WHERE id=?)",
                     (datetime.now().isoformat(),observation_id))
        bump_revision(conn)


def observe_import(conn, bill, classified_rows, file_name):
    from bill_pipeline.db import INSERT_TX
    changes = ImportChanges()
    records = classified_rows.astype(object).where(classified_rows.notna(), None).to_dict('records')
    with conn:
        coverage_changed = not conn.execute('SELECT 1 FROM imports WHERE source=? AND period_start=? AND period_end=? '
                                           'AND exported_at IS ? AND export_scope IS ?',
                                           (bill.source,bill.period_start,bill.period_end,bill.exported_at,bill.export_scope)).fetchone()
        import_id = conn.execute('INSERT INTO imports(file_name,source,period_start,period_end,imported_at,rows_total,exported_at,export_scope) VALUES(?,?,?,?,?,?,?,?)',
                                 (file_name,bill.source,bill.period_start,bill.period_end,datetime.now().isoformat(),len(records),bill.exported_at,bill.export_scope)).lastrowid
        for data in records:
            data.update(source=bill.source,import_id=import_id)
            key = (bill.source,data['tx_id'])
            old = _dict_row(conn.execute('SELECT * FROM transactions WHERE source=? AND tx_id=?',key))
            if old is not None and not conn.execute('SELECT 1 FROM transaction_selection WHERE source=? AND tx_id=?',key).fetchone():
                _select(conn,_record(conn,old,None))
            oid = _record(conn,data,bill.exported_at)
            if old is None:
                conn.execute(INSERT_TX,data)
                _select(conn,oid)
                changes.new += 1
            elif all(old[k]==data[k] for k in ('tx_time','tx_type','counterparty','item','direction','amount_cents','method','status','merchant_order','note')):
                changes.duplicate += 1
            else:
                previous = conn.execute('SELECT o.exported_at FROM transaction_selection s JOIN transaction_observations o ON o.id=s.observation_id WHERE s.source=? AND s.tx_id=?',key).fetchone()[0]
                facts_same = all(old[k]==data[k] for k in ('tx_time','direction','amount_cents','counterparty'))
                terminal = data['status']=='已全额退款' and old['status']!='已全额退款'
                old_file = previous and bill.exported_at and bill.exported_at < previous
                trusted_new = previous and bill.exported_at and bill.exported_at>previous
                if facts_same and not old_file and (trusted_new or (terminal and not previous)) and not (old['status']=='已全额退款' and data['status']!='已全额退款'):
                    _select(conn,oid)
                    changes.updated += 1
                elif old_file and facts_same:
                    changes.duplicate += 1
                else:
                    issue(conn,key,'快照冲突',{'observation_id':oid,'reason':'来源事实或状态需要核查'})
                    changes.conflicts += 1
            suspect = ('退款' in data['status'] or '退款' in data['tx_type'] or '退款' in data['item'] or '退款' in data['note'])
            if suspect and not (data['direction']=='支出' and data['status']=='已全额退款'):
                issue(conn,key,'退款待核查',{'reason':'核实退款与原消费的关系；未自动抵扣','observation_id':oid})
        conn.execute('UPDATE imports SET rows_new=?,rows_skipped=?,rows_updated=?,rows_conflicts=? WHERE id=?',
                     (changes.new,changes.duplicate,changes.updated,changes.conflicts,import_id))
        if changes.new or changes.updated or changes.conflicts or coverage_changed:
            bump_revision(conn)
    return changes
