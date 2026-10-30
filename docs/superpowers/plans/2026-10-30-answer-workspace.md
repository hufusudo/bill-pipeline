# Answer Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 A「账单研究室」及可连续追问、有明确预算、可追溯依据的复杂账单问答。

**Architecture:** 保留 NiceGUI 与 SQLite；数据库负责确定性计算，assistant 负责工具协议，独立运行状态负责取消和进度。主 UI 通过队列接收工作线程事件，按运行标识隔离迟到结果。

**Tech Stack:** 项目现有 Python、NiceGUI 3.18.0、OpenAI SDK 3.35.1、SQLite、pytest；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-30-answer-workspace-design.md`，用户已于 2026-10-30 审阅通过。

## Global Constraints

- 快速模式允许最多 5 批工具查询；深度模式允许最多 15 批；每批最多执行 6 个工具。
- 查询阶段时间预算：快速 60 秒、深度 180 秒；总结阶段另限 30 秒。
- 单次模型请求不超过 30 秒和阶段剩余时间；本题关闭 SDK 自动重试。
- 连续两批没有新增成功查询时提前总结；预算耗尽后最多一次禁止工具的总结请求。
- 最多最近 6 组历史问答；每组问题/回答/依据摘要分别最多 2,000/6,000/4,000 字符，截断显式标记。
- 日期范围两端包含、最多 366 天；每页最多 50 条明细；缺账单不等于零消费。
- 不修改 .env，不安装系统包，不改系统配置，不自动调用真实付费模型。
- 所有查询只读、参数化 SQL；对个人隐藏姓名和商品文本；指标不从自由文本猜取。
- 沿用现有计入口径、导航、主题；演示金额不得硬编码进产品。

## Review Focus

1. 相同时间的多平台交易：分页按 `(tx_time DESC, source, tx_id)` 稳定排序，无重复遗漏（Task 1）。
2. 下降或零基期对比：不除零，不将下降误称增长贡献（Task 1）。
3. 模型无视最终禁用工具或同批请求超过 6 项：协议完整且有界结束（Task 3）。
4. 停止后立即重问、切页或清空：旧线程不得覆盖新回答（Task 5）。
5. 导入/归类改变后继续问旧月份：历史只作语义背景，金额重新查询（Task 4、5）。

## 文件与责任

- `bill_pipeline/db.py`：扩展查询条件、稳定排序、日期范围聚合。
- `bill_pipeline/assistant.py`：现有工具、两项新工具、工具协议与循环。
- 新建 `bill_pipeline/assistant_state.py`：预算、进度事件、结果类型、会话摘要与运行状态。
- 新建 `web/ask.py`：A 布局、输入、会话展示、工作线程与队列接入。
- `web/pages.py`：Context 接入、月份/面板切换；移除被迁移的问答实现。
- `web/theme.py`：问答页局部样式。
- `tests/test_assistant.py`、`tests/test_db.py`、`tests/fakes.py`、`tests/test_web.py`；新建 `tests/test_assistant_state.py`：对应测试。
- `README.local.zh-CN.md`、`docs/design.md`：用户操作与实际边界。

按任务顺序串行落实接口。每项仅一个修改者；任务完成后检查差异再交接，不同时派人修改 assistant.py 或 pages.py。执行方式待用户选择；推荐主 Sol 连续实施，完成后独立复核。

### Task 1：可验证的组合查询与分页

**Files:** 修改 db.py、assistant.py、test_db.py、test_assistant.py。

**Interfaces:**
- 扩展 `find_transactions(conn, month=None, category=None, keyword=None, *, start_date=None, end_date=None) -> list[Found]`，保留旧调用方式。
- 增加 DB `range_totals(conn, start_date: str, end_date: str, group_by: str) -> dict`，group_by 为 day/month/category；只输出聚合与覆盖信息。
- 增加工具 `compare_months(conn, base_month: str, target_month: str) -> dict`、`range_summary(conn, start_date: str, end_date: str, group_by: str = 'month') -> dict`。
- 扩展工具 `search_transactions(..., limit: int = 20, *, start_date=None, end_date=None, offset: int = 0) -> dict`，返回 count/totals/rows/offset/has_more/truncated。
- 对比返回 base_month/target_month、base/target 的 expense/income/net、delta、change_percent、by_category；分类项含 base/target/delta/contribution_percent。金额为十进制字符串，百分比为可空数值。范围查询返回 start_date/end_date/group_by、totals、groups、coverage（首末交易日期、present_months、missing_months），不声称导入完整。

- [ ] 写失败测试：两月餐饮 100→160 元、购物 50→40 元，消费 150→200 元，delta 为 `50.00`，餐饮贡献为 120%，购物为 -20%；净额依照收入减消费。
- [ ] 写失败测试：零基期 change_percent 为空；下降月份 contribution_percent 为空并有说明；无账单月份报错。
- [ ] 写失败测试：起止日期包含、非法日期/倒序/367 天拒绝；无交易月份列入 missing_months；day/month/category 三种聚合均正确。
- [ ] 写失败测试：同时间跨平台至少 51 笔交易，第一页 50、第二页剩余且无重叠；两页 totals 一致；月份与日期取交集；个人明细继续脱敏。limit 的 0、-1、True、1.5、51 和 offset 的负数/True 均返回错误。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_db.py tests/test_assistant.py -q`，确认新增行为测试先失败。
- [ ] 实现上述接口与 schema/标签注册；金额用分，百分比用 Decimal 计算；SQL 使用参数和稳定主键排序，保留旧字段和默认参数。
- [ ] 重跑同一测试命令，全部通过后提交 `feat: add range and month comparison queries`。

