# bill-pipeline AI 功能实施计划（第三版）

> **给执行的 agent：** 必须用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐个实现。步骤用复选框（`- [ ]`）跟踪。

**目标：**
- 分类改由用户维护，可以添加新分类。
- AI 从现有分类里给交易对方建议类别，并统计准确率。
- 新增“问答”页：用工具调用回答关于消费的问题。

**架构：**
- 分类和 AI 建议都存进 SQLite。
- `bill_pipeline/ai.py` 负责连模型和分类建议。
- `bill_pipeline/assistant.py` 负责问答：定义查询工具、执行查询、跑工具调用的循环。
- 页面只调这两个模块。模型客户端通过 `ai.make_client()` 获取，测试时换成假的。

**技术栈：** openai 3.x（连 DeepSeek，接口和 OpenAI 兼容）、NiceGUI 3.18、SQLite、pytest。

**设计文档：** `docs/design.md` 第 15 节。前两份计划是 `docs/plan.md`、`docs/plan-ui.md`。

## 全局约束

- **配置**：项目根目录的 `.env` 里有 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`AGENT_MODEL`。先把 `.env` 加进 `.gitignore`，再从 demo B 复制一份。复制时不显示内容；key 不打印，也不写进任何文件和日志。
- **测试不联网**：一律用 `tests/fakes.py` 里的 `FakeLLM` 代替真实客户端。
- **什么时候联网**：只有点了“让 AI 给建议”，或者提问的时候。页面打开、导入、归类都不调用模型。
- **个人的定义**：交易对方最近一笔（或这一笔）的交易类型属于 `PERSON_TYPES = {"扫二维码付款", "转账", "微信红包", "转账红包"}`。
  - 分类建议：不发个人。
  - 问答：个人的名字一律换成“个人收款”。
  - 永远不发：交易单号、商户单号、对方账号、支付方式、备注。
- **分类颜色**：按 `categories` 表的顺序分配，跳过“其他”。
  - 依次用 `#1baf7a #2a78d6 #eb6834 #6250d6 #eda100 #e87ba4 #008300 #e34948`（后三种已用验证脚本检查过排法）。
  - 第 9 个及以后用 `#9aa3af`。
  - “其他”用 `#c3c9d3`，“未归类”用 `#e5e9ef`。
- **默认分类顺序**：`吃饭、运动、购物、交通、娱乐、其他`。
- **模型调用**：分类建议用 `response_format={"type": "json_object"}`，`temperature=0`。问答用 `tools`，最多 5 步。
- **出错不崩溃**：所有模型错误都转成 `ai.AIError(原因)`，页面上显示原因。
- **测试命令**：`.venv/bin/pytest -q`，输出没有警告。

## 重点检查

1. **模型返回的类别不在分类表里，或者名字不是我们发过去的**：丢掉这一条，不要写进库。→ 任务 22 `test_suggest_drops_invalid`
2. **个人的名字被发给模型**：建议请求和问答里都不能出现。→ 任务 22 `test_suggest_skips_people`，任务 24 `test_ask_masks_people`
3. **没配 key，或者网络、JSON 出错**：页面给出原因，手动功能照常能用。→ 任务 23 `test_ai_suggest_error_shown`，任务 25 `test_ask_without_config`
4. **加了第 9 个分类**：颜色用中灰，不报错。→ 任务 20 `test_category_colors`
5. **模型一直调工具不收尾**：5 步后停下，并给出提示。→ 任务 24 `test_ask_stops_after_max_steps`

## 文件结构

```
bill_pipeline/
  rules.py       CATEGORIES 改名为 DEFAULT_CATEGORIES，顺序改成环形图的顺序
  db.py          加 categories 表、add_category、categories；set_category 按库里的分类校验，
                 并回填 ai_suggestions.chosen；加 ai_suggestions 表、save_suggestions、suggestions、ai_accuracy；
                 Card 加 item 字段（最近一笔的商品说明）
  ai.py          新：load_env、AIError、make_client、is_person、suggest_categories
  assistant.py   新：TOOLS、run_tool、ask、Answer、Step
web/
  theme.py       CATEGORY_COLORS 换成 category_colors(names)；donut_option 增加分类顺序参数
  pages.py       归类页：+ 新分类、让 AI 给建议、建议高亮、准确率；新增“问答”页
scripts/
  eval_ai.py     新：在本机库上评测问答，输出正确率
tests/
  fakes.py       加 FakeLLM
  test_ai.py、test_assistant.py   新
```

---

### 任务 20：分类存进数据库

**接口：**
- `db.categories(conn) -> list[str]`：按 `position` 排序。
- `db.add_category(conn, name) -> str`：返回去掉首尾空白后的名字。出错时抛 `ValueError`，消息依次是：
  - 空名字：`分类名不能为空`
  - 超长：`分类名最多 8 个字`
  - 重名：`已经有这个分类了`
  - 叫“未归类”：`“未归类”是保留的名字`
