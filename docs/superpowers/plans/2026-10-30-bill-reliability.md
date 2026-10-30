# Bill Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第一类六项可靠性问题，并让总览、趋势、对账和问答使用一致的个人消费口径。

**Architecture:** 保留原始交易观测与当前有效来源快照，独立存储人工关联/分类/AA调整。单行有效交易视图提供消费收入，分类分配视图处理拆分，来源核验独立保留。所有写入事务化并更新数据修订号，为下一份会话计划提供过期检测依据。

**Tech Stack:** 现有 Python、SQLite、pandas、NiceGUI、pytest；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-30-bill-reliability-design.md`（用户已回复继续，规格通过）。

## Global Constraints

- 真实 XLSX/CSV 仅供本机只读核验；真实明细、身份字段、订单号和金额不进入提交、测试或线上模型。
- 继续使用现有 SQLite、NiceGUI 和整数分金额；AI 不自动关联退款、不决定退款金额、不改账。
- 迁移在单一事务中执行；先通过 SQLite backup API 生成数据库备份，失败时回滚并给出可操作提示。
- 消费分析口径默认回溯调整原消费所属月；原始资金流水继续按实际发生日展示。
- 未验证的支付宝退款和部分退款格式，不升级成自动确认规则；支付宝中性交易不能一律当退款。
- 有效区间取声明范围与导出时刻的交集；旧导入缺少元数据时标为“范围信息待确认”。
- 主 Sol 独立串行实施，不派生代理；复用当前开发分支，不修改系统配置或密钥。

## Review Focus

1. 旧库升级失败/磁盘不足：备份可用、事务回滚，不留下半套表或错误版本号（Task 1）。
2. 源状态退款和独立入账是同一退款证据：不能重复扣减；部分退款证据不明确时不能猜累计额（Task 3）。
3. 退款后已有 AA/分类拆分失效：收入抵扣与分类总额必须一起重核，不能局部更新（Task 4）。
4. 同秒导出、时间未知、同ID关键事实改变：不凭导入先后覆盖；保留冲突与人工选择（Task 2）。
5. 多分类搜索、明细分页、商户排行：不能因视图多行导致总额膨胀或漏掉部分金额（Task 5）。

## 文件与接口归属

新建 `bill_pipeline/migrations.py`（版本/备份）、`bill_pipeline/observations.py`（快照选择）、`bill_pipeline/adjustments.py`（退款/AA/分类）、`bill_pipeline/coverage.py`（覆盖与可信度）、`web/review.py`（交易核查和调整UI）。修改 `model.py/header.py/wechat.py/alipay.py/pipeline.py/db.py/report.py/assistant.py/web/pages.py/web/theme.py` 仅作对应接入。

新建 `tests/test_migrations.py/test_observations.py/test_adjustments.py/test_coverage.py/test_review.py`，扩展现有 DB、导入、规则、报表、问答测试。每任务唯一修改者为主Sol，共享文件按任务顺序交接。

### Task 1：可回滚迁移与数据修订号

**Files:** 新建 migrations.py、test_migrations.py；修改 db.py、rules.py。

**Interfaces:** `migrate(conn: sqlite3.Connection, db_path: Path | None) -> None`；`data_revision(conn) -> int`；`bump_revision(conn) -> int`，由调用方事务提交；`RULESET_VERSION: str`（rules.py）。

表结构：`schema_version(version)`、`data_state(id=1, revision, ruleset_version)`；新增 `imports.exported_at/export_scope/fingerprint` 可空字段。观测表 `transaction_observations(id,source,tx_id,import_id,exported_at,fingerprint,payload_json)`，唯一 `(source,tx_id,fingerprint)`；`transaction_selection(source,tx_id,observation_id)` 指向选定观测；`review_issues(id,source,tx_id,kind,details_json,resolved_at)` 保留核查原因。

- [ ] 写失败测试 `test_legacy_upgrade_preserves_rows_and_creates_backup`：构造旧schema合成库，升级后原交易和分类不变，备份可打开且仍是原schema。
- [ ] 写失败测试 `test_migration_failure_rolls_back`：注入中途失败，版本号与DDL一起回滚，连接可关闭/重开；备份失败时不开始DDL。重复connect不重复备份，内存库不创建磁盘备份。
- [ ] 写失败测试 `test_revision_is_transactional`：回滚后修订号不变；规则版本变化触发已知派生字段重算及修订更新。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_migrations.py -q`，确认新增行为失败。
- [ ] 实现接口：先确认需升级且连接无未提交事务，再用SQLite backup写入库旁 `backups/`，最后显式事务逐条执行DDL，避免 executescript 隐式提交；旧行初始化为时间未知观测。不自动恢复覆盖用户数据库。
- [ ] 同命令通过后提交 `feat: add transactional schema migrations and data revisions`。

