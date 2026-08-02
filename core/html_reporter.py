"""
Render indicator Excel data into a self-contained interactive HTML page.

Features:
  - ECharts line chart (CDN with multiple fallbacks)
  - Drag-to-select time range (dataZoom slider + mouse wheel / drag inside chart)
  - Linear trend lines recomputed over the currently visible range
  - Dynamic valuation zones (min~P25 / P25~P75 / P75~max) that follow the
    selected time range
  - Market-cap overlay curve (right axis, legend-toggle)
  - markPoints for annotated dates (bull peaks / bear bottoms)
  - Second page: analysis view with the SAME interactive chart + forecast
    (bull/bear ranges based on historical marks, extreme-value handling)
"""

import json
from pathlib import Path

import pandas as pd

from core.excel_writer import load_excel

_ECHARTS_CDN = """<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>window.echarts||document.write('<script src="https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js"><\\/script>');</script>
<script>window.echarts||document.write('<script src="https://unpkg.com/echarts@5.5.0/dist/echarts.min.js"><\\/script>');</script>"""

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="description" content="A股证券化率（巴菲特指标）交互式可视化 — 牛熊信号检测与预测" />
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230a0e13'/%3E%3Ccircle cx='16' cy='16' r='9' fill='none' stroke='%233d8bfd' stroke-width='3'/%3E%3C/svg%3E" />
<title>__TITLE__</title>
__ECHARTS__
<style>
  :root {
    --bg: #0a0e13;
    --surface: #10161d;
    --surface-2: #151d26;
    --border: rgba(148, 172, 200, 0.13);
    --border-strong: rgba(148, 172, 200, 0.26);
    --text: #e6ebf2;
    --text-2: #94a0af;
    --text-3: #5d6875;
    --accent: #3d8bfd;
    --green: #2fbf71;
    --red: #f0534c;
    --glow-a: rgba(61, 139, 253, 0.08);
    --glow-b: rgba(216, 166, 87, 0.05);
    --header-bg: linear-gradient(180deg, rgba(24, 32, 42, 0.92), rgba(13, 18, 25, 0.92));
    --tab-bg: rgba(10, 14, 19, 0.6);
    --input-bg: #0c1219;
    --dot-off: #232c38;
    --dot-hover: #2d3947;
    --hl: #5b9dff;
    --hlr: #ff6b5e;
    --hlg: #35d07a;
    --mono: "JetBrains Mono", ui-monospace, "SF Mono", Consolas, "Cascadia Mono", monospace;
  }
  * { box-sizing: border-box; }
  html { color-scheme: dark; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    background:
      radial-gradient(1100px 480px at 18% -8%, var(--glow-a), transparent 60%),
      radial-gradient(800px 400px at 88% -6%, var(--glow-b), transparent 55%),
      var(--bg);
    color: var(--text);
    min-height: 100dvh;
    -webkit-font-smoothing: antialiased;
  }
  body::before {
    content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.045'/%3E%3C/svg%3E");
  }
  .page-wrap { position: relative; z-index: 1; max-width: 1440px; margin: 0 auto; padding: 0 20px 36px; }

  /* ── Header ── */
  .header {
    background: var(--header-bg);
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    position: sticky; top: 0; z-index: 10;
  }
  .header-inner { max-width: 1440px; margin: 0 auto; padding: 14px 20px 12px; }
  .brand-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand-dot {
    width: 12px; height: 12px; border-radius: 4px;
    background: linear-gradient(135deg, #57a1ff, #2c6fe0);
    box-shadow: 0 0 14px rgba(61, 139, 253, 0.55);
  }
  .header h1 { margin: 0; font-size: 19px; font-weight: 600; letter-spacing: -0.01em; }
  .tab-bar { display: flex; gap: 4px; padding: 3px; background: var(--tab-bg); border: 1px solid var(--border); border-radius: 10px; }
  .tab {
    padding: 5px 16px; border: none; background: transparent; border-radius: 7px;
    cursor: pointer; font-size: 13px; color: var(--text-2); transition: all 0.2s; font-family: inherit;
  }
  .tab:hover { color: var(--text); }
  .tab.active { background: var(--accent); color: #fff; box-shadow: 0 2px 10px rgba(61, 139, 253, 0.35); }
  .stats {
    display: flex; flex-wrap: wrap; align-items: flex-end; gap: 14px 40px;
    margin-top: 14px; padding-top: 12px; border-top: 1px dashed rgba(148, 172, 200, 0.12);
  }
  .stat .label { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3); }
  .stat .value {
    font-family: var(--mono); font-size: 25px; font-weight: 600; margin-top: 3px;
    font-variant-numeric: tabular-nums; letter-spacing: -0.02em; color: var(--text);
  }
  .stat .value small { font-size: 12px; font-weight: 400; color: var(--text-3); font-family: inherit; }
  .range-box { min-width: 360px; }
  .range-controls { display: flex; align-items: center; gap: 6px; font-weight: 400; margin-top: 6px; }
  .range-controls input[type="date"] {
    height: 30px; font-size: 12px; padding: 0 8px; border: 1px solid var(--border); border-radius: 7px;
    color: var(--text); background: var(--input-bg); outline: none; transition: border-color 0.2s;
  }
  .range-controls input[type="date"]:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(61, 139, 253, 0.15); }
  .range-controls .sep { color: var(--text-3); font-size: 13px; }
  .btn-apply {
    height: 30px; padding: 0 18px; font-size: 12px; font-weight: 500; font-family: inherit;
    background: linear-gradient(180deg, #4a93ff, #2c6fe0); color: #fff; border: none; border-radius: 7px;
    cursor: pointer; transition: all 0.2s;
  }
  .btn-apply:hover { filter: brightness(1.1); box-shadow: 0 3px 12px rgba(61, 139, 253, 0.35); }
  .btn-apply:active { transform: translateY(1px) scale(0.98); }
  .quick-btns { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
  .quick-btns .qbtn {
    padding: 3px 13px; font-size: 12px; border: 1px solid var(--border); border-radius: 999px;
    background: var(--input-bg); color: var(--text-2); cursor: pointer; transition: all 0.2s; font-family: inherit;
  }
  .quick-btns .qbtn:hover { border-color: var(--accent); color: var(--accent); }
  .quick-btns .qbtn.active { background: var(--accent); color: #fff; border-color: transparent; }

  /* ── 图表卡片 ── */
  .chart-wrap {
    margin: 16px 0; background: linear-gradient(180deg, var(--surface-2), var(--surface));
    border: 1px solid var(--border); border-radius: 14px; padding: 10px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 16px 40px -20px rgba(0, 0, 0, 0.6);
  }
  #chart { width: 100%; height: 72vh; min-height: 420px; }
  #chart-analysis { width: 100%; height: 62vh; min-height: 400px; }
  .legend { margin: 0 4px 16px; color: var(--text-3); font-size: 12.5px; line-height: 2; }
  .legend b { color: var(--text-2); font-weight: 600; }

  /* ── 分析页卡片 ── */
  .acards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 16px 0; }
  .acard {
    background: linear-gradient(180deg, var(--surface-2), var(--surface));
    border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    transition: border-color 0.2s;
  }
  .acard:hover { border-color: var(--border-strong); }
  .alabel { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3); }
  .aval {
    font-family: var(--mono); font-size: 26px; font-weight: 600; margin-top: 6px;
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }
  .asub { font-size: 12px; color: var(--text-3); margin-top: 5px; }
  .guide {
    margin: 16px 0; background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 18px 22px; line-height: 1.9; font-size: 13.5px;
  }
  .guide h3 { margin: 0 0 10px; font-size: 15px; font-weight: 600; }
  .guide p { margin: 6px 0; color: var(--text-2); }
  .guide .hl { color: var(--hl); font-weight: 600; }
  .guide .hlr { color: var(--hlr); font-weight: 600; }
  .guide .hlg { color: var(--hlg); font-weight: 600; }
  .guide ul { color: var(--text-2); }

  /* ── 牛熊信号 ── */
  .sig-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
  .sig-toolbar label { font-size: 13px; color: var(--text-2); }
  .sig-toolbar input[type="date"] {
    height: 30px; font-size: 12px; padding: 0 8px; border: 1px solid var(--border); border-radius: 7px;
    color: var(--text); background: var(--input-bg); outline: none;
  }
  .sig-toolbar input[type="date"]:focus { border-color: var(--accent); }
  .sig-banner { border-radius: 12px; padding: 13px 18px; font-size: 14px; margin: 6px 0 12px; line-height: 1.8; }
  .sig-banner small { color: var(--text-2); }
  .sig-banner.strong-bot { background: linear-gradient(135deg, rgba(47, 191, 113, 0.16), rgba(47, 191, 113, 0.03)); border: 1px solid rgba(47, 191, 113, 0.4); }
  .sig-banner.strong-top { background: linear-gradient(135deg, rgba(240, 83, 76, 0.16), rgba(240, 83, 76, 0.03)); border: 1px solid rgba(240, 83, 76, 0.4); }
  .sig-banner.mid-bot { background: linear-gradient(135deg, rgba(47, 191, 113, 0.10), rgba(47, 191, 113, 0.02)); border: 1px solid rgba(47, 191, 113, 0.28); }
  .sig-banner.mid-top { background: linear-gradient(135deg, rgba(240, 83, 76, 0.10), rgba(240, 83, 76, 0.02)); border: 1px solid rgba(240, 83, 76, 0.28); }
  .sig-banner.none { background: var(--surface); border: 1px solid var(--border); color: var(--text-2); }
  .sig-dots { display: inline-flex; gap: 5px; margin: 0 8px; vertical-align: middle; }
  .sig-dots span { width: 14px; height: 14px; border-radius: 50%; background: var(--dot-off); display: inline-block; }
  .sig-dots span.on { background: var(--accent); }
  .sig-dots span.on.bot { background: var(--green); }
  .sig-dots span.on.top { background: var(--red); }
  .sig-cards { display: flex; gap: 10px; margin: 10px 0 4px; flex-wrap: wrap; }
  .sig-card {
    flex: 1; min-width: 160px; background: var(--input-bg); border: 1px solid var(--border);
    border-radius: 11px; padding: 11px 13px; text-align: center; transition: all 0.2s;
  }
  .sig-card:hover { box-shadow: 0 6px 18px -8px rgba(0, 0, 0, 0.6); border-color: var(--border-strong); transform: translateY(-1px); }
  .sig-card .w-name { font-size: 12px; color: var(--text-3); }
  .sig-card .w-pos { font-size: 15px; font-weight: 700; margin: 5px 0 2px; font-variant-numeric: tabular-nums; }
  .sig-card .w-pos.bot { color: var(--green); }
  .sig-card .w-pos.top { color: var(--red); }
  .sig-card .w-pos.mid { color: var(--accent); }
  .sig-card .w-pct { font-size: 11px; color: var(--text-3); }
  .sig-card .w-trend { font-size: 12px; margin-top: 5px; color: var(--text-2); }
  .sig-note { color: var(--text-3); font-size: 12.5px; }
  .legend-bottom { margin-bottom: 24px; }

  /* ── 交互通用 ── */
  button:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  ::selection { background: rgba(61, 139, 253, 0.35); }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb { background: var(--dot-off); border-radius: 5px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--dot-hover); }
  ::-webkit-scrollbar-track { background: transparent; }

  /* ── 浅色主题 ── */
  body[data-theme="light"] {
    --bg: #f4f6fa;
    --surface: #ffffff;
    --surface-2: #f7f9fc;
    --border: rgba(23, 45, 80, 0.10);
    --border-strong: rgba(23, 45, 80, 0.20);
    --text: #1a2332;
    --text-2: #5a6b80;
    --text-3: #8a99ad;
    --accent: #2f6fe0;
    --green: #1f9d57;
    --red: #d9483f;
    --glow-a: rgba(47, 111, 224, 0.06);
    --glow-b: rgba(216, 166, 87, 0.08);
    --header-bg: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(247, 249, 252, 0.96));
    --tab-bg: rgba(23, 45, 80, 0.05);
    --input-bg: #ffffff;
    --dot-off: #dde4ee;
    --dot-hover: #c9d3e0;
    --hl: #2f6fe0;
    --hlr: #d9483f;
    --hlg: #1f9d57;
  }
  .theme-btn {
    width: 34px; height: 30px; border: 1px solid var(--border); border-radius: 8px;
    background: var(--input-bg); color: var(--text-2); font-size: 14px; cursor: pointer;
    transition: all 0.2s; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .theme-btn:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .theme-btn:active { transform: scale(0.96); }
</style>
</head>
<body>
<header class="header">
  <div class="header-inner">
    <div class="brand-row">
      <div class="brand"><span class="brand-dot"></span><h1>__TITLE__</h1></div>
      <div class="tab-bar">
        <button id="btn-chart" class="tab active">📈 图表</button>
        <button id="btn-analysis" class="tab">📊 分析</button>
      </div>
      <button id="btnTheme" class="theme-btn" title="切换深浅主题"></button>
    </div>
    <div class="stats">
    <div class="stat"><div class="label">最新值</div><div class="value" id="stLatest">--</div></div>
    <div class="stat range-box">
      <div class="label">可视范围（可直接选择）</div>
      <div class="range-controls">
        <input type="date" id="rangeFrom" />
        <span class="sep">~</span>
        <input type="date" id="rangeTo" />
        <button id="btnApplyRange" class="btn-apply">应用</button>
      </div>
      <div class="quick-btns">
        <button class="qbtn" data-years="1">近1年</button>
        <button class="qbtn" data-years="3">近3年</button>
        <button class="qbtn" data-years="5">近5年</button>
        <button class="qbtn" data-years="10">近10年</button>
        <button class="qbtn" data-all="1">全部</button>
      </div>
    </div>
    <div class="stat"><div class="label">范围内最高</div><div class="value" id="stMax">--</div></div>
    <div class="stat"><div class="label">范围内最低</div><div class="value" id="stMin">--</div></div>
    </div>
  </div>
</header>
<div class="page-wrap">

<!-- ============ 图表页 ============ -->
<div id="page-chart">
  <div class="chart-wrap"><div id="chart"></div></div>
  <div class="legend">
    <b>操作：</b>拖动底部滑块选择时间范围，或在顶部输入起止日期自定义范围；范围变化后趋势线（虚线）、统计与估值区域自动重算。
    <br><b>估值区域(随所选时间范围动态·对数正态±1σ)：</b><span id="zoneInfo">计算中...</span><br><b>牛熊信号区间：</b>点击图例「牛熊信号区间」显示/隐藏历史牛熊信号区段（绿=熊市底部信号区，红=牛市顶部信号区）
    <br><b>图例：</b><span style="color:#2f80ed">━</span> 证券化率　<span style="color:#f2994a">━</span> 总市值(万亿·右轴，点击图例叠加显示)　<span style="color:#eb5757">━</span> 证券化率趋势线　<span style="color:#9b59b6">━</span> 市值趋势线　<span style="color:#e74c3c">●</span> 牛市顶点　<span style="color:#27ae60">●</span> 熊市底部　<span style="color:#f39c12">◆</span> 预测转折点
  </div>
</div>

<!-- ============ 分析页 ============ -->
<div id="page-analysis" style="display:none">
  <div class="acards">
    <div class="acard"><div class="alabel">当前证券化率</div><div class="aval" id="an-cur">--</div><div class="asub" id="an-date">--</div></div>
    <div class="acard"><div class="alabel">历史分位</div><div class="aval" id="an-rank">--</div><div class="asub">低于历史上 X% 的时间</div></div>
    <div class="acard"><div class="alabel">🔺 常规顶部区</div><div class="aval" id="an-top">--</div><div class="asub" id="an-top-sub">历史牛市顶点分布（已剔除极端）</div></div>
    <div class="acard"><div class="alabel">🔻 常规底部区</div><div class="aval" id="an-bot">--</div><div class="asub" id="an-bot-sub">历史熊市底部分布（已剔除极端）</div></div>
  </div>

  <div class="chart-wrap"><div id="chart-analysis"></div></div>
  <div class="legend">
    <b>提示：</b>本图与图表页交互一致（滑块/顶部日期自定义范围选择）。预测区基于<b>全历史统计（固定不随范围变化）</b>：<span style="color:#e74c3c">┄</span>常规顶部区(91~108%)　<span style="color:#27ae60">┄</span>常规底部区(40~60%)　<span style="color:#e74c3c">┅</span>极端顶参考(2007年164%)，<span style="color:#f39c12">◆</span>预测转折点。缩放时Y轴跟随数据动态变化，但始终保留顶部区上沿与底部区下沿两条线可见。
  </div>

  <div class="guide">
    <h3>🔮 牛熊预测</h3>
    <p id="an-pred">计算中...</p>
  </div>

  <div class="guide legend-bottom">
    <h3>📖 图形解读</h3>
    <p><span class="hl">证券化率</span> = A股全市场总市值 ÷ GDP（巴菲特指标），衡量股票市场相对实体经济的估值水平。</p>
    <p><span class="hl">三个估值区域</span>（图表页背景色块）：对当前所选时间范围内的证券化率取对数（ln），按对数正态分布的均值±1个标准差划分——合理区(蓝)约覆盖中间68%的时间，其下为底部参考区(绿)、其上为顶部参考区(红)。采用对数变换是因为证券化率呈右偏厚尾分布（2007年164%等极端值会污染直接用均值±σ计算的边界），对数空间乘除对称，边界更稳健。区域随你选择的时间范围动态变化：看长期时反映大周期位置，看短期时反映近期相对位置。</p>
    <p><span class="hl">趋势线</span>（虚线）：当前可视范围内的线性回归线，红色=证券化率趋势、紫色=总市值趋势。向上表示处于上升通道，向下表示下降通道。</p>
    <p><span class="hl">牛熊标记</span>：红色圆点=历史牛市顶点（6124/5178/3731等），绿色圆点=历史熊市底部（1664/2635等）。曲线进入顶部区并出现红色标记，往往是泡沫期；曲线沉入底部区并出现绿色标记，往往是黄金坑。</p>
    <p><span class="hl">总市值曲线</span>（橙色，右轴）：点击图例叠加显示。短期与证券化率同步（GDP短期近似不变），长期可能背离（GDP增长导致），背离方向反映估值中枢的变化。</p>
  </div>

  <div class="guide legend-bottom">
    <h3>🔔 牛熊信号检测</h3>
    <div id="signalResult">检测中...</div>
    <p class="sig-note"><b>判定逻辑</b>：以基准日为准，往前分别取 <b>10年/5年/3年</b> 窗口，逐窗口检查——
      ① <b>估值位置</b>：当日证券化率是否处于底部区（绝对锚点&lt;62%，或62~75%且窗口内分位&lt;P30）或顶部区（绝对锚点&gt;90%，或82~90%且窗口内分位&gt;P70）；
      ② <b>短周期惯性</b>：3年窗口趋势斜率（底部信号要求下行、顶部信号要求上行）；
      ③ <b>中周期衰竭</b>：底部要求5年趋势走平（|斜率|&lt;0.2%/月）、顶部要求5年涨速低于3年（动能衰减）。
      5项条件满足越多信号越强。历史验证：2024-02-05（2635点底）触发5/5底部信号，2013-06-25（1849底）4/5，2015-06-12（5178顶）5/5，2021-02-18（3731顶）5/5；2016-01-27（熔断低点）与2024-10-08（924脉冲顶）均不触发（正确排除）。</p>
  </div>
</div>
</div><!-- /.page-wrap -->

<script>
const RAW = __DATA__;
const N = RAW.length;
const HAS_MCAP = N > 0 && RAW[0].mcap !== undefined;

// ---------- 通用工具 ----------
function valueOf(i) { return RAW[i].value; }

function pctOf(arr, p) {
  if (!arr.length) return 0;
  const s = arr.slice().sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * s.length))];
}

