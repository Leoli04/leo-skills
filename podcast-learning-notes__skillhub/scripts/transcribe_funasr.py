#!/usr/bin/env python3
"""Transcribe a podcast audio file with FunASR + speaker diarization (cam++).

Unlike the OpenAI-compatible ``/v1/audio/transcriptions`` server path, this
script runs FunASR's ``AutoModel`` locally with a speaker model attached, so the
output separates who-said-what. That is required for multi-speaker podcasts:
without diarization the transcript is one undifferentiated wall of text.

Pipeline: paraformer (ASR) + fsmn-vad (segmentation) + ct-punc (punctuation) +
cam++ (speaker diarization). The result's ``sentence_info`` carries a ``spk``
id per sentence, which this script collapses into ``说话人N`` placeholder labels.
The labels are positional only; mapping them to real names is a human step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe audio with FunASR + cam++ speaker diarization.",
    )
    parser.add_argument("audio", type=Path, help="Path to the audio file (.wav/.mp3/.m4a/...).")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("source/transcript.md"),
        help="Where to write the markdown transcript (default: source/transcript.md).",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cuda", "cpu"],
        default="auto",
        help="Inference device. 'auto' picks cuda when available, else cpu.",
    )
    parser.add_argument(
        "--model",
        default="paraformer-zh",
        help="ASR model. Use paraformer-zh for Chinese, paraformer-en for English.",
    )
    parser.add_argument(
        "--spk-model",
        default="cam++",
        help="Speaker diarization model. Pass an empty string to disable diarization.",
    )
    parser.add_argument(
        "--hotword",
        default="",
        help="Space-separated hotwords to bias proper nouns (e.g. guest names).",
    )
    parser.add_argument(
        "--batch-size-s",
        type=int,
        default=300,
        help="Dynamic batch length in seconds (lower it if you run out of memory).",
    )
    parser.add_argument(
        "--raw-json",
        type=Path,
        default=None,
        help="Optional path to also dump the raw FunASR result for debugging.",
    )
    return parser.parse_args(argv)


def resolve_device(choice: str) -> str:
    if choice != "auto":
        return choice
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def build_model(model: str, spk_model: str, device: str) -> Any:
    from funasr import AutoModel

    kwargs: dict[str, Any] = {
        "model": model,
        "vad_model": "fsmn-vad",
        "punc_model": "ct-punc",
        "device": device,
        "disable_update": True,
    }
    if spk_model:
        kwargs["spk_model"] = spk_model
    return AutoModel(**kwargs)


def format_timestamp(ms: float) -> str:
    """Milliseconds -> ``[mm:ss]`` or ``[hh:mm:ss]`` for long episodes."""
    total = int(round(ms / 1000))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
    return f"[{minutes:02d}:{seconds:02d}]"


def merge_turns(sentence_info: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive sentences from the same speaker into one turn."""
    turns: list[dict[str, Any]] = []
    for sent in sentence_info:
        text = (sent.get("text") or "").strip()
        if not text:
            continue
        spk = sent.get("spk", 0)
        start = sent.get("start", 0)
        if turns and turns[-1]["spk"] == spk:
            turns[-1]["text"] = f"{turns[-1]['text']} {text}"
        else:
            turns.append({"spk": spk, "start": start, "text": text})
    return turns


def render_markdown(result: dict[str, Any], *, model: str, spk_model: str) -> str:
    sentence_info = result.get("sentence_info")
    lines: list[str] = ["# 转写稿"]

    if not sentence_info:
        # No diarization (plain-text fallback): be honest in the header.
        lines.append("")
        lines.append(f"> 模型：{model}（无 sentence_info，未做说话人分离/时间戳）")
        lines.append("> 说话人：未分离 —— 请检查 spk_model 是否生效")
        lines.append("")
        lines.append((result.get("text") or "").strip())
        lines.append("")
        return "\n".join(lines)

    turns = merge_turns(sentence_info)
    speakers = sorted({turn["spk"] for turn in turns})
    label = {spk: f"说话人{idx + 1}" for idx, spk in enumerate(speakers)}

    chain = f"{model} + fsmn-vad + ct-punc"
    if spk_model:
        chain += f" + {spk_model}"
    lines.append("")
    lines.append(f"> 模型：{chain}")
    lines.append(f"> 说话人：自动分离为 {len(speakers)} 个；下列编号为占位标签，需人工对应到真实姓名")
    lines.append("> 时间戳：每段起始，格式 [mm:ss]")
    lines.append("> 音频核对：未核对原音频；转写可能有漏词/专名误识别/说话人切分错误")
    lines.append("")
    lines.append("## 说话人对照（待人工填写）")
    lines.append("")
    for spk in speakers:
        lines.append(f"- {label[spk]} → ？")
    lines.append("")
    lines.append("---")
    lines.append("")
    for turn in turns:
        ts = format_timestamp(turn["start"])
        lines.append(f"{ts} **{label[turn['spk']]}**：{turn['text']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.audio.exists():
        print(f"音频文件不存在：{args.audio}", file=sys.stderr)
        return 1

    device = resolve_device(args.device)
    print(
        f"设备：{device}；模型：{args.model}；说话人模型：{args.spk_model or '（关闭）'}",
        file=sys.stderr,
    )

    try:
        model = build_model(args.model, args.spk_model, device)
    except ImportError:
        print(
            "未安装 funasr。请先：pip install funasr modelscope torch torchaudio",
            file=sys.stderr,
        )
        return 1

    generate_kwargs: dict[str, Any] = {
        "input": str(args.audio),
        "batch_size_s": args.batch_size_s,
    }
    if args.hotword:
        generate_kwargs["hotword"] = args.hotword

    results = model.generate(**generate_kwargs)
    if not results:
        print("FunASR 未返回任何结果。", file=sys.stderr)
        return 1
    result = results[0]

    if args.raw_json:
        args.raw_json.parent.mkdir(parents=True, exist_ok=True)
        args.raw_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    markdown = render_markdown(result, model=args.model, spk_model=args.spk_model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")

    if result.get("sentence_info"):
        print(f"已写出带说话人标签的转写稿：{args.output}", file=sys.stderr)
    else:
        print(
            f"已写出转写稿（但无说话人分离）：{args.output}\n"
            "  结果里没有 sentence_info —— 确认 spk_model=cam++ 已生效、模型已下载。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
