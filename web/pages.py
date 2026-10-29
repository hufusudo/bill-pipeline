"""账单流水线的界面：左边导航，右边五个面板。只负责收文件、调函数、显示结果。"""
import io
import os
import sqlite3
from pathlib import Path

from nicegui import ui

from bill_pipeline.db import (categorized, category_transactions, connect, daily_expense, import_history,
                              month_by_category, month_totals, months, recent_months, set_category,
                              unmapped_counterparties)
from bill_pipeline.model import BillError
from bill_pipeline.pipeline import ImportReport, import_bill
from bill_pipeline.report import change_ratio, previous_month
from bill_pipeline.rules import CATEGORIES
from web.theme import (CATEGORY_COLORS, COUNT_UP_JS, CSS, daily_option, donut_option, money, monthly_option)

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "bills.db"
PAGES = [("overview", "总览", "space_dashboard"), ("trend", "趋势", "trending_up"), ("upload", "导入", "upload"),
         ("sort", "归类", "sell"), ("recon", "对账", "task_alt")]
TITLES = {"trend": "花钱的节奏", "upload": "导入账单", "sort": "给交易对方归类", "recon": "钱都去哪了"}


def db_path() -> Path:
    # 每次打开页面时才读环境变量，测试才能换成临时库
    return Path(os.environ.get("BILL_DB", DEFAULT_DB))


def month_name(month: str) -> str:
    return f"{int(month[5:7])} 月"


def month_label(month: str) -> str:
    return f"{month[:4]} 年 {month_name(month)}"