function allValues() {
  return RAW.map(r => r.value).filter(v => v !== null && v !== undefined);
}

function percentileRank(v, arr) {
  return arr.filter(x => x < v).length / arr.length * 100;
}

function linearSlope(vals) {
  const n = vals.length;
  if (n < 2) return 0;
  let sx = 0, sy = 0, sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sx += i; sy += vals[i]; sxy += i * vals[i]; sxx += i * i; }
  const den = n * sxx - sx * sx;
  return den === 0 ? 0 : (n * sxy - sx * sy) / den;
}

// ---------- 主题系统（深浅两套，仅影响视觉） ----------
const THEMES = {
  dark: {
    tooltipBg: 'rgba(13,18,24,.97)', tooltipBorder: 'rgba(148,172,200,.25)', tooltipText: '#e6ebf2',
    axisLabel: '#94a0af', axisLine: 'rgba(148,172,200,.18)', splitLine: 'rgba(148,172,200,.08)',
    legendText: '#94a0af', legendInactive: '#3c4754',
    markLineColor: '#414d5c', markLineLabel: '#6b7686', markAreaLabel: '#6b7686',
    markPointLabel: '#aab4c2',
    dzBorder: '#26303c', dzFill: 'rgba(61,139,253,.16)', dzHandle: '#3d8bfd', dzText: '#8b95a5',
    zoneColors: ['rgba(39,174,96,.17)', 'rgba(47,128,237,.13)', 'rgba(231,76,60,.17)'],
    signalZoneColors: ['rgba(39,174,96,.22)', 'rgba(231,76,60,.22)'],
    ratioAreaTop: 'rgba(47,128,237,.22)', mcapArea: 'rgba(242,153,74,.15)',
  },
  light: {
    tooltipBg: 'rgba(255,255,255,.98)', tooltipBorder: '#e2e8f0', tooltipText: '#1a2332',
    axisLabel: '#5a6b80', axisLine: 'rgba(20,40,70,.18)', splitLine: 'rgba(20,40,70,.07)',
    legendText: '#5a6b80', legendInactive: '#b6c2d2',
    markLineColor: '#b0bccb', markLineLabel: '#8a99ad', markAreaLabel: '#8a99ad',
    markPointLabel: '#4a5a70',
    dzBorder: '#d5dde8', dzFill: 'rgba(47,111,224,.14)', dzHandle: '#2f6fe0', dzText: '#5a6b80',
    zoneColors: ['rgba(39,174,96,.10)', 'rgba(47,128,237,.06)', 'rgba(231,76,60,.10)'],
    signalZoneColors: ['rgba(39,174,96,.14)', 'rgba(231,76,60,.14)'],
    ratioAreaTop: 'rgba(47,128,237,.14)', mcapArea: 'rgba(242,153,74,.12)',
  },
};
let initTheme = 'dark';
try { initTheme = localStorage.getItem('buf_theme') || 'dark'; } catch (e) {}
let TC = THEMES[initTheme] || THEMES.dark;
document.body.dataset.theme = TC === THEMES.dark ? 'dark' : 'light';

