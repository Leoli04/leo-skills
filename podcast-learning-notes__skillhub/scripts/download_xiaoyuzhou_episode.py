#!/usr/bin/env python3
"""Download audio and show notes from a Xiaoyuzhou episode page."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


MEDIA_RE = re.compile(
    r"https?://media\.xyzcdn\.net/[^\s\"'<>]+?\.m4a(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(
    r"(?m)(?:^|\s)(?:\d{1,2}:)?\d{1,2}:\d{2}\s+.{2,120}"
)
DATE_KEY_RE = re.compile(
    r"(?:pub|publish|published|release|create|created|update|updated|upload).*?(?:date|time|at)|pubdate|datepublished|uploaddate",
    re.IGNORECASE,
)
DURATION_KEY_RE = re.compile(r"(?:duration|durationseconds|length)", re.IGNORECASE)


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        raw = " ".join(self.parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def normalize_text(raw: str) -> str:
    value = html.unescape(raw)
    value = value.replace("\\/", "/")
    value = value.replace("\\u002F", "/")
    value = value.replace("\\u003A", ":")
    value = value.replace("\\u0026", "&")
    return value


def extract_audio_url(text: str) -> str | None:
    normalized = normalize_text(text)
    match = MEDIA_RE.search(normalized)
    return match.group(0) if match else None


def request_page(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        import requests
    except ImportError:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def render_page(url: str) -> tuple[str, str, list[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "普通 HTTP 请求未提取完整信息，且当前 Python 环境没有 playwright。"
            "请先安装：pip install playwright && playwright install chromium"
        ) from exc

    captured_urls: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", lambda req: captured_urls.append(req.url))
        page.goto(url, wait_until="networkidle", timeout=60000)
        content = page.content()
        visible_text = page.locator("body").inner_text(timeout=10000)
        browser.close()
    return content, visible_text, captured_urls


def walk_json(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                found.append((child_path, child))
                visit(child, child_path)
        elif isinstance(node, list):
            for idx, child in enumerate(node):
                visit(child, f"{path}[{idx}]")

    visit(value, "")
    return found


def extract_json_blocks(page_html: str) -> list[Any]:
    blocks: list[Any] = []
    for match in re.finditer(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        try:
            blocks.append(json.loads(html.unescape(match.group(1))))
        except json.JSONDecodeError:
            pass

    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        try:
            blocks.append(json.loads(html.unescape(match.group(1))))
        except json.JSONDecodeError:
            pass
    return blocks


def meta_content(page_html: str, name: str) -> str | None:
    patterns = [
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return normalize_text(match.group(1)).strip()
    return None


def strip_html(page_html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(page_html)
    return parser.text()


def score_key(path: str) -> int:
    lower = path.lower()
    score = 0
    for token in ["shownote", "show_note", "description", "summary", "content", "intro"]:
        if token in lower:
            score += 3
    for token in ["title", "podcast", "episode", "guest", "author", "speaker"]:
        if token in lower:
            score += 1
    return score


def collect_json_text(page_html: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for block in extract_json_blocks(page_html):
        for path, value in walk_json(block):
            if not isinstance(value, str):
                continue
            text = normalize_text(value).strip()
            if len(text) < 8:
                continue
            if score_key(path) or TIMESTAMP_RE.search(text):
                candidates.append((path, text))
    return candidates


def first_json_value(page_html: str, path_patterns: list[str], value_type: type | tuple[type, ...]) -> Any | None:
    lowered_patterns = [pattern.lower() for pattern in path_patterns]
    for block in extract_json_blocks(page_html):
        for path, value in walk_json(block):
            lower_path = path.lower()
            if not isinstance(value, value_type):
                continue
            if any(pattern in lower_path for pattern in lowered_patterns):
                return value
    return None


def first_json_key_match(page_html: str, key_re: re.Pattern[str]) -> tuple[str, Any] | None:
    for block in extract_json_blocks(page_html):
        for path, value in walk_json(block):
            key = path.rsplit(".", 1)[-1]
            key = re.sub(r"\[\d+\]", "", key)
            if key_re.fullmatch(key) or key_re.search(key):
                if isinstance(value, (str, int, float)) and str(value).strip():
                    return path, value
    return None


def normalize_datetime(value: Any) -> str:
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return str(value)

    text = normalize_text(str(value)).strip()
    if re.fullmatch(r"\d{10,13}", text):
        return normalize_datetime(int(text))
    return text


def normalize_duration(value: Any) -> str:
    if isinstance(value, (int, float)) or re.fullmatch(r"\d+(?:\.\d+)?", str(value).strip()):
        seconds = int(float(value))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"
    return normalize_text(str(value)).strip()


def extract_episode_metadata(page_html: str, page_url: str, audio_url: str | None = None) -> list[tuple[str, str]]:
    metadata: list[tuple[str, str]] = []

    episode_title = first_json_value(
        page_html,
        ["props.pageprops.episode.title", "episode.title", "name"],
        str,
    )
    podcast_title = first_json_value(
        page_html,
        ["props.pageprops.episode.podcast.title", "episode.podcast.title", "podcast.title"],
        str,
    )
    duration = first_json_key_match(page_html, DURATION_KEY_RE)
    publish_time = first_json_key_match(page_html, DATE_KEY_RE)

    if not episode_title:
        episode_title = meta_content(page_html, "og:title") or meta_content(page_html, "twitter:title")
    if episode_title:
        metadata.append(("单集标题", normalize_text(str(episode_title)).strip()))
    if podcast_title:
        metadata.append(("节目", normalize_text(str(podcast_title)).strip()))
    metadata.append(("原始链接", page_url))
    if publish_time:
        metadata.append(("发布时间", normalize_datetime(publish_time[1])))
    if duration:
        metadata.append(("音频时长", normalize_duration(duration[1])))
    if audio_url:
        metadata.append(("音频直链", audio_url))

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, value in metadata:
        if key in seen or not value:
            continue
        seen.add(key)
        deduped.append((key, value))
    return deduped


def dedupe_lines(text: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def extract_show_notes(
    page_html: str,
    visible_text: str | None = None,
    page_url: str | None = None,
    audio_url: str | None = None,
) -> str | None:
    parts: list[str] = []
    title = meta_content(page_html, "og:title") or meta_content(page_html, "twitter:title")
    desc = (
        meta_content(page_html, "og:description")
        or meta_content(page_html, "description")
        or meta_content(page_html, "twitter:description")
    )

    if title:
        parts.append(f"# {title}")
    metadata = extract_episode_metadata(page_html, page_url or "", audio_url)
    if metadata:
        metadata_lines = "\n".join(f"- {key}: {value}" for key, value in metadata)
        parts.append("## 元数据\n\n" + metadata_lines)
    if desc:
        parts.append("## 节目简介\n\n" + desc)

    json_candidates = collect_json_text(page_html)
    if json_candidates:
        json_parts = []
        for path, text in sorted(json_candidates, key=lambda item: score_key(item[0]), reverse=True):
            if text == title or text == desc:
                continue
            if len(text) > 5000:
                text = text[:5000].rstrip() + "\n\n[已截断：字段过长]"
            json_parts.append(f"### {path}\n\n{text}")
        if json_parts:
            parts.append("## 页面结构化文本\n\n" + "\n\n".join(json_parts[:12]))

    body_text = visible_text or strip_html(page_html)
    body_text = dedupe_lines(normalize_text(body_text))
    timestamp_lines = "\n".join(match.group(0).strip() for match in TIMESTAMP_RE.finditer(body_text))
    if timestamp_lines:
        parts.append("## 时间戳大纲候选\n\n" + timestamp_lines)

    if not parts and body_text:
        clipped = body_text[:8000].rstrip()
        parts.append("## 页面可见文本\n\n" + clipped)

    if not parts:
        return None

    return (
        "\n\n".join(parts).strip()
        + "\n\n---\n\n"
        + "说明：本文件来自小宇宙页面 HTML/渲染文本提取，只作为辅助元数据；正式学习笔记仍以 transcript.md 为事实底座。\n"
    )


def filename_from_audio_url(audio_url: str) -> str:
    name = Path(unquote(urlparse(audio_url).path)).name
    return name if name.endswith(".m4a") else "audio.m4a"


def download_file(url: str, output: Path) -> None:
    headers = {"User-Agent": "Mozilla/5.0"}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import requests
    except ImportError:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=90) as response, output.open("wb") as file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file.write(chunk)
        return

    with requests.get(url, headers=headers, stream=True, timeout=90) as response:
        response.raise_for_status()
        with output.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从小宇宙单集页提取 media.xyzcdn.net 音频直链，下载音频，并保存 show notes。"
    )
    parser.add_argument("url", help="小宇宙单集页面 URL")
    parser.add_argument("--audio-out", default=None, help="音频输出路径，默认使用 URL 文件名或 audio.m4a")
    parser.add_argument("--notes-out", default="show-notes.md", help="show notes 输出路径")
    parser.add_argument("--skip-audio", action="store_true", help="只提取 show notes，不下载音频")
    parser.add_argument("--skip-notes", action="store_true", help="只下载音频，不保存 show notes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    page_url = args.url
    host = urlparse(page_url).netloc
    if "xiaoyuzhoufm.com" not in host:
        print("提示：输入 URL 看起来不是 xiaoyuzhoufm.com，将仍然尝试解析。", file=sys.stderr)

    print("尝试普通 HTTP 请求...")
    try:
        page_html = request_page(page_url)
    except Exception as exc:
        print(f"普通 HTTP 请求失败：{exc}", file=sys.stderr)
        page_html = ""

    audio_url = extract_audio_url(page_html) if page_html else None
    show_notes = (
        None
        if args.skip_notes
        else extract_show_notes(page_html, page_url=page_url, audio_url=audio_url)
        if page_html
        else None
    )

    if (not audio_url and not args.skip_audio) or (not show_notes and not args.skip_notes):
        print("普通 HTML 信息不完整，尝试 Playwright 渲染页面...")
        try:
            rendered_html, visible_text, captured_urls = render_page(page_url)
        except RuntimeError as exc:
            if not audio_url and not args.skip_audio:
                print(str(exc), file=sys.stderr)
            rendered_html, visible_text, captured_urls = "", "", []

        if not audio_url:
            audio_url = extract_audio_url(rendered_html)
        if not audio_url:
            for captured_url in captured_urls:
                audio_url = extract_audio_url(captured_url)
                if audio_url:
                    break
        if not show_notes and not args.skip_notes and rendered_html:
            show_notes = extract_show_notes(rendered_html, visible_text, page_url=page_url, audio_url=audio_url)

    if not audio_url and not args.skip_audio:
        print(
            "未找到 media.xyzcdn.net 下的 .m4a 音频地址。"
            "可能页面结构已变化、需要登录、音频域名不同，或平台未暴露直链。",
            file=sys.stderr,
        )
        return 2

    if not show_notes and not args.skip_notes:
        print("未提取到 show notes；将只处理音频。", file=sys.stderr)

    if audio_url and not args.skip_audio:
        audio_out = Path(args.audio_out) if args.audio_out else Path(filename_from_audio_url(audio_url))
        print(f"找到音频地址：{audio_url}")
        print(f"下载音频到：{audio_out}")
        download_file(audio_url, audio_out)
        print(f"音频下载完成：{audio_out.resolve()}")

    if show_notes and not args.skip_notes:
        notes_out = Path(args.notes_out)
        notes_out.parent.mkdir(parents=True, exist_ok=True)
        notes_out.write_text(show_notes, encoding="utf-8")
        print(f"show notes 已保存：{notes_out.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
