# bill-pipeline 实施计划

> **给执行的 agent：** 必须用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐个实现。步骤用复选框（`- [ ]`）跟踪。

**目标：** 在本机网页上传微信账单，程序依次完成读取、清洗、三关校验、入库、归类和月报。

**架构：** 核心是 `bill_pipeline/` 里的几个模块，每个只做一件事：读文件 → 清洗规则 → 校验与对账 → SQLite 入库 → 查询。`pipeline.import_bill` 把它们串起来，产出导入报告。`app.py`（Streamlit）只负责收文件、调函数、显示结果，不含业务逻辑。

**技术栈：** Python 3.13、pandas + openpyxl、sqlite3（标准库）、Streamlit、pytest。

**设计文档：** `docs/design.md`。执行前先读一遍，本计划里的取值都来自它。

## 范围

- 本计划只做微信。支付宝的格式还没核实（设计文档 3.2）。等黄飞导出样本、看过结构后，另写一份短计划，接到 `pipeline.read_bill` 里，输出同样的 `ParsedBill`。
- AI 功能、单笔改类、部署都不在本计划内（设计文档第 2 节、第 12 节）。

## 全局约束

- 环境：Python 3.13，用 `python3.13 -m venv .venv` 建虚拟环境。依赖只装 pandas、openpyxl、streamlit、pytest，版本钉死在 `requirements.txt`。
- 金额：一律用整数分（int）存储和计算，只通过 `convert.to_cents` 换算。不允许对 float 求和。
- 清洗结果只有四种取值：`消费`、`收入`、`不算`、`未识别`。
- 类别固定六个：`吃饭`、`运动`、`娱乐`、`购物`、`交通`、`其他`。
- 去重键：（来源，交易单号）。微信的来源取值是 `微信`。
- 拒收：一律抛 `BillError`。消息用中文，说清哪里不对，有行号就带上行号。
- 不联网，不调用大模型。Streamlit 只监听 localhost，并关闭使用统计（`.streamlit/config.toml`）。
- 隐私：
  - 真实账单和数据库都不进 Git。
  - 测试只用 `tests/fakes.py` 生成的假账单。
  - 开发时用真实账单只打印笔数和对账行，不打印交易对方、商品、备注的内容。
- 文字：用户能看到的文字（页面、报错）用中文；代码标识符用英文；注释用中文，只写代码本身看不出来的原因。
- 测试命令：`.venv/bin/pytest -q`（在项目根目录运行）。

## 重点检查

测试没有直接覆盖、但最可能出问题的五种情况，以及各自的测试由哪个任务负责：

1. **账单被 Excel 或 WPS 打开后另存过**，交易单号变成了数字：要拒收并说明原因，不能带着错的单号入库。→ 任务 3 `test_read_wechat_rejects_numeric_tx_id`
2. **某个时间段里一笔交易都没有**（`共0笔记录`）：要能正常导入，报告显示 0 笔，不崩溃。→ 任务 3 `test_read_wechat_empty_bill`，任务 4 `test_apply_rules_empty`，任务 7 `test_empty_bill_imports_cleanly`
3. **金额是 19.6、0.07 这类浮点数，或者说明行的金额带千分位**：要精确换算到分。→ 任务 2 `test_to_cents`
4. **数据下面有空行，或交易对方名字前后有空格**：空行跳过；名字去掉首尾空格，否则归类对照表对不上。→ 任务 3 `test_read_wechat_strips_text_and_skips_blank_rows`
5. **出现没见过的交易类型或状态**：照常导入，但标成未识别、不计入统计，对账照样平，页面要提醒。→ 任务 5 `test_reconcile_lists_unknown_rows`，任务 7 `test_unknown_rows_are_imported_but_flagged`

## 文件结构

```
bill_pipeline/
  __init__.py
  model.py       公共类型：BillError、Summary、ParsedBill、ROW_COLUMNS
  convert.py     金额换算成分，时间换算成文字，分显示成元
  wechat.py      读微信 xlsx，得到 ParsedBill
  rules.py       清洗规则：每一行 → 结果、原因、固定类别、计入金额
  validate.py    第一关（和说明行核对）、文件内交易单号查重、第二关（对账表）
  db.py          SQLite：建表、整份入库（事务 + 去重）、归类对照表、月报查询
  pipeline.py    一份账单从读取到入库的完整流程，产出导入报告
app.py           Streamlit 页面
tests/
  __init__.py
  fakes.py       造假的微信账单
  test_*.py
.streamlit/config.toml
pyproject.toml
requirements.txt
README.md
```

---

### 任务 1：项目骨架

**文件：**
- 新建：`requirements.txt`、`pyproject.toml`、`.streamlit/config.toml`、`bill_pipeline/__init__.py`（空文件）、`tests/__init__.py`（空文件）
- 测试：`tests/test_smoke.py`

**接口：**
- 产出：可以 `import bill_pipeline`，`.venv/bin/pytest` 能运行。

- [ ] **第 1 步：建虚拟环境并安装依赖**

```bash
python3.13 -m venv .venv
.venv/bin/pip install pandas openpyxl streamlit pytest
.venv/bin/pip freeze | grep -iE '^(pandas|openpyxl|streamlit|pytest)==' > requirements.txt
```

预期：`requirements.txt` 里正好 4 行，每行都是 `包名==版本`。

- [ ] **第 2 步：写配置文件**

`pyproject.toml`：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`.streamlit/config.toml`：

```toml
[server]
address = "localhost"

[browser]
gatherUsageStats = false
```

- [ ] **第 3 步：写冒烟测试 `tests/test_smoke.py`**

```python
def test_package_imports():
    import bill_pipeline  # noqa: F401
```

- [ ] **第 4 步：运行测试**

运行：`.venv/bin/pytest -q`
预期：`1 passed`

- [ ] **第 5 步：提交**

```bash
git add requirements.txt pyproject.toml .streamlit/config.toml bill_pipeline/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: project skeleton"
```

---

### 任务 2：公共类型与换算

**文件：**
- 新建：`bill_pipeline/model.py`、`bill_pipeline/convert.py`
- 测试：`tests/test_convert.py`

