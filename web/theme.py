"""界面的颜色、样式、动画脚本和图表配置。图表配置都是纯函数：输入数据，返回 ECharts 的 option 字典。"""
from decimal import Decimal

from bill_pipeline.rules import OTHER
from bill_pipeline.validate import ReconLine

ACCENT = "#1baf7a"
TEXT = "#111827"
MUTED = "#6b7584"
GRID = "#eef1f5"
SURFACE = "#ffffff"
DIM = "#dde3ea"
BASE = "#c3c9d3"
MINUS = "#eb6834"

# 分类颜色按分类顺序取。这 8 种颜色按这个顺序相邻时，用 dataviz 的配色脚本验证过；按金额排序会打乱
PALETTE = ["#1baf7a", "#2a78d6", "#eb6834", "#6250d6", "#eda100", "#e87ba4", "#008300", "#e34948"]
OTHER_COLOR, UNCATEGORIZED_COLOR, EXTRA_COLOR = "#c3c9d3", "#e5e9ef", "#9aa3af"

AXIS = {"axisLine": {"show": False}, "axisTick": {"show": False}}
AXIS_LABEL = {"color": MUTED, "fontSize": 12}
TOOLTIP = {"backgroundColor": SURFACE, "borderColor": GRID, "textStyle": {"color": TEXT, "fontSize": 13},
           "extraCssText": "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.12);"}
GRID_BOX = {"left": 6, "right": 18, "top": 36, "bottom": 6, "containLabel": True}
# 冒号开头的键是 NiceGUI 的写法：值是一段 JavaScript，在浏览器里变成函数
JS_MONEY = "v => '¥' + v.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})"


def money(cents: int) -> str:
    """显示用的金额：¥1,286.50；负数写成 −¥86.50。"""
    sign = "−" if cents < 0 else ""
    return f"{sign}¥{Decimal(abs(int(cents))) / 100:,.2f}"


def category_colors(names: list[str]) -> dict[str, str]:
    """“其他”灰色，“未归类”浅灰；其余按顺序用色板，超过 8 个的用中灰，靠名字区分。"""
    colored = [name for name in names if name != OTHER]
    colors = {name: PALETTE[i] if i < len(PALETTE) else EXTRA_COLOR for i, name in enumerate(colored)}
    return {**colors, OTHER: OTHER_COLOR, "未归类": UNCATEGORIZED_COLOR}


def donut_option(by_category: list[tuple[str, int]], order: list[str]) -> dict:
    """扇区按分类顺序排，颜色跟着分类走，不跟着金额排名走。"""
    amounts = dict(by_category)
    colors = category_colors(order)
    names = order + ["未归类"] + [name for name in amounts if name not in order and name != "未归类"]
    data = [{"name": name, "value": amounts[name] / 100, "text": money(amounts[name]),
             "itemStyle": {"color": colors.get(name, EXTRA_COLOR)}}
            for name in names if amounts.get(name, 0) > 0]
    option = {
        "tooltip": {"trigger": "item", **TOOLTIP,
                    ":formatter": "p => `${p.marker}${p.name}　${p.data.text}（${p.percent}%）`"},
        "series": [{
            "type": "pie", "radius": ["60%", "82%"], "center": ["50%", "50%"],
            "label": {"show": False}, "labelLine": {"show": False},
            "itemStyle": {"borderColor": SURFACE, "borderWidth": 2, "borderRadius": 4},
            "emphasis": {"scale": True, "scaleSize": 6},
            "data": data,
            "animationType": "expansion", "animationDuration": 1200, "animationEasing": "cubicOut",
        }],
    }
    if data:
        total = sum(amounts[d["name"]] for d in data)
        top = max(data, key=lambda d: amounts[d["name"]])["name"]
        option["graphic"] = {"type": "text", "left": "center", "top": "middle", "style": {
            "text": f"花得最多\n{top} {round(amounts[top] / total * 100)}%",
            "fill": TEXT, "font": "600 18px sans-serif", "textAlign": "center", "lineHeight": 28}}
    return option


