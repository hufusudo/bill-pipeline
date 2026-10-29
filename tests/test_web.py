import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing import User

from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setenv("BILL_DB", str(path))
    return path


async def test_overview_empty(user: User, db):
    await user.open("/")
    await user.should_see("还没有导入账单")


async def test_overview_with_data(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    await user.should_see("10 月消费")
    await user.should_see("¥85.50")
    await user.should_see("71%")  # 列表里“未归类”的占比；“花得最多”画在图表内部，模拟测试看不到
    await user.should_see(kind=ui.echart)


async def test_trend_page_modes(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-trend").click()
    await user.should_see("花钱的节奏")
    await user.should_see("10-02 花得最多：¥40.00")
    user.find(marker="trend-mode").elements.pop().set_value("表格")
    await user.should_see("比上月")
    await user.should_see("¥85.50")


async def _upload(user: User, name: str, data: bytes) -> None:
    await user.should_see(marker="upload")  # 切页是后台重画，等上传组件真的出现
    upload = user.find(marker="upload").elements.pop()
    await upload.handle_uploads([SmallFileUpload(name=name, content_type="application/octet-stream", _data=data)])


async def test_upload_imports_file(user: User, db, tmp_path):
    await user.open("/")
    user.find(marker="nav-upload").click()
    await _upload(user, "b.xlsx", write_wechat_xlsx(tmp_path / "b.xlsx").read_bytes())
    await user.should_see("新增 9 笔 · 跳过 0 笔")
    await user.should_see("第三关：不重复")


async def test_upload_rejects_bad_file_but_keeps_others(user: User, db, tmp_path):
    await user.open("/")
    user.find(marker="nav-upload").click()
    await _upload(user, "bad.xlsx", b"not an excel file")
    await _upload(user, "b.xlsx", write_wechat_xlsx(tmp_path / "b.xlsx").read_bytes())
    await user.should_see("bad.xlsx 拒收")
    await user.should_see("新增 9 笔 · 跳过 0 笔")
