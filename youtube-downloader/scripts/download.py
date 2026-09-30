#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 视频下载脚本 / YouTube Video Downloader Script
支持下载视频、音频、字幕（中文/英文）
Supports downloading video, audio, and subtitles (Chinese/English)

用法 / Usage:
    python download.py <URL> [options]

示例 / Examples:
    python download.py https://www.youtube.com/watch?v=xxxxx
    python download.py https://www.youtube.com/watch?v=xxxxx --audio-only
    python download.py https://www.youtube.com/watch?v=xxxxx --subs zh-Hans,en
    python download.py https://www.youtube.com/watch?v=xxxxx --quality 720
    python download.py https://www.youtube.com/watch?v=xxxxx --output "D:/Videos"
"""

import sys
import os
import argparse
import subprocess

# ── 自动安装依赖 / Auto-install dependencies ──────────────────────────────────
def ensure_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        print("[INFO] yt-dlp not found, installing... / 正在安装 yt-dlp ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "yt-dlp", "-q"]
        )
        import yt_dlp
        return yt_dlp

yt_dlp = ensure_yt_dlp()

# ── 参数解析 / Argument Parsing ───────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="YouTube 视频下载工具 / YouTube Video Downloader"
    )
    parser.add_argument("url", help="YouTube 视频或播放列表 URL / Video or playlist URL")
    parser.add_argument(
        "--output", "-o",
        default=".",
        help="输出目录 / Output directory (default: current directory)"
    )
    parser.add_argument(
        "--output-template", "-t",
        default=None,
        help="自定义输出文件名模板 / Custom output filename template\n"
             "可用变量 / Available: %(title)s, %(id)s, %(ext)s, %(playlist_index)s\n"
             "例如 / e.g.: series_e%(playlist_index)02d.%(ext)s"
    )
    parser.add_argument(
        "--quality", "-q",
        default="best",
        help="视频质量 / Video quality: best(默认), 1080, 720, 480, 360, worst"
    )
    parser.add_argument(
        "--audio-only", "-a",
        action="store_true",
        help="仅下载音频 / Download audio only (mp3)"
    )
    parser.add_argument(
        "--subs", "-s",
        default=None,
        help="下载字幕，逗号分隔语言代码 / Download subtitles, comma-separated language codes\n"
             "例/e.g.: zh-Hans,zh-Hant,en,en-US"
    )
    parser.add_argument(
        "--auto-subs",
        action="store_true",
        help="同时下载自动生成字幕 / Also download auto-generated subtitles"
    )
    parser.add_argument(
        "--embed-subs",
        action="store_true",
        help="将字幕嵌入视频文件 / Embed subtitles into video file"
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="下载整个播放列表 / Download entire playlist"
    )
    parser.add_argument(
        "--cookies",
        default=None,
        help="cookies 文件路径（用于会员视频）/ Cookies file path (for members-only videos)"
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="代理地址 / Proxy URL, e.g. http://127.0.0.1:7890"
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="列出所有可用格式 / List all available formats"
    )
    parser.add_argument(
        "--js-runtime", "-j",
        default=None,
        help="JavaScript 运行时路径 / JS runtime path (e.g. /path/to/node.exe)"
    )
    parser.add_argument(
        "--client", "-c",
        default=None,
        help="YouTube 客户端类型 / Player client type: web, web_embedded, tv, ios, android\n"
             "web: 视频流（Topic 频道必须用此），web_embedded: 字幕更强，tv/默认: 部分受限"
    )
    return parser.parse_args()


# ── 格式选择 / Format Selection ───────────────────────────────────────────────
def build_format_selector(quality: str, audio_only: bool) -> str:
    if audio_only:
        return "bestaudio/best"
    quality_map = {
        "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/bestaudio/best",
        "1080":  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/bestaudio/best",
        "720":   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/bestaudio/best",
        "480":   "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/bestaudio/best",
        "360":   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/bestaudio/best",
        "worst": "worstvideo+worstaudio/worst",
    }
    return quality_map.get(quality, quality_map["best"])


# ── 字幕语言列表 / Subtitle language list ────────────────────────────────────
COMMON_CHINESE_CODES = ["zh-Hans", "zh-Hant", "zh", "zh-CN", "zh-TW", "zh-HK"]
COMMON_ENGLISH_CODES = ["en", "en-US", "en-GB", "en-AU"]

def parse_sub_langs(subs_arg: str) -> list[str]:
    if not subs_arg:
        return []
    return [lang.strip() for lang in subs_arg.split(",") if lang.strip()]


# ── 主下载逻辑 / Main Download Logic ─────────────────────────────────────────
def download(args):
    # 设 UTF-8 避免 emoji 打印崩溃
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    os.makedirs(args.output, exist_ok=True)

    # 输出文件名模板：优先使用自定义模板，否则用视频标题
    if args.output_template:
        outtmpl = os.path.join(args.output, args.output_template)
    else:
        outtmpl = os.path.join(args.output, "%(title)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "restrictfilenames": True,  # 替换全角竖线等 Windows 不兼容字符
        "format": build_format_selector(args.quality, args.audio_only),
        "noplaylist": not args.playlist,
        "merge_output_format": "mp4",
        "postprocessors": [],
        "verbose": False,
        "quiet": False,
        "no_warnings": False,
    }

    # 音频模式 / Audio mode
    if args.audio_only:
        ydl_opts["postprocessors"].append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })
        ydl_opts["outtmpl"] = os.path.join(args.output, "%(title)s.%(ext)s")

    # 字幕 / Subtitles
    sub_langs = parse_sub_langs(args.subs) if args.subs else []
    if sub_langs:
        ydl_opts["writesubtitles"] = True
        ydl_opts["subtitleslangs"] = sub_langs
        ydl_opts["subtitlesformat"] = "srt/vtt"
        if args.auto_subs:
            ydl_opts["writeautomaticsub"] = True
        if args.embed_subs:
            ydl_opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    # YouTube 客户端类型 / Player client
    # web_embedded (默认+cookies) 可能只有图片; web 客户端能拿到真实视频流
    # For Topic/Music channels, use 'web' to get actual video instead of images-only
    if args.client:
        ydl_opts["extractor_args"] = {"youtube": {"player_client": [args.client]}}

    # cookies / proxy
    if args.cookies:
        ydl_opts["cookiefile"] = args.cookies
    if args.proxy:
        ydl_opts["proxy"] = args.proxy

    # JS runtime (for n-challenge solving)
    js_runtime_path = args.js_runtime
    if js_runtime_path:
        ydl_opts["js_runtimes"] = {"node": {"path": js_runtime_path}}

    # 列出格式 / List formats
    if args.list_formats:
        ydl_opts["listformats"] = True
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(args.url, download=False)
        return

    print(f"\n{'='*60}")
    print(f"  YouTube 下载器 / YouTube Downloader")
    print(f"{'='*60}")
    print(f"  URL     : {args.url}")
    print(f"  输出目录: {os.path.abspath(args.output)}")
    print(f"  质量    : {'音频(mp3)' if args.audio_only else args.quality}")
    if sub_langs:
        print(f"  字幕    : {', '.join(sub_langs)}")
    if args.proxy:
        print(f"  代理    : {args.proxy}")
    print(f"{'='*60}\n")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(args.url, download=True)
        if info:
            title = info.get("title", "Unknown")
            print(f"\n✅ 下载完成 / Download complete: {title}")
            print(f"   保存至 / Saved to: {os.path.abspath(args.output)}")


# ── 入口 / Entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()
    try:
        download(args)
    except KeyboardInterrupt:
        print("\n⛔ 已取消 / Cancelled by user")
        sys.exit(1)
    except Exception as e:
        try:
            print(f"\n[ERROR] {e}")
        except UnicodeEncodeError:
            print(f"\n[ERROR] (encoding issue, see message above)")
        sys.exit(1)
