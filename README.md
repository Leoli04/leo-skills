# leo-skills

CodeBuddy 自定义技能（Skills）集合。每个子目录是一个独立的 Skill，包含 `SKILL.md` 描述文件、参考资料和可执行脚本。

## Skills 一览

### 📥 youtube-downloader

YouTube 视频下载工具，基于 yt-dlp。

- **功能**：下载视频（可选画质）、提取音频（mp3）、下载中/英文字幕（支持自动生成字幕）、播放列表批量下载、代理设置、字幕烧录
- **核心脚本**：
  - `scripts/download.py` — 下载视频/音频/字幕
  - `scripts/burn_subs.py` — 将 SRT 字幕硬编码烧录进视频画面（含音频流保留）
  - `scripts/translate_subs.py` — 字幕翻译
  - `scripts/pipeline.py` — 下载→翻译→烧录 一条龙流水线
- **依赖**：Python 3.8+、yt-dlp、yt-dlp-ejs（JS Challenge Solver）、Node.js、ffmpeg（可选，用于烧录/转码）
- **典型用法**：
  ```bash
  python scripts/download.py "<URL>" --subs "en" --auto-subs --proxy http://127.0.0.1:7890
  python scripts/burn_subs.py "video.mp4" --sub "subtitle.en.srt" --lang eng
  ```

### 🔍 stock-screener

A股粗筛器，以 12 条可执行横截面条件从全市场约 5,100 只筛出候选池。**定位是「粗筛」，深度评估交给 `stock-analyzer`。**

- **12 类**：严格前奏 / 质量宽口径 / 成长 / 小盘成长 / 超跌反弹 / 低估值 / 困境反转 / 高股息 / 白马 / 周期底部 / 网格交易 / **周期陷阱（排雷）**
- **网格池特殊**：判据是**箱体形态**（时间序列特征），由 `scripts/box.py` 拉 52 周周K 计算 —— 箱体振幅 12~60%、周收盘穿越中轴 ≥4 次、单边性 <55%。横截面财务条件只做流动性粗筛。
- **触发词**：「帮我筛股票」「有哪些值得看的标的」「筛出候选池」「初筛」「超跌的」「高股息的」「低估值的」等
- **输出**：零依赖单文件 HTML 看板（12 个 tab、A 股红涨绿跌）+ 结构化 JSON
- **核心文件**：
  - `SKILL.md` —12 类判据、与 stock-analyzer 的分工、三个必须知道的局限
  - `scripts/screen.py` — 筛选执行体（幂等，`--refresh` 强制刷新）
  - `scripts/box.py` — 箱体形态计算（网格池专用，可单独跑 `python box.py sh600887`）
  - `scripts/候选池看板.html` — 生成物
  - `scripts/candidates.json` / `industry_cache.json` / `box_cache.json` — 数据与缓存
- **⚠️ 外部依赖**：`westock-tool` 的横截面筛选接口**不在本仓库内**（属 WorkBuddy 插件缓存）。换机器时需设置：

```bash
# 必须先设置环境变量，指向 westock-tool 目录（含 scripts/index.js）
set WESTOCK_TOOL_DIR=<westock-tool 目录>

cd <stock-screener 目录>/scripts
python screen.py --list       # 列出 12 类及判据
python screen.py--refresh     # 全量跑 → 候选池看板.html
python screen.py --type value,dividend   # 只跑指定类型
```

### 📊 stock-analyzer

股票投资全面分析工具，以 A 股通用方法论 v2.3 的 10 步流水线为骨架，生成交互式 HTML 报告。

