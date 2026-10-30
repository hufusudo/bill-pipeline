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
SPLIT_LINE = {"lineStyle": {"color": GRID, "type": "dashed"}}
TOOLTIP = {"backgroundColor": "rgba(255,255,255,.94)", "borderColor": GRID, "textStyle": {"color": TEXT, "fontSize": 13},
           "extraCssText": "border-radius:14px;padding:10px 14px;box-shadow:0 18px 40px -16px rgba(15,23,42,.3);backdrop-filter:blur(12px);"}
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
            "emphasis": {"scale": True, "scaleSize": 8, "itemStyle": {"shadowBlur": 22, "shadowColor": "rgba(15,23,42,.18)"}},
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
        "yAxis": {"type": "value", "splitLine": SPLIT_LINE, **AXIS,
                  "axisLabel": {**AXIS_LABEL, ":formatter": "v => '¥' + v"}},
        "series": [{
            "name": "当天消费", "type": "line", "smooth": 0.3, "showSymbol": False, "symbol": "circle", "symbolSize": 8,
            "data": [cents / 100 for _, cents in days],
            "lineStyle": {"width": 2.5, "color": ACCENT, "shadowColor": "rgba(27,175,122,.35)", "shadowBlur": 12, "shadowOffsetY": 5},
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
        "yAxis": {"type": "value", "splitLine": SPLIT_LINE, **AXIS,
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
        "yAxis": {"type": "value", "splitLine": SPLIT_LINE, **AXIS,
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
  var text = function (v) { return (target < 0 ? '−¥' : '¥') + fmt(Math.abs(v)); };
  (function start() {
    var el = document.getElementById(id);
    if (!el) { if (tries++ < 20) requestAnimationFrame(start); return; }
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { el.textContent = text(target); return; }
    var t0 = performance.now();
    (function step(now) {
      var k = Math.min(1, (now - t0) / 1200), e = 1 - Math.pow(1 - k, 3);
      el.textContent = text(target * e);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  })();
};
// 鼠标经过的卡片：把光标位置写进 CSS 变量，光斑由 CSS 画
document.addEventListener('pointermove', function (e) {
  var card = e.target.closest && e.target.closest('.hero, .chart, .legend, .who');
  if (!card) return;
  var r = card.getBoundingClientRect();
  card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
  card.style.setProperty('--my', (e.clientY - r.top) + 'px');
});
</script>
"""

CSS = """
:root {
  --accent: #1baf7a;
  --accent-ink: #0f8a5f;
  --accent-soft: #e8f8f1;
  --muted: #6b7584;
  --line: rgba(15, 23, 42, .08);
  --card-shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 16px 36px -24px rgba(15, 23, 42, .28);
  --ease: cubic-bezier(.2, .8, .2, 1);
  --spring: cubic-bezier(.34, 1.56, .64, 1);
  --font-sans: "Source Han Sans CN", "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --font-serif: "Source Han Serif CN", "Noto Serif CJK SC", "Songti SC", STSong, Georgia, serif;
}
/* 背景两层：底下是缓慢漂移的彩色光晕，上面是静态颗粒；都不接收鼠标 */
body { margin: 0; min-height: 100vh; background: #eef3f1; color: #111827; font-family: var(--font-sans); }
body::before, body::after { content: ""; position: fixed; inset: 0; pointer-events: none; }
body::before { z-index: -2; inset: -25%; animation: drift 30s ease-in-out infinite alternate;
  background: radial-gradient(40% 40% at 18% 22%, rgba(27, 175, 122, .24), transparent 70%),
    radial-gradient(38% 38% at 84% 14%, rgba(64, 141, 255, .16), transparent 70%),
    radial-gradient(44% 44% at 72% 92%, rgba(140, 110, 255, .12), transparent 70%); }
body::after { z-index: -1; opacity: .5; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .09 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"); }
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.shell { display: flex; gap: 12px; width: 100%; min-height: 100vh; box-sizing: border-box; padding: 12px; }
/* 导航是悬浮的玻璃层，内容区才是实的纸面 */
.rail { position: sticky; top: 12px; align-self: flex-start; height: calc(100vh - 24px); width: 84px; flex-shrink: 0; box-sizing: border-box;
  display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 18px 0; border-radius: 26px;
  background: rgba(255, 255, 255, .56); backdrop-filter: blur(22px) saturate(170%); border: 1px solid rgba(255, 255, 255, .8);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .9), 0 24px 50px -30px rgba(15, 23, 42, .35); }
.logo { width: 40px; height: 40px; border-radius: 14px; display: grid; place-items: center; margin-bottom: 18px;
  font-family: var(--font-serif); font-size: 19px; font-weight: 600; color: #fff; background: linear-gradient(145deg, #2fd08f, #0f8a5f);
  animation: breathe 5s ease-in-out infinite; }
.nav { position: relative; width: 66px; padding: 9px 0 7px; border-radius: 16px; display: flex; flex-direction: column; align-items: center;
  gap: 4px; font-size: 11px; color: var(--muted); cursor: pointer; user-select: none;
  transition: background-color .3s var(--ease), color .3s var(--ease), box-shadow .3s var(--ease), transform .4s var(--spring); }
.nav .q-icon { transition: transform .45s var(--spring), color .3s var(--ease); }
.nav:hover { color: #111827; background: rgba(255, 255, 255, .6); }
.nav:hover .q-icon { transform: translateY(-2px) scale(1.08); }
.nav:active { transform: scale(.92); }
.nav.on { color: var(--accent-ink); background: #fff; box-shadow: 0 10px 22px -12px rgba(15, 23, 42, .35), inset 0 0 0 1px rgba(27, 175, 122, .2); }
.nav.on .q-icon { color: var(--accent); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; border-radius: 28px;
  background: rgba(255, 255, 255, .94); border: 1px solid rgba(255, 255, 255, .9);
  box-shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 40px 80px -48px rgba(15, 61, 48, .4); }
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 26px 40px 0; }
.eyebrow { padding: 6px 12px; border-radius: 999px; background: #f1f5f3; color: var(--accent-ink); font-size: 12px; font-weight: 600; letter-spacing: .04em; }
.month-select { min-width: 160px; }
.panels { flex: 1; background: transparent !important; }
.panels .q-tab-panel { padding: 8px 40px 44px; }
/* 每个面板切换时，内容按顺序浮现 */
.panels .q-tab-panel > * { animation: rise .5s var(--ease) both; }
.panels .q-tab-panel > :nth-child(2) { animation-delay: .05s; }
.panels .q-tab-panel > :nth-child(3) { animation-delay: .1s; }
.panels .q-tab-panel > :nth-child(4) { animation-delay: .15s; }
.panels .q-tab-panel > :nth-child(n+5) { animation-delay: .2s; }
.title { font-family: var(--font-serif); font-size: 32px; font-weight: 600; letter-spacing: -.02em; line-height: 1.25; }
.empty { color: var(--muted); font-size: 15px; padding: 60px 0 10px; }
.note { font-size: 13px; color: var(--muted); }
/* 总览的英雄卡：深翠绿渐变 + 缓慢漂动的光；数字用等宽数字，计数时不左右跳 */
.hero { position: relative; isolation: isolate; overflow: hidden; width: 100%; box-sizing: border-box; margin-top: 18px; padding: 30px 34px 28px; border-radius: 30px; color: #ecfff6;
  background: radial-gradient(120% 130% at 0% 0%, #25ab7b 0%, #0f6b4e 44%, #0a3b2c 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .22), 0 36px 60px -36px rgba(10, 59, 44, .8); }
.hero::before { content: ""; position: absolute; z-index: -1; width: 64%; aspect-ratio: 1; right: -14%; top: -42%; border-radius: 50%;
  background: radial-gradient(closest-side, rgba(170, 255, 220, .42), transparent); animation: bloom 14s ease-in-out infinite; }
.hero::after { content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none; opacity: 0; transition: opacity .5s var(--ease);
  background: radial-gradient(360px circle at var(--mx, 85%) var(--my, 0%), rgba(255, 255, 255, .18), transparent 70%); }
.hero:hover::after { opacity: 1; }
.hero-label { font-size: 13px; letter-spacing: .02em; color: rgba(236, 255, 246, .8); }
.hero-row { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin-top: 8px; }
.hero-num { font-size: clamp(46px, 5.6vw, 68px); font-weight: 650; line-height: 1.1; letter-spacing: -.035em; color: #fff;
  font-variant-numeric: tabular-nums; text-shadow: 0 6px 24px rgba(0, 0, 0, .12); }
.hero .sub { margin-top: 14px; color: rgba(236, 255, 246, .78); }
.hero .sub b { color: #fff; }
.pill { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 4px 11px; }
.pill.down { background: #e3f5e9; color: #0a7a0a; }
.pill.up { background: #fbe9e9; color: #b42318; }
.hero .pill.down { background: rgba(255, 255, 255, .16); color: #e6fff2; box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .22); }
.hero .pill.up { background: rgba(255, 110, 110, .2); color: #ffe0e0; box-shadow: inset 0 0 0 1px rgba(255, 160, 160, .3); }
.sub { font-size: 13px; color: var(--muted); }
.sub b { color: #111827; font-weight: 600; }
.split { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr); gap: 20px; width: 100%; margin-top: 20px; }
/* 图表、图例、分类卡共用一套纸面质感；鼠标经过时有一束跟随光标的光 */
.chart, .legend, .who { position: relative; isolation: isolate; background: #fff; border: 1px solid var(--line); border-radius: 26px;
  box-shadow: var(--card-shadow); transition: box-shadow .5s var(--ease); }
.chart::after, .legend::after, .who::after { content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none; border-radius: inherit;
  opacity: 0; transition: opacity .5s var(--ease);
  background: radial-gradient(320px circle at var(--mx, 50%) var(--my, 0%), rgba(27, 175, 122, .11), transparent 70%); }
.chart:hover::after, .legend:hover::after, .who:hover::after { opacity: 1; }
.chart { width: 100%; height: 340px; }
.legend { display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 16px 12px; box-sizing: border-box; }
.legend-row { position: relative; isolation: isolate; display: grid; grid-template-columns: 12px 1fr auto 46px; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 14px; font-size: 14px; cursor: pointer;
  animation: rise .45s var(--ease) var(--d, 0s) both; transition: transform .4s var(--spring); }
/* 每一类的占比条：宽度就是占比，颜色取分类色 */
.legend-row::before { content: ""; position: absolute; z-index: -1; inset: 0 auto 0 0; width: var(--p, 0%); border-radius: 14px;
  background: color-mix(in srgb, var(--c, #c3c9d3) 12%, transparent); transform-origin: left center;
  animation: grow .8s var(--ease) calc(var(--d, 0s) + .1s) both; transition: background-color .3s var(--ease); }
.legend-row:hover { transform: translateX(4px); }
.legend-row:hover::before { background: color-mix(in srgb, var(--c, #c3c9d3) 22%, transparent); }
.legend-row:nth-child(2) { --d: .05s; } .legend-row:nth-child(3) { --d: .1s; }
.legend-row:nth-child(4) { --d: .15s; } .legend-row:nth-child(5) { --d: .2s; }
.legend-row:nth-child(6) { --d: .25s; } .legend-row:nth-child(7) { --d: .3s; }
.dot { width: 10px; height: 10px; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(17, 24, 39, .12); }
.amt { font-variant-numeric: tabular-nums; font-weight: 600; }
.pct { color: var(--muted); text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; }
.table { width: 100%; max-width: 560px; overflow: hidden; border: 1px solid var(--line); border-radius: 20px; background: #fff;
  box-shadow: var(--card-shadow); font-size: 14px; }
.tr { display: grid; grid-template-columns: 1fr 1fr 1fr; padding: 11px 18px; border-top: 1px solid #eef1f5;
  font-variant-numeric: tabular-nums; transition: background-color .3s var(--ease); }
.tr:not(:first-child):hover { background: #f7fbf9; }
.tr:first-child { border-top: 0; background: #f7f9fb; color: var(--muted); font-size: 12px; }
.tr > div:not(:first-child) { text-align: right; }
.drop.q-uploader { width: 100%; max-width: none; border: 1.5px dashed #cdd6e0; border-radius: 24px; box-shadow: none; background: rgba(247, 249, 251, .85);
  transition: border-color .35s var(--ease), background-color .35s var(--ease), box-shadow .35s var(--ease); }
.drop.q-uploader:hover { border-color: var(--accent); background: var(--accent-soft); box-shadow: 0 0 0 6px rgba(27, 175, 122, .08); }
.drop .q-uploader__header { background: transparent !important; color: var(--accent-ink) !important; padding: 26px 18px; }
.drop .q-uploader__title { font-size: 15px; font-weight: 600; }
.drop .q-uploader__subtitle { display: none; }
.drop .q-uploader__list { display: none; }
.result { width: 100%; padding: 18px 22px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 22px;
  background: rgba(255, 255, 255, .92); box-shadow: var(--card-shadow); animation: rise .5s var(--ease) both; }
.result.bad { background: #fdf1f0; border-color: #f4c7c3; color: #b42318; }
.result-head { display: flex; justify-content: space-between; width: 100%; font-size: 14px; }
.bar { width: 100%; height: 6px; border-radius: 6px; background: #e6eaf0; overflow: hidden; margin: 12px 0 8px; }
.bar > div { height: 100%; border-radius: 6px; background: linear-gradient(90deg, #2fd08f, var(--accent)); animation: fill 1.4s var(--ease) both; }
.check { display: flex; align-items: center; gap: 10px; font-size: 14px; padding: 4px 0; animation: rise .5s var(--ease) both; }
.checks > .check:nth-child(1) { animation-delay: .5s; } .checks > .check:nth-child(2) { animation-delay: .9s; }
.checks > .check:nth-child(3) { animation-delay: 1.3s; }
.tick { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700;
  background: #e3f5e9; color: #0a7a0a; animation: pop .6s var(--spring) both; }
.checks > .check:nth-child(1) .tick { animation-delay: .65s; } .checks > .check:nth-child(2) .tick { animation-delay: 1.05s; }
.checks > .check:nth-child(3) .tick { animation-delay: 1.45s; }
.history { font-size: 13px; color: var(--muted); }
.cardzone { width: 100%; display: flex; flex-direction: column; align-items: center; padding-top: 18px; }
.who { width: min(480px, 100%); padding: 28px 28px 24px; box-sizing: border-box; animation: slide-in .5s var(--ease) both; }
.who-name { font-family: var(--font-serif); font-size: 28px; font-weight: 600; letter-spacing: -.01em; }
.who-meta { font-size: 13px; color: var(--muted); margin-top: 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
.chip { padding: 9px 16px; border-radius: 999px; border: 1px solid rgba(15, 23, 42, .12); background: #fff; font-size: 14px; cursor: pointer; user-select: none;
  transition: background-color .25s var(--ease), color .25s var(--ease), border-color .25s var(--ease), transform .4s var(--spring), box-shadow .3s var(--ease); }
.chip:hover { background: var(--accent); border-color: var(--accent); color: #fff; transform: translateY(-2px); box-shadow: 0 10px 20px -12px rgba(27, 175, 122, .9); }
.chip:active { transform: scale(.92); transition-duration: .12s; }
.chip.suggested { border-color: var(--accent); color: var(--accent-ink); font-weight: 600; box-shadow: inset 0 0 0 1px var(--accent); animation: ring 1.8s var(--ease) 2; }
.chip.add { border-style: dashed; color: var(--accent-ink); }
.chip.add:hover { color: #fff; }
.ai-line { display: flex; align-items: center; gap: 10px; min-height: 32px; margin-top: 14px; font-size: 13px; color: var(--muted); }
.ai-pick { font-size: 14px; font-weight: 600; color: var(--accent-ink); }
.skip { font-size: 13px; color: var(--muted); cursor: pointer; margin-top: 12px; transition: color .2s var(--ease); }
.skip:hover { color: var(--accent-ink); }
.recat { width: 100%; max-width: 560px; margin-top: 22px; }
.recat-row { display: grid; grid-template-columns: 1fr auto 130px; gap: 12px; align-items: center; width: 100%; font-size: 14px; padding: 4px 0; }
.explain { font-size: 14px; color: var(--muted); line-height: 1.75; max-width: 640px; }
.badges { display: flex; gap: 10px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 6px 12px; border-radius: 999px; background: var(--accent-soft); color: #0a7a0a; font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(27, 175, 122, .16); }
.mini-table { max-width: 520px; }
.mini-table .tr { grid-template-columns: 2fr 1fr 1fr; }
.trust-banner { width: 100%; margin: 14px 0 0; padding: 4px 12px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 16px;
  background: rgba(255, 255, 255, .72); backdrop-filter: blur(10px); color: #547565; font-size: 12px; }
.review-summary { width: 100%; padding: 15px; border-radius: 16px; background: var(--accent-soft); color: #285846; }
.review-dialog { width: min(540px, 92vw); overflow-wrap: anywhere; }
.answer-text { font-size: 15px; line-height: 1.7; margin-top: 6px; }
.steps { margin-top: 8px; font-size: 13px; color: var(--muted); }
/* 研究室：问答页自己的版式，颜色和卡片与其他页统一 */
.ask-room { width: 100%; max-width: 1320px; margin: 12px auto; color: #203c32; }
.ask-kicker { display: flex; align-items: center; gap: 8px; color: var(--accent-ink); font-size: 12px; letter-spacing: .16em; font-weight: 650; }
.ask-kicker::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: ping 2.4s var(--ease) infinite; }
.ask-title { font-family: var(--font-serif); font-size: 28px; font-weight: 600; letter-spacing: -.02em; }
.ask-workspace { display: grid; grid-template-columns: minmax(0, 7fr) minmax(240px, 3fr); gap: 42px; margin-top: 32px; }
.ask-main { min-width: 0; width: 100%; gap: 16px; }
.ask-welcome { white-space: pre-line; margin-top: 24px; font-family: var(--font-serif); font-size: clamp(30px, 3.4vw, 46px); font-weight: 600;
  line-height: 1.32; letter-spacing: -.035em; animation: rise .7s var(--ease) .1s both; }
.ask-intro { margin-bottom: 15px; font-size: 14px; line-height: 1.9; color: var(--muted); animation: rise .7s var(--ease) .2s both; }
.ask-example { width: 100%; padding: 12px 16px; border: 1px solid #dfeae3; border-radius: 14px; background: #f7fbf8; color: var(--accent-ink);
  font-size: 13px; text-align: left; transition: background-color .3s var(--ease), border-color .3s var(--ease), transform .4s var(--spring), box-shadow .3s var(--ease); }
.ask-example:hover { transform: translateX(4px); background: #fff; border-color: var(--accent); box-shadow: 0 12px 24px -18px rgba(15, 138, 95, .7); }
.ask-question { font-size: 20px; font-weight: 600; line-height: 1.7; overflow-wrap: anywhere; }
.ask-progress { width: 100%; padding: 11px 0; border-bottom: 1px solid #e2eae2; color: var(--accent-ink); font-size: 12px; }
.ask-answer { width: 100%; line-height: 1.9; overflow-wrap: anywhere; animation: rise .6s var(--ease) both; }
.ask-answer h1, .ask-answer h2, .ask-answer h3 { color: #203c32; line-height: 1.55; font-family: var(--font-serif); }
.ask-answer h1, .ask-answer h2 { font-size: 27px; font-weight: 600; letter-spacing: -.02em; }
.ask-answer h3 { font-size: 20px; font-weight: 600; }
.ask-answer table { display: block; overflow-x: auto; max-width: 100%; }
.ask-composer { width: 100%; margin-top: 10px; padding: 14px 18px; gap: 6px; box-sizing: border-box; border: 1px solid rgba(203, 221, 211, .9); border-radius: 22px;
  background: rgba(255, 255, 255, .82); backdrop-filter: blur(16px) saturate(160%);
  box-shadow: 0 24px 48px -30px rgba(15, 61, 48, .35), inset 0 1px 0 rgba(255, 255, 255, .9); transition: border-color .4s var(--ease), box-shadow .4s var(--ease); }
.ask-composer:focus-within { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(27, 175, 122, .14), 0 24px 48px -30px rgba(15, 61, 48, .35); }
.ask-composer .q-field__native { font-size: 14px; }
.ask-composer .q-btn { border-radius: 12px; }
.ask-mode { width: 140px; font-size: 12px; }
.ask-evidence { width: 100%; min-width: 0; gap: 12px; padding-left: 26px; border-left: 1px solid #e4ebe4; }
.ask-evidence-title { font-size: 13px; font-weight: 650; }
.ask-evidence-card { width: 100%; font-size: 12px; overflow-wrap: anywhere; border-bottom: 1px solid #e4ebe4; }
.ask-evidence-card .q-item { padding-left: 0; padding-right: 0; }
.ask-evidence-card .q-item__label { overflow-wrap: anywhere; }
.ask-evidence-card .q-expansion-item__content { padding-bottom: 12px; }
.ask-evidence-card .q-table__container { max-width: 100%; overflow-x: auto; }
.ask-evidence-card td, .ask-evidence-card th { white-space: nowrap; }
.ask-footnote { font-size: 11px; line-height: 1.9; color: #75857c; overflow-wrap: anywhere; }
.ask-history { flex-wrap: nowrap; width: 100%; gap: 4px; padding-bottom: 5px; overflow-x: auto; }
.ask-history-item { flex-shrink: 0; max-width: 220px; font-size: 11px; border-radius: 8px; background: #f0f5ef; }
.ask-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; width: 100%; }
.ask-metric { padding: 18px 16px; border: 1px solid var(--line); border-radius: 18px; background: #fff; box-shadow: var(--card-shadow);
  transition: transform .45s var(--spring), box-shadow .4s var(--ease); }
.ask-metric:hover { transform: translateY(-3px); box-shadow: 0 22px 40px -24px rgba(15, 23, 42, .35); }
.ask-money { margin-top: 8px; font-size: clamp(18px, 2.1vw, 27px); font-weight: 600; letter-spacing: -.03em; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.ask-conversations { width: 100%; margin-top: 18px; padding: 3px 10px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 16px;
  background: rgba(255, 255, 255, .7); color: #456a56; }
.ask-conversations .q-btn { max-width: 100%; overflow-wrap: anywhere; }
.ask-stale { width: 100%; padding: 10px 14px; box-sizing: border-box; border-radius: 12px; background: #fff7e9; color: #946227; font-size: 12px; }
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
  .ask-answer h1, .ask-answer h2 { font-size: 22px; }
  .ask-composer { padding: 10px 12px; }
}
/* Quasar 组件的统一覆盖：品牌色、圆角、焦点光圈、按压反馈 */
.bg-teal { background: var(--accent) !important; }
.text-teal { color: var(--accent-ink) !important; }
.q-btn { transition: transform .35s var(--spring), box-shadow .3s var(--ease), background-color .3s var(--ease), color .3s var(--ease); }
.q-btn:not(.disabled):active { transform: scale(.96); }
.bg-teal:not(.disabled):hover { box-shadow: 0 12px 24px -14px rgba(27, 175, 122, .9); }
.q-btn--rounded { border-radius: 999px !important; }
.q-btn-group { padding: 3px; border-radius: 999px; background: rgba(15, 23, 42, .05); box-shadow: inset 0 1px 2px rgba(15, 23, 42, .06); }
.q-btn-group > .q-btn { border-radius: 999px !important; }
.q-field--outlined .q-field__control { border-radius: 14px; transition: box-shadow .35s var(--ease); }
.q-field--outlined.q-field--focused .q-field__control { box-shadow: 0 0 0 4px rgba(27, 175, 122, .14); }
.q-expansion-item { border-radius: 16px; overflow: hidden; }
.q-expansion-item:not(.trust-banner):not(.ask-conversations):not(.ask-evidence-card) {
  background: rgba(255, 255, 255, .8); border: 1px solid var(--line); box-shadow: var(--card-shadow); }
.q-expansion-item + .q-expansion-item { margin-top: 10px; }
.q-card { border-radius: 22px; }
.q-linear-progress { border-radius: 99px; }
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes slide-in { from { opacity: 0; transform: translateX(46px); } to { opacity: 1; transform: none; } }
@keyframes fill { from { width: 0; } to { width: 100%; } }
@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes pop { from { opacity: 0; transform: scale(.4); } to { opacity: 1; transform: none; } }
@keyframes ring { from { box-shadow: inset 0 0 0 1px var(--accent), 0 0 0 0 rgba(27, 175, 122, .45); }
  to { box-shadow: inset 0 0 0 1px var(--accent), 0 0 0 12px rgba(27, 175, 122, 0); } }
@keyframes ping { 0% { box-shadow: 0 0 0 0 rgba(27, 175, 122, .5); } 70%, 100% { box-shadow: 0 0 0 9px rgba(27, 175, 122, 0); } }
@keyframes drift { from { transform: translate3d(-3%, -2%, 0) scale(1); } to { transform: translate3d(3%, 2%, 0) scale(1.06); } }
@keyframes bloom { 0%, 100% { transform: translate3d(0, 0, 0) scale(1); } 50% { transform: translate3d(-16%, 12%, 0) scale(1.12); } }
@keyframes breathe { 0%, 100% { box-shadow: inset 0 1px 0 rgba(255, 255, 255, .35), 0 10px 22px -10px rgba(15, 138, 95, .8); }
  50% { box-shadow: inset 0 1px 0 rgba(255, 255, 255, .35), 0 14px 30px -8px rgba(27, 175, 122, .9); } }
@media (max-width: 760px) {
  .split { grid-template-columns: minmax(0, 1fr); }
  .hero { padding: 24px 22px; }
  .hero-num { font-size: 44px; }
  .shell { padding: 8px; gap: 8px; }
  .rail { width: 64px; }
  .nav { width: 52px; }
  .main { border-radius: 22px; }
  .panels .q-tab-panel, .topbar { padding-left: 18px; padding-right: 18px; }
}
/* 减少动态效果：去掉装饰性动画；加载转圈、进度条保留，它们传达的是“还在工作” */
@media (prefers-reduced-motion: reduce) {
  body::before, .hero::before, .logo, .ask-kicker::before, .ask-welcome, .ask-intro, .ask-answer,
  .panels .q-tab-panel > *, .legend-row, .legend-row::before, .result, .check, .tick, .bar > div, .who, .chip.suggested {
    animation: none !important;
  }
}
"""
