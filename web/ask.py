"""账单研究室：页面内会话、只读查询进度和可核查的依据。"""
import queue
import time
from dataclasses import dataclass, field
from decimal import Decimal

from nicegui import run, ui

from bill_pipeline import ai, assistant
from bill_pipeline.assistant_state import Answer, RunState, Step, Turn
from bill_pipeline.db import connect
from bill_pipeline import conversations as chats
from bill_pipeline.migrations import data_revision


@dataclass
class AskSession:
    turns: list[Turn] = field(default_factory=list)
    active_run: RunState | None = None
    selected_turn: int = -1
    mode: str = 'quick'
    draft: str = ''
    default_month_notice: str = ''
    current_question: str = ''
    current_month: str = ''
    current_steps: list[Step] = field(default_factory=list)
    progress: str = ''
    store: object = None
    conversation_id: str | None = None
    message_ids: list = field(default_factory=list)
    saved_messages: dict = field(default_factory=dict)
    active_message_id: str | None = None
    save_error: str = ''
    pending_save: tuple | None = None

    def attach(self,conn):
        self.store=conn
        chats.register_instance(conn,chats.INSTANCE_ID)
        chats.interrupt_owned_messages(conn,chats.INSTANCE_ID)
        saved=chats.list_conversations(conn)
        if saved:self.open(saved[0]['id'])

    def open(self,cid):
        self.stop()
        if self.pending_save:raise ValueError('有结果尚未保存，请先重试保存')
        messages=chats.load_turns(self.store,cid)
        self.conversation_id=cid
        self.turns=[chats.as_turn(m) for m in messages]
        self.message_ids=[m['id'] for m in messages]
        self.saved_messages={m['id']:m for m in messages}
        self.selected_turn=len(self.turns)-1
        self.save_error='';self.pending_save=None

    def begin(self,state,text,month):
        if self.store is None:return
        if self.conversation_id is None:self.conversation_id=chats.create_conversation(self.store)
        self.active_message_id=chats.begin_message(self.store,self.conversation_id,text,month,self.mode,state.run_id,chats.INSTANCE_ID)

    def persist(self,state,answer):
        if self.store is None:return
        mid=self.active_message_id
        self.message_ids.append(mid)
        self.pending_save=(mid,state.run_id,answer)
        self.retry_save()

    def retry_save(self):
        if not self.pending_save:return
        try:
            if not chats.finish_message(self.store,*self.pending_save):
                self.save_error='会话已删除或运行状态已变化，本次结果未保存。';self.pending_save=None;return
            self.saved_messages={m['id']:m for m in chats.load_turns(self.store,self.conversation_id)}
            self.pending_save=None;self.save_error=''
        except Exception as error:self.save_error=f'本机保存失败（{type(error).__name__}），当前回答仍在页面中，请重试保存。'

    def history(self):
        return [turn for i,turn in enumerate(self.turns)
                if self.saved_messages.get(self.message_ids[i] if i<len(self.message_ids) else None,{}).get('status',turn.answer.status) in ('complete','partial','timeout')]

    def stop(self):
        if self.active_run is None:
            return
        self.active_run.cancel.set()
        # UI 定时器可能还没消费刚完成的结果，停止时也应保留它们。
        while True:
            try:
                event = self.active_run.events.get_nowait()
            except queue.Empty:
                break
            if event.run_id == self.active_run.run_id and event.kind == 'result':
                self.current_steps.append(event.detail['step'])
        self.turns.append(Turn(self.current_question, self.current_month,
                               Answer('查询已停止，已取得的依据保留在右侧。', list(self.current_steps),
                                      status='cancelled', reason='已停止')))
        self.persist(self.active_run,self.turns[-1].answer)
        self.selected_turn = len(self.turns)-1
        self.active_run = None  # 迟到响应无法匹配新运行。

    def clear(self):
        self.stop()
        if self.pending_save:raise ValueError('有结果尚未保存，请先重试保存')
        self.turns.clear()
        self.conversation_id=None;self.message_ids.clear();self.saved_messages.clear()
        self.selected_turn = -1
        self.draft = ''
        self.default_month_notice = ''
        self.current_steps.clear()


