# bill-pipeline 界面第二版实施计划

> **给执行的 agent：** 必须用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐个实现。步骤用复选框（`- [ ]`）跟踪。

**目标：** 把 Streamlit 页面换成 NiceGUI 做的五页界面（总览、趋势、导入、归类、对账），浅色薄荷绿风格，ECharts 图表带动效。

**架构：** 核心 `bill_pipeline/` 不改，只在 `db.py` 加查询，并新加 `report.py`，负责按月汇总和对账。界面放在 `web/`：`theme.py` 存颜色、CSS 和图表配置，都是纯函数，能单测；`pages.py` 搭页面。`main.py` 是入口。

**技术栈：** NiceGUI 3.18.0（底层 FastAPI、Vue/Quasar，ECharts 已打包）、pytest + pytest-asyncio（跑 NiceGUI 的模拟用户测试）。

**设计文档：** `docs/design.md` 第 7、8、10、11、13 节。草图在 `.superpowers/brainstorm/` 下的 `style-v2.html`（A 版），不进 Git。前一份计划是 `docs/plan.md`（任务 1–11）。

## 全局约束

- 依赖：去掉 streamlit，加上 `nicegui==3.18.0` 和 `pytest-asyncio`。版本钉死在 `requirements.txt`。
- 启动：`ui.run(host="127.0.0.1", port=8080, title="账单流水线", reload=False)`。必须明确写 `127.0.0.1`，因为 NiceGUI 默认监听 `0.0.0.0`，同一网络里的人都能打开。
- 不联网：只用 NiceGUI 自带的前端文件，不加任何外部字体、脚本或网址。
- 数据库路径：`os.environ.get("BILL_DB")`，没有就用 `data/bills.db`。在每次打开页面时读取，不在导入模块时读取，这样测试才能换成临时库。
- 颜色（设计文档 8.1）：

  | 用途 | 颜色 |
  |---|---|
  | 主色 | `#1baf7a` |
  | 吃饭 | `#1baf7a` |
  | 运动 | `#2a78d6` |
  | 购物 | `#eb6834` |
  | 交通 | `#6250d6` |
  | 娱乐 | `#eda100` |
  | 其他 | `#c3c9d3` |
  | 未归类 | `#e5e9ef` |

  环形图的扇区固定按 `吃饭、运动、购物、交通、娱乐、其他、未归类` 排列。
- 图表细节：
  - 线宽 2px。
  - 柱子只有顶端圆角 4px，底部贴着基线。
  - 环形图扇区之间留 2px 白缝。
  - 网格线用实线，颜色 `#eef1f5`。
  - 柱状图和瀑布图的 y 轴从 0 开始。
  - 大号数字不用等宽数字，表格里需要对齐的数字用等宽数字。
- 每个数都要能直接读到，不能只靠悬停：环形图配列表，趋势页有表格，瀑布图每根柱子都标金额。
- 金额在核心里一律用整数分。只有交给图表画图时才除以 100，显示的文字一律用 `yuan()`。
- 用户能看到的文字用中文，下面各任务里写的文案要照抄，测试会按这些字查找。
- 隐私：用真实账单验收时只核对数字；截图只用假数据。
- 测试命令：`.venv/bin/pytest -q`。

## 重点检查

1. **空库或者某个月没有数据**：五页都显示空状态的文字，不报错，图表的数据是空列表。→ 任务 13 `test_donut_empty`，任务 14 `test_overview_empty`
2. **上个月没有数据**：不显示“比上月”的小标签，不能出现除以 0。→ 任务 12 `test_change_ratio`
3. **这个月只有收入或中性交易，没有支出**：环形图显示空状态，对账页写“这个月没有支出记录”。→ 任务 12 `test_month_reconciliation_empty_month`，任务 18 `test_recon_page_without_expense`
4. **一次上传多份，其中一份被拒收**：被拒的那份出一张红色卡片写原因，其他文件照常导入。→ 任务 16 `test_upload_rejects_bad_file_but_keeps_others`
5. **归完最后一张卡片，或者在“已归类”里改了类别**：显示“都归好类了”，改类别后总览马上按新类别统计。→ 任务 17 `test_sort_page_saves_and_finishes`、`test_sort_page_recategorize`