// ---------- 图表配置构建（两个页面共用同一套逻辑，功能一致） ----------
const markPoints = RAW.filter(r => r.type).map(r => ({
  name: r.type,
  coord: [r.date, r.value],
  value: r.value,
  symbolSize: 10,
  itemStyle: {
    color: r.type.indexOf('牛') >= 0 ? '#e74c3c' : (r.type.indexOf('熊') >= 0 ? '#27ae60' : '#909399')
  },
  label: {
    show: true, fontSize: 10, color: TC.markPointLabel,
    formatter: p => (p.name || '').replace(/\\(.*\\)/, '')
  }
}));

// 预测点：离当日最近的已确认转折点（Zigzag最后一个），
// 峰→预测牛市顶点?  谷→预测熊市底部?（仅标一个）
function getLastTurningPoint() {
  // 以A股总市值序列做转折检测（阈值12万亿），取离当日最近的一个转折点
  const ex = detectZigzag(12, i => RAW[i].mcap);
  if (!ex.length) return null;
  const last = ex[ex.length - 1];
  const di = RAW.findIndex(r => r.date === last.date);
  return {
    type: last.type,          // 'peak' | 'trough'
    date: last.date,
    mcap: last.v,             // 总市值（万亿）
    value: di >= 0 ? RAW[di].value : null  // 当日证券化率（图上y坐标）
  };
}
const lastTurning = getLastTurningPoint();
const predictMark = lastTurning ? [{
  name: lastTurning.type === 'peak' ? '预测牛市顶点?' : '预测熊市底部?',
  coord: [lastTurning.date, lastTurning.value],
  value: lastTurning.value,
  symbol: 'diamond',
  symbolSize: 14,
  itemStyle: { color: '#f39c12', borderColor: '#fff', borderWidth: 1.5 },
  label: {
    show: true, fontSize: 11, fontWeight: 'bold', color: '#d68910',
    position: 'top',
    formatter: () => (lastTurning.type === 'peak' ? '预测牛市顶点?\\n总市值' : '预测熊市底部?\\n总市值') + lastTurning.mcap.toFixed(1) + '万亿'
  }
}] : [];

function visibleIdx(chart) {
  let opt = null;
  try { opt = chart.getOption(); } catch (e) { opt = null; }
  const zooms = opt && opt.dataZoom;
  if (!zooms || !zooms.length) return [0, N - 1];  // before first setOption
  const z = zooms[0];
  const i0 = Math.floor(z.start / 100 * N);
  const i1 = Math.ceil(z.end / 100 * N);
  return [Math.max(0, Math.min(i0, N - 1)), Math.max(0, Math.min(i1, N - 1))];
}

function computeZones(chart) {
  const [i0, i1] = visibleIdx(chart);
  const vals = [];
  for (let i = i0; i <= i1; i++) {
    const v = valueOf(i);
    if (v !== null && v !== undefined) vals.push(v);
  }
  if (vals.length < 4) {
    return { bottom: [20, 60], mid: [60, 100], top: [100, 180], ymin: 0, ymax: 180 };
  }
  const mn = Math.min(...vals);
  const mx = Math.max(...vals);

  // 对数正态方案：证券化率右偏厚尾，直接在原尺度用均值±σ会被极端值污染。
  // 做法：对可视范围内的值取对数 ln(v)，求均值μ与标准差σ，
  //       合理区 = [exp(μ-σ), exp(μ+σ)]（约覆盖中间68%），其外为底部/顶部区。
  // 乘除对称：exp(μ±σ) 等价于几何均值 ×/÷ exp(σ)，适应右偏分布。
  const logs = vals.map(v => Math.log(Math.max(v, 1e-9)));
  const mu = logs.reduce((a, b) => a + b, 0) / logs.length;
  const sigma = Math.sqrt(logs.reduce((s, x) => s + (x - mu) * (x - mu), 0) / logs.length);
  let midLo = Math.round(Math.exp(mu - sigma));
  let midHi = Math.round(Math.exp(mu + sigma));
  if (midLo >= midHi) midHi = midLo + 5;          // 防止区域退化
  const lo = Math.max(0, Math.floor(mn));
  const hi = Math.ceil(mx);
  return {
    bottom: [lo, midLo],
    mid: [midLo, midHi],
    top: [midHi, hi],
    ymin: Math.max(0, lo - 5),
    ymax: hi + 10
  };
}