def ask_in_thread(db_path, client, model, question, month, *, mode, history, run_state) -> Answer:
    conn = connect(db_path)
    try:
        return assistant.ask(client, model, conn, question, month, mode=mode, history=history, run_state=run_state)
    finally:
        conn.close()


def step_label(step: Step) -> str:
    name = assistant.TOOL_LABELS.get(step.tool, step.tool)
    args = '、'.join(str(v) for v in step.args.values())
    return f'{name}（{args}）' if args else name


def evidence_cards(answer: Answer) -> list[dict]:
    return [{'label': step_label(s), 'result': s.result} for s in answer.steps if 'error' not in s.result]


def comparison_view(answer: Answer) -> dict | None:
    return next((s.result for s in reversed(answer.steps)
                 if s.tool == 'compare_months' and 'error' not in s.result), None)


def render_result(result: dict):
    scope=[str(result[k]) for k in ('month','base_month','target_month','start_date','end_date') if result.get(k)]
    if scope:ui.label('查询范围：'+' — '.join(scope)).classes('ask-footnote')
    for key in ('trust','base_trust'):
        if result.get(key,{}).get('provisional'):
            ui.label('数据范围不足或有待核查项；这些数字为暂计口径。').classes('ask-footnote')
    labels = {'expense': '消费', 'income': '收入', 'net': '结余', 'delta': '变化',
              'category': '分类', 'amount': '金额', 'time': '时间', 'counterparty': '交易对方',
              'item': '商品', 'count': '笔数', 'direction': '方向', 'counted_as': '计入口径',
              'why': '原因', 'base': '基期', 'target': '本期', 'contribution_percent': '增长贡献 %',
              'date': '日期', 'key': '分组', 'month': '月份'}
    for key in ('expense', 'income', 'total', 'delta', 'change_percent'):
        if key in result and result[key] is not None:
            ui.label(f'{labels.get(key, {"total": "合计", "change_percent": "增幅 %"}.get(key, key))}　{result[key]}') \
                .classes('ask-footnote')
    for key in ('totals', 'base', 'target'):
        if isinstance(result.get(key), dict):
            ui.label(('全量合计' if key == 'totals' else labels[key]) + '　' +
                     ' · '.join(f'{labels.get(k, k)} {v}' for k, v in result[key].items())).classes('ask-footnote')
    coverage = result.get('coverage')
    if coverage:
        ui.label(f'实际交易范围：{coverage["first_date"] or "无"} — {coverage["last_date"] or "无"}').classes('ask-footnote')
        if coverage['missing_months']:
            ui.label('范围内无交易记录的月份：'+'、'.join(coverage['missing_months'])).classes('ask-footnote')
        ui.label(coverage.get('note','历史覆盖摘要；有交易不代表当月数据完整')).classes('ask-footnote')
    if result.get('history_snapshot'):
        ui.label('历史聚合快照，未保存逐笔明细；金额需重新查询。').classes('ask-footnote')
    if result.get('note'):
        ui.label(result['note']).classes('ask-footnote')
    for key in ('months', 'by_category', 'groups', 'days', 'rows'):
        rows = result.get(key)
        if not rows:
            continue
        columns = [{'name': k, 'label': labels.get(k, k), 'field': k, 'align': 'left'} for k in rows[0]]
        ui.table(columns=columns, rows=rows, pagination=5).props('dense flat').classes('w-full')