**接口：**
- 产出（`model.py`）：
  - `class BillError(Exception)`：拒收原因，消息是给黄飞看的中文。
  - `@dataclass(frozen=True) class Summary`，字段依次为 `count: int`、`income_count: int`、`income_cents: int`、`expense_count: int`、`expense_cents: int`、`neutral_count: int`、`neutral_cents: int`。
  - `@dataclass class ParsedBill`，字段依次为 `source: str`、`period_start: str`、`period_end: str`、`summary: Summary`、`rows: pd.DataFrame`。
  - `ROW_COLUMNS = ["tx_id", "tx_time", "tx_type", "counterparty", "item", "direction", "amount_cents", "method", "status", "merchant_order", "note"]`
- 产出（`convert.py`）：
  - `to_cents(value) -> int`
  - `to_time_text(value) -> str`：返回 `"YYYY-MM-DD HH:MM:SS"`。
  - `yuan(cents: int) -> str`

- [ ] **第 1 步：写失败的测试 `tests/test_convert.py`**

```python
import datetime as dt

import pytest

from bill_pipeline.convert import to_cents, to_time_text, yuan
from bill_pipeline.model import BillError


@pytest.mark.parametrize("value, cents", [
    (19.6, 1960), (1631.04, 163104), (0.07, 7), (40, 4000),
    ("1,620.60", 162060), (" 80.08 ", 8008),
])
def test_to_cents(value, cents):
    assert to_cents(value) == cents


@pytest.mark.parametrize("value", [True, None, float("nan"), "abc", "1.234", 0.001, -5])
def test_to_cents_rejects(value):
    with pytest.raises(BillError):
        to_cents(value)


def test_to_time_text_accepts_datetime_serial_and_text():
    expected = "2026-10-01 12:00:00"
    serial = (dt.datetime(2026, 10, 1, 12) - dt.datetime(1899, 12, 30)).total_seconds() / 86400
    assert to_time_text(dt.datetime(2026, 10, 1, 12)) == expected
    assert to_time_text(serial) == expected
    assert to_time_text(" 2026-10-01 12:00:00 ") == expected


@pytest.mark.parametrize("value", [None, True, "2026/10/01", "昨天"])
def test_to_time_text_rejects(value):
    with pytest.raises(BillError):
        to_time_text(value)


def test_yuan():
    assert yuan(157444) == "1574.44"
    assert yuan(5) == "0.05"
    assert yuan(0) == "0.00"
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_convert.py -q`
预期：报错，原因是 `ModuleNotFoundError: No module named 'bill_pipeline.convert'`。

- [ ] **第 3 步：实现 `model.py` 和 `convert.py`**

`to_cents` 的规则：
- 先拒绝 bool（bool 是 int 的子类）。
- int 直接乘 100。float 先 `Decimal(str(value))`。字符串去掉首尾空白和逗号后转成 `Decimal`。
- 结果必须是有限数、不能是负数，乘 100 后必须是整数，否则抛 `BillError(f"金额不是有效数字：{value!r}")`。

`to_time_text` 的规则：
- 拒绝 bool。
- `datetime`（包括 pandas 的 Timestamp）直接格式化。
- int 或 float 当作 Excel 日期数字：`datetime(1899, 12, 30) + timedelta(seconds=round(value * 86400))`。
- 字符串去掉首尾空白后，按 `%Y-%m-%d %H:%M:%S` 解析。
- 其他情况抛 `BillError`。

- [ ] **第 4 步：运行，确认通过**

运行：`.venv/bin/pytest tests/test_convert.py -q`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add bill_pipeline/model.py bill_pipeline/convert.py tests/test_convert.py
git commit -m "feat: shared types and money/time conversion"
```

---

### 任务 3：造假账单，读微信账单

**文件：**
- 新建：`tests/fakes.py`、`bill_pipeline/wechat.py`
- 测试：`tests/test_wechat.py`

**接口：**
- 用到：任务 2 的 `BillError`、`Summary`、`ParsedBill`、`ROW_COLUMNS`、`to_cents`、`to_time_text`。
- 产出（`tests/fakes.py`）：
  - `make_row(n: int, day: int, hour: int, tx_type: str, who: str, direction: str, amount: float, status: str, method: str = "零钱") -> dict`：键是账单里的中文列名，见第 1 步。
  - `SAMPLE_ROWS: list[dict]`
  - `write_wechat_xlsx(path: Path, rows: list[dict] = SAMPLE_ROWS, *, title: str = "微信支付账单明细", summary_override: dict | None = None, time_as: str = "datetime", drop_columns: tuple = (), blank_rows_after: int = 0) -> Path`
- 产出（`bill_pipeline/wechat.py`）：
  - `WECHAT_COLUMNS: dict[str, str]`：中文列名 → `ROW_COLUMNS` 里的英文名。
  - `read_wechat(src) -> ParsedBill`：`src` 可以是路径，也可以是二进制文件对象（Streamlit 的上传文件）。

- [ ] **第 1 步：写 `tests/fakes.py`**

样例数据要原样照抄，后面所有任务的期望值都基于这 9 行：

```python
from datetime import datetime


def make_row(n, day, hour, tx_type, who, direction, amount, status, method="零钱"):
    return {
        "交易时间": datetime(2026, 10, day, hour, 0, 0), "交易类型": tx_type, "交易对方": who,
        "商品": "/", "收/支": direction, "金额(元)": amount, "支付方式": method,
        "当前状态": status, "交易单号": f"4200000000202610{n:012d}", "商户单号": "/", "备注": "/",
    }


