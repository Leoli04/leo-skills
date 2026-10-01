# Chinese Stock Market Color Conventions

## Core Rule

Chinese stock market convention is the **opposite** of US/European convention:
- **涨 (price increase) = Red (红色)**
- **跌 (price decrease) = Green (绿色)**

This applies universally across all charts, metric cards, and text formatting in the report.

## CSS Color Palette

### Primary Colors
| Usage | Hex Code | CSS Class Suffix |
|-------|----------|-----------------|
| Price up / Bullish / Positive change | `#e94560` | `.up`, `.pos` |
| Price down / Bearish / Negative change | `#00c853` | `.down`, `.neg` |
| Neutral / Informational | `#2196f3` | `.neutral` |
| Warning / Caution | `#ff9800` | (inline style) |
| Highlight / Gold | `#ffd700` | (inline style) |

### Metric Card Classes
- `.m-val.up` → `color: #e94560` (for "涨" or positive absolute values)
- `.m-val.down` → `color: #00c853` (for "跌" or negative absolute values)
- `.m-val.neutral` → `color: #2196f3` (for informational metrics)
- `.m-change.pos` → `color: #e94560` (↑ arrows in change text)
- `.m-change.neg` → `color: #00c853` (↓ arrows in change text)
- `.m-change.neutral` → `color: #888`

### Tag Colors (Sentiment News Tags)
| Tag | CSS Class | Background | Text Color |
|-----|-----------|------------|------------|
| 负面 | `.tag-red` | `#fde8ea` | `#e94560` |
| 正面 | `.tag-green` | `#e8f5e9` | `#2e7d32` |
| 政策/行业 | `.tag-blue` | `#e3f2fd` | `#1565c0` |
| 风险/注意 | `.tag-orange` | `#fff3e0` | `#e65100` |
| 中性/其他 | `.tag-gray` | `#f5f5f5` | `#555` |

### Risk Severity Colors
| Level | CSS Class | Background | Text Color |
|-------|-----------|------------|------------|
| 高风险 | `.risk-high` | `#fde8ea` | `#e94560` |
| 中风险 | `.risk-mid` | `#fff3e0` | `#e65100` |
| 低风险 | `.risk-low` | `#e8f5e9` | `#2e7d32` |

### Chart Color Palette (for multi-series charts)
Use these hex values in order when creating charts with multiple categories/series:
1. `#e94560` (红 — primary)
2. `#2196f3` (蓝 — secondary)
3. `#00c853` (绿 — tertiary)
4. `#ffd700` (金 — quaternary)
5. `#ff9800` (橙 — quinary)
6. `#9c27b0` (紫)
7. `#999` (灰 — "other" category)

## Signal Indicators
- `.signal-buy` → `background: #fde8ea; color: #e94560` (bullish signal)
- `.signal-sell` → `background: #e8f5e9; color: #2e7d32` (bearish signal)
- `.signal-neutral` → `background: #f5f5f5; color: #888` (neutral)

### 方法论 v2.3 组件的语义色

| 组件 | 类 / 用法 | 语义色 |
|---|---|---|
| 第 0 步估值锚定位 | `.anchor-box` | `border-left: #e94560`（红色，全书最强调的一步） |
| 合法尺子标签 | `.allowed-tag` | 绿底 `#e8f5e9` / 深绿 `#2e7d32` |
| 禁用尺子标签 | `.banned-tag` | 红底 `#fde8ea` / 深红 `#c62828` |
| 折现期望价盒 | `.exp-price-box` | 深底 `#1a1a2e`；通过用 `#0be881`（`.ep-pass`），不通过用 `#e94560`（`.ep-fail`），期望价本身用金色 `#ffd700` |
| 自检清单 | `.checklist li` | 默认灰 `☐`；`.ok` 绿 `☑` `#2e7d32`；`.no` 红 `✗` `#e94560` |
| 时间炸弹行 | `.bomb-row` / `.bomb-date` | 日期用警示红 `#c62828` |
| 四象限图 | `quadrantChart` | 本公司点 `#e94560`；真便宜区绿；盈利在顶橙；盈利崩塌红；双高区灰 |
| 一维横向定位图（四象限降级形态） | `quadrantChart`（`indexAxis:'y'` bar） | 亏损公司红 `#e94560`；盈利公司蓝 `#2196f3`；按 PB 升序排列 |
| 资金进出趋势（日度） | `moneyFlowChart` | 净流入柱红 `rgba(233,69,96,0.75)`；净流出柱绿 `rgba(0,200,83,0.75)`；主力线橙 `#ff9800`；股价线灰虚线 `#9e9e9e` |
| 周度资金净流入 | `moneyFlowWeeklyChart` | 同「净流入红 / 净流出绿」；被截断的极端柱用描边虚线 `rgba(0,200,83,0.35)` + `#00c853` 边框 |
| 资金流数值色 | `.mf-pos` / `.mf-neg` | 净流入 `#c62828`；净流出 `#2e7d32`（**A 股约定：红=流入，绿=流出**） |
| 通道分流标签 | `.path-chain .pc-step` / `.pc-end` | 步骤灰底 `#f8f8fc`；结论落点红 `#c62828` |

