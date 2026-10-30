from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx


def test_coverage_uses_export_time_and_marks_gaps(tmp_path):
    from bill_pipeline.coverage import coverage,set_expected_sources
    c=connect(':memory:')
    import_bill(c,write_wechat_xlsx(tmp_path/'a.xlsx'),'a.xlsx')
    with c:c.execute("UPDATE imports SET exported_at='2026-10-20 09:00:00', export_scope='全部账单'")
    result=coverage(c,'2026-10-01 00:00:00','2026-10-31 23:59:59',['微信','支付宝'])
    assert not result['complete']
    assert result['sources']['微信']['intervals'][0][1]=='2026-10-20 09:00:00'
    assert result['sources']['支付宝']['gaps']
    set_expected_sources(c,['微信'])
    assert coverage(c,'2026-10-01 00:00:00','2026-10-10 23:59:59')['complete']
