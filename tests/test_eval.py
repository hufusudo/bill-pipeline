import pytest

from bill_pipeline.db import connect, set_category
from bill_pipeline.pipeline import import_bill
from scripts.eval_ai import cases, is_correct
from tests.fakes import write_wechat_xlsx


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
