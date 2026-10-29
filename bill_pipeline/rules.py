"""清洗规则：每一笔交易算不算、算成什么、为什么。规则见设计文档第 4 节。"""
import re
from typing import NamedTuple

import pandas as pd

from bill_pipeline.convert import to_cents

# 默认分类，顺序就是环形图扇区的顺序（相邻颜色验证过）；用户加的分类排在后面，存在数据库里
DEFAULT_CATEGORIES = ["吃饭", "运动", "购物", "交通", "娱乐", "其他"]
EXPENSE, INCOME, EXCLUDED, UNKNOWN = "消费", "收入", "不算", "未识别"
OTHER = "其他"

FAILED_STATUSES = {"交易关闭", "支付失败"}
PARTIAL_REFUND = re.compile(r"^已退款[（(][￥¥]?(\d+(?:\.\d{1,2})?)[)）]$")
# （收/支, 交易类型, 状态）→（结果, 原因, 固定类别）。表里没有的组合不猜，标成未识别
KNOWN = {
    ("支出", "商户消费", "支付成功"): (EXPENSE, "消费", None),
    ("支出", "扫二维码付款", "已转账"): (EXPENSE, "消费", None),
    ("支出", "转账", "对方已收钱"): (EXPENSE, "转账（归其他）", OTHER),
    ("收入", "转账", "已存入零钱"): (INCOME, "转账收入", None),
    ("收入", "微信红包", "已存入零钱"): (INCOME, "收红包", None),
}
# 支付宝的“交易分类”是它自己的消费分类，不分转账和消费，所以只看（收/支, 状态）
ALIPAY_KNOWN = {
    ("支出", "交易成功"): (EXPENSE, "消费", None),
}


class Classified(NamedTuple):
    result: str
    reason: str
    category: str | None
    counted_cents: int


def classify(direction: str, tx_type: str, status: str, amount_cents: int, source: str = "微信") -> Classified:
    """按顺序匹配，命中第一条就停。前两条两家共用。"""
    amount_cents = int(amount_cents)
    if direction == "/":
        return Classified(EXCLUDED, "中性交易", None, 0)
    if status in FAILED_STATUSES:
        return Classified(EXCLUDED, "失败或关闭", None, 0)
    if source == "支付宝":
        if (direction, status) in ALIPAY_KNOWN:
            result, reason, category = ALIPAY_KNOWN[(direction, status)]
            return Classified(result, reason, category, amount_cents)
        return Classified(UNKNOWN, f"未识别（{tx_type}/{status}）", None, 0)
    if direction == "支出" and status == "已全额退款":
        return Classified(EXCLUDED, "全额退款的原交易", None, 0)
    if direction == "收入" and (tx_type.endswith("-退款") or status == "已全额退款"):
        return Classified(EXCLUDED, "退款", None, 0)
    if direction == "支出" and (match := PARTIAL_REFUND.match(status)):
        refunded = to_cents(match.group(1))
        if 0 < refunded < amount_cents:
            return Classified(EXPENSE, "部分退款（待确认）", None, amount_cents - refunded)
    if (direction, tx_type, status) in KNOWN:
        result, reason, category = KNOWN[(direction, tx_type, status)]
        return Classified(result, reason, category, amount_cents)
    if direction == "支出" and tx_type == "微信红包":
        return Classified(EXPENSE, "发红包（归其他）", OTHER, amount_cents)
    return Classified(UNKNOWN, f"未识别（{tx_type}/{status}）", None, 0)


def apply_rules(rows: pd.DataFrame, source: str = "微信") -> pd.DataFrame:
    """返回副本，多出 result、reason、category、counted_cents 四列。"""
    out = rows.copy()
    # 不用 DataFrame.apply：表为空时它拿不到列
    results = [classify(*args, source=source)
               for args in zip(rows.direction, rows.tx_type, rows.status, rows.amount_cents)]
    for i, name in enumerate(Classified._fields):
        out[name] = [r[i] for r in results]
    return out
