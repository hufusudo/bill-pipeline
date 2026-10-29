"""账单流水线的页面：只负责收文件、调函数、显示结果。运行：streamlit run app.py"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from bill_pipeline.convert import yuan
from bill_pipeline.db import (connect, month_by_category, month_totals, months, set_category,
                              unmapped_counterparties)
from bill_pipeline.model import BillError
from bill_pipeline.pipeline import import_bill
from bill_pipeline.rules import CATEGORIES

# 环境变量只给测试用，平时用项目里的 data/bills.db
DB_PATH = Path(os.environ.get("BILL_DB", Path(__file__).parent / "data" / "bills.db"))
SKIP = "（先不归）"

st.set_page_config(page_title="账单流水线")
st.title("账单流水线")
conn = connect(DB_PATH)

st.header("导入账单")
files = st.file_uploader("上传微信账单（.xlsx），可以一次选多份", type=["xlsx"], accept_multiple_files=True)
if files and st.button("导入"):
    for f in files:
        try:
            report = import_bill(conn, f, f.name)
        except BillError as e:
            st.error(f"{f.name} 拒收：{e}")
            continue
        st.success(f"{f.name}：新增 {report.new} 笔，跳过 {report.skipped} 笔已存在")
        if report.unknown:
            st.warning(f"有 {report.unknown} 笔没见过的交易类型或状态，没算进统计，需要补规则")
        st.dataframe(pd.DataFrame([(line.direction, line.label, line.count, yuan(line.cents)) for line in report.recon],
                                  columns=["方向", "项目", "笔数", "金额（元）"]), hide_index=True)

st.header("给交易对方归类")
unmapped = unmapped_counterparties(conn)
if not unmapped:
    st.caption("都归好类了")
else:
    with st.form("categorize"):
        choices = {name: st.selectbox(f"{name}（{n} 笔，{yuan(cents)} 元）", [SKIP] + CATEGORIES, key=f"cat_{name}")
                   for name, n, cents in unmapped}
        if st.form_submit_button("保存归类"):
            for name, category in choices.items():
                if category != SKIP:
                    set_category(conn, name, category)
            st.rerun()

st.header("月报")
all_months = months(conn)
if not all_months:
    st.info("还没有导入账单")
else:
    month = st.selectbox("月份", all_months, key="month")
    expense, income = month_totals(conn, month)
    left, right = st.columns(2)
    left.metric("消费", f"{yuan(expense)} 元")
    right.metric("收入", f"{yuan(income)} 元")
    by_category = month_by_category(conn, month)
    if by_category:
        # 元只用于画图，表格里的金额仍按分换算显示
        chart = pd.DataFrame([(c, cents / 100) for c, cents in by_category], columns=["类别", "元"])
        st.bar_chart(chart.set_index("类别"))
        st.dataframe(pd.DataFrame([(c, yuan(cents)) for c, cents in by_category], columns=["类别", "金额（元）"]),
                     hide_index=True)
