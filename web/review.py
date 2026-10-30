"""本机核查入口：所有账单调整都先展示预览，再由用户确认。"""
import json
from nicegui import ui
from bill_pipeline.adjustments import (effective_transactions,list_review_issues,transaction,confirm_refund,revoke_refund,
    set_transaction_categories,clear_transaction_categories,create_advance,allocate_repayment,revoke_advance,
    revoke_repayment,set_counterparty_alias,resolve_refund_review)
from bill_pipeline.convert import to_cents,yuan
from bill_pipeline.coverage import trust_info,set_expected_sources
from bill_pipeline.db import categories,set_category
from bill_pipeline.observations import select_observation
from bill_pipeline.model import BillError


def render_trust_banner(ctx):
    if not ctx.month:return
    info=trust_info(ctx.conn,ctx.month)
    with ui.expansion('数据范围与核查状态',icon='verified_user').classes('trust-banner'):
        ui.label(f'待核查 {info["pending_reviews"]} 项 · '+('当前为暂计口径' if info['provisional'] else '已导入来源覆盖此月')).classes('note')
        for source,item in info['coverage']['sources'].items():
            ui.label(source+'：'+('覆盖此月' if item['complete'] else '存在缺口或范围待确认')).classes('note')
            for a,b in item['intervals']:ui.label(f'已覆盖 {a} — {b}').classes('note')
            if item['unknown_metadata']:ui.label('有导入文件缺少可信导出时间或全部交易范围声明，不能确认完整。').classes('note')
            for a,b in item['gaps']:ui.label(f'未确认覆盖 {a} — {b}').classes('note')
        ui.label('文件核验通过不代表所有月份、所有来源或个人消费口径均已核查。').classes('note')
        ui.button('去核查',on_click=lambda:ctx.show('review')).props('flat dense color=teal')


