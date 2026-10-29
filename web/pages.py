"""账单流水线的界面：左边导航，右边五个面板。只负责收文件、调函数、显示结果。"""
import os
import sqlite3
from pathlib import Path

from nicegui import ui

from bill_pipeline.db import category_transactions, connect, month_by_category, month_totals, months
from bill_pipeline.report import change_ratio, previous_month
from web.theme import CATEGORY_COLORS, COUNT_UP_JS, CSS, donut_option, money

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


def placeholder(page: str):
    return lambda ctx: ui.label(TITLES[page]).classes("title")


RENDERERS = {"overview": render_overview, "trend": placeholder("trend"), "upload": placeholder("upload"),
             "sort": placeholder("sort"), "recon": placeholder("recon")}


def make_view(render, ctx: Context):
    @ui.refreshable
    def view() -> None:
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
            ctx.page = page
            for key, nav in navs.items():
                nav.classes(add="on") if key == page else nav.classes(remove="on")
            eyebrow.set_text(dict((key, label) for key, label, _ in PAGES)[page])
            panels.set_value(page)
            ctx.views[page].refresh()

        def change_month(value: str) -> None:
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
                            ctx.views[key] = make_view(RENDERERS[key], ctx)
