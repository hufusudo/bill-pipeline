"""应用数据库升级。备份先于任何旧库修改，DDL与版本号同事务提交。"""
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

VERSION = 3
DECISION_DDL='CREATE TABLE review_decisions(id INTEGER PRIMARY KEY,issue_id INTEGER NOT NULL REFERENCES review_issues(id),decision TEXT NOT NULL,created_at TEXT NOT NULL)'
CHAT_DDL = [
    'CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,deleted_at TEXT)',
    'CREATE TABLE messages(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,question TEXT NOT NULL,default_month TEXT,mode TEXT,status TEXT NOT NULL,answer TEXT NOT NULL DEFAULT \'\',reason TEXT NOT NULL DEFAULT \'\',batches INTEGER DEFAULT 0,elapsed REAL DEFAULT 0,start_revision INTEGER NOT NULL,end_revision INTEGER,run_id TEXT NOT NULL,owner_instance TEXT,created_at TEXT NOT NULL,finished_at TEXT)',
    'CREATE TABLE evidence(message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,position INTEGER,tool TEXT NOT NULL,summary_json TEXT NOT NULL,PRIMARY KEY(message_id,position))',
    'CREATE TABLE runtime_instances(id TEXT PRIMARY KEY,heartbeat_at REAL NOT NULL)',
]
DDL = [
    'CREATE TABLE schema_version(version INTEGER NOT NULL)',
    "CREATE TABLE data_state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, ruleset_version TEXT NOT NULL)",
    'CREATE TABLE transaction_observations(id INTEGER PRIMARY KEY,source TEXT NOT NULL,tx_id TEXT NOT NULL,import_id INTEGER,exported_at TEXT,fingerprint TEXT NOT NULL,payload_json TEXT NOT NULL,UNIQUE(source,tx_id,fingerprint))',
    'CREATE TABLE transaction_selection(source TEXT,tx_id TEXT,observation_id INTEGER REFERENCES transaction_observations(id),PRIMARY KEY(source,tx_id))',
    'CREATE TABLE review_issues(id INTEGER PRIMARY KEY,source TEXT NOT NULL,tx_id TEXT NOT NULL,kind TEXT NOT NULL,details_json TEXT NOT NULL DEFAULT \'{}\',resolved_at TEXT,UNIQUE(source,tx_id,kind))',
    'CREATE TABLE refund_events(id TEXT PRIMARY KEY,expense_source TEXT,expense_id TEXT,cents INTEGER NOT NULL CHECK(cents>0),confirmed_at TEXT NOT NULL,revoked_at TEXT)',
    'CREATE TABLE refund_evidence(event_id TEXT REFERENCES refund_events(id),source TEXT,tx_id TEXT,PRIMARY KEY(source,tx_id))',
    'CREATE TABLE category_overrides(source TEXT,tx_id TEXT,net_snapshot INTEGER NOT NULL,PRIMARY KEY(source,tx_id))',
    'CREATE TABLE category_allocations(source TEXT,tx_id TEXT,category TEXT,cents INTEGER NOT NULL CHECK(cents>=0),PRIMARY KEY(source,tx_id,category),FOREIGN KEY(source,tx_id) REFERENCES category_overrides(source,tx_id) ON DELETE CASCADE)',
    'CREATE TABLE counterparty_aliases(source TEXT,counterparty TEXT,canonical TEXT NOT NULL,PRIMARY KEY(source,counterparty))',
    'CREATE TABLE advance_groups(id TEXT PRIMARY KEY,source TEXT,tx_id TEXT,net_snapshot INTEGER NOT NULL,personal_cents INTEGER NOT NULL CHECK(personal_cents>=0),revoked_at TEXT)',
    'CREATE UNIQUE INDEX active_advance ON advance_groups(source,tx_id) WHERE revoked_at IS NULL',
    'CREATE TABLE repayment_allocations(id TEXT PRIMARY KEY,advance_id TEXT REFERENCES advance_groups(id),source TEXT,tx_id TEXT,cents INTEGER NOT NULL CHECK(cents>0),net_snapshot INTEGER NOT NULL,revoked_at TEXT)',
    'CREATE TABLE preferences(name TEXT PRIMARY KEY,value TEXT NOT NULL)',
]