function zoneMarkArea(z) {
  return [
    [{ yAxis: z.bottom[0], name: '底部参考区 ' + z.bottom[0] + '~' + z.bottom[1] + '%' },
     { yAxis: z.bottom[1], itemStyle: { color: TC.zoneColors[0] } }],
    [{ yAxis: z.mid[0], name: '合理区 ' + z.mid[0] + '~' + z.mid[1] + '%' },
     { yAxis: z.mid[1], itemStyle: { color: TC.zoneColors[1] } }],
    [{ yAxis: z.top[0], name: '顶部参考区 ' + z.top[0] + '~' + z.top[1] + '%' },
     { yAxis: z.top[1], itemStyle: { color: TC.zoneColors[2] } }]
  ];
}

function linearTrendFor(chart) {
  const [i0, i1] = visibleIdx(chart);
  const out = new Array(N).fill(null);
  const n = i1 - i0 + 1;
  if (n < 2) return out;
  let sx = 0, sy = 0, sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) {
    const v = valueOf(i0 + i);
    sx += i; sy += v; sxy += i * v; sxx += i * i;
  }
  const den = n * sxx - sx * sx;
  if (den === 0) return out;
  const b = (n * sxy - sx * sy) / den;
  const a = (sy - b * sx) / n;
  for (let i = 0; i < n; i++) out[i0 + i] = +(a + b * i).toFixed(2);
  return out;
}

function mcapTrendFor(chart) {
  const [i0, i1] = visibleIdx(chart);
  const out = new Array(N).fill(null);
  const n = i1 - i0 + 1;
  if (n < 2) return out;
  let sx = 0, sy = 0, sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) {
    const v = RAW[i0 + i].mcap;
    if (v === undefined || v === null) return out;
    sx += i; sy += v; sxy += i * v; sxx += i * i;
  }
  const den = n * sxx - sx * sx;
  if (den === 0) return out;
  const b = (n * sxy - sx * sy) / den;
  const a = (sy - b * sx) / n;
  for (let i = 0; i < n; i++) out[i0 + i] = +(a + b * i).toFixed(2);
  return out;
}

function themePatch() {
  const patch = {
    legend: { textStyle: { color: TC.legendText }, inactiveColor: TC.legendInactive },
    tooltip: { backgroundColor: TC.tooltipBg, borderColor: TC.tooltipBorder, textStyle: { color: TC.tooltipText } },
    xAxis: [{ axisLabel: { color: TC.axisLabel }, axisLine: { lineStyle: { color: TC.axisLine } } }],
    yAxis: [{ axisLabel: { color: TC.axisLabel }, splitLine: { lineStyle: { color: TC.splitLine } } }],
    dataZoom: [null, { borderColor: TC.dzBorder, fillerColor: TC.dzFill,
      handleStyle: { color: TC.dzHandle }, textStyle: { color: TC.dzText } }],
    series: [{ id: 'ratio', markPoint: { data: markPoints.map(p => ({ ...p, label: { ...p.label, color: TC.markPointLabel } })) } }]
  };
  return patch;
}

function applyTheme(t, save) {
  TC = THEMES[t] || THEMES.dark;
  const isDark = TC === THEMES.dark;
  document.body.dataset.theme = isDark ? 'dark' : 'light';
  document.getElementById('btnTheme').textContent = isDark ? '☀️' : '🌙';
  if (save !== false) { try { localStorage.setItem('buf_theme', isDark ? 'dark' : 'light'); } catch (e) {} }
  const patch = themePatch();
  chart.setOption(patch);
  if (analysisInited && analysisChart) analysisChart.setOption(patch);
  computeSignalZones();  // 用当前主题色重算信号色带
  const sz = { series: [{ id: 'signalZone', markArea: { data: signalZonesData } }] };
  chart.setOption(sz);
  if (analysisInited && analysisChart) analysisChart.setOption(sz);
  refreshTrendFor(chart);
  if (analysisInited) {
    refreshTrendFor(analysisChart, { showDynamic: true, updateInfo: false,
      yMinFloor: globalThis.analysisYMinFloor, yMaxCeil: globalThis.analysisYMaxCeil });
  }
}

function toggleTheme() { applyTheme(TC === THEMES.dark ? 'light' : 'dark'); }

function buildBaseOption(chart, opts) {
  opts = opts || {};
  const showDynamic = opts.showDynamic !== false;   // 动态三区（图表页默认开）
  const extraAreas = opts.extraAreas || [];          // 预测区色带（分析页）
  const extraLines = opts.extraLines || [];          // 极端值虚线（分析页）
  const initZones = computeZones(chart);
  // 初始y轴同样应用预测区可见性约束
  const yMin = opts.yMinFloor !== undefined ? Math.min(initZones.ymin, opts.yMinFloor) : initZones.ymin;
  const yMax = opts.yMaxCeil !== undefined ? Math.max(initZones.ymax, opts.yMaxCeil) : initZones.ymax;
  const yAxisArr = [{
    type: 'value', name: '证券化率 (%)', nameTextStyle: { color: '#8a94a6' },
    min: 0, max: 180,
    axisLabel: { color: TC.axisLabel, formatter: '{value}%' },
    splitLine: { lineStyle: { color: TC.splitLine } }
  }];
  if (HAS_MCAP) {
    yAxisArr.push({
      type: 'value', name: '总市值(万亿)', nameTextStyle: { color: '#f2994a' },
      axisLabel: { color: '#f2994a', formatter: '{value}' },
      splitLine: { show: false }, axisLine: { show: false }
    });
  }

  const baseLines = [
    { yAxis: 100, name: '100%' },
    { yAxis: 75, name: '75%' }
  ];
  const allLines = baseLines.concat(extraLines || []);

  const seriesArr = [{
    id: 'ratio',
    name: '证券化率', type: 'line', data: RAW.map(r => r.value),
    showSymbol: false, smooth: true, connectNulls: true,
    lineStyle: { width: 2, color: '#2f80ed' },
    areaStyle: {
      color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: TC.ratioAreaTop }, { offset: 1, color: 'rgba(47,128,237,0)' }] }
    },
    markLine: {
      silent: true, symbol: 'none',
      lineStyle: { color: TC.markLineColor, type: 'dashed' },
      label: { color: TC.markLineLabel, fontSize: 11, position: 'insideEndTop' },
      data: allLines
    },
    markArea: {
      silent: true,
      label: { color: TC.markAreaLabel, fontSize: 10, position: 'insideTop' },
      data: (showDynamic ? zoneMarkArea(initZones) : []).concat(extraAreas)
    },
    markPoint: { data: markPoints.concat(predictMark) }
  }];
  if (HAS_MCAP) {
    seriesArr.push({
      id: 'mcap',
      name: '总市值(万亿)', type: 'line', yAxisIndex: 1,
      data: RAW.map(r => r.mcap),
      showSymbol: false, smooth: true, connectNulls: true, z: 1, silent: true,
      lineStyle: { width: 1.5, color: '#f2994a' },
      areaStyle: { color: TC.mcapArea }
    });
    seriesArr.push({
      id: 'mcapTrend',
      name: '市值趋势线', type: 'line', yAxisIndex: 1,
      data: [],
      showSymbol: false, smooth: true, connectNulls: false, z: 2, silent: true,
      lineStyle: { width: 1.5, type: 'dashed', color: '#9b59b6' }
    });
  }
  seriesArr.push({
    id: 'trend',
    name: '趋势线', type: 'line', data: [],
    showSymbol: false, smooth: true, connectNulls: false, z: 2, silent: true,
    lineStyle: { width: 2, type: 'dashed', color: '#eb5757' }
  });
  // 牛熊信号区间：独立series承载markArea色带，legend点击控制显隐（两图各自独立）
  seriesArr.push({
    id: 'signalZone',
    name: '牛熊信号区间', type: 'line',
    data: RAW.map(() => null),
    symbol: 'none',
    lineStyle: { color: '#8a94a6', width: 2, opacity: 0.9 },
    z: 0, silent: true, legendHoverLink: false,
    markArea: {
      silent: true,
      label: { show: false },
      data: signalZonesData
    }
  });

  return {
    animation: false,
    legend: {
      top: 4, right: 16, itemGap: 16,
      data: HAS_MCAP
        ? ['证券化率', '总市值(万亿)', '趋势线', '市值趋势线', '牛熊信号区间']
        : ['证券化率', '趋势线', '牛熊信号区间'],
      selected: HAS_MCAP
        ? { '证券化率': true, '总市值(万亿)': false, '趋势线': true, '市值趋势线': false, '牛熊信号区间': false }
        : { '证券化率': true, '趋势线': true, '牛熊信号区间': false },
      textStyle: { color: TC.legendText, fontSize: 12 },
      inactiveColor: TC.legendInactive,
      itemWidth: 18, itemHeight: 10
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: TC.tooltipBg,
      borderColor: TC.tooltipBorder,
      textStyle: { color: TC.tooltipText },
      formatter: ps => {
        const r = RAW[ps[0].dataIndex];
        let html = '<b>' + r.date + '</b><br>';
        html += ps.map(p => {
          let unit = '';
          if (p.seriesName === '证券化率') unit = '%';
          else if (p.seriesName === '总市值(万亿)' || p.seriesName === '市值趋势线') unit = '万亿';
          return p.marker + ' ' + p.seriesName + ': <b>' + p.value + unit + '</b>';
        }).join('<br>');
        for (const k in r.extra) {
          html += '<br>' + k + ': ' + r.extra[k];
        }
        if (r.type) html += '<br>类型: ' + r.type;
        return html;
      }
    },
    grid: { left: 66, right: 66, top: 62, bottom: 66 },
    xAxis: {
      type: 'category', data: RAW.map(r => r.date), boundaryGap: false,
      axisLabel: { color: TC.axisLabel, fontSize: 11 },
      axisLine: { lineStyle: { color: TC.axisLine } }
    },
    yAxis: [{ ...yAxisArr[0], min: yMin, max: yMax }].concat(yAxisArr.slice(1)),
    dataZoom: [
      { type: 'inside', start: 0, end: 100, zoomOnMouseWheel: false, moveOnMouseMove: false },
      { type: 'slider', start: 0, end: 100, height: 22, bottom: 14,
        borderColor: TC.dzBorder, fillerColor: TC.dzFill,
        handleStyle: { color: TC.dzHandle }, textStyle: { color: TC.dzText, fontSize: 11 } }
    ],
    series: seriesArr
  };
}

