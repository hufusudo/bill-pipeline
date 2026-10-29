import io

import pytest

from bill_pipeline.alipay import read_alipay
from bill_pipeline.model import ROW_COLUMNS, BillError, Summary
from tests.fakes import write_alipay_csv


def test_read_alipay_gbk(tmp_path):
    bill = read_alipay(write_alipay_csv(tmp_path / "a.csv"))
    assert bill.source == "支付宝"
    assert (bill.period_start, bill.period_end) == ("2026-10-01 00:00:00", "2026-10-31 23:59:59")
    assert bill.summary == Summary(4, 0, 0, 3, 9550, 1, 6660)
    assert list(bill.rows.columns) == ROW_COLUMNS
    first = bill.rows.iloc[0]
    assert first.tx_id == "2026100122001000000000000001"
    assert (first.tx_time, first.tx_type, first.amount_cents) == ("2026-10-01 12:00:00", "餐饮美食", 1850)
    assert bill.rows.iloc[3].direction == "/"


def test_read_alipay_utf8(tmp_path):
    assert len(read_alipay(write_alipay_csv(tmp_path / "a.csv", encoding="utf-8-sig")).rows) == 4


def test_read_alipay_from_upload(tmp_path):
    data = write_alipay_csv(tmp_path / "a.csv").read_bytes()
    assert len(read_alipay(io.BytesIO(data)).rows) == 4


@pytest.mark.parametrize("kwargs, message", [
    ({"with_account_line": False}, "不是支付宝账单"),
    ({"summary_override": {"neutral": None}}, "说明行"),
])
def test_read_alipay_rejects_bad_files(tmp_path, kwargs, message):
    with pytest.raises(BillError, match=message):
        read_alipay(write_alipay_csv(tmp_path / "a.csv", **kwargs))


@pytest.mark.parametrize("data, message", [
    (b"\xff\xff\xff", "编码"),
    ("随便写的一行字".encode("gb18030"), "找不到表头"),
])
def test_read_alipay_rejects_unreadable(tmp_path, data, message):
    path = tmp_path / "a.csv"
    path.write_bytes(data)
    with pytest.raises(BillError, match=message):
        read_alipay(path)
