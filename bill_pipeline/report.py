"""按月的报表：上一个月、比上月的变化、月度对账。界面只调用这里，不自己算。"""
import sqlite3

from bill_pipeline.db import month_rows
from bill_pipeline.model import Summary
from bill_pipeline.validate import ReconLine, reconcile


def previous_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def change_ratio(current: int, previous: int) -> float | None:
    """本月比上月的变化，-0.1 表示少了 10%；上月没有数据时返回 None。"""
    return None if previous == 0 else (current - previous) / previous


def month_reconciliation(conn: sqlite3.Connection, month: str) -> list[ReconLine]:
    """用库里这个月的明细重新对账：账单的原始金额当作平台合计，减项和计入的算法和第二关一样。"""
    rows = month_rows(conn, month)

    def stated(direction: str) -> tuple[int, int]:
        part = rows[rows.direction == direction]
        return len(part), int(part.amount_cents.sum())

    (ec, ecents), (ic, icents), (nc, ncents) = stated("支出"), stated("收入"), stated("/")
    return reconcile(rows, Summary(len(rows), ic, icents, ec, ecents, nc, ncents))
