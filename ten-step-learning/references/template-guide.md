# 模板填充规范 · assets/template.html

> 目标:把内容写成 `data.json`(键 = 占位符名,值 = HTML 片段),由 `scripts/render.py` 渲染进 `assets/template.html`。**只填内容,不改 CSS / 侧边栏 / JS**。
> 所有片段必须复用模板已定义的组件类(下面给出示例),不要新造样式、不要写内联 `style` 去改颜色/圆角/阴影。
>
> **不要在值里写 `{{...}}`**:提示词原文里的主题/角色占位写法,必须先替换成真实值再放进 data。含双花括号的值会被渲染器当成"没替换干净"而报警(它无法区分"漏填"和"内容里本来就有")。
>
> **配色铁律:`data.json` 里一个 `#hex` 都不要写。** 模板是**双主题**(默认深色 + 可切浅色),颜色全在语义令牌里:
> 你在内容里写死 `#043f2e`,浅色下正常,深色下就是"深绿字压近黑底"——整块隐形。
>
> | 你要的效果 | 用什么 |
> |---|---|
> | 普通文字 / 强调文字 | 不写颜色(继承),或 `.prose` 内用 `<strong>` |
> | 次要说明、标签小标题 | `.persona__k` / `.res__k` / `.rung__lv` / `.viz__cap` / `.upstream` |
> | 强调色块 | `.tag`(亮绿底深字)/ `.tag--sage`(浅底)/ `.tag--forest`(深色强调底) |
> | 深色/深绿大块 | `.takeaways`(学习结果)/ `.card--forest` |
> | SVG 图形 | 只用 `.viz-node` / `.viz-accent` / `.viz-ink` / `.viz-node-ink` / `.viz-accent-ink` / `.viz-edge`(见下) |
> | 一个 `<i>` 图例线 | `class="k-conflict"` / `k-consensus` / `k-edge` |
>
> **禁止**:`style="color:..."`、`style="background:..."`、SVG 的 `fill="#..."` / `stroke="#..."`。
> `style="margin-top:16px"` 这类纯间距可以(它不参与配色)。
> 渲染器会扫 `*_VIZ` 与 `LOOP_DIAGRAM` 里的写死颜色并**直接报错**。
>
> 视觉约束不变:无阴影;圆角只 4px 或 16px;标题字号 ≥36px 才用衬线。

## 占位符总清单

| 占位符(data 键) | 位置 | 填什么 |
|---|---|---|
| `TOPIC` | title / 侧栏 / 总览大标题(**多处,全部替换**) | 主题名(短) |
| `METHOD_INTRO` | 总览 lead | 2–4 句:这套十步法是什么、这次要带你把该主题学成什么样 |
| `STEP_MAP` | 总览 | 10 张 `.stepmap` 卡(见下) |
| `STEP_N_TITLE` | 第 N 步大标题 | 该步针对本主题的一句话标题(可含主题词) |
| `STEP_N_PURPOSE` | 第 N 步 lead | 1–2 句:这一步在干嘛、为什么重要(取自原文该步的旁白) |
| `STEP_N_TAKEAWAYS` | 第 N 步·学习结果 | `<ul><li>` 3–5 条提炼结论(见下) |
| `STEP_N_VIZ` | 第 N 步·可视化槽 | 仅 1/2/6 步填;其余步**留空字符串** |
| `STEP_N_OUTPUT` | 第 N 步·输出面板 | 该步完整原始产物,`.prose` 排版(第 5/8 步用专用组件) |
| `STEP_N_INPUT` | 第 N 步·输入面板 | `.upstream` 上游标签 + `.prompt-block` 提示词 |
| `CLOSING_INTRO` | 收尾 lead | 2–3 句:十步连成一条线的复述(开局→吃透→检验→压缩) |
| `LOOP_DIAGRAM` | 收尾 | 环形闭环 SVG(见下) |
| `CLOSING_DELIVERABLES` | 收尾 forest 卡 | `.prose`:最终可带走的交付物清单(简报/阶梯/速查表各一句) |

> 共 66 个占位符。**不要手工数**:`python scripts/render.py --data data.json --check` 会直接告诉你缺哪个、多哪个。

---

## 通用组件片段

### 学习结果 `STEP_N_TAKEAWAYS`
```html
<ul>
  <li><strong>连对手都承认的:</strong> ……(一句结论)</li>
  <li>……</li>
  <li>……</li>
</ul>
```

### 输入面板 `STEP_N_INPUT`
```html
<div class="upstream">消费上游:<span class="tag tag--sage">第1步·五视角</span><span class="tag tag--sage">第2步·矛盾图谱</span></div>
<div class="prompt-block">这里粘该步实际使用的提示词(主题与角色已替换成真实值,原文的占位写法不要原样保留)。</div>
```
> 第 8、9 步的输入面板末尾加一句:`<p class="res__v" style="margin-top:12px">注:原文该步为一问一答的交互式版本,此处改为一次性生成可复用材料。</p>`

