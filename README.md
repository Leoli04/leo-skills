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

股票投资全面分析工具，生成交互式 HTML 报告。

- **功能**：对任意上市公司生成 9 大维度的深度分析报告（公司概览、财务、技术面、市场情绪、同业对比、估值与健康度、宏观环境、风险、投资建议），支持用户持仓时的个性化仓位建议
- **触发词**：「分析XX股票」「XX公司全面分析」「stock analysis」「投资分析」等
- **输出**：自包含 HTML 文件（Chart.js 图表 + 分页导航 UI）
- **依赖**：WebSearch 数据检索，无需额外安装

## 使用方式

将本仓库克隆后，把对应 skill 目录放入 CodeBuddy 的 skills 目录（`.codebuddy/skills/`），即可通过自然语言触发。

## 目录结构

```
leo-skills/
├── stock-analyzer/        # 股票分析技能
│   ├── SKILL.md
│   ├── assets/            # HTML 报告模板
│   └── references/        # 参考资料
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
