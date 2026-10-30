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


async def test_review_preview_rejects_changed_database(user:User,tmp_path,monkeypatch):
    from bill_pipeline.adjustments import effective_transactions
    from bill_pipeline.migrations import bump_revision
    path=tmp_path/'review.db';monkeypatch.setenv('BILL_DB',str(path))
    c=connect(path);import_bill(c,write_wechat_xlsx(tmp_path/'bill.xlsx'),'bill.xlsx')
    index=next(i for i,t in enumerate(effective_transactions(c)) if t['counterparty']=='星光球馆')
    await user.open('/');user.find(marker='nav-review').click()
    await user.should_see(marker='review-transaction')
    user.find(marker='review-transaction').elements.pop().set_value(index)
    await user.should_see('星光球馆')
    user.find(marker='review-split').type('运动 40.00')
    user.find(marker='review-split-preview').click()
    await user.should_see('确认这次调整')
    with c:bump_revision(c)
    user.find(marker='review-confirm').click()
    await user.should_see('数据已变化，请重新预览')
    assert c.execute('SELECT count(*) FROM category_overrides').fetchone()[0]==0
    c.close()