### Task 2：来源元数据、交易观测与状态同步

**Files:** 新建 observations.py、test_observations.py；修改 model.py/header.py/wechat.py/alipay.py/pipeline.py/db.py/tests/fakes.py 与导入测试。

**Interfaces:** ParsedBill 追加可空 `exported_at: str | None`、`export_scope: str | None`；`parse_export_metadata(text: str) -> tuple[str | None, str | None]`；`observe_import(conn, bill, classified_rows, file_name) -> ImportChanges`；`select_observation(conn, observation_id: int) -> None` 仅供明确人工确认，重算派生口径并更新修订号。`ImportChanges(new, updated, duplicate, conflicts)`；ImportReport增加默认值字段updated/conflicts，保留new/skipped兼容并明确 skipped=duplicate。

关键事实比较 source/tx_id/tx_time/direction/amount_cents/counterparty；变化进入冲突、不自动选定。状态不同且可信时间更新的快照可选定，但已退款退回支付成功仍需核查；相同可信时间不同内容或缺时间的非单调变化均需核查。无时间“支付成功→已全额退款”可作为明确终态更新，反向不自动更新。相同内容重复不更改修订号；新增覆盖元数据确有变化时可更新修订号。

- [ ] 写失败测试：成功→全额退款重导后有效消费0；再导旧成功文件仍0；较新成功与既有退款矛盾进入冲突。无时间旧库也不回退终态。
- [ ] 写失败测试：同ID金额/方向/时间/交易对方改变、同秒不同状态、缺导出时间均保留观测并报告冲突；人工分类关联不丢。
- [ ] 写失败测试：重复导入指纹幂等、导入前校验失败不入库、途中数据库失败整份回滚；导入报告四类计数准确。
- [ ] 写失败测试：两种虚构文件提取导出元信息；缺字段不猜文件名时间；真实文件仅另做只读复验，不用作fixture。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_observations.py tests/test_pipeline.py tests/test_db.py tests/test_wechat.py tests/test_alipay.py -q`，确认失败后实现上述接口，再运行至通过。
- [ ] 提交 `feat: synchronize transaction observations without status regression`。

### Task 3：退款核查和有效交易口径

**Files:** 新建 adjustments.py、test_adjustments.py；修改 rules.py、db.py、report.py。

**Interfaces:** `list_review_issues(conn, month: str | None = None) -> list[dict]`；`refund_candidates(conn, source: str, refund_id: str) -> list[dict]`；`confirm_refund(conn, expense_key: tuple[str,str], refund_key: tuple[str,str] | None, cents: int, *, event_id: str | None = None) -> str`；`revoke_refund(conn, event_id: str) -> None`；`effective_transactions(conn, month: str | None = None) -> list[dict]`。

数据：`refund_events(id,expense_source,expense_id,cents,confirmed_at,revoked_at)`；`refund_evidence(event_id,source,tx_id)` 唯一关联同一退款记录，已有事件追加证据不新增退款额。原状态明确全额退款时净消费直接为0，独立证据不再冲减；部分退款格式只生成核查项，只有确认的独立事件参与合计。证据重叠/累计关系不明确时必须人工选择已有事件或确认新事件，拒绝静默相加。

- [ ] 写失败测试：全额状态+独立退款证据只冲减一次；退款先到/原消费后到/跨月/多次确认/重复点击不双扣，撤销可恢复。
- [ ] 写失败测试：手动确认两个不同部分退款事件20+30分后仅扣50分；同事件多个证据仍扣一次；超额/负数/布尔金额拒绝且事务不部分写入。
- [ ] 写失败测试：未知支付宝中性退款先列核查，普通中性提现不列退款；未验证部分退款不直接按猜测金额扣除；孤立退款不改变任意旧月。
- [ ] 写失败测试：候选只因同金额/同名不自动确认；重复商户单号、多候选、跨来源均需人工关联；可手动关联两个来源但绝不自动猜跨来源身份。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_adjustments.py tests/test_rules.py -q`，确认失败后实现退款事件与有效行投影。所有金额用分；来源行仍保持原文件核验值；保留核查数与暂计标记。
- [ ] 同命令通过后提交 `feat: reconcile refund evidence with auditable review actions`。