VIEWS = [
    """CREATE VIEW valid_refunds AS SELECT f.* FROM refund_events f WHERE f.revoked_at IS NULL
       AND NOT EXISTS(SELECT 1 FROM review_issues q WHERE q.source=f.expense_source AND q.tx_id=f.expense_id AND q.kind='退款来源变更' AND q.resolved_at IS NULL)
       AND NOT EXISTS(SELECT 1 FROM refund_evidence e JOIN review_issues q ON q.source=e.source AND q.tx_id=e.tx_id WHERE e.event_id=f.id AND q.kind='退款来源变更' AND q.resolved_at IS NULL)""",
    """CREATE VIEW net_transactions AS SELECT t.*,
       CASE WHEN t.status='已全额退款' THEN 0 WHEN t.result='消费' THEN MAX(0,t.counted_cents-
       COALESCE((SELECT SUM(cents) FROM valid_refunds f WHERE f.expense_source=t.source AND f.expense_id=t.tx_id AND f.revoked_at IS NULL),0))
       ELSE t.counted_cents END AS net_cents FROM transactions t""",
    """CREATE VIEW valid_advances AS SELECT g.* FROM advance_groups g
       JOIN net_transactions t ON t.source=g.source AND t.tx_id=g.tx_id
       WHERE g.revoked_at IS NULL AND NOT EXISTS(SELECT 1 FROM review_issues q WHERE q.source=g.source AND q.tx_id=g.tx_id AND q.kind='垫款来源变更' AND q.resolved_at IS NULL) AND g.net_snapshot=t.net_cents AND t.result='消费'
       AND NOT EXISTS(SELECT 1 FROM repayment_allocations r LEFT JOIN transactions i ON i.source=r.source AND i.tx_id=r.tx_id
       WHERE r.advance_id=g.id AND r.revoked_at IS NULL AND (i.tx_id IS NULL OR i.result!='收入' OR i.counted_cents-COALESCE((SELECT SUM(f.cents) FROM refund_evidence e JOIN valid_refunds f ON f.id=e.event_id WHERE e.source=i.source AND e.tx_id=i.tx_id AND f.revoked_at IS NULL),0)!=r.net_snapshot))""",
    """CREATE VIEW personal_transactions AS SELECT t.*,
       CASE WHEN t.result='消费' THEN COALESCE(g.personal_cents,t.net_cents)
       WHEN t.result='收入' THEN MAX(0,t.counted_cents-COALESCE((SELECT SUM(f.cents) FROM refund_evidence e JOIN valid_refunds f ON f.id=e.event_id WHERE e.source=t.source AND e.tx_id=t.tx_id AND f.revoked_at IS NULL),0)-COALESCE((SELECT SUM(r.cents) FROM repayment_allocations r
       JOIN valid_advances g ON g.id=r.advance_id WHERE r.source=t.source AND r.tx_id=t.tx_id AND r.revoked_at IS NULL),0))
       ELSE t.net_cents END AS personal_cents
       FROM net_transactions t LEFT JOIN valid_advances g ON g.source=t.source AND g.tx_id=t.tx_id""",
    """CREATE VIEW effective_transactions AS SELECT t.source,t.tx_id,t.tx_time,t.tx_type,t.counterparty,t.item,t.direction,
       t.amount_cents,t.method,t.status,t.merchant_order,t.note,t.result,t.import_id,
       t.personal_cents AS counted_cents,
       CASE WHEN t.personal_cents!=t.counted_cents THEN '个人口径调整' ELSE t.reason END AS reason,
       CASE WHEN o.source IS NOT NULL AND o.net_snapshot=t.personal_cents THEN
         CASE WHEN (SELECT COUNT(*) FROM category_allocations a WHERE a.source=t.source AND a.tx_id=t.tx_id)>1 THEN '多类别'
         ELSE (SELECT category FROM category_allocations a WHERE a.source=t.source AND a.tx_id=t.tx_id LIMIT 1) END
       ELSE COALESCE(t.category,m.category,am.category) END AS category
       FROM personal_transactions t LEFT JOIN category_overrides o ON o.source=t.source AND o.tx_id=t.tx_id AND NOT EXISTS(SELECT 1 FROM review_issues q WHERE q.source=t.source AND q.tx_id=t.tx_id AND q.kind='分类来源变更' AND q.resolved_at IS NULL)
       LEFT JOIN counterparty_categories m ON m.counterparty=t.counterparty
       LEFT JOIN counterparty_aliases alias ON alias.source=t.source AND alias.counterparty=t.counterparty
       LEFT JOIN counterparty_categories am ON am.counterparty=alias.canonical""",
    """CREATE VIEW effective_allocations AS
       SELECT t.source,t.tx_id,a.category,a.cents AS counted_cents FROM personal_transactions t
       JOIN category_overrides o ON o.source=t.source AND o.tx_id=t.tx_id AND o.net_snapshot=t.personal_cents AND NOT EXISTS(SELECT 1 FROM review_issues q WHERE q.source=t.source AND q.tx_id=t.tx_id AND q.kind='分类来源变更' AND q.resolved_at IS NULL)
       JOIN category_allocations a ON a.source=t.source AND a.tx_id=t.tx_id WHERE t.result='消费'
       UNION ALL SELECT t.source,t.tx_id,COALESCE(t.category,'未归类'),t.counted_cents FROM effective_transactions t
       WHERE t.result='消费' AND NOT EXISTS(SELECT 1 FROM category_overrides o WHERE o.source=t.source AND o.tx_id=t.tx_id AND o.net_snapshot=t.counted_cents AND NOT EXISTS(SELECT 1 FROM review_issues q WHERE q.source=t.source AND q.tx_id=t.tx_id AND q.kind='分类来源变更' AND q.resolved_at IS NULL))""",
]