- **功能**：从**选对估值锚**起步（15 类形态 → 主锚 + 禁用尺子），依次完成七维尽调、估值与赔率（**折现 + 概率加权 + 当前买入胜率**）、前奏态扫描、验证与退出闭环，产出 11 个章节的深度报告；用户提供持仓时追加仓位建议
- **触发词**：「分析XX股票」「XX公司全面分析」「XX股票怎么样」「XX值不值得买」「stock analysis」等
- **输出**：自包含 HTML 文件（Chart.js 图表 + 分页导航 UI）
- **核心文件**：
  - `SKILL.md` — 10 步流水线 + Phase 0–11（**Phase 0a 历史报告检索与评估模式确认** / Phase 0b 口径确认 / **Phase 9.5 报告内容回查** / **Phase 11 观察池台账 + 上传后旧版归档**）
  - `assets/report_template.html` — 生产级 11 节报告模板
  - `assets/verify_report.py` — **报告回查脚本**，自动核验标签配平、版本号、计数、折现/期望价/门槛算术、**三情景股息项**、**跨标的模板污染**、**结论数字跨位置同值**等 30 项
  - `assets/lib_reports.py` — **资料库历史报告检索 / 全量盘查 / 旧版归档**（`scan` 按标的检索历史版本，给出 `NO_HISTORY` / `HISTORY_FOUND` / `MULTI_VERSION`；`audit` 全量盘查，一次列出所有「多版本并存」组与重复标题，给出 `CLEAN` / `NEEDS_ACTION`；`archive` 幂等移入「旧版归档」）
  - `assets/peer_attribution.py` — **同业归因核查**（第 5 步行业横向前必跑）：`python assets/peer_attribution.py 300558 688578`，一次输出单季拆解（营收/归母/扣非，转亏自动标注）/ 三口径利润与非经常性损益 / 主营构成（判「有没有这个靶点的产品」是否等于「是不是赛道代理」）/ 经营评述中「减值·剔除」原文 / 自动判读提示。**防的是「对手失血」被误读成「赛道失速」**——这类错误数字全真、结论方向反，对持仓含义相反（详见 redlines 第 61–66 条）
  - `assets/watchlist/build_watchlist.py` / `render_watchlist.py` — **观察池台账**（Phase 11）：按 manifest 从各报告抽结论字段建 `ledger_final.json`，再渲成自包含 HTML「决策驾驶舱」（可操作性分区 / 与上期比对的变化高亮 / 复核时间轴 / 三档配色）。`overrides.alert` 可给单只标的挂一条**报告出具后的行情更新**琥珀条（典型：跌破报告自己写死的退出价位）：默认**只提示不改数**；经确认后也可把 `px` 一并覆盖为当日收盘、**维护为最新价**（潜在空间与距买点随新价重算，期望价/胜率/判定/报告日期仍保持报告原值）
  - `assets/watchlist/check_ledger_gap.py` — **台账的 audit**（台账漏更新的机器兜底）：把「本地根目录报告代码集」与「实测库端台账 `data-k` 代码集」做差集，输出 `MISSING`（有报告无行）/ `STALE`（台账胜率 ≠ 报告胜率，该行数值停在旧版）/ `EXTRA`，末行给 `LEDGER_GAP_RESULT: CLEAN|NEEDS_ACTION`；`--pull` 先拉最新库端台账。**每轮报告交付收尾必跑，`NEEDS_ACTION` 时不许报完成**。`STALE` 只认胜率——胜率随模型修订变、不随股价变，潜在空间会被「全池换价」按当日收盘重算，拿它判会全表误报
  - `assets/watchlist/check_ledger_skeleton.py` — **台账的骨架体检**（与上一条互补：gap 查「行有没有 / 数对不对」，本脚本查「行之外的一切有没有」）：三组判据 —— core 骨架（`h1` / 四个 `h2` 模块 / `zone zone--` / `WL_MODEL` / `#pxbar` / `qt.gtimg.cn` / `wl-theme`）、smart 组（`inject.js` / `#posSrc` + `data-sp-bindable` + `data-sp-database-id` / `.padd-mini` 的 CSS 与 JS **分开判** / `posMask` / `addRecord` / `fetchAll` / `#view-pos` + `data-v="pos"`）、optional（后加 Tab），末行给 `LEDGER_SKELETON_RESULT: OK|BROKEN`。**为什么需要它**：`render_watchlist.py` 原本只产出「观察池」这一层，智能页面 / 数据表绑定 / ＋加行增强层 / 持仓 Tab 全靠事后补，每次整页重建覆盖上传都会静默吃掉一批（页面看着完全正常，只有点「＋」没反应），而 gap 检查对此完全无感。**2026-11-07 起增强层已固化成 `assets/watchlist/enhance/`（`enh.css` / `enh.js` / `pos_src.html`），渲染器自动拼入**，本脚本转为回归防线。`--stage render` 时 `inject.js` 标 SKIP（平台上传才注入），其余 smart 项一律 PASS 才算过；`--diff <上一版.html>` 直接列出丢了哪几条。**每次改台账后、上传前必跑**
  - `assets/watchlist/enhance/` — 交互增强层三个真源文件。**要改「＋」加行 / 持仓表单 / 数据表绑定行为就改这里**，别再写一次性补丁脚本；`@@ENH_DB_ID@@` 由渲染器 `--database-id` 替换
  - `assets/watchlist/patch_schl_tab.py` — **给台账加「沃尔特施洛斯策略观察」视图**：`--csv` 传施洛斯筛选结果（取 `层级=A`）、`--funnel` 传漏斗各层、`--metrics-date` 传口径日期，已含该视图自动跳过。Tab 数据来自外部筛选结果，故不塞进渲染器。新视图一律 `schl-` 前缀类名，脚本末尾断言不得混入 `data-row` / `zone` / `zcard` / `wl`（混入会把 A 级那几只算进观察池的 KPI 与分区计数）
  - `references/methodology.md` — 方法论全文结构速查
  - `references/redlines.md` — 66 条红线 / 49 个陷阱 / 79 项自检
  - `references/data_pipeline.md` — 实测可用的数据管线接口
  - `references/color_conventions.md` — 配色与结构约定