## 文件结构

```
bill_pipeline/
  db.py          加：daily_expense、recent_months、import_history、categorized、category_transactions、month_rows；
                 unmapped_counterparties 改为返回 Card（带最近一笔的提示）
  report.py      新：previous_month、change_ratio、month_reconciliation
web/
  __init__.py
  theme.py       新：颜色、CSS、计数动画脚本、图表配置（纯函数）
  pages.py       新：register() 里定义 '/' 页面：左侧导航、五个面板、月份选择
main.py          新：入口，调 register()，再调用 ui.run
tests/
  conftest.py    新：pytest_plugins = ["nicegui.testing.user_plugin"]
  test_report.py 新
  test_theme.py  新
  test_web.py    新（NiceGUI 模拟用户）
  test_db.py     改：unmapped_counterparties 的预期值，加新查询的测试
删除：app.py、tests/test_app.py、.streamlit/
```

---

### 任务 12：按月汇总的查询

**文件：**
- 修改：`bill_pipeline/db.py`、`tests/test_db.py`
- 新建：`bill_pipeline/report.py`、`tests/test_report.py`

**接口：**
- `db.Card(NamedTuple)`，字段依次为 `counterparty: str`、`count: int`、`cents: int`、`source: str`、`tx_type: str`、`last_time: str`。
- `db.unmapped_counterparties(conn) -> list[Card]`：最近一笔取这个对方在“消费”结果里时间最晚的那一笔，排序规则不变。
- `db.daily_expense(conn, month) -> list[tuple[str, int]]`：从 1 号排到这个月最后一笔交易（不管结果是什么）那天；没有消费的日子记 0；这个月没有任何交易就返回 `[]`。
- `db.recent_months(conn, n=6) -> list[tuple[str, int]]`：最近 n 个有交易的月份，按时间从早到晚排，值是消费计入合计。
- `db.import_history(conn, limit=5) -> list[tuple[str, str, str, str, int, int]]`：依次是文件名、来源、开始时间、结束时间、新增、跳过；最新的在前。
- `db.categorized(conn) -> list[tuple[str, str, int, int]]`：依次是交易对方、类别、笔数、金额。只统计“消费”且没有规则固定类别的行。按金额从大到小排，金额一样再按名字排。
- `db.category_transactions(conn, month, category) -> list[tuple[str, str, str, int]]`：依次是时间、交易对方、商品、计入金额。类别的判断和 `month_by_category` 一样；`"未归类"` 也能查。按时间从晚到早排。
- `db.month_rows(conn, month) -> pd.DataFrame`：列为 `direction, amount_cents, counted_cents, result, reason`。
- `report.previous_month(month: str) -> str`
- `report.change_ratio(current: int, previous: int) -> float | None`：`previous` 为 0 时返回 `None`。
- `report.month_reconciliation(conn, month) -> list[ReconLine]`：用 `month_rows` 的原始金额，按方向算出一个 `Summary`，再交给 `validate.reconcile`。

- [ ] **第 1 步：写失败的测试**

`tests/test_report.py`：