function updateStatsFor(chart) {
  const [i0, i1] = visibleIdx(chart);
  let mn = Infinity, mx = -Infinity, mi = i0, xi = i0;
  for (let i = i0; i <= i1; i++) {
    const v = valueOf(i);
    if (v < mn) { mn = v; mi = i; }
    if (v > mx) { mx = v; xi = i; }
  }
  document.getElementById('stMax').innerHTML = mx.toFixed(2) + '%<small> (' + RAW[xi].date + ')</small>';
  document.getElementById('stMin').innerHTML = mn.toFixed(2) + '%<small> (' + RAW[mi].date + ')</small>';
}

function updateZonesFor(chart, opts) {
  opts = opts || {};
  const showDynamic = opts.showDynamic !== false;
  const extraAreas = opts.extraAreas || [];
  const updateInfo = opts.updateInfo !== false;
  const z = computeZones(chart);
  // y轴默认跟随可视数据；分析页通过 yMinFloor/yMaxCeil 保证预测区关键边界线始终可见
  // （yMinFloor=下限不能超过的值，yMaxCeil=上限不能低于的值）
  const yMin = opts.yMinFloor !== undefined ? Math.min(z.ymin, opts.yMinFloor) : z.ymin;
  const yMax = opts.yMaxCeil !== undefined ? Math.max(z.ymax, opts.yMaxCeil) : z.ymax;
  const areas = [];
  if (showDynamic) areas.push(...zoneMarkArea(z));
  areas.push(...extraAreas);
  chart.setOption({
    yAxis: [{ min: yMin, max: yMax }],
    series: [{ id: 'ratio', markArea: { data: areas } }]
  });
  if (updateInfo) {
    const el = document.getElementById('zoneInfo');
    if (el) {
      el.innerHTML =
        '<span style="color:#27ae60">底部 ' + z.bottom[0] + '~' + z.bottom[1] + '%</span> | ' +
        '<span style="color:#2f80ed">合理 ' + z.mid[0] + '~' + z.mid[1] + '%</span> | ' +
        '<span style="color:#e74c3c">顶部 ' + z.top[0] + '~' + z.top[1] + '%</span>';
    }
  }
}

function refreshTrendFor(chart, opts) {
  opts = opts || {};
  const upd = { series: [{ id: 'trend', data: linearTrendFor(chart) }] };
  if (HAS_MCAP) upd.series.push({ id: 'mcapTrend', data: mcapTrendFor(chart) });
  chart.setOption(upd);
  updateStatsFor(chart);
  updateZonesFor(chart, opts);
}

// ---------- 主图（图表页） ----------
let zoomSyncing = false;  // 防循环：两图缩放双向同步标志
let signalZonesData = [];   // 牛熊信号区间（独立series的markArea，两图各自legend控制显隐）
computeSignalZones();

function syncZoomTo(src, dst) {
  if (zoomSyncing || !dst) return;
  zoomSyncing = true;
  try {
    let opt = null;
    try { opt = src.getOption(); } catch (e) { opt = null; }
    const z = opt && opt.dataZoom && opt.dataZoom[0];
    if (z) dst.dispatchAction({ type: 'dataZoom', start: z.start, end: z.end });
  } finally {
    zoomSyncing = false;
  }
}

const chart = echarts.init(document.getElementById('chart'));
chart.setOption(buildBaseOption(chart));
chart.on('dataZoom', () => {
  refreshTrendFor(chart);
  if (analysisInited) syncZoomTo(chart, analysisChart);
});
window.addEventListener('resize', () => chart.resize());

const last = RAW[N - 1];
document.getElementById('stLatest').innerHTML =
  (last.value === null ? '--' : last.value.toFixed(2) + '%') + '<small> (' + last.date + ')</small>';
refreshTrendFor(chart);

// ---------- 可视范围选择器（顶部卡片） ----------
function findIdx(dateStr, mode) {
  // mode: 'from'=第一个>=该日期的索引; 'to'=最后一个<=该日期的索引
  if (mode === 'from') {
    for (let i = 0; i < N; i++) if (RAW[i].date >= dateStr) return i;
    return N - 1;
  }
  for (let i = N - 1; i >= 0; i--) if (RAW[i].date <= dateStr) return i;
  return 0;
}

function refreshAllCharts() {
  // 主图：趋势线/统计/估值区域全量同步
  refreshTrendFor(chart);
  // 分析图：同样全量同步（含预测区可见性约束）
  if (analysisInited) {
    refreshTrendFor(analysisChart, { showDynamic: true, updateInfo: false,
      yMinFloor: globalThis.analysisYMinFloor, yMaxCeil: globalThis.analysisYMaxCeil });
  }
}

function setDataZoomRange(i0, i1) {
  const start = i0 / N * 100;
  const end = (i1 + 1) / N * 100;
  chart.dispatchAction({ type: 'dataZoom', start, end });
  if (analysisInited) analysisChart.dispatchAction({ type: 'dataZoom', start, end });
  // 不依赖事件，直接同步两图所有数据（趋势线/统计/区域）
  refreshAllCharts();
}

function applyRange() {
  const from = document.getElementById('rangeFrom').value;
  const to = document.getElementById('rangeTo').value;
  if (!from || !to) return;
  let i0 = findIdx(from, 'from');
  let i1 = findIdx(to, 'to');
  if (i0 > i1) { alert('起始日期需早于结束日期'); return; }
  // 回填为实际对齐的数据点日期
  document.getElementById('rangeFrom').value = RAW[i0].date;
  document.getElementById('rangeTo').value = RAW[i1].date;
  setDataZoomRange(i0, i1);
  updateQuickActive();
}

function quickRange(years) {
  const lastIdx = N - 1;
  const d = new Date(RAW[lastIdx].date);
  d.setFullYear(d.getFullYear() - years);
  document.getElementById('rangeFrom').value = d.toISOString().slice(0, 10);
  document.getElementById('rangeTo').value = RAW[lastIdx].date;
  applyRange();
}

function quickAll() {
  document.getElementById('rangeFrom').value = RAW[0].date;
  document.getElementById('rangeTo').value = RAW[N - 1].date;
  setDataZoomRange(0, N - 1);
  updateQuickActive();
}

function updateQuickActive() {
  const from = document.getElementById('rangeFrom').value;
  const to = document.getElementById('rangeTo').value;
  document.querySelectorAll('.qbtn').forEach(b => b.classList.remove('active'));
  if (from === RAW[0].date && to === RAW[N - 1].date) {
    const allBtn = document.querySelector('.qbtn[data-all]');
    if (allBtn) allBtn.classList.add('active');
  }
}

document.getElementById('btnApplyRange').onclick = applyRange;
// 日期变化直接生效（无需点应用）；Enter 也触发
['rangeFrom', 'rangeTo'].forEach(id => {
  document.getElementById(id).addEventListener('change', applyRange);
  document.getElementById(id).addEventListener('keydown', e => { if (e.key === 'Enter') applyRange(); });
});
// 快捷按钮
document.querySelectorAll('.qbtn').forEach(btn => {
  btn.onclick = () => {
    if (btn.getAttribute('data-all')) quickAll();
    else quickRange(parseInt(btn.getAttribute('data-years'), 10));
  };
});

// ---------- 页面切换 ----------
let analysisInited = false;
let analysisChart = null;

function switchPage(page) {
  const chartPage = page === 'chart';
  document.getElementById('page-chart').style.display = chartPage ? 'block' : 'none';
  document.getElementById('page-analysis').style.display = chartPage ? 'none' : 'block';
  document.getElementById('btn-chart').classList.toggle('active', chartPage);
  document.getElementById('btn-analysis').classList.toggle('active', !chartPage);
  if (chartPage) {
    chart.resize();
    refreshTrendFor(chart);
  } else {
    if (!analysisInited) { initAnalysis(); }
    else {
      analysisChart.resize();
      refreshTrendFor(analysisChart, { showDynamic: true, updateInfo: false,
        yMinFloor: globalThis.analysisYMinFloor, yMaxCeil: globalThis.analysisYMaxCeil });
    }
  }
}
document.getElementById('btn-chart').onclick = () => switchPage('chart');
document.getElementById('btn-analysis').onclick = () => switchPage('analysis');

