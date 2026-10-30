"""账单流水线的界面：左边导航，右边五个面板。只负责收文件、调函数、显示结果。"""
import io
import os
import sqlite3
from pathlib import Path

from nicegui import background_tasks, run, ui

from bill_pipeline import ai
from bill_pipeline.db import (Card, add_category, ai_accuracy, asked_counterparties, categories, categorized,
                              category_transactions, connect, daily_expense, import_history, month_by_category,
                              month_totals, months, recent_months, reclassify_unknown, save_suggestions,
                              set_category, suggestions,
                              unmapped_counterparties)
from bill_pipeline.model import BillError
from bill_pipeline.pipeline import ImportReport, import_bill
from bill_pipeline.report import change_ratio, month_reconciliation, previous_month
from web.ask import AskSession, render_ask
from web.review import render_review, render_trust_banner
from web.theme import (COUNT_UP_JS, CSS, EXTRA_COLOR, category_colors, daily_option, donut_option, money, monthly_option,
                       waterfall_option)

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "bills.db"
PAGES = [("overview", "总览", "space_dashboard"), ("trend", "趋势", "trending_up"), ("upload", "导入", "upload"),
         ("sort", "归类", "sell"), ("recon", "对账", "task_alt"), ("ask", "问答", "forum"), ("review", "核查", "fact_check")]
TITLES = {"trend": "花钱的节奏", "upload": "导入账单", "sort": "给交易对方归类", "recon": "钱都去哪了",
          "ask": "问问你的账单"}
AI_BATCH = 20  # 一次问 20 个：回复短，不容易被截断，第一张卡片的建议也来得快


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
        # AI 建议在后台问：状态放这里，切走再切回归类页也能接着显示
        self.ask_session = AskSession()
        self.ask_session.attach(conn)
        self.db_path = db_path()
        self.ai_busy = False
        self.ai_error: str | None = None
        self.sort_card = None


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
    render_trust_banner(ctx)
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
    order = categories(ctx.conn)
    colors = category_colors(order)
    with ui.element("div").classes("split"):
        ui.echart(donut_option(by_category, order), on_point_click=lambda e: open_category(ctx, e.name)).classes("chart")
        with ui.element("div").classes("legend"):
            for category, cents in by_category:
                with ui.element("div").classes("legend-row").mark(f"legend-{category}") as row:
                    ui.element("span").classes("dot").style(f"background:{colors.get(category, EXTRA_COLOR)}")
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
    render_trust_banner(ctx)
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
            ui.label(f"新增 {report.new} 笔 · 跳过 {report.skipped} 笔 · 更新 {report.updated} 笔 · 冲突 {report.conflicts} 笔").classes("note")
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
                       on_upload=handle).props("accept=.xlsx,.csv flat") \
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


async def fetch_suggestions(ctx: Context, cards: list[Card]) -> None:
    """后台问 AI，每问完一批就存下来、刷新卡片。调用前先把 ctx.ai_busy 设成 True。"""
    try:
        client, model = ai.make_client()
        names = categories(ctx.conn)
        for start in range(0, len(cards), AI_BATCH):
            batch = cards[start:start + AI_BATCH]
            mapping = await run.io_bound(ai.suggest_categories, client, model, batch, names)
            if mapping is None:  # 程序正在关闭；这批不存，免得被当成“AI 没把握”
                return
            save_suggestions(ctx.conn, {c.counterparty: mapping.get(c.counterparty, "") for c in batch}, model)
            ctx.sort_card.refresh()
    except ai.AIError as e:
        ctx.ai_error = str(e)
    finally:
        ctx.ai_busy = False
        ctx.sort_card.refresh()


