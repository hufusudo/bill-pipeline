import pytest

from bill_pipeline.model import ROW_COLUMNS, BillError, Summary
from bill_pipeline.wechat import read_wechat
from tests.fakes import SAMPLE_ROWS, write_wechat_xlsx


def test_read_wechat_summary_period_and_rows(tmp_path):
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx"))
    assert bill.source == "微信"
    assert (bill.period_start, bill.period_end) == ("2026-10-01 00:00:00", "2026-10-31 23:59:59")
    assert bill.summary == Summary(count=9, income_count=3, income_cents=158360,
                                   expense_count=5, expense_cents=10510,
                                   neutral_count=1, neutral_cents=8008)
    assert list(bill.rows.columns) == ROW_COLUMNS
    assert len(bill.rows) == 9
    first = bill.rows.iloc[0]
    assert first.tx_time == "2026-10-01 12:00:00"
    assert first.amount_cents == 1250
    assert first.counterparty == "食堂一楼"
    assert first.tx_id == "4200000000202610000000000001"


def test_read_wechat_excel_serial_dates(tmp_path):
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", time_as="serial"))
    assert bill.rows.iloc[0].tx_time == "2026-10-01 12:00:00"


def test_read_wechat_strips_text_and_skips_blank_rows(tmp_path):
    rows = [dict(SAMPLE_ROWS[0], **{"交易对方": "  食堂一楼  "})] + SAMPLE_ROWS[1:]
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", rows, blank_rows_after=2))
    assert len(bill.rows) == 9
    assert bill.rows.iloc[0].counterparty == "食堂一楼"


def test_read_wechat_empty_bill(tmp_path):
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", rows=[]))
    assert bill.summary.count == 0
    assert bill.rows.empty
    assert list(bill.rows.columns) == ROW_COLUMNS


@pytest.mark.parametrize("kwargs, message", [
    ({"title": "支付宝交易明细"}, "不是微信账单"),
    ({"drop_columns": ("交易时间",)}, "找不到表头"),
    ({"drop_columns": ("交易单号",)}, "交易单号"),
    ({"summary_override": {"expense": None}}, "说明行"),
])
def test_read_wechat_rejects_bad_files(tmp_path, kwargs, message):
    with pytest.raises(BillError, match=message):
        read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", **kwargs))


def test_read_wechat_rejects_non_xlsx(tmp_path):
    path = tmp_path / "b.xlsx"
    path.write_bytes(b"not an excel file")
    with pytest.raises(BillError, match="打不开"):
        read_wechat(path)


def test_read_wechat_rejects_numeric_tx_id(tmp_path):
    rows = [dict(SAMPLE_ROWS[0], **{"交易单号": 4.2e27})] + SAMPLE_ROWS[1:]
    with pytest.raises(BillError, match="交易单号不是文字"):
        read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", rows))
