"""解析账单说明行里的汇总和起止时间，微信和支付宝共用。"""
import re

from bill_pipeline.convert import to_cents
from bill_pipeline.model import BillError, Summary


def parse_summary(text: str, neutral_label: str) -> Summary:
    """neutral_label 是中性交易那一行的叫法：微信是“中性交易”，支付宝是“不计收支”。"""
    labels = ["收入", "支出", neutral_label]
    count = re.search(r"共\s*(\d+)\s*笔记录", text)
    found = {label: re.search(rf"{label}[：:]\s*(\d+)\s*笔\s*([\d,.]+)\s*元", text) for label in labels}
    missing = ([] if count else ["共几笔"]) + [label for label, m in found.items() if m is None]
    if missing:
        raise BillError(f"说明行里找不到笔数和金额汇总：缺{'、'.join(missing)}")
    (ic, icents), (ec, ecents), (nc, ncents) = (
        (int(found[label].group(1)), to_cents(found[label].group(2))) for label in labels)
    return Summary(int(count.group(1)), ic, icents, ec, ecents, nc, ncents)


def parse_period(text: str) -> tuple[str, str]:
    start = re.search(r"起始时间[：:]\s*\[(.+?)\]", text)
    end = re.search(r"终止时间[：:]\s*\[(.+?)\]", text)
    if not (start and end):
        raise BillError("说明行里找不到起止时间")
    return start.group(1).strip(), end.group(1).strip()