def daily_option(days: list[tuple[str, int]]) -> dict:
    return {
        "grid": GRID_BOX,
        "tooltip": {"trigger": "axis", **TOOLTIP, ":valueFormatter": JS_MONEY,
                    "axisPointer": {"type": "line", "lineStyle": {"color": MUTED, "width": 1}}},
        "xAxis": {"type": "category", "boundaryGap": False, "data": [day[5:] for day, _ in days], **AXIS,
                  "axisLabel": {**AXIS_LABEL, "interval": 6}},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": GRID}}, **AXIS,
                  "axisLabel": {**AXIS_LABEL, ":formatter": "v => '¥' + v"}},
        "series": [{
            "name": "当天消费", "type": "line", "smooth": 0.3, "showSymbol": False, "symbol": "circle", "symbolSize": 8,
            "data": [cents / 100 for _, cents in days],
            "lineStyle": {"width": 2, "color": ACCENT},
            "itemStyle": {"color": ACCENT, "borderColor": SURFACE, "borderWidth": 2},
            "areaStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [
                {"offset": 0, "color": "rgba(27,175,122,.24)"}, {"offset": 1, "color": "rgba(27,175,122,0)"}]}},
            "markPoint": {"symbol": "circle", "symbolSize": 9,
                          "itemStyle": {"color": ACCENT, "borderColor": SURFACE, "borderWidth": 2},
                          "label": {"show": True, "position": "top", "distance": 8, "color": TEXT, "fontSize": 12,
                                    "fontWeight": 600, ":formatter": f"p => '最高 ' + ({JS_MONEY})(p.value)"},
                          "data": [{"type": "max"}]},
            "animationDuration": 1700, "animationEasing": "cubicInOut",
        }],
    }


def monthly_option(months: list[tuple[str, int]], current: str) -> dict:
    return {
        "grid": GRID_BOX,
        "tooltip": {"trigger": "item", **TOOLTIP, ":formatter": f"p => p.name + '　' + ({JS_MONEY})(p.value)"},
        "xAxis": {"type": "category", "data": [f"{int(month[5:7])} 月" for month, _ in months], **AXIS,
                  "axisLabel": AXIS_LABEL},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": GRID}}, **AXIS,
                  "axisLabel": {**AXIS_LABEL, ":formatter": "v => '¥' + v"}},
        "series": [{
            "type": "bar", "barWidth": "38%",
            "data": [{"value": cents / 100,
                      "itemStyle": {"color": ACCENT if month == current else DIM, "borderRadius": [4, 4, 0, 0]},
                      "label": {"show": month == current, "position": "top", "color": TEXT, "fontWeight": 600,
                                ":formatter": f"p => ({JS_MONEY})(p.value)"}}
                     for month, cents in months],
            ":animationDelay": "i => i * 110", "animationDuration": 900, "animationEasing": "cubicOut",
        }],
    }


def waterfall_option(lines: list[ReconLine]) -> dict:
    """lines 是某一个方向的对账行：平台合计、若干减项、= 计入。"""
    platform, *deductions, kept = lines
    names = ["账单支出"] + [line.label.removeprefix("减：") for line in deductions] + ["实际消费"]
    remaining, bases = platform.cents, [0]
    for line in deductions:
        remaining -= line.cents
        bases.append(remaining / 100)
    bases.append(0)
    values = [platform.cents] + [line.cents for line in deductions] + [kept.cents]
    texts = [money(platform.cents)] + ["−" + money(line.cents) for line in deductions] + [money(kept.cents)]
    colors = [BASE] + [MINUS] * len(deductions) + [ACCENT]
    return {
        "grid": {**GRID_BOX, "top": 42},
        "tooltip": {"trigger": "item", **TOOLTIP,
                    ":formatter": "p => p.seriesName === 'base' ? '' : p.name + '　' + p.data.text"},
        "xAxis": {"type": "category", "data": names, **AXIS, "axisLabel": {**AXIS_LABEL, "fontSize": 13, "interval": 0}},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": GRID}}, **AXIS,
                  "axisLabel": {**AXIS_LABEL, ":formatter": "v => '¥' + v"}},
        "series": [
            {"name": "base", "type": "bar", "stack": "s", "data": bases, "itemStyle": {"color": "transparent"},
             "emphasis": {"disabled": True}, "tooltip": {"show": False}},
            {"name": "value", "type": "bar", "stack": "s", "barWidth": "34%",
             "data": [{"value": v / 100, "text": t, "itemStyle": {"color": c, "borderRadius": [4, 4, 0, 0]}}
                      for v, t, c in zip(values, texts, colors)],
             "label": {"show": True, "position": "top", "color": TEXT, "fontWeight": 600, "fontSize": 13,
                       ":formatter": "p => p.data.text"},
             ":animationDelay": "i => i * 380", "animationDuration": 900, "animationEasing": "cubicOut"},
        ],
    }


