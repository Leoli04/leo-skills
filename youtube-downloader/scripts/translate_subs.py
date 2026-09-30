#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕翻译工具 / Subtitle Translator
将英文字幕翻译为中文，生成同名 .zh-Hans.srt 文件
Translate English SRT subtitles to Chinese (zh-Hans)

用法 / Usage:
    python translate_subs.py input.en.srt [output.zh-Hans.srt]
    python translate_subs.py input.en.srt --batch 10   # 每批翻译行数

依赖 / Dependencies:
    pip install deep-translator
"""

import sys
import os
import re
import argparse
import subprocess
from pathlib import Path


# ── 自动安装依赖 ────────────────────────────────────────────────────────────────
def ensure_dependencies():
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator
    except ImportError:
        print("[INFO] deep-translator not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "deep-translator", "-q"])
        from deep_translator import GoogleTranslator
        return GoogleTranslator

GoogleTranslator = ensure_dependencies()


# ── SRT 解析 ────────────────────────────────────────────────────────────────────
def parse_srt(filepath: str) -> list[dict]:
    """解析 SRT 文件，返回 [{index, start, end, text}, ...]"""
    blocks = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    # 按空行分割
    raw_blocks = re.split(r'\n\s*\n', content)
    for block in raw_blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        # 时间戳行
        time_match = re.match(r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})', lines[1])
        if not time_match:
            continue
        text = '\n'.join(lines[2:]).strip()
        if text:
            blocks.append({
                "index": index,
                "start": time_match.group(1),
                "end": time_match.group(2),
                "text": text,
            })
    return blocks


# ── 翻译 ────────────────────────────────────────────────────────────────────────
def translate_blocks(blocks: list[dict], batch_size: int = 15) -> list[str]:
    """批量翻译字幕文本，返回翻译后的文本列表（顺序一致）"""
    translator = GoogleTranslator(source='en', target='zh-CN')
    texts = [b["text"] for b in blocks]
    translated = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        # 用换行符连接批量翻译，再拆分（比逐条调用快很多）
        separator = "\n---\n"
        combined = separator.join(batch)
        try:
            result = translator.translate(combined)
            # 拆分回单条
            parts = result.split(separator)
            translated.extend(parts)
        except Exception as e:
            print(f"  [WARN] 批量翻译失败 (i={i}): {e}，逐条重试...")
            # 逐条降级
            for text in batch:
                try:
                    t = translator.translate(text)
                    translated.append(t)
                except Exception as e2:
                    print(f"  [WARN] 单条翻译失败: {e2}，保留原文")
                    translated.append(text)

        # 进度提示
        done = min(i + batch_size, len(texts))
        print(f"  [{done}/{len(texts)}] 已翻译...")

    return translated


# ── 生成 SRT ────────────────────────────────────────────────────────────────────
def write_srt(blocks: list[dict], translated: list[str], output_path: str):
    """输出翻译后的 SRT 文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        for block, zh_text in zip(blocks, translated):
            f.write(f"{block['index']}\n")
            f.write(f"{block['start']} --> {block['end']}\n")
            f.write(f"{zh_text.strip()}\n\n")
    print(f"\n✅ 翻译完成 / Translation complete: {output_path}")
    print(f"   共 {len(blocks)} 条字幕 / {len(blocks)} subtitle entries")


# ── 入口 ────────────────────────────────────────────────────────────────────────
def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="字幕翻译工具 / Subtitle Translator")
    parser.add_argument("input", help="输入 SRT 文件（英文）/ Input English SRT file")
    parser.add_argument("output", nargs="?", default=None, help="输出 SRT 文件 / Output Chinese SRT file")
    parser.add_argument("--batch", type=int, default=15, help="每批翻译条数 / Batch size (default: 15)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] 文件不存在: {args.input}")
        sys.exit(1)

    # 自动推断输出文件名
    if args.output is None:
        base = os.path.splitext(args.input)[0]
        # 去掉语言后缀（如 .en → .zh-Hans）
        base_no_lang = re.sub(r'\.(en|en-US|eng)$', '', base)
        args.output = f"{base_no_lang}.zh-Hans.srt"

    # 若已存在则跳过
    if os.path.exists(args.output):
        print(f"[SKIP] 输出文件已存在: {args.output}")
        print(f"   (删除该文件后重新运行以重新翻译)")
        sys.exit(0)

    print(f"输入: {args.input}")
    print(f"输出: {args.output}")
    print(f"解析字幕中... / Parsing subtitles...")

    blocks = parse_srt(args.input)
    if not blocks:
        print("[ERROR] 未找到有效字幕块 / No valid subtitle blocks found")
        sys.exit(1)

    print(f"共 {len(blocks)} 条字幕，开始翻译... / Translating {len(blocks)} entries...")
    translated = translate_blocks(blocks, args.batch)
    write_srt(blocks, translated, args.output)


if __name__ == "__main__":
    main()
