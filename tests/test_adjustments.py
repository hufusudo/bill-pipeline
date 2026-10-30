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


def test_simple_aa_return_and_undo_are_atomic(ledger):
    from bill_pipeline.adjustments import record_return,undo_return
    c,key=ledger
    change=record_return(c,'aa',key('星光球馆'),key('爸爸'),1000)
    assert month_totals(c,'2026-10')==(7550,127800)
    undo_return(c,change)
    assert month_totals(c,'2026-10')==(8550,128800)
    with pytest.raises(ValueError):record_return(c,'aa',key('星光球馆'),key('爸爸'),999999)
    assert c.execute('SELECT count(*) FROM advance_groups WHERE revoked_at IS NULL').fetchone()[0]==0


def test_simple_aa_additional_receipt_updates_own_share(ledger):
    from bill_pipeline.adjustments import record_return
    c,key=ledger
    record_return(c,'aa',key('星光球馆'),key('爸爸'),1000)
    record_return(c,'aa',key('星光球馆'),key('亲戚'),500)
    assert month_totals(c,'2026-10')==(7050,127300)
    repeated=record_return(c,'aa',key('星光球馆'),key('亲戚'),500)
    assert not repeated['changed']
    assert month_totals(c,'2026-10')==(7050,127300)


def test_simple_return_rolls_back_group_on_write_failure(ledger):
    import sqlite3
    from bill_pipeline.adjustments import record_return
    c,key=ledger
    c.execute("CREATE TRIGGER fail_return BEFORE INSERT ON repayment_allocations BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):record_return(c,'aa',key('星光球馆'),key('爸爸'),1000)
    assert c.execute('SELECT count(*) FROM advance_groups').fetchone()[0]==0
    assert month_totals(c,'2026-10')==(8550,128800)


def test_refund_through_unified_entry_can_be_undone(ledger):
    from bill_pipeline.adjustments import record_return,undo_return
    c,key=ledger
    change=record_return(c,'refund',key('星光球馆'),None,500)
    assert month_totals(c,'2026-10')[0]==8050
    undo_return(c,change)
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


def test_linked_refund_receipt_is_not_income_and_invalidates_repayment(ledger):
    from bill_pipeline.adjustments import create_advance,allocate_repayment,confirm_refund
    c,key=ledger
    gid=create_advance(c,key('星光球馆'),1000)
    allocate_repayment(c,gid,key('爸爸'),3000)
    confirm_refund(c,key('食堂一楼'),key('爸爸'),1000)
    assert month_totals(c,'2026-10')==(7550,127800)


def test_review_resolution_survives_identical_reimport(ledger,tmp_path):
    c,key=ledger
    with c:c.execute("UPDATE review_issues SET resolved_at='confirmed'")
    import_bill(c,write_wechat_xlsx(tmp_path/'again.xlsx'),'again.xlsx')
    assert c.execute('SELECT count(*) FROM review_issues WHERE resolved_at IS NULL').fetchone()[0]==0


def test_confirmed_identity_change_invalidates_manual_adjustments(ledger,tmp_path):
    from bill_pipeline.adjustments import set_transaction_categories,create_advance
    from bill_pipeline.observations import observe_import,select_observation
    from bill_pipeline.pipeline import read_bill
    from bill_pipeline.rules import apply_rules
    c,key=ledger
    create_advance(c,key('星光球馆'),1000)
    set_transaction_categories(c,key('星光球馆'),[('运动',1000)])
    bill=read_bill(write_wechat_xlsx(tmp_path/'new.xlsx'),'new.xlsx')
    bill.rows.loc[bill.rows.counterparty=='星光球馆','counterparty']='另一家演示商户'
    observe_import(c,bill,apply_rules(bill.rows),'new.xlsx')
    oid=c.execute("SELECT id FROM transaction_observations WHERE payload_json LIKE '%另一家演示商户%'").fetchone()[0]
    select_observation(c,oid)
    assert month_totals(c,'2026-10')[0]==8550
    assert ('运动',1000) not in month_by_category(c,'2026-10')


def test_identity_change_requires_refund_recheck(ledger,tmp_path):
    from bill_pipeline.adjustments import confirm_refund
    from bill_pipeline.observations import observe_import,select_observation
    from bill_pipeline.pipeline import read_bill
    from bill_pipeline.rules import apply_rules
    c,key=ledger
    confirm_refund(c,key('星光球馆'),None,500)
    bill=read_bill(write_wechat_xlsx(tmp_path/'changed.xlsx'),'changed.xlsx')
    bill.rows.loc[bill.rows.counterparty=='星光球馆','counterparty']='新的演示商户'
    observe_import(c,bill,apply_rules(bill.rows),'changed.xlsx')
    oid=c.execute("SELECT id FROM transaction_observations WHERE payload_json LIKE '%新的演示商户%'").fetchone()[0]
    select_observation(c,oid)
    assert month_totals(c,'2026-10')[0]==8550
