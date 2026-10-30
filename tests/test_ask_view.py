from web.ask import AskSession, comparison_view, evidence_cards
from bill_pipeline.assistant_state import Answer, RunState, Step


def test_only_structured_successful_data_becomes_metrics():
    text_only = Answer('本月花了 ¥999.00', [])
    assert comparison_view(text_only) is None
    failed = Answer('', [Step('compare_months', {}, {'error': '缺数据'})])
    assert comparison_view(failed) is None and not evidence_cards(failed)
    actual = {'base': {'expense': '10.00'}, 'target': {'expense': '20.00'}}
    assert comparison_view(Answer('', [Step('compare_months', {}, actual)])) == actual


def test_stop_invalidates_run_and_clear_removes_history():
    session = AskSession()
    state = RunState()
    session.active_run = state
    session.current_question = '查数'
    session.current_steps = [Step('list_months', {}, {'months': []})]
    session.stop()
    assert state.cancel.is_set() and session.active_run is None
    assert session.turns[-1].answer.status == 'cancelled'
    assert len(session.turns[-1].answer.steps) == 1
    session.clear()
    assert not session.turns


def test_stop_preserves_results_not_yet_polled_by_ui():
    session = AskSession()
    state = RunState()
    session.active_run = state
    state.publish('result', 1, 'list_months', {'step': Step('list_months', {}, {'months': []})})
    session.stop()
    assert len(session.turns[-1].answer.steps) == 1


def test_unsaved_result_cannot_be_discarded_by_new_chat():
    import pytest
    session=AskSession()
    session.pending_save=('m','r',Answer('尚未保存',[]))
    with pytest.raises(ValueError):session.clear()


def test_closed_page_stops_heartbeat_before_connection_closes():
    from bill_pipeline.db import connect
    from web.pages import Context
    c=connect(':memory:');ctx=Context(c)
    ctx.close()
    ctx.heartbeat()
    ctx.close()  # 重复断开也安全。
