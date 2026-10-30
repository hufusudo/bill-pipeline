import pytest
from nicegui.testing import User
from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx


async def test_review_controls_visible(user:User,tmp_path,monkeypatch):
    path=tmp_path/'b.db'
    monkeypatch.setenv('BILL_DB',str(path))
    c=connect(path)
    import_bill(c,write_wechat_xlsx(tmp_path/'bill.xlsx'),'bill.xlsx');c.close()
    await user.open('/')
    user.find(marker='nav-review').click()
    await user.should_see('交易核查与调整')
    await user.should_see('退款关联')
    await user.should_see('个人承担')