### Task 4：单笔分类、拆分、商户别名和 AA

**Files:** 修改 adjustments.py、db.py；扩展 test_adjustments.py、test_db.py。

**Interfaces:** `set_transaction_categories(conn, tx_key, allocations: list[tuple[str,int]]) -> None`；`clear_transaction_categories(conn, tx_key) -> None`；`set_counterparty_alias(conn, source: str, counterparty: str, canonical: str) -> None`；`create_advance(conn, expense_key, personal_cents: int) -> str`；`allocate_repayment(conn, advance_id: str, income_key, cents: int) -> str`；`revoke_advance(conn, advance_id: str) -> None`；`effective_allocations(conn, month: str | None = None) -> list[dict]`。

表：category_overrides与category_allocations保存独立人工记录；counterparty_aliases只允许显式创建；advance_groups保存净额快照/个人份额，repayment_allocations存引用/金额/撤销。来源事实不改写。事务同时验证分配守恒与收入可用余额；使用 BEGIN IMMEDIATE 防并发超额。

- [ ] 写失败测试：同商户两笔分别改类，商户默认规则保持；固定“其他”的转账也能单笔改运动；拆分合计不等于有效个人消费则拒绝，合计正确则总消费不变。
- [ ] 写失败测试：垫付300分、自己100分、朋友还200分，个人消费100分，关联收回款不计普通收入；部分收回/多人分批/一收款分给多组不重复；超额/撤销/重复提交有界。
- [ ] 写失败测试：后续退款使AA份额或拆分失效时标记重核，整组相关收入分配停用并回退可解释默认口径，分类合计仍等于消费；撤销恢复可重核状态。
- [ ] 写失败测试：别名只经用户选择生效，跨来源相似名字不自动合并；人工覆盖更新修订号，重导保留。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_adjustments.py tests/test_db.py -q`，确认失败后实现接口，再运行至通过。
- [ ] 提交 `feat: support transaction categories and recoverable advances`。

### Task 5：统一查询、覆盖区间与报表可信度

**Files:** 新建 coverage.py、test_coverage.py；修改 db.py/report.py/assistant.py；扩展 test_db.py/test_report.py/test_assistant.py。

**Interfaces:** `coverage(conn, start: str, end: str, expected_sources: list[str] | None = None) -> dict` 返回 sources/intervals/gaps/unknown_metadata/complete；`trust_info(conn, month: str) -> dict` 返回 coverage/pending_reviews/revision/provisional；`set_expected_sources(conn, sources: list[str]) -> None` 持久保存明确选择。

所有月度/每日/商户/搜索总额从单行有效交易取数；分类统计与分类明细从有效分类分配取数。全库搜索每笔只一行，多类别显示“多类别”；带category条件时返回该分类分配的counted_cents，原金额保留单独字段，合计只算该分类份额。分页仍按时间/来源/ID稳定排序。原始流水对账单独使用来源快照，增加人工口径调整项说明，不能把人工修改伪装为来源文件扣除规则。

- [ ] 写失败测试：各页查询与AI八工具的消费/收入一致；拆分交易无筛选只一行，分类筛选50/30分分别正确，总消费80分不膨胀。
- [ ] 写失败测试：重叠/相邻到秒区间合并，未来结束裁剪到导出时刻；未知导出范围或过滤导出不宣称完整；缺来源、旧库未知元数据、无交易日均正确提示；用户来源设置重启保留。
- [ ] 写失败测试：不同月范围不齐时comparisons返回provisional/trust_info；共同范围查询不按天数估算；本月尚未结束明确截至时间。
- [ ] 写失败测试：人工退款/AA改变个人总额后，来源文件核验值不变，个人调整解释可核对；未解决核查不显示最终“全部平了”。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_coverage.py tests/test_db.py tests/test_report.py tests/test_assistant.py -q`，确认失败后改造统一查询及元信息，再运行至通过。
- [ ] 提交 `feat: unify effective accounting and source coverage reporting`。

