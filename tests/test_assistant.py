import pytest

from bill_pipeline.ai import AIError
from bill_pipeline.assistant import MAX_STEPS, ask, run_tool
from bill_pipeline.db import connect, set_category
from bill_pipeline.pipeline import import_bill
from tests.fakes import FakeLLM, write_wechat_xlsx

PEOPLE = ("张阿姨", "球友A", "爸爸", "亲戚")


@pytest.fixture
def conn(tmp_path):
    conn = connect(":memory:")
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    set_category(conn, "星光球馆", "运动")
    return conn


def test_run_tool_month_summary(conn):
    result = run_tool(conn, "month_summary", {"month": "2026-10"})
    assert result["expense"] == "85.50"
    assert {"category": "运动", "amount": "40.00"} in result["by_category"]


@pytest.mark.parametrize("name, args", [
    ("month_summary", {"month": "十月"}),
    ("month_summary", {"month": "2026-09"}),  # 格式对，但没有这个月的账单
    ("month_summary", {}),
    ("top_counterparties", {"month": "2026-10", "limit": "很多"}),
    ("no_such_tool", {}),
])
def test_run_tool_bad_args(conn, name, args):
    assert "error" in run_tool(conn, name, args)


def test_top_counterparties_merges_people(conn):
    rows = run_tool(conn, "top_counterparties", {"month": "2026-10"})["rows"]
    # 张阿姨 8 元和球友A 25 元都是付给个人的，合成一行
    assert [(r["counterparty"], r["amount"]) for r in rows] == [
        ("星光球馆", "40.00"), ("个人收款", "33.00"), ("食堂一楼", "12.50")]


def test_category_detail_masks_people(conn):
    result = run_tool(conn, "category_detail", {"month": "2026-10", "category": "其他"})
    assert result["total"] == "25.00"
    assert [r["counterparty"] for r in result["rows"]] == ["个人收款"]


def test_search_transactions_totals(conn):
    result = run_tool(conn, "search_transactions", {"keyword": "星光"})
    assert result["count"] == 1 and result["totals"]["消费"] == "40.00"


def test_compare_and_range_tools(conn):
    result = run_tool(conn, "compare_months", {"base_month": "2026-10", "target_month": "2026-10"})
    assert result["delta"] == "0.00"
    assert all(r["contribution_percent"] is None for r in result["by_category"])
    result = run_tool(conn, "range_summary", {"start_date": "2026-09-01", "end_date": "2026-10-31"})
    assert result["totals"]["expense"] == "85.50"
    assert result["coverage"]["missing_months"] == ["2026-09"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 51])
def test_limit_validation(conn, limit):
    assert "error" in run_tool(conn, "search_transactions", {"limit": limit})


def test_search_pagination_and_dates(conn):
    first = run_tool(conn, "search_transactions", {"limit": 1, "offset": 0})
    second = run_tool(conn, "search_transactions", {"limit": 1, "offset": 1})
    assert first["has_more"] and first["truncated"]
    assert first["totals"] == second["totals"]
    assert first["rows"] != second["rows"]
    assert "error" in run_tool(conn, "range_summary", {"start_date": "2026-02-30", "end_date": "2026-10-31"})


def test_ask_masks_people(conn):
    llm = FakeLLM([{"tool_calls": [("search_transactions", {"month": "2026-10"})]}, {"content": "查完了"}])
    ask(llm, "fake", conn, "这个月的钱都去哪了", "2026-10")
    tool_text = "".join(m["content"] for m in llm.calls[-1]["messages"] if isinstance(m, dict) and m["role"] == "tool")
    assert "个人收款" in tool_text and "星光球馆" in tool_text
    assert not [name for name in PEOPLE if name in llm.sent_text()]


def test_ask_returns_answer_and_steps(conn):
    llm = FakeLLM([{"tool_calls": [("month_summary", {"month": "2026-10"})]}, {"content": "10 月消费 ¥85.50。"}])
    answer = ask(llm, "fake", conn, "这个月花了多少", "2026-10")
    assert answer.text == "10 月消费 ¥85.50。"
    assert [step.tool for step in answer.steps] == ["month_summary"]
    assert answer.steps[0].result["expense"] == "85.50"
    assert "2026-10" in llm.calls[0]["messages"][0]["content"]  # 没说月份时默认用这个月


def test_ask_stops_after_max_steps(conn):
    replies = [{"tool_calls": [("search_transactions", {"limit": n})]} for n in range(1, 6)]
    llm = FakeLLM(replies + [{"content": "根据已有数据，阶段性结论。"}])
    answer = ask(llm, "fake", conn, "随便问问", "2026-10")
    assert answer.text == "根据已有数据，阶段性结论。" and answer.status == "partial"
    assert len(answer.steps) == MAX_STEPS and len(llm.calls) == MAX_STEPS + 1
    assert llm.calls[-1]["tool_choice"] == "none"
    assert all(o['max_retries'] == 0 and o['timeout'] <= 30 for o in llm.options)


def test_deep_mode_and_history(conn):
    from bill_pipeline.assistant_state import Turn, Answer
    llm = FakeLLM([{"tool_calls": [("search_transactions", {"limit": n})]} for n in range(1, 8)] + [{"content": "完成"}])
    result = ask(llm, "fake", conn, "继续", "2026-10", mode="deep",
                 history=[Turn("原问题", "2026-09", Answer("原答", []))])
    assert result.status == "complete" and result.batches == 7
    assert "原问题" in str(llm.calls[0]) and "2026-09" in str(llm.calls[0])