```python
import pytest

from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from bill_pipeline.report import change_ratio, month_reconciliation, previous_month
from bill_pipeline.validate import ReconLine
from tests.fakes import write_alipay_csv, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.db")


def test_previous_month():
    assert previous_month("2026-10") == "2026-09"
    assert previous_month("2026-01") == "2025-12"


def test_change_ratio():
    assert change_ratio(8550, 9500) == pytest.approx(-0.1)
    assert change_ratio(100, 0) is None


def test_month_reconciliation_matches_import(conn, tmp_path):
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    assert month_reconciliation(conn, "2026-10") == [
        ReconLine("支出", "平台合计", 5, 11230),
        ReconLine("支出", "减：全额退款的原交易", 1, 2680),
        ReconLine("支出", "= 计入", 4, 8550),
        ReconLine("收入", "平台合计", 3, 131480),
        ReconLine("收入", "减：退款", 1, 2680),
        ReconLine("收入", "= 计入", 2, 128800),
        ReconLine("中性交易", "平台合计", 1, 5050),
        ReconLine("中性交易", "减：中性交易", 1, 5050),
        ReconLine("中性交易", "= 计入", 0, 0),
    ]


def test_month_reconciliation_two_sources(conn, tmp_path):
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    import_bill(conn, write_alipay_csv(tmp_path / "a.csv"), "a.csv")
    lines = month_reconciliation(conn, "2026-10")
    assert ReconLine("支出", "平台合计", 8, 20780) in lines
    assert ReconLine("支出", "= 计入", 7, 18100) in lines
    assert ReconLine("中性交易", "平台合计", 2, 11710) in lines


def test_month_reconciliation_empty_month(conn):
    assert month_reconciliation(conn, "2026-10") == [
        ReconLine("支出", "平台合计", 0, 0), ReconLine("支出", "= 计入", 0, 0),
        ReconLine("收入", "平台合计", 0, 0), ReconLine("收入", "= 计入", 0, 0),
        ReconLine("中性交易", "平台合计", 0, 0), ReconLine("中性交易", "= 计入", 0, 0),
    ]
```

`tests/test_db.py`：

- 把 `test_categories_and_month_report` 里第一个断言改成：
  ```python
  [("星光球馆", 1, 4000, "微信", "商户消费", "2026-10-02 19:00:00"),
   ("食堂一楼", 1, 1250, "微信", "商户消费", "2026-10-01 12:00:00"),
   ("张阿姨", 1, 800, "微信", "扫二维码付款", "2026-10-03 08:00:00")]
  ```
- 再加下面这些测试：

```python
def test_daily_expense(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    days = daily_expense(conn, "2026-10")
    assert days[:4] == [("2026-10-01", 1250), ("2026-10-02", 4000), ("2026-10-03", 3300), ("2026-10-04", 0)]
    assert len(days) == 9
    assert daily_expense(conn, "2026-09") == []


def test_recent_months_and_history(conn, tmp_path):
    september = dict(make_row(11, 1, 9, "商户消费", "食堂一楼", "支出", 10.0, "支付成功"),
                     **{"交易时间": datetime(2026, 9, 30, 12)})
    for name, rows in (("b.xlsx", SAMPLE_ROWS), ("c.xlsx", [september])):
        bill, prepared = _prepared(tmp_path, name, rows=rows)
        save_import(conn, bill, prepared, name)
    assert recent_months(conn) == [("2026-09", 1000), ("2026-10", 8550)]
    assert [h[0] for h in import_history(conn)] == ["c.xlsx", "b.xlsx"]
    assert import_history(conn)[0][4:] == (1, 0)


def test_categorized_and_category_transactions(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    assert len(category_transactions(conn, "2026-10", "未归类")) == 3
    set_category(conn, "星光球馆", "运动")
    set_category(conn, "食堂一楼", "吃饭")
    set_category(conn, "张阿姨", "吃饭")
    assert categorized(conn) == [("星光球馆", "运动", 1, 4000), ("食堂一楼", "吃饭", 1, 1250), ("张阿姨", "吃饭", 1, 800)]
    assert category_transactions(conn, "2026-10", "吃饭") == [
        ("2026-10-03 08:00:00", "张阿姨", "/", 800), ("2026-10-01 12:00:00", "食堂一楼", "/", 1250)]
    assert category_transactions(conn, "2026-10", "其他") == [("2026-10-03 21:00:00", "球友A", "/", 2500)]
```

