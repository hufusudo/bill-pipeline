"""读微信支付导出的账单（xlsx）。"""
import pandas as pd

from bill_pipeline.convert import to_cents, to_time_text
from bill_pipeline.header import parse_period, parse_summary, parse_export_metadata
from bill_pipeline.model import ROW_COLUMNS, BillError, ParsedBill

TITLE = "微信支付账单明细"
WECHAT_COLUMNS = {
    "交易时间": "tx_time", "交易类型": "tx_type", "交易对方": "counterparty", "商品": "item",
    "收/支": "direction", "金额(元)": "amount_cents", "支付方式": "method", "当前状态": "status",
    "交易单号": "tx_id", "商户单号": "merchant_order", "备注": "note",
}
TEXT_COLUMNS = ["tx_type", "counterparty", "item", "direction", "method", "status", "merchant_order", "note"]


def _is_blank(value) -> bool:
    return pd.isna(value) or (isinstance(value, str) and not value.strip())


def _text(value) -> str:
    return "" if _is_blank(value) else str(value).strip()


def read_wechat(src) -> ParsedBill:
    """src 可以是路径，也可以是二进制文件对象（网页上传的文件）。"""
    try:
        sheet = pd.read_excel(src, header=None, dtype=object, engine="openpyxl")
    except Exception as e:  # 不是 xlsx、文件损坏等都转成拒收；Ctrl+C 不是 Exception，照样能中断
        raise BillError(f"打不开文件：不是有效的 xlsx（{type(e).__name__}）") from e
    cells = sheet.values.tolist()

    header_at = next((i for i, row in enumerate(cells)
                      if any(isinstance(v, str) and v.strip() == "交易时间" for v in row)), None)
    if header_at is None:
        raise BillError("认不出账单：找不到表头“交易时间”")

    lines = [" ".join(_text(v) for v in row if not _is_blank(v)) for row in cells[:header_at]]
    lines = [line for line in lines if line]
    # 只比第一行：分隔线里也有“微信支付账单明细”这几个字
    if not lines or lines[0] != TITLE:
        raise BillError(f"不是微信账单：第一行不是“{TITLE}”")
    text = "\n".join(lines)

    header = [_text(v) for v in cells[header_at]]
    missing = [name for name in WECHAT_COLUMNS if name not in header]
    if missing:
        raise BillError(f"账单缺少这些列：{'、'.join(missing)}")
    position = {english: header.index(chinese) for chinese, english in WECHAT_COLUMNS.items()}

    summary = parse_summary(text, "中性交易")
    period_start, period_end = parse_period(text)
    records = [_parse_row(row, position, excel_row=i + 1)
               for i, row in enumerate(cells) if i > header_at and not all(_is_blank(v) for v in row)]
    return ParsedBill("微信", period_start, period_end, summary, pd.DataFrame(records, columns=ROW_COLUMNS), *parse_export_metadata(text))


def _parse_row(row: list, position: dict[str, int], excel_row: int) -> dict:
    raw = {name: row[i] for name, i in position.items()}
    tx_id = raw["tx_id"]
    # 单号被 Excel 改成数字后，28 位以上会丢精度，去重就不可靠了
    if not isinstance(tx_id, str):
        raise BillError(f"第 {excel_row} 行的交易单号不是文字，文件可能被 Excel 另存过")
    if not tx_id.strip():
        raise BillError(f"第 {excel_row} 行没有交易单号")
    try:
        record = {name: _text(raw[name]) for name in TEXT_COLUMNS}
        record.update(tx_id=tx_id.strip(), tx_time=to_time_text(raw["tx_time"]),
                      amount_cents=to_cents(raw["amount_cents"]))
    except BillError as e:
        raise BillError(f"第 {excel_row} 行：{e}") from None
    return record