// ---------- 分析页：预测计算 ----------

// Zigzag转折点检测：波动超过 minMove 个百分点才确认峰/谷，
// 自动识别所有大周期牛熊转折点（不依赖手工标注）
function detectZigzag(minMove, getter) {
  getter = getter || valueOf;  // 默认证券化率；可传 i => RAW[i].mcap 用总市值
  const pts = [];
  for (let i = 0; i < N; i++) {
    const v = getter(i);
    if (v !== null && v !== undefined) pts.push({ i, v, date: RAW[i].date });
  }
  const extrema = [];
  let dir = 0;
  let cand = pts[0];
  for (let k = 1; k < pts.length; k++) {
    const p = pts[k];
    if (dir === 0) {
      if (p.v > cand.v) { dir = 1; cand = p; }
      else if (p.v < cand.v) { dir = -1; cand = p; }
    } else if (dir === 1) {
      if (p.v >= cand.v) cand = p;
      else if (cand.v - p.v >= minMove) {
        extrema.push({ type: 'peak', v: cand.v, date: cand.date });
        cand = p; dir = -1;
      }
    } else {
      if (p.v <= cand.v) cand = p;
      else if (p.v - cand.v >= minMove) {
        extrema.push({ type: 'trough', v: cand.v, date: cand.date });
        cand = p; dir = 1;
      }
    }
  }
  return extrema;
}

function computeForecast() {
  const cur = RAW[N - 1].value;
  const vals = allValues();
  const rank = percentileRank(cur, vals);

  // Zigzag自动检测全部大周期转折点（阈值15个百分点）
  const extrema = detectZigzag(15);
  const peaks = extrema.filter(e => e.type === 'peak').map(e => e.v);
  const troughs = extrema.filter(e => e.type === 'trough').map(e => e.v);

  // 常规区间 = P30~P70 分位（稳健，自动排除两端离群值）
  const topLo = Math.round(pctOf(peaks, 0.30));
  const topHi = Math.round(pctOf(peaks, 0.70));
  const topMed = Math.round(pctOf(peaks, 0.50));
  const botLo = Math.round(pctOf(troughs, 0.30));
  const botHi = Math.round(pctOf(troughs, 0.70));
  const botMed = Math.round(pctOf(troughs, 0.50));
  // 极端参考线 = 峰最大值 / 谷最小值（2007年164%顶、2005年20%底）
  const extremeTop = peaks.length ? Math.round(Math.max(...peaks)) : null;
  const extremeBot = troughs.length ? Math.round(Math.min(...troughs)) : null;

  // 近12个月趋势（24个半月点）
  const recent = RAW.slice(-24).map(r => r.value).filter(v => v !== null);
  const slopePerMonth = linearSlope(recent) * 2;  // 每点=半个月

  // 历史熊市回撤（峰→下一个谷的跌幅）
  const drops = [];
  for (let i = 0; i < extrema.length - 1; i++) {
    if (extrema[i].type === 'peak') {
      for (let j = i + 1; j < extrema.length; j++) {
        if (extrema[j].type === 'trough') {
          drops.push((extrema[j].v - extrema[i].v) / extrema[i].v * 100);
          break;
        }
      }
    }
  }
  const avgDrop = drops.length ? drops.reduce((a, b) => a + b, 0) / drops.length : -37;

  // 熊市周期（谷→下一个谷）月数
  const troughPts = extrema.filter(e => e.type === 'trough');
  const cycles = [];
  for (let i = 1; i < troughPts.length; i++) {
    cycles.push((new Date(troughPts[i].date) - new Date(troughPts[i - 1].date)) / 86400000 / 30);
  }
  const avgCycle = cycles.length ? Math.round(cycles.reduce((a, b) => a + b, 0) / cycles.length) : 40;

  return {
    cur, rank,
    peaks, troughs,
    normalTopLo: topLo, normalTopHi: topHi, normalTopMed: topMed,
    normalBotLo: botLo, normalBotHi: botHi, normalBotMed: botMed,
    extremeTop, extremeBot,
    slopePerMonth, avgDrop, avgCycle
  };
}

function initAnalysis() {
  const fc = computeForecast();

  // 预测区：不画色带，只用虚线标注常规顶部/底部区边界（与图表页动态三区叠加不冲突）
  const extraLines = [
    { yAxis: fc.normalTopLo, name: '常规顶区下沿', lineStyle: { color: '#e74c3c', type: 'dashed' },
      label: { color: '#e74c3c', formatter: '常规顶区 ' + fc.normalTopLo + '%' } },
    { yAxis: fc.normalTopHi, name: '常规顶区上沿', lineStyle: { color: '#e74c3c', type: 'dashed' },
      label: { color: '#e74c3c', formatter: '常规顶区 ' + fc.normalTopHi + '%' } },
    { yAxis: fc.normalBotLo, name: '常规底区下沿', lineStyle: { color: '#27ae60', type: 'dashed' },
      label: { color: '#27ae60', formatter: '常规底区 ' + fc.normalBotLo + '%' } },
    { yAxis: fc.normalBotHi, name: '常规底区上沿', lineStyle: { color: '#27ae60', type: 'dashed' },
      label: { color: '#27ae60', formatter: '常规底区 ' + fc.normalBotHi + '%' } }
  ];
  if (fc.extremeTop !== null) {
    extraLines.push({
      yAxis: fc.extremeTop, name: '极端顶', lineStyle: { color: '#e74c3c', type: 'dotted' },
      label: { color: '#e74c3c', formatter: '极端顶 ' + fc.extremeTop + '%' }
    });
  }
  if (fc.extremeBot !== null) {
    extraLines.push({
      yAxis: fc.extremeBot, name: '极端底', lineStyle: { color: '#27ae60', type: 'dotted' },
      label: { color: '#27ae60', formatter: '极端底 ' + fc.extremeBot + '%' }
    });
  }

  // 分析图与图表页交互完全一致；y轴跟随可视数据动态缩放，
  // 但保证常规顶部区上沿(108%)与常规底部区下沿(40%)两条虚线始终可见
  globalThis.analysisYMinFloor = fc.normalBotLo - 6;   // 40-6=34
  globalThis.analysisYMaxCeil = fc.normalTopHi + 6;    // 108+6=114
  analysisChart = echarts.init(document.getElementById('chart-analysis'));
  const aOpts = { extraLines, showDynamic: true, updateInfo: false,
    yMinFloor: globalThis.analysisYMinFloor, yMaxCeil: globalThis.analysisYMaxCeil };
  analysisChart.setOption(buildBaseOption(analysisChart, aOpts));
  // 分析图缩放 → 刷新自身 + 同步主图（防循环）
  analysisChart.on('dataZoom', () => {
    refreshTrendFor(analysisChart, aOpts);
    syncZoomTo(analysisChart, chart);
  });
  // 初始化后继承主图当前的可视范围（懒加载时主图可能已缩放）
  syncZoomTo(chart, analysisChart);
  refreshTrendFor(analysisChart, aOpts);
  analysisInited = true;  // 必须在同步逻辑生效前标记
  fillAnalysis(fc);
}