**图表轴必须全部可观测（硬约束）**：
- 四象限图的两根轴都必须有**真实可得的数值**。任一根轴不可用（如亏损标的的 PE 轴）时，**禁止用「同业（示意）」等编造坐标凑图**——直接把该图降级为一维横向柱图（只画可用的那根轴），并在图注里说明「XX 轴在本例不可用，故降级为一维」。
- 降级图的排序、配色、数值必须全部来自真实抓取数据；亏损/盈利等定性状态用红/蓝区分，让读者一眼看出「低估值是结果还是机会」。
- 同类问题：饼图/甜甜圈若与另一张柱图同源数据（如「行业地位」画成业务板块占比），属于**同源重复渲染**，必须改画真正不同的信息（行业地位 → 赛道相对位势雷达 + 可比公司对照表）。

**语义约定**：
- 「有效阻力 / 买入门槛 / 破位」用红系（`#c62828` / `#e94560`）
- 「支撑位 / 通过 / 安全边际」用绿系（`#2e7d32` / `#00c853`）
- 「期望价 / 关键结论」用金色（`#ffd700`）—— 注意是金色，不是红色
- 四类退出判据：估值到位 / 逻辑破坏用 `risk-high`，价格破位 / 时间止损用 `risk-mid`

---

## 模板技术约定（踩坑记录，改模板前必读）

### 1. 图例必须写 `usePointStyle`，否则虚线会横穿文字

Chart.js 图例默认用**字体度量**决定图例框高度（`font.lineHeight` 默认 `1.2`）。带 `borderDash` 的数据集，虚线会横穿整个框高，在文字上呈现**删除线**观感。

```js
// ✗ 错误：虚线穿过文字
labels: { color: '#666', font: { size: 11 }, boxWidth: 12 }

// ✓ 正确：图例改用几何线型绘制，高度与字体度量解耦
labels: { color: '#666', font: { size: 11 }, boxWidth: 12, usePointStyle: true, pointStyle: 'line' }
```

**注意**：只加 `font.lineHeight: 1` **不能解决**（框高缩到 11px 仍会穿字），实测无效。必须用 `usePointStyle`。

### 2. 虚线必须用自定义 plugin，不能写 `plugins.annotation`

模板**只引入 `chart.umd.js`，未引入 chartjs-plugin-annotation**。写 `plugins.annotation.annotations{...}` 会被 Chart.js 静默忽略 —— 配置看着对，线却从不出现。

```js
// ✓ 自定义 plugin 画水平虚线
plugins: [{
  id: 'myLines',
  afterDatasetsDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = '#e94560';
    const py = scales.y.getPixelForValue(6.7);
    if (py >= chartArea.top && py <= chartArea.bottom) {
      ctx.beginPath();
      ctx.moveTo(chartArea.left, py);
      ctx.lineTo(chartArea.right, py);
      ctx.stroke();
    }
    ctx.restore();
  }
}]
```

### 3. scriptable 选项的回调**禁止返回 `undefined`** —— 会在渲染帧抛 TypeError，图只剩轴没有数据