### 输出面板 `STEP_N_OUTPUT`（通用步用 `.prose`）
```html
<div class="prose">
  <h4>小节标题</h4>
  <p>段落……</p>
  <ul><li>要点……</li></ul>
</div>
```

### 总览步骤地图 `STEP_MAP`（10 张卡）
```html
<a href="#view-1" data-view="view-1"><div class="stepmap__n">01</div><div class="stepmap__t">五视角 STORM</div><div class="stepmap__d">让 5 种人吵一架</div></a>
<!-- …一直到 view-10；data-view 必须与目标 section id 一致，JS 才会切换 -->
```

---

## 专用组件

### 第 1 步 · 五视角 persona 卡 → `STEP_1_VIZ`
```html
<div class="persona-grid">
  <div class="persona">
    <div class="persona__role">实践者</div>
    <div class="persona__tag">每天跟这东西打交道的人</div>
    <div class="persona__block"><div class="persona__k">核心立场</div><div class="persona__v">两句话……</div></div>
    <div class="persona__block"><div class="persona__k">最强证据</div><div class="persona__v">真实证据/来源……</div></div>
    <div class="persona__insight"><div class="persona__k">只有他会告诉你</div>独有洞察……</div>
  </div>
  <!-- 学者 / 怀疑者 / 经济学家 / 历史学家 共 5 张 -->
</div>
```
> 第 1 步的 `STEP_1_OUTPUT` 可放更细的展开叙述;persona 卡负责一眼看全。
> 五张卡在 1000px 容器里会排成 3+2,属正常 `auto-fit` 行为,不要为了让它们凑一行而改栅格。

### 第 2 步 · 矛盾图谱 SVG → `STEP_2_VIZ`
5 个视角作节点摆成五边形,**冲突用红线、共识用绿线**连接,盲区在底部标注。用 viewBox 保证自适应。

**节点坐标(实测可用,直接抄)**:viewBox `0 0 640 470`;五点 `(320,70) (500,200) (430,380) (210,380) (140,200)`;半径 `34`。
盲区文字基线放 `y=452` —— 节点下沿是 `cy+34`,标注必须比它再低约 38px,否则会压在圆上(这个坑踩过)。

```html
<div class="viz">
  <svg viewBox="0 0 640 470" role="img" aria-label="矛盾图谱">
    <!-- 冲突边:只连真正对立的两方 -->
    <line x1="320" y1="70" x2="210" y2="380" class="viz-edge viz-edge--conflict" stroke-width="2"/>
    <!-- 共识边:连全体承认的两方 -->
    <line x1="500" y1="200" x2="210" y2="380" class="viz-edge viz-edge--consensus" stroke-width="2" stroke-dasharray="5 5"/>
    <!-- 节点:圆 + 文字(类名决定配色,不许写 fill) -->
    <g><circle cx="320" cy="70" r="34" class="viz-node"/><text x="320" y="74" text-anchor="middle" class="viz-node-ink" font-size="13" font-family="Inter">实践者</text></g>
    <!-- …其余 4 个节点,按上面的坐标摆… -->
    <text x="320" y="452" text-anchor="middle" class="viz-ink" font-size="12" font-family="Inter">盲区:没有任何视角提到 ……</text>
  </svg>
  <div class="legend">
    <span><i class="k-conflict"></i>直接冲突</span>
    <span><i class="k-consensus"></i>全体共识</span>
  </div>
  <div class="viz__cap">图注:一句话说清最大的那条冲突,以及"一旦回答就能化解它"的关键问题。</div>
</div>
```
> 文字在圆里居中:基线取 `cy + 4`(中文字形重心偏上),`text-anchor="middle"`。

### 第 5 步 · 资源卡 → `STEP_5_OUTPUT`
```html
<div class="res">
  <div class="res__head"><span class="res__name">资源名(真实)</span><span class="tag tag--pill tag--sage">书/课/社区</span></div>
  <div class="res__meta"><span class="tag tag--pill">约 3 小时</span><span class="tag tag--pill tag--sage">读 / 看 / 练</span></div>
  <div class="res__k">为什么比同类强</div><div class="res__v">……</div>
  <div class="res__k">该拿走的一个关键点</div><div class="res__v">……</div>
</div>
<!-- 5 张资源卡后,追加"被高估的坑"与"一周路径" -->
<div class="card" style="margin-top:16px"><div class="prose"><h4>被高估的坑</h4><ul><li>……</li></ul><h4>一周学习路径</h4><ol><li>第 1-2 天……</li></ol></div></div>
```

### 第 6 步 · 学习阶梯 → `STEP_6_VIZ`（VIZ 放阶梯；8 要素明细放 OUTPUT 的 .prose）
```html
<div class="ladder">
  <div class="rung"><div class="rung__lv">级别 1 · 完全初学者</div><div class="rung__name">阶段名</div><div class="rung__milestone"><strong>里程碑:</strong>能做到……就可进级</div></div>
  <div class="rung"><div class="rung__lv">级别 2 · 基本理解</div>……</div>
  <!-- 5 级,column-reverse 会让级别 5 显示在顶端 -->
</div>
```
> **必须按 1→5 的 DOM 顺序写**(级别 1 在前)。模板用 `column-reverse` 翻转显示,并让第 1 级的宽度是 62%、逐级递增到 98% —— 台阶感来自宽度差,不是靠额外 div 拼的。
> `rung` 是纸面卡(`--surface`)+ 细边,不要改回 `--canvas`(那是 body 背景色,卡片会直接隐形——深浅两套主题下都隐形)。