SAMPLE_ROWS = [
    make_row(1, 1, 12, "商户消费", "食堂一楼", "支出", 12.5, "支付成功"),
    make_row(2, 2, 19, "商户消费", "星光球馆", "支出", 40.0, "支付成功"),
    make_row(3, 3, 8, "扫二维码付款", "张阿姨", "支出", 8.0, "已转账"),
    make_row(4, 3, 21, "转账", "球友A", "支出", 25.0, "对方已收钱"),
    make_row(5, 5, 10, "商户消费", "某电商", "支出", 19.6, "已全额退款"),
    make_row(6, 6, 10, "淘宝平台-退款", "某电商", "收入", 19.6, "已全额退款"),
    make_row(7, 7, 9, "转账", "爸爸", "收入", 1500.0, "已存入零钱"),
    make_row(8, 8, 20, "微信红包", "亲戚", "收入", 64.0, "已存入零钱"),
    make_row(9, 9, 15, "零钱提现", "某银行", "/", 80.08, "提现已到账", method="/"),
]
```

`write_wechat_xlsx` 用 openpyxl 写一个工作表，版式照真实账单：

| 行 | A 列内容 |
|---|---|
| 1 | `title` |
| 2 | `微信昵称：[测试用户]` |
| 3 | `起始时间：[2026-10-01 00:00:00] 终止时间：[2026-10-31 23:59:59]` |
| 4 | `导出类型：[全部账单]` |
| 5 | `导出时间：[2026-10-31 23:59:59]` |
| 6 | 空 |
| 7 | `共{n}笔记录`（键 `count`） |
| 8 | `收入：{笔数}笔 {金额:.2f}元`（键 `income`） |
| 9 | `支出：{笔数}笔 {金额:.2f}元`（键 `expense`） |
| 10 | `中性交易：{笔数}笔 {金额:.2f}元`（键 `neutral`） |
| 11–15 | `注：` 和四行注释，内容随意 |
| 16 | 空 |
| 17 | `----------------------微信支付账单明细列表--------------------` |
| 18 | 表头：11 个中文列名，顺序同 `make_row` |
| 19 起 | 每行一笔交易 |

参数说明：
- 第 7–10 行的笔数和金额按 `rows` 的 `收/支` 用 `Decimal` 现算。
- `summary_override` 按键整行替换；值为 `None` 时删掉那一行。
- `time_as="serial"` 时，交易时间写成 Excel 日期数字（float），而不是 datetime。
- `drop_columns` 里的列，在表头和数据里都去掉。
- `blank_rows_after` 在数据下面再写几行空字符串单元格。

- [ ] **第 2 步：写失败的测试 `tests/test_wechat.py`**

```python
import pytest

from bill_pipeline.model import ROW_COLUMNS, BillError, Summary
from bill_pipeline.wechat import read_wechat
from tests.fakes import SAMPLE_ROWS, write_wechat_xlsx


def test_read_wechat_summary_period_and_rows(tmp_path):
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx"))
    assert bill.source == "微信"
    assert (bill.period_start, bill.period_end) == ("2026-10-01 00:00:00", "2026-10-31 23:59:59")
    assert bill.summary == Summary(count=9, income_count=3, income_cents=158360,
                                   expense_count=5, expense_cents=10510,
                                   neutral_count=1, neutral_cents=8008)
    assert list(bill.rows.columns) == ROW_COLUMNS
    assert len(bill.rows) == 9
    first = bill.rows.iloc[0]
    assert first.tx_time == "2026-10-01 12:00:00"
    assert first.amount_cents == 1250
    assert first.counterparty == "食堂一楼"
    assert first.tx_id == "4200000000202610000000000001"


def test_read_wechat_excel_serial_dates(tmp_path):
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", time_as="serial"))
    assert bill.rows.iloc[0].tx_time == "2026-10-01 12:00:00"


def test_read_wechat_strips_text_and_skips_blank_rows(tmp_path):
    rows = [dict(SAMPLE_ROWS[0], **{"交易对方": "  食堂一楼  "})] + SAMPLE_ROWS[1:]
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", rows, blank_rows_after=2))
    assert len(bill.rows) == 9
    assert bill.rows.iloc[0].counterparty == "食堂一楼"


def test_read_wechat_empty_bill(tmp_path):
    bill = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", rows=[]))
    assert bill.summary.count == 0
    assert bill.rows.empty
    assert list(bill.rows.columns) == ROW_COLUMNS


@pytest.mark.parametrize("kwargs, message", [
    ({"title": "支付宝交易明细"}, "不是微信账单"),
    ({"drop_columns": ("交易时间",)}, "找不到表头"),
    ({"drop_columns": ("交易单号",)}, "交易单号"),
    ({"summary_override": {"expense": None}}, "说明行"),
])
def test_read_wechat_rejects_bad_files(tmp_path, kwargs, message):
    with pytest.raises(BillError, match=message):
        read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", **kwargs))


def test_read_wechat_rejects_non_xlsx(tmp_path):
    path = tmp_path / "b.xlsx"
    path.write_bytes(b"not an excel file")
    with pytest.raises(BillError, match="打不开"):
        read_wechat(path)


def test_read_wechat_rejects_numeric_tx_id(tmp_path):
    rows = [dict(SAMPLE_ROWS[0], **{"交易单号": 4.2e27})] + SAMPLE_ROWS[1:]
    with pytest.raises(BillError, match="交易单号不是文字"):
        read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", rows))
```

- [ ] **第 3 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_wechat.py -q`
预期：报错，原因是 `ModuleNotFoundError: No module named 'bill_pipeline.wechat'`。

- [ ] **第 4 步：实现 `read_wechat(src) -> ParsedBill`**

依次做下面这些，任何一步不对就抛 `BillError`，消息里要带上测试 `match` 的那几个字：

1. `pd.read_excel(src, header=None, dtype=object, engine="openpyxl")`。读取出任何异常都转成 `BillError("打不开文件：不是有效的 xlsx …")`。这里用 `except Exception`，不是裸 except，Ctrl+C 照样能中断。
2. 表头行：第一个有单元格去空白后等于 `交易时间` 的行。找不到 → `认不出账单：找不到表头“交易时间”`。
3. 说明文字：表头上方每行的非空单元格拼起来。表头上方第一个非空行去掉空白后，必须正好等于 `微信支付账单明细`，否则 → `不是微信账单…`。不能只查“包含”这几个字，因为分隔线里也有。
4. 表头缺了 `WECHAT_COLUMNS` 里的列 → `账单缺少这些列：…`，列名用 `、` 连接。
5. 汇总用正则从说明文字里取：`共\s*(\d+)\s*笔记录`、`收入[：:]\s*(\d+)\s*笔\s*([\d,.]+)\s*元`，`支出`、`中性交易` 同理。缺任何一项 → `说明行里找不到笔数和金额汇总：缺…`。金额用 `to_cents` 换算。
6. 起止时间用正则取 `起始时间[：:]\s*\[(.+?)\]` 和 `终止时间[：:]\s*\[(.+?)\]`，缺了 → `说明行里找不到起止时间`。
7. 数据：表头下面的行，跳过所有单元格都为空（NaN、None 或空白字符串）的行。每行：
   - 文字列转成 `str` 并去首尾空白，空值转成 `""`。
   - `交易单号` 必须本来就是字符串且不为空，否则 → `第 {N} 行的交易单号不是文字，文件可能被 Excel 另存过`。
   - 金额用 `to_cents`，时间用 `to_time_text`。出错时在消息前加 `第 {N} 行：`。
   - N 是 Excel 里的行号，等于 DataFrame 下标 + 1。