`test_db.py` 顶部的 import 补上：`from datetime import datetime`，以及 `db` 里的 `daily_expense, recent_months, import_history, categorized, category_transactions`。

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest -q tests/test_report.py tests/test_db.py`
预期：`test_report.py` 报 `ModuleNotFoundError: No module named 'bill_pipeline.report'`；`test_db.py` 报 ImportError（新函数还不存在）。

- [ ] **第 3 步：实现**

- `unmapped_counterparties` 里，“最近一笔”的来源和类型用子查询取：在同一个交易对方、结果为“消费”的行里按时间倒序取第一行。
- `month_reconciliation` 由三步组成：`month_rows` 取数，按方向数出笔数、加出金额，组成 `Summary`，然后交给 `reconcile`。

- [ ] **第 4 步：运行全部测试**

运行：`.venv/bin/pytest -q`
预期：全部通过（`tests/test_app.py` 这时还在，也要通过）。

- [ ] **第 5 步：提交**

```bash
git add bill_pipeline/db.py bill_pipeline/report.py tests/test_db.py tests/test_report.py
git commit -m "feat: month-level queries and reconciliation for the new UI"
```

---

### 任务 13：主题和图表配置（纯函数）

**文件：**
- 新建：`web/__init__.py`（空文件）、`web/theme.py`、`tests/test_theme.py`

**接口：**
- `ACCENT = "#1baf7a"`
- `CATEGORY_COLORS: dict[str, str]`，顺序就是环形图扇区的顺序。
- `CSS: str`：页面样式。照草图 A 的变量写：背景 `#ffffff`、导航栏 `#f3f5f8`、卡片底 `#f7f9fb`、线 `#e6eaf0`、正文 `#111827`、次要文字 `#6b7584`。
- `COUNT_UP_JS: str`：定义 `window.countUp(id, target)`，1.2 秒，三次缓出，`toLocaleString('zh-CN')` 保留两位小数，前面加 `¥`。元素还没出现时，每帧重试一次，最多 20 帧。
- `donut_option(by_category: list[tuple[str, int]]) -> dict`
  - 扇区按 `CATEGORY_COLORS` 的顺序，跳过金额为 0 的类别。
  - 每个数据项带上 `itemStyle.color`，以及 `text`（`yuan` 格式化好的金额）。
  - 中心用 `graphic` 写“花得最多\n{类别} {占比}%”，占比四舍五入取整。
  - 没有数据时，`series[0].data == []`，也不加 `graphic`。
  - 入场动画：`animationType: "expansion"`，1200ms。
- `daily_option(days: list[tuple[str, int]]) -> dict`
  - x 轴取日期的 `MM-DD`。
  - 平滑面积线，渐变填充；`markPoint` 标最大值，标签写“最高 ¥x”。
  - 1700ms 入场。
- `monthly_option(months: list[tuple[str, int]], current: str) -> dict`
  - 当前月用主色并标金额，其他月份用 `#dde3ea`。
  - 柱子依次入场，每根比前一根晚 110ms。
- `waterfall_option(lines: list[ReconLine]) -> dict`
  - 输入是某一个方向的对账行。
  - x 轴：第一项叫“账单支出”，中间各项去掉“减：”前缀，最后一项叫“实际消费”。
  - 透明的垫底系列，数值依次是：第一项 0；中间各项是“还剩多少”（平台合计减去到这一项为止的减项累计）；最后一项 0。
  - 颜色依次是：灰 `#c3c9d3`；减项为 `#eb6834`；结果为主色。
  - 柱子依次入场，每根比前一根晚 380ms。
- 所有图表的 JS 函数（tooltip 的 formatter 等）都用 NiceGUI 的冒号前缀写法：`":formatter": "p => ..."`。渐变用 ECharts 的 JSON 写法（`{"type": "linear", ..., "colorStops": [...]}`），不用 `echarts.graphic`。

- [ ] **第 1 步：写失败的测试 `tests/test_theme.py`**

