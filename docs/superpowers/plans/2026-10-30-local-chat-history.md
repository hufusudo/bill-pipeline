# Local Chat History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仅在本机保存账单问答，支持刷新恢复、会话管理和旧答案过期提示。

**Architecture:** SQLite会话仓库使用前一计划的迁移与data_revision；AskSession保留运行身份和取消控制，持久仓库负责历史与快照。打开历史不触发模型，继续提问只取最近6组受限历史并重新查数。

**Tech Stack:** 当前 Python、SQLite、NiceGUI、pytest，无新依赖。

**Spec:** `docs/superpowers/specs/2026-10-30-local-chat-history-design.md`（用户已批准）。

## Global Constraints

- 仅写当前本机账单数据库，不上传会话库；提问时仍会向配置的模型发送必要上下文和查询结果。
- 密钥、内部思考、完整SDK请求和大量交易明细不存入会话。
- 最近6组上下文；单组问题/答案/依据分别沿用2000/6000/4000字符上限；不自动恢复付费调用。
- 默认自动保存已提交问题及最终/部分/取消/失败状态，未提交草稿不持久化。
- 普通删除可恢复；永久删除必须执行前确认；备份可能保留旧内容。
- 数据变更只标记旧答案过时，不自动改写；默认不新增加密/密码/云同步。
- 主Sol独立实施，不派生代理。依赖账单可靠性计划Task 1的数据迁移与修订接口，部署顺序为可靠性计划完成后再交付本功能。

## Review Focus

1. 两个页面同时看同一会话：某页断开不能把另一页仍在运行的问题标成中断（Task 2）。
2. 保存失败：页面不得假装已存；已查询结果保留并提示重试（Task 2/3）。
3. 回答开始和完成之间账单变化：答案也要标过时，不能只比较打开时间（Task 2）。
4. 切换/删除会话后旧线程返回：不能写入另一会话或恢复已删会话（Task 2/3）。
5. 用户问题或答案本身含个人信息：只存本机，不把“依据脱敏”误称为整份会话无敏感信息（Task 3/4）。

## 文件职责

新建 `bill_pipeline/conversations.py`（仓库与受限证据序列化）、`tests/test_conversations.py`。修改 migrations.py（新版本表）、assistant_state.py（持久化回读）、web/ask.py（会话管理接入）和theme.py（列表/抽屉），扩展test_web.py与test_ask_view.py。不改变AI八工具或预算。

### Task 1：会话仓库与安全序列化

**Files:** conversations.py、test_conversations.py、migrations.py。

**Interfaces:** `create_conversation(conn, title: str = '') -> str`；`list_conversations(conn, *, deleted: bool = False) -> list[dict]`；`rename_conversation(conn, conversation_id: str, title: str) -> None`；`load_turns(conn, conversation_id: str) -> list[dict]`；`set_deleted(conn, conversation_id: str, deleted: bool) -> None`；`purge_conversation(conn, conversation_id: str) -> None`。

表：conversations(id,title,created_at,updated_at,deleted_at)；messages(id,conversation_id,question,default_month,mode,status,answer,reason,batches,elapsed,start_revision,end_revision,run_id,owner_instance,created_at,finished_at)；evidence(message_id,position,tool,summary_json)。外键级联删除仅对永久清除，普通删除只设deleted_at。库中只存有界聚合摘要，逐笔rows、订单号、对方账号和SDK内部字段不序列化。

- [ ] 写失败测试：新建、排序、改名、软删/恢复、永久清除关联行；无效ID不创建新会话；标题空白拒绝、最长80字符；命名默认使用首问题的截断文本。
- [ ] 写失败测试：证据白名单与长度上限，无rows/密钥/内部思考；恢复的有限依据可展示但明确是历史快照，不伪造完整Step结果。
- [ ] 写失败测试：旧库升级、外键引用、失败回滚、软删会话不出现在普通列表或上下文；会话管理不增加账单data_revision。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_conversations.py tests/test_migrations.py -q` 确认失败；实现接口和迁移后同命令通过。
- [ ] 提交 `feat: persist conversations and bounded evidence locally`。

### Task 2：运行持久化、重启中断与过期判定

**Files:** 修改conversations.py、migrations.py、assistant_state.py、web/ask.py、web/pages.py；扩展test_conversations.py/test_ask_view.py。

**Interfaces:** `begin_message(conn, conversation_id, question, month, mode, run_id, owner_instance) -> str` 记录start_revision；`finish_message(conn, message_id, run_id, answer: Answer) -> bool` 记录end_revision，仅当前run_id/未删除会话可写；`interrupt_owned_messages(conn, owner_instance: str) -> int`；`is_stale(message: dict, current_revision: int) -> bool`。

每次应用启动生成仅本进程使用的instance ID；新增 `runtime_instances(id,heartbeat_at)`，每5秒更新心跳，超过30秒无心跳才算过期。`register_instance(conn, instance_id: str) -> None` 与 `heartbeat_instance(conn, instance_id: str) -> None` 在conversations.py实现，由应用生命周期启动/停止维护。仅清理租约已过期实例的running消息；新进程启动不立刻抢占旧实例。页面断开只取消自己的run，不批量处理中断其他页面。测试注入时钟，避免真实等待30秒。

- [ ] 写失败测试：刷新后恢复已完成消息；应用重启旧running变interrupted且无模型调用；同实例不同页面不互相中断；外部活跃实例租约未过期不能被抢占。
- [ ] 写失败测试：start_revision≠end_revision或current_revision已变化时标过时；重复完成幂等；已取消/已删除/已切换run的迟到完成拒绝。
- [ ] 写失败测试：落库失败保留内存结果并返回可见保存失败状态，重试保存使用同一message_id防重复；取消保存已有有界依据，继续提问不带取消/失败记录作金额事实。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_conversations.py tests/test_ask_view.py -q` 确认失败，再实现生命周期接入，使用独立连接并finally关闭，测试通过后提交 `feat: make conversation runs restart-safe and revision-aware`。