Chart.js 的 scriptable option（`borderDash` / `backgroundColor` 等写成函数）**返回值就是最终值，不会回退到静态默认值**。回调返回 `undefined` 时，绘制阶段 `ctx.setLineDash(undefined)` 抛 `TypeError: Failed to execute 'setLineDash'`——该帧 datasets 绘制循环中断，**画面停留在「坐标轴 + 图例已画、数据没画」**，且每帧重绘都崩在同一位置，表现为永久性空图。

```js
// ✗ 错误：2026E 虚线段之后想用 undefined 表示「无虚线」
borderDash: ctx => ctx.dataIndex >= 3 ? [6,4] : undefined

// ✓ 正确：空数组 = 实线（setLineDash([]) 合法）
borderDash: ctx => ctx.dataIndex >= 3 ? [6,4] : []
```

**排查特征**：轴和图例在、数据全无；DevTools console 有 `setLineDash` TypeError（注意 playwright 的 `pageerror` 能抓到，console.error 不一定）。
**真实事故**：武商集团报告 ② 财务节 revenueChart 的归母 line dataset 用了 `: undefined`，用户看到「营收图无柱无线、旁边 marginChart 空白」。

### 4. 同一份报告内，情景数字只能有一套

期望价盒、胜率盒、胜率×赔率散点图**必须共用同一组三情景价格与概率**。

⚠️ **历史上出过的事故**：期望价盒用 4.50/7.80/10.20、胜率盒却用 8.00/10.00/13.00 —— 同一页面两套情景数据。此时胜率到底该填 75% 还是 30%，取决于**用的是哪一组**，任何单看一处的判断都会出错。

**改动任一情景数字时，必须同步四处**：期望价盒、胜率指标卡、胜率情景表、散点图坐标。

**校验方法**：把四处的情景价与概率抄到一行，确认完全一致，再用同一门槛（现价 × 1.15）重算胜率。

⚠️ **不要拿 `methodology.md` 的演示案例数字当模板答案。** 方法论里那组（8.00/10.50/13.00 @ 现价 10.00）是**通用演示**，结论 30% 只对那组数字成立。模板示例是另一家公司（4.50/7.80/10.20 @ 现价 5.02），胜率 75%。**套错数字会把结论整个反过来。**

### 5. 模板内容替换清单

模板以「分众传媒」为示例填充。复制后**必须整体替换**：公司名/代码、价格与市值、全部财务数字、护城河条目与分数、竞争对手名与对比表、新闻条目、风险条目、宏观数字、情景价格与概率、胜率与赔率、验证点与退出价位、综合评分、页脚日期。

**交付前用 `grep -c "分众\|新潮"` 应返回 0**（示例公司名残留检查）。

### 6. tab 切换的 div 配对 —— 错的不是「总数」，是「层级归属」

模板的 tab 机制是：

```css
.section { display: none; }
.section.active { display: block; }
```

`showSection()` 只切换 `.section` 上的 `active` 类。所有 `.section` 必须是 `<div class="content">` 的**直接子元素**（平级）。一旦某个 `</div>` 错位，会同时引发两种症状：

| 错位方向 | 症状 |
|---|---|
| `.content` 被提前闭合 | 后面的 section 掉到 `<body>` 下（失去 padding，视觉错乱） |
| 某个 section 没闭合 | **后续所有 section 被嵌进它内部** → 父级 `display:none` 时，子 section 的 `offsetHeight` 全为 0 → **点开是空白页** |

**关键：看「div 总数平衡」会漏判。** 一多一少会互相抵消成 `607/607`，但结构是错的。必须同时查三项：

```python
# ① 总数与终值
depth = 0
for ln in lines:
    depth += len(re.findall(r'<div\b', ln)) - len(re.findall(r'</div>', ln))
assert depth == 0            # 终值必须为 0

# ② 逐行深度是否在预期位置归零（错位点会提前或推迟归零）
# ③ 层级归属（最关键）—— 在浏览器里查每个 section 的 parentElement
```

```javascript
document.querySelectorAll('.section').forEach(s => {
  const p = s.parentElement;
  console.log(s.id, '<-', p.tagName + '.' + p.className);
  // 期望：全部是 DIV.content，且彼此平级
});
```

**再验渲染高度**（比可见性更严格，能抓出「可见但零高度」）：