function fillAnalysis(fc) {
  fc = fc || computeForecast();  // 页面加载时的兜底
  const { cur, rank, peaks, troughs, normalTopLo, normalTopHi, normalTopMed, extremeTop,
          normalBotLo, normalBotHi, normalBotMed, extremeBot,
          slopePerMonth, avgDrop, avgCycle } = fc;

  document.getElementById('an-cur').innerHTML = cur.toFixed(1) + '%';
  document.getElementById('an-date').innerHTML = RAW[N - 1].date;
  document.getElementById('an-rank').innerHTML = rank.toFixed(0) + '%分位';
  document.getElementById('an-top').innerHTML = normalTopLo + '~' + normalTopHi + '%';
  document.getElementById('an-top-sub').innerHTML =
    '自动检测 ' + peaks.length + ' 个牛市峰（P30~P70），极值' + (extremeTop !== null ? extremeTop + '%' : '—');
  document.getElementById('an-bot').innerHTML = normalBotLo + '~' + normalBotHi + '%';
  document.getElementById('an-bot-sub').innerHTML =
    '自动检测 ' + troughs.length + ' 个熊市谷（P30~P70），极值' + (extremeBot !== null ? extremeBot + '%' : '—');

  // ---- 预测文本 ----
  let html = '';

  // 当前状态
  html += '<p><span class="hl">当前 ' + cur.toFixed(1) + '%</span>（' + RAW[N - 1].date + '），' +
    '处于全历史 <span class="hl">P' + rank.toFixed(0) + '</span> 分位（历史上约 ' + rank.toFixed(0) + '% 的时间证券化率低于当前值）。</p>';

  // 顶部预测
  const topGap = normalTopLo - cur;
  html += '<p>🔺 <b>牛市顶部预测：</b>自动检测的历史牛市峰共 <b>' + peaks.length +
    ' 个</b>，集中分布在 <span class="hlr">' + normalTopLo + '~' + normalTopHi + '%</span>（中位数 <b>' + normalTopMed +
    '%</b>）' +
    (extremeTop !== null ? '；最高峰 <span class="hlr">' + extremeTop + '%</span>（2007年）为极端泡沫（见下方说明），仅作极端参考' : '') +
    '。';
  if (cur >= normalTopLo) {
    html += '当前值 <span class="hlr">已处于常规顶部区间内</span>' +
      (cur >= normalTopMed ? '，甚至已超过历史顶部中位数，估值偏高，建议分批减仓。' : '，接近顶部下沿，需提高警惕。');
  } else {
    html += '当前距常规顶部下沿 ' + normalTopLo + '% 还有 <span class="hlr">+' + topGap.toFixed(1) + ' 个百分点</span>。';
    if (slopePerMonth > 0) {
      const monthsTop = Math.max(0, topGap / slopePerMonth);
      html += '按近12个月趋势（约 <span class="hl">+' + slopePerMonth.toFixed(1) + '%/月</span>）外推，' +
        (monthsTop < 200 ? '约 <b>' + Math.round(monthsTop) + ' 个月</b>后可能触及常规顶部区下沿。' :
          '短期难以触及顶部区。');
    } else {
      html += '近12个月证券化率呈<span class="hlr">下行趋势</span>，当前不在上升通道中，暂无迫近顶部的迹象。';
    }
  }
  html += '</p>';

  // 底部预测
  const botGap = cur - normalBotHi;
  html += '<p>🔻 <b>熊市底部预测：</b>自动检测的历史熊市谷共 <b>' + troughs.length +
    ' 个</b>，集中分布在 <span class="hlg">' + normalBotLo + '~' + normalBotHi +
    '%</span>（中位数 <b>' + normalBotMed + '%</b>）' +
    (extremeBot !== null ? '；最低谷 <span class="hlg">' + extremeBot + '%</span>（2005年998点大底）为极端情形，仅作极端参考' : '') +
    '。当前距常规底部上沿 ' + normalBotHi + '% 还有 <span class="hlg">-' + Math.max(0, botGap).toFixed(1) +
    ' 个百分点</span>。若发生熊市，历史峰→谷平均回撤约 <span class="hlr">' + avgDrop.toFixed(0) +
    '%</span>，从当前水平回撤后对应约 <span class="hlg">' + (cur * (1 + avgDrop / 100)).toFixed(0) +
    '%</span>。历史熊市周期（谷到下一次谷）平均约 <span class="hl">' + avgCycle + ' 个月</span>。</p>';

  // 预测逻辑说明
  html += '<p><b>📐 预测逻辑说明</b>（为什么这样划分顶部/底部区域）：</p>';
  html += '<ul style="margin:4px 0 4px 20px;padding:0;color:var(--text-2);font-size:13px;line-height:2">';
  html += '<li><b>转折点自动检测（Zigzag）</b>：对全部 ' + N + ' 个数据点扫描，证券化率从峰回落或从谷回升 <b>超过15个百分点</b> 才确认一个转折点，自动识别出 <b>' +
    (peaks.length + troughs.length) + ' 个</b>大周期牛熊转折（' + peaks.length + '峰/' + troughs.length + '谷），不依赖人工标注。波动不足15个百分点的次级震荡被忽略。</li>';
  html += '<li><b>与图表页动态三区的区别</b>：图表页的估值区域是对<b>可视范围内全部数据</b>做对数正态 μ±1σ 划分（随缩放变化，回答"现在处于所选范围的什么相对位置"）；本页预测区是对<b>全历史牛熊转折点</b>做分位统计（固定不变，回答"未来顶/底目标在哪"）。两者方法不同但互补——动态三区看"相对位置"，预测区看"绝对目标"。</li>';
  html += '<li><b>常规区间 = 分位数 P30~P70</b>：对全部峰（或谷）取值后，取中间40%的分位区间作为“常规”范围——比 min~max 稳健得多，单点异常（如 <span class="hlr">2007年' + (extremeTop || '') + '%</span>、<span class="hlg">2005年' + (extremeBot || '') + '%</span>）被自动排除在区间之外，仅作为极端参考线保留。</li>';
  html += '<li><b>时间预测</b>：用近12个月证券化率的线性回归斜率做外推，<b>假设趋势延续</b>；若斜率向下则不做顶部时间预测（改为提示当前不在上升通道）。</li>';
  html += '<li><b>回撤参考</b>：平均回撤 = 每个自动检测的峰到其后最近谷的跌幅均值；熊市周期 = 相邻两个谷的间隔月数均值。</li>';
  html += '<li><b>局限</b>：GDP增速、IPO扩容、政策与资金面变化都可能使历史规律失效；15个百分点阈值与P30~P70区间为统计设定，可调整。本页所有数字均为统计参考，不构成投资建议。</li>';
  html += '</ul>';

  document.getElementById('an-pred').innerHTML = html;
}

// ---------- 牛熊信号区间（全历史逐点检测，x轴方向色带） ----------
function scoreSignal(w) {
  let botScore = 0, topScore = 0, botTrend = 0, topTrend = 0;
  for (const years of [10, 5, 3]) {
    const s = w[years];
    if (!s) continue;
    if (s.inBot) botScore += 1;
    if (s.inTop) topScore += 1;
  }
  const s3 = w[3], s5 = w[5];
  if (s3 && s5) {
    if (s3.slopePerMonth < 0) botTrend += 1;
    if (Math.abs(s5.slopePerMonth) < 0.2) botTrend += 1;
    if (s3.slopePerMonth > 0) topTrend += 1;
    if (s5.slopePerMonth < s3.slopePerMonth) topTrend += 1;
  }
  return { botTotal: botScore + botTrend, topTotal: topScore + topTrend };
}

function computeSignalZones() {
  // 逐点打分（阈值>=4视为信号）
  const botRuns = [], topRuns = [];
  let botRun = null, topRun = null;
  for (let i = 0; i < N; i++) {
    const sc = scoreSignal(detectSignal(i));
    if (sc.botTotal >= 4) { if (botRun === null) botRun = [i, i]; else botRun[1] = i; }
    else if (botRun !== null) { botRuns.push(botRun); botRun = null; }
    if (sc.topTotal >= 4) { if (topRun === null) topRun = [i, i]; else topRun[1] = i; }
    else if (topRun !== null) { topRuns.push(topRun); topRun = null; }
  }
  if (botRun !== null) botRuns.push(botRun);
  if (topRun !== null) topRuns.push(topRun);

  // 合并：间隔<=3个数据点(约1.5个月)的连续段合并；长度<2个点(约1个月)视为噪声过滤
  const merge = (runs) => {
    if (!runs.length) return [];
    const out = [runs[0].slice()];
    for (let i = 1; i < runs.length; i++) {
      if (runs[i][0] - out[out.length - 1][1] <= 3) out[out.length - 1][1] = runs[i][1];
      else out.push(runs[i].slice());
    }
    return out.filter(r => r[1] - r[0] >= 2);
  };

  signalZonesData = [];
  for (const [s, e] of merge(botRuns)) {
    signalZonesData.push([
      { xAxis: RAW[s].date, name: '熊市底部信号区 ' + RAW[s].date + '~' + RAW[e].date },
      { xAxis: RAW[e].date, itemStyle: { color: TC.signalZoneColors[0] } }
    ]);
  }
  for (const [s, e] of merge(topRuns)) {
    signalZonesData.push([
      { xAxis: RAW[s].date, name: '牛市顶部信号区 ' + RAW[s].date + '~' + RAW[e].date },
      { xAxis: RAW[e].date, itemStyle: { color: TC.signalZoneColors[1] } }
    ]);
  }
}
fillAnalysis();

// ---------- 牛熊信号检测（多尺度窗口） ----------
function windowStats(fromIdx, toIdx) {
  const data = [];
  for (let i = fromIdx; i <= toIdx; i++) {
    const v = valueOf(i);
    if (v !== null && v !== undefined) data.push(v);
  }
  if (data.length < 4) return null;
  const cur = data[data.length - 1];
  const logs = data.map(v => Math.log(Math.max(v, 1e-9)));
  const mu = logs.reduce((a, b) => a + b, 0) / logs.length;
  const sigma = Math.sqrt(logs.reduce((s, x) => s + (x - mu) * (x - mu), 0) / logs.length);
  const botHi = Math.exp(mu - sigma);   // 窗口对数正态底部区上沿
  const topLo = Math.exp(mu + sigma);   // 窗口对数正态顶部区下沿
  // 位置判定：绝对锚点主导（常规底区上沿62 / 常规顶区下沿90，含容差），
  // 窗口分位作“接近”补充：62~75之间仅在窗口内低位(P30以下)才算接近底部；82~90之间仅在窗口内高位(P70以上)才算接近顶部
  const inBot = (cur <= 62) || (cur <= 75 && percentileRank(cur, data) < 30);
  const inTop = (cur >= 90) || (cur >= 82 && percentileRank(cur, data) > 70);
  return {
    cur, n: data.length,
    pctRank: percentileRank(cur, data),
    inBot, inTop,
    botHi, topLo,
    slopePerMonth: linearSlope(data) * 2  // 每点=半个月
  };
}

