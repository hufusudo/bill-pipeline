"""一份账单从读取到入库的完整流程，产出导入报告。"""
from dataclasses import dataclass

from bill_pipeline.db import save_import
from bill_pipeline.model import BillError, ParsedBill
from bill_pipeline.rules import UNKNOWN, apply_rules
from bill_pipeline.validate import ReconLine, check_summary, check_unique_ids, reconcile
from bill_pipeline.wechat import read_wechat


@dataclass
class ImportReport:
    file_name: str
    source: str
    period_start: str
    period_end: str
    total: int
    new: int
    skipped: int
    unknown: int
    recon: list[ReconLine]


def read_bill(src, file_name: str) -> ParsedBill:
    """按文件类型交给对应的读取函数。以后支付宝从这里接入。"""
    if file_name.lower().endswith(".xlsx"):
        return read_wechat(src)
    raise BillError(f"暂时只支持微信账单（.xlsx）：{file_name}")


def import_bill(conn, src, file_name: str) -> ImportReport:
    bill = read_bill(src, file_name)
    check_summary(bill)
    check_unique_ids(bill)
    rows = apply_rules(bill.rows)
    recon = reconcile(rows, bill.summary)
    # 入库放在最后：前面任何一步拒收，库里都不会多出东西
    new, skipped = save_import(conn, bill, rows, file_name)
    return ImportReport(file_name, bill.source, bill.period_start, bill.period_end,
                        len(rows), new, skipped, int((rows.result == UNKNOWN).sum()), recon)