8. 返回 `ParsedBill(source="微信", …, rows=pd.DataFrame(records, columns=ROW_COLUMNS))`。没有交易时也要带齐这些列。

- [ ] **第 5 步：运行，确认通过**

运行：`.venv/bin/pytest tests/test_wechat.py -q`
预期：全部通过。

- [ ] **第 6 步：提交**

```bash
git add tests/fakes.py tests/test_wechat.py bill_pipeline/wechat.py
git commit -m "feat: read WeChat bill xlsx with header summary"
```

---

### 任务 4：清洗规则

**文件：**
- 新建：`bill_pipeline/rules.py`
- 测试：`tests/test_rules.py`

**接口：**
- 用到：任务 2 的 `ROW_COLUMNS`、`to_cents`；测试用任务 3 的 `read_wechat`、`write_wechat_xlsx`。
- 产出：
  - `CATEGORIES = ["吃饭", "运动", "娱乐", "购物", "交通", "其他"]`
  - `EXPENSE, INCOME, EXCLUDED, UNKNOWN = "消费", "收入", "不算", "未识别"`
  - `class Classified(NamedTuple)`，字段依次为 `result: str`、`reason: str`、`category: str | None`、`counted_cents: int`。
  - `classify(direction: str, tx_type: str, status: str, amount_cents: int) -> Classified`
  - `apply_rules(rows: pd.DataFrame) -> pd.DataFrame`：返回副本，多出 `result`、`reason`、`category`、`counted_cents` 四列，不改传进来的表。

规则按下面的顺序匹配，命中第一条就停（原因文字照抄，报告和对账表直接显示它）：

| 顺序 | 条件 | 结果 | 原因 | 类别 | 计入金额 |
|---|---|---|---|---|---|
| 1 | `direction == "/"` | 不算 | `中性交易` | None | 0 |
| 2 | `status` 是 `交易关闭` 或 `支付失败` | 不算 | `失败或关闭` | None | 0 |
| 3 | 支出，且 `status == "已全额退款"` | 不算 | `全额退款的原交易` | None | 0 |
| 4 | 收入，且（`tx_type` 以 `-退款` 结尾，或 `status == "已全额退款"`） | 不算 | `退款` | None | 0 |
| 5 | 支出，`status` 匹配 `^已退款[（(][￥¥]?(\d+(?:\.\d{1,2})?)[)）]$`，且 0 < 已退金额 < 金额 | 消费 | `部分退款（待确认）` | None | 金额 − 已退金额 |
| 6 | （支出，`商户消费`，`支付成功`） | 消费 | `消费` | None | 金额 |
| 6 | （支出，`扫二维码付款`，`已转账`） | 消费 | `消费` | None | 金额 |
| 6 | （支出，`转账`，`对方已收钱`） | 消费 | `转账（归其他）` | `其他` | 金额 |
| 6 | （收入，`转账`，`已存入零钱`） | 收入 | `转账收入` | None | 金额 |
| 6 | （收入，`微信红包`，`已存入零钱`） | 收入 | `收红包（待确认）` | None | 金额 |
| 7 | 支出，且 `tx_type == "微信红包"` | 消费 | `发红包（归其他，待确认）` | `其他` | 金额 |
| 8 | 其他所有情况 | 未识别 | `未识别（{tx_type}/{status}）` | None | 0 |

第 6 条是一张（收/支，交易类型，状态）→ 结果的对照表，写成一个 dict。

- [ ] **第 1 步：写失败的测试 `tests/test_rules.py`**

```python
import pandas as pd
import pytest

from bill_pipeline.model import ROW_COLUMNS
from bill_pipeline.rules import apply_rules, classify
from bill_pipeline.wechat import read_wechat
from tests.fakes import write_wechat_xlsx


@pytest.mark.parametrize("args, expected", [
    (("/", "零钱提现", "提现已到账", 8008), ("不算", "中性交易", None, 0)),
    (("支出", "商户消费", "支付失败", 500), ("不算", "失败或关闭", None, 0)),
    (("支出", "商户消费", "已全额退款", 1960), ("不算", "全额退款的原交易", None, 0)),
    (("收入", "淘宝平台-退款", "已全额退款", 1960), ("不算", "退款", None, 0)),
    (("支出", "商户消费", "已退款(￥5.00)", 2000), ("消费", "部分退款（待确认）", None, 1500)),
    (("支出", "商户消费", "已退款（¥20.00）", 2000), ("未识别", "未识别（商户消费/已退款（¥20.00））", None, 0)),
    (("支出", "商户消费", "支付成功", 1250), ("消费", "消费", None, 1250)),
    (("支出", "扫二维码付款", "已转账", 800), ("消费", "消费", None, 800)),
    (("支出", "转账", "对方已收钱", 2500), ("消费", "转账（归其他）", "其他", 2500)),
    (("收入", "转账", "已存入零钱", 150000), ("收入", "转账收入", None, 150000)),
    (("收入", "微信红包", "已存入零钱", 6400), ("收入", "收红包（待确认）", None, 6400)),
    (("支出", "微信红包", "已领取", 2000), ("消费", "发红包（归其他，待确认）", "其他", 2000)),
    (("支出", "转账", "已退还", 2500), ("未识别", "未识别（转账/已退还）", None, 0)),
    (("收入", "二手交易", "已收钱", 3000), ("未识别", "未识别（二手交易/已收钱）", None, 0)),
])
def test_classify(args, expected):
    assert classify(*args) == expected


def test_apply_rules_adds_columns_and_keeps_input(tmp_path):
    rows = read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx")).rows
    out = apply_rules(rows)
    assert list(out.columns) == ROW_COLUMNS + ["result", "reason", "category", "counted_cents"]
    assert out.groupby("result").counted_cents.sum().to_dict() == {"不算": 0, "收入": 156400, "消费": 8550}
    assert out.loc[out.counterparty == "球友A", "category"].item() == "其他"
    assert list(rows.columns) == ROW_COLUMNS


def test_apply_rules_empty():
    out = apply_rules(pd.DataFrame(columns=ROW_COLUMNS))
    assert out.empty
    assert "counted_cents" in out.columns
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_rules.py -q`
预期：报错，原因是 `ModuleNotFoundError: No module named 'bill_pipeline.rules'`。

