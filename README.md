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
- **网格池特殊**：判据是**箱体形态**（时间序列），由  拉 52 周周K 计算 —— 箱体振幅 12~60%、周收盘穿越中轴 ≥4 次、单边性 <55%。横截面财务条件只做流动性粗筛。
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
  - `SKILL.md` — 10 步流水线 + Phase 0–10（含 **Phase 9.5 报告内容回查**）
  - `assets/report_template.html` — 生产级 11 节报告模板
  - `assets/verify_report.py` — **报告回查脚本**，自动核验标签配平、版本号、计数、折现/期望价/门槛算术等 19 项
  - `references/methodology.md` — 方法论全文结构速查
  - `references/redlines.md` — 43 条红线 / 26 个陷阱 / 38 项自检
  - `references/data_pipeline.md` — 实测可用的数据管线接口
  - `references/color_conventions.md` — 配色与结构约定
- **依赖**：数据检索能力；回查脚本需 Python 3

```bash
# 报告生成后回查（交付前必跑）
python assets/verify_report.py "<报告.html>" --skill-dir <stock-analyzer 目录>
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
