---
name: youtube-downloader
description: >
  YouTube 视频下载工具。支持从 YouTube 下载指定 URL 的视频、音频（mp3）、
  以及中英文字幕（zh-Hans / en）。基于 yt-dlp，支持画质选择、字幕嵌入、
  播放列表批量下载、代理设置等功能。
  YouTube video downloader. Downloads videos, audio (mp3), and subtitles
  (Chinese/English) from a specified YouTube URL using yt-dlp.
  Use this skill when the user wants to download a YouTube video, extract
  audio, or fetch subtitles for any YouTube URL.
agent_created: true
---

# YouTube 视频下载技能 / YouTube Video Downloader Skill

## 用途 / Purpose

从 YouTube 指定 URL 下载视频（含中英文字幕），支持：

- 📥 视频下载（mp4，可选画质）
- 🎵 仅提取音频（mp3）
- 📝 字幕下载（中文 zh-Hans / 英文 en，支持自动生成字幕）
- 📋 播放列表批量下载 + **智能系列管理**（配合 Agent 使用）
- 🔥 硬字幕烧录（双语支持）
- 🗂️ 下载状态追踪（`downloads.json`）
- 🌐 代理支持（用于网络受限环境）

---

## 架构 / Architecture

本 Skill 与 `youtube-download-agent` Agent 协同工作：

```
Agent (youtube-download-agent)
  ├── 意图解析 → 状态检查 → 范围定位 → 去重
  └── 调用 Skill 脚本执行具体操作
         │
         ├── download.py        → 单个视频下载
         ├── burn_subs.py       → 字幕烧录
         └── playlist_manager.py → 状态管理 / 系列解析
              └── downloads.json → 持久状态
```

---

## 依赖 / Dependencies

- **Python 3.8+**（使用 managed runtime）
- **yt-dlp**：基础下载库，`pip install yt-dlp`
- **yt-dlp-ejs**：JavaScript Challenge Solver，**必需** — 没有它大部分视频无法解析格式
  ```bash
  pip install yt-dlp-ejs
  ```
- **Node.js**：JS Runtime（用于执行 Challenge Solver 脚本），指定路径如：
  ```
  C:\Users\86130\.workbuddy\binaries\node\versions\22.22.2\node.exe
  ```
- **ffmpeg**（可选）：用于字幕嵌入、音频转 mp3、硬字幕烧录。无 ffmpeg 时可以下载原始格式

---

## 核心脚本 / Core Scripts

| 脚本 | 路径 | 用途 |
|---|---|---|
| `download.py` | `scripts/download.py` | 下载视频/音频/字幕（单视频或完整播放列表） |
| `burn_subs.py` | `scripts/burn_subs.py` | 将字幕硬编码烧录到视频画面 |
| `translate_subs.py` | `scripts/translate_subs.py` | 英→中字幕翻译（中文字幕不可用时的兜底方案） |
| `playlist_manager.py` | `scripts/playlist_manager.py` | 播放列表解析、状态管理、资源检测 |

---

## 工作流 / Workflow

### 场景 A：单视频下载

#### Step 1 — 确认参数

从用户请求中提取以下信息：

| 参数 | 说明 | 默认值 |
|---|---|---|
| `url` | YouTube 视频链接（必填） | — |
| `--output` | 保存目录 | 当前工作目录 |
| `--quality` | 画质：`best/1080/720/480/360/worst` | `best` |
| `--audio-only` | 仅提取音频(mp3) | false |
| `--subs` | 字幕语言，逗号分隔 | 无 |
| `--auto-subs` | 同时下载自动生成字幕 | false |
| `--embed-subs` | 将字幕嵌入视频 | false |
| `--playlist` | 下载整个播放列表 | false |
| `--proxy` | 代理地址 | 无 |
| `--list-formats` | 列出所有可用格式后退出 | false |
| `--js-runtime` | Node.js 路径 | 自动检测 |
| `--client` | YouTube 客户端类型: `web`/`web_embedded`/`tv`/`ios`/`android` | 默认(youtube) |
| `--output-template` | 自定义输出文件名模板，支持 `%(title)s`/`%(id)s`/`%(ext)s`/`%(playlist_index)s` | `%(title)s.%(ext)s` |

#### Step 2 — 构建命令

```bash
# 下载视频（默认最高画质）
<python> scripts/download.py "<URL>"

# 下载视频 + 中英文字幕
<python> scripts/download.py "<URL>" --subs "zh-Hans,en" --auto-subs

# 指定文件名模板（系列管理）
<python> scripts/download.py "https://www.youtube.com/watch?v=XXXX" \
  --output "D:/Videos" \
  --output-template "my-series_e03_%(title)s.%(ext)s" \
  --subs "zh-Hans,en" --auto-subs

# 仅提取音频
<python> scripts/download.py "<URL>" --audio-only

# 指定画质 + 保存目录
<python> scripts/download.py "<URL>" --quality 720 --output "D:/Videos"

# 下载播放列表
<python> scripts/download.py "<URL>" --playlist
```

#### Step 3 — 执行下载

Python 路径：
```
C:\Users\86130\.workbuddy\binaries\python\versions\3.13.12\python.exe
```