```javascript
btns.forEach(b => {
  b.click();
  const s = [...document.querySelectorAll('.section')].find(x => getComputedStyle(x).display !== 'none');
  console.log(b.textContent, 'h=' + s.offsetHeight, 'textLen=' + s.innerText.length);
  // h=0 或 textLen 异常偏大（吞了兄弟 section 的文本）都是错位信号
});
```

**根因记录（真实版）**：模板升级过程中，③ 技术分析结尾多了一个 `</div>`，把 `.content` 容器提前关掉 —— 于是 ④⑤⑥ 掉出 `.content`，⑥ 的收尾标签又正好顶替了 `.content` 的位置，导致 ⑦–⑪ 五个 section 被嵌进 `#valuation` 内部。因为 `#valuation` 默认 `display:none`，⑦–⑪ 的 `offsetHeight` 全是 0，**用户看到的就是「⑦ 到 ⑪ 没有任何数据」**。

而第一轮排查时我只做了「div 总数平衡」检查（当时确实是 607/607），所以误判成「⑥ 里多一个 `</div>`」，还错误地在 ⑪ 末尾补了一个闭合 —— 等于用错误补错误，把并列关系坐实成了嵌套。**真正的解法是删掉 ③ 后面那个多余的 `</div>`，再让 ⑥ 正常闭合、`.content` 在最后闭合。**

**教训：改 600+ div 的单文件模板，不要只做计数校验。必须查层级归属 + 渲染高度。**

### 6. 批量改数字/文案时，「同一数值有几种写法」必须先穷举

做过一次全量审核，把 `2.6 : 1` 改成 `1.4 : 1` 时用了带空格的精确匹配 `2.6 : 1`，结果漏掉了没有空格的 `2.6:1` —— 同一个页面于是同时出现 1.4 和 2.6 两个赔率。

**规则**：替换一个数值前，先把它的**所有排版变体**列出来再搜：

```bash
# ✗ 会漏
grep -n "2.6 : 1" template.html

# ✓ 用宽松模式，再人工确认命中项
grep -nE "2\.6\s*:" template.html
```

同理适用于：`27亿` / `27.0亿`、`21.52` / `21.53`（四舍五入差异）、`25.29` / `25.3` / `25`。

**另一类高发问题：标题说 N 项，正文只有 N-2 项。** 典型事故：⑪自检清单标题改成「38 项」，正文 `<li>` 却仍是 30 条（新增项只改了标题没补正文）。**改标题计数时，必须同时数正文实际条目**，两边都要动：

```python
# 数标题声称的 vs 实际渲染的
declared = re.search(r'·\s*(\d+)\s*项', title_line).group(1)
actual   = sum(1 for l in section_lines if '<li' in l)
assert declared == actual, f'{declared} != {actual}'
```

同理，`redlines.md` 的「43 条红线 / 26 个陷阱 / 38 项自检」三个数字也必须与实际条目数逐一核对（红线数 `<ol>` 编号项、陷阱数表格 body 行、自检数 `- [ ]` 项）。**跨文件引用时还要注意口径：方法论文档正文是 41/24/34，skill 的 `redlines.md` 在此基础上自行增补，为 43/26/38 —— 两套数字各自自洽，不要混用。**

### 7. 同一指标在页面多处出现时，须逐个对齐

本次审核抓出的不一致：

| 指标 | 冲突写法 | 统一为 |
|---|---|---|
| 扣非净利润 | `27亿` / `27.2亿` | 27.2 亿 |
| 赔率 R/R | `2.6 : 1` / `1.4 : 1` | 1.4 : 1 |
| 减值金额 | `21.52` / `21.53` | 21.52 亿 |
| 减值+亏损合计 | `25` / `25.29` / `25.3` | 25.29 亿 |
| 强阻力位 | `7.17` / `6.40` | 6.40 元 |

**每改一处指标，先在全文件搜该指标的所有出现位置，一次性改完。** 局部改一处等于制造新的不一致。


## Visual Cues
- Bullish conclusion boxes: `border-left: 4px solid #e94560`
- Bearish conclusion boxes: `border-left: 4px solid #00c853`
- Support level boxes: green-tinted background
- Resistance level boxes: red-tinted background
- Current price box: blue-tinted background

## Important
Never swap red/green meanings for Chinese stocks. This applies regardless of what Western financial conventions dictate. If the user explicitly asks for US-style coloring, comply with their request.
