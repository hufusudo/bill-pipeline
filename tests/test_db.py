import sqlite3

import pytest

from bill_pipeline.db import (connect, month_by_category, month_totals, months, save_import,
                              set_category, unmapped_counterparties)
from bill_pipeline.rules import apply_rules
from bill_pipeline.wechat import read_wechat
from tests.fakes import SAMPLE_ROWS, make_row, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "data" / "t.db")


def _prepared(tmp_path, name="b.xlsx", **kwargs):
    bill = read_wechat(write_wechat_xlsx(tmp_path / name, **kwargs))
    return bill, apply_rules(bill.rows)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_save_import_and_reimport(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    assert save_import(conn, bill, rows, "b.xlsx") == (9, 0)
    assert save_import(conn, bill, rows, "b.xlsx") == (0, 9)
    assert _count(conn, "transactions") == 9
    assert _count(conn, "imports") == 2


def test_overlapping_export(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    later = SAMPLE_ROWS[4:] + [make_row(10, 20, 12, "商户消费", "食堂一楼", "支出", 15.0, "支付成功")]
    bill2, rows2 = _prepared(tmp_path, "c.xlsx", rows=later)
    assert save_import(conn, bill2, rows2, "c.xlsx") == (1, 5)


def test_save_import_is_all_or_nothing(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    rows.loc[rows.index[-1], "tx_id"] = None  # 最后一行违反 NOT NULL
    with pytest.raises(sqlite3.IntegrityError):
        save_import(conn, bill, rows, "b.xlsx")
    assert _count(conn, "transactions") == 0
    assert _count(conn, "imports") == 0


def test_categories_and_month_report(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    assert unmapped_counterparties(conn) == [("星光球馆", 1, 4000), ("食堂一楼", 1, 1250), ("张阿姨", 1, 800)]
    assert ("未归类", 6050) in month_by_category(conn, "2026-10")
    set_category(conn, "星光球馆", "运动")
    set_category(conn, "食堂一楼", "吃饭")
    set_category(conn, "张阿姨", "吃饭")
    assert unmapped_counterparties(conn) == []
    assert months(conn) == ["2026-10"]
    assert month_totals(conn, "2026-10") == (8550, 156400)
    assert month_by_category(conn, "2026-10") == [("运动", 4000), ("其他", 2500), ("吃饭", 2050)]


def test_set_category_rejects_unknown(conn):
    with pytest.raises(ValueError):
        set_category(conn, "某店", "零食")
