import pandas as pd
import pytest

from bill_pipeline.model import ROW_COLUMNS
from bill_pipeline.rules import apply_rules, classify
from bill_pipeline.wechat import read_wechat
from tests.fakes import write_wechat_xlsx


@pytest.mark.parametrize("args, expected", [
    (("/", "零钱提现", "提现已到账", 5050), ("不算", "中性交易", None, 0)),
    (("支出", "商户消费", "支付失败", 500), ("不算", "失败或关闭", None, 0)),
    (("支出", "商户消费", "已全额退款", 2680), ("不算", "全额退款的原交易", None, 0)),
    (("收入", "淘宝平台-退款", "已全额退款", 2680), ("不算", "退款", None, 0)),
    (("支出", "商户消费", "已退款(￥5.00)", 2000), ("消费", "部分退款（待确认）", None, 1500)),
    (("支出", "商户消费", "已退款（¥20.00）", 2000), ("未识别", "未识别（商户消费/已退款（¥20.00））", None, 0)),
    (("支出", "商户消费", "支付成功", 1250), ("消费", "消费", None, 1250)),
    (("支出", "扫二维码付款", "已转账", 800), ("消费", "消费", None, 800)),
    (("支出", "转账", "对方已收钱", 2500), ("消费", "转账（归其他）", "其他", 2500)),
    (("收入", "转账", "已存入零钱", 120000), ("收入", "转账收入", None, 120000)),
    (("收入", "微信红包", "已存入零钱", 8800), ("收入", "收红包", None, 8800)),
    (("支出", "微信红包", "已领取", 2000), ("消费", "发红包（归其他）", "其他", 2000)),
    (("支出", "转账", "已退还", 2500), ("未识别", "未识别（转账/已退还）", None, 0)),
    (("支出", "消费-其他", "支付成功", 1000), ("消费", "消费", None, 1000)),
    (("支出", "转账", "对方已退还", 2500), ("不算", "转账被对方退还", None, 0)),
    (("收入", "二维码收款", "已收钱", 3000), ("收入", "收款码收入", None, 3000)),
    (("收入", "二手交易", "已收钱", 3000), ("未识别", "未识别（二手交易/已收钱）", None, 0)),
])
def test_classify(args, expected):
    assert classify(*args) == expected


def test_apply_rules_adds_columns_and_keeps_input(tmp_path):
    rows = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx")).rows
    out = apply_rules(rows)
    assert list(out.columns) == ROW_COLUMNS + ["result", "reason", "category", "counted_cents"]
    assert out.groupby("result").counted_cents.sum().to_dict() == {"不算": 0, "收入": 128800, "消费": 8550}
    assert out.loc[out.counterparty == "球友A", "category"].item() == "其他"
    assert list(rows.columns) == ROW_COLUMNS


def test_apply_rules_empty():
    out = apply_rules(pd.DataFrame(columns=ROW_COLUMNS))
    assert out.empty
    assert "counted_cents" in out.columns


@pytest.mark.parametrize("args, expected", [
    (("支出", "餐饮美食", "交易成功", 1850), ("消费", "消费", None, 1850)),
    (("/", "投资理财", "交易成功", 6660), ("不算", "中性交易", None, 0)),
    (("支出", "日用百货", "交易关闭", 500), ("不算", "失败或关闭", None, 0)),
    (("收入", "退款", "退款成功", 500), ("未识别", "未识别（退款/退款成功）", None, 0)),
    (("支出", "转账红包", "等待确认收货", 500), ("未识别", "未识别（转账红包/等待确认收货）", None, 0)),
])
def test_classify_alipay(args, expected):
    assert classify(*args, source="支付宝") == expected
