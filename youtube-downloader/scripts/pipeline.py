#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单视频完整处理管线 / Single Video Full Pipeline
  下载 → 过滤音效 → 翻译 → 烧录 → 标记 → 清理

用法:
  python pipeline.py --video-id YztyofbUMV8 --index 063 --name Plane \
      --playlist "https://www.youtube.com/playlist?list=PL..." \
      --cookies ... --js-runtime ... --proxy ...

也可以跳过某些步骤:
  --skip-download   (视频已存在)
  --skip-burn       (只下载+翻译，不烧录)
"""

import sys, os, argparse, subprocess, shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

# ── 编码 ────────────────────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

def run(cmd, desc=""):
    print(f"  [{desc}]", " ".join(str(c) for c in cmd[:5]), "..." if len(cmd)>5 else "")
    r = subprocess.run(cmd, capture_output=False, text=True)
    if r.returncode != 0:
        print(f"  [FAILED] {desc} (exit={r.returncode})")
    return r.returncode == 0

def parse_args():
    p = argparse.ArgumentParser(description="单视频完整处理管线")
    p.add_argument("--video-id", required=True, help="YouTube video ID")
    p.add_argument("--index", required=True, type=int, help="集数编号")
    p.add_argument("--name", required=True, help="短名称 (如 Playground)")
    p.add_argument("--playlist", default=None, help="播放列表 URL（标记状态用）")
    p.add_argument("--output-dir", required=True, help="输出目录")
    p.add_argument("--cookies", default=None, help="Cookies 文件路径")
    p.add_argument("--proxy", default=None, help="代理地址")
    p.add_argument("--js-runtime", default=None, help="Node.js 路径")
    p.add_argument("--db", default=str(SKILL_DIR / "data" / "downloads.json"), help="数据库路径")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--skip-burn", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    vid = args.video_id
    idx = f"{args.index:03d}"
    name = args.name
    root = f"{idx}_{name}"
    out_dir = args.output_dir

    original = os.path.join(out_dir, f"{root}_original.mp4")
    en_srt = os.path.join(out_dir, f"{root}_original.en.srt")
    zh_srt = os.path.join(out_dir, f"{root}_original.zh-Hans.srt")
    en_clean = os.path.join(out_dir, f"{root}_original.en_clean.srt")
    zh_tmp = os.path.join(out_dir, f"{root}_original.en_clean.zh-Hans.srt")
    zh_clean = os.path.join(out_dir, f"{root}_original.en_clean.zh-Hans_clean.srt")
    output_mp4 = os.path.join(out_dir, f"{root}.mp4")

    print(f"\n{'='*50}")
    print(f"  Pipeline: {root}")
    print(f"{'='*50}")

    # ── ① 下载 ──────────────────────────────────────────────────────────────
    if not args.skip_download:
        print("\n[1/5] 下载视频+英文字幕...")
        cmd = [sys.executable, str(SCRIPT_DIR / "download.py"),
               f"https://www.youtube.com/watch?v={vid}",
               "--output", out_dir,
               "--output-template", f"{root}_original.%(ext)s",
               "--subs", "en", "--auto-subs"]
        if args.cookies: cmd += ["--cookies", args.cookies]
        if args.proxy: cmd += ["--proxy", args.proxy]
        if args.js_runtime: cmd += ["--js-runtime", args.js_runtime]
        if not run(cmd, "download"): return 1

    # ── ② 过滤 + 翻译 ──────────────────────────────────────────────────────
    print("\n[2/5] 过滤音效标签 + 英→中翻译...")
    filter_py = str(SCRIPT_DIR / "_filter.py")
    translate_py = str(SCRIPT_DIR / "translate_subs.py")

    if os.path.exists(en_srt):
        if not run([sys.executable, filter_py, en_srt], "filter EN"): return 1
    if os.path.exists(en_clean):
        if not run([sys.executable, translate_py, en_clean], "translate"): return 1
    if os.path.exists(zh_tmp):
        if not run([sys.executable, filter_py, zh_tmp], "filter ZH"): return 1
        shutil.copy(zh_clean, zh_srt)  # 重命名为规范文件名

    # ── ③ 烧录 ──────────────────────────────────────────────────────────────
    if not args.skip_burn and os.path.exists(original):
        print("\n[3/5] 烧录双字幕...")
        cmd = [sys.executable, str(SCRIPT_DIR / "burn_subs.py"), original,
               "--sub", zh_srt, "--sub2", en_clean,
               "--lang", "chi", "--lang2", "eng",
               "--output", output_mp4]
        if not run(cmd, "burn"): return 1

    # ── ④ 标记 ──────────────────────────────────────────────────────────────
    if args.playlist:
        print("\n[4/5] 更新状态...")
        pm = str(SCRIPT_DIR / "playlist_manager.py")
        subs = f"en:{root}_original.en.srt,zh-Hans:{root}_original.zh-Hans.srt" if os.path.exists(zh_srt) else f"en:{root}_original.en.srt"
        run([sys.executable, pm, "mark-downloaded", args.playlist, vid,
             "--file", f"{root}_original.mp4", "--subs", subs, "--db", args.db], "mark-dl")
        if os.path.exists(output_mp4):
            run([sys.executable, pm, "mark-burned", args.playlist, vid,
                 "--file", f"{root}.mp4", "--sub-lang", "zh-Hans+en", "--db", args.db], "mark-burn")

    # ── ⑤ 清理 ──────────────────────────────────────────────────────────────
    print("\n[5/5] 清理临时文件...")
    for f in [en_clean, zh_tmp, zh_clean]:
        if os.path.exists(f):
            os.remove(f)
            print(f"  del: {os.path.basename(f)}")
    # 清理 .part 残留
    for f in os.listdir(out_dir):
        if f.startswith(root) and ".part" in f:
            os.remove(os.path.join(out_dir, f))
            print(f"  del: {f}")

    print(f"\n{'='*50}")
    print(f"  DONE: {root}.mp4")
    print(f"{'='*50}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