- **依赖**：数据检索能力；回查脚本需 Python 3

```bash
# 开工前先查资料库有无同标的历史报告（取数之前必跑）
python assets/lib_reports.py scan --manifest <工作目录>/watchlist_manifest.json \
  --code 600066 --name 宇通客车

# 全量盘查：一次列出库里所有「同标的多版本并存」与重复标题
python assets/lib_reports.py audit --manifest <工作目录>/watchlist_manifest.json

# 行业横向之前：核查同业是不是「赛道代理」（三口径利润 / 单季拆解 / 主营构成）
python assets/peer_attribution.py 300558 688578

# 报告生成后回查（交付前必跑）
python assets/verify_report.py "<报告.html>" --skill-dir <stock-analyzer 目录>

# 台账漏项自检（每份报告交付收尾必跑，NEEDS_ACTION 不许报完成）
python assets/watchlist/check_ledger_gap.py --root <工作目录> --pull

# 台账骨架体检（任何改台账动作之后、上传前必跑，BROKEN 不许上传）
python assets/watchlist/check_ledger_skeleton.py --html "<台账.html>" --stage upload
python assets/watchlist/check_ledger_skeleton.py --html "<新版.html>" --diff "<上一版.html>"

# 给台账加「沃尔特施洛斯策略观察」视图（可选；已含则自动跳过）
python assets/watchlist/patch_schl_tab.py --html "<台账.html>" --csv _schl_result.csv \
    --funnel "5927:全 A,167:估值初筛,69:财务六关,38:九关全过" --metrics-date 2026-11-07
```

> `lib_reports.py` 依赖 CodeBuddy 内置 `library` skill 的 `space_api.py`（资料库接口），目录可用 `--lib-dir` 或环境变量 `WORKBUDDY_LIBRARY_DIR` 指定；不接资料库时可跳过 Phase 0a。

### 📊 fund-etf-review

基金/ETF 评估与文档复评技能。两个场景：①评估「基金/ETF 挑选指南」类方法论文档（多轮迭代复评直到定稿）；②评估**具体单只基金**——从查数到落库一条链全通。

- **功能**（单基金评估七步）：
  1. 数字口径复算（费率复利拖累、A/C 类盈亏平衡点等，全部脚本化）
  2. 权威判据完整性（ETF 六项筛选、主动基金四看+硬否决+一触发器、定投纪律）
  3. **替代品对比**：场内 ETF + 场外联接**双通道缺一不可**（联接基金费率须逐只核实、ETF 无联接须明说）
  4. **多维对比**：统一窗口的近 1/3 年收益、年化、最大回撤、波动、Sharpe、Calmar + 前十大持仓重叠度（联接写穿透口径）——只比费率 = 对比不完整
  5. 生成零依赖 HTML 报告（内联 SVG 净值曲线、命名规范、修正声明机制）
  6. 上传资料库（`--node-block-id` 原地覆盖更新）