**完整模板（系列下载）**：
```bash
# 输出到系列独立文件夹
C:\Users\86130\.workbuddy\binaries\python\versions\3.13.12\python.exe \
  "{SKILL_ROOT}/scripts/download.py" \
  "https://www.youtube.com/watch?v=XXXXXX" \
  --subs "zh-Hans,en" \
  --auto-subs \
  --output "F:\lixiaofei\WorkBuddy\youtube\Maisy_Mouse" \
  --output-template "002_Playground_original.%(ext)s" \
  --proxy "http://127.0.0.1:PORT" \
  --cookies "youtube_cookies.txt" \
  --js-runtime "C:/Users/86130/.workbuddy/binaries/node/versions/22.22.2/node.exe"
```

### 场景 B：系列智能下载（配合 Agent）

Agent 使用 `playlist_manager.py` 管理系列：

```bash
# 1. 解析播放列表
<python> scripts/playlist_manager.py parse "<PLAYLIST_URL>" \
  --proxy "http://127.0.0.1:PORT" \
  --cookies "<cookies_path>" \
  --js-runtime "<node_path>" \
  --db "{SKILL_ROOT}/data/downloads.json"
  
# 2. 查看状态
<python> scripts/playlist_manager.py status "<PLAYLIST_URL>" \
  --db "{SKILL_ROOT}/data/downloads.json"

# 3. 获取待下载列表（自动去重）
<python> scripts/playlist_manager.py pending "<PLAYLIST_URL>" \
  --range "3-10" --json \
  --db "{SKILL_ROOT}/data/downloads.json"

# 4. 下载单个视频（用 video_id 构造 URL）
<python> scripts/download.py "https://www.youtube.com/watch?v={VIDEO_ID}" --subs "zh-Hans,en" --auto-subs ...

# 5. 标记下载完成
<python> scripts/playlist_manager.py mark-downloaded "<PLAYLIST_URL>" "{VIDEO_ID}" \
  --file "downloaded_file.mp4" \
  --subs "zh-Hans:file.zh-Hans.srt,en:file.en.srt" \
  --db "{SKILL_ROOT}/data/downloads.json"

# 6. 标记烧录完成
<python> scripts/playlist_manager.py mark-burned "<PLAYLIST_URL>" "{VIDEO_ID}" \
  --file "burned_file_sub.mp4" \
  --sub-lang "zh-Hans+en" \
  --db "{SKILL_ROOT}/data/downloads.json"
```

---

## 字幕烧录 / Burning Subtitles into Video

### 硬字幕（烧录到画面，推荐）

用 `scripts/burn_subs.py` 将字幕直接画到视频每一帧：

```bash
# 烧录到同一系列文件夹（原视频 → 成品，无 _original 后缀）
<python> scripts/burn_subs.py \
  "Maisy_Mouse/002_Playground_original.mp4" \
  --sub "Maisy_Mouse/002_Playground_original.zh-Hans.srt" \
  --sub2 "Maisy_Mouse/002_Playground_original.en.srt" \
  --lang chi --lang2 eng \
  --output "Maisy_Mouse/002_Playground.mp4"
```

```bash
# 单语言字幕烧录
<python> scripts/burn_subs.py \
  "video.mp4" \
  --sub "subtitle.en.srt" --lang eng
```

**burn_subs.py 参数说明：**

| 参数 | 说明 | 默认值 |
|---|---|---|
| `-s / --sub` | 主字幕 SRT 文件路径（必填） | — |
| `--sub2` | 第二语言字幕 SRT 文件路径 | — |
| `--lang` | 主字幕语言标签 (chi/eng/jpn/kor) | chi |
| `--lang2` | 第二语言标签 | eng |
| `-o / --output` | 输出视频路径 | `原文件名_sub.mp4` |
| `-d / --output-dir` | 输出目录，文件名自动生成 | 视频所在目录 |
| `--font-size` | 字幕字号 | 18 |
| `--crf` | 视频质量 (越小越清晰，18-28) | 23 |
| `--preset` | 编码速度 (fast/medium/slow) | medium |

---

## 字幕语言代码参考 / Subtitle Language Codes

最常用：
- 简体中文：`zh-Hans`（或 `zh-CN`）
- 繁体中文：`zh-Hant`（或 `zh-TW`）
- 英文：`en`（或 `en-US`）

---

## 注意事项 / Notes

1. **网络环境**：YouTube 在中国大陆需要代理，通过 `--proxy` 参数传入
2. **版权**：仅用于个人学习用途，请遵守 YouTube 服务条款及当地法律
3. **yt-dlp 更新**：YouTube 频繁更新反爬机制，若下载失败可先更新：
   ```bash
   <python> -m pip install -U yt-dlp
   ```
4. **ffmpeg**：通过 winget 安装：
   ```powershell
   winget install "FFmpeg (Essentials Build)"
   ```
5. **Windows 文件名兼容**：YouTube 标题含全角竖线 `｜` 等字符在 Windows 上可能导致错误，脚本已内置 `restrictfilenames=True` 自动替换。
6. **bot 检测**：`--js-runtime` 和 `--cookies` 几乎总是需要同时使用。
7. **yt-dlp-ejs**：必须先安装此依赖，否则大部分视频无法解析格式。
