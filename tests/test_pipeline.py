import io

import pytest

from bill_pipeline.db import connect, month_totals
from bill_pipeline.model import BillError
from bill_pipeline.pipeline import import_bill
from bill_pipeline.validate import ReconLine
from tests.fakes import SAMPLE_ROWS, make_row, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.db")


def test_import_bill_end_to_end(conn, tmp_path):
    path = write_wechat_xlsx(tmp_path / "b.xlsx")
    report = import_bill(conn, path, "b.xlsx")
    assert (report.source, report.total, report.new, report.skipped, report.unknown) == ("微信", 9, 9, 0, 0)
    assert ReconLine("支出", "= 计入", 4, 8550) in report.recon
    again = import_bill(conn, path, "b.xlsx")
    assert (again.new, again.skipped) == (0, 9)


def test_import_bill_accepts_uploaded_bytes(conn, tmp_path):
    data = write_wechat_xlsx(tmp_path / "b.xlsx").read_bytes()
    assert import_bill(conn, io.BytesIO(data), "b.xlsx").new == 9


def test_rejected_bill_saves_nothing(conn, tmp_path):
    path = write_wechat_xlsx(tmp_path / "b.xlsx", summary_override={"expense": "支出：5笔 105.11元"})
    with pytest.raises(BillError):
        import_bill(conn, path, "b.xlsx")
    assert conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0


def test_unsupported_file_type(conn):
    with pytest.raises(BillError, match="只支持微信"):
        import_bill(conn, io.BytesIO(b"a,b"), "bill.csv")


def test_unknown_rows_are_imported_but_flagged(conn, tmp_path):
    rows = SAMPLE_ROWS + [make_row(10, 10, 10, "二手交易", "闲鱼买家", "收入", 30.0, "已收钱")]
    report = import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx", rows=rows), "b.xlsx")
    assert report.unknown == 1
    assert month_totals(conn, "2026-10") == (8550, 156400)


def test_empty_bill_imports_cleanly(conn, tmp_path):
    report = import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx", rows=[]), "b.xlsx")
    assert (report.total, report.new, report.skipped) == (0, 0, 0)