- **触发词**：「评估基金文档」「已修改，再次评估」（基金/ETF 语境）、「评估场外基金 <代码>」等
- **核心文件**：
  - `SKILL.md` — 首轮五步 + 复评模式 + 评分锚点（85/93/97）+ 数据源降级路径
  - `references/checklist.md` — 权威判据清单（文档必备模块、8 条数字复算锚点、9 条常见易错点）
  - `scripts/verify_math.py` — 复算脚本：`fee-drag`（费率复利 20 年终值差）、`ac-breakeven`（A/C 临界持有期）
- **依赖**：Python 3 标准库（脚本零第三方依赖）；数据源 neodata → 东财天天基金公开接口降级链

```bash
# 费率拖累复算：1.5% vs 0.2%，持有 20 年
python scripts/verify_math.py fee-drag 0.015 0.002 --years 20
# A/C 类盈亏平衡：申购费 0.10% vs 销售服务费 0.20%/年
python scripts/verify_math.py ac-breakeven 0.0010 0.0020 --fees 0.0010,0.0015
```

### 📊 fund-dca-manager

多账户多基金定投的仓位管理与周度执行。与 `fund-etf-review` 分工明确：**review 管「买什么」，本 skill 管「怎么买、买多少、何时卖」**。

- **核心机制**
  1. **统一量纲用估值历史分位**，不用 PE 绝对值——创业板 PE 30 与沪深300 PE 13 不可比，只能比各自在历史中的位置
  2. **双层决策**：单只按分位落档算理论投入额；账户层在预算不足时按分位从低到高分配，最贵的先砍
  3. **单只限额是可选约束，默认不设**：用户给的金额通常是**当前市值**，不是「计划投入总额度」，两者不能混用——把市值当额度会算出「已用 91%、快没钱了」这种虚构结论。所以 `pool` 默认不填，周投额只由档位系数与账户预算决定；只有用户明确说「这只最多再投 X」时才填，填了才按 天花板 = pool × 档位比例 截断（只占新增额度，不占历史持仓，避免大额存量的老基金一接入就被判停投）
  4. **只给档位，不给金额**：用户要的是「这只贵还是便宜、该不该加」，不是「这只投 100 还是 200」。金额牵涉现金流、平台扣款设置、心理承受度，脚本没有这些信息，给出具体数字等于把不确定性包装成建议。所以默认只输出**档位表**（PE / PE分位 / PB分位 / 档位 / 较上次 / 备注），加 `--amounts` 才折算理论额。**档位变化必须显式给出**：表格有「较上次」列 + 单独汇总段（`↑` 变便宜可加码 / `↓` 变贵收紧），基线取**上一份不同 ISO 周的快照**——同周重跑往往是改了规则，拿它当「档位变化」会把规则调整误报成市场变化。逐只建议写「C 档（0.5×）减速维持」，不写「投 50 元/周」。
  5. **清仓重开要标记**：`funds[].reopen` 记「清仓后重新开仓」，页面对该只打「重开」徽标并提示：成本基准从重开日算起，浮亏不含清仓前那一段，与连续持有的基金横比会低估真实亏损。
  6. **四层止盈**：L1 停投（分位 >47%）→ L2 移动止盈（浮盈 40% 启动，自最高净值回撤 8% 清仓）→ L3 估值极值 → L4 时间复核（满 4 年收益 <10% 暂停复盘，不清仓）
  7. **代理指数显式化**：主动基金没有对应指数估值时，用成分最接近的指数代理，配置里 `index_code` + `index_proxy` 同时写明合同基准与替代理由，代理关系会打进终端输出和 HTML 的「代理指数说明」表——分位可信度打折这件事是可见的，不是暗箱。蛋卷完全没有数据的（北证50、中证金融地产等）走 `manual_percentile` 手工填分位；两者都缺则标「无分位、本周不分配」，不用 PE 绝对值凑数
