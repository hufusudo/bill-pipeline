import pytest
from bill_pipeline.db import connect,month_totals,month_by_category,category_transactions,find_transactions
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx


@pytest.fixture
def ledger(tmp_path):
    conn=connect(':memory:')
    import_bill(conn,write_wechat_xlsx(tmp_path/'bill.xlsx'),'bill.xlsx')
    def key(who):
        return conn.execute('SELECT source,tx_id FROM transactions WHERE counterparty=?',(who,)).fetchone()
    return conn,key


def test_refund_events_and_split_conserve_amounts(ledger):
    from bill_pipeline.adjustments import confirm_refund,set_transaction_categories,revoke_refund
    c,key=ledger
    event=confirm_refund(c,key('星光球馆'),None,1000)
    assert month_totals(c,'2026-10')[0]==7550
    set_transaction_categories(c,key('星光球馆'),[('运动',2000),('吃饭',1000)])
    assert sum(v for _,v in month_by_category(c,'2026-10'))==7550
    assert sum(r.counted_cents for r in find_transactions(c,category='运动'))==2000
    with pytest.raises(ValueError):set_transaction_categories(c,key('星光球馆'),[('运动',1)])
    revoke_refund(c,event)
    assert month_totals(c,'2026-10')[0]==8550


def test_advance_and_repayment(ledger):
    from bill_pipeline.adjustments import create_advance,allocate_repayment,revoke_advance
    c,key=ledger
    advance=create_advance(c,key('星光球馆'),1000)
    allocate_repayment(c,advance,key('爸爸'),3000)
    assert month_totals(c,'2026-10')==(5550,125800)
    with pytest.raises(ValueError):allocate_repayment(c,advance,key('爸爸'),1)
    revoke_advance(c,advance)
    assert month_totals(c,'2026-10')==(8550,128800)


def test_full_refund_does_not_double_deduct(ledger):
    from bill_pipeline.adjustments import confirm_refund
    c,key=ledger
    confirm_refund(c,key('某电商'),None,1000)
    assert month_totals(c,'2026-10')[0]==8550


def test_refund_invalidates_advance_and_income_allocation(ledger):
    from bill_pipeline.adjustments import create_advance,allocate_repayment,confirm_refund
    c,key=ledger
    advance=create_advance(c,key('星光球馆'),1000)
    allocate_repayment(c,advance,key('爸爸'),3000)
    confirm_refund(c,key('星光球馆'),None,500)
    assert month_totals(c,'2026-10')==(8050,128800)
