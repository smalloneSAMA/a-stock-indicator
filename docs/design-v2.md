# 证券化率终端 · V2 视觉重设计

> 依据：frontend-design（差异化美学）+ UI/UX Pro Max 设计系统（Real-Time Monitoring 风格）
> 原则：**全部现有功能保留**（双页联动/动态三区/信号检测/牛熊预测/主题切换等），只重塑视觉层。

---

## 1. 设计概念：「估值雷达」金融终端

**方向**：专业行情终端（Bloomberg / 富途 / Longbridge 一脉）——深空 slate 底、单一绿色强调（金融"买入/健康"语义）、等宽数字、细网格纹理。区别于上一版"通用深蓝仪表盘"：主曲线改冰蓝、UI 强调改**金融绿**、数字全部 Fira Code 等宽、背景加**十字网格纹理**（终端纸感）。

**记忆点**（用户会记住的一个细节）：
- Header 左侧**脉冲雷达点 + 数据状态行**（"DATA 2026-08-01 · 全市场 109.78 万亿"），LED 呼吸灯效果
- 图表面板顶部**细高光线 + 绿色 LIVE 徽标**，终端设备感
- 估值区域色带与牛熊信号色带改用**绿/蓝/红三元语义**（底部=买入绿、顶部=泡沫红）

---

## 2. 设计系统（Design Tokens）

### 2.1 配色（双主题，语义化 token）

**深色主题**（默认，UI/UX Pro Max slate 系）：

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg` | `#020617` | 页面底（slate-950） |
| `--surface` | `#0F172A` | 卡片面板（slate-900） |
| `--surface-2` | `#1E293B` | 嵌套面/悬浮 |
| `--border` | `rgba(148,163,184,.14)` | 分隔线 |
| `--text` | `#F8FAFC` | 主文本（≥4.5:1） |
| `--text-2` | `#94A3B8` | 次文本（≥3:1） |
| `--text-3` | `#64748B` | 弱标签 |
| `--accent` | `#22C55E` | **金融绿**：按钮/激活/LED/底部语义 |
| `--accent-deep` | `#16A34A` | 渐变深端 |
| `--danger` | `#EF4444` | 顶部语义/警示 |
| `--curve` | `#38BDF8` | 主曲线冰蓝（图表） |
| `--curve-2` | `#F59E0B` | 总市值琥珀（右轴） |
| `--trend` | `#F87171` | 证券化率趋势线 |
| `--trend-2` | `#A78BFA` | 市值趋势线 |

**浅色主题**（同 token 名，值反转）：

| Token | 值 |
|-------|-----|
| `--bg` | `#F8FAFC` |
| `--surface` | `#FFFFFF` |
| `--surface-2` | `#F1F5F9` |
| `--text` | `#0F172A` |
| `--text-2` | `#475569` |
| `--accent` | `#16A34A`（白字对比 4.5:1） |
| `--curve` | `#0284C7` |