class Context:
    """一个浏览器页面的状态：数据库连接、当前月份、当前面板，以及切换面板的方法。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        all_months = months(conn)
        self.month: str | None = all_months[0] if all_months else None
        self.page = "overview"
        self.views: dict = {}
        self.show = lambda page: None


def open_category(ctx: Context, category: str) -> None:
    """弹窗列出这个月某一类的每一笔。"""
    rows = category_transactions(ctx.conn, ctx.month, category)
    with ui.dialog() as dialog, ui.card().classes("min-w-[420px]"):
        ui.label(f"{category} · {month_name(ctx.month)}").classes("text-lg font-bold")
        for tx_time, counterparty, _, cents in rows:
            with ui.row().classes("w-full justify-between no-wrap"):
                ui.label(f"{tx_time[5:16]}　{counterparty}")
                ui.label(money(cents)).classes("amt")
        ui.button("关闭", on_click=dialog.close).props("flat")
    dialog.open()


def render_overview(ctx: Context) -> None:
    if ctx.month is None:
        ui.label("还没有导入账单").classes("empty")
        ui.button("去导入", on_click=lambda: ctx.show("upload")).props("unelevated rounded color=teal")
        return
    expense, income = month_totals(ctx.conn, ctx.month)
    previous = previous_month(ctx.month)
    ratio = change_ratio(expense, month_totals(ctx.conn, previous)[0])
    ui.label(f"{month_name(ctx.month)}消费").classes("hero-label")
    with ui.element("div").classes("hero-row"):
        hero = ui.label(money(expense)).classes("hero-num")
        if ratio is not None:
            arrow, word, kind = ("↓", "少", "down") if ratio < 0 else ("↑", "多", "up")
            ui.label(f"{arrow} 比 {month_name(previous)}{word} {abs(ratio) * 100:.1f}%").classes(f"pill {kind}")
    ui.label(f"收入 {money(income)} · 结余 {money(income - expense)}").classes("sub")
    ui.run_javascript(f"window.countUp('{hero.html_id}', {expense / 100})")

    by_category = month_by_category(ctx.conn, ctx.month)
    if not by_category:
        ui.label("这个月还没有消费").classes("empty")
        return
    total = sum(cents for _, cents in by_category)
    with ui.element("div").classes("split"):
        ui.echart(donut_option(by_category), on_point_click=lambda e: open_category(ctx, e.name)).classes("chart")
        with ui.element("div").classes("legend"):
            for category, cents in by_category:
                with ui.element("div").classes("legend-row") as row:
                    ui.element("span").classes("dot").style(f"background:{CATEGORY_COLORS.get(category, '#c3c9d3')}")
                    ui.label(category)
                    ui.label(money(cents)).classes("amt")
                    ui.label(f"{round(cents / total * 100)}%").classes("pct")
                row.on("click", lambda category=category: open_category(ctx, category))


def trend_table(ctx: Context) -> None:
    with ui.element("div").classes("table"):
        with ui.element("div").classes("tr"):
            for head in ("月份", "消费", "比上月"):
                ui.label(head)
        previous = None
        for month, cents in recent_months(ctx.conn):
            ratio = None if previous is None else change_ratio(cents, previous)
            with ui.element("div").classes("tr"):
                ui.label(month_name(month))
                ui.label(money(cents))
                ui.label("—" if ratio is None else f"{'+' if ratio >= 0 else '−'}{abs(ratio) * 100:.1f}%")
            previous = cents


def render_trend(ctx: Context) -> None:
    ui.label(TITLES["trend"]).classes("title")
    if ctx.month is None:
        ui.label("还没有导入账单").classes("empty")
        return

    @ui.refreshable
    def body(mode: str) -> None:
        if mode == "表格":
            trend_table(ctx)
        elif mode == "按天":
            days = daily_expense(ctx.conn, ctx.month)
            day, cents = max(days, key=lambda d: d[1], default=("", 0))
            if cents == 0:
                ui.label("这个月还没有消费").classes("note")
                return
            ui.label(f"{day[5:]} 花得最多：{money(cents)}").classes("note")
            ui.echart(daily_option(days)).classes("chart")
        else:
            current, previous = month_totals(ctx.conn, ctx.month)[0], month_totals(ctx.conn, previous_month(ctx.month))[0]
            if previous:
                word = "少" if current < previous else "多"
                ui.label(f"{month_name(ctx.month)}比 {month_name(previous_month(ctx.month))}{word}花 "
                         f"{money(abs(current - previous))}").classes("note")
            ui.echart(monthly_option(recent_months(ctx.conn), ctx.month)).classes("chart")

    ui.toggle(["按天", "按月", "表格"], value="按天", on_change=lambda e: body.refresh(e.value)) \
        .props("unelevated rounded no-caps toggle-color=teal").classes("my-3").mark("trend-mode")
    body("按天")


def result_card(report: ImportReport) -> None:
    with ui.element("div").classes("result"):
        with ui.element("div").classes("result-head"):
            ui.label(f"{report.source}账单 {report.period_start[5:10]} ~ {report.period_end[5:10]}") \
                .classes("font-semibold")
            ui.label(f"新增 {report.new} 笔 · 跳过 {report.skipped} 笔").classes("note")
        with ui.element("div").classes("bar"):
            ui.element("div")
        with ui.element("div").classes("checks"):
            for text in ("第一关：读全了", "第二关：对账平了", "第三关：不重复"):
                with ui.element("div").classes("check"):
                    ui.label("✓").classes("tick")
                    ui.label(text)
        if report.unknown:
            ui.label(f"有 {report.unknown} 笔没见过的交易类型或状态，没算进统计，需要补规则") \
                .classes("text-sm text-orange-9")


def refresh_months(ctx: Context) -> None:
    """导入后可能多出新的月份；原来没有数据时，切到最新的月份。"""
    all_months = months(ctx.conn)
    if ctx.month is None and all_months:
        ctx.month = all_months[0]
    ctx.month_select.set_options({m: month_label(m) for m in all_months}, value=ctx.month)
    ctx.month_select.set_visibility(bool(all_months))


def render_upload(ctx: Context) -> None:
    ui.label(TITLES["upload"]).classes("title")

    async def handle(e) -> None:
        data = await e.file.read()
        with results:
            try:
                report = import_bill(ctx.conn, io.BytesIO(data), e.file.name)
            except BillError as error:
                with ui.element("div").classes("result bad"):
                    ui.label(f"{e.file.name} 拒收：{error}")
            else:
                result_card(report)
        upload.reset()
        refresh_months(ctx)
        history.refresh()

    upload = ui.upload(label="把微信 .xlsx 或支付宝 .csv 拖到这里", multiple=True, auto_upload=True,
                       on_upload=handle).props("accept=.xlsx,.csv flat bordered color=teal") \
        .classes("drop mt-3").mark("upload")
    results = ui.column().classes("w-full gap-3 mt-3")

    @ui.refreshable
    def history() -> None:
        rows = import_history(ctx.conn)
        if rows:
            ui.label("最近导入").classes("note mt-4")
        for _, source, start, end, new, skipped in rows:
            ui.label(f"{source} · {start[:10]} ~ {end[:10]} · 新增 {new} · 跳过 {skipped}").classes("history")

    history()


def render_sort(ctx: Context) -> None:
    ui.label(TITLES["sort"]).classes("title")
    skipped: set[str] = set()
    total = len(unmapped_counterparties(ctx.conn))

    def choose(name: str, category: str | None) -> None:
        if category is None:
            skipped.add(name)  # 跳过只在这一轮有效，不写库
        else:
            set_category(ctx.conn, name, category)
            done_list.refresh()
        card.refresh()

    @ui.refreshable
    def card() -> None:
        pending = [c for c in unmapped_counterparties(ctx.conn) if c.counterparty not in skipped]
        with ui.element("div").classes("cardzone"):
            if not pending:
                ui.label("剩下的都跳过了" if skipped else "都归好类了").classes("empty")
                return
            c = pending[0]
            ui.label(f"第 {total - len(pending) + 1} / {total} 个 · 归一次，以后自动记住").classes("note")
            with ui.element("div").classes("who"):
                ui.label(c.counterparty).classes("who-name")
                ui.label(f"{c.count} 笔 · {money(c.cents)}").classes("who-meta")
                hint = f"支付宝分类：{c.tx_type}" if c.source == "支付宝" else c.tx_type
                ui.label(f"{hint} · 最近一笔 {c.last_time[5:16]}").classes("who-meta")
                with ui.element("div").classes("chips"):
                    for category in CATEGORIES:
                        ui.label(category).classes("chip").mark(f"chip-{category}") \
                            .on("click", lambda category=category, name=c.counterparty: choose(name, category))
            ui.label("跳过，以后再说 →").classes("skip").mark("skip") \
                .on("click", lambda name=c.counterparty: choose(name, None))

    @ui.refreshable
    def done_list() -> None:
        rows = categorized(ctx.conn)
        with ui.expansion(f"已归类（{len(rows)}）").classes("recat"):
            for name, category, count, cents in rows:
                with ui.element("div").classes("recat-row"):
                    ui.label(name)
                    ui.label(f"{count} 笔 · {money(cents)}").classes("note")
                    ui.select(CATEGORIES, value=category,
                              on_change=lambda e, name=name: set_category(ctx.conn, name, e.value)) \
                        .props("dense outlined").mark(f"recat-{name}")

    card()
    done_list()


def placeholder(page: str):
    return lambda ctx: ui.label(TITLES[page]).classes("title")


RENDERERS = {"overview": render_overview, "trend": render_trend, "upload": render_upload,
             "sort": render_sort, "recon": placeholder("recon")}


def make_view(page: str, render, ctx: Context):
    # 只画当前这一页：切走时清空，切回来重画，动效也会重放
    @ui.refreshable
    def view() -> None:
        if ctx.page == page:
            render(ctx)

    view()
    return view


def register() -> None:
    # 页面定义放在函数里：模拟测试每个用例都会重置 NiceGUI 并重新执行 main.py
    @ui.page("/")
    def index() -> None:
        ui.add_css(CSS)
        ui.add_head_html(COUNT_UP_JS)
        conn = connect(db_path())
        ui.context.client.on_disconnect(conn.close)
        ctx = Context(conn)
        navs = {}

        def show(page: str) -> None:
            old, ctx.page = ctx.page, page
            for key, nav in navs.items():
                nav.classes(add="on") if key == page else nav.classes(remove="on")
            eyebrow.set_text(dict((key, label) for key, label, _ in PAGES)[page])
            panels.set_value(page)
            ctx.views[old].refresh()
            ctx.views[page].refresh()

        def change_month(value: str) -> None:
            if value == ctx.month:  # 导入后程序自己改选项时也会触发，这时不重画，免得冲掉导入结果
                return
            ctx.month = value
            ctx.views[ctx.page].refresh()

        ctx.show = show
        with ui.element("div").classes("shell"):
            with ui.element("div").classes("rail"):
                ui.label("账").classes("logo")
                for key, label, icon in PAGES:
                    with ui.element("div").classes("nav on" if key == "overview" else "nav").mark(f"nav-{key}") as nav:
                        ui.icon(icon).classes("text-[22px]")
                        ui.label(label)
                    nav.on("click", lambda key=key: show(key))
                    navs[key] = nav
            with ui.element("div").classes("main"):
                with ui.element("div").classes("topbar"):
                    eyebrow = ui.label("总览").classes("eyebrow")
                    ctx.month_select = ui.select({m: month_label(m) for m in months(conn)}, value=ctx.month,
                                                 on_change=lambda e: change_month(e.value)) \
                        .props("outlined dense").classes("month-select").mark("month")
                    ctx.month_select.set_visibility(ctx.month is not None)
                with ui.tab_panels(value="overview", animated=True) \
                        .props("transition-prev=fade transition-next=fade").classes("panels") as panels:
                    for key, _, _ in PAGES:
                        with ui.tab_panel(key):
                            ctx.views[key] = make_view(key, RENDERERS[key], ctx)
