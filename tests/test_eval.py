import json

import pytest

from bill_pipeline.db import Card, connect, set_category
from bill_pipeline.pipeline import import_bill
from bill_pipeline.rules import DEFAULT_CATEGORIES
from scripts.eval_ai import cases, is_correct, suggest_scores
from tests.fakes import FakeLLM, write_wechat_xlsx


def test_cases(tmp_path):
    conn = connect(":memory:")
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    set_category(conn, "星光球馆", "运动")
    assert cases(conn) == [
        ("2026 年 10 月一共花了多少钱？", 8550),
        ("2026 年 10 月运动花了多少钱？", 4000),
        ("2026 年 10 月其他花了多少钱？", 2500),  # 未归类的不问
        ("2026 年 10 月哪天花得最多？", 4000),
    ]


@pytest.mark.parametrize("answer, ok", [
    ("10 月一共花了 ¥1,286.50。", True),
    ("一共 1286.50 元", True),
    ("一共 11286.50 元", False),  # 不能只因为包含这串数字就算对
    ("大约 1286.5 元", False),  # 要求写到分
])
def test_is_correct(answer, ok):
    assert is_correct(answer, 128650) is ok


def test_suggest_scores():
    labeled = [(Card("星光球馆", 1, 4000, "微信", "商户消费", "2026-10-02 19:00:00", "/"), "运动"),
               (Card("食堂一楼", 1, 1250, "微信", "商户消费", "2026-10-01 12:00:00", "/"), "吃饭"),
               (Card("某影院", 1, 4500, "支付宝", "文化休闲", "2026-10-03 20:00:00", "测试商品"), "娱乐")]
    reply = {"suggestions": [{"name": "星光球馆", "category": "运动"}, {"name": "食堂一楼", "category": "购物"}]}
    llm = FakeLLM([{"content": json.dumps(reply, ensure_ascii=False)}])
    # AI 给了 2 个建议，猜对 1 个；某影院它没把握，没给
    assert suggest_scores(llm, "fake", labeled, DEFAULT_CATEGORIES) == (2, 1, 0)
    sent = llm.calls[0]["messages"][1]["content"]
    assert not [label for _, label in labeled if label in sent]  # 标准答案（用户选的类别）不能发给 AI
