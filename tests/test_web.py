import json

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing import User

from bill_pipeline.db import connect, month_by_category, save_suggestions, set_category
from bill_pipeline.pipeline import import_bill
from bill_pipeline.rules import EXPENSE, KNOWN
from tests.fakes import SAMPLE_ROWS, FakeLLM, make_row, write_wechat_xlsx


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setenv("BILL_DB", str(path))
    return path


async def test_overview_empty(user: User, db):
    await user.open("/")
    await user.should_see("还没有导入账单")


async def test_overview_with_data(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    await user.should_see("10 月消费")
    await user.should_see("¥85.50")
    await user.should_see("71%")  # 列表里“未归类”的占比；“花得最多”画在图表内部，模拟测试看不到
    await user.should_see(kind=ui.echart)


async def test_trend_page_modes(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-trend").click()
    await user.should_see("花钱的节奏")
    await user.should_see("10-02 花得最多：¥40.00")
    user.find(marker="trend-mode").elements.pop().set_value("表格")
    await user.should_see("比上月")
    await user.should_see("¥85.50")


async def _upload(user: User, name: str, data: bytes) -> None:
    await user.should_see(marker="upload")  # 切页是后台重画，等上传组件真的出现
    upload = user.find(marker="upload").elements.pop()
    await upload.handle_uploads([SmallFileUpload(name=name, content_type="application/octet-stream", _data=data)])


async def test_upload_imports_file(user: User, db, tmp_path):
    await user.open("/")
    user.find(marker="nav-upload").click()
    await _upload(user, "b.xlsx", write_wechat_xlsx(tmp_path / "b.xlsx").read_bytes())
    await user.should_see("新增 9 笔 · 跳过 0 笔")
    await user.should_see("第三关：不重复")


async def test_upload_rejects_bad_file_but_keeps_others(user: User, db, tmp_path):
    await user.open("/")
    user.find(marker="nav-upload").click()
    await _upload(user, "bad.xlsx", b"not an excel file")
    await _upload(user, "b.xlsx", write_wechat_xlsx(tmp_path / "b.xlsx").read_bytes())
    await user.should_see("bad.xlsx 拒收")
    await user.should_see("新增 9 笔 · 跳过 0 笔")


async def test_sort_page_saves_and_finishes(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see("第 1 / 3 个")
    await user.should_see("星光球馆")
    user.find(marker="chip-运动").click()
    await user.should_see("第 2 / 3 个")
    user.find(marker="chip-吃饭").click()
    await user.should_see("第 3 / 3 个")  # 换卡片也是后台重画，等新卡片出来再点
    user.find(marker="chip-吃饭").click()
    await user.should_see("都归好类了")


async def test_sort_page_recategorize(user: User, db, tmp_path):
    conn = connect(db)
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    for name, category in (("星光球馆", "运动"), ("食堂一楼", "吃饭"), ("张阿姨", "吃饭")):
        set_category(conn, name, category)
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see("都归好类了")
    user.find(marker="recat-星光球馆").elements.pop().set_value("娱乐")
    assert ("娱乐", 4000) in month_by_category(connect(db), "2026-10")


async def test_recon_page(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-recon").click()
    await user.should_see("这个月账单里的支出是 ¥112.30，其中全额退款的原交易 ¥26.80 不算消费，所以实际消费是 ¥85.50。")
    await user.should_see("✓ 对账平了")


async def test_recon_page_without_expense(user: User, db, tmp_path):
    only_income = [r for r in SAMPLE_ROWS if r["收/支"] != "支出"]
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx", rows=only_income), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-recon").click()
    await user.should_see("这个月没有支出记录。")


async def test_overview_category_dialog(user: User, db, tmp_path):
    conn = connect(db)
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    set_category(conn, "食堂一楼", "吃饭")
    await user.open("/")
    user.find(marker="legend-吃饭").click()
    await user.should_see("吃饭 · 10 月")
    await user.should_see("10-01 12:00　食堂一楼")


async def _open_add_dialog(user: User, db, tmp_path) -> None:
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see(marker="add-category")
    user.find(marker="add-category").click()
    await user.should_see(marker="new-category-name")


async def test_add_category_from_sort_page(user: User, db, tmp_path):
    await _open_add_dialog(user, db, tmp_path)
    user.find(marker="new-category-name").type("宠物")
    user.find(marker="new-category-ok").click()
    await user.should_see(marker="chip-宠物")


async def test_add_duplicate_category_shows_error(user: User, db, tmp_path):
    await _open_add_dialog(user, db, tmp_path)
    user.find(marker="new-category-name").type("吃饭")
    user.find(marker="new-category-ok").click()
    await user.should_see("已经有这个分类了")


async def test_ai_suggestion_under_card(user: User, db, tmp_path, monkeypatch):
    reply = {"suggestions": [{"name": "星光球馆", "category": "运动"}, {"name": "食堂一楼", "category": "吃饭"}]}
    llm = FakeLLM([{"content": json.dumps(reply, ensure_ascii=False)}])
    monkeypatch.setattr("bill_pipeline.ai.make_client", lambda: (llm, "fake"))
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see("AI 建议：运动")
    user.find(marker="ai-accept").click()
    await user.should_see("AI 建议：吃饭")
    await user.should_see("AI 建议准确率：1 / 1（100%）")
    user.find(marker="ai-accept").click()
    await user.should_see("付给个人的钱不发给 AI")  # 第三张是张阿姨
    assert len(llm.calls) == 1 and "张阿姨" not in llm.sent_text()


async def test_ai_suggest_error_shown(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see("AI 这次没给出建议：AI 还没配置")  # conftest 让测试看不到 key
    user.find(marker="chip-运动").click()  # 手动归类照常能用
    await user.should_see("第 2 / 3 个")


async def _ask(user: User, db, tmp_path, question: str) -> None:
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-ask").click()
    await user.should_see(marker="question")
    user.find(marker="question").type(question)


async def test_ask_page_answers(user: User, db, tmp_path, monkeypatch):
    llm = FakeLLM([{"tool_calls": [("month_summary", {"month": "2026-10"})]}, {"content": "10 月一共花了 ¥85.50。"}])
    monkeypatch.setattr("bill_pipeline.ai.make_client", lambda: (llm, "fake"))
    await _ask(user, db, tmp_path, "这个月花了多少")
    user.find(marker="ask-btn").click()
    await user.should_see("10 月一共花了 ¥85.50。")
    await user.should_see("这次查了什么")
    await user.should_see("月度汇总（2026-10）")


async def test_ask_without_config(user: User, db, tmp_path):
    await _ask(user, db, tmp_path, "这个月花了多少")
    user.find(marker="question").trigger("keydown.enter")  # 回车也能提问
    await user.should_see("AI 还没配置")


async def test_ask_follows_up_and_new_conversation(user: User, db, tmp_path, monkeypatch):
    llm = FakeLLM([{'content': '第一答'}, {'content': '第二答'}])
    monkeypatch.setattr('bill_pipeline.ai.make_client', lambda: (llm, 'fake'))
    await _ask(user, db, tmp_path, '第一个问题')
    user.find(marker='ask-btn').click()
    await user.should_see('第一答')
    user.find(marker='question').clear().type('然后呢')
    user.find(marker='ask-btn').click()
    await user.should_see('第二答')
    assert '第一个问题' in str(llm.calls[-1]['messages'])
    user.find(marker='nav-trend').click()
    user.find(marker='nav-ask').click()
    await user.should_see('第二答')
    user.find(marker='ask-new').click()
    await user.should_not_see('第二答')


async def test_ask_example_only_fills(user: User, db, tmp_path):
    await _ask(user, db, tmp_path, '')
    user.find(marker='ask-example-0').click()
    assert user.find(marker='question').elements.pop().value
    await user.should_see('本次分析的依据')


async def test_ask_stop_keeps_evidence_and_rejects_late_reply(user: User, db, tmp_path, monkeypatch):
    import asyncio
    import threading
    release = threading.Event()
    slow = FakeLLM([{'tool_calls':[('list_months', {})]}, {'content':'不应显示的迟到回答'}])
    fast = FakeLLM([{'content':'新的回答'}])
    original = slow.chat.completions.create
    def block_second(**kw):
        if len(slow.calls) == 1:
            release.wait(5)
        return original(**kw)
    slow.chat.completions.create = block_second
    clients = iter([slow, fast])
    monkeypatch.setattr('bill_pipeline.ai.make_client', lambda: (next(clients), 'fake'))
    await _ask(user, db, tmp_path, '先查月份')
    user.find(marker='ask-btn').click()
    try:
        await user.should_see('已取得 1 项查询结果')
        user.find(marker='ask-stop').click()
        await user.should_see('已停止')
        await user.should_see('这次查了什么')
        user.find(marker='question').type('新问题')
        user.find(marker='ask-btn').click()
        await user.should_see('新的回答')
    finally:
        release.set()
    await asyncio.sleep(0.05)
    await user.should_see('新的回答')
    await user.should_not_see('不应显示的迟到回答')


async def test_ask_deep_mode_reaches_beyond_five_batches(user: User, db, tmp_path, monkeypatch):
    llm = FakeLLM([{'tool_calls':[('search_transactions', {'limit':n})]} for n in range(1,8)] + [{'content':'深度回答完成'}])
    monkeypatch.setattr('bill_pipeline.ai.make_client', lambda: (llm, 'fake'))
    await _ask(user, db, tmp_path, '复杂问题')
    user.find(marker='ask-mode').elements.pop().set_value('deep')
    user.find(marker='ask-btn').click()
    await user.should_see('深度回答完成')
    await user.should_see('7 批查询')
    assert len(llm.calls) == 8


async def test_ask_partial_answer_visible(user: User, db, tmp_path, monkeypatch):
    llm = FakeLLM([{'tool_calls':[('search_transactions', {'limit':n})]} for n in range(1,6)] + [{'content':'已经查到的结论'}])
    monkeypatch.setattr('bill_pipeline.ai.make_client', lambda: (llm, 'fake'))
    await _ask(user, db, tmp_path, '复杂问题')
    user.find(marker='ask-btn').click()
    await user.should_see('阶段性回答')
    await user.should_see('已经查到的结论')


async def test_ask_changed_month_is_explicit(user: User, db, tmp_path, monkeypatch):
    llm = FakeLLM([{'content':'第一答'}, {'content':'第二答'}])
    monkeypatch.setattr('bill_pipeline.ai.make_client', lambda: (llm, 'fake'))
    await _ask(user, db, tmp_path, '这个月呢')
    # 为测试构建第二个月，重开页面刷新月份选择器。
    conn = connect(db)
    with conn:
        conn.execute("UPDATE transactions SET tx_time='2026-09-01 12:00:00' WHERE counterparty='星光球馆'")
    conn.close()
    await user.open('/')
    user.find(marker='nav-ask').click()
    await user.should_see(marker='question')
    user.find(marker='question').type('这个月呢')
    user.find(marker='ask-btn').click()
    await user.should_see('第一答')
    user.find(marker='month').elements.pop().set_value('2026-09')
    await user.should_see('默认月份已切换')
    user.find(marker='question').type('那现在呢')
    user.find(marker='ask-btn').click()
    await user.should_see('第二答')
    assert '默认是 2026-09' in llm.calls[-1]['messages'][0]['content']
    assert '这个月呢' in str(llm.calls[-1]['messages'])


async def test_recategorize_updates_ai_accuracy(user: User, db, tmp_path):
    conn = connect(db)
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    save_suggestions(conn, {"星光球馆": "运动"}, "fake")
    set_category(conn, "星光球馆", "运动")  # 采用了 AI 的建议
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see("AI 建议准确率：1 / 1（100%）")
    user.find(marker="recat-星光球馆").elements.pop().set_value("娱乐")  # 后来又改了主意
    await user.should_see("AI 建议准确率：0 / 1（0%）")


async def test_page_load_applies_new_rules(user: User, db, tmp_path, monkeypatch):
    rows = SAMPLE_ROWS + [make_row(10, 10, 12, "某新类型", "某商户", "支出", 30.0, "支付成功")]
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx", rows=rows), "b.xlsx")
    monkeypatch.setitem(KNOWN, ("支出", "某新类型", "支付成功"), (EXPENSE, "消费", None))  # 程序更新后补了规则
    await user.open("/")
    await user.should_see("¥115.50")  # 原来的 85.50 加上这笔 30
