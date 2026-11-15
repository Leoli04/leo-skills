#!/usr/bin/env python3
"""Cloud ASR helpers for podcast-learning-notes.

The script has two jobs:

1. Call Tongyi/DashScope ASR when the user provides ``DASHSCOPE_API_KEY`` and
   a public audio URL.
2. Normalize JSON results exported by cloud ASR tools into the skill's
   ``source/transcript.md`` shape.

Feishu Minutes deployments vary by tenant and product permission. For Feishu,
prefer exporting or fetching the transcript with the user's own Feishu app, then
run ``normalize --provider feishu`` here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or normalize cloud ASR results.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tongyi = subparsers.add_parser("tongyi", help="Run Tongyi/DashScope ASR with an audio URL.")
    tongyi.add_argument("--audio-url", required=True, help="Publicly reachable audio URL.")
    tongyi.add_argument("--output", type=Path, default=Path("source/transcript.md"))
    tongyi.add_argument("--raw-json", type=Path, default=Path("source/cloud-asr-raw.json"))
    tongyi.add_argument("--model", default="paraformer-v2")
    tongyi.add_argument("--language", default="zh")
    tongyi.add_argument("--env-file", type=Path, default=Path(".env.local"))
    tongyi.add_argument("--no-diarization", action="store_true", help="Do not request speaker diarization.")
    tongyi.add_argument("--poll-interval", type=float, default=5.0)
    tongyi.add_argument("--timeout", type=float, default=3600.0)

    normalize = subparsers.add_parser("normalize", help="Normalize a cloud ASR JSON file.")
    normalize.add_argument("--provider", required=True, choices=["tongyi", "feishu", "generic"])
    normalize.add_argument("--input-json", type=Path, required=True)
    normalize.add_argument("--output", type=Path, default=Path("source/transcript.md"))
    normalize.add_argument("--raw-json", type=Path, default=None)
    normalize.add_argument("--model", default="")
    return parser.parse_args(argv)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"缺少环境变量 {name}。请在本机 shell 中设置，不要把密钥写进 repo。")
    return value


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def call_tongyi(args: argparse.Namespace) -> dict[str, Any]:
    load_env_file(args.env_file)
    require_env("DASHSCOPE_API_KEY")
    try:
        import dashscope
    except ImportError as exc:
        raise SystemExit("未安装 dashscope SDK。请先安装：pip install dashscope") from exc

    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

    try:
        transcription = dashscope.audio.asr.Transcription
    except AttributeError as exc:
        raise SystemExit("当前 dashscope SDK 未暴露 audio.asr.Transcription，请升级 dashscope。") from exc

    call_kwargs: dict[str, Any] = {
        "model": args.model,
        "file_urls": [args.audio_url],
        "language_hints": [args.language],
    }
    if not args.no_diarization:
        call_kwargs["diarization_enabled"] = True

    try:
        response = transcription.async_call(**call_kwargs)
    except TypeError:
        call_kwargs.pop("diarization_enabled", None)
        response = transcription.async_call(**call_kwargs)

    task_id = extract_task_id(response)
    if not task_id:
        return object_to_jsonable(response)

    deadline = time.time() + args.timeout
    last: Any = response
    while time.time() < deadline:
        last = transcription.fetch(task=task_id)
        status = extract_status(last)
        if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
            result = object_to_jsonable(last)
            return enrich_tongyi_result(result)
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            raise SystemExit(f"通义转写任务失败：{json.dumps(object_to_jsonable(last), ensure_ascii=False)[:2000]}")
        time.sleep(args.poll_interval)

    raise SystemExit(f"通义转写任务超时，task_id={task_id}，最后状态：{extract_status(last)}")


def extract_task_id(response: Any) -> str | None:
    data = object_to_jsonable(response)
    for path in [("output", "task_id"), ("task_id",), ("request_id",)]:
        node: Any = data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, str) and node:
            return node
    return None


def extract_status(response: Any) -> str:
    data = object_to_jsonable(response)
    for path in [("output", "task_status"), ("output", "status"), ("status",)]:
        node: Any = data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, str):
            return node.upper()
    return ""


def enrich_tongyi_result(result: dict[str, Any]) -> dict[str, Any]:
    urls = collect_urls(result)
    for url in urls:
        if "transcription" not in url.lower() and not url.lower().endswith(".json"):
            continue
        try:
            with urlopen(url, timeout=60) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                result["downloaded_transcription"] = json.loads(response.read().decode(charset))
                break
        except Exception as exc:
            result.setdefault("download_errors", []).append(f"{url}: {exc}")
    return result


def collect_urls(value: Any) -> list[str]:
    urls: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, str) and node.startswith(("http://", "https://")):
            urls.append(node)

    visit(value)
    return urls


def object_to_jsonable(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return json.loads(json.dumps(value.__dict__, ensure_ascii=False, default=str))
    return {"value": str(value)}


def normalize_items(provider: str, data: Any) -> list[dict[str, Any]]:
    root = data.get("downloaded_transcription", data) if isinstance(data, dict) else data
    candidates: list[Any] = []
    if isinstance(root, dict):
        transcripts = root.get("transcripts")
        if isinstance(transcripts, list):
            transcript_items: list[dict[str, Any]] = []
            for transcript in transcripts:
                if not isinstance(transcript, dict):
                    continue
                sentences = transcript.get("sentences")
                if isinstance(sentences, list) and sentences:
                    transcript_items.extend(normalize_items(provider, sentences))
                else:
                    text = find_text(transcript)
                    if text:
                        transcript_items.append({"text": text})
            if transcript_items:
                return transcript_items

        for key in ["sentences", "sentence_info", "segments", "paragraphs", "utterances"]:
            value = root.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates:
            output = root.get("output")
            if isinstance(output, dict):
                return normalize_items(provider, output)
            results = root.get("results")
            if isinstance(results, list) and results:
                return normalize_items(provider, results[0])
            text = find_text(root)
            return [{"text": text}] if text else []
    elif isinstance(root, list):
        candidates = root

    items: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = find_text(item)
        if not text:
            continue
        speaker = first_present(item, ["speaker", "speaker_id", "spk", "role"])
        start = first_present(item, ["begin_time", "start_time", "start", "start_ms"])
        items.append({"text": text, "speaker": speaker, "start": parse_ms(start)})
    return items


def find_text(node: dict[str, Any]) -> str:
    for key in ["text", "transcript", "sentence", "content", "words"]:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_present(node: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in node and node[key] is not None:
            return node[key]
    return None


def parse_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number.is_integer() and number < 10000:
        number *= 1000
    return int(number)


def format_timestamp(ms: int | None) -> str:
    if ms is None:
        return ""
    total = int(round(ms / 1000))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"[{hours:02d}:{minutes:02d}:{seconds:02d}] "
    return f"[{minutes:02d}:{seconds:02d}] "


def render_markdown(provider: str, model: str, items: list[dict[str, Any]]) -> str:
    has_speaker = any(item.get("speaker") not in (None, "") for item in items)
    has_ts = any(item.get("start") is not None for item in items)
    lines = [
        "# 转写稿",
        "",
        f"> 转写服务：{provider}",
        f"> 模型：{model or '未标明'}",
        f"> 说话人分离：{'有' if has_speaker else '无'}",
        f"> 时间戳：{'有' if has_ts else '无'}",
        "> 音频核对：未核对原音频；转写可能有漏词、专名误识别或说话人切分错误",
        "",
    ]
    if has_speaker:
        speakers = []
        for item in items:
            speaker_value = item.get("speaker")
            speaker = "" if speaker_value is None else str(speaker_value)
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        labels = {speaker: f"说话人{idx + 1}" for idx, speaker in enumerate(speakers)}
        lines.extend(["## 说话人对照（待人工填写）", ""])
        for speaker in speakers:
            lines.append(f"- {labels[speaker]}（原始ID: {speaker}）→ ？")
        lines.extend(["", "---", ""])
        for item in items:
            speaker_value = item.get("speaker")
            speaker = "" if speaker_value is None else str(speaker_value)
            prefix = format_timestamp(item.get("start"))
            label = labels.get(speaker, "说话人？")
            lines.append(f"{prefix}**{label}**：{item['text']}")
            lines.append("")
    else:
        lines.extend(["## 原始转写文本", ""])
        for item in items:
            prefix = format_timestamp(item.get("start"))
            lines.append(f"{prefix}{item['text']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    *,
    provider: str,
    model: str,
    data: dict[str, Any],
    output: Path,
    raw_json: Path | None,
) -> int:
    if raw_json:
        raw_json.parent.mkdir(parents=True, exist_ok=True)
        raw_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    items = normalize_items(provider, data)
    if not items:
        detail = f" 原始 JSON 已保存：{raw_json}" if raw_json else ""
        print(f"云转写结果里没有找到可用文本字段。请检查原始 JSON。{detail}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(provider, model, items), encoding="utf-8")
    print(f"已写出 transcript：{output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "tongyi":
        data = call_tongyi(args)
        return write_outputs(
            provider="tongyi",
            model=args.model,
            data=data,
            output=args.output,
            raw_json=args.raw_json,
        )
    if args.command == "normalize":
        data = json.loads(args.input_json.read_text(encoding="utf-8"))
        raw_json = args.raw_json
        if raw_json and raw_json.resolve() != args.input_json.resolve():
            raw_json.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.input_json, raw_json)
            raw_json = None
        return write_outputs(
            provider=args.provider,
            model=args.model,
            data=data,
            output=args.output,
            raw_json=raw_json,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
