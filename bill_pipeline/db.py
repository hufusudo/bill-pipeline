"""SQLite：建表、整份入库（事务 + 去重）、归类对照表、月报查询。"""
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from bill_pipeline.model import ParsedBill
from bill_pipeline.rules import CATEGORIES, EXPENSE, INCOME

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
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def save_import(conn: sqlite3.Connection, bill: ParsedBill, rows: pd.DataFrame,
                file_name: str) -> tuple[int, int]:
    """整份账单在一个事务里入库，中途出错就全部回滚。返回（新增笔数，跳过笔数）。"""
    # pandas 3 的字符串列把空值记成 NaN，这里统一换成 None，入库才是 NULL
    records = rows.astype(object).where(rows.notna(), None).to_dict("records")
    with conn:
        import_id = conn.execute(
            "INSERT INTO imports (file_name, source, period_start, period_end, imported_at, rows_total) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_name, bill.source, bill.period_start, bill.period_end,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(records)),
        ).lastrowid
        for record in records:
            record.update(source=bill.source, import_id=import_id)
        new = conn.executemany(INSERT_TX, records).rowcount if records else 0
        skipped = len(records) - new
        conn.execute("UPDATE imports SET rows_new = ?, rows_skipped = ? WHERE id = ?",
                     (new, skipped, import_id))
    return new, skipped


def unmapped_counterparties(conn: sqlite3.Connection) -> list[tuple[str, int, int]]:
    """还没归类的消费交易对方：（交易对方, 笔数, 计入金额），金额大的在前。"""
    return conn.execute("""
        SELECT t.counterparty, COUNT(*), SUM(t.counted_cents)
        FROM transactions t
        LEFT JOIN counterparty_categories m ON m.counterparty = t.counterparty
        WHERE t.result = ? AND t.category IS NULL AND m.category IS NULL
        GROUP BY t.counterparty
        ORDER BY SUM(t.counted_cents) DESC, t.counterparty
    """, (EXPENSE,)).fetchall()


def set_category(conn: sqlite3.Connection, counterparty: str, category: str) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"没有这个类别：{category}")
    with conn:
        conn.execute(
            "INSERT INTO counterparty_categories (counterparty, category) VALUES (?, ?) "
            "ON CONFLICT(counterparty) DO UPDATE SET category = excluded.category",
            (counterparty, category))


def months(conn: sqlite3.Connection) -> list[str]:
    return [month for (month,) in conn.execute(
        "SELECT DISTINCT substr(tx_time, 1, 7) AS month FROM transactions ORDER BY month DESC")]


def month_totals(conn: sqlite3.Connection, month: str) -> tuple[int, int]:
    """（消费计入合计, 收入计入合计），按交易时间算月份。"""
    return conn.execute("""
        SELECT COALESCE(SUM(CASE WHEN result = ? THEN counted_cents END), 0),
               COALESCE(SUM(CASE WHEN result = ? THEN counted_cents END), 0)
        FROM transactions WHERE substr(tx_time, 1, 7) = ?
    """, (EXPENSE, INCOME, month)).fetchone()


def month_by_category(conn: sqlite3.Connection, month: str) -> list[tuple[str, int]]:
    """这个月各类消费，金额大的在前。规则定的类别优先，其次是对照表，都没有就是未归类。"""
    return conn.execute("""
        SELECT COALESCE(t.category, m.category, ?) AS cat, SUM(t.counted_cents) AS cents
        FROM transactions t
        LEFT JOIN counterparty_categories m ON m.counterparty = t.counterparty
        WHERE t.result = ? AND substr(t.tx_time, 1, 7) = ?
        GROUP BY cat
        ORDER BY cents DESC, cat
    """, (UNCATEGORIZED, EXPENSE, month)).fetchall()
