#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
播放列表管理器 / Playlist Manager
负责：解析播放列表、管理下载状态、检测资源存在性、生成待下载列表
Responsible for: parsing playlists, managing download state, checking resources, generating pending lists

数据存储结构 / Data structure:
    data/
      downloads.json          ← 索引文件（config + 系列列表）
      series/
        PLxxxxx.json          ← 每个系列独立文件，按 playlist_id 命名
        PLyyyyy.json

用法 / Usage:
    python playlist_manager.py parse <URL> [--proxy URL] [--cookies FILE] [--js-runtime PATH] [--abbrev NAME]
    python playlist_manager.py status <URL>
    python playlist_manager.py pending <URL> [--range 3-10] [--json]
    python playlist_manager.py mark-downloaded <URL> <VIDEO_ID> --file <FILENAME> [--subs ...]
    python playlist_manager.py mark-burned <URL> <VIDEO_ID> --file <FILENAME> --sub-lang <LANG>
    python playlist_manager.py config {show|get|set} [--key ...] [--value ...]
    python playlist_manager.py check <URL> <VIDEO_ID> [--check-dir DIR]
    python playlist_manager.py check-all <URL> [--check-dir DIR]
    python playlist_manager.py list [--json]
"""

import sys
import os
import json
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# ── 自动安装依赖 ────────────────────────────────────────────────────────────────
def ensure_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        print("[INFO] yt-dlp not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"])
        import yt_dlp
        return yt_dlp

yt_dlp = ensure_yt_dlp()

# ── 默认路径 ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_DB = str(SKILL_DIR / "data" / "downloads.json")

def series_dir(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path), "series")

def series_path(db_path: str, abbrev: str) -> str:
    """返回系列文件路径。直接使用缩写：{abbrev}.json"""
    safe = re.sub(r'[\\/:*?"<>|]', '_', abbrev)
    return os.path.join(series_dir(db_path), f"{safe}.json")

import re
def load_db(db_path: str) -> dict:
    """加载索引文件，自动迁移旧格式"""
    default_config = {"output_dir": ".", "check_dir": "."}
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            db = json.load(f)
    else:
        return {"version": "2.0", "config": default_config, "series_index": {}}

    # 自动迁移：v1 格式（series 内嵌在 db 中）→ v2 格式（分文件存储）
    if "series" in db and db["series"]:
        print("[INFO] 检测到旧格式数据，正在迁移为分文件存储...")
        if "config" not in db:
            db["config"] = default_config
        if "series_index" not in db:
            db["series_index"] = {}
        sdir = series_dir(db_path)
        os.makedirs(sdir, exist_ok=True)
        for pid, sdata in db["series"].items():
            sdata["last_updated"] = datetime.now().isoformat()
            abbrev = sdata.get("abbrev", pid[:10])
            spath = series_path(db_path, abbrev)
            with open(spath, "w", encoding="utf-8") as f:
                json.dump(sdata, f, ensure_ascii=False, indent=2)
            db["series_index"][pid] = {
                "name": sdata.get("name", pid),
                "abbrev": sdata.get("abbrev", pid[:20]),
                "url": sdata.get("url", ""),
                "total_videos": sdata.get("total_videos", 0),
                "file": f"series/{abbrev}.json",
            }
        del db["series"]
        db["version"] = "2.0"
        save_db(db, db_path)
        print(f"[OK] 已迁移 {len(db['series_index'])} 个系列到 data/series/ 目录")

    if "config" not in db:
        db["config"] = default_config
    if "series_index" not in db:
        db["series_index"] = {}
    if "version" not in db:
        db["version"] = "2.0"
    return db

def save_db(db: dict, db_path: str):
    """保存索引文件（只保存 config + series_index，不含系列数据）"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    to_save = {
        "version": db.get("version", "2.0"),
        "meta": {"last_updated": datetime.now().isoformat()},
        "config": db.get("config", {}),
        "series_index": db.get("series_index", {}),
    }
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def get_config_dir(db: dict, key: str) -> str:
    cfg = db.get("config", {})
    return cfg.get(key, ".")

# ── 系列文件读写（data/series/{playlist_id}.json） ──────────────────────────────
def load_series(db_path: str, playlist_id: str, db: dict = None) -> dict:
    """加载系列数据文件。通过索引或旧文件名查找"""
    sdir = series_dir(db_path)
    # 1. 通过索引查 abbrev → {abbrev}.json
    if db and playlist_id in db.get("series_index", {}):
        abbrev = db["series_index"][playlist_id].get("abbrev", "")
        if abbrev:
            spath = series_path(db_path, abbrev)
            if os.path.exists(spath):
                with open(spath, "r", encoding="utf-8") as f:
                    return json.load(f)
    # 2. 在目录中搜索包含 playlist_id 的文件（兼容旧命名）
    if os.path.exists(sdir):
        for fname in os.listdir(sdir):
            if playlist_id in fname and fname.endswith(".json"):
                with open(os.path.join(sdir, fname), "r", encoding="utf-8") as f:
                    return json.load(f)
    return None