### 第 8 步 · 题库翻卡 → `STEP_8_OUTPUT`（点开题目才显示答案）
```html
<details class="flash">
  <summary><span class="flash__lv">初级</span><span class="flash__q">题目 1 ……</span><span class="flash__reveal">显示答案 ▾</span></summary>
  <div class="flash__a">
    <div class="persona__k">参考答案(满分长这样)</div><div class="res__v">……</div>
    <div class="rubric"><strong>评分标准:</strong>满分=…… / 及格=…… / 常见薄弱点=……</div>
  </div>
</details>
<!-- 10 题(初3/中3/高2/专家2)。最后 5 道终极挑战题只给题目,不给答案: -->
<div class="card--forest" style="margin-top:16px"><p class="eyebrow">5 道终极挑战(自己想)</p><div class="prose"><ol><li>……</li></ol><p>全部答好 = 达到 ______ 水平。</p></div></div>
```
> 深色卡里的 `.prose` 由 `.card--forest .prose` 自动取高亮文字色,**不要再写内联颜色**——写死了到浅色主题就变成浅字浅底。

### 收尾 · 环形闭环 SVG → `LOOP_DIAGRAM`
四段弧(开局→吃透→检验→压缩)围成一个环,回到起点,体现"一个闭环"。
```html
<svg viewBox="0 0 520 360" role="img" aria-label="学习闭环">
  <circle cx="260" cy="180" r="120" fill="none" class="viz-edge" stroke-width="2"/>
  <!-- 四个阶段节点用 viz-accent(亮绿),文字用 viz-accent-ink:上(260,60) 右(380,180) 下(260,300) 左(140,180) -->
  <g><circle cx="260" cy="60" r="30" class="viz-accent"/><text x="260" y="65" text-anchor="middle" font-size="12" font-family="Inter" class="viz-accent-ink">开局</text></g>
  <!-- 吃透(右)/检验(下)/压缩(左),均匀 4 等分;箭头示意顺时针闭合 -->
  <text x="260" y="185" text-anchor="middle" font-family="Fraunces" font-size="20" class="viz-ink">一个闭环</text>
</svg>
```

---

## 主题与 SVG 类(新增)

**默认深色**:`<html data-theme="dark">` 写在模板标签上,无 JS 也不闪白;右上角 `.theme-btn` 切浅色,选择存 localStorage。你不必管它,只要**不写死颜色**。

**可视化只准用这 6 个类**(模板已定义,深浅两套自动换值):

| 类名 | 用在 | 浅色 | 深色 |
|---|---|---|---|
| `viz-node` | 节点圆/矩形 | 深绿 `#043f2e` | 暗绿 `#1d4031` |
| `viz-node-ink` | 节点内文字 | 纸白 | 浅绿白 |
| `viz-accent` | 强调图形(闭环阶段节点) | 亮绿 `#c8f169` | 亮绿(不变) |
| `viz-accent-ink` | 强调图形内文字 | 近黑 | 近黑 |
| `viz-ink` | 普通 SVG 文字 | `#242423` | 浅灰绿 |
| `viz-edge` | 连线/圆环 | 中绿 | 浅绿 |
| `viz-edge--conflict` / `--consensus` | 加在 `viz-edge` 上 | 红 / 绿 | 提亮后的红 / 绿 |

- 连线写 `<line class="viz-edge viz-edge--conflict" stroke-width="2"/>`,**不要**写 `stroke=`,更不要 `stroke="#..."`。
- 文字默认已是 `viz-ink`(模板有兜底),但节点内文字必须显式 `class="viz-node-ink"`,否则浅色下是深灰字压深绿圆,看不清。
- 确实需要固定颜色(极少数,如图中嵌入品牌色块):在该片段里写 `<!-- theme-fixed -->`,渲染器的配色检查会放行。

## 填充顺序建议(分片,别一次性输出)

一次性输出十步 × 三栏 ≈ 1.5–2 万字,极易被截断,留下半张破损页面。按下面四批写 `data.json`:

1. **总览批**:`TOPIC`、`METHOD_INTRO`、`STEP_MAP`。
2. **第 1–5 步批**:每步 `TITLE`/`PURPOSE`/`TAKEAWAYS`/`OUTPUT`/`INPUT`,第 1、2 步补 `VIZ`。
3. **第 6–10 步批**:同上,第 6 步补 `VIZ`。
4. **收尾批**:`CLOSING_INTRO`、`LOOP_DIAGRAM`、`CLOSING_DELIVERABLES`。

每批写完立刻 `render.py --check`,缺键马上补;四批齐了再正式渲染。渲染后不要再手工改 HTML —— 要改就改 data 重渲染。