- **触发词**：「本周定投该投多少」「多只基金怎么分配」「什么时候加仓减仓」「定投止盈规则」「账户预算怎么分」
- **双锚定档：PE 分位定档 + PB 分位做 ±1 档校验**（默认开启）。恒等式 `PE = PB ÷ ROE` 说明 PE 分位偏高有两种成因：净资产没比历史贵、PE 高是盈利在下滑（周期底部，此时停投是错的），或者价格真涨上去了。规则：PB 分位比 PE 分位低 20 个百分点以上 → 上修 1 档；高 20pct 以上 → 下修 1 档；差额不足则不动；**修正上限 ±1 档，绝不越级**。因此 D/E 档不再一律归零，真正 0 元的只剩「两锚共振判贵」，不需要额外设统一保底系数。选 PB 而不是 ERP 做主校验，是因为 PB 与 PE 同接口同窗口同量纲、不依赖外部利率，而 ERP 跨行业不可比（成长股盈利收益率天然低），统一阈值会系统性压制成长与消费类。实测：沪深300 PE 分位 51.6% 判停投，但 PB 分位仅 27.0% → 上修到 C 档；中证500 PE/PB 双 58.6%/58.5% → 维持停投。
- **ERP 与回撤降级为告警**：ERP = 100/PE − 10Y国债 只在页面展示利率环境（`anchors.bond10y` + 数据日，超 90 天提示重取；蛋卷自带的 `bond_yeild` 恒为 0.05 是 2016 年写死的旧值，不可用）。回撤不单独当买入信号——白酒 2026 年跌 36.9%，回撤极深但两锚都不便宜且盈利在下修。**不为「怕等不到低点」而单方面放宽阈值**，要用第二锚承托，不是把线挪走。
- **跨端数据源**：持仓与配置的唯一真源是资料库两张数据表（`基金定投-账户` / `基金定投-持仓`），本地 `holdings.json` / `dca_plan.json` 只是渲染缓存。`scripts/sync_lib.py pull|diff|push` 双向同步，database_id 从配置的 `library.databases` 读。多设备（家里/公司两台电脑、手机网页）改表后，换设备第一件事是 `pull`。**本地不保留表里查不到的业务数据**——「重开 / 不定档 / 手工分位日」已是表内的结构化列，不再靠备注文本推断；`pull` 只更新本地已收录的代码，持仓拆分或新开/清仓后要用 `align_from_table.py` 按表端整表重建，验收标准是 `diff` 输出「待更新 0 行、待新增 0 只」。
- **核心文件**：
  - `SKILL.md` — 与 review 的分工表、三条原则 + 双锚定档规则、Step 0–6 工作流、五条红线
  - `scripts/sync_lib.py` — 资料库数据表 ⇄ 本地 JSON 双向同步（`pull` / `diff` / `push`）
  - `references/tier_rules.md` — 分位档位系数表、双锚校验与实测对照、窗口口径披露、`PB ÷ ROE = PE` 自检、`base_weekly` 定法
  - `references/exit_rules.md` — 四层止盈、8% 回撤回测、场外基金不能做 T 的费率实证、三类大跌事件胜率表
  - `references/accounts.md` — 多账户独立预算、重复暴露检测、季度再平衡
- **依赖**：Python 3 标准库；估值分位来自蛋卷（雪球基金）指数估值接口

```bash
# 1. 算本周该投多少（查分位 → 落档 → 分账户分配预算 → 落盘 md + csv 台账）
python scripts/dca_weekly.py

# 2. 渲染可视化台账（单文件 HTML，零 CDN 零 JS，可打印）
python scripts/render_dca_html.py

# 3. 渲染并发布到资料库（已有节点原地覆盖，不产生重复条目）
python scripts/publish_dca.py
```

> 台账按 ISO 周去重，同一周内重复运行不会重复记账。`actual` 列可手工改成实际成交额，下次运行按它累加。

### 📚 ten-step-learning

把一个陌生主题学到「能与专业人士对谈」，产出**单文件离线学习 HTML**（12 个视图：总览 + 十步 + 收尾闭环）。