- `connect` 建表时补上 `categories(name TEXT PRIMARY KEY, position INTEGER NOT NULL)`，用 `INSERT OR IGNORE` 写入 6 个默认分类。
- `set_category` 改成按 `categories(conn)` 校验。
- `theme.category_colors(names: list[str]) -> dict[str, str]`：结果里还要包含“未归类”。
- `theme.donut_option(by_category, order: list[str])`：扇区按 `order + ["未归类"]` 的顺序排列。

**测试（要点）：**
- `test_default_categories`：新库里 `categories(conn) == ["吃饭", "运动", "购物", "交通", "娱乐", "其他"]`。
- `test_add_category_and_errors`：
  - `add_category(conn, " 宠物 ") == "宠物"`，加完排在最后。
  - 四种出错情况，消息分别和上面一致。
  - `set_category(conn, "某宠物店", "宠物")` 能成功。
- `test_category_colors`：
  - 默认 6 个分类的颜色，和上面列的一致。
  - 再加 4 个分类：第 6–8 个依次是 `#e87ba4 #008300 #e34948`，第 9 个是 `#9aa3af`。
- `test_theme.py` 里的旧测试改成用 `category_colors`。

提交：`feat: user-managed categories`

---

### 任务 21：在归类页添加新分类

- 类别按钮那一排的最后加一个 `+ 新分类`，带 marker `add-category`。
- 点了弹出对话框：输入框带 marker `new-category-name`，“添加”按钮带 marker `new-category-ok`。
  - 出错时，在对话框里显示 `ValueError` 的消息。
  - 成功后关闭对话框，刷新卡片和“已归类”列表。
- “已归类”列表里的下拉选项，改成用 `categories(conn)`。

**测试：**
- `test_add_category_from_sort_page`：输入“宠物”，点添加，然后能看到 marker `chip-宠物`。
- `test_add_duplicate_category_shows_error`：输入“吃饭”，能看到“已经有这个分类了”。

提交：`feat: add categories from the categorize page`

---

### 任务 22：AI 分类建议（核心）

**接口：**
- `ai.load_env(path: Path) -> None`：
  - 读 `KEY=VALUE` 行，跳过空行和 `#` 开头的行，去掉值两边的引号。
  - 只在环境变量里还没有这个键时才设置。
  - 文件不存在就什么也不做。
- `ai.AIError(Exception)`
- `ai.make_client() -> tuple[OpenAI, str]`：
  - 先 `load_env(项目根/.env)`。
  - 缺 `OPENAI_API_KEY` 时，抛 `AIError("AI 还没配置：在项目的 .env 里填好 OPENAI_API_KEY、OPENAI_BASE_URL、AGENT_MODEL")`。
- `ai.is_person(tx_type: str) -> bool`
- `ai.suggest_categories(client, model, cards: list[Card], categories: list[str]) -> dict[str, str]`
  - 只发 `not is_person(card.tx_type)` 的卡片。每个卡片发 `name`，以及 `hints` 列表：支付宝分类、不是“/”的商品说明。
  - 系统提示要求只返回 `{"suggestions": [{"name": ..., "category": ...}]}`，`category` 只能从给出的列表里选。
  - 返回的结果里，名字不在发出去的名单里、或者类别不在列表里的，都丢掉。
  - 接口出错或者 JSON 解析失败，都转成 `AIError`。
- `db.save_suggestions(conn, mapping: dict[str, str], model: str) -> None`：按交易对方覆盖写入，`chosen` 清空。
- `db.suggestions(conn) -> dict[str, str]`：只返回 `chosen IS NULL` 的。
- `db.ai_accuracy(conn) -> tuple[int, int]`：（`chosen == suggested` 的条数，`chosen` 不为空的条数）。
- `db.Card` 加字段 `item`（最近一笔的商品说明），放在最后。`test_db.py` 里的预期值跟着补上 `"/"`。

**`tests/fakes.py` 加 `FakeLLM`：**
- 构造时传入一组回复，依次返回。每个回复是 `{"content": str}` 或 `{"tool_calls": [(name, args_dict), ...]}`。
- `.chat.completions.create(**kwargs)` 把 kwargs 记进 `self.calls`，然后返回一个像 openai 响应的对象：
  - `choices[0].message.content`
  - `choices[0].message.tool_calls[i].id / .function.name / .function.arguments`，其中 `arguments` 是 JSON 字符串
- 回复用完了再调用，就抛异常。

**测试（`tests/test_ai.py`）：**
- `test_load_env`：带注释和引号的写法；已有的环境变量不会被覆盖。
- `test_suggest_skips_people`：用 SAMPLE 导入后的卡片调用，发出去的内容里没有“张阿姨”，有“星光球馆”。
- `test_suggest_drops_invalid`：FakeLLM 返回三条，一条类别是“零食”，一条名字是“不存在的店”，一条正常。只留下正常的那一条。
- `test_suggest_bad_json_raises`：返回 `"不是 JSON"`，抛 `AIError`。
- `test_accuracy`：存了 2 条建议，`set_category` 一条选对、一条选错，`ai_accuracy == (1, 2)`。

提交：`feat: AI category suggestions with accuracy tracking`

---

### 任务 23：归类页接上 AI 建议