COUNT_UP_JS = """
<script>
window.countUp = function (id, target) {
  var tries = 0;
  var fmt = function (v) { return v.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2}); };
  (function start() {
    var el = document.getElementById(id);
    if (!el) { if (tries++ < 20) requestAnimationFrame(start); return; }
    var t0 = performance.now();
    (function step(now) {
      var k = Math.min(1, (now - t0) / 1200), e = 1 - Math.pow(1 - k, 3);
      el.textContent = (target < 0 ? '−¥' : '¥') + fmt(Math.abs(target) * e);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  })();
};
</script>
"""

CSS = """
body { background: #e9edf2; color: #111827;
  font-family: "Inter", "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; }
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.shell { display: flex; width: 100%; min-height: 100vh; }
.rail { width: 84px; flex-shrink: 0; background: #f3f5f8; display: flex; flex-direction: column; align-items: center;
  padding: 20px 0; gap: 4px; }
.logo { width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; font-weight: 800;
  margin-bottom: 18px; background: #1baf7a; color: #fff; }
.nav { width: 64px; padding: 9px 0 7px; border-radius: 14px; display: flex; flex-direction: column; align-items: center;
  gap: 4px; font-size: 11px; color: #6b7584; cursor: pointer; transition: background .25s, color .25s; user-select: none; }
.nav:hover { color: #111827; }
.nav.on { background: #e4f6ee; color: #0f8a5f; }
.main { flex: 1; min-width: 0; background: #fff; display: flex; flex-direction: column; }
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 22px 34px 0; }
.eyebrow { font-size: 13px; color: #6b7584; }
.month-select { min-width: 150px; }
.panels { flex: 1; background: transparent !important; }
.panels .q-tab-panel { padding: 6px 34px 28px; }
.title { font-size: 22px; font-weight: 700; letter-spacing: -.01em; }
.hero-label { font-size: 13px; color: #6b7584; margin-top: 6px; }
.hero-row { display: flex; align-items: center; gap: 12px; }
.hero-num { font-size: 54px; font-weight: 700; letter-spacing: -.025em; line-height: 1.12; }
.pill { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 3px 10px; }
.pill.down { background: #e3f5e9; color: #0a7a0a; }
.pill.up { background: #fbe9e9; color: #b42318; }
.sub { font-size: 13px; color: #6b7584; }
.sub b { color: #111827; font-weight: 600; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; width: 100%; margin-top: 12px; }
.chart { width: 100%; height: 340px; }
.legend { display: flex; flex-direction: column; justify-content: center; gap: 10px; }
.legend-row { display: grid; grid-template-columns: 12px 1fr auto 44px; align-items: center; gap: 10px; font-size: 14px;
  padding: 6px 8px; border-radius: 10px; cursor: pointer; animation: rise .45s ease both; }
.legend-row:hover { background: #f3f5f8; }
.legend-row:nth-child(2) { animation-delay: .07s } .legend-row:nth-child(3) { animation-delay: .14s }
.legend-row:nth-child(4) { animation-delay: .21s } .legend-row:nth-child(5) { animation-delay: .28s }
.legend-row:nth-child(6) { animation-delay: .35s } .legend-row:nth-child(7) { animation-delay: .42s }
.dot { width: 10px; height: 10px; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(17,24,39,.12); }
.amt { font-variant-numeric: tabular-nums; font-weight: 600; }
.pct { color: #6b7584; text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; }
.empty { color: #6b7584; font-size: 15px; padding: 60px 0 10px; }
.note { font-size: 13px; color: #6b7584; }
.table { width: 100%; max-width: 560px; border: 1px solid #e6eaf0; border-radius: 14px; overflow: hidden; font-size: 14px; }
.tr { display: grid; grid-template-columns: 1fr 1fr 1fr; padding: 10px 18px; border-top: 1px solid #e6eaf0;
  font-variant-numeric: tabular-nums; }
.tr:first-child { border-top: 0; background: #f7f9fb; color: #6b7584; font-size: 12px; }
.tr > div:not(:first-child) { text-align: right; }
.drop.q-uploader { width: 100%; max-width: none; border: 2px dashed #cfd6e0; border-radius: 18px; box-shadow: none;
  background: #f7f9fb; }
.drop .q-uploader__header { background: transparent !important; color: #0f8a5f !important; padding: 22px 18px; }
.drop .q-uploader__title { font-size: 15px; font-weight: 600; }
.drop .q-uploader__subtitle { display: none; }
.drop .q-uploader__list { display: none; }
.result { width: 100%; background: #f7f9fb; border: 1px solid #e6eaf0; border-radius: 16px; padding: 16px 20px;
  animation: rise .4s ease both; }
.result.bad { background: #fdf1f0; border-color: #f4c7c3; color: #b42318; }
.result-head { display: flex; justify-content: space-between; width: 100%; font-size: 14px; }
.bar { width: 100%; height: 6px; border-radius: 6px; background: #e6eaf0; overflow: hidden; margin: 10px 0 6px; }
.bar > div { height: 100%; background: #1baf7a; border-radius: 6px; animation: fill 1.4s cubic-bezier(.2,.8,.2,1) both; }
.check { display: flex; align-items: center; gap: 10px; font-size: 14px; padding: 4px 0; animation: rise .4s ease both; }
.checks > .check:nth-child(1) { animation-delay: .5s } .checks > .check:nth-child(2) { animation-delay: .9s }
.checks > .check:nth-child(3) { animation-delay: 1.3s }
.tick { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-size: 11px;
  background: #e3f5e9; color: #0a7a0a; font-weight: 700; }
.history { font-size: 13px; color: #6b7584; }
.cardzone { width: 100%; display: flex; flex-direction: column; align-items: center; padding-top: 18px; }
.who { width: min(460px, 100%); background: #f7f9fb; border: 1px solid #e6eaf0; border-radius: 22px;
  padding: 26px 26px 22px; box-shadow: 0 14px 34px rgba(0,0,0,.08); animation: slide-in .35s ease both; }
.who-name { font-size: 26px; font-weight: 700; }
.who-meta { font-size: 13px; color: #6b7584; margin-top: 4px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.chip { padding: 8px 16px; border-radius: 999px; border: 1px solid #cfd6e0; font-size: 14px; cursor: pointer;
  transition: background .2s, color .2s, border-color .2s, transform .15s; user-select: none; }
.chip.suggested { border-color: #1baf7a; box-shadow: inset 0 0 0 1px #1baf7a; color: #0f8a5f; font-weight: 600; }
.chip:hover { background: #1baf7a; border-color: #1baf7a; color: #fff; transform: translateY(-1px); }
.chip.add { border-style: dashed; color: #0f8a5f; }
.chip.add:hover { color: #fff; }
.ai-line { display: flex; align-items: center; gap: 10px; min-height: 32px; margin-top: 14px;
  font-size: 13px; color: #6b7584; }
.ai-pick { font-size: 14px; font-weight: 600; color: #0f8a5f; }
.skip { font-size: 13px; color: #6b7584; cursor: pointer; margin-top: 12px; }
.ask-row { display: flex; gap: 10px; align-items: center; width: 100%; max-width: 640px; margin-top: 16px; }
.answer { max-width: 640px; margin-top: 18px; padding: 18px 20px; background: #f7f9fb; border: 1px solid #e6eaf0;
  border-radius: 18px; animation: rise .4s ease both; }
.answer-text { font-size: 15px; line-height: 1.7; margin-top: 6px; }
.steps { margin-top: 8px; font-size: 13px; color: #6b7584; }
.recat { width: 100%; max-width: 560px; margin-top: 22px; }
.recat-row { display: grid; grid-template-columns: 1fr auto 130px; gap: 12px; align-items: center; width: 100%;
  font-size: 14px; padding: 4px 0; }
.explain { font-size: 14px; color: #6b7584; line-height: 1.7; max-width: 640px; }
.badges { display: flex; gap: 10px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 6px 12px; border-radius: 999px; background: #e3f5e9; color: #0a7a0a; font-weight: 600; }
.mini-table { max-width: 520px; }
.mini-table .tr { grid-template-columns: 2fr 1fr 1fr; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes slide-in { from { opacity: 0; transform: translateX(46px); } to { opacity: 1; transform: none; } }
@keyframes fill { from { width: 0; } to { width: 100%; } }
@media (max-width: 760px) { .split { grid-template-columns: 1fr; } .hero-num { font-size: 40px; }
  .rail { width: 64px; } .nav { width: 52px; } .panels .q-tab-panel, .topbar { padding-left: 18px; padding-right: 18px; } }
"""