- **方法论**：五视角 STORM（多视角取证 → 矛盾图谱 → 综合简报 → 同行评审）之后进入 学习阶梯 → 核心 20% → 题库自测 → 费曼循环 → 一页速查表。**灵魂是逐环交接**：前一步的产物就是后一步的输入，严禁跳序、严禁凭空生成
- **触发词**：「帮我系统学一下 X」「用十步学习法过一遍 X」「把 X 学到能跟人聊」「给我做份学习资料」
- **输入** = 一个主题；开场只问两个快问（当前水平+目标深度、角色/使用场景），之后全自动、零打断
- **输出** = `<主题>-十步学习.html`，单文件、零 CDN、零外链、零 fetch，断网双击即完整渲染
- **默认深色**：右上角按钮切浅色（localStorage 记忆）。配色走语义令牌层（`--canvas` / `--surface` / `--text` / `--accent` / `--rail-*` / `--viz-*`），深浅两套共用同一套组件规则，加主题只改变量块
- **不手工拼 HTML**：模板有 66 个占位符，手填必漏，而漏填的表现是页面某块**静默空白**、不报错。所以内容与外壳分离：先写 `data.json`，再由 `render.py` 校验 → 单遍替换 → 残留/结构/配色自检 → 幂等写出
- **核心文件**：
  - `SKILL.md` — 五阶段流程、三栏语义（输入=提示词 / 输出=原始产物 / 学习结果=提炼结论）、交付前自检
  - `assets/template.html` — 12 视图外壳：侧栏导航 + 组件类 + 主题令牌 + SVG 图形类
  - `assets/fonts-inline.css` — Fraunces + Inter latin 子集 base64（151 KB），保住标题衬线观感，**仍是纯离线**（来源与 OFL 许可见 `assets/FONTS.md`）
  - `scripts/render.py` — 渲染器（纯标准库）：键名拼错直接报错、深色主题壳完好性检查、可视化里写死 `#hex` 直接拦下
  - `scripts/fetch-fonts.mjs` — 重做内联字体（需联网一次，`--force` 覆盖）
  - `references/ten-step-prompts.md` — 十步逐字提示词（含每步「消费哪些上游」与「该提炼什么」）
  - `references/template-guide.md` — 占位符清单 + 组件类写法 + SVG 实测坐标与配色类
- **依赖**：Python 3 标准库；仅重做字体时需要 Node.js
- **联网**：第 1 步（多视角取证）、第 5 步（资源筛选）需要真实检索；有 `web-access` 就用它，否则用环境内置 WebSearch/WebFetch，**两者都没有时必须显式标注「未联网核实」，不许编造来源与资源**

```bash
# 1. 只校验（缺键 / 拼错 / 残留 / 配色问题一次报全，不写文件）
python scripts/render.py --data data.json --check

# 2. 渲染（--fonts 注入内联字体；不写则回退系统字体）
python scripts/render.py --data data.json --fonts
```

### 🎧 podcast-learning-notes

把一期播客（音频 / 小宇宙单集页 / 已有文字稿）整理成「约 1/4 时长能读完」的忠实学习笔记。

- **双模型分工**：转写只管音频 → 文字稿（本地 FunASR 或通义/飞书等云 ASR），写笔记只管文字稿 → 笔记。`source/transcript.md` 已存在就复用，改风格、加内容不重跑转写
- **七道工序**：全文清洗 → 问题骨架 + 切块 → 逐块精读 → 排记录稿 → 三轮审校 → 成稿收口 → 复盘。每道有判据，不靠「感觉差不多了」
- **记录与成稿分开**（本 skill 的核心设计）：`notes.draft.md` 只求不漏、保留全部 `[mm:ss]`；`notes.md` 只做好读，锚点全删并另存 `notes.带时间锚点-溯源版.md`。在同一遍里又加又减，是反复改稿的根因
- **审校分三轮**：结构 / 逻辑保真 / 文字，每轮只看一件事。含限定词抽查（随机 10 处回对干净稿）与归属三分（嘉宾原话 / 主持人引导 / 我的推论）
- **成稿先定体量档位**：速读 3000–4000 / 标准 5000–6500 / 完整 8000–10000 汉字；偏离 20% 必须写明原因
- **核心文件**：
  - `SKILL.md` — 七阶段流程、各阶段判据与已踩过的坑
  - `references/note-template.md` — 成稿结构、取舍规则、段落颗粒度、小标题节奏、自检清单
  - `references/review-and-retrospective.md` — 三轮审校表、失败项、修复记录格式
  - `references/ai-term-corrections.md` — AI 专名同音误转写对照表（这类错误句意通顺，只能主动排查）
  - `references/xiaoyuzhou-source.md` — 小宇宙单集页解析
  - `references/funasr-local.md` / `references/cloud-asr.md` — 两种转写方案与取舍
  - `scripts/download_xiaoyuzhou_episode.py` — 抓音频与 show notes
  - `scripts/transcribe_funasr.py` / `transcribe_cloud_asr.py` — 转写与结果规范化
