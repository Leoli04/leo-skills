#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""硬字幕烧录 / Hard Subtitle Burner  (基于 ffmpeg-python)
pip install ffmpeg-python  (ffmpeg 二进制仍需安装)
"""
import os, sys, re, argparse
import ffmpeg

try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass

SOUND_TAGS = {"[Music]","[Applause]","[音乐]","[掌声]","[音效]","♪","♫"}

def filter_srt(input_path):
    with open(input_path, "r", encoding="utf-8") as f: lines = f.readlines()
    out, removed = [], 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s in SOUND_TAGS or (s.startswith("[") and s.endswith("]") and len(s)<20):
            removed += 1
            if out and out[-1] == "\n": out.pop()
            continue
        out.append(line)
    result = re.sub(r"\n{3,}", "\n\n", "".join(out))
    out_path = input_path.replace(".srt", "_clean.srt")
    with open(out_path, "w", encoding="utf-8") as f: f.write(result)
    return out_path, removed

def do_burn(input_video, srt_file, output_video, font_size=24, color="FFFFFF",
            margin_v=10, crf=23, preset="medium"):
    """烧录单条字幕到视频
    样式: 白色文字 + 半透明黑色背板(BorderStyle=3) + 粗描边，明亮背景也能看清"""
    style = f"FontSize={font_size},PrimaryColour=&H00{color}," \
            f"OutlineColour=&H00000000,Outline=4,Shadow=2,BorderStyle=1," \
            f"MarginV={margin_v}"
    try:
        vin = ffmpeg.input(input_video)
        vout = vin.filter('subtitles', srt_file, force_style=style)
        # subtitles 是纯视频滤镜，必须显式传入音频流，否则输出无声
        ffmpeg.output(vout, vin.audio, output_video, vcodec='libx264', crf=crf,
                      preset=preset, acodec='copy').overwrite_output().run(
                          quiet=True, capture_stderr=True)
        return True
    except ffmpeg.Error as e:
        err = e.stderr.decode() if e.stderr else str(e)
        print(f"  [ERROR] {err[-300:]}")
        return False

def burn_dual(video, cn_srt, en_srt, output, font_size=22, crf=23, preset="medium"):
    """两步烧录：中文(下)→英文(上)"""
    wd = os.path.dirname(os.path.abspath(video))
    # 按输出文件名生成独立临时文件，避免多视频并发冲突
    base = os.path.splitext(os.path.basename(output))[0]
    tmp = f"_temp_burn_{base}.mp4"
    # cd 到视频目录，只用文件名（ffmpeg-python 无 cwd，且 Windows 绝对路径有问题）
    old_cwd = os.getcwd()
    os.chdir(wd)
    try:
        vf, cf, ef, of2 = os.path.basename(video), os.path.basename(cn_srt), os.path.basename(en_srt), os.path.basename(output)
        # 清理上次可能残留的临时文件
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except: pass
        print(f"[1/2] 烧录中文 (下方, MarginV=10)...")
        if not do_burn(vf, cf, tmp, font_size, margin_v=10, color="FFFFFF", crf=crf, preset=preset):
            return False
        print(f"[2/2] 烧录英文 (上方, MarginV=50)...")
        if not do_burn(tmp, ef, of2, font_size, margin_v=50, color="FFFFFF", crf=crf, preset=preset):
            return False
        print(f"双字幕烧录完成 ({os.path.getsize(output)/1024/1024:.1f} MB)")
        return True
    finally:
        # 清理临时文件
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except: pass
        os.chdir(old_cwd)

def parse_args():
    p = argparse.ArgumentParser(description="硬字幕烧录工具")
    p.add_argument("video"); p.add_argument("--sub","-s",required=True)
    p.add_argument("--sub2",default=None); p.add_argument("--lang",default="chi")
    p.add_argument("--lang2",default="eng")
    p.add_argument("--output","-o",default=None); p.add_argument("--output-dir","-d",default=None)
    p.add_argument("--font-size",type=int,default=18)
    p.add_argument("--crf",type=int,default=23); p.add_argument("--preset",default="medium")
    p.add_argument("--filter-tags",action="store_true")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    s1, s2 = args.sub, args.sub2
    if args.filter_tags:
        s1, _ = filter_srt(args.sub)
        if args.sub2:
            s2, _ = filter_srt(args.sub2)
    if not args.output:
        base = os.path.splitext(args.video)[0]
        args.output = f"{base}_sub.mp4"
        if args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            args.output = os.path.join(args.output_dir, os.path.basename(args.output))
    if args.sub2:
        ok = burn_dual(args.video, s1, s2, args.output, args.font_size, args.crf, args.preset)
    else:
        ok = do_burn(args.video, s1, args.output, args.font_size, "FFFFFF", 10, args.crf, args.preset)
    sys.exit(0 if ok else 1)
