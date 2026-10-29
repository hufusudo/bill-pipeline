import sqlite3
from datetime import datetime

import pytest

from bill_pipeline.db import (add_category, categories, categorized, category_transactions, connect, daily_expense,
                              import_history,
                              mapped_counterparties, month_by_category, month_totals, months, recent_months,
                              reclassify_unknown, save_import,
                              set_category, unmapped_counterparties)
from bill_pipeline.report import month_reconciliation
from bill_pipeline.rules import EXPENSE, KNOWN, apply_rules
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
    assert unmapped_counterparties(conn) == [
        ("星光球馆", 1, 4000, "微信", "商户消费", "2026-10-02 19:00:00", "/"),
        ("食堂一楼", 1, 1250, "微信", "商户消费", "2026-10-01 12:00:00", "/"),
        ("张阿姨", 1, 800, "微信", "扫二维码付款", "2026-10-03 08:00:00", "/"),
    ]
    assert ("未归类", 6050) in month_by_category(conn, "2026-10")
    set_category(conn, "星光球馆", "运动")
    set_category(conn, "食堂一楼", "吃饭")
    set_category(conn, "张阿姨", "吃饭")
    assert unmapped_counterparties(conn) == []
    mapped = mapped_counterparties(conn)
    assert [(card.counterparty, category) for card, category in mapped] == [
        ("星光球馆", "运动"), ("食堂一楼", "吃饭"), ("张阿姨", "吃饭")]
    assert mapped[0][0] == ("星光球馆", 1, 4000, "微信", "商户消费", "2026-10-02 19:00:00", "/")
    assert months(conn) == ["2026-10"]
    assert month_totals(conn, "2026-10") == (8550, 128800)
    assert month_by_category(conn, "2026-10") == [("运动", 4000), ("其他", 2500), ("吃饭", 2050)]


def test_set_category_rejects_unknown(conn):
    with pytest.raises(ValueError):
        set_category(conn, "某店", "零食")


def test_daily_expense(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    days = daily_expense(conn, "2026-10")
    assert days[:4] == [("2026-10-01", 1250), ("2026-10-02", 4000), ("2026-10-03", 3300), ("2026-10-04", 0)]
    assert len(days) == 9
    assert daily_expense(conn, "2026-09") == []


def test_recent_months_and_history(conn, tmp_path):
    september = dict(make_row(11, 1, 9, "商户消费", "食堂一楼", "支出", 10.0, "支付成功"),
                     **{"交易时间": datetime(2026, 9, 30, 12)})
    for name, rows in (("b.xlsx", SAMPLE_ROWS), ("c.xlsx", [september])):
        bill, prepared = _prepared(tmp_path, name, rows=rows)
        save_import(conn, bill, prepared, name)
    assert recent_months(conn) == [("2026-09", 1000), ("2026-10", 8550)]
    assert [h[0] for h in import_history(conn)] == ["c.xlsx", "b.xlsx"]
    assert import_history(conn)[0][4:] == (1, 0)


def test_categorized_and_category_transactions(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    assert len(category_transactions(conn, "2026-10", "未归类")) == 3
    set_category(conn, "星光球馆", "运动")
    set_category(conn, "食堂一楼", "吃饭")
    set_category(conn, "张阿姨", "吃饭")
    assert categorized(conn) == [("星光球馆", "运动", 1, 4000), ("食堂一楼", "吃饭", 1, 1250), ("张阿姨", "吃饭", 1, 800)]
    assert category_transactions(conn, "2026-10", "吃饭") == [
        ("2026-10-03 08:00:00", "张阿姨", "/", 800), ("2026-10-01 12:00:00", "食堂一楼", "/", 1250)]
    assert category_transactions(conn, "2026-10", "其他") == [("2026-10-03 21:00:00", "球友A", "/", 2500)]


def test_default_categories(conn, tmp_path):
    assert categories(conn) == ["吃饭", "运动", "购物", "交通", "娱乐", "其他"]
    assert categories(connect(tmp_path / "data" / "t.db")) == ["吃饭", "运动", "购物", "交通", "娱乐", "其他"]


@pytest.mark.parametrize("name, message", [
    ("  ", "分类名不能为空"), ("一二三四五六七八九", "分类名最多 8 个字"),
    ("吃饭", "已经有这个分类了"), ("未归类", "保留的名字"),
])
def test_add_category_errors(conn, name, message):
    with pytest.raises(ValueError, match=message):
        add_category(conn, name)


def test_add_category_and_use_it(conn, tmp_path):
    assert add_category(conn, " 宠物 ") == "宠物"
    assert categories(conn)[-1] == "宠物"
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    set_category(conn, "星光球馆", "宠物")
    assert ("宠物", 4000) in month_by_category(conn, "2026-10")


def test_reclassify_unknown_after_adding_a_rule(conn, tmp_path, monkeypatch):
    rows = SAMPLE_ROWS + [make_row(10, 10, 12, "某新类型", "某商户", "支出", 30.0, "支付成功")]
    bill, prepared = _prepared(tmp_path, rows=rows)
    save_import(conn, bill, prepared, "b.xlsx")
    assert month_totals(conn, "2026-10")[0] == 8550  # 没见过的那笔先不算
    monkeypatch.setitem(KNOWN, ("支出", "某新类型", "支付成功"), (EXPENSE, "消费", None))  # 补上规则
    assert reclassify_unknown(conn) == 1
    assert month_totals(conn, "2026-10")[0] == 8550 + 3000
    month_reconciliation(conn, "2026-10")  # 改完以后月度对账照样平，不平会抛错
    assert reclassify_unknown(conn) == 0
