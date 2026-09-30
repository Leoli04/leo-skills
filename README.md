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

## 目录结构

```
leo-skills/
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
