from bill_pipeline.assistant_state import Answer, Step, Turn, RunState, BUDGETS, history_messages


def test_budgets_and_independent_runs():
    assert (BUDGETS['quick'].max_batches, BUDGETS['quick'].query_seconds) == (5, 60)
    assert (BUDGETS['deep'].max_batches, BUDGETS['deep'].query_seconds) == (15, 180)
    a, b = RunState(), RunState()
    a.cancel.set()
    assert not b.cancel.is_set() and a.events is not b.events
    assert Answer('ok', []).status == 'complete'


def test_history_limits_and_no_detail_leak():
    turns = [Turn('问' * 3000, '2026-10', Answer('答' * 7000, [
        Step('search_transactions', {}, {'totals': {'消费': '10.00'}, 'rows': [{'counterparty': '秘密姓名'}]})])) for _ in range(8)]
    messages = history_messages(turns)
    assert len(messages) == 12
    assert '秘密姓名' not in str(messages)
    assert all(len(m['content']) <= 11000 for m in messages)
    assert '截断' in str(messages) and '2026-10' in str(messages)
