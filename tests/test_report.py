import pytest

from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from bill_pipeline.report import change_ratio, month_reconciliation, previous_month
from bill_pipeline.validate import ReconLine
from tests.fakes import write_alipay_csv, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.db")


def test_previous_month():
    assert previous_month("2026-10") == "2026-09"
    assert previous_month("2026-01") == "2025-12"


def test_change_ratio():
    assert change_ratio(8550, 9500) == pytest.approx(-0.1)
    assert change_ratio(100, 0) is None


def test_month_reconciliation_matches_import(conn, tmp_path):
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    assert month_reconciliation(conn, "2026-10") == [
        ReconLine("支出", "平台合计", 5, 11230),
        ReconLine("支出", "减：全额退款的原交易", 1, 2680),
        ReconLine("支出", "= 计入", 4, 8550),
        ReconLine("收入", "平台合计", 3, 131480),
        ReconLine("收入", "减：退款", 1, 2680),
        ReconLine("收入", "= 计入", 2, 128800),
        ReconLine("中性交易", "平台合计", 1, 5050),
        ReconLine("中性交易", "减：中性交易", 1, 5050),
        ReconLine("中性交易", "= 计入", 0, 0),
    ]


def test_month_reconciliation_two_sources(conn, tmp_path):
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    import_bill(conn, write_alipay_csv(tmp_path / "a.csv"), "a.csv")
    lines = month_reconciliation(conn, "2026-10")
    assert ReconLine("支出", "平台合计", 8, 20780) in lines
    assert ReconLine("支出", "= 计入", 7, 18100) in lines
    assert ReconLine("中性交易", "平台合计", 2, 11710) in lines


def test_month_reconciliation_empty_month(conn):
    assert month_reconciliation(conn, "2026-10") == [
        ReconLine("支出", "平台合计", 0, 0), ReconLine("支出", "= 计入", 0, 0),
        ReconLine("收入", "平台合计", 0, 0), ReconLine("收入", "= 计入", 0, 0),
        ReconLine("中性交易", "平台合计", 0, 0), ReconLine("中性交易", "= 计入", 0, 0),
    ]