> 规则：按钮主色 = `--accent` 深色；浅色主题按钮白字用 `--accent`(#16A34A)；**绿只给"正向/买入/激活"，红只给"顶部/警示"**，数据中性色用蓝/琥珀——语义不打架。

### 2.2 字体

- **Fira Code**（`wght@400;500;600;700`）：全部数字、指标值、坐标轴标签、图例数值 → `font-variant-numeric: tabular-nums`
- **Fira Sans**（`wght@300;400;500;600;700`）：标题、正文（中文 fallback：PingFang SC / Microsoft YaHei）
- 加载：Google Fonts `<link>` + `font-display: swap` + 多级 fallback（离线不阻塞）；中文不加载 webfont（系统字体栈），只保证拉丁/数字用 Fira
- 标题层级：页面 20px/700/-0.02em；卡片标题 13px/600；标签 11px/500/+0.08em 大写；数字 24~28px/600 等宽

### 2.3 间距（8dp 节奏，density 8/10）

`--space-1:4px … --space-6:48px`；卡片内边距 16-20px、面板间距 16px、区块间距 24/32px。栅格：`.acards` 用 `grid repeat(auto-fit, minmax(220px,1fr))`，容器 max-width 1440px。

### 2.4 圆角/阴影/质感

- 圆角：面板 14px、内嵌件 8px、胶囊 999px（内外层差，避免千篇一律）
- 阴影：深色 = 同底色黑阴影 `0 16px 40px -20px rgba(0,0,0,.6)` + 1px 顶部内高光；浅色 = `0 1px 3px rgba(15,23,42,.06)` + 细边框
- 质感：body 叠加 **SVG 网格纹理**（1px 线，rgba 3%，终端纸感）+ 顶部径向辉光（绿/蓝 4-6%）；噪点保留（5%）

---

## 3. 布局结构

```
<body data-theme="dark">
├─ <header>  sticky · 毛玻璃 slate
│   ├─ .hdr-row
│   │   ├─ .brand     [脉冲雷达点] A股证券化率 · 估值雷达终端
│   │   │              DATA 2026-08-01 ─ 全市场 109.78 万亿 (LED 状态行)
│   │   └─ .hdr-actions
│   │       ├─ .tab-bar  [📈 图表] [📊 分析]   ← SVG 图标，无 emoji
│   │       └─ .theme-btn  ☀/🌙 SVG
│   └─ .statbar   最新值 | 可视范围(日期×2+应用+快捷) | 范围最高 | 范围最低
│                  → 等宽数字、label 大写追踪、hover 高亮
├─ <main class="page-wrap">  max-width 1440
│   ├─ #page-chart
│   │   ├─ .panel.chart-panel  顶部细高光线 + LIVE 徽标
│   │   │   └─ #chart  (ECharts)
│   │   ├─ .legend  图例说明（图标化，色点+等宽）
│   ├─ #page-analysis
│   │   ├─ .acards  4 状态卡（当前值/分位/顶区/底区）
│   │   ├─ .panel   #chart-analysis + 预测虚线
│   │   ├─ .legend
│   │   ├─ .guide 🔮牛熊预测   ← SVG 图标 + 区块色条
│   │   ├─ .guide 📖图形解读
│   │   └─ .guide 🔔牛熊信号检测（工具栏+横幅+三窗口卡）
└─ <script>  (逻辑零改动)
```

**结构与上一版差异**：header 拆成品牌行 + 统计条两层；所有面板统一 `.panel` 样式；图标 emoji → 内联 SVG；`#page-*` / 全部 JS 依赖 ID 原样保留。

---

## 4. 组件设计

| 组件 | 设计 |
|------|------|
| **品牌区** | 12px 圆角方块 logo（绿→蓝渐变 + 呼吸光晕）+ 标题 20px/700 + 状态行 11px 等宽 `DATA 2026-08-01 · 全市场 109.78万亿`，前置 6px 绿色 LED 点（pulse 动画） |
| **Tab 切换** | 胶囊容器（`--surface` 底 + 细边框），激活项 `--accent` 绿底白字 + 投影；**SVG 线形图标**（chart-line / chart-bars），16px/1.5 描边统一 |
| **主题按钮** | 34×30 方形，sun/moon SVG 切换，hover 边框变绿 |
| **统计条** | label 11px 大写 +0.08em 弱灰；value 24px Fira Code 600 等宽；hover 值色变绿；分隔用虚线 |
| **范围控件** | 日期输入深色底（`color-scheme:dark`）+ 聚焦绿环；快捷按钮胶囊、激活绿底；应用按钮绿渐变 + active 下压 |
| **状态卡(.acard)** | 左上角 3px 色条（绿=当前值/底区、红=顶区、蓝=分位）+ label/value/asub 层级；hover 边框提亮 + 1px 上浮 |
| **信号横幅** | 左侧 4px 语义色条 + 底纹渐变 + 5 点阵（点阵尺寸 12px，空点为 slate-700）；无信号态用中性面 |
| **三窗口卡片** | 居中布局，P 分位大数字等宽 + 趋势箭头 SVG（↑↓→ 用 SVG 而非字符） |
| **图例(.legend)** | 色点(8px 圆)+等宽数字说明，行距 2，弱灰 |
| **解读/预测卡片(.guide)** | 标题行 = SVG 图标 + 14px/600；正文 13px/1.9 `--text-2`；关键数字 `<b>` 等宽；列表紧凑 |

---

## 5. 图表视觉（ECharts 终端化）

| 元素 | 深色 | 浅色 | 说明 |
|------|------|------|------|
| 主曲线 证券化率 | `#38BDF8` 2px | `#0284C7` 2px | 渐变填充 20%→0 |
| 总市值（右轴） | `#F59E0B` 1.5px | `#D97706` | 填充 14% |
| 趋势线 率/市值 | `#F87171` / `#A78BFA` | `#DC2626` / `#7C3AED` | 虚线 2px |
| 估值三区 | 绿 `rgba(34,197,94,.16)` / 蓝 `rgba(56,189,248,.10)` / 红 `rgba(239,68,68,.16)` | 对应 .12/.08/.12 | 色带提亮、深色下可见 |
| 牛熊信号区 | `rgba(34,197,94,.22)` / `rgba(239,68,68,.22)` | .14 系 | 同上 |
| 牛熊标记 | 底 `#22C55E` / 顶 `#EF4444` | 同（浅色用 #16A34A/#DC2626） | markPoint 色改为 TC 引用 |
| 参考线 100/75 | `#475569` 虚线 | `#CBD5E1` | label 弱灰 |
| 坐标轴 | label `#94A3B8` Fira Code；分割线 `rgba(148,163,184,.07)` | label `#475569` | 细网格 |
| Tooltip | 面板 `#0F172A` 97% + 细边框 + 等宽数字 + 系列色点 | 白 98% | 终端卡片风 |
| dataZoom | 滑块条 22px，handle 绿 `#22C55E`，填充 `rgba(34,197,94,.14)` | 对应浅色 | 发光 handle |
| 预测虚线(分析页) | 顶区 `#EF4444` / 底区 `#22C55E` 虚线 / 极端 164 点线 | 对应深色值 | 保持原逻辑 |
| 预测转折 ◆ | `#F59E0B` 菱形 + 白描边 | `#D97706` | 不变 |

全部颜色入 `THEMES` 对象（已有结构），深/浅两套完整映射。

---

## 6. 动效（150-300ms · 尊重 reduced-motion）

| 位置 | 效果 |
|------|------|
| 页面加载 | 面板/统计条 staggered fade-up（delay 60ms 阶梯，240ms ease-out） |
| 品牌 LED | 呼吸 pulse（opacity/scale 循环 2.4s，仅深色） |
| Tab/按钮 | hover 边框/亮度变化 180ms；active translateY(1px)+scale(.98) |
| 主题切换 | body/面板 `background-color` 300ms 过渡（仅颜色，性能安全） |
| 统计值 hover | 颜色 150ms 变绿 |
| 图表内 | ECharts 自带动画保持（animation 已关，避免干扰缩放） |

`@media (prefers-reduced-motion: reduce)`：全部动画/过渡禁用。

---

## 7. 响应式 & 无障碍

- 断点：375 / 768 / 1024 / 1440（容器 1440 居中，两侧留白随屏宽）
- ≤768px：品牌行换行、统计条 2 列 grid、tab 保持可点（≥44px 目标）、图例折行
- 对比度：主文本 ≥4.5:1、次文本 ≥3:1（双主题已按 slate 标定）
- `:focus-visible` 绿色环；`cursor:pointer` 全覆盖
- 语义化：`<header>/<main>/<section>`；按钮/输入均有 `aria-label`/`title`
- 图标全 SVG 内联（无 emoji 结构图标），描边 1.5px 统一
- 字体 `font-display:swap`，CDN 失败回退系统栈不阻塞

---

## 8. 功能保留映射表（核对项）

| 功能 | 保留方式 |
|------|---------|
| 双页 tab 切换 | `#btn-chart/#btn-analysis/#page-chart/#page-analysis` ID 原样 |
| 双图缩放双向联动 | `chart`/`chart-analysis` 实例 + `syncZoomTo` 逻辑不动 |
| 动态对数正态三区 | `zoneMarkArea` 色值换 TC（逻辑不变） |
| 可见范围趋势线 | 不动 |
| 总市值叠加（图例开关） | 不动（legend data/selected 原样） |
| 牛熊信号区间开关 | `signalZone` series 原样，色值换 TC |
| 预测转折点/牛熊标注 | markPoint 逻辑不动，颜色入 TC |
| 顶部统计卡/范围控件/快捷按钮 | ID `stLatest/stMax/stMin/rangeFrom/rangeTo/btnApplyRange/.qbtn` 原样 |
| 分析页 4 状态卡 + 预测虚线 + Y 轴约束 | ID `an-*` 原样，`analysisYMinFloor/Ceil` 逻辑不动 |
| 牛熊信号检测（基准日期/三窗口/打分） | `signalResult`/`.sig-card`/`.sig-banner` 类原样 |
| 深浅主题切换 + localStorage | 现有 `THEMES/applyTheme` 结构扩展色值 |
| ECharts CDN 三源降级 | 不动 |
| 图形解读/预测说明文本 | 内容保留，图标换 SVG |

---

## 9. 实施步骤（后续执行时）

1. 替换 `<style>` 块：新 token 体系 + 组件样式 + 动效 + 响应式
2. 重排 header/statbar/面板 HTML 外壳（ID/类名全部保留，新增 `.hdr-row/.statbar/.panel` 等）
3. emoji → 内联 SVG（tab/卡片标题/横幅/工具栏）
4. 扩展 `THEMES`：新增 curve/mark/zone 色值映射，替换 buildBaseOption 引用
5. `python main.py --html-only` 重新生成
6. CloakBrowser 回归：功能锚点 + 双主题交互 + 缩放联动 + 无 JS 错误
