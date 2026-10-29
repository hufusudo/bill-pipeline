from pathlib import Path

from streamlit.testing.v1 import AppTest

from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_with_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BILL_DB", str(tmp_path / "t.db"))
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert at.title[0].value == "账单流水线"


def test_app_shows_month_report(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    import_bill(connect(db_path), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    monkeypatch.setenv("BILL_DB", str(db_path))
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert at.selectbox(key="month").value == "2026-10"
    assert at.metric[0].value == "85.50 元"