- [ ] **第 3 步：实现 `classify` 和 `apply_rules`**

`apply_rules` 用 `zip(rows.direction, rows.tx_type, rows.status, rows.amount_cents)` 逐行调用 `classify`，再把结果分别赋成四列。不要用 `DataFrame.apply`：表为空时它拿不到列，会出错。

- [ ] **第 4 步：运行，确认通过**

运行：`.venv/bin/pytest tests/test_rules.py -q`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add bill_pipeline/rules.py tests/test_rules.py
git commit -m "feat: cleaning rules"
```

---

### 任务 5：第一关、文件内查重、第二关（对账）

**文件：**
- 新建：`bill_pipeline/validate.py`
- 测试：`tests/test_validate.py`

**接口：**
- 用到：任务 2 的 `BillError`、`ParsedBill`、`Summary`、`yuan`；任务 4 的 `apply_rules` 和四个结果常量。
- 产出：
  - `check_summary(bill: ParsedBill) -> None`
  - `check_unique_ids(bill: ParsedBill) -> None`
  - `class ReconLine(NamedTuple)`，字段依次为 `direction: str`、`label: str`、`count: int`、`cents: int`。
  - `reconcile(rows: pd.DataFrame, summary: Summary) -> list[ReconLine]`：`rows` 必须已经过 `apply_rules`。

`check_summary` 依次检查：
1. `收/支` 只能是 `支出`、`收入`、`/`。出现别的值 → `收/支 出现没见过的值：…`。
2. 总笔数等于 `summary.count`，否则 → `读出来共 {a} 笔，说明行写的是共 {b} 笔`。
3. 三个方向各自的笔数和金额都要等于说明行。不等时，每个不等的方向写一句：`读出来的{支出/收入/中性交易}是 {n} 笔 {元} 元，说明行写的是 {m} 笔 {元} 元`。

`check_unique_ids`：同一个文件里交易单号重复 → `文件里交易单号重复：{k} 个`。

`reconcile`：方向按 `支出`、`收入`、`/` 的顺序处理，`/` 在对账行里显示为 `中性交易`。每个方向产出：
1. `ReconLine(方向, "平台合计", 说明行笔数, 说明行金额)`
2. 这个方向里 `amount_cents > counted_cents` 的行按 `reason` 分组，按原因文字排序，每组一行：`ReconLine(方向, f"减：{reason}", 笔数, Σ(amount_cents − counted_cents))`
3. `ReconLine(方向, "= 计入", 笔数, Σcounted_cents)`。只算结果等于这个方向应计结果的行：支出算 `消费`，收入算 `收入`，中性交易永远是 0 笔 0 分。

如果 平台合计 − Σ减项 ≠ 计入，抛 `BillError(f"对账不平：{方向} 平台合计 {yuan} 元 − 减项 {yuan} 元 ≠ 计入 {yuan} 元")`。

- [ ] **第 1 步：写失败的测试 `tests/test_validate.py`**

```python
import pytest

from bill_pipeline.model import BillError
from bill_pipeline.rules import apply_rules
from bill_pipeline.validate import ReconLine, check_summary, check_unique_ids, reconcile
from bill_pipeline.wechat import read_wechat
from tests.fakes import SAMPLE_ROWS, make_row, write_wechat_xlsx


def _bill(tmp_path, **kwargs):
    return read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", **kwargs))


def test_check_summary_passes(tmp_path):
    check_summary(_bill(tmp_path))


@pytest.mark.parametrize("override, message", [
    ({"expense": "支出：5笔 105.11元"}, "支出"),
    ({"income": "收入：4笔 1583.60元"}, "收入"),
    ({"count": "共10笔记录"}, "共"),
])
def test_check_summary_mismatch(tmp_path, override, message):
    with pytest.raises(BillError, match=message):
        check_summary(_bill(tmp_path, summary_override=override))


def test_check_summary_unknown_direction(tmp_path):
    rows = [dict(SAMPLE_ROWS[0], **{"收/支": "其他"})] + SAMPLE_ROWS[1:]
    with pytest.raises(BillError, match="收/支"):
        check_summary(_bill(tmp_path, rows=rows))


def test_check_unique_ids(tmp_path):
    with pytest.raises(BillError, match="交易单号重复"):
        check_unique_ids(_bill(tmp_path, rows=SAMPLE_ROWS + [dict(SAMPLE_ROWS[0])]))


def test_reconcile_sample(tmp_path):
    bill = _bill(tmp_path)
    assert reconcile(apply_rules(bill.rows), bill.summary) == [
        ReconLine("支出", "平台合计", 5, 10510),
        ReconLine("支出", "减：全额退款的原交易", 1, 1960),
        ReconLine("支出", "= 计入", 4, 8550),
        ReconLine("收入", "平台合计", 3, 158360),
        ReconLine("收入", "减：退款", 1, 1960),
        ReconLine("收入", "= 计入", 2, 156400),
        ReconLine("中性交易", "平台合计", 1, 8008),
        ReconLine("中性交易", "减：中性交易", 1, 8008),
        ReconLine("中性交易", "= 计入", 0, 0),
    ]