### Task 3：回答页会话列表与历史恢复

**Files:** 修改web/ask.py、theme.py、test_web.py。

**Interfaces:** AskSession追加conversation_id；`open_conversation(ctx, conversation_id: str) -> None` 先停止本页运行，再回读本地历史；新对话新建会话；历史消息使用仓库受限依据，不当完整交易明细。浏览器重开时默认最近一个未删除会话，若没有则新建空会话；空会话可延迟到首提问再落库。

- [ ] 写失败UI测试：刷新后找回并继续问，打开历史不调用make_client；新建/改名/删除/回收站恢复；窄屏会话入口可操作。
- [ ] 写失败UI测试：旧数据提示“账单已变化，旧答案需重新核查”，重新分析由按钮触发且保存为新消息；原答案内容不变。
- [ ] 写失败UI测试：运行时切换或删除会话，迟到回答不能污染新页；保存失败可见并可重试；问题中的个人文字不出现在浏览器地址或日志。
- [ ] 写失败UI测试：永久删除显示具体会话标题和本机备份提示，取消无删除效果；确认按钮才调用purge_conversation。未提交草稿刷新不恢复，打开/改名/删除不发模型请求。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_web.py tests/test_ask_view.py -q` 确认失败，再实现紧凑会话列表和窄屏抽屉，保留A布局/问答测试标记；同命令通过后提交 `feat: add local conversation history controls`。

### Task 4：整体验收与用户说明

**Files:** 更新README.md、README.local.zh-CN.md、docs/design.md、problem.md（本机文件保持排除）。

- [ ] `.venv/bin/python -m pytest -q` 全部通过，`git diff --check`无错误；检查上下文仍有最近6组限制，个人交易脱敏未退化。
- [ ] 在合成数据库和假模型下实际浏览器验证桌面/窄屏：刷新、重启、会话切换、旧答案过期、软删恢复及永久删除取消；只对测试会话执行确认删除，不操作真实历史。
- [ ] 文档准确区分本机保存与向模型发送上下文；不宣称SQLite默认加密，不自动恢复付费调用。更新problem.md第9项为“连续追问与本地恢复已实现”，保留真实模型评测边界。
- [ ] 提交 `docs: explain local history persistence and stale answers`；记录测试/截图和未验证项，不推送或发布。

## 自检与交接

Task 1→2→3→4 串行；依赖上一计划data_revision和迁移接口已锁定。所有历史操作独立于账单修订号，避免改标题让全部答案误过时。多页面/多进程中断规则与保存失败路径已列入测试。主Sol独立执行方式已确定，待用户审阅本计划即可进入实现。

## 实施与验收记录

用户回复“开始”后由主Sol独立实施，无代理。迁移/观测/统一视图/退款事件/AA/分类拆分/核查UI与本地会话均已落地。基础提交99e6e10，整合提交7bca3d1，后续边界修正另提交。

实际使用统一SQL视图实现单行交易与分类分配；数据库版本3包含历史观测、人工事件、会话与核查决定。先在真实库只读副本演练，再通过正常connect迁移真实库，迁移前SQLite备份保留，未自动确认任何退款或AA。

测试使用虚构数据与假模型，新增状态倒退/冲突、金额守恒、退款-AA交互、旧调整失效、迁移回滚、范围覆盖、历史刷新恢复、保存重试和过期判定等回归。真实浏览器验证单笔分类预览/保存/恢复以及刷新后会话恢复，390px结构无水平溢出；全页截图接口最初不可用；重启最终演示后成功保存视口截图 `.superpowers/reliability-final.jpg`。

已知边界：支付宝退款与部分退款真实格式仍待样本确认；旧导入缺元数据仍待确认；未知收入类型不能猜作AA收回款；会话未额外加密，真实模型效果未付费评测。