### Task 2：运行状态与受限历史

**Files:** 新建 assistant_state.py、test_assistant_state.py。

**Interfaces:**
- dataclass `Budget(max_batches: int, query_seconds: float, summary_seconds: float = 30, max_tools: int = 6)`；`BUDGETS['quick']` 为 5/60，`BUDGETS['deep']` 为 15/180。
- dataclass `Progress(run_id: str, kind: str, batch: int = 0, tool: str = '', detail: dict | None = None)`，kind 限 started/query/result/finished。
- dataclass `Turn(question: str, default_month: str, answer: Answer)`。
- dataclass `RunState(run_id: str, cancel: threading.Event, events: queue.Queue[Progress])`。
- 将原 Step 与 Answer 移到此模块并从 assistant.py 再导出，避免循环引用；Answer 保留 text、steps，增加默认值字段 status/reason/batches/elapsed；status 为 complete/partial/cancelled/timeout/error。
- `history_messages(turns: list[Turn]) -> list[dict]` 仅生成受限问答与依据摘要，不转发原始明细；预算校验函数 `get_budget(mode: str) -> Budget` 拒绝未知模式。

- [ ] 写失败测试断言两模式精确预算、默认结果字段兼容 `Answer(text, steps)`、独立运行不共享 Event/Queue。
- [ ] 写失败测试：8 组历史只保留最后 6 组，每段不超过 2000/6000/4000 字符（含截断标记）；默认月份保留；摘要无姓名商品明细，不包含原始 tool_call 协议。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_assistant_state.py -q`，确认失败后实现接口，再运行至通过。
- [ ] 提交 `feat: define assistant run state and bounded history`。

### Task 3：有界 AI 循环与最后总结

**Files:** 修改 assistant.py、tests/fakes.py、test_assistant.py。

**Interfaces:**
- `ask(client, model, conn, question, default_month, *, mode='quick', history=(), run_state=None, clock=time.monotonic) -> Answer`；兼容旧五位置参数。
- 请求通过 `client.with_options(timeout=remaining, max_retries=0).chat.completions.create(...)`；FakeLLM 补 with_options 记录配置并返回自身。
- 通过 RunState 发布进度，保留每个 tool_call_id 的结果；最终请求 `tool_choice='none'`，不再执行模型返回的工具。

- [ ] 写失败测试：5 批不同成功查询后第 6 次仅总结成功；deep 超过 5 批仍可取数；自行回答即结束。
- [ ] 写失败测试：一批 8 个调用只执行 6 个，但 8 个 id 都有返回；重复参数排序不同也复用；连续两批无新增成功结果后总结。
- [ ] 写失败测试：强制总结仍调工具/空回复时无额外取数；无成功取数时明确缺依据；部分结果状态与停止原因正确。
- [ ] 写失败测试：可控 clock 用尽查询/总结预算，精确校验每请求 timeout≤30 和 remaining，max_retries=0；取消前/请求后检查事件，不触发后续请求；API异常不包含伪造 key。
- [ ] 写失败测试：本题 SDK assistant 消息含 reasoning_content 时原样保留；传入历史能承接语义但新题仍查工具。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_assistant.py tests/test_assistant_state.py -q`，确认新增测试失败。
- [ ] 实现循环、规范化缓存和总结；取消用本地阶段性说明，超时/接口失败保留已有证据。更新旧 GAVE_UP/五轮测试为新语义，不通过删断言规避回归。
- [ ] 重跑本任务测试至通过，提交 `feat: support bounded deep analysis and final synthesis`。

### Task 4：页面会话与跨线程工作生命周期

**Files:** 新建 web/ask.py；修改 pages.py、test_web.py。

**Interfaces:**
- `AskSession`（web/ask.py）拥有 turns、active_run、selected_turn、mode、default_month_notice；每页面单独创建；`stop()` 设 Event 并使运行标识失效，`clear()` 先 stop 再清空。
- `ask_in_thread(db_path, client, model, question, month, *, mode, history, run_state) -> Answer` 自建连接，finally 关闭。
- `render_ask(ctx) -> None` 为 pages.py 提供入口；UI 以 `ui.timer` 消费队列，仅主事件循环修改 UI；完成事件匹配 active_run 才保存 Turn。
- 面板切走保留历史、停止当前运行；切回重画。月份切换保留历史并提示，新题默认用新月份。