def test_reconcile_catches_rule_bug(tmp_path):
    bill = _bill(tmp_path)
    rows = apply_rules(bill.rows)
    rows.loc[rows.counterparty == "食堂一楼", "result"] = "收入"  # 支出行被错算成收入
    with pytest.raises(BillError, match="对账不平"):
        reconcile(rows, bill.summary)


def test_reconcile_lists_unknown_rows(tmp_path):
    rows = SAMPLE_ROWS + [make_row(10, 10, 10, "二手交易", "闲鱼买家", "收入", 30.0, "已收钱")]
    bill = _bill(tmp_path, rows=rows)
    lines = reconcile(apply_rules(bill.rows), bill.summary)
    assert ReconLine("收入", "减：未识别（二手交易/已收钱）", 1, 3000) in lines
    assert ReconLine("收入", "= 计入", 2, 156400) in lines
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_validate.py -q`
预期：报错，原因是 `ModuleNotFoundError: No module named 'bill_pipeline.validate'`。

- [ ] **第 3 步：按上面的说明实现三个函数和 `ReconLine`**

- [ ] **第 4 步：运行，确认通过**

运行：`.venv/bin/pytest tests/test_validate.py -q`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add bill_pipeline/validate.py tests/test_validate.py
git commit -m "feat: summary check, duplicate ids and reconciliation"
```

---

### 任务 6：数据库

**文件：**
- 新建：`bill_pipeline/db.py`
- 测试：`tests/test_db.py`

**接口：**
- 用到：任务 2 的 `ParsedBill`；任务 4 的 `CATEGORIES`；`rows` 是 `apply_rules` 的输出。
- 产出：
  - `connect(path: str | Path) -> sqlite3.Connection`：不存在的父目录先建好，打开外键，执行建表语句。
  - `save_import(conn, bill: ParsedBill, rows: pd.DataFrame, file_name: str) -> tuple[int, int]`：返回（新增笔数，跳过笔数）。
  - `unmapped_counterparties(conn) -> list[tuple[str, int, int]]`：没有固定类别、对照表里也没有的消费交易对方，返回（交易对方，笔数，计入金额），按金额从大到小排。
  - `set_category(conn, counterparty: str, category: str) -> None`：类别不在 `CATEGORIES` 里就抛 `ValueError`；已有对照时覆盖（UPSERT）。
  - `months(conn) -> list[str]`：有交易的月份 `YYYY-MM`，从新到旧排。
  - `month_totals(conn, month: str) -> tuple[int, int]`：（消费计入合计，收入计入合计），没有数据时是 0。
  - `month_by_category(conn, month: str) -> list[tuple[str, int]]`：这个月各类消费，类别取 `COALESCE(t.category, m.category, '未归类')`，按金额从大到小排。

建表语句照抄：

```sql
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    source TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    rows_total INTEGER NOT NULL,
    rows_new INTEGER,
    rows_skipped INTEGER
);
CREATE TABLE IF NOT EXISTS transactions (
    source TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    tx_time TEXT NOT NULL,
    tx_type TEXT NOT NULL,
    counterparty TEXT NOT NULL,
    item TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    merchant_order TEXT NOT NULL,
    note TEXT NOT NULL,
    result TEXT NOT NULL,
    reason TEXT NOT NULL,
    category TEXT,
    counted_cents INTEGER NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    PRIMARY KEY (source, tx_id)
);
CREATE TABLE IF NOT EXISTS counterparty_categories (
    counterparty TEXT PRIMARY KEY,
    category TEXT NOT NULL
);
```

`save_import` 的要求：
- 整个过程放在一个 `with conn:` 里：先插入 `imports` 拿到 id，再插入交易，最后回写 `rows_new`、`rows_skipped`。
- 插入交易用 `INSERT … ON CONFLICT(source, tx_id) DO NOTHING`，不要用 `INSERT OR IGNORE`：后者会把 NOT NULL 违规也悄悄跳过，坏行会被当成“已存在”。
- 新增笔数取 `executemany` 返回的 `rowcount`。
- 记录用 `rows.to_dict("records")` 配合命名参数，再补上 `source` 和 `import_id`。直接用 itertuples 会带出 numpy 类型，sqlite3 绑定不了。
- 按月统计用 `substr(tx_time, 1, 7)`。

- [ ] **第 1 步：写失败的测试 `tests/test_db.py`**

```python
import sqlite3

import pytest

from bill_pipeline.db import (connect, month_by_category, month_totals, months, save_import,
                              set_category, unmapped_counterparties)
from bill_pipeline.rules import apply_rules
from bill_pipeline.wechat import read_wechat
from tests.fakes import SAMPLE_ROWS, make_row, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "data" / "t.db")


def _prepared(tmp_path, name="b.xlsx", **kwargs):
    bill = read_wechat(write_wechat_xlsx(tmp_path / name, **kwargs))
    return bill, apply_rules(bill.rows)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_save_import_and_reimport(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    assert save_import(conn, bill, rows, "b.xlsx") == (9, 0)
    assert save_import(conn, bill, rows, "b.xlsx") == (0, 9)
    assert _count(conn, "transactions") == 9
    assert _count(conn, "imports") == 2


def test_overlapping_export(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    later = SAMPLE_ROWS[4:] + [make_row(10, 20, 12, "商户消费", "食堂一楼", "支出", 15.0, "支付成功")]
    bill2, rows2 = _prepared(tmp_path, "c.xlsx", rows=later)
    assert save_import(conn, bill2, rows2, "c.xlsx") == (1, 5)


def test_save_import_is_all_or_nothing(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    rows.loc[rows.index[-1], "tx_id"] = None  # 最后一行违反 NOT NULL
    with pytest.raises(sqlite3.IntegrityError):
        save_import(conn, bill, rows, "b.xlsx")
    assert _count(conn, "transactions") == 0
    assert _count(conn, "imports") == 0


def test_categories_and_month_report(conn, tmp_path):
    bill, rows = _prepared(tmp_path)
    save_import(conn, bill, rows, "b.xlsx")
    assert unmapped_counterparties(conn) == [("星光球馆", 1, 4000), ("食堂一楼", 1, 1250), ("张阿姨", 1, 800)]
    assert ("未归类", 6050) in month_by_category(conn, "2026-10")
    set_category(conn, "星光球馆", "运动")
    set_category(conn, "食堂一楼", "吃饭")
    set_category(conn, "张阿姨", "吃饭")
    assert unmapped_counterparties(conn) == []
    assert months(conn) == ["2026-10"]
    assert month_totals(conn, "2026-10") == (8550, 156400)
    assert month_by_category(conn, "2026-10") == [("运动", 4000), ("其他", 2500), ("吃饭", 2050)]


def test_set_category_rejects_unknown(conn):
    with pytest.raises(ValueError):
        set_category(conn, "某店", "零食")
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_db.py -q`
预期：报错，原因是 `ModuleNotFoundError: No module named 'bill_pipeline.db'`。

