import pytest

from bill_pipeline.ai import AIError
from bill_pipeline.assistant import GAVE_UP, MAX_STEPS, ask, run_tool
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
    llm = FakeLLM([{"tool_calls": [("list_months", {})]}] * MAX_STEPS)
    answer = ask(llm, "fake", conn, "随便问问", "2026-10")
    assert answer.text == GAVE_UP
    assert len(answer.steps) == MAX_STEPS and len(llm.calls) == MAX_STEPS


def test_ask_api_error_raises(conn):
    with pytest.raises(AIError, match="调用模型出错"):
        ask(FakeLLM([]), "fake", conn, "这个月花了多少", "2026-10")