# 研究室样式仅作用于问答页，不覆盖其他面板。
CSS += """
.ask-room { width: 100%; max-width: 1320px; margin: 12px auto; color: #203c32; }
.ask-kicker { color: #158465; font-size: 11px; letter-spacing: .16em; font-weight: 650; }
.ask-title { font-size: 25px; font-weight: 650; letter-spacing: -.04em; }
.ask-workspace { display: grid; grid-template-columns: minmax(0, 7fr) minmax(240px, 3fr); gap: 42px; margin-top: 32px; }
.ask-main { min-width: 0; width: 100%; gap: 16px; }
.ask-welcome { white-space: pre-line; font-size: clamp(26px, 3vw, 42px); font-weight: 650; line-height: 1.4; letter-spacing: -.05em; margin-top: 25px; }
.ask-intro { font-size: 14px; line-height: 1.9; color: #728179; margin-bottom: 15px; }
.ask-example { width: 100%; color: #46735f; border: 1px solid #e4ece5; border-radius: 12px; background: #f7faf6; padding: 11px 14px; font-size: 13px; text-align: left; }
.ask-question { font-size: 20px; font-weight: 600; line-height: 1.7; overflow-wrap: anywhere; }
.ask-progress { padding: 11px 0; color: #158465; font-size: 12px; border-bottom: 1px solid #e2eae2; width: 100%; }
.ask-answer { width: 100%; line-height: 1.9; overflow-wrap: anywhere; }
.ask-answer h1, .ask-answer h2, .ask-answer h3 { color: #203c32; line-height: 1.55; }
.ask-answer table { display: block; overflow-x: auto; max-width: 100%; }
.ask-composer { width: 100%; padding: 12px 18px; border: 1px solid #cfddd3; border-radius: 16px; background: #fff; box-shadow: 0 8px 30px #173c2e08; margin-top: 10px; gap: 6px; }
.ask-composer .q-field__native { font-size: 14px; }
.ask-composer .q-btn { border-radius: 9px; }
.ask-mode { width: 140px; font-size: 12px; }
.ask-evidence { width: 100%; min-width: 0; border-left: 1px solid #e4ebe4; padding-left: 26px; gap: 12px; }
.ask-evidence-title { font-size: 13px; font-weight: 650; }
.ask-evidence-card { width: 100%; border-bottom: 1px solid #e4ebe4; font-size: 12px; overflow-wrap: anywhere; }
.ask-evidence-card .q-item { padding-left: 0; padding-right: 0; }
.ask-evidence-card .q-item__label { overflow-wrap: anywhere; }
.ask-evidence-card .q-expansion-item__content { padding-bottom: 12px; }
.ask-evidence-card .q-table__container { max-width: 100%; overflow-x: auto; }
.ask-footnote { color: #75857c; font-size: 11px; line-height: 1.9; overflow-wrap: anywhere; }
.ask-history { flex-wrap: nowrap; width: 100%; overflow-x: auto; gap: 4px; padding-bottom: 5px; }
.ask-history-item { flex-shrink: 0; max-width: 220px; font-size: 11px; border-radius: 7px; background: #f0f5ef; }
.ask-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; width: 100%; }
.ask-metric { padding: 16px 14px; border: 1px solid #e3ebe3; border-radius: 12px; background: #fafcf9; }
.ask-money { font-variant-numeric: tabular-nums; font-size: clamp(18px, 2.1vw, 27px); font-weight: 600; margin-top: 8px; letter-spacing: -.03em; overflow-wrap: anywhere; }
@media (max-width: 900px) {
  .ask-workspace { grid-template-columns: minmax(0, 1fr); gap: 28px; }
  .ask-evidence { border-left: 0; border-top: 1px solid #e4ebe4; padding: 20px 0 0; }
}
@media (max-width: 520px) {
  .ask-room { margin-top: 6px; }
  .ask-title { font-size: 22px; }
  .ask-metrics { grid-template-columns: minmax(0, 1fr); }
  .ask-workspace { margin-top: 20px; }
  .ask-question { font-size: 18px; }
  .ask-composer { padding: 10px 12px; }
}
"""