```python
from bill_pipeline.validate import ReconLine
from web.theme import CATEGORY_COLORS, daily_option, donut_option, monthly_option, waterfall_option


def test_donut_keeps_fixed_order_and_colors():
    option = donut_option([("其他", 2500), ("运动", 4000), ("吃饭", 2050), ("未归类", 100), ("交通", 0)])
    data = option["series"][0]["data"]
    assert [d["name"] for d in data] == ["吃饭", "运动", "其他", "未归类"]
    assert [d["itemStyle"]["color"] for d in data] == [CATEGORY_COLORS[n] for n in ["吃饭", "运动", "其他", "未归类"]]
    assert data[1]["text"] == "¥40.00"
    assert option["graphic"]["style"]["text"] == "花得最多\n运动 46%"


def test_donut_empty():
    option = donut_option([])
    assert option["series"][0]["data"] == []
    assert "graphic" not in option


def test_daily_option_labels_and_values():
    option = daily_option([("2026-10-01", 1250), ("2026-10-02", 0)])
    assert option["xAxis"]["data"] == ["10-01", "10-02"]
    assert option["series"][0]["data"] == [12.5, 0.0]


def test_monthly_option_highlights_current():
    option = monthly_option([("2026-09", 1000), ("2026-10", 8550)], current="2026-10")
    bars = option["series"][0]["data"]
    assert [b["itemStyle"]["color"] for b in bars] == ["#dde3ea", "#1baf7a"]
    assert option["xAxis"]["data"] == ["9 月", "10 月"]


def test_waterfall_bases_and_values():
    lines = [ReconLine("支出", "平台合计", 5, 11230), ReconLine("支出", "减：全额退款的原交易", 1, 2680),
             ReconLine("支出", "= 计入", 4, 8550)]
    option = waterfall_option(lines)
    assert option["xAxis"]["data"] == ["账单支出", "全额退款的原交易", "实际消费"]
    assert option["series"][0]["data"] == [0, 85.5, 0]
    assert [v["value"] for v in option["series"][1]["data"]] == [112.3, 26.8, 85.5]
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest -q tests/test_theme.py`
预期：报 `ModuleNotFoundError: No module named 'web'`。

- [ ] **第 3 步：实现 `web/theme.py`**

- [ ] **第 4 步：运行，确认通过**

运行：`.venv/bin/pytest -q tests/test_theme.py`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add web/__init__.py web/theme.py tests/test_theme.py
git commit -m "feat: theme and chart options for the new UI"
```

---

### 任务 14：NiceGUI 骨架和总览页

**文件：**
- 新建：`main.py`、`web/pages.py`、`tests/conftest.py`、`tests/test_web.py`
- 修改：`requirements.txt`（加 nicegui、pytest-asyncio）、`pyproject.toml`（加 `asyncio_mode = "auto"`、`main_file = "main.py"`）

**接口：**
- `web.pages.register() -> None`：在函数里用 `@ui.page("/")` 定义页面。放在函数里，是因为模拟测试每个用例都会重置 NiceGUI 的全局状态，并重新执行 `main.py`。
- `main.py` 顶层调用 `register()`，`if __name__ in {"__main__", "__mp_main__"}:` 里调用 `ui.run(...)`（参数见全局约束）。
- 页面结构：
  - 左侧竖向导航：logo“账”，以及五个按钮。按钮带 marker：`nav-overview`、`nav-trend`、`nav-upload`、`nav-sort`、`nav-recon`，文字依次是“总览”“趋势”“导入”“归类”“对账”。
  - 右侧是 `ui.tab_panels(animated=True)`，加上 props `transition-prev=fade transition-next=fade`。
  - 顶部右边是月份选择 `ui.select`，带 marker `month`。选项来自 `months(conn)`，默认选最新的月份。
  - 每个面板的内容是一个 `@ui.refreshable` 函数。切到某个面板，或者换了月份，就刷新那个面板，动效会重新播放。
- 总览面板：
  - 空库时显示“还没有导入账单”，加一个按钮“去导入”，点了切到导入页。
  - 有数据时：
    - 小标题“{月} 月消费”，月份去掉前导 0。
    - 大数字“¥x”，先直接写出最终值，再用 `ui.run_javascript` 调 `countUp` 从 0 滚上去。
    - 比上月的标签：变少写“↓ 比 {上月} 月少 {百分比}%”，变多写“↑ 比 {上月} 月多 {百分比}%”，保留一位小数；`change_ratio` 返回 `None` 时不显示。
    - 一行小字“收入 ¥x · 结余 ¥y”，结余为负时写“−¥”。
    - 环形图 `ui.echart(donut_option(...), on_point_click=...)`。
    - 右边列表：按金额从高到低，每行有色点、类别、金额、占比。点某一行，或者点环形图的某一块，打开 `ui.dialog`：标题“{类别} · {月} 月”，每行是时间（`MM-DD HH:MM`）、交易对方、金额。

- [ ] **第 1 步：写失败的测试**

`tests/conftest.py`：

```python
pytest_plugins = ["nicegui.testing.user_plugin"]
```

`tests/test_web.py`：

```python
import pytest
from nicegui import ui
from nicegui.testing import User