def save_series(db_path: str, playlist_id: str, series_data: dict):
    """保存系列数据到文件（直接以 abbrev 命名）"""
    sdir = series_dir(db_path)
    os.makedirs(sdir, exist_ok=True)
    abbrev = series_data.get("abbrev", playlist_id[:10])
    series_data["last_updated"] = datetime.now().isoformat()

    # 清理所有包含该 playlist_id 的旧文件
    for fname in os.listdir(sdir):
        if playlist_id in fname and fname.endswith(".json") and fname != f"{abbrev}.json":
            os.remove(os.path.join(sdir, fname))

    # 保存
    spath = series_path(db_path, abbrev)
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(series_data, f, ensure_ascii=False, indent=2)

def list_series_files(db_path: str) -> list:
    """列出所有系列文件"""
    sdir = series_dir(db_path)
    if not os.path.exists(sdir):
        return []
    return sorted([f for f in os.listdir(sdir) if f.endswith(".json")])

# ── 播放列表解析 ────────────────────────────────────────────────────────────────
def safe_print(msg: str):
    """安全打印，处理 UnicodeEncodeError（如 GBK 控制台遇到 emoji）"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))

def get_playlist_id(url: str) -> str:
    import re
    m = re.search(r'list=([^&]+)', url)
    if m:
        return m[1]
    return url

def strip_emoji(text: str) -> str:
    """去除 emoji 和特殊 Unicode 符号，保留 ASCII + 中文 + 基本标点"""
    import re
    # 保留：字母、数字、中文、空格、连字符、下划线、点
    cleaned = re.sub(r'[^\w\s\-_.\u4e00-\u9fff]', '', text, flags=re.UNICODE)
    # 合并多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if cleaned else text[:20]

# ── 通用前缀/后缀（从标题中提取集名关键词时使用）──────────────
_COMMON_PREFIXES = ["Maisy Mouse Official", "Peppa Pig Official"]
_COMMON_SUFFIXES = sorted([
    "English Full Episode", "Cartoon For Kids", "Videos For Kids",
    "Full Episodes", "Full Episode", "Kids Cartoon", "Kids Movies",
    "Cartoons For Kids", "Video For Kids", "Videos For Kid",
    "Cartoon for Kids", "Videos for Kids",
    "Christmas SPECIAL", "Christmas Special", "HOLLIDAY SPECIAL", "SPECIAL",
], key=len, reverse=True)  # 按长度降序，长词优先匹配

def extract_short_title(title: str, index: int) -> str:
    """从完整标题中提取短标题，并清理 emoji
    规则：
      1. 若含 | 分隔符，取第二个最短有效段（通常为集名关键词）
         "Maisy Mouse Official | Playground | English ..." → "Playground"
         "Maisy Mouse Official | ✈️ Plane ✈️ | ..." → "Plane"
      2. 若 | 分隔后所有后段都是噪音词（English Full Episode 等），
         则从第一段中剔除前缀/后缀提取集名
      3. 若无 | 分隔符，剔除已知前缀/后缀后取关键词
      4. 兜底：取前 30 字符，末尾截到最近空格
    """
    skip_words = {"english full episode", "cartoon for kids", "videos for kids",
                   "full episode", "full episodes", "official", "hd", "1080p", "720p",
                   "kids cartoon", "kids movies", "cartoons for kids", "kids movie",
                   "video for kids", "videos for kid"}

    if "|" in title:
        segments = [s.strip() for s in title.split("|")]
        # 优先从 | 分隔的后段中找有效集名
        candidates = [strip_emoji(s) for s in segments[1:]
                      if s.lower() not in skip_words
                      and len(strip_emoji(s)) <= 50
                      and len(strip_emoji(s)) >= 1]
        if candidates:
            return candidates[0][:40]
        # 所有后段都是噪音词 → 从第一段中提取
        if len(segments) >= 2:
            result = _clean_prefix_suffix(strip_emoji(segments[0]))
            if result:
                return result
            # 也尝试从第二段提取（可能未被 skip_words 覆盖）
            alt = strip_emoji(segments[1])
            if alt and len(alt) <= 50:
                return alt[:40]
            return strip_emoji(segments[1])[:30]

    # 无 | 分隔符：剔除前缀/后缀提取
    result = _clean_prefix_suffix(strip_emoji(title))
    if result:
        return result

    # 兜底
    short = strip_emoji(title)[:40].rstrip()
    if " " in short:
        short = short[:short.rfind(" ")]
    return short


def _clean_prefix_suffix(text: str) -> str:
    """剔除已知前缀和后缀，返回纯净集名（无长度限制，由调用方截断）"""
    cleaned = text
    for prefix in _COMMON_PREFIXES:
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip()
            break
    for suffix in _COMMON_SUFFIXES:
        pat = re.compile(re.escape(suffix), re.IGNORECASE)
        cleaned = pat.sub('', cleaned).strip()
    # 清理残留分隔符和多余空格
    cleaned = re.sub(r'[\|\-–—•]+', ' ', cleaned)
    # 剔除末尾的已知全大写噪音尾缀（如 CHRISTMAS、SPECIAL 等）
    for noise_word in ["CHRISTMAS"]:
        cleaned = re.sub(rf'\s+\b{re.escape(noise_word)}\b\s*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    if cleaned and len(cleaned) <= 50:
        return cleaned[:40]
    if cleaned:
        # 过长：截断到最近空格
        short = cleaned[:40].rstrip()
        if " " in short:
            short = short[:short.rfind(" ")]
        return short
    return ""


def parse_playlist(url: str, proxy: str = None, cookies: str = None,
                   js_runtime: str = None, abbrev: str = None,
                   start: int = None, end: int = None, full: bool = True):
    """解析播放列表（默认全量，支持>100条翻页）
    full=True (默认): extract_flat=False + ignoreerrors，逐视频获取元数据
    full=False (--quick): 只获取前100条（快速预览用）"""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False if full else "in_playlist",
        "ignoreerrors": True,
    }
    if start and end:
        ydl_opts["playliststart"] = start
        ydl_opts["playlistend"] = end
    elif start:
        ydl_opts["playliststart"] = start

    if proxy:
        ydl_opts["proxy"] = proxy
    if cookies:
        ydl_opts["cookiefile"] = cookies
    if js_runtime:
        ydl_opts["js_runtimes"] = {"node": {"path": js_runtime}}

    mode_str = " [快速/Quick]" if not full else " [全量/Full]"
    range_str = f" (范围 {start}-{end})" if start else ""
    safe_print(f"[INFO] 正在解析播放列表...{mode_str}{range_str}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" not in info:
            safe_print("[ERROR] 未检测到播放列表")
            return None

        playlist_title = info.get("title", "Unknown Playlist")
        playlist_id = info.get("id", get_playlist_id(url))
        entries = info.get("entries", [])
        valid_entries = [e for e in entries if e is not None]
        total = len(valid_entries)

        safe_print(f"[OK] 播放列表: {playlist_title} ({total} 个视频)")

        base_idx = start if start else 1
        videos = {}
        for i, entry in enumerate(valid_entries):
            vid = entry.get("id")
            if not vid:
                continue
            idx = base_idx + i
            title = entry.get("title", f"Video_{idx}")
            short = extract_short_title(title, idx)
            abbrev_title = f"{idx:03d}_{short}"
            videos[vid] = {
                "index": idx,
                "title_original": title,
                "title_abbrev": abbrev_title,
                "skip": False,  # 去重标记
                "downloaded": False,
                "video_file": None,
                "subtitles": {},
                "burned": {"done": False, "file": None, "sub_lang": None, "time": None},
                "processed_at": None,
            }

        result = {
            "url": url,
            "name": playlist_title,
            "abbrev": abbrev or playlist_title[:20],
            "total_videos": total,
            "videos": videos,
        }
        return playlist_id, result

    except Exception as e:
        safe_print(f"[ERROR] 解析失败 / Parse failed: {e}")
        return None

# ── InnerTube API 解析（快速翻页，替代 yt-dlp 全量模式）─────────────────────
def parse_innertube(url, proxy=None, cookies=None, js_runtime=None, abbrev=None):
    """用 InnerTube API 解析播放列表（快速，支持分页>100）
    需要 requests 库和有效的 cookies 文件"""
    import requests, http.cookiejar

    API_URL = "https://www.youtube.com/youtubei/v1/browse?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
    playlist_id = get_playlist_id(url)

    # 加载 cookies
    cj = http.cookiejar.MozillaCookieJar(cookies)
    cj.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = cj
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update({"Content-Type": "application/json"})
    CTX = {"context": {"client": {"hl": "en", "clientName": "WEB", "clientVersion": "2.20250603.01.00"}}}

    def walk_page(data):
        """递归提取 lockupViewModel 和 continuation token"""
        vs = []
        token = None
        def _walk(obj):
            nonlocal token
            if isinstance(obj, dict):
                lvm = obj.get("lockupViewModel")
                if lvm:
                    # videoId from thumbnail URL
                    vid = ""
                    img = lvm.get("contentImage",{}).get("thumbnailViewModel",{}).get("image",{})
                    for src in img.get("sources", []):
                        m = re.search(r'/vi/([^/]+)/', src.get("url", ""))
                        if m: vid = m.group(1); break
                    # title from metadata.lockupMetadataViewModel.title
                    title = "?"
                    lmd = lvm.get("metadata",{}).get("lockupMetadataViewModel",{})
                    td = lmd.get("title", {})
                    runs = td.get("runs", [])
                    if runs:
                        title = "".join(r.get("text","") for r in runs)
                    elif td.get("content"):
                        title = td["content"]
                    if vid:
                        vs.append({"id": vid, "title": title})
                    return
                # continuation token
                if not token:
                    for k in ("nextContinuationData","continuationCommand"):
                        if not token and k in obj:
                            t = obj[k].get("continuation") or obj[k].get("token")
                            if t: token = t
                for v in obj.values(): _walk(v)
            elif isinstance(obj, list):
                for v in obj: _walk(v)
        _walk(data)
        return vs, token

    safe_print("[INFO] 正在通过 InnerTube API 解析播放列表...")
    try:
        r = s.post(API_URL, json={**CTX, "browseId": f"VL{playlist_id}"}, timeout=30)
        if r.status_code != 200:
            safe_print(f"[ERROR] HTTP {r.status_code}")
            return None
        r_json = r.json()
        # 检查是否被拦截
        if "twoColumnBrowseResultsRenderer" not in str(r_json):
            safe_print("[ERROR] 响应格式异常, cookies 可能失效")
            return None

        all_v, token = walk_page(r_json)
        playlist_name = ""
        try:
            playlist_name = r_json["metadata"]["playlistMetadataRenderer"]["title"]
        except: pass

        # 翻页
        page = 2
        while token and page <= 10:
            r = s.post(API_URL, json={**CTX, "continuation": token}, timeout=30)
            new_v, token = walk_page(r.json())
            if not new_v: break
            all_v.extend(new_v)
            page += 1

        safe_print(f"[OK] 共获取 {len(all_v)} 个视频 (通过 InnerTube API)")

        # 构造 series_data
        videos = {}
        for i, entry in enumerate(all_v):
            vid = entry["id"]
            idx = i + 1
            title = entry.get("title", f"Video_{idx}")
            short = extract_short_title(title, idx)
            abbrev_title = f"{idx:03d}_{short}"
            videos[vid] = {
                "index": idx,
                "title_original": title,
                "title_abbrev": abbrev_title,
                "skip": False,  # 去重标记
                "downloaded": False,
                "video_file": None,
                "subtitles": {},
                "burned": {"done": False, "file": None, "sub_lang": None, "time": None},
                "processed_at": None,
            }

        result = {
            "url": url,
            "name": playlist_name or "Unknown Playlist",
            "abbrev": abbrev or (playlist_name[:20] if playlist_name else "playlist"),
            "total_videos": len(videos),
            "videos": videos,
        }
        return playlist_id, result

    except Exception as e:
        safe_print(f"[ERROR] InnerTube 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return None

# ── 状态查询 ────────────────────────────────────────────────────────────────────
def get_series_status(series_data: dict) -> dict:
    """获取系列状态摘要"""
    videos = series_data["videos"]
    total = len(videos)
    downloaded = sum(1 for v in videos.values() if v.get("downloaded"))
    burned = sum(1 for v in videos.values() if v.get("burned", {}).get("done"))
    return {
        "name": series_data["name"],
        "abbrev": series_data.get("abbrev", ""),
        "total": total,
        "downloaded": downloaded,
        "burned": burned,
        "pending_download": total - downloaded,
        "pending_burn": downloaded - burned,
    }

def get_pending_list(series_data: dict, range_str: str = None) -> list:
    """获取待下载/待烧录列表"""
    videos = series_data["videos"]
    pending = []

    start_idx, end_idx = 1, len(videos)
    if range_str:
        parts = range_str.split("-")
        try:
            if len(parts) == 2:
                start_idx, end_idx = int(parts[0]), int(parts[1])
            elif len(parts) == 1:
                start_idx = end_idx = int(parts[0])
        except ValueError:
            pass

    for vid, v in sorted(videos.items(), key=lambda x: x[1]["index"]):
        idx = v["index"]
        if idx < start_idx or idx > end_idx:
            continue
        if v.get("skip"):
            continue  # 标记为重复，直接跳过
        if not v.get("downloaded"):
            pending.append({
                "video_id": vid,
                "index": idx,
                "title": v["title_original"],
                "abbrev": v.get("title_abbrev", f"ep{idx:02d}"),
                "need_video": True,
                "need_subs": {
                    lang: True for lang in v.get("subtitles", {})
                    if not v["subtitles"][lang].get("downloaded")
                },
            })
        else:
            if not v.get("burned", {}).get("done"):
                has_subs = any(
                    s.get("downloaded") and s.get("file")
                    for s in v.get("subtitles", {}).values()
                )
                if has_subs:
                    needs_burn = {
                        "video_id": vid,
                        "index": idx,
                        "title": v["title_original"],
                        "abbrev": v.get("title_abbrev", f"ep{idx:02d}"),
                        "need_video": False,
                        "need_burn": True,
                        "video_file": v.get("video_file"),
                        "available_subs": [
                            {"lang": lang, "file": s["file"]}
                            for lang, s in v.get("subtitles", {}).items()
                            if s.get("downloaded") and s.get("file")
                        ],
                    }
                    pending.append(needs_burn)
    return pending

# ── 状态更新 ────────────────────────────────────────────────────────────────────
def mark_downloaded(series_data: dict, video_id: str,
                    video_file: str, subs_info: dict = None) -> dict:
    """标记视频已下载"""
    if video_id not in series_data["videos"]:
        return {"error": f"Video {video_id} not found in series"}
    v = series_data["videos"][video_id]
    v["downloaded"] = True
    v["video_file"] = video_file
    v["processed_at"] = datetime.now().isoformat()
    if subs_info:
        for lang, sub_file in subs_info.items():
            v["subtitles"][lang] = {"downloaded": True, "file": sub_file}
    return {"ok": True}

def mark_burned(series_data: dict, video_id: str,
                file: str, sub_lang: str) -> dict:
    """标记字幕烧录完成"""
    if video_id not in series_data["videos"]:
        return {"error": f"Video {video_id} not found"}
    v = series_data["videos"][video_id]
    v["burned"] = {
        "done": True,
        "file": file,
        "sub_lang": sub_lang,
        "time": datetime.now().isoformat()
    }
    return {"ok": True}

# ── 资源检测 ────────────────────────────────────────────────────────────────────
def check_resource(series_data: dict, video_id: str, output_dir: str = ".") -> dict:
    """检测视频、字幕、烧录文件是否存在"""
    if video_id not in series_data["videos"]:
        return {"error": f"Video {video_id} not found"}

    v = series_data["videos"][video_id]
    result = {
        "video_id": video_id,
        "index": v["index"],
        "title": v["title_original"],
    }

    def disk_exists(db_file):
        if not db_file:
            return False
        full = db_file if os.path.isabs(db_file) else os.path.join(output_dir, db_file)
        return os.path.exists(full)

    video_db_file = v.get("video_file")
    result["video"] = {
        "db_exists": bool(video_db_file),
        "db_file": video_db_file,
        "disk_exists": disk_exists(video_db_file),
        "db_downloaded": v.get("downloaded", False),
    }

    result["subtitles"] = {}
    for lang, sub in v.get("subtitles", {}).items():
        sub_file = sub.get("file")
        result["subtitles"][lang] = {
            "db_downloaded": sub.get("downloaded", False),
            "db_file": sub_file,
            "disk_exists": disk_exists(sub_file),
        }

    burned = v.get("burned", {})
    burn_file = burned.get("file")
    result["burned"] = {
        "db_done": burned.get("done", False),
        "db_file": burn_file,
        "db_lang": burned.get("sub_lang"),
        "disk_exists": disk_exists(burn_file),
    }
    return result

# ── CLI 入口 ─────────────────────────────────────────────────────────────────────
def main():
    # 尝试设 UTF-8，避免 emoji 等字符导致 GBK 编码崩溃
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="播放列表管理器 / Playlist Manager")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # parse
    p_parse = subparsers.add_parser("parse", help="解析播放列表")
    p_parse.add_argument("url", help="播放列表 URL")
    p_parse.add_argument("--proxy", default=None)
    p_parse.add_argument("--cookies", default=None)
    p_parse.add_argument("--js-runtime", default=None)
    p_parse.add_argument("--abbrev", default=None, help="系列简称")
    p_parse.add_argument("--start", type=int, default=None, help="起始集数")
    p_parse.add_argument("--end", type=int, default=None, help="结束集数")
    p_parse.add_argument("--quick", action="store_true", help="快速模式（仅前100条，预览用）")
    p_parse.add_argument("--inner", action="store_true", help="用 InnerTube API 解析（快，需 valid cookies）")
    p_parse.add_argument("--db", default=str(DEFAULT_DB))

    # status
    p_status = subparsers.add_parser("status", help="查看系列状态")
    p_status.add_argument("url", help="播放列表 URL")
    p_status.add_argument("--db", default=str(DEFAULT_DB))

    # pending
    p_pending = subparsers.add_parser("pending", help="获取待下载列表")
    p_pending.add_argument("url", help="播放列表 URL")
    p_pending.add_argument("--range", default=None, help="视频范围，如 3-10")
    p_pending.add_argument("--db", default=str(DEFAULT_DB))
    p_pending.add_argument("--json", action="store_true")

    # mark-downloaded
    p_md = subparsers.add_parser("mark-downloaded", help="标记下载完成")
    p_md.add_argument("url", help="播放列表 URL")
    p_md.add_argument("video_id", help="视频 ID")
    p_md.add_argument("--file", required=True, help="下载的文件名")
    p_md.add_argument("--subs", default=None, help="字幕映射: zh-Hans:file.srt,en:file.srt")
    p_md.add_argument("--db", default=str(DEFAULT_DB))

    # mark-burned
    p_mb = subparsers.add_parser("mark-burned", help="标记烧录完成")
    p_mb.add_argument("url", help="播放列表 URL")
    p_mb.add_argument("video_id", help="视频 ID")
    p_mb.add_argument("--file", required=True, help="烧录后文件名")
    p_mb.add_argument("--sub-lang", required=True, help="烧录的字幕语言")
    p_mb.add_argument("--db", default=str(DEFAULT_DB))

    # mark-skip (去重)
    p_ms = subparsers.add_parser("mark-skip", help="标记视频为重复(下载时跳过)")
    p_ms.add_argument("url", help="播放列表 URL")
    p_ms.add_argument("video_id", help="视频 ID")
    p_ms.add_argument("--reason", default="duplicate", help="跳过原因")
    p_ms.add_argument("--db", default=str(DEFAULT_DB))

    # renumber
    p_rn = subparsers.add_parser("renumber", help="对未跳过视频重新连续编号(001起)")
    p_rn.add_argument("url", help="播放列表 URL")
    p_rn.add_argument("--db", default=str(DEFAULT_DB))

    # set-title
    p_st = subparsers.add_parser("set-title", help="修改视频的短标题")
    p_st.add_argument("url", help="播放列表 URL")
    p_st.add_argument("video_id", help="视频 ID")
    p_st.add_argument("title", help="新的短标题（如 003_Playground）")
    p_st.add_argument("--db", default=str(DEFAULT_DB))

    # get-title
    p_gt = subparsers.add_parser("get-title", help="获取单个视频标题")
    p_gt.add_argument("video", help="视频 URL 或 video_id")
    p_gt.add_argument("--cookies", default=None)
    p_gt.add_argument("--js-runtime", default=None)
    p_gt.add_argument("--proxy", default=None)
    p_gt.add_argument("--db", default=str(DEFAULT_DB))

    # config
    p_config = subparsers.add_parser("config", help="查看/设置工作目录配置")
    p_config.add_argument("action", choices=["get", "set", "show"])
    p_config.add_argument("--key", choices=["output_dir", "check_dir"])
    p_config.add_argument("--value")
    p_config.add_argument("--db", default=str(DEFAULT_DB))

    # check
    p_check = subparsers.add_parser("check", help="检查资源是否存在")
    p_check.add_argument("url", help="播放列表 URL")
    p_check.add_argument("video_id", help="视频 ID")
    p_check.add_argument("--check-dir", default=None, help="检测目录（默认 config.check_dir）")
    p_check.add_argument("--db", default=str(DEFAULT_DB))
    p_check.add_argument("--json", action="store_true")

    # check-all
    p_ca = subparsers.add_parser("check-all", help="检查系列所有资源")
    p_ca.add_argument("url", help="播放列表 URL")
    p_ca.add_argument("--check-dir", default=None, help="检测目录（默认 config.check_dir）")
    p_ca.add_argument("--db", default=str(DEFAULT_DB))
    p_ca.add_argument("--json", action="store_true")

    # list
    p_list = subparsers.add_parser("list", help="列出所有已注册的系列")
    p_list.add_argument("--db", default=str(DEFAULT_DB))
    p_list.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    db = load_db(args.db)

    # ── config ──
    if args.command == "config":
        if args.action == "show":
            print(json.dumps({
                "output_dir": get_config_dir(db, "output_dir"),
                "check_dir": get_config_dir(db, "check_dir"),
            }, ensure_ascii=False, indent=2))
        elif args.action == "get":
            if not args.key:
                print("[ERROR] --key required"); sys.exit(1)
            print(db.get("config", {}).get(args.key, "."))
        elif args.action == "set":
            if not args.key or not args.value:
                print("[ERROR] --key and --value required"); sys.exit(1)
            if "config" not in db:
                db["config"] = {}
            db["config"][args.key] = args.value
            save_db(db, args.db)
            print(f"[OK] config.{args.key} = {args.value}")
        sys.exit(0)

    # ── list ──
    if args.command == "list":
        sindex = db.get("series_index", {})
        if args.json:
            print(json.dumps(sindex, ensure_ascii=False, indent=2))
        else:
            if not sindex:
                print("(空 / Empty — 还没有注册的系列)")
                sys.exit(0)
            print(f"共 {len(sindex)} 个系列:\n")
            for pid, si in sindex.items():
                print(f"  [{pid}] {si['name']}")
                print(f"        缩写: {si.get('abbrev', 'N/A')}  |  共 {si.get('total_videos', '?')} 集")
                print(f"        文件: {si.get('file', 'N/A')}")
                print(f"        URL : {si.get('url', 'N/A')}")
                print()
        sys.exit(0)

    # ── get-title ──
    if args.command == "get-title":
        import yt_dlp
        url = args.video
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
        if getattr(args, "cookies", None):
            opts["cookiefile"] = args.cookies
        if getattr(args, "proxy", None):
            opts["proxy"] = args.proxy
        if getattr(args, "js_runtime", None):
            opts["js_runtimes"] = {"node": {"path": args.js_runtime}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            print(json.dumps({
                "video_id": info.get("id", ""),
                "title": info.get("title", ""),
                "url": info.get("webpage_url", url),
            }, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f'{{"error": "{e}"}}')
        sys.exit(0)

    # ── 系列相关命令 ──
    playlist_id = get_playlist_id(args.url)
    series_data = load_series(args.db, playlist_id, db)

    if args.command == "parse":
        if args.inner:
            result = parse_innertube(
                args.url, args.proxy, args.cookies, args.js_runtime, args.abbrev,
            )
        else:
            result = parse_playlist(
                args.url, args.proxy, args.cookies, args.js_runtime, args.abbrev,
                args.start, args.end, not args.quick,
            )
        if result is None:
            sys.exit(1)
        pid, new_data = result

        # 合并已有状态（翻页解析时追加，全量解析时替换）
        if series_data:
            old_videos = series_data.get("videos", {})
            if args.start:
                # 翻页模式：把新视频合并到已有数据中
                for vid, v in new_data["videos"].items():
                    if vid not in old_videos:
                        old_videos[vid] = v
                new_data["videos"] = old_videos
                new_data["total_videos"] = len(old_videos)
            else:
                # 全量模式：用旧状态更新新数据
                for vid, v in new_data["videos"].items():
                    if vid in old_videos:
                        ov = old_videos[vid]
                        v["downloaded"] = ov.get("downloaded", False)
                        v["video_file"] = ov.get("video_file")
                        v["subtitles"] = ov.get("subtitles", {})
                        v["burned"] = ov.get("burned", {"done": False, "file": None, "sub_lang": None, "time": None})
                        v["processed_at"] = ov.get("processed_at")
                        old_abbrev = ov.get("title_abbrev", "")
                        if old_abbrev and not any(ord(c) > 0xFFFF or (0x1F300 <= ord(c) <= 0x1FAFF) for c in old_abbrev):
                            v["title_abbrev"] = old_abbrev
            new_data["abbrev"] = new_data["abbrev"] if args.abbrev else series_data.get("abbrev", new_data["abbrev"])

        # 保存系列文件
        save_series(args.db, pid, new_data)

        # 更新索引
        if "series_index" not in db:
            db["series_index"] = {}
        db["series_index"][pid] = {
            "name": new_data["name"],
            "abbrev": new_data["abbrev"],
            "url": new_data["url"],
            "total_videos": new_data["total_videos"],
            "file": f"series/{new_data['abbrev']}.json",
        }
        save_db(db, args.db)

        safe_print(f"[OK] 播放列表已保存 / Playlist saved: {new_data['name']}")
        safe_print(f"     视频数 / Videos: {new_data['total_videos']}")
        safe_print(f"     缩写 / Abbrev: {new_data['abbrev']}")
        safe_print(f"     系列文件 / File: data/series/{new_data['abbrev']}.json")
        safe_print(f"     索引文件 / Index: {args.db}")
        safe_print("\n--- JSON OUTPUT ---")
        # 控制台输出用 ensure_ascii=True 避免 emoji 编码问题
        safe_print(json.dumps({"playlist_id": pid, "total_videos": new_data["total_videos"],
                               "abbrev": new_data["abbrev"], "name": new_data["name"]},
                              ensure_ascii=True))

    elif args.command == "status":
        if not series_data:
            print(json.dumps({"error": "Series not found"}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps(get_series_status(series_data), ensure_ascii=False, indent=2))

    elif args.command == "pending":
        if not series_data:
            print(json.dumps({"error": "Series not found"}, ensure_ascii=False))
            sys.exit(1)
        pending = get_pending_list(series_data, args.range)
        if args.json:
            print(json.dumps(pending, ensure_ascii=False, indent=2))
        else:
            if not pending:
                print("✅ 所有视频已处理完毕 / All videos processed!")
            for item in pending:
                if item.get("need_burn"):
                    print(f"  🔥 待烧录 / Pending burn: [{item['index']}] {item['title']} ({item['video_id']})")
                else:
                    need_subs = [l for l, n in item.get("need_subs", {}).items() if n]
                    subs_str = f" (字幕: {', '.join(need_subs)})" if need_subs else ""
                    print(f"  ⬇ 待下载 / Pending:    [{item['index']}] {item['title']} ({item['video_id']}){subs_str}")

    elif args.command == "mark-downloaded":
        if not series_data:
            print(f"[ERROR] Series not found: {playlist_id}")
            sys.exit(1)
        subs_info = {}
        if args.subs:
            for pair in args.subs.split(","):
                lang, fname = pair.split(":", 1)
                subs_info[lang.strip()] = fname.strip()
        result = mark_downloaded(series_data, args.video_id, args.file, subs_info)
        if result.get("ok"):
            save_series(args.db, playlist_id, series_data)
            print(f"[OK] 已标记下载 / Marked downloaded: {args.video_id} -> {args.file}")
        else:
            print(f"[ERROR] {result.get('error')}")

    elif args.command == "mark-burned":
        if not series_data:
            print(f"[ERROR] Series not found: {playlist_id}")
            sys.exit(1)
        result = mark_burned(series_data, args.video_id, args.file, args.sub_lang)
        if result.get("ok"):
            save_series(args.db, playlist_id, series_data)
            print(f"[OK] 已标记烧录 / Marked burned: {args.video_id} -> {args.file}")
        else:
            print(f"[ERROR] {result.get('error')}")

    elif args.command == "mark-skip":
        if not series_data:
            print(f"[ERROR] Series not found: {playlist_id}")
            sys.exit(1)
        if args.video_id not in series_data["videos"]:
            print(f"[ERROR] Video {args.video_id} not found")
            sys.exit(1)
        series_data["videos"][args.video_id]["skip"] = True
        series_data["videos"][args.video_id]["skip_reason"] = args.reason or "duplicate"
        save_series(args.db, playlist_id, series_data)
        print(f"[OK] 已标记跳过 / Marked skip: {args.video_id}")

    elif args.command == "renumber":
        if not series_data:
            print(f"[ERROR] Series not found: {playlist_id}")
            sys.exit(1)
        # 按原始 index 排序，只对未跳过视频分配新编号 + 更新短标题
        sorted_vids = sorted(series_data["videos"].items(), key=lambda x: x[1]["index"])
        new_idx = 1
        for vid, v in sorted_vids:
            if v.get("skip"):
                v["new_index"] = None
            else:
                v["new_index"] = new_idx
                # 更新 title_abbrev 前缀为新编号
                old_abbrev = v.get("title_abbrev", "")
                short_name = old_abbrev.split("_", 1)[-1] if "_" in old_abbrev else old_abbrev
                v["title_abbrev"] = f"{new_idx:03d}_{short_name}"
                new_idx += 1
        save_series(args.db, playlist_id, series_data)
        total_active = new_idx - 1
        print(f"[OK] 重新编号完成: {total_active} 个有效视频 (001-{total_active:03d})")

    elif args.command == "set-title":
        if not series_data:
            print(f"[ERROR] Series not found: {playlist_id}")
            sys.exit(1)
        if args.video_id not in series_data["videos"]:
            print(f"[ERROR] Video {args.video_id} not found in series")
            sys.exit(1)
        series_data["videos"][args.video_id]["title_abbrev"] = args.title
        save_series(args.db, playlist_id, series_data)
        print(f"[OK] 已更新短标题 / Title updated: {args.video_id} -> {args.title}")

    elif args.command == "check":
        if not series_data:
            print(json.dumps({"error": "Series not found"}, ensure_ascii=False))
            sys.exit(1)
        check_dir = args.check_dir or get_config_dir(db, "check_dir")
        result = check_resource(series_data, args.video_id, check_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"检测目录: {os.path.abspath(check_dir)}")
            print(f"视频: {result['title']} ({result['video_id']})")
            print(f"  视频文件: DB={'✅' if result['video']['db_exists'] else '❌'} "
                  f"磁盘={'✅' if result['video']['disk_exists'] else '❌'}")
            for lang, sub in result.get("subtitles", {}).items():
                print(f"  字幕 {lang}: DB={'✅' if sub['db_downloaded'] else '❌'} "
                      f"磁盘={'✅' if sub['disk_exists'] else '❌'}")
            print(f"  烧录: DB={'✅' if result['burned']['db_done'] else '❌'} "
                  f"磁盘={'✅' if result['burned']['disk_exists'] else '❌'}")

    elif args.command == "check-all":
        if not series_data:
            print(json.dumps({"error": "Series not found"}, ensure_ascii=False))
            sys.exit(1)
        check_dir = args.check_dir or get_config_dir(db, "check_dir")
        all_results = []
        for vid in series_data["videos"]:
            r = check_resource(series_data, vid, check_dir)
            all_results.append(r)
        if args.json:
            print(json.dumps({
                "check_dir": os.path.abspath(check_dir),
                "videos": all_results
            }, ensure_ascii=False, indent=2))
        else:
            print(f"检测目录: {os.path.abspath(check_dir)}")
            for r in all_results:
                status_icon = "✅" if (
                    r["video"]["disk_exists"] and
                    all(s["disk_exists"] for s in r["subtitles"].values())
                ) else "❌"
                print(f"{status_icon} [{r['index']}] {r['title']}")


if __name__ == "__main__":
    main()
