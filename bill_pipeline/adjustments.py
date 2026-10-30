"""人工确认的退款、垫款与分类。每次修改同事务校验并更新修订号。"""
import json
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from bill_pipeline.migrations import bump_revision
from bill_pipeline.observations import issue


@contextmanager
def writing(conn):
    if conn.in_transaction:
        raise ValueError('请先完成当前数据库操作')
    try:
        conn.execute('BEGIN IMMEDIATE')
        before=conn.total_changes
        yield
        if conn.total_changes!=before:bump_revision(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def integer(value, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError('金额必须是有效的整数分')


def transaction(conn,key,view='transactions'):
    if view not in ('transactions','net_transactions','effective_transactions'):
        raise ValueError('无效查询')
    cur=conn.execute(f'SELECT * FROM {view} WHERE source=? AND tx_id=?',key)
    row=cur.fetchone()
    if row is None:raise ValueError('找不到交易')
    return dict(zip([c[0] for c in cur.description],row))


def confirm_refund(conn, expense_key, refund_key, cents, *, event_id=None):
    integer(cents)
    with writing(conn):
        expense=transaction(conn,expense_key)
        if conn.execute("SELECT 1 FROM review_issues WHERE source=? AND tx_id=? AND kind='退款来源变更' AND resolved_at IS NULL",expense_key).fetchone():raise ValueError('原消费已变化，请先解除旧退款关联后重新核查')
        if expense['direction']!='支出' or expense['status'] in ('交易关闭','支付失败'):
            raise ValueError('请选择有效原消费')
        if refund_key==expense_key:raise ValueError('退款与消费不能是同一笔')
        if refund_key:
            refund=transaction(conn,refund_key)
            if refund['direction']=='支出' or cents>refund['amount_cents']:
                raise ValueError('退款记录的方向或金额不符')
            existing=conn.execute('SELECT event_id FROM refund_evidence WHERE source=? AND tx_id=?',refund_key).fetchone()
            if existing:
                if event_id is not None and existing[0]!=event_id:raise ValueError('该退款已关联其他事件')
                previous=conn.execute('SELECT expense_source,expense_id,cents,revoked_at FROM refund_events WHERE id=?',existing).fetchone()
                if previous and tuple(previous[:2])==tuple(expense_key) and previous[2]==cents and previous[3] is None:return existing[0]
                raise ValueError('该退款已有分配，请先解除关联')
        if event_id:
            old=conn.execute('SELECT expense_source,expense_id,cents,revoked_at FROM refund_events WHERE id=?',(event_id,)).fetchone()
            if not old or tuple(old[:2])!=tuple(expense_key) or old[2]!=cents or old[3]:raise ValueError('现有退款事件不匹配')
        else:
            total=conn.execute('SELECT COALESCE(SUM(cents),0) FROM refund_events WHERE expense_source=? AND expense_id=? AND revoked_at IS NULL',expense_key).fetchone()[0]
            if total+cents>expense['amount_cents']:raise ValueError('累计退款超过原金额')
            event_id=uuid4().hex
            conn.execute('INSERT INTO refund_events VALUES(?,?,?,?,?,NULL)',(event_id,*expense_key,cents,datetime.now().isoformat()))
        if refund_key:
            conn.execute('INSERT INTO refund_evidence VALUES(?,?,?)',(event_id,*refund_key))
            conn.execute("UPDATE review_issues SET resolved_at=? WHERE source=? AND tx_id=? AND kind='退款待核查'",(datetime.now().isoformat(),*refund_key))
        conn.execute("UPDATE review_issues SET resolved_at=? WHERE source=? AND tx_id=? AND kind='退款待核查'",(datetime.now().isoformat(),*expense_key))
    return event_id


def revoke_refund(conn,event_id):
    with writing(conn):
        keys=conn.execute('SELECT source,tx_id FROM refund_evidence WHERE event_id=?',(event_id,)).fetchall()
        original=conn.execute('SELECT expense_source,expense_id FROM refund_events WHERE id=?',(event_id,)).fetchone()
        conn.execute('UPDATE refund_events SET revoked_at=? WHERE id=?',(datetime.now().isoformat(),event_id))
        conn.execute('DELETE FROM refund_evidence WHERE event_id=?',(event_id,))
        for key in keys:issue(conn,key,'退款待核查',{'reason':'退款关联已解除'})
        for key in keys+([original] if original else []):
            if not conn.execute('SELECT 1 FROM refund_events f WHERE f.revoked_at IS NULL AND ((f.expense_source=? AND f.expense_id=?) OR EXISTS(SELECT 1 FROM refund_evidence e WHERE e.event_id=f.id AND e.source=? AND e.tx_id=?))',(*key,*key)).fetchone():
                conn.execute("UPDATE review_issues SET resolved_at=? WHERE source=? AND tx_id=? AND kind='退款来源变更'",(datetime.now().isoformat(),*key))


def set_transaction_categories(conn,tx_key,allocations):
    if not allocations or len(set(c for c,_ in allocations))!=len(allocations):raise ValueError('分类不能为空或重复')
    with writing(conn):
        tx=transaction(conn,tx_key,'effective_transactions')
        if tx['result']!='消费':raise ValueError('只有消费能设置分类')
        allowed={r[0] for r in conn.execute('SELECT name FROM categories')}|{'未归类'}
        for category,cents in allocations:
            integer(cents,zero=True)
            if category not in allowed:raise ValueError('分类不存在')
        if sum(v for _,v in allocations)!=tx['counted_cents']:raise ValueError('拆分合计必须等于个人消费净额')
        conn.execute('DELETE FROM category_overrides WHERE source=? AND tx_id=?',tx_key)
        conn.execute('INSERT INTO category_overrides VALUES(?,?,?)',(*tx_key,tx['counted_cents']))
        conn.execute("UPDATE review_issues SET resolved_at=? WHERE source=? AND tx_id=? AND kind='分类来源变更'",(datetime.now().isoformat(),*tx_key))
        conn.executemany('INSERT INTO category_allocations VALUES(?,?,?,?)',[(*tx_key,c,n) for c,n in allocations])


def clear_transaction_categories(conn,tx_key):
    with writing(conn):
        conn.execute('DELETE FROM category_overrides WHERE source=? AND tx_id=?',tx_key)
        conn.execute("UPDATE review_issues SET resolved_at=? WHERE source=? AND tx_id=? AND kind='分类来源变更'",(datetime.now().isoformat(),*tx_key))


def set_counterparty_alias(conn,source,counterparty,canonical):
    if not canonical.strip():raise ValueError('默认商户名不能为空')
    with writing(conn):
        conn.execute('INSERT INTO counterparty_aliases VALUES(?,?,?) ON CONFLICT(source,counterparty) DO UPDATE SET canonical=excluded.canonical',
                     (source,counterparty,canonical.strip()))


def create_advance(conn,expense_key,personal_cents):
    integer(personal_cents,zero=True)
    with writing(conn):
        tx=transaction(conn,expense_key,'net_transactions')
        if tx['result']!='消费' or personal_cents>tx['net_cents']:raise ValueError('个人份额不能超过净消费')
        old=conn.execute('SELECT id,personal_cents FROM advance_groups WHERE source=? AND tx_id=? AND revoked_at IS NULL',expense_key).fetchone()
        if old:
            if old[1]==personal_cents and conn.execute('SELECT 1 FROM valid_advances WHERE id=?',(old[0],)).fetchone():return old[0]
            raise ValueError('已有垫款组，请先解除')
        gid=uuid4().hex
        conn.execute('INSERT INTO advance_groups VALUES(?,?,?,?,?,NULL)',(gid,*expense_key,tx['net_cents'],personal_cents))
    return gid


def allocate_repayment(conn,advance_id,income_key,cents):
    integer(cents)
    with writing(conn):
        group=conn.execute('SELECT net_snapshot,personal_cents FROM valid_advances WHERE id=?',(advance_id,)).fetchone()
        income=transaction(conn,income_key)
        if not group or income['result']!='收入':raise ValueError('垫款组或收款口径需要核查')
        prior=conn.execute('SELECT id,cents FROM repayment_allocations WHERE advance_id=? AND source=? AND tx_id=? AND revoked_at IS NULL',(advance_id,*income_key)).fetchone()
        if prior:
            if prior[1]==cents:return prior[0]
            raise ValueError('这笔收款已经分配到该组，请先解除后重新分配')
        used=conn.execute('SELECT COALESCE(SUM(cents),0) FROM repayment_allocations WHERE advance_id=? AND revoked_at IS NULL',(advance_id,)).fetchone()[0]
        available=transaction(conn,income_key,'effective_transactions')['counted_cents']
        if cents>group[0]-group[1]-used or cents>available:raise ValueError('超过垫款或收款可分配金额')
        rid=uuid4().hex
        conn.execute('INSERT INTO repayment_allocations VALUES(?,?,?,?,?,?,NULL)',(rid,advance_id,*income_key,cents,income['counted_cents']))
    return rid


def revoke_repayment(conn,allocation_id):
    with writing(conn):conn.execute('UPDATE repayment_allocations SET revoked_at=? WHERE id=?',(datetime.now().isoformat(),allocation_id))


def revoke_advance(conn,advance_id):
    with writing(conn):
        conn.execute('UPDATE advance_groups SET revoked_at=? WHERE id=?',(datetime.now().isoformat(),advance_id))
        conn.execute("UPDATE review_issues SET resolved_at=? WHERE (source,tx_id)=(SELECT source,tx_id FROM advance_groups WHERE id=?) AND kind='垫款来源变更'",(datetime.now().isoformat(),advance_id))


def effective_transactions(conn,month=None):
    cur=conn.execute('SELECT * FROM effective_transactions WHERE (? IS NULL OR substr(tx_time,1,7)=?) ORDER BY tx_time DESC,source,tx_id',(month,month))
    return [dict(zip([c[0] for c in cur.description],r)) for r in cur.fetchall()]


def effective_allocations(conn,month=None):
    cur=conn.execute('SELECT a.* FROM effective_allocations a JOIN transactions t USING(source,tx_id) WHERE (? IS NULL OR substr(t.tx_time,1,7)=?)',(month,month))
    return [dict(zip([c[0] for c in cur.description],r)) for r in cur.fetchall()]


def list_review_issues(conn,month=None):
    cur=conn.execute('SELECT i.*,t.tx_time,t.counterparty FROM review_issues i JOIN transactions t USING(source,tx_id) WHERE i.resolved_at IS NULL AND (? IS NULL OR substr(t.tx_time,1,7)=?) ORDER BY i.id DESC',(month,month))
    result=[dict(zip([c[0] for c in cur.description],r)) for r in cur.fetchall()]
    for row in conn.execute('SELECT g.source,g.tx_id FROM advance_groups g WHERE g.revoked_at IS NULL AND NOT EXISTS(SELECT 1 FROM valid_advances v WHERE v.id=g.id)'):
        tx=transaction(conn,row)
        if month is None or tx['tx_time'].startswith(month):result.append({'source':row[0],'tx_id':row[1],'kind':'垫款需重核','counterparty':tx['counterparty'],'tx_time':tx['tx_time']})
    for row in conn.execute('SELECT o.source,o.tx_id FROM category_overrides o JOIN effective_transactions t USING(source,tx_id) WHERE o.net_snapshot!=t.counted_cents'):
        tx=transaction(conn,row)
        if month is None or tx['tx_time'].startswith(month):result.append({'source':row[0],'tx_id':row[1],'kind':'分类拆分需重核','counterparty':tx['counterparty'],'tx_time':tx['tx_time']})
    return result


def refund_candidates(conn,source,refund_id):
    refund=transaction(conn,(source,refund_id))
    if refund['merchant_order'] in ('','/'):return []
    return [t for t in effective_transactions(conn) if t['source']==source and t['direction']=='支出'
            and t['merchant_order']==refund['merchant_order'] and t['amount_cents']>=refund['amount_cents']]


def resolve_refund_review(conn,key,decision):
    if not decision.strip():raise ValueError('请说明核查结论')
    with writing(conn):
        for (iid,) in conn.execute("SELECT id FROM review_issues WHERE source=? AND tx_id=? AND kind='退款待核查' AND resolved_at IS NULL",key).fetchall():
            conn.execute('INSERT INTO review_decisions(issue_id,decision,created_at) VALUES(?,?,?)',(iid,decision.strip(),datetime.now().isoformat()))
            conn.execute('UPDATE review_issues SET resolved_at=? WHERE id=?',(datetime.now().isoformat(),iid))


def record_return(conn,kind,expense_key,receipt_key,cents):
    """统一回款入口，AA的组创建和收款分配在同一事务中完成。"""
    from bill_pipeline.migrations import data_revision
    integer(cents)
    before=data_revision(conn)
    if kind=='refund':
        eid=confirm_refund(conn,expense_key,receipt_key,cents)
        return {'kind':kind,'id':eid,'revision':data_revision(conn),'changed':data_revision(conn)!=before}
    if kind!='aa':raise ValueError('请选择退款或AA回款')
    if receipt_key is None:raise ValueError('AA回款需要选择收款记录；尚未收齐可使用更多操作')
    with writing(conn):
        expense=transaction(conn,expense_key,'net_transactions')
        receipt=transaction(conn,receipt_key)
        if expense['result']!='消费' or receipt['result']!='收入':raise ValueError('请选择有效支出和已识别的收入记录')
        group=conn.execute('SELECT id,personal_cents,net_snapshot FROM advance_groups WHERE source=? AND tx_id=? AND revoked_at IS NULL',expense_key).fetchone()
        old_own=None
        created=not group
        if group:
            gid,old_own,net=group
            if not conn.execute('SELECT 1 FROM valid_advances WHERE id=?',(gid,)).fetchone():raise ValueError('已有AA分配需重核，请展开更多操作')
            prior=conn.execute('SELECT id,cents FROM repayment_allocations WHERE advance_id=? AND source=? AND tx_id=? AND revoked_at IS NULL',(gid,*receipt_key)).fetchone()
            if prior:
                if prior[1]!=cents:raise ValueError('该收款已分配，修改金额前请先撤销')
                return {'kind':kind,'id':prior[0],'changed':False,'revision':before}
            used=conn.execute('SELECT COALESCE(SUM(cents),0) FROM repayment_allocations WHERE advance_id=? AND revoked_at IS NULL',(gid,)).fetchone()[0]
            # 普通回款按累计收回金额自动计算自付额；明确设置过的未收齐AA保留个人份额。
            own=old_own-cents if net-old_own==used else old_own
            if own<0 or used+cents>net-own:raise ValueError('回款超过这笔支出的可抵扣金额')
        else:
            net=expense['net_cents'];own=net-cents;gid=uuid4().hex
            if own<0:raise ValueError('回款超过这笔支出的净额')
        available=transaction(conn,receipt_key,'effective_transactions')['counted_cents']
        if cents>available:raise ValueError('回款超过收款记录的可分配金额')
        if created:conn.execute('INSERT INTO advance_groups VALUES(?,?,?,?,?,NULL)',(gid,*expense_key,net,own))
        else:conn.execute('UPDATE advance_groups SET personal_cents=? WHERE id=?',(own,gid))
        baseline=receipt['counted_cents']-conn.execute('SELECT COALESCE(SUM(f.cents),0) FROM refund_evidence e JOIN valid_refunds f ON f.id=e.event_id WHERE e.source=? AND e.tx_id=?',receipt_key).fetchone()[0]
        rid=uuid4().hex
        conn.execute('INSERT INTO repayment_allocations VALUES(?,?,?,?,?,?,NULL)',(rid,gid,*receipt_key,cents,baseline))
    return {'kind':kind,'id':rid,'group':gid,'created':created,'old_own':old_own,'changed':True,'revision':data_revision(conn)}


def undo_return(conn,change):
    from bill_pipeline.migrations import data_revision
    if not change.get('changed'):return
    if data_revision(conn)!=change['revision']:raise ValueError('数据已变化，请在更多操作中解除对应回款')
    if change['kind']=='refund':
        revoke_refund(conn,change['id']);return
    with writing(conn):
        conn.execute('UPDATE repayment_allocations SET revoked_at=? WHERE id=?',(datetime.now().isoformat(),change['id']))
        if change['created']:conn.execute('UPDATE advance_groups SET revoked_at=? WHERE id=?',(datetime.now().isoformat(),change['group']))
        else:conn.execute('UPDATE advance_groups SET personal_cents=? WHERE id=?',(change['old_own'],change['group']))
