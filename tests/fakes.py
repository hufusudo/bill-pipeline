"""造假的微信账单：版式照真实账单，数据全是编的。"""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

HEADER = ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)",
          "支付方式", "当前状态", "交易单号", "商户单号", "备注"]
EXCEL_EPOCH = datetime(1899, 12, 30)


def make_row(n, day, hour, tx_type, who, direction, amount, status, method="零钱"):
    return {
        "交易时间": datetime(2026, 10, day, hour, 0, 0), "交易类型": tx_type, "交易对方": who,
        "商品": "/", "收/支": direction, "金额(元)": amount, "支付方式": method,
        "当前状态": status, "交易单号": f"4200000000202610{n:012d}", "商户单号": "/", "备注": "/",
    }


SAMPLE_ROWS = [
    make_row(1, 1, 12, "商户消费", "食堂一楼", "支出", 12.5, "支付成功"),
    make_row(2, 2, 19, "商户消费", "星光球馆", "支出", 40.0, "支付成功"),
    make_row(3, 3, 8, "扫二维码付款", "张阿姨", "支出", 8.0, "已转账"),
    make_row(4, 3, 21, "转账", "球友A", "支出", 25.0, "对方已收钱"),
    make_row(5, 5, 10, "商户消费", "某电商", "支出", 19.6, "已全额退款"),
    make_row(6, 6, 10, "淘宝平台-退款", "某电商", "收入", 19.6, "已全额退款"),
    make_row(7, 7, 9, "转账", "爸爸", "收入", 1500.0, "已存入零钱"),
    make_row(8, 8, 20, "微信红包", "亲戚", "收入", 64.0, "已存入零钱"),
    make_row(9, 9, 15, "零钱提现", "某银行", "/", 80.08, "提现已到账", method="/"),
]


def _summary_lines(rows):
    totals = {"收入": [0, Decimal(0)], "支出": [0, Decimal(0)], "/": [0, Decimal(0)]}
    for row in rows:
        if row["收/支"] in totals:
            totals[row["收/支"]][0] += 1
            totals[row["收/支"]][1] += Decimal(str(row["金额(元)"]))

    def line(label, key):
        n, amount = totals[key]
        return f"{label}：{n}笔 {amount:.2f}元"

    return {
        "count": f"共{len(rows)}笔记录",
        "income": line("收入", "收入"),
        "expense": line("支出", "支出"),
        "neutral": line("中性交易", "/"),
    }


def write_wechat_xlsx(path, rows=SAMPLE_ROWS, *, title="微信支付账单明细", summary_override=None,
                      time_as="datetime", drop_columns=(), blank_rows_after=0):
    summary = {**_summary_lines(rows), **(summary_override or {})}
    top = [
        title,
        "微信昵称：[测试用户]",
        "起始时间：[2026-10-01 00:00:00] 终止时间：[2026-10-31 23:59:59]",
        "导出类型：[全部账单]",
        "导出时间：[2026-10-31 23:59:59]",
        None,
        summary["count"], summary["income"], summary["expense"], summary["neutral"],
        "注：",
        "1. 充值/提现/理财通购买/零钱通存取/信用卡还款等交易，将计入中性交易",
        "2. 若交易记录明细无有效内容，则代表该时间段内此微信号无交易",
        "3. 本明细仅供个人对账使用",
        "4. 本账单中所有时间均为UTC+08:00时间",
        None,
        "----------------------微信支付账单明细列表--------------------",
    ]
    columns = [name for name in HEADER if name not in drop_columns]

    wb = Workbook()
    ws = wb.active
    for r, text in enumerate(top, start=1):
        if text is not None:
            ws.cell(row=r, column=1, value=text)
    header_row = len(top) + 1
    for c, name in enumerate(columns, start=1):
        ws.cell(row=header_row, column=c, value=name)
    for r, row in enumerate(rows, start=header_row + 1):
        for c, name in enumerate(columns, start=1):
            value = row[name]
            if name == "交易时间" and time_as == "serial":
                value = (value - EXCEL_EPOCH).total_seconds() / 86400
            ws.cell(row=r, column=c, value=value)
    first_blank = header_row + 1 + len(rows)
    for r in range(first_blank, first_blank + blank_rows_after):
        ws.cell(row=r, column=1, value=" ")
    wb.save(path)
    return Path(path)