- **依赖**：Python 3 标准库（云转写走 REST，无需 SDK）；本地 FunASR 需另装 funasr / torch
- **联网**：抓小宇宙页面、云转写需要联网；本地 FunASR 可离线

```bash
# 小宇宙单集页 → 音频 + show notes
python scripts/download_xiaoyuzhou_episode.py <episode-url> \
    --audio-out source/audio.m4a --notes-out source/show-notes.md

# 云端已导出的转写结果 → 统一为 source/transcript.md
python scripts/transcribe_cloud_asr.py normalize --provider tongyi --input-json raw.json
```

## 使用方式

将本仓库克隆后，把对应 skill 目录放入 CodeBuddy 的 skills 目录（`.codebuddy/skills/`），即可通过自然语言触发。

### 两个股票 skill 的关系

它们是**两阶段串联**，不是二选一：

```
全市场 ~5,100 只
      │  stock-screener（粗筛，横截面条件，12 类池）
      ▼
候选池 4~120 只  →  先看「周期陷阱」排雷池，再挑机会
      │  stock-analyzer（深评，10 步流水线，11 节报告）
      ▼
单只标的完整分析报告（含买入价位/ 胜率 / 赔率）
```

只说「帮我筛股票」走第一步；说「分析 XX 股票」走第二步；说「筛完顺便分析一下」则两步连跑。

### 两个基金 skill 的关系

同样是**先后串联**，不是二选一：

```
基金候选  →  fund-etf-review（选品：替代品 / 费率 / 业绩 / 回撤 / 持仓重叠）
                  │  选定载体
                  ▼
            fund-dca-manager（执行：分位落档 / 账户预算分配 / 止盈触发）

说「这只基金怎么样、有没有更便宜的载体」  → review
说「本周定投投多少、三只都在跌先买哪只」  → manager
```

**不要越界**：manager 不做选品评估，review 不做仓位分配。想换标的要先走完 review，不要在定投执行阶段临时换。

## 目录结构

```
leo-skills/
├── stock-screener/        # 股票粗筛技能
│   ├── SKILL.md
│   └── scripts/           # 筛选脚本 + 看板/数据/行业缓存
├── stock-analyzer/        # 股票分析技能
│   ├── SKILL.md
│   ├── assets/            # HTML 报告模板 + 回查脚本
│   └── references/        # 方法论 / 红线 / 数据管线 / 配色
├── fund-etf-review/       # 基金/ETF 评估技能
│   ├── SKILL.md
│   ├── references/        # 权威判据清单
│   └── scripts/           # 费率/临界点复算脚本
├── fund-dca-manager/      # 基金定投仓位管理技能
│   ├── SKILL.md
│   ├── references/        # 档位系数 / 止盈规则 / 多账户
│   └── scripts/           # 周度执行表 / HTML 台账 / 资料库发布
├── ten-step-learning/     # 十步学习法：主题 → 单文件学习 HTML
│   ├── SKILL.md
│   ├── assets/            # HTML 外壳模板 + 内联字体
│   ├── references/        # 十步提示词 / 模板填充规范
│   └── scripts/           # 渲染器 / 字体抓取
├── podcast-learning-notes__skillhub/  # 播客 → 学习笔记（转写 + 七阶段收口）
│   ├── SKILL.md
│   ├── references/        # 笔记模板 / 三轮审校 / 专名纠错 / 转写方案
│   └── scripts/           # 小宇宙抓取 / 本地与云转写
├── youtube-downloader/    # YouTube 下载技能
│   ├── SKILL.md
│   ├── README_zh.md
│   ├── scripts/           # 可执行脚本
│   ├── data/              # 下载记录/系列配置
│   └── references/        # 字幕语言代码等参考
└── .gitignore
```

## 许可

仅供个人学习使用，请遵守 YouTube 服务条款及当地法律。