- [ ] **第 3 步：按上面的说明实现 `db.py`**

- [ ] **第 4 步：运行，确认通过**

运行：`.venv/bin/pytest tests/test_db.py -q`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add bill_pipeline/db.py tests/test_db.py
git commit -m "feat: sqlite storage with dedupe, categories and month queries"
```

---

### 任务 7：导入流程

**文件：**
- 新建：`bill_pipeline/pipeline.py`
- 测试：`tests/test_pipeline.py`

**接口：**
- 用到：任务 3 的 `read_wechat`，任务 4 的 `apply_rules`，任务 5 的 `check_summary`、`check_unique_ids`、`reconcile`、`ReconLine`，任务 6 的 `save_import`。
- 产出：
  - `read_bill(src, file_name: str) -> ParsedBill`：文件名以 `.xlsx` 结尾（不分大小写）就交给 `read_wechat`；其他情况抛 `BillError(f"暂时只支持微信账单（.xlsx）：{file_name}")`。以后支付宝从这里接入。
  - `@dataclass class ImportReport`，字段依次为 `file_name: str`、`source: str`、`period_start: str`、`period_end: str`、`total: int`、`new: int`、`skipped: int`、`unknown: int`、`recon: list[ReconLine]`。
  - `import_bill(conn, src, file_name: str) -> ImportReport`：依次调用 `read_bill` → `check_summary` → `check_unique_ids` → `apply_rules` → `reconcile` → `save_import`。入库放在最后一步，前面任何一步拒收，库里都不会多出任何东西。`unknown` 是结果为 `未识别` 的笔数。

- [ ] **第 1 步：写失败的测试 `tests/test_pipeline.py`**

```python
import io

import pytest

from bill_pipeline.db import connect, month_totals
from bill_pipeline.model import BillError
from bill_pipeline.pipeline import import_bill
from bill_pipeline.validate import ReconLine
from tests.fakes import SAMPLE_ROWS, make_row, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.db")


def test_import_bill_end_to_end(conn, tmp_path):
    path = write_wechat_xlsx(tmp_path / "b.xlsx")
    report = import_bill(conn, path, "b.xlsx")
    assert (report.source, report.total, report.new, report.skipped, report.unknown) == ("微信", 9, 9, 0, 0)
    assert ReconLine("支出", "= 计入", 4, 8550) in report.recon
    again = import_bill(conn, path, "b.xlsx")
    assert (again.new, again.skipped) == (0, 9)


def test_import_bill_accepts_uploaded_bytes(conn, tmp_path):
    data = write_wechat_xlsx(tmp_path / "b.xlsx").read_bytes()
    assert import_bill(conn, io.BytesIO(data), "b.xlsx").new == 9


def test_rejected_bill_saves_nothing(conn, tmp_path):
    path = write_wechat_xlsx(tmp_path / "b.xlsx", summary_override={"expense": "支出：5笔 105.11元"})
    with pytest.raises(BillError):
        import_bill(conn, path, "b.xlsx")
    assert conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0


def test_unsupported_file_type(conn):
    with pytest.raises(BillError, match="只支持微信"):
        import_bill(conn, io.BytesIO(b"a,b"), "bill.csv")


def test_unknown_rows_are_imported_but_flagged(conn, tmp_path):
    rows = SAMPLE_ROWS + [make_row(10, 10, 10, "二手交易", "闲鱼买家", "收入", 30.0, "已收钱")]
    report = import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx", rows=rows), "b.xlsx")
    assert report.unknown == 1
    assert month_totals(conn, "2026-10") == (8550, 156400)


def test_empty_bill_imports_cleanly(conn, tmp_path):
    report = import_bill(conn, write_wechat_xlsx(tmp_path / "b.xlsx", rows=[]), "b.xlsx")
    assert (report.total, report.new, report.skipped) == (0, 0, 0)
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_pipeline.py -q`
预期：报错，原因是 `ModuleNotFoundError: No module named 'bill_pipeline.pipeline'`。

- [ ] **第 3 步：实现 `read_bill`、`ImportReport`、`import_bill`**

- [ ] **第 4 步：运行全部测试**

运行：`.venv/bin/pytest -q`
预期：全部通过。

- [ ] **第 5 步：提交**

```bash
git add bill_pipeline/pipeline.py tests/test_pipeline.py
git commit -m "feat: import pipeline with report"
```

---

### 任务 8：页面

**文件：**
- 新建：`app.py`
- 测试：`tests/test_app.py`

**接口：**
- 用到：任务 6 的 `connect`、`unmapped_counterparties`、`set_category`、`months`、`month_totals`、`month_by_category`；任务 7 的 `import_bill`；任务 4 的 `CATEGORIES`；任务 2 的 `yuan`、`BillError`。
- 产出：`streamlit run app.py` 能打开的页面。

页面从上到下：
- 数据库路径：`DB_PATH = Path(os.environ.get("BILL_DB", Path(__file__).parent / "data" / "bills.db"))`。环境变量只给测试用，平时不设。
- 标题：`st.title("账单流水线")`
- **导入账单**（`st.header`）：
  - `st.file_uploader("上传微信账单（.xlsx），可以一次选多份", type=["xlsx"], accept_multiple_files=True)`，再加一个按钮 `导入`。
  - 按下按钮后逐份调用 `import_bill(conn, f, f.name)`：
    - 成功：`st.success(f"{f.name}：新增 {new} 笔，跳过 {skipped} 笔已存在")`，再用 `st.dataframe` 显示对账表，列为 `方向`、`项目`、`笔数`、`金额（元）`，金额用 `yuan`。
    - `unknown > 0` 时：`st.warning(f"有 {unknown} 笔没见过的交易类型或状态，没算进统计，需要补规则")`。
    - `BillError`：`st.error(f"{f.name} 拒收：{e}")`，接着处理下一份。
- **给交易对方归类**（`st.header`）：
  - 没有未归类的交易对方时：`st.caption("都归好类了")`。
  - 有的话放进一个 `st.form`，每个交易对方一个 `st.selectbox`：标签是 `f"{名字}（{笔数} 笔，{yuan(金额)} 元）"`，选项是 `["（先不归）"] + CATEGORIES`。
  - 提交按钮 `保存归类`。按下后，对选了类别的调用 `set_category`，然后 `st.rerun()`。
- **月报**（`st.header`）：
  - 没有数据时：`st.info("还没有导入账单")`。
  - 有数据时：`st.selectbox("月份", months(conn), key="month")`。
  - 两个 `st.metric`：`消费`、`收入`，值是 `f"{yuan(cents)} 元"`。
  - 各类消费：`st.bar_chart`（数值用 `cents / 100`，只用于画图），再加一张表，金额用 `yuan`。

- [ ] **第 1 步：写失败的测试 `tests/test_app.py`**

```python
from pathlib import Path