from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx


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
    await user.should_see("花得最多")
    await user.should_see(kind=ui.echart)
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pip install nicegui==3.18.0 pytest-asyncio`，然后更新 `requirements.txt` 和 `pyproject.toml`，再运行 `.venv/bin/pytest -q tests/test_web.py`。
预期：失败，原因是找不到 `main.py`。

- [ ] **第 3 步：实现 `main.py` 和 `web/pages.py`（先只做骨架和总览）**

其他四个面板先各放一个标题：“花钱的节奏”“导入账单”“给交易对方归类”“钱都去哪了”。

- [ ] **第 4 步：运行全部测试**

运行：`.venv/bin/pytest -q`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add main.py web/pages.py tests/conftest.py tests/test_web.py requirements.txt pyproject.toml
git commit -m "feat: NiceGUI shell and overview page"
```

---

### 任务 15：趋势页

- 标题“花钱的节奏”。下面是 `ui.toggle(["按天", "按月", "表格"], value="按天")`，带 marker `trend-mode`。
- 按天：`daily_option(daily_expense(conn, month))`。说明文字“{MM-DD} 花得最多：¥x”；这个月没有消费时写“这个月还没有消费”。
- 按月：`monthly_option(recent_months(conn), current=month)`。说明文字“{月} 月比 {上月} 月少花 ¥x” 或 “多花 ¥x”；上月没有数据时不写。
- 表格：最近 6 个月，三列：月份（如“10 月”）、消费、比上月（如“−8.2%”，第一行写“—”）。

测试（追加到 `tests/test_web.py`）：

```python
async def test_trend_page_modes(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-trend").click()
    await user.should_see("花钱的节奏")
    await user.should_see("10-02 花得最多：¥40.00")
    user.find(marker="trend-mode").elements.pop().set_value("表格")
    await user.should_see("10 月")
    await user.should_see("¥85.50")
```

步骤照任务 14：先看测试失败，再实现，然后跑全量测试。提交信息：`feat: trend page`。

---

### 任务 16：导入页

- 标题“导入账单”。
- `ui.upload(multiple=True, auto_upload=True, on_upload=...)`，加上 props `accept=.xlsx,.csv`，标签“把微信 .xlsx 或支付宝 .csv 拖到这里”，带 marker `upload`。
- 每份文件：`import_bill(conn, io.BytesIO(await e.file.read()), e.file.name)`。处理完调用 `upload.reset()`。
  - 成功：结果卡片。标题“{来源}账单 {MM-DD} ~ {MM-DD}”，副标题“新增 n 笔 · 跳过 m 笔”。一条进度条，加三行核对，用 CSS 动画依次出现：“第一关：读全了”“第二关：对账平了”“第三关：不重复”。有未识别的交易时加一行：“有 k 笔没见过的交易类型或状态，没算进统计，需要补规则”。
  - `BillError`：红色卡片，写“{文件名} 拒收：{原因}”。
- 结果卡片放在一个列里，离开导入页时清空。
- 下面是“最近导入”：每行“{来源} · {开始日期} ~ {结束日期} · 新增 n · 跳过 m”。

测试：

```python
from nicegui.elements.upload_files import SmallFileUpload


async def _upload(user: User, name: str, data: bytes) -> None:
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
```

提交信息：`feat: upload page`。

---

### 任务 17：归类页

