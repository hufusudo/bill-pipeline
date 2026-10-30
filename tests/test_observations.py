from dataclasses import replace
from bill_pipeline.db import connect, save_import, month_totals
from bill_pipeline.pipeline import read_bill
from bill_pipeline.rules import apply_rules
from tests.fakes import write_wechat_xlsx


def test_status_sync_and_old_export_cannot_restore_expense(tmp_path):
    conn = connect(':memory:')
    bill = read_bill(write_wechat_xlsx(tmp_path/'a.xlsx'), 'a.xlsx')
    bill.exported_at = '2026-10-20 12:00:00'
    save_import(conn, bill, apply_rules(bill.rows), 'a.xlsx')
    updated = replace(bill, rows=bill.rows.copy(), exported_at='2026-10-30 12:00:00')
    updated.rows.loc[updated.rows.counterparty=='星光球馆','status']='已全额退款'
    save_import(conn, updated, apply_rules(updated.rows), 'b.xlsx')
    assert month_totals(conn,'2026-10')[0] == 4550
    save_import(conn, bill, apply_rules(bill.rows), 'old.xlsx')
    assert month_totals(conn,'2026-10')[0] == 4550
    assert conn.execute('SELECT count(*) FROM transaction_observations').fetchone()[0] == 10


def test_fact_change_is_conflict(tmp_path):
    conn = connect(':memory:')
    bill = read_bill(write_wechat_xlsx(tmp_path/'a.xlsx'), 'a.xlsx')
    save_import(conn,bill,apply_rules(bill.rows),'a.xlsx')
    changed=replace(bill,rows=bill.rows.copy())
    changed.rows.loc[changed.rows.counterparty=='星光球馆','amount_cents']=9000
    save_import(conn,changed,apply_rules(changed.rows),'b.xlsx')
    assert month_totals(conn,'2026-10')[0] == 8550
    assert conn.execute("SELECT count(*) FROM review_issues WHERE kind='快照冲突' AND resolved_at IS NULL").fetchone()[0] == 1