from streamlit.testing.v1 import AppTest

from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill
from tests.fakes import write_wechat_xlsx

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_with_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BILL_DB", str(tmp_path / "t.db"))
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert at.title[0].value == "账单流水线"


def test_app_shows_month_report(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    import_bill(connect(db_path), write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    monkeypatch.setenv("BILL_DB", str(db_path))
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert at.selectbox(key="month").value == "2026-10"
    assert at.metric[0].value == "85.50 元"
```

- [ ] **第 2 步：运行，确认失败**

运行：`.venv/bin/pytest tests/test_app.py -q`
预期：失败，原因是 `app.py` 不存在。

- [ ] **第 3 步：按上面的说明实现 `app.py`**

- [ ] **第 4 步：运行全部测试**

运行：`.venv/bin/pytest -q`
预期：全部通过。

- [ ] **第 5 步：实际打开页面看一眼**

运行：`.venv/bin/streamlit run app.py --server.headless true`（放到后台），用浏览器打开 `http://localhost:8501`，然后关掉。
预期：三块都在，没有报错。启动信息里不应出现局域网 IP 地址，因为只监听本机。

- [ ] **第 6 步：提交**

```bash
git add app.py tests/test_app.py
git commit -m "feat: streamlit page for import, categorizing and monthly report"
```

---

### 任务 9：用黄飞的真实微信账单验收

只看统计，不看明细。真实数字不写进这个仓库。

- [ ] **第 1 步：在临时数据库里导两遍真实账单，只打印笔数和对账行**

```bash
.venv/bin/python - <<'EOF'
import pathlib, tempfile
from bill_pipeline.db import connect
from bill_pipeline.pipeline import import_bill

src = sorted(pathlib.Path.home().glob("下载/微信支付账单流水文件*.xlsx"))[-1]
with tempfile.TemporaryDirectory() as d:
    conn = connect(pathlib.Path(d) / "check.db")
    for _ in range(2):
        r = import_bill(conn, src, src.name)
        print("共", r.total, "新增", r.new, "跳过", r.skipped, "未识别", r.unknown)
        for line in r.recon:
            print(line)
EOF
```

预期：
- 第一遍：新增等于共几笔，跳过 0，未识别 0。
- 第二遍：新增 0。
- 支出和收入的 `= 计入` 两行，和笔记仓库 `导师/项目/bill-pipeline 带练记录.md` 里“真实数据对账基准”的数字一致。

- [ ] **第 2 步：处理不一致**

如果被拒收、对账不平或者出现未识别，把拒收消息或未识别的（类型/状态）告诉黄飞，等他定规则。不要自己改规则，也不要改测试去迁就。

- [ ] **第 3 步：交给黄飞**

请黄飞运行 `.venv/bin/streamlit run app.py`，自己上传账单，给交易对方归类。这一步 AI 不看名字。然后在笔记仓库的带练记录里勾上“微信账单跑通”。

---

### 任务 10：英文 README

**文件：**
- 新建：`README.md`

- [ ] **第 1 步：写 README.md（英文）**

按这个顺序写下面几节，内容来自设计文档，不写任何真实数字：

1. **标题和一句话简介**：A local data pipeline that collects, cleans, validates, stores and analyzes personal WeChat Pay bills.
2. **Why**：改进前后对比的 mermaid 流程图。
   - Before：手动在终端记账本里录入，只存“备注 → 累计金额”，没有日期。
   - After：export → upload → clean → three checks → categorize → monthly report。
   - 下面再放一张 pain point → improvement 的表。
3. **Cleaning rules**：设计文档第 4 节的表译成英文，保留 “pending confirmation” 标记。
4. **Validation**：文件检查、check 1（与说明行核对）、check 2（对账）、check 3（按来源 + 交易单号去重）、整份入库要么全成功要么全不进。
5. **Privacy**：只在本机运行；Streamlit 只监听 localhost，关闭使用统计；真实账单和数据库都在 .gitignore 里；测试只用生成的假账单。
6. **How to run**：建 venv、`pip install -r requirements.txt`、`streamlit run app.py`、`pytest`。
7. **Project structure**：每个模块一句话。
8. **Credits**：Requirements, cleaning rules and validation design by Huang Fei; code written with AI coding assistance (Claude Code).
9. **Roadmap**：Alipay import; AI-suggested categories confirmed by the user; natural-language questions through the demo B agent.

- [ ] **第 2 步：检查**

用支持 mermaid 的预览（比如 VS Code）打开，确认流程图能渲染。再确认里面没有真实金额、真实交易对方、银行名。

- [ ] **第 3 步：提交**

```bash
git add README.md
git commit -m "docs: English README"
```
