"""SQLite：建表、整份入库（事务 + 去重）、归类对照表、月报查询。"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from bill_pipeline.model import ParsedBill
from bill_pipeline.rules import DEFAULT_CATEGORIES, EXPENSE, INCOME, PERSON_TYPES, UNKNOWN, classify

UNCATEGORIZED = "未归类"

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    source TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    rows_total INTEGER NOT NULL,
    rows_new INTEGER,
    rows_skipped INTEGER
);
CREATE TABLE IF NOT EXISTS transactions (
    source TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    tx_time TEXT NOT NULL,
    tx_type TEXT NOT NULL,
    counterparty TEXT NOT NULL,
    item TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    merchant_order TEXT NOT NULL,
    note TEXT NOT NULL,
    result TEXT NOT NULL,
    reason TEXT NOT NULL,
    category TEXT,
    counted_cents INTEGER NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    PRIMARY KEY (source, tx_id)
);
CREATE TABLE IF NOT EXISTS counterparty_categories (
    counterparty TEXT PRIMARY KEY,
    category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_suggestions (
    counterparty TEXT PRIMARY KEY,
    suggested TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    chosen TEXT
);
"""

TX_COLUMNS = [
    "source", "tx_id", "tx_time", "tx_type", "counterparty", "item", "direction", "amount_cents",
    "method", "status", "merchant_order", "note", "result", "reason", "category", "counted_cents",
    "import_id",
]
# 只对 (source, tx_id) 冲突跳过；不用 INSERT OR IGNORE，它会把 NOT NULL 违规也悄悄跳过
INSERT_TX = (f"INSERT INTO transactions ({', '.join(TX_COLUMNS)}) "
             f"VALUES ({', '.join(':' + c for c in TX_COLUMNS)}) "
             "ON CONFLICT(source, tx_id) DO NOTHING")