def render_ask(ctx) -> None:
    session = ctx.ask_session
    if ctx.month is None:
        ui.label('问问你的账单').classes('title')
        ui.label('还没有导入账单').classes('empty')
        ui.button('去导入', on_click=lambda: ctx.show('upload')).props('flat color=teal')
        return

    def redraw():
        if ctx.page == 'ask':
            content.refresh()

    def stop():
        session.stop()
        redraw()

    def clear():
        try:session.clear()
        except ValueError as error:ui.notify(str(error),type='warning')
        redraw()

    async def submit():
        text = session.draft.strip()
        if not text or session.active_run is not None:
            return
        if session.pending_save:
            ui.notify('请先重试保存上一条回答',type='warning');return
        state = RunState()
        try:session.begin(state,text,ctx.month)
        except Exception as error:
            session.save_error=f'本机保存失败（{type(error).__name__}），尚未发送给模型。';redraw();return
        session.active_run = state
        session.current_question, session.current_month = text, ctx.month
        session.current_steps = []
        session.progress = '正在准备查询…'
        session.draft = ''
        history = session.history()
        mode, month = session.mode, ctx.month
        redraw()
        try:
            client, model = ai.make_client()
            result = await run.io_bound(ask_in_thread, ctx.db_path, client, model, text, month,
                                        mode=mode, history=history, run_state=state)
        except ai.AIError as error:
            result = Answer(f'AI 这次没答上来：{error}', [], status='error', reason='调用失败')
        except Exception as error:
            result = Answer(f'查询暂时失败（{type(error).__name__}），可以重试。', [], status='error', reason='查询失败')
        if session.active_run is not state or state.cancel.is_set() or result is None:
            return
        session.turns.append(Turn(text, month, result))
        session.persist(state,result)
        session.selected_turn = len(session.turns)-1
        session.active_run = None
        redraw()

    def drain():
        state = session.active_run
        if state is None:
            return
        changed = False
        # 每个定时回调有界处理，避免大量事件阻塞 UI。
        for _ in range(100):
            try:
                event = state.events.get_nowait()
            except queue.Empty:
                break
            if event.run_id != state.run_id:
                continue
            if event.kind == 'query':
                session.progress = f'第 {event.batch} 批 · 正在{assistant.TOOL_LABELS.get(event.tool, event.tool)}'
                changed = True
            elif event.kind == 'result':
                session.current_steps.append(event.detail['step'])
                changed = True
        if changed:
            redraw()

    def select_turn(index):
        session.selected_turn = index
        redraw()

    @ui.refreshable
    def content():
        busy = session.active_run is not None
        with ui.element('section').classes('ask-room'):
            with ui.row().classes('w-full items-center justify-between'):
                with ui.column().classes('gap-1'):
                    ui.label('账单研究室').classes('ask-kicker')
                    ui.label('问问你的账单').classes('ask-title')
                ui.button('新对话', icon='add', on_click=clear).props('flat color=teal').mark('ask-new')
            if session.default_month_notice:
                ui.label(session.default_month_notice).classes('ask-footnote')
            if session.save_error:
                ui.label(session.save_error).classes('text-orange-9 text-sm').mark('ask-save-error')
                if session.pending_save:ui.button('重试保存',on_click=lambda:(session.retry_save(),redraw())).props('flat')
            if session.store is not None:
                with ui.expansion('本机会话',icon='history').classes('ask-conversations'):
                    ui.label('仅保存在本机；提交新问题时，必要上下文仍会发送给配置的模型。').classes('ask-footnote')
                    for conversation in chats.list_conversations(session.store):
                        cid=conversation['id']
                        def open_chat(cid=cid):
                            try:session.open(cid);redraw()
                            except Exception as error:ui.notify(f'打开失败（{type(error).__name__}）',type='negative')
                        def rename_chat(cid=cid,title=conversation['title']):
                            with ui.dialog() as dialog,ui.card().classes('w-80'):
                                name=ui.input('会话标题',value=title).classes('w-full')
                                def save():
                                    try:chats.rename_conversation(session.store,cid,name.value);dialog.close();redraw()
                                    except ValueError as error:ui.notify(str(error),type='warning')
                                ui.button('保存标题',on_click=save)
                            dialog.open()
                        def delete_chat(cid=cid):
                            try:
                                if session.conversation_id==cid:session.clear()
                                chats.set_deleted(session.store,cid,True);redraw()
                            except Exception as error:ui.notify(f'删除失败（{type(error).__name__}）',type='warning')
                        with ui.row().classes('w-full items-center no-wrap'):
                            ui.button(conversation['title'],on_click=open_chat).props('flat no-caps').classes('grow text-left')
                            ui.button(icon='edit',on_click=rename_chat).props('flat dense').tooltip('重命名')
                            ui.button(icon='delete_outline',on_click=delete_chat).props('flat dense').tooltip('移到回收站')
                    with ui.expansion('回收站').classes('w-full'):
                        for conversation in chats.list_conversations(session.store,deleted=True):
                            cid=conversation['id']
                            ui.label(conversation['title']).classes('ask-footnote')
                            ui.button('恢复',on_click=lambda cid=cid:(chats.set_deleted(session.store,cid,False),redraw())).props('flat dense')
                            def purge(cid=cid,title=conversation['title']):
                                with ui.dialog() as dialog,ui.card().classes('w-80'):
                                    ui.label('永久删除会话：'+title)
                                    ui.label('本次会删除问题、回答和依据；本机数据库备份可能仍保留旧内容。').classes('ask-footnote')
                                    ui.button('取消',on_click=dialog.close).props('flat')
                                    ui.button('确认永久删除',on_click=lambda:(chats.purge_conversation(session.store,cid),dialog.close(),redraw())).props('color=negative')
                                dialog.open()
                            ui.button('永久删除',on_click=purge).props('flat dense color=negative')
            with ui.element('div').classes('ask-workspace'):
                with ui.column().classes('ask-main'):
                    if session.turns:
                        with ui.row().classes('ask-history'):
                            for i, turn in enumerate(session.turns):
                                ui.button(f'{i+1} · {turn.question[:18]}', on_click=lambda i=i: select_turn(i)) \
                                    .props('flat dense no-caps color=teal').classes('ask-history-item')
                    answer = None
                    if busy:
                        ui.label(session.current_question).classes('ask-question')
                        ui.label(session.progress).classes('ask-progress').mark('ask-status')
                        ui.label(f'已取得 {sum("error" not in s.result for s in session.current_steps)} 项查询结果').classes('ask-footnote')
                        ui.linear_progress().props('indeterminate color=teal').classes('w-full')
                        answer = Answer('', list(session.current_steps))
                    elif session.turns:
                        turn = session.turns[session.selected_turn]
                        answer = turn.answer
                        mid=session.message_ids[session.selected_turn] if session.message_ids else None
                        saved=session.saved_messages.get(mid)
                        if saved and chats.is_stale(saved,data_revision(session.store)):
                            ui.label('账单已变化，旧答案需重新核查').classes('ask-stale').mark('ask-stale')
                            async def reanalyze():
                                session.draft=turn.question
                                await submit()
                            ui.button('重新分析此问题',on_click=reanalyze).props('flat color=teal')
                        ui.label(turn.question).classes('ask-question')
                        labels = {'complete': '分析完成', 'partial': '阶段性回答', 'cancelled': '已停止',
                                  'timeout': '时间预算已用尽', 'error': '暂未完成'}
                        ui.label(f'{labels[answer.status]} · {answer.batches} 批查询 · {answer.elapsed:.1f} 秒') \
                            .classes('ask-progress').mark('ask-status')
                        if answer.reason:
                            ui.label(answer.reason).classes('ask-footnote')
                        comp = comparison_view(answer)
                        if comp:
                            with ui.element('div').classes('ask-metrics'):
                                for label, amount in [(comp['base_month']+' 消费', comp['base']['expense']),
                                                      (comp['target_month']+' 消费', comp['target']['expense']),
                                                      ('消费变化', comp['delta'])]:
                                    with ui.element('div').classes('ask-metric'):
                                        ui.label(label).classes('ask-footnote')
                                        ui.label(f'¥{Decimal(amount):,.2f}').classes('ask-money')
                        ui.markdown(answer.text).classes('answer-text ask-answer')
                        if comp:
                            ui.echart({'tooltip': {'trigger': 'axis'},
                                       'grid': {'left': 55, 'right': 20, 'bottom': 35, 'top': 20},
                                       'xAxis': {'type': 'category', 'data': [comp['base_month'], comp['target_month']]},
                                       'yAxis': {'type': 'value', 'name': '元'},
                                       'series': [{'type': 'bar', 'barWidth': '30%', 'itemStyle': {'color': '#158465', 'borderRadius': [5,5,0,0]},
                                                   'data': [float(comp['base']['expense']), float(comp['target']['expense'])]}]}) \
                                .classes('w-full h-52')
                        if answer.steps:
                            with ui.expansion('这次查了什么').classes('w-full steps'):
                                for step in answer.steps:
                                    ui.label(step_label(step)).classes('note')
                                    if 'error' in step.result:
                                        ui.label(step.result['error']).classes('ask-footnote')
                    else:
                        ui.label('让每一个回答，\n都有据可查。').classes('ask-welcome')
                        ui.label('从一笔消费，到几个月的变化。先问一个你关心的问题。').classes('ask-intro')
                        for i, text in enumerate(('这个月花得最多的是哪一类？', '这个月哪天花得最多？', '比较最近两个月的分类消费变化')):
                            ui.button(text, icon='north_east', on_click=lambda text=text: question.set_value(text)) \
                                .props('flat no-caps align=left').classes('ask-example').mark(f'ask-example-{i}')
                    with ui.column().classes('ask-composer'):
                        question = ui.input(placeholder='继续追问，或问一个关于账单的新问题', value=session.draft,
                                            on_change=lambda e: setattr(session, 'draft', e.value)) \
                            .props('borderless autogrow').classes('w-full').mark('question')
                        question.on('keydown.enter', submit)
                        if busy:
                            question.disable()
                        with ui.row().classes('w-full items-center justify-between'):
                            mode = ui.select({'quick': '快速问答', 'deep': '深度分析'}, value=session.mode,
                                             on_change=lambda e: setattr(session, 'mode', e.value)) \
                                .props('borderless dense options-dense').classes('ask-mode').mark('ask-mode')
                            if busy:
                                mode.disable()
                                ui.button('停止', icon='stop', on_click=stop).props('outline color=teal').mark('ask-stop')
                            else:
                                ui.button('提问', icon='arrow_upward', on_click=submit).props('unelevated color=teal').mark('ask-btn')
                    ui.label('数值来自账单查询 · 个人交易对方脱敏 · 对话仅保存在本机').classes('ask-footnote')
                with ui.column().classes('ask-evidence'):
                    ui.label('本次分析的依据').classes('ask-evidence-title')
                    cards = evidence_cards(answer) if answer else []
                    if not cards:
                        ui.icon('fact_check').classes('text-3xl text-teal-7 mt-4')
                        ui.label('查询完成后，这里会显示数据范围、合计与明细。').classes('ask-footnote')
                        ui.label('先看结论，再核对依据。').classes('ask-footnote')
                    for i, card in enumerate(cards):
                        result = card['result']
                        with ui.expansion(f'{i+1:02d}  {card["label"]}').classes('ask-evidence-card'):
                            rows = result.get('rows', [])
                            if 'count' in result:
                                ui.label(f'全量匹配 {result["count"]} 笔 · 返回 {len(rows)} 笔').classes('ask-footnote')
                            if result.get('truncated') or ('count' in result and result['count'] > len(rows)):
                                ui.label('明细已截断；合计按全部匹配交易计算').classes('ask-footnote')
                            render_result(result)
                    ui.label('账单可以说明变化；消费动机需要更多背景。').classes('ask-footnote mt-6')

    content()
    ui.timer(0.15, drain)