### Task 6：交易核查、调整与覆盖界面

**Files:** 新建 web/review.py、test_review.py；修改 pages.py/theme.py/web/ask.py、test_web.py。

**Interfaces:** `render_review(ctx) -> None` 提供可筛选的交易核查页（导航名“核查”）；`render_trust_banner(ctx) -> None` 在总览/趋势/对账接入；对话依据展示trust_info。弹窗表单先预览变更前后，再由用户点击确认提交。

- [ ] 写失败UI测试：列出疑似退款并人工选原消费、确认/解除；无候选可手选，金额不合法不保存；旧快照冲突能选择保留/采用且有变更预览。
- [ ] 写失败UI测试：单笔改类/分类拆分、商户默认与别名、建立AA及分配收款操作均能进入，保存后总览和问答取数一致，双击确认不重复。
- [ ] 写失败UI测试：按来源覆盖区间/缺口提示与预计来源设置可见；“文件金额核验通过”和“个人口径待核查”可同时出现。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_review.py tests/test_web.py -q` 确认失败；实施界面，真实金额只在用户本机显示，错误不暴露原始异常；重核操作后刷新月份和相关面板。
- [ ] 同命令通过后，用合成数据在桌面与窄屏实测退款/AA/拆分/覆盖提示，再提交 `feat: add transaction review and accounting adjustment controls`。

### Task 7：旧库复验、文档与整体验收

**Files:** 更新 docs/design.md、README.md、README.local.zh-CN.md、problem.md（后两者保持本机排除状态）。

- [ ] `.venv/bin/python -m pytest -q` 全部通过；`git diff --check` 无错误。
- [ ] 在合成旧库进行备份、升级、状态倒退、退款/AA交互回放；复验用户两份账单只读校验仍通过，未核实格式仍列未知，不把真实文件导入公开测试库。
- [ ] 先复制/备份真实数据库，在备份副本演练迁移和统计差异；仅确认副本升级成功且差异可解释后，通过应用正常迁移路径升级真实库。不自动生成或确认任何人工退款/AA关联。
- [ ] 更新文档与problem.md各项状态，区分“有人工解决路径”与“所有来源格式已验证”；检查日志/提交无真实数据，记录各统计差异理由并仅在本机保存。
- [ ] 提交 `docs: explain accounting review and coverage limits`；保留当前分支供用户使用，不自行发布或推送。

## 自检与交接

覆盖规格的迁移、状态同步、退款证据、AA、单笔/拆分、商户别名、来源覆盖和全页面一致性。Task 1→2→3→4→5→6→7 串行；不会同时修改db.py。退款累计以独立事件/明确证据合并，不能用简单max或相加猜测部分退款重叠。所有消费者明确取单行交易或分类分配，避免拆分翻倍。

执行方式沿用主Sol独立实施；用户审阅计划后开始。

## 实施与验收记录

用户回复“开始”后由主Sol独立实施，无代理。迁移/观测/统一视图/退款事件/AA/分类拆分/核查UI与本地会话均已落地。基础提交99e6e10，整合提交7bca3d1，后续边界修正另提交。

实际使用统一SQL视图实现单行交易与分类分配；数据库版本3包含历史观测、人工事件、会话与核查决定。先在真实库只读副本演练，再通过正常connect迁移真实库，迁移前SQLite备份保留，未自动确认任何退款或AA。

测试使用虚构数据与假模型，新增状态倒退/冲突、金额守恒、退款-AA交互、旧调整失效、迁移回滚、范围覆盖、历史刷新恢复、保存重试和过期判定等回归。真实浏览器验证单笔分类预览/保存/恢复以及刷新后会话恢复，390px结构无水平溢出；截图接口不可用，未伪称取得新截图。

已知边界：支付宝退款与部分退款真实格式仍待样本确认；旧导入缺元数据仍待确认；未知收入类型不能猜作AA收回款；会话未额外加密，真实模型效果未付费评测。
