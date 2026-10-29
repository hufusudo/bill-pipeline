"""校验：第一关（和说明行核对）、文件内交易单号查重、第二关（对账）。"""
from typing import NamedTuple

import pandas as pd

from bill_pipeline.convert import yuan
from bill_pipeline.model import BillError, ParsedBill, Summary
from bill_pipeline.rules import EXPENSE, INCOME

# 收/支 的取值 →（显示名, Summary 字段前缀, 这个方向计入的结果）
DIRECTIONS = {
    "支出": ("支出", "expense", EXPENSE),
    "收入": ("收入", "income", INCOME),
    "/": ("中性交易", "neutral", None),
}


class ReconLine(NamedTuple):
    direction: str
    label: str
    count: int
    cents: int


def _stated(summary: Summary, prefix: str) -> tuple[int, int]:
    return getattr(summary, f"{prefix}_count"), getattr(summary, f"{prefix}_cents")


def check_summary(bill: ParsedBill) -> None:
    """第一关：逐行加出来的笔数和金额，要和说明行写的一模一样。"""
    rows, summary = bill.rows, bill.summary
    unexpected = sorted(set(rows.direction) - set(DIRECTIONS))
    if unexpected:
        raise BillError(f"收/支 出现没见过的值：{'、'.join(unexpected)}")
    problems = []
    if len(rows) != summary.count:
        problems.append(f"读出来共 {len(rows)} 笔，说明行写的是共 {summary.count} 笔")
    for direction, (label, prefix, _) in DIRECTIONS.items():
        part = rows[rows.direction == direction]
        got = (len(part), int(part.amount_cents.sum()))
        stated = _stated(summary, prefix)
        if got != stated:
            problems.append(f"读出来的{label}是 {got[0]} 笔 {yuan(got[1])} 元，"
                            f"说明行写的是 {stated[0]} 笔 {yuan(stated[1])} 元")
    if problems:
        raise BillError("；".join(problems))


def check_unique_ids(bill: ParsedBill) -> None:
    ids = bill.rows.tx_id
    duplicated = ids[ids.duplicated()].nunique()
    if duplicated:
        raise BillError(f"文件里交易单号重复：{duplicated} 个")


def reconcile(rows: pd.DataFrame, summary: Summary) -> list[ReconLine]:
    """第二关：平台合计 − 各项不算的 = 计入。rows 必须已经过 apply_rules。"""
    lines = []
    for direction, (label, prefix, counted_result) in DIRECTIONS.items():
        part = rows[rows.direction == direction]
        stated_count, stated_cents = _stated(summary, prefix)
        lines.append(ReconLine(label, "平台合计", stated_count, stated_cents))

        deducted_total = 0
        deducted = part[part.amount_cents > part.counted_cents]
        for reason, group in deducted.groupby("reason"):
            cents = int((group.amount_cents - group.counted_cents).sum())
            deducted_total += cents
            lines.append(ReconLine(label, f"减：{reason}", len(group), cents))

        kept = part[part.result == counted_result] if counted_result else part.iloc[0:0]
        kept_cents = int(kept.counted_cents.sum())
        lines.append(ReconLine(label, "= 计入", len(kept), kept_cents))
        if stated_cents - deducted_total != kept_cents:
            raise BillError(f"对账不平：{label} 平台合计 {yuan(stated_cents)} 元 − 减项 "
                            f"{yuan(deducted_total)} 元 ≠ 计入 {yuan(kept_cents)} 元")
    return lines
