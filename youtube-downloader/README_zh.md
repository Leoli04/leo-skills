# YouTube 视频下载工具 (youtube-downloader)

> 基于 yt-dlp 的 YouTube 视频下载 Skill，支持视频/音频/中英文字幕下载，以及硬字幕烧录。

---

## 目录

- [功能特性](#功能特性)
- [系统要求](#系统要求)
- [依赖安装](#依赖安装)
- [快速开始](#快速开始)
- [核心脚本](#核心脚本)
  - [download.py — 视频下载](#downloadpy--视频下载)
  - [burn_subs.py — 硬字幕烧录](#burn_subspy--硬字幕烧录)
- [字幕功能详解](#字幕功能详解)
  - [软字幕 vs 硬字幕](#软字幕-vs-硬字幕)
  - [完整工作流：下载 + 中英双语硬字幕](#完整工作流下载--中英双语硬字幕)
- [网络与代理](#网络与代理)
- [常见问题排查](#常见问题排查)
- [实战经验总结](#实战经验总结)
- [文件结构](#文件结构)

---

## 功能特性

| 功能 | 说明 |
|---|---|
| 视频下载 | 支持 mp4 格式，可选最高/1080p/720p/480p/360p/最低画质 |
| 音频提取 | 仅下载音频流，保存为原始格式（需 ffmpeg 转换为 mp3） |
| 字幕下载 | 手动字幕 + 自动生成字幕，支持中、英、日、韩等多语言 |
| 软字幕嵌入 | 将 SRT 字幕作为可选轨道嵌入 mp4（mov_text 格式） |
| 硬字幕烧录 | 将字幕直接画到视频画面上，任何播放器都能看到 |
| 播放列表 | 支持批量下载整个播放列表 |
| 代理支持 | HTTP / SOCKS5 代理，适配中国大陆网络环境 |
| JS 反爬 | 内置 Node.js Challenge Solver，解决 YouTube bot 检测 |
| Cookies 支持 | 支持浏览器导出的 cookies.txt，绕过登录验证 |

---

## 系统要求

| 组件 | 要求 | 说明 |
|---|---|---|
| Python | 3.8+ | 使用 WorkBuddy managed runtime: `3.13.12` |
| Node.js | 22.x+ | 用于 JS Challenge Solver，WorkBuddy managed: `22.22.2` |
| yt-dlp | 最新版 | 基础下载库 |
| yt-dlp-ejs | 最新版 | JS Challenge Solver 插件（必需） |
| ffmpeg | — | 硬字幕烧录、音频转换时需要 |

---

## 依赖安装

### 1. yt-dlp + yt-dlp-ejs

```bash
# 使用清华镜像加速安装（国内推荐）
python -m pip install yt-dlp yt-dlp-ejs \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn
```

### 2. ffmpeg（Windows）

```powershell
winget install "FFmpeg (Essentials Build)"
```

安装后 ffmpeg 位于：
```
%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_*\bin\ffmpeg.exe
```

### 3. Cookies 文件（必需）

YouTube 要求浏览器 cookies 验证。使用 Chrome/Edge 扩展导出：

1. 安装扩展：[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. 打开 https://www.youtube.com
3. 点击扩展图标 → Export → 保存为 `youtube_cookies.txt`

---

## 快速开始

### 基本下载

```bash
# 下载视频（默认最高画质）
python download.py "https://www.youtube.com/watch?v=XXXXXX"

# 下载视频 + 中英文字幕（推荐）
python download.py "https://www.youtube.com/watch?v=XXXXXX" \
  --subs "zh-Hans,en" --auto-subs

# 仅提取音频
python download.py "https://www.youtube.com/watch?v=XXXXXX" --audio-only

# 指定 720p 画质
python download.py "https://www.youtube.com/watch?v=XXXXXX" --quality 720
```

### 在中国大陆环境下（推荐模板）

```bash
python scripts/download.py \
  "https://www.youtube.com/watch?v=XXXXXX" \
  --subs "zh-Hans,en" \
  --auto-subs \
  --output "./output" \
  --proxy "http://127.0.0.1:7890" \
  --cookies "./youtube_cookies.txt" \
  --js-runtime "node"
```

---

## 核心脚本

### download.py — 视频下载

**路径**：`scripts/download.py`

#### 全部参数

| 参数 | 简写 | 说明 | 默认值 |
|---|---|---|---|
| `url` | — | YouTube 视频/播放列表链接（必填） | — |
| `--output` | `-o` | 输出目录 | 当前目录 |
| `--quality` | `-q` | 画质：best/1080/720/480/360/worst | best |
| `--audio-only` | `-a` | 仅提取音频 | false |
| `--subs` | `-s` | 字幕语言，逗号分隔（如 zh-Hans,en） | 无 |
| `--auto-subs` | — | 同时下载自动生成字幕 | false |
| `--embed-subs` | — | 将字幕嵌入视频为软字幕轨道 | false |
| `--playlist` | — | 下载整个播放列表 | false |
| `--cookies` | — | cookies.txt 文件路径 | 无 |
| `--proxy` | — | 代理地址 | 无 |
| `--list-formats` | — | 查看所有可用格式后退出 | false |
| `--js-runtime` | `-j` | Node.js 路径（Challenge Solver 用） | 自动检测 |
| `--client` | `-c` | YouTube 客户端类型：web / web_embedded / tv / ios / android | 默认 |

#### 关键参数说明

- **`--cookies`** + **`--js-runtime`**：几乎总是需要同时使用。YouTube 的 bot 检测要求 cookies 验证 + JS challenge solver。
- **`--client web`**：YouTube Topic/Music 频道视频（只有封面图无视频流）必须使用此参数，否则只能下载图片和音频。
- **`--auto-subs`**：下载自动生成字幕（AI 语音识别），部分视频没有手动上传的字幕。

---

### burn_subs.py — 硬字幕烧录

**路径**：`scripts/burn_subs.py`

将 SRT 字幕文件直接画到视频画面中，任何播放器都能看到字幕。

#### 全部参数

| 参数 | 简写 | 说明 | 默认值 |
|---|---|---|---|
| `video` | — | 输入视频文件路径（必填） | — |
| `--sub` | `-s` | 主字幕 SRT 文件路径（必填） | — |
| `--sub2` | — | 第二语言字幕文件路径 | 无 |
| `--lang` | — | 主字幕语言标签：chi / eng / jpn / kor | chi |
| `--lang2` | — | 第二语言标签 | eng |
| `--output` | `-o` | 输出文件路径 | 原文件名_sub.mp4 |
| `--output-dir` | `-d` | 输出目录（文件名自动生成为 `原文件名_sub.mp4`） | 视频所在目录 |
| `--font-size` | — | 字幕字号 | 18 |
| `--crf` | — | 视频质量 CRF (18-28，越小越清晰) | 23 |
| `--preset` | — | 编码速度预设：fast / medium / slow | medium |

#### 使用示例

```bash
# 中英双语硬字幕（中文蓝色上方 + 英文白色下方，存到 ./output/ 目录）
python scripts/burn_subs.py "video.mp4" \
  --sub "video.zh-Hans.srt" \
  --sub2 "video.en.srt" \
  --lang chi --lang2 eng \
  --output-dir "./output"

# 单语言字幕，指定输出路径
python scripts/burn_subs.py "video.mp4" \
  --sub "video.en.srt" --lang eng \
  --font-size 20 \
  --output "./output/my_video.mp4"
```

---

## 字幕功能详解

### 软字幕 vs 硬字幕

| 类型 | 格式 | 优点 | 缺点 | 适用场景 |
|---|---|---|---|---|
| **软字幕** | mov_text (mp4) | 可开关、不损伤画质、文件小 | 多数播放器不支持 | 专业播放器 (VLC/PotPlayer) |
| **硬字幕** | 烧录到画面 | 任何播放器都能看到 | 不可关闭、需重编码、文件变大 | 内建播放器、手机、在线分享 |

**结论**：如果不知道最终用什么播放器，用硬字幕是最稳妥的选择。

### 完整工作流：下载 + 中英双语硬字幕

```bash
# ========== Step 1: 下载视频 + 字幕 ==========
python scripts/download.py \
  "https://www.youtube.com/watch?v=XXXXXX" \
  --subs "zh-Hans,en" \
  --auto-subs \
  --output "./output" \
  --proxy "http://127.0.0.1:7890" \
  --cookies "./youtube_cookies.txt" \
  --js-runtime "node"

# ========== Step 2: 中文字幕被限流 429？等 15-30 秒后重试 ==========
# 如果中文字幕下载失败，单独重试：
python -c "
import yt_dlp
ydl_opts = {
    'proxy': 'http://127.0.0.1:7890',
    'cookiefile': './youtube_cookies.txt',
    'js_runtimes': {'node': {'path': 'node'}},
    'skip_download': True,
    'writeautomaticsub': True,
    'subtitleslangs': ['zh-Hans'],
    'subtitlesformat': 'srt',
    'outtmpl': './output/%(title)s.%(ext)s',
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.extract_info('https://www.youtube.com/watch?v=XXXXXX', download=True)
"

# ========== Step 3: 烧录中英双语硬字幕 ==========
python scripts/burn_subs.py \
  "./output/video.mp4" \
  --sub "./output/video.zh-Hans.srt" \
  --sub2 "./output/video.en.srt" \
  --lang chi --lang2 eng \
  --output-dir "./output"

# ========== Step 4: 确认效果，清理临时文件 ==========
```

---

## 字幕语言代码

| 语言 | 代码 |
|---|---|
| 简体中文 | `zh-Hans` `zh-CN` `zh` |
| 繁体中文 | `zh-Hant` `zh-TW` `zh-HK` |
| 英文 | `en` `en-US` `en-GB` |
| 日文 | `ja` |
| 韩文 | `ko` |
| 法文 | `fr` |
| 德文 | `de` |
| 西班牙文 | `es` |

---

## 网络与代理

YouTube 在中国大陆需要代理访问，不同代理软件的默认端口：

| 代理软件 | HTTP 端口 | SOCKS5 端口 |
|---|---|---|
| Clash / Clash Verge | 7890 | 7891 |
| V2RayN | 10809 | 10808 |
| Shadowsocks | 1080 | 1080 |

**诊断代理连通性**：

```bash
# 测试代理能否访问 YouTube
curl -x http://127.0.0.1:7890 -s --connect-timeout 10 \
  -o /dev/null -w "%{http_code}" https://www.youtube.com
# 返回 200 即可用
```

---

## 常见问题排查

### 1. `Sign in to confirm you're not a bot`

**原因**：YouTube 的 bot 检测需要浏览器验证。  
**解决**：使用「Get cookies.txt LOCALLY」扩展导出 cookies，添加 `--cookies` 参数。

### 2. `n challenge solving failed`

**原因**：JS Challenge Solver 未配置。  
**解决**：安装 `yt-dlp-ejs` + 指定 `--js-runtime` 路径。

### 3. `HTTP Error 429: Too Many Requests`

**原因**：字幕下载临时限流。  
**解决**：等待 15-30 秒后单独重试字幕。

### 4. 下载的视频只有封面图没有画面

**原因**：YouTube Topic/Music 频道视频，默认客户端只返回图片。  
**解决**：添加 `--client web` 参数。

### 5. 视频文件显示"已删除"

**原因**：文件名中的全角竖线 `｜` 等字符在 Windows 上不兼容。  
**解决**：脚本已内置 `restrictfilenames=True` 自动处理。如已下载，手动重命名文件。

### 6. 软字幕在播放器中不显示

**原因**：多数播放器不支持 `mov_text` 软字幕格式。  
**解决**：使用 `burn_subs.py` 烧录硬字幕。

### 7. pip 安装超时

**原因**：系统代理拦截了 pip 请求。  
**解决**：使用清华镜像源：
```bash
pip install yt-dlp yt-dlp-ejs \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn
```

---

## 实战经验总结

以下是创建此 Skill 过程中遇到的关键问题和解决方案：

| 问题 | 根因 | 解决方案 |
|---|---|---|
| Bot 检测失败 | 缺少 cookies + JS solver | `--cookies` + `--js-runtime` 同时使用 |
| 视频只有图片 | Topic 频道走 web_embedded 客户端 | 用 `--client web` |
| 字幕 429 限流 | YouTube CDN 反爬 | 等 15-30s 重试，或换 `web_embedded` 客户端 |
| 字幕两层中文 | force_style 逗号未转义 | ffmpeg 滤镜内逗号需 `\,` 转义 |
| 文件打不开 | 全角竖线 `｜` 不兼容 Windows | `restrictfilenames=True` |
| 软字幕不显示 | mov_text 不被支持 | 改用硬字幕烧录 |
| 烧录字幕重复 | 在已有字幕的视频上二次烧录 | 务必用干净视频做输入 |

---

## 文件结构

```
~/.workbuddy/skills/youtube-downloader/
├── SKILL.md                 # Skill 配置文件（中英双语）
├── README_zh.md             # 中文说明文档（本文件）
├── scripts/
│   ├── download.py          # 视频/音频/字幕下载脚本
│   └── burn_subs.py         # 硬字幕烧录脚本
└── references/
    └── reference.md          # 字幕代码、画质选项速查表
```

---

## 更新日志

| 日期 | 更新内容 |
|---|---|
| 2026-06-20 | 初始创建：download.py + 基础画质/音频/字幕下载 |
| 2026-06-24 | 增加 `burn_subs.py` 硬字幕烧录；增加 `--client` 参数；增加 `restrictfilenames`；完善 SKILL.md 字幕烧录文档；增加 README_zh.md；增加 `--output-dir` 参数；文档路径改为相对路径 |