- 标题“给交易对方归类”。
- 进入归类页时，记下当时未归类的总数 N，以及本轮已经处理了几个 k。
- 卡片：
  - 上方进度文字“第 k+1 / N 个 · 归一次，以后自动记住”。
  - 卡片里：交易对方名字；“{笔数} 笔 · ¥金额”；提示——支付宝写“支付宝分类：{tx_type}”，微信直接写 tx_type，后面接“ · 最近一笔 {MM-DD HH:MM}”。
  - 六个类别按钮，带 marker `chip-{类别}`；外加“跳过，以后再说”，带 marker `skip`。
  - 点类别按钮：调用 `set_category` 保存，然后换下一张，卡片用 CSS 动画滑入。
  - 跳过：只记在这一轮里，不写库。
- 都处理完以后：没有未归类的了，写“都归好类了”；还有被跳过的，写“剩下的都跳过了”。
- 卡片下面是 `ui.expansion("已归类（n）")`：每行有名字、“{笔数} 笔 · ¥金额”、一个 `ui.select(CATEGORIES)`，带 marker `recat-{名字}`。改了就调用 `set_category`。

测试：

```python
async def test_sort_page_saves_and_finishes(user: User, db, tmp_path):
    import_bill(connect(db), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    await user.open("/")
    user.find(marker="nav-sort").click()
    await user.should_see("第 1 / 3 个")
    await user.should_see("星光球馆")
    user.find(marker="chip-运动").click()
    await user.should_see("第 2 / 3 个")
    user.find(marker="chip-吃饭").click()
    user.find(marker="chip-吃饭").click()
    await user.should_see("都归好类了")


async def test_sort_page_recategorize(user: User, db, tmp_path):
    conn = connect(db)
    import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    for name, category in (("星光球馆", "运动"), ("食堂一楼", "吃饭"), ("张阿姨", "吃饭")):
        set_category(conn, name, category)
    await user.open("/")
    user.find(marker="nav-sort").click()
    user.find(marker="recat-星光球馆").elements.pop().set_value("娱乐")
    await user.should_see("都归好类了")
    assert ("娱乐", 4000) in month_by_category(connect(db), "2026-10")
```

`test_web.py` 顶部的 import 补上 `set_category`、`month_by_category`。提交信息：`feat: categorize page`。

---

### 任务 18：对账页

- 标题“钱都去哪了”。
- 说明文字由支出那几行对账生成：
  - 有减项：“这个月账单里的支出是 ¥x，其中{原因1} ¥a、{原因2} ¥b 不算消费，所以实际消费是 ¥y。”
  - 没有减项：“这个月账单里的支出是 ¥x，全部算作消费。”
  - 支出是 0：“这个月没有支出记录。”
- 这个月有数据时，显示三个徽章：“✓ 读全了”“✓ 对账平了”“✓ 不重复”。
- 瀑布图：`waterfall_option(支出那几行)`。支出是 0 时不画。
- 下面一个小表，列出收入和中性交易的对账行：项目、笔数、金额。

测试：

```python
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
```

`test_web.py` 顶部的 import 补上 `SAMPLE_ROWS`。提交信息：`feat: reconciliation page`。

---

### 任务 19：收尾

- [ ] 删除 `app.py`、`tests/test_app.py`、`.streamlit/`；删掉 `pyproject.toml` 里那条 Streamlit 警告过滤；`requirements.txt` 去掉 streamlit，重新 `pip freeze` 钉版本。
- [ ] README 改三处：
  - How to run 改成 `.venv/bin/python main.py`，打开 `http://127.0.0.1:8080`。
  - 项目结构里加上 `web/`、`main.py`、`report.py`。
  - Privacy 里写明：只监听 127.0.0.1，前端文件都是本地的。
- [ ] 跑全量测试：`.venv/bin/pytest -q`，预期全部通过，没有警告。
- [ ] 用假数据看界面：把假账单导进一个临时库，用 `BILL_DB=<临时库> .venv/bin/python main.py` 启动，在浏览器里把五页各看一遍：动效、空状态、弹窗。
- [ ] 用真实账单验收，只核对数字：两份真实账单导进临时库后，`month_totals` 和 `month_reconciliation` 的结果要和带练记录里的基准一致。不截图，也不打印交易对方。
- [ ] 提交：`git commit -m "chore: replace Streamlit with NiceGUI; README"`