def data_revision(conn) -> int:
    return conn.execute('SELECT revision FROM data_state WHERE id=1').fetchone()[0]


def bump_revision(conn) -> int:
    conn.execute('UPDATE data_state SET revision=revision+1 WHERE id=1')
    return data_revision(conn)


def backup_database(conn, path: Path) -> Path:
    folder = path.parent / 'backups'
    folder.mkdir(parents=True, exist_ok=True,mode=0o700)
    target = folder / f'{path.stem}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.db'
    backup = sqlite3.connect(target)
    target.chmod(0o600)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    return target


def migrate(conn, db_path: Path | None) -> None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone()
    if exists:
        version = conn.execute('SELECT version FROM schema_version').fetchone()[0]
        if version > VERSION:
            raise ValueError('数据库版本较新，请使用匹配的应用版本')
        if version < VERSION:
            if conn.in_transaction:raise RuntimeError('升级前存在未提交事务')
            if db_path is not None:backup_database(conn,db_path)
            try:
                conn.execute('BEGIN IMMEDIATE')
                if version<2:
                    for statement in CHAT_DDL:conn.execute(statement)
                if version<3:conn.execute(DECISION_DDL)
                for view in ('effective_allocations','effective_transactions','personal_transactions','valid_advances','net_transactions','valid_refunds'):
                    conn.execute('DROP VIEW IF EXISTS '+view)
                for statement in VIEWS:conn.execute(statement)
                conn.execute('UPDATE schema_version SET version=?',(VERSION,))
                conn.commit()
            except BaseException:
                conn.rollback();raise
        return
    if conn.in_transaction:
        raise RuntimeError('数据库升级前存在未提交事务')
    if db_path is not None:
        backup_database(conn, db_path)
    from bill_pipeline.rules import RULESET_VERSION
    try:
        conn.execute('BEGIN IMMEDIATE')
        for statement in DDL:
            conn.execute(statement)
        for statement in CHAT_DDL:
            conn.execute(statement)
        conn.execute(DECISION_DDL)
        for name, dtype in [('exported_at','TEXT'),('export_scope','TEXT'),('fingerprint','TEXT'),
                            ('rows_updated','INTEGER DEFAULT 0'),('rows_conflicts','INTEGER DEFAULT 0')]:
            conn.execute(f'ALTER TABLE imports ADD COLUMN {name} {dtype}')
        conn.execute('INSERT INTO schema_version VALUES (?)', (VERSION,))
        conn.execute('INSERT INTO data_state VALUES (1,0,?)', ('legacy' if db_path is not None else RULESET_VERSION,))
        for statement in VIEWS:
            conn.execute(statement)
        from bill_pipeline.observations import _record
        cur=conn.execute('SELECT * FROM transactions')
        names=[c[0] for c in cur.description]
        for row in cur.fetchall():
            data=dict(zip(names,row))
            oid=_record(conn,data,None)
            conn.execute('INSERT INTO transaction_selection VALUES(?,?,?)',(data['source'],data['tx_id'],oid))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