def ai_line(ctx: Context, c: Card, suggestion: str | None, accept) -> None:
    """卡片下面的一行：AI 的建议，或者没有建议的原因。"""
    with ui.element("div").classes("ai-line"):
        if suggestion:
            ui.label(f"AI 建议：{suggestion}").classes("ai-pick")
            ui.button("采用", on_click=accept).props("unelevated rounded dense color=teal").classes("px-3") \
                .mark("ai-accept")
        elif ai.is_person(c.tx_type):
            ui.label("付给个人的钱不发给 AI，请自己选")
        elif c.counterparty in asked_counterparties(ctx.conn):
            ui.label("AI 没把握，请自己选")
        elif ctx.ai_busy:
            ui.spinner(size="16px", color="teal")
            ui.label("AI 正在想…")
        elif ctx.ai_error:
            ui.label(f"AI 这次没给出建议：{ctx.ai_error}").mark("ai-error")


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

    def recategorize(name: str, category: str) -> None:
        set_category(ctx.conn, name, category)
        card.refresh()  # AI 准确率显示在卡片区，改了类别要跟着更新

    def open_add_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes("min-w-[320px]"):
            ui.label("添加新分类").classes("text-lg font-bold")
            name = ui.input("分类名，最多 8 个字").props("autofocus outlined dense").classes("w-full") \
                .mark("new-category-name")
            error = ui.label().classes("text-sm text-red-8")

            def submit() -> None:
                try:
                    add_category(ctx.conn, name.value or "")
                except ValueError as e:
                    error.set_text(str(e))
                    return
                dialog.close()
                card.refresh()
                done_list.refresh()

            name.on("keydown.enter", submit)
            with ui.row().classes("w-full justify-end"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button("添加", on_click=submit).props("unelevated color=teal").mark("new-category-ok")
        dialog.open()

    def add_button() -> None:
        ui.label("+ 新分类").classes("chip add").mark("add-category").on("click", open_add_dialog)

    @ui.refreshable
    def card() -> None:
        pending = [c for c in unmapped_counterparties(ctx.conn) if c.counterparty not in skipped]
        with ui.element("div").classes("cardzone"):
            if not pending:
                ui.label("剩下的都跳过了" if skipped else "都归好类了").classes("empty")
                add_button()
            else:
                c = pending[0]
                suggestion = suggestions(ctx.conn).get(c.counterparty)
                ui.label(f"第 {total - len(pending) + 1} / {total} 个 · 归一次，以后自动记住").classes("note")
                with ui.element("div").classes("who"):
                    ui.label(c.counterparty).classes("who-name")
                    ui.label(f"{c.count} 笔 · {money(c.cents)}").classes("who-meta")
                    hint = f"支付宝分类：{c.tx_type}" if c.source == "支付宝" else c.tx_type
                    ui.label(f"{hint} · 最近一笔 {c.last_time[5:16]}").classes("who-meta")
                    with ui.element("div").classes("chips"):
                        for category in categories(ctx.conn):
                            ui.label(category).classes("chip suggested" if category == suggestion else "chip") \
                                .mark(f"chip-{category}") \
                                .on("click", lambda category=category, name=c.counterparty: choose(name, category))
                        add_button()
                    ai_line(ctx, c, suggestion, lambda name=c.counterparty, s=suggestion: choose(name, s))
                ui.label("跳过，以后再说 →").classes("skip").mark("skip") \
                    .on("click", lambda name=c.counterparty: choose(name, None))
            hits, decided = ai_accuracy(ctx.conn)
            if decided:
                ui.label(f"AI 建议准确率：{hits} / {decided}（{round(hits / decided * 100)}%）").classes("note mt-3")

    @ui.refreshable
    def done_list() -> None:
        rows = categorized(ctx.conn)
        with ui.expansion(f"已归类（{len(rows)}）").classes("recat"):
            for name, category, count, cents in rows:
                with ui.element("div").classes("recat-row"):
                    ui.label(name)
                    ui.label(f"{count} 笔 · {money(cents)}").classes("note")
                    ui.select(categories(ctx.conn), value=category,
                              on_change=lambda e, name=name: recategorize(name, e.value)) \
                        .props("dense outlined").mark(f"recat-{name}")

    asked = asked_counterparties(ctx.conn)
    need = [c for c in unmapped_counterparties(ctx.conn) if not ai.is_person(c.tx_type) and c.counterparty not in asked]
    start = bool(need) and not ctx.ai_busy  # 上一次还没问完就不再问，免得重复花钱
    if start:
        ctx.ai_busy, ctx.ai_error = True, None  # 先设好，卡片第一次画出来就显示“AI 正在想…”
    ctx.sort_card = card
    card()
    done_list()
    if start:
        background_tasks.create(fetch_suggestions(ctx, need), name="ai-suggest")


def render_recon(ctx: Context) -> None:
    ui.label(TITLES["recon"]).classes("title")
    render_trust_banner(ctx)
    if ctx.month is None:
        ui.label("还没有导入账单").classes("empty")
        return
    lines = month_reconciliation(ctx.conn, ctx.month)
    expense = [line for line in lines if line.direction == "支出"]
    platform, *deductions, kept = expense
    if platform.cents == 0:
        text = "这个月没有支出记录。"
    elif deductions:
        parts = "、".join(f"{line.label.removeprefix('减：')} {money(line.cents)}" for line in deductions)
        text = f"这个月账单里的支出是 {money(platform.cents)}，其中{parts} 不算消费，所以实际消费是 {money(kept.cents)}。"
    else:
        text = f"这个月账单里的支出是 {money(platform.cents)}，全部算作消费。"
    ui.label(text).classes("explain mt-2")
    # 能进库的数据都过了三关，这个月有数据就说明三关都过了
    with ui.element("div").classes("badges mt-3"):
        for badge in ("✓ 文件金额核验通过", "✓ 来源流水可追溯", "个人口径请结合待核查事项"):
            ui.label(badge).classes("badge")
    if platform.cents:
        ui.echart(waterfall_option(expense)).classes("chart")
    with ui.element("div").classes("table mini-table mt-4"):
        with ui.element("div").classes("tr"):
            for head in ("收入和中性交易", "笔数", "金额"):
                ui.label(head)
        for line in lines:
            if line.direction != "支出":
                with ui.element("div").classes("tr"):
                    ui.label(f"{line.direction} · {line.label}")
                    ui.label(str(line.count))
                    ui.label(money(line.cents))



RENDERERS = {"overview": render_overview, "trend": render_trend, "upload": render_upload,
             "sort": render_sort, "recon": render_recon, "ask": render_ask, "review": render_review}


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
        try:
            conn = connect(db_path())
        except Exception as error:
            ui.label('本机数据库无法打开或升级').classes('title')
            ui.label(f'操作未完成（{type(error).__name__}）。请检查数据库文件权限与可用空间；如已生成升级备份，会保留在 data/backups/。不要在服务运行时覆盖数据库。').classes('note')
            return
        reclassify_unknown(conn)  # 程序更新、补了清洗规则以后，旧的“未识别”交易按新规则重新判断
        ctx = Context(conn)
        ui.context.client.on_disconnect(ctx.ask_session.stop)
        ui.context.client.on_disconnect(conn.close)
        from bill_pipeline import conversations as chats
        ui.timer(5, lambda: (chats.heartbeat_instance(conn,chats.INSTANCE_ID), chats.interrupt_owned_messages(conn,chats.INSTANCE_ID)))
        navs = {}

        def show(page: str) -> None:
            if ctx.page == "ask" and page != "ask":
                ctx.ask_session.stop()
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
            ctx.ask_session.stop()
            ctx.ask_session.default_month_notice = "默认月份已切换；新问题会使用所选月份，历史范围保持原样。"
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