- 进度文字下面加一个按钮“让 AI 给建议”，带 marker `ai-suggest`。
  - 点了以后：调用 `make_client()`、`suggest_categories()`、`save_suggestions()`，然后刷新卡片。
  - 出 `AIError` 时，显示“AI 这次没给出建议：{原因}”，带 marker `ai-error`。
- 当前卡片有建议时：显示“AI 建议：{类别}”，对应的按钮多加一个 `suggested` 样式（主色描边）。
- 有确认过的建议时，显示“AI 建议准确率：{对的} / {确认过的}（{百分比}%）”。

**测试**（`monkeypatch.setattr("bill_pipeline.ai.make_client", lambda: (FakeLLM([...]), "fake"))`）：
- `test_ai_suggest_on_sort_page`：点 `ai-suggest`，能看到“AI 建议：运动”；点 `chip-运动` 后，能看到“AI 建议准确率：1 / 1（100%）”。
- `test_ai_suggest_error_shown`：`make_client` 抛 `AIError("AI 还没配置…")`，能看到“AI 这次没给出建议：AI 还没配置”。

提交：`feat: AI suggestions on the categorize page`

---

### 任务 24：问答核心

**接口：**
- `assistant.TOOLS`：6 个函数工具，名字依次是 `list_months`、`month_summary(month)`、`category_detail(month, category)`、`daily_spending(month)`、`top_counterparties(month, limit=5)`、`search_transactions(month=None, category=None, keyword=None, limit=20)`。参数用 JSON Schema 描述，`month` 的格式是 `YYYY-MM`。
- `assistant.run_tool(conn, name, args) -> dict`：
  - 只做只读查询。
  - 金额用字符串，比如 `"1286.50"`。
  - 个人的名字换成“个人收款”。
  - 名字或参数不对时，返回 `{"error": "..."}`，交给模型自己改。
- `assistant.Step(NamedTuple)`：`tool: str`、`args: dict`、`result: dict`
- `assistant.Answer(NamedTuple)`：`text: str`、`steps: list[Step]`
- `assistant.ask(client, model, conn, question, default_month) -> Answer`：
  - 系统提示写明：只用工具结果回答；金额写到分；查不到就直说；没说月份时默认用 `{default_month}`。
  - 最多 5 轮。超过了就返回 `Answer("这个问题我没能在 5 步内查完，换个问法试试。", steps)`。
  - 接口出错转成 `AIError`。

**测试（`tests/test_assistant.py`，用 SAMPLE 导入后的库）：**
- `test_run_tool_month_summary`：`run_tool(conn, "month_summary", {"month": "2026-10"})` 里的消费是 `"85.50"`。
- `test_ask_masks_people`：FakeLLM 先要求调用 `search_transactions({"month": "2026-10"})`，再给出回答。断言交回给模型的工具结果里没有“张阿姨”“球友A”，有“个人收款”。
- `test_ask_returns_answer_and_steps`：回答文字等于 FakeLLM 的最后一条；`steps` 里有一步 `month_summary`。
- `test_ask_stops_after_max_steps`：FakeLLM 连续 5 次都要求调工具，返回“没能在 5 步内查完”。
- `test_run_tool_bad_args`：月份写成 `"十月"`，返回里有 `error`。

提交：`feat: tool-calling assistant over the bill database`

---

### 任务 25：问答页

- 导航加第六项：`("ask", "问答", "forum")`，带 marker `nav-ask`。标题是“问问你的账单”。
- 一个输入框，带 marker `question`；一个按钮“提问”，带 marker `ask-btn`。按回车也能提问。
- 回答显示在一张卡片里。下面是 `ui.expansion("这次查了什么")`，每一步列出“{工具的中文名}（参数）”。
- 提问时按钮转圈，不能连点。出 `AIError` 时显示原因。

**测试：**
- `test_ask_page_answers`：FakeLLM 一步工具调用加一句回答；页面上能看到回答，也能看到“这次查了什么”。
- `test_ask_without_config`：能看到“AI 还没配置”。

提交：`feat: ask page`

---

### 任务 26：评测、配置、文档

- [ ] `.gitignore` 加上 `.env`（任务 22 动手前就要先做）。从 demo B 复制 `.env`，复制时不显示内容。
- [ ] `requirements.txt` 加上 openai，钉住版本。
- [ ] `scripts/eval_ai.py`：
  - 对库里每个月，生成三类问题：“{月}月一共花了多少钱？”“{月}月{类别}花了多少？”（只问这个月有消费的类别）、“{月}月哪天花得最多？”。
  - 标准答案直接查库得到。回答里出现了标准答案的金额（如 `1286.50` 或 `1,286.50`），就算对。
  - 只打印“问了几题、对了几题、正确率”，不打印问题和回答的具体内容。
  - 这一步会联网、会花钱，只在黄飞同意后运行。
- [ ] README 加一节 AI：两个功能、发出去什么不发什么、怎么配置、怎么评测。设计文档第 15 节的状态改成“已确认”。
- [ ] 全量测试通过，然后提交：`docs: AI section, eval script, config`