def render_review(ctx):
    ui.label('交易核查与调整').classes('title')
    ui.label('来源流水保留原样；退款、分类与垫款通过可撤销的个人调整计算。').classes('note')
    chosen=[None]

    def execute(action,dialog):
        try:
            action()
        except (ValueError,BillError) as error:
            ui.notify(str(error),type='warning');return
        except Exception as error:
            ui.notify(f'保存失败（{type(error).__name__}），未完成操作',type='negative');return
        dialog.close();ui.notify('已保存，可返回总览核对');body.refresh()

    def preview(text,action):
        with ui.dialog() as dialog,ui.card().classes('review-dialog'):
            ui.label('确认这次调整').classes('text-lg font-bold')
            ui.label(text).classes('whitespace-pre-wrap')
            ui.label('只修改个人计入口径，原始导入证据保留。').classes('note')
            with ui.row():
                ui.button('取消',on_click=dialog.close).props('flat')
                ui.button('确认保存',on_click=lambda:execute(action,dialog)).mark('review-confirm')
        dialog.open()

    @ui.refreshable
    def body():
        rows=effective_transactions(ctx.conn)
        if not rows:
            ui.label('还没有导入账单').classes('empty');return
        keys={i:(t['source'],t['tx_id']) for i,t in enumerate(rows)}
        labels={i:f'{t["source"]} · {t["tx_time"][:16]} · {t["counterparty"]} · ¥{yuan(t["amount_cents"])}' for i,t in enumerate(rows)}
        if chosen[0] not in keys:chosen[0]=0
        def choose(value):chosen[0]=value;body.refresh()
        pending=list_review_issues(ctx.conn)
        with ui.expansion(f'待核查事项 · {len(pending)} 项',value=bool(pending)).classes('w-full'):
            for problem in pending:
                index=next((i for i,key in keys.items() if key==(problem['source'],problem['tx_id'])),None)
                ui.button(f'{problem["kind"]} · {problem["tx_time"][:10]} · {problem["counterparty"]}',
                          on_click=lambda index=index:choose(index)).props('flat no-caps color=teal')
                if problem['kind']=='退款待核查':
                    pk=(problem['source'],problem['tx_id'])
                    ui.button('已核实，保留当前个人口径',on_click=lambda pk=pk:preview('请先核实该笔是否需退款冲减。确认后将记录你的结论，金额保持当前口径，不由AI决定。',
                              lambda:resolve_refund_review(ctx.conn,pk,'用户已核实，保留当前个人口径'))).props('flat dense')
            if not pending:ui.label('暂无待核查事项').classes('note')
        ui.select(labels,value=chosen[0],label='选择要查看或调整的交易',on_change=lambda e:choose(e.value)) \
            .props('outlined use-input options-dense').classes('w-full').mark('review-transaction')
        key=keys[chosen[0]];tx=transaction(ctx.conn,key,'effective_transactions')
        ui.label(f'来源金额 ¥{yuan(tx["amount_cents"])} · 当前个人计入 ¥{yuan(tx["counted_cents"])} · {tx["status"]}').classes('review-summary')
        with ui.expansion('只改这一笔的分类 / 拆分',value=tx['result']=='消费').classes('w-full'):
            ui.label('每行填写“分类 金额”，例如“吃饭 10.00”。合计必须等于当前个人消费。').classes('note')
            split=ui.textarea('分类与金额（元）',placeholder='运动 10.00').props('outlined').classes('w-full').mark('review-split')
            existing=ctx.conn.execute('SELECT category,counted_cents FROM effective_allocations WHERE source=? AND tx_id=?',key).fetchall()
            if existing:ui.label('当前分配：'+'、'.join(f'{c} ¥{yuan(n)}' for c,n in existing)).classes('note')
            def save_split():
                try:
                    allocations=[]
                    for line in (split.value or '').splitlines():
                        if line.strip():
                            category,amount=line.strip().rsplit(maxsplit=1);allocations.append((category,to_cents(amount)))
                    preview('将这一笔个人消费拆分为：\n'+'\n'.join(f'{c} ¥{yuan(n)}' for c,n in allocations),
                            lambda:set_transaction_categories(ctx.conn,key,allocations))
                except (ValueError,BillError):ui.notify('请每行填写分类和金额，例如“运动 10.00”',type='warning')
            with ui.row():
                ui.button('预览单笔分类',on_click=save_split).mark('review-split-preview')
                ui.button('恢复默认分类',on_click=lambda:preview('解除这一笔的人工分类。',lambda:clear_transaction_categories(ctx.conn,key))).props('flat')
            default=ui.select(categories(ctx.conn),label='此商户默认分类').props('outlined').classes('w-full')
            ui.button('设置商户默认分类',on_click=lambda:preview('以后使用该商户默认类别；单笔覆盖仍优先。',lambda:set_category(ctx.conn,tx['counterparty'],default.value))).props('flat')
            canonical=ui.input('合并到已有商户名（仅默认分类）').props('outlined').classes('w-full')
            ui.button('确认商户别名',on_click=lambda:preview('仅共享商户默认分类，不合并来源单号。',lambda:set_counterparty_alias(ctx.conn,key[0],tx['counterparty'],canonical.value))).props('flat')
        with ui.expansion('退款关联 / 部分退款待核查').classes('w-full'):
            expense_options={i:labels[i] for i,t in enumerate(rows) if t['direction']=='支出'}
            refund_options={i:labels[i] for i,t in enumerate(rows) if t['direction']!='支出'}
            expense=ui.select(expense_options,label='原消费（必选）').props('outlined use-input').classes('w-full')
            refund=ui.select(refund_options,label='退款入账记录（无独立记录可留空）',clearable=True).props('outlined use-input').classes('w-full')
            amount=ui.input('本次确认退款金额（元）').props('outlined').classes('w-full')
            events=ctx.conn.execute('SELECT id,expense_source,expense_id,cents FROM refund_events WHERE revoked_at IS NULL').fetchall()
            old_event=ui.select({r[0]:f'已有事件 · {r[1]} · ¥{yuan(r[3])} · {r[0][:6]}' for r in events},label='同一笔退款的补充证据？选已有事件；新退款留空',clearable=True).props('outlined').classes('w-full')
            def save_refund():
                try:
                    if expense.value is None:raise ValueError('请先选原消费')
                    cents=to_cents(amount.value);ek=keys[expense.value];rk=keys[refund.value] if refund.value is not None else None;eid=old_event.value
                    preview(f'将退款 ¥{yuan(cents)} 关联到 {labels[expense.value]}。\n'+('作为已有退款的补充证据，不重复扣减。' if eid else '确认为独立退款事件；消费回溯到原月份。'),
                            lambda:confirm_refund(ctx.conn,ek,rk,cents,event_id=eid))
                except (ValueError,BillError) as error:ui.notify(str(error),type='warning')
            ui.button('预览退款关联',on_click=save_refund).mark('review-refund-preview')
            for eid,source,tid,cents in events:
                ui.button(f'解除退款关联 ¥{yuan(cents)} · {eid[:6]}',on_click=lambda eid=eid:preview('解除该事件及证据关联，重新核查退款。',lambda:revoke_refund(ctx.conn,eid))).props('flat')
        with ui.expansion('AA 与个人承担 / 收回垫款').classes('w-full'):
            ui.label('当前选中交易作为垫付款；未收回的垫款另列，不当作个人消费。').classes('note')
            personal=ui.input('个人承担金额（元）').props('outlined').classes('w-full')
            def save_advance():
                try:
                    cents=to_cents(personal.value)
                    preview(f'个人承担 ¥{yuan(cents)}，剩余净支出为替他人垫款。',lambda:create_advance(ctx.conn,key,cents))
                except BillError as error:ui.notify(str(error),type='warning')
            ui.button('预览垫款分配',on_click=save_advance)
            groups=ctx.conn.execute('SELECT id,source,tx_id,net_snapshot,personal_cents FROM advance_groups WHERE revoked_at IS NULL').fetchall()
            group=ui.select({r[0]:f'{r[1]} · 垫款¥{yuan(r[3]-r[4])} · {r[0][:6]}' for r in groups},label='选择垫款组').props('outlined').classes('w-full')
            income=ui.select({i:labels[i] for i,t in enumerate(rows) if t['result']=='收入'},label='选择收回款').props('outlined use-input').classes('w-full')
            recovered=ui.input('本次分配收回金额（元）').props('outlined').classes('w-full')
            def save_repayment():
                try:
                    if not group.value or income.value is None:raise ValueError('请选择垫款组和收款')
                    gid=group.value;ik=keys[income.value];cents=to_cents(recovered.value)
                    preview(f'收回 ¥{yuan(cents)} 作为垫款归还，不再计普通收入。',lambda:allocate_repayment(ctx.conn,gid,ik,cents))
                except (ValueError,BillError) as error:ui.notify(str(error),type='warning')
            ui.button('预览收回款分配',on_click=save_repayment)
            for gid,source,tid,net,own in groups:
                collected=ctx.conn.execute('SELECT COALESCE(SUM(cents),0) FROM repayment_allocations WHERE advance_id=? AND revoked_at IS NULL',(gid,)).fetchone()[0]
                ui.label(f'{gid[:6]} · 自付¥{yuan(own)} · 待收回¥{yuan(max(0,net-own-collected))}').classes('note')
                ui.button('解除垫款组 '+gid[:6],on_click=lambda gid=gid:preview('解除垫款组，相关收入分配一并停止生效。',lambda:revoke_advance(ctx.conn,gid))).props('flat')
            for rid,cents in ctx.conn.execute('SELECT id,cents FROM repayment_allocations WHERE revoked_at IS NULL'):
                ui.button(f'解除收回款分配 ¥{yuan(cents)} · {rid[:6]}',on_click=lambda rid=rid:preview('解除这次收款分配。',lambda:revoke_repayment(ctx.conn,rid))).props('flat')
        with ui.expansion('来源快照冲突').classes('w-full'):
            observations=ctx.conn.execute('SELECT id,exported_at,payload_json FROM transaction_observations WHERE source=? AND tx_id=? ORDER BY id DESC',key).fetchall()
            for oid,exported,payload in observations:
                data=json.loads(payload)
                ui.label(f'{exported or "导出时间未知"} · {data["status"]} · ¥{yuan(data["amount_cents"])}').classes('note')
                ui.button('采用此快照',on_click=lambda oid=oid:preview('采用此来源快照，相关退款、AA和拆分可能需重新核查。',lambda:select_observation(ctx.conn,oid))).props('flat')
        with ui.expansion('应包含的来源与覆盖').classes('w-full'):
            saved=ctx.conn.execute("SELECT value FROM preferences WHERE name='expected_sources'").fetchone()
            sources=ui.select(['微信','支付宝'],value=json.loads(saved[0]) if saved else sorted({t['source'] for t in rows}),multiple=True,label='我应该包含的来源').props('outlined').classes('w-full')
            ui.button('保存来源范围',on_click=lambda:preview('按所选来源检查遗漏，不估算补齐金额。',lambda:set_expected_sources(ctx.conn,sources.value))).props('flat')
            render_trust_banner(ctx)
        with ui.expansion('全部交易（个人口径）').classes('w-full'):
            columns=[{'name':k,'field':k,'label':v,'align':'left'} for k,v in [('tx_time','时间'),('source','来源'),('counterparty','交易对方'),('category','分类'),('original','来源金额'),('personal','个人计入')]]
            ui.table(columns=columns,rows=[{**t,'original':yuan(t['amount_cents']),'personal':yuan(t['counted_cents'])} for t in rows],pagination=10).classes('w-full').props('flat dense')
    body()