def test_duplicate_queries_and_forbidden_final_tools(conn):
    llm = FakeLLM([{"tool_calls": [("list_months", {})]}] * 4)
    result = ask(llm, "fake", conn, "问题", "2026-10")
    assert len(result.steps) == 3 and len(llm.calls) == 4
    assert result.status == "partial"
    assert llm.calls[-1]['tool_choice'] == 'none'


def test_batch_limit_has_all_tool_replies(conn):
    llm = FakeLLM([{"tool_calls": [("search_transactions", {"limit": n}) for n in range(1, 9)]}, {"content": "完成"}])
    result = ask(llm, "fake", conn, "问题", "2026-10")
    assert len(result.steps) == 8
    assert sum('error' not in s.result for s in result.steps) == 6
    assert len([m for m in llm.calls[-1]['messages'] if isinstance(m, dict) and m['role']=='tool']) == 8


def test_cancelled_never_calls_model(conn):
    from bill_pipeline.assistant_state import RunState
    state = RunState()
    state.cancel.set()
    llm = FakeLLM([])
    result = ask(llm, 'fake', conn, '问题', '2026-10', run_state=state)
    assert result.status == 'cancelled' and not llm.calls


def test_request_cancel_ignores_late_answer(conn):
    from bill_pipeline.assistant_state import RunState
    state = RunState()
    llm = FakeLLM([{'content':'迟到回答'}])
    original = llm.chat.completions.create
    def cancel_after(**kw):
        response = original(**kw)
        state.cancel.set()
        return response
    llm.chat.completions.create = cancel_after
    result = ask(llm, 'fake', conn, '问题', '2026-10', run_state=state)
    assert result.status == 'cancelled' and '迟到回答' not in result.text


def test_query_timeout_keeps_results_and_summarizes(conn):
    now = [0.0]
    llm = FakeLLM([{'tool_calls': [('list_months', {})]}, {'content': '太迟了'}, {'content': '已有结果的总结'}])
    original = llm.chat.completions.create
    def advance(**kw):
        response = original(**kw)
        if len(llm.calls) == 2:
            now[0] = 61
        return response
    llm.chat.completions.create = advance
    result = ask(llm, 'fake', conn, '问题', '2026-10', clock=lambda: now[0])
    assert result.status == 'timeout' and result.text == '已有结果的总结'
    assert len(result.steps) == 1 and len(llm.calls) == 3


def test_summary_timeout_and_error_do_not_leak_secrets(conn):
    llm = FakeLLM([{'tool_calls': [('list_months', {})]}] * 3)
    result = ask(llm, 'fake', conn, '问题', '2026-10')
    assert result.status == 'error' and result.steps
    assert 'FakeLLM 的回复用完了' not in result.reason


def test_compare_math_and_missing_month(conn):
    with conn:
        conn.execute("UPDATE transactions SET tx_time='2026-09-01 12:00:00' WHERE counterparty='星光球馆'")
    result = run_tool(conn, 'compare_months', {'base_month': '2026-09', 'target_month': '2026-10'})
    assert result['base']['expense'] == '40.00'
    assert result['target']['expense'] == '45.50' and result['delta'] == '5.50'
    assert result['change_percent'] == 13.8
    assert 'error' in run_tool(conn, 'compare_months', {'base_month':'2026-08','target_month':'2026-10'})


@pytest.mark.parametrize('args', [
    {'start_date':'2026-10-02','end_date':'2026-10-01'},
    {'start_date':'2025-01-01','end_date':'2026-01-02'},
    {'start_date':'2026-1-1','end_date':'2026-10-02'},
    {'start_date':'2026-10-01','end_date':'2026-10-31','group_by':'sql'},
])
def test_range_rejects_invalid_input(conn, args):
    assert 'error' in run_tool(conn, 'range_summary', args)


def test_stable_pagination_identical_timestamps(conn):
    with conn:
        conn.execute("UPDATE transactions SET tx_time='2026-10-01 12:00:00'")
    all_rows = run_tool(conn, 'search_transactions', {'limit':50})
    pages = [run_tool(conn, 'search_transactions', {'limit':1,'offset':i})['rows'][0]
             for i in range(all_rows['count'])]
    assert pages == all_rows['rows']
    assert 'error' in run_tool(conn, 'search_transactions', {'offset':True})


def test_range_includes_endpoints_and_masks_person_detail(conn):
    result = run_tool(conn, 'range_summary', {'start_date':'2026-10-02','end_date':'2026-10-03','group_by':'day'})
    assert result['totals']['expense'] == '73.00'
    assert [g['key'] for g in result['groups']] == ['2026-10-02','2026-10-03']
    rows = run_tool(conn, 'search_transactions', {'start_date':'2026-10-03','end_date':'2026-10-03'})['rows']
    assert all(r['counterparty'] == '个人收款' and r['item'] == '' for r in rows)



def test_ask_api_error_raises(conn):
    with pytest.raises(AIError, match="调用模型出错"):
        ask(FakeLLM([]), "fake", conn, "这个月花了多少", "2026-10")
