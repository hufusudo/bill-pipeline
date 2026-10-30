"""读支付宝导出的账单（CSV）。格式见设计文档 3.2。"""
import csv
from pathlib import Path

import pandas as pd

from bill_pipeline.convert import to_cents, to_time_text
from bill_pipeline.header import parse_period, parse_summary, parse_export_metadata
from bill_pipeline.model import ROW_COLUMNS, BillError, ParsedBill

# “对方账号”是个人信息，用不上，不读
ALIPAY_COLUMNS = {
    "交易时间": "tx_time", "交易分类": "tx_type", "交易对方": "counterparty", "商品说明": "item",
    "收/支": "direction", "金额": "amount_cents", "收/付款方式": "method", "交易状态": "status",
    "交易订单号": "tx_id", "商家订单号": "merchant_order", "备注": "note",
}
TEXT_COLUMNS = ["tx_type", "counterparty", "item", "direction", "method", "status", "merchant_order", "note"]
NEUTRAL = "不计收支"


def _decode(data: bytes) -> str:
    # 支付宝一直用 GBK（这里用它的超集 GB18030）；先试 UTF-8，以后换了编码也能读
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BillError("编码认不出来：既不是 UTF-8，也不是 GBK")


def read_alipay(src) -> ParsedBill:
    """src 可以是路径，也可以是二进制文件对象（网页上传的文件）。"""
    if hasattr(src, "read"):
        src.seek(0)
        data = src.read()
    else:
        data = Path(src).read_bytes()
    lines = _decode(data).splitlines()

    header_at = next((i for i, line in enumerate(lines) if line.split(",")[0].strip() == "交易时间"), None)
    if header_at is None:
        raise BillError("认不出账单：找不到表头“交易时间”")
    above = [line.strip() for line in lines[:header_at] if line.strip()]
    if not any(line.startswith("支付宝账户") for line in above):
        raise BillError("不是支付宝账单：说明行里没有“支付宝账户”")
    text = "\n".join(above)

    reader = csv.reader(lines[header_at:])
    header = [name.strip() for name in next(reader)]
    missing = [name for name in ALIPAY_COLUMNS if name not in header]
    if missing:
        raise BillError(f"账单缺少这些列：{'、'.join(missing)}")
    position = {english: header.index(chinese) for chinese, english in ALIPAY_COLUMNS.items()}

    summary = parse_summary(text, NEUTRAL)
    period_start, period_end = parse_period(text)
    records = []
    for row in reader:
        if any(cell.strip() for cell in row):
            # reader.line_num 从表头那一行数起，加上表头之前的行数就是文件里的行号
            records.append(_parse_row(row, position, line_no=header_at + reader.line_num))
    return ParsedBill("支付宝", period_start, period_end, summary, pd.DataFrame(records, columns=ROW_COLUMNS), *parse_export_metadata(text))


def _parse_row(row: list[str], position: dict[str, int], line_no: int) -> dict:
    cells = row + [""] * (max(position.values()) + 1 - len(row))
    # 单号前后带着制表符，其他字段也一律去掉首尾空白
    raw = {name: cells[i].strip() for name, i in position.items()}
    if not raw["tx_id"]:
        raise BillError(f"第 {line_no} 行没有交易订单号")
    try:
        record = {name: raw[name] for name in TEXT_COLUMNS}
        record.update(tx_id=raw["tx_id"], tx_time=to_time_text(raw["tx_time"]),
                      amount_cents=to_cents(raw["amount_cents"]))
    except BillError as e:
        raise BillError(f"第 {line_no} 行：{e}") from None
    # 统一取值：支付宝的“不计收支”就是微信的中性交易
    if record["direction"] == NEUTRAL:
        record["direction"] = "/"
    return record
