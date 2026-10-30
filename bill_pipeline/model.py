"""各模块共用的类型。"""
from dataclasses import dataclass

import pandas as pd


class BillError(Exception):
    """账单被拒收的原因，消息直接显示给用户。"""


@dataclass(frozen=True)
class Summary:
    """账单说明行里写的笔数和金额汇总。"""
    count: int
    income_count: int
    income_cents: int
    expense_count: int
    expense_cents: int
    neutral_count: int
    neutral_cents: int


@dataclass
class ParsedBill:
    source: str
    period_start: str
    period_end: str
    summary: Summary
    rows: pd.DataFrame
    exported_at: str | None = None
    export_scope: str | None = None


ROW_COLUMNS = [
    "tx_id", "tx_time", "tx_type", "counterparty", "item", "direction",
    "amount_cents", "method", "status", "merchant_order", "note",
]