def connect(path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    existed = str(path) != ":memory:" and Path(path).exists() and Path(path).stat().st_size > 0
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    from bill_pipeline.migrations import migrate
    if existed:
        migrate(conn, Path(path)) if conn.execute("SELECT 1 FROM sqlite_master WHERE name='transactions'").fetchone() else None
    conn.executescript(SCHEMA)
    migrate(conn, None)
    with conn:
        conn.executemany("INSERT OR IGNORE INTO categories (name, position) VALUES (?, ?)",
                         [(name, i) for i, name in enumerate(DEFAULT_CATEGORIES, start=1)])
    return conn


def save_import(conn: sqlite3.Connection, bill: ParsedBill, rows: pd.DataFrame,
                file_name: str) -> tuple[int, int]:
    """整份账单在一个事务里入库，中途出错就全部回滚。返回（新增笔数，跳过笔数）。"""
    from bill_pipeline.observations import observe_import
    changes = observe_import(conn, bill, rows, file_name)
    return changes.new, changes.duplicate


def reclassify_unknown(conn: sqlite3.Connection) -> int:
    """用现在的规则重新判断库里“未识别”的交易，返回改了几笔。补了规则以后，旧数据靠它跟着更新。"""
    changed = []
    for source, tx_id, direction, tx_type, status, cents in conn.execute(
            "SELECT source, tx_id, direction, tx_type, status, amount_cents FROM transactions WHERE result = ?",
            (UNKNOWN,)).fetchall():
        c = classify(direction, tx_type, status, cents, source=source)
        if c.result != UNKNOWN:
            changed.append((c.result, c.reason, c.category, c.counted_cents, source, tx_id))
    with conn:
        conn.executemany("UPDATE transactions SET result = ?, reason = ?, category = ?, counted_cents = ? "
                         "WHERE source = ? AND tx_id = ?", changed)
    return len(changed)


class Card(NamedTuple):
    """一个还没归类的交易对方，带上最近一笔的提示。"""
    counterparty: str
    count: int
    cents: int
    source: str
    tx_type: str
    last_time: str
    item: str


def _cards(conn: sqlite3.Connection, mapped: bool) -> list[tuple]:
    """消费交易对方的卡片，最后多一列用户选的类别。mapped 为真时只要归过类的，否则只要没归过类的。"""
    return conn.execute(f"""
        SELECT t.counterparty, COUNT(*), SUM(t.counted_cents),
               (SELECT x.source FROM effective_transactions x WHERE x.counterparty = t.counterparty
                AND x.result = :expense AND (SELECT category FROM transactions raw WHERE raw.source=x.source AND raw.tx_id=x.tx_id) IS NULL ORDER BY x.tx_time DESC LIMIT 1),
               (SELECT x.tx_type FROM effective_transactions x WHERE x.counterparty = t.counterparty
                AND x.result = :expense AND (SELECT category FROM transactions raw WHERE raw.source=x.source AND raw.tx_id=x.tx_id) IS NULL ORDER BY x.tx_time DESC LIMIT 1),
               MAX(t.tx_time),
               (SELECT x.item FROM effective_transactions x WHERE x.counterparty = t.counterparty
                AND x.result = :expense AND (SELECT category FROM transactions raw WHERE raw.source=x.source AND raw.tx_id=x.tx_id) IS NULL ORDER BY x.tx_time DESC LIMIT 1),
               m.category
        FROM effective_transactions t
        LEFT JOIN counterparty_categories m ON m.counterparty = t.counterparty
        WHERE t.result = :expense AND (SELECT category FROM transactions raw WHERE raw.source=t.source AND raw.tx_id=t.tx_id) IS NULL AND m.category IS {"NOT NULL" if mapped else "NULL"}
        GROUP BY t.counterparty
        ORDER BY SUM(t.counted_cents) DESC, t.counterparty
    """, {"expense": EXPENSE}).fetchall()


def unmapped_counterparties(conn: sqlite3.Connection) -> list[Card]:
    """还没归类的消费交易对方，金额大的在前；附上最近一笔的来源、类型和时间。"""
    return [Card(*row[:-1]) for row in _cards(conn, mapped=False)]


def mapped_counterparties(conn: sqlite3.Connection) -> list[tuple[Card, str]]:
    """用户归过类的消费交易对方，以及用户选的类别；评测分类建议时拿来当标准答案。"""
    return [(Card(*row[:-1]), row[-1]) for row in _cards(conn, mapped=True)]


def categorized(conn: sqlite3.Connection) -> list[tuple[str, str, int, int]]:
    """已经归过类的交易对方：（交易对方, 类别, 笔数, 金额），金额大的在前。"""
    return conn.execute("""
        SELECT m.counterparty, m.category, COUNT(t.tx_id), COALESCE(SUM(t.counted_cents), 0)
        FROM counterparty_categories m
        LEFT JOIN effective_transactions t ON t.counterparty = m.counterparty AND t.result = ? AND (SELECT category FROM transactions raw WHERE raw.source=t.source AND raw.tx_id=t.tx_id) IS NULL
        GROUP BY m.counterparty, m.category
        ORDER BY 4 DESC, m.counterparty
    """, (EXPENSE,)).fetchall()


def set_category(conn: sqlite3.Connection, counterparty: str, category: str) -> None:
    if category not in categories(conn):
        raise ValueError(f"没有这个类别：{category}")
    with conn:
        conn.execute(
            "INSERT INTO counterparty_categories (counterparty, category) VALUES (?, ?) "
            "ON CONFLICT(counterparty) DO UPDATE SET category = excluded.category",
            (counterparty, category))
        conn.execute("UPDATE ai_suggestions SET chosen = ? WHERE counterparty = ?", (category, counterparty))
        from bill_pipeline.migrations import bump_revision
        bump_revision(conn)


class Found(NamedTuple):
    """查明细查到的一笔交易；分类只有消费才有。"""
    tx_time: str
    counterparty: str
    item: str
    direction: str
    amount_cents: int
    counted_cents: int
    result: str
    reason: str
    category: str | None


def find_transactions(conn: sqlite3.Connection, month: str | None = None, category: str | None = None,
                      keyword: str | None = None, *,
                      start_date: str | None = None, end_date: str | None = None) -> list[Found]:
    """按月份、分类、关键词（匹配交易对方和商品）查明细，是 None 的条件不限。晚的在前。"""
    rows = conn.execute("""
        SELECT t.tx_time, t.counterparty, t.item, t.direction, t.amount_cents, CASE WHEN :category IS NOT NULL THEN (SELECT a.counted_cents FROM effective_allocations a WHERE a.source=t.source AND a.tx_id=t.tx_id AND a.category=:category) ELSE t.counted_cents END, t.result, t.reason,
               CASE WHEN t.result = :expense THEN COALESCE(t.category, m.category, :uncat) END
        FROM effective_transactions t
        LEFT JOIN counterparty_categories m ON m.counterparty = t.counterparty
        WHERE (:month IS NULL OR substr(t.tx_time, 1, 7) = :month)
          AND (:category IS NULL OR (t.result = :expense AND EXISTS(SELECT 1 FROM effective_allocations a WHERE a.source=t.source AND a.tx_id=t.tx_id AND a.category=:category)))
          AND (:keyword IS NULL OR t.counterparty LIKE '%' || :keyword || '%' OR t.item LIKE '%' || :keyword || '%')
        AND (:start IS NULL OR substr(t.tx_time, 1, 10) >= :start)
          AND (:end IS NULL OR substr(t.tx_time, 1, 10) <= :end)
        ORDER BY t.tx_time DESC, t.source, t.tx_id
    """, {"start": start_date, "end": end_date, "expense": EXPENSE, "uncat": UNCATEGORIZED, "month": month, "category": category,
          "keyword": keyword}).fetchall()
    return [Found(*row) for row in rows]


def person_counterparties(conn: sqlite3.Connection) -> set[str]:
    """有过转账、红包、扫个人二维码这类交易的交易对方，也就是真人。"""
    marks = ", ".join("?" * len(PERSON_TYPES))
    return {name for (name,) in conn.execute(
        f"SELECT DISTINCT counterparty FROM effective_transactions WHERE tx_type IN ({marks})", sorted(PERSON_TYPES))}


def month_by_counterparty(conn: sqlite3.Connection, month: str) -> list[tuple[str, int, int]]:
    """这个月每个交易对方的消费：（交易对方, 笔数, 金额），金额大的在前。"""
    return conn.execute("""
        SELECT counterparty, COUNT(*), SUM(counted_cents) FROM effective_transactions
        WHERE result = ? AND substr(tx_time, 1, 7) = ?
        GROUP BY counterparty ORDER BY 3 DESC, counterparty
    """, (EXPENSE, month)).fetchall()


def months(conn: sqlite3.Connection) -> list[str]:
    return [month for (month,) in conn.execute(
        "SELECT DISTINCT substr(tx_time, 1, 7) AS month FROM effective_transactions ORDER BY month DESC")]


def month_totals(conn: sqlite3.Connection, month: str) -> tuple[int, int]:
    """（消费计入合计, 收入计入合计），按交易时间算月份。"""
    return conn.execute("""
        SELECT COALESCE(SUM(CASE WHEN result = ? THEN counted_cents END), 0),
               COALESCE(SUM(CASE WHEN result = ? THEN counted_cents END), 0)
        FROM effective_transactions WHERE substr(tx_time, 1, 7) = ?
    """, (EXPENSE, INCOME, month)).fetchone()


def month_by_category(conn,month):
    return conn.execute("SELECT a.category,SUM(a.counted_cents) FROM effective_allocations a JOIN transactions t USING(source,tx_id) WHERE substr(t.tx_time,1,7)=? GROUP BY a.category ORDER BY 2 DESC,a.category",(month,)).fetchall()


def category_transactions(conn,month,category):
    return conn.execute("SELECT t.tx_time,t.counterparty,t.item,a.counted_cents FROM effective_allocations a JOIN transactions t USING(source,tx_id) WHERE substr(t.tx_time,1,7)=? AND a.category=? ORDER BY t.tx_time DESC,t.source,t.tx_id",(month,category)).fetchall()


def daily_expense(conn: sqlite3.Connection, month: str) -> list[tuple[str, int]]:
    """这个月每天的消费：从 1 号排到最后一笔交易那天，没有消费的日子记 0。"""
    last = conn.execute("SELECT MAX(substr(tx_time, 1, 10)) FROM effective_transactions WHERE substr(tx_time, 1, 7) = ?",
                        (month,)).fetchone()[0]
    if last is None:
        return []
    spent = dict(conn.execute("""
        SELECT substr(tx_time, 1, 10), SUM(counted_cents) FROM effective_transactions
        WHERE result = ? AND substr(tx_time, 1, 7) = ? GROUP BY 1
    """, (EXPENSE, month)).fetchall())
    days = (f"{month}-{d:02d}" for d in range(1, int(last[8:10]) + 1))
    return [(day, spent.get(day, 0)) for day in days]


def recent_months(conn: sqlite3.Connection, n: int = 6) -> list[tuple[str, int]]:
    """最近 n 个有交易的月份，以及每月的消费，按时间从早到晚。"""
    rows = conn.execute("""
        SELECT substr(tx_time, 1, 7) AS month, COALESCE(SUM(CASE WHEN result = ? THEN counted_cents END), 0)
        FROM effective_transactions GROUP BY month ORDER BY month DESC LIMIT ?
    """, (EXPENSE, n)).fetchall()
    return rows[::-1]


def import_history(conn: sqlite3.Connection, limit: int = 5) -> list[tuple[str, str, str, str, int, int]]:
    """最近几次导入：（文件名, 来源, 开始, 结束, 新增, 跳过），最新的在前。"""
    return conn.execute("""
        SELECT file_name, source, period_start, period_end, rows_new, rows_skipped
        FROM imports ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()


def month_rows(conn: sqlite3.Connection, month: str) -> pd.DataFrame:
    """这个月的明细里对账要用的几列。"""
    return pd.read_sql_query(
        "SELECT direction, amount_cents, counted_cents, result, reason FROM transactions "
        "WHERE substr(tx_time, 1, 7) = ?", conn, params=(month,))


def categories(conn: sqlite3.Connection) -> list[str]:
    """当前的分类，按添加顺序。"""
    return [name for (name,) in conn.execute("SELECT name FROM categories ORDER BY position")]


def add_category(conn: sqlite3.Connection, name: str) -> str:
    """添加一个新分类，排在最后；返回去掉首尾空白后的名字。"""
    name = name.strip()
    if not name:
        raise ValueError("分类名不能为空")
    if len(name) > 8:
        raise ValueError("分类名最多 8 个字")
    if name == UNCATEGORIZED:
        raise ValueError("“未归类”是保留的名字")
    if name in categories(conn):
        raise ValueError("已经有这个分类了")
    with conn:
        conn.execute("INSERT INTO categories (name, position) "
                     "VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM categories))", (name,))
        from bill_pipeline.migrations import bump_revision
        bump_revision(conn)
    return name


def save_suggestions(conn: sqlite3.Connection, mapping: dict[str, str], model: str) -> None:
    """存下 AI 的建议；同一个交易对方再建议一次就覆盖，并清掉旧的选择。

    分类是空字符串表示问过了、AI 没把握：记下来，下次就不再问它。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.executemany(
            "INSERT INTO ai_suggestions (counterparty, suggested, model, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(counterparty) DO UPDATE SET suggested = excluded.suggested, model = excluded.model, "
            "created_at = excluded.created_at, chosen = NULL",
            [(name, category, model, now) for name, category in mapping.items()])


def asked_counterparties(conn: sqlite3.Connection) -> set[str]:
    """问过 AI 的交易对方，不管它给没给建议。"""
    return {name for (name,) in conn.execute("SELECT counterparty FROM ai_suggestions")}


def suggestions(conn: sqlite3.Connection) -> dict[str, str]:
    """还没被确认的 AI 建议：{交易对方: 建议的分类}。"""
    return dict(conn.execute(
        "SELECT counterparty, suggested FROM ai_suggestions WHERE chosen IS NULL AND suggested != ''"))


def ai_accuracy(conn: sqlite3.Connection) -> tuple[int, int]:
    """（AI 猜对的条数, 用户确认过的条数）。AI 没给建议的不算。"""
    hits, decided = conn.execute(
        "SELECT COALESCE(SUM(chosen = suggested), 0), COUNT(chosen) FROM ai_suggestions "
        "WHERE suggested != ''").fetchone()
    return hits, decided