- [ ] 写失败 UI 测试：两次提问第一题仍可查看且第二题携带第一题上下文；新对话清空；页面刷新另建会话。
- [ ] 写失败 UI 测试：切页返回保留已完成回答；切月后提示且下一请求使用新月份；导入/归类后追问使用更新数据库结果。
- [ ] 写失败 UI 测试：停止后迟到完成不得保存；立即重问后旧事件不能覆盖；双击/回车不能重复提交；后台连接异常也关闭。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_web.py -q` 确认新增用例失败。
- [ ] 实现会话与生命周期，保留 question/ask-btn 测试标记，添加 ask-stop/ask-new/ask-mode/ask-status 标记；工作线程不使用 ctx.conn 或直接触碰 UI。
- [ ] 重跑本任务测试至通过，提交 `feat: add follow-up sessions and cancellable query runs`。

### Task 5：A 布局、证据与实际状态

**Files:** 修改 web/ask.py、theme.py、test_web.py、test_theme.py。

**Interfaces:**
- `evidence_cards(answer: Answer) -> list[dict]` 从成功 Step 生成查询名称、条件、范围、合计、计数/截断信息；过滤错误结果。
- `comparison_view(answer: Answer) -> dict | None` 只消费 compare_months 结构化结果，提供两月指标和图表；无匹配工具则 None。
- `.ask-workspace` 桌面 `minmax(0,7fr) minmax(240px,3fr)`；宽度小于 900px 单列并折叠依据；局部样式不覆盖全局 .status 等通用类。

- [ ] 写失败测试：有对比工具时指标与依据精确对应，只有自由文本金额时不生成指标；失败查询不冒充成功依据；截断明细标注全量笔数与已返回笔数。
- [ ] 写失败测试：空态三个示例点击只填输入；模式选择影响预算；查询进度能在模型尚未结束时显示；partial/cancelled/timeout/error 状态有不同提示。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_web.py tests/test_theme.py -q` 确认新增断言失败。
- [ ] 对照 A 稿实现标题、问题、状态、指标、Markdown、右侧依据、历史切换和追问输入；保留“这次查了什么”。普通 query 工具结果缺少某字段时省略对应展示，不填假值。
- [ ] 重跑本任务测试至通过，提交 `feat: build evidence-first answer workspace`。

### Task 6：浏览器核验、文档与整体验收

**Files:** 修改 README.local.zh-CN.md、docs/design.md；检查上述所有改动。

- [ ] 运行 `.venv/bin/python -m pytest -q`；预期所有现有及新增测试通过，不读取真实 .env 或账单。
- [ ] 用临时库与 FakeLLM 启动本地演示，在 1440px 和 390px 浏览器检查空态、执行进度、正常/部分回答、取消、错误；保存截图到 .superpowers 下，不把虚构账单写入 data/。
- [ ] 操作验证停止后重问、切页返回、切月追问、依据展开与历史切换；检查窄屏无横向溢出，恢复浏览器临时视口。
- [ ] 文档记录 5/15 批加最终总结、60/180 秒加总结预算、协作停止可能等待在途请求、页面内历史刷新清除、八工具及明细分页。与实现逐项对照。
- [ ] 执行 `git diff --check`，预期无格式错误；独立复核针对预算、线程、计入口径和隐私边界，不重复无关测试。
- [ ] 修复复核发现并运行相关测试；没有新增失败或改动不重复全套测试。
- [ ] 提交 `docs: describe answer analysis modes and limits`，报告实际测试结果、截图和任何未验证限制，不声称已做真实模型成功率评测。

## 自检与执行交接

已逐条覆盖规格 1—6 节及五项 Review Focus；任务 1→2→3→4→5→6 顺序执行，Task 1 与 Task 2 理论可独立，但本计划默认串行减少共享 assistant.py 冲突。类型统一由 assistant_state.py 定义并再导出，UI 不依赖原始 SDK 对象。每项含先失败再通过的验证与提交点，无待定接口。

执行方式：推荐主 Sol 在当前会话连续实施，再由独立复核检查整体；也可选择逐任务实施与逐任务复核的代理流程。用户审阅本计划并确认方式后开始。

## 实施记录（2026-10-30）

用户选择主 Sol 直接实施，所有开发独立执行。代码已落地，数据/状态/循环/UI相关提交分别为7898524、2579995、a5aae1b、e84605a、e9e484d；最终修正与文档另提交。

与计划的差异：范围聚合复用已有只读 find_transactions，在工具层计算，未增加重复的 range_totals；保持统计口径一致。Task 4/5 的同一 UI 模块一并实现，样式单独提交。遵照用户独立执行要求，最终由主 Sol 自审，无代理复核。

验证：虚构账单与 FakeLLM；桌面1440px和手机390px实际浏览器检查，保存空态/正常回答/错误态截图；深度、部分回答、取消/迟到响应、换月、追问通过自动UI测试。真实模型效果未付费评测。
