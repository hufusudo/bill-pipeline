from bill_pipeline.rules import CATEGORIES
from bill_pipeline.validate import ReconLine
from web.theme import CATEGORY_COLORS, daily_option, donut_option, money, monthly_option, waterfall_option


def test_every_category_has_a_color():
    assert set(CATEGORY_COLORS) == set(CATEGORIES) | {"未归类"}


def test_money():
    assert money(128650) == "¥1,286.50"
    assert money(-8650) == "−¥86.50"
    assert money(0) == "¥0.00"


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