function detectSignal(targetIdx) {
  const d = new Date(RAW[targetIdx].date);
  const res = {};
  for (const years of [3, 5, 10]) {
    const sd = new Date(d);
    sd.setFullYear(sd.getFullYear() - years);
    const i0 = findIdx(sd.toISOString().slice(0, 10), 'from');
    res[years] = windowStats(Math.max(0, i0), targetIdx);
  }
  return res;
}

function runSignalCheck() {
  const v = document.getElementById('signalDate').value;
  if (v) {
    const i = findIdx(v, 'from');
    document.getElementById('signalDate').value = RAW[i].date;
    renderSignal(i);
  } else {
    renderSignal(N - 1);
  }
}

function renderSignal(targetIdx) {
  const target = RAW[targetIdx];
  const w = detectSignal(targetIdx);
  const names = { 3: '3年窗口', 5: '5年窗口', 10: '10年窗口' };

  let botScore = 0, topScore = 0, botTrend = 0, topTrend = 0;
  let cards = '';
  for (const years of [10, 5, 3]) {
    const s = w[years];
    if (!s) { cards += '<div class="sig-card"><div class="w-name">' + names[years] + '</div><div class="w-pos mid">数据不足</div></div>'; continue; }
    let posTxt, posCls;
    if (s.inBot) { posTxt = '底部区'; posCls = 'bot'; }
    else if (s.inTop) { posTxt = '顶部区'; posCls = 'top'; }
    else { posTxt = '合理区'; posCls = 'mid'; }
    let arrow, arrowColor;
    if (Math.abs(s.slopePerMonth) < 0.2) { arrow = '→ 走平'; arrowColor = '#2f80ed'; }
    else if (s.slopePerMonth > 0) { arrow = '↑ 上行'; arrowColor = '#e74c3c'; }
    else { arrow = '↓ 下行'; arrowColor = '#27ae60'; }
    cards += '<div class="sig-card">' +
      '<div class="w-name">' + names[years] + '</div>' +
      '<div class="w-pos ' + posCls + '">' + posTxt + '</div>' +
      '<div class="w-pct">P' + s.pctRank.toFixed(0) + '分位 · ' + s.cur.toFixed(1) + '%</div>' +
      '<div class="w-trend" style="color:' + arrowColor + '">' + arrow + ' <small>(' + (s.slopePerMonth > 0 ? '+' : '') + s.slopePerMonth.toFixed(2) + '%/月)</small></div>' +
      '</div>';
    if (s.inBot) botScore += 1;
    if (s.inTop) topScore += 1;
  }
  const s3 = w[3], s5 = w[5];
  if (s3 && s5) {
    if (s3.slopePerMonth < 0) botTrend += 1;              // 底部：短周期仍下行（磨底）
    if (Math.abs(s5.slopePerMonth) < 0.2) botTrend += 1;  // 底部：中周期走平（衰竭）
    if (s3.slopePerMonth > 0) topTrend += 1;              // 顶部：短周期仍上行（冲顶）
    if (s5.slopePerMonth < s3.slopePerMonth) topTrend += 1; // 顶部：中周期涨速放缓（动能衰减）
  }
  const botTotal = botScore + botTrend;
  const topTotal = topScore + topTrend;

  // 结论横幅
  let bannerCls = 'none', bannerHtml = '';
  const dotsHtml = (total, side) => {
    let d = '';
    for (let i = 0; i < 5; i++) d += '<span class="' + (i < total ? 'on ' + side : '') + '"></span>';
    return '<span class="sig-dots">' + d + '</span>';
  };
  if (botTotal >= 5) {
    bannerCls = 'strong-bot';
    bannerHtml = '🔻 <b>强熊市底部信号</b>' + dotsHtml(5, 'bot') + '<br>' +
      '<small>多周期估值低位 + 中周期衰竭 + 短周期磨底——历史上该形态对应大级别底部区（2024-02、2013-06、2019-01均触发）</small>';
  } else if (botTotal >= 4) {
    bannerCls = 'mid-bot';
    bannerHtml = '🔻 <b>偏熊市底部信号</b>' + dotsHtml(botTotal, 'bot') + '<br>' +
      '<small>估值低位明显，趋势条件部分满足，可分批布局</small>';
  } else if (topTotal >= 5) {
    bannerCls = 'strong-top';
    bannerHtml = '🔺 <b>强牛市顶部信号</b>' + dotsHtml(5, 'top') + '<br>' +
      '<small>多周期估值高位 + 动能衰减——历史上该形态对应大级别顶部区（2007-10、2015-06、2021-02均触发）</small>';
  } else if (topTotal >= 4) {
    bannerCls = 'mid-top';
    bannerHtml = '🔺 <b>偏牛市顶部信号</b>' + dotsHtml(topTotal, 'top') + '<br>' +
      '<small>估值高位明显，趋势条件部分满足，建议逐步减仓</small>';
  } else {
    bannerCls = 'none';
    bannerHtml = '⚪ <b>无明显牛熊信号</b>' + dotsHtml(Math.max(botTotal, topTotal), '') + '<br>' +
      '<small>估值处于中间地带（' + Math.max(botTotal, topTotal) + '/5），等待趋势确认</small>';
  }

  const el = document.getElementById('signalResult');
  if (el) {
    el.innerHTML =
      '<div class="sig-toolbar"><label>📅 基准日期</label>' +
      '<input type="date" id="signalDate" value="' + target.date + '" /> ' +
      '<button id="btnSignal" class="qbtn">检测</button>' +
      '<span style="color:#8a94a6;font-size:12px">（默认最新日期，可输入历史日期验证当时信号）</span></div>' +
      '<div class="sig-banner ' + bannerCls + '">' + bannerHtml + '</div>' +
      '<div class="sig-cards">' + cards + '</div>' +
      '<p style="margin-top:6px;font-size:12px;color:#555">判定依据：① 各窗口估值位置（绝对锚点62%/90% + 窗口内分位接近） ② 3年趋势方向（底负顶正） ③ 5年趋势衰竭（底部走平 / 顶部涨速衰减）。5项满足越多信号越强。</p>';
    // 重新绑定事件（元素被重建）
    document.getElementById('btnSignal').onclick = runSignalCheck;
    document.getElementById('signalDate').addEventListener('change', runSignalCheck);
  }
}

// 默认：检测最新日期（当前时点）——renderSignal 内部会生成控件并绑定事件
renderSignal(N - 1);

// ---------- 主题初始化 ----------
document.getElementById('btnTheme').onclick = toggleTheme;
applyTheme(initTheme, false);

// 初始化可视范围输入框为全范围（此时所有变量已就绪）
quickAll();
</script>
</body>
</html>"""


def generate_indicator_html(indicator, output_dir=None) -> Path | None:
    """
    Generate an interactive HTML page from an indicator's Excel data.
    Returns the output file path, or None if no data available.
    """
    df = load_excel(indicator.output_file, indicator.date_col)
    if df.empty:
        return None

    cols = list(df.columns)
    date_col = indicator.date_col
    # 优先用指标声明的 value_col，否则取列名含"率/比"的列，再退化为第一个数值列
    value_col = getattr(indicator, "value_col", None)
    if value_col is None or value_col not in cols:
        value_col = next((c for c in cols if c != date_col and c != "类型" and ("率" in c or "比" in c)), None)
    if value_col is None:
        value_col = next((c for c in cols if c != date_col and c != "类型"), None)
    type_col = "类型" if "类型" in df.columns else None
    if value_col is None:
        return None
    # 检测市值列（用于叠加曲线）
    mcap_col = next((c for c in cols if "市值" in c and c != date_col and c != value_col), None)

    records = []
    for _, row in df.iterrows():
        v = row.get(value_col)
        rec = {
            "date": str(row[date_col])[:10],
            "value": round(float(v), 2) if pd.notna(v) else None,
            "type": str(row[type_col]).strip() if (type_col and pd.notna(row.get(type_col))) else "",
            "extra": {},
        }
        if mcap_col and pd.notna(row.get(mcap_col)):
            rec["mcap"] = round(float(row.get(mcap_col)), 2)
        for c in cols:
            if c in (date_col, value_col, type_col):
                continue
            val = row.get(c)
            if pd.notna(val):
                try:
                    rec["extra"][c] = round(float(val), 2)
                except (ValueError, TypeError):
                    pass  # non-numeric column (e.g. GDP来源) — skip
        records.append(rec)

    records.sort(key=lambda r: r["date"])
    if not records:
        return None

    html = _PAGE_TEMPLATE.replace("__TITLE__", indicator.name)
    html = html.replace("__ECHARTS__", _ECHARTS_CDN)
    html = html.replace("__DATA__", json.dumps(records, ensure_ascii=False))

    filename = getattr(indicator, "html_filename", None) or f"{indicator.name}.html"
    out = (output_dir or Path("output")) / filename
    out.write_text(html, encoding="utf-8")
    return out
