#!/usr/bin/env python3
"""Batch-transcribe podcast episodes from audio direct links with FunASR.

This wraps the single-file ``transcribe_funasr.py`` for the common case: you
have a list of audio URLs (e.g. ``media.xyzcdn.net/...m4a``) and want a markdown
transcript for each. The win over looping the single-file script externally is
that the heavy ``AutoModel`` (paraformer + vad + punc + cam++) is built *once*
and reused across every episode — model load dominates wall-clock for short
audio, so building it per-file would multiply that cost by N.

Inputs (either or both):
  - URLs passed positionally on the command line.
  - ``--from-file FILE``: one entry per line. A line may be just a URL, or
    ``URL | custom-name`` to control the output filename. ``#`` lines and blanks
    are ignored.

Each episode is downloaded to ``--audio-dir`` (skipped if already present) and
its transcript written to ``--out-dir/<name>.md``. One failing episode does not
abort the run; a summary is printed at the end.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

# Reuse the single-file script's model + rendering logic so the two stay in sync.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe_funasr import (  # noqa: E402
    build_model,
    render_markdown,
    resolve_device,
)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) podcast-batch-funasr/1.0"
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus"}


def ensure_ffmpeg() -> None:
    """Make a bare ``ffmpeg`` available on PATH.

    FunASR shells out to ``ffmpeg`` (not torchaudio) to decode compressed audio
    like ``.m4a``. On a machine without a system ffmpeg this fails with
    ``No such file or directory: 'ffmpeg'``. Rather than require brew/sudo, fall
    back to the binary bundled by the already-installed ``imageio-ffmpeg``
    package: symlink it as ``ffmpeg`` into a cache dir and prepend that to PATH.
    The bundled binary's real name carries a platform/version suffix, so a plain
    ``ffmpeg`` symlink is what makes the bare-command lookup succeed.
    """
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
    except ImportError:
        return  # nothing we can do; FunASR will surface the original error
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    bin_dir = Path.home() / ".cache" / "podcast-funasr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / "ffmpeg"
    if not link.exists():
        link.symlink_to(exe)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


class Job(NamedTuple):
    url: str
    name: str  # output stem, no extension


def slug_from_url(url: str) -> str:
    """Derive a filesystem-safe stem from the URL's last path segment."""
    path = unquote(urlparse(url).path)
    stem = Path(path).stem or "episode"
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in stem)
    return safe.strip("-") or "episode"


def ext_from_url(url: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    return suffix if suffix in AUDIO_EXTS else ".m4a"


def parse_jobs(urls: list[str], from_file: Path | None) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()

    def add(url: str, name: str | None) -> None:
        url = url.strip()
        if not url or url in seen:
            return
        seen.add(url)
        jobs.append(Job(url=url, name=(name or slug_from_url(url))))

    for url in urls:
        add(url, None)

    if from_file:
        for raw in from_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                url_part, name_part = line.split("|", 1)
                add(url_part.strip(), name_part.strip() or None)
            else:
                add(line, None)

    # De-dupe output names by suffixing collisions, so two episodes named the
    # same don't silently overwrite each other.
    used: dict[str, int] = {}
    deduped: list[Job] = []
    for job in jobs:
        if job.name in used:
            used[job.name] += 1
            deduped.append(job._replace(name=f"{job.name}-{used[job.name]}"))
        else:
            used[job.name] = 1
            deduped.append(job)
    return deduped


def download(url: str, dest: Path, *, force: bool) -> Path:
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  已存在，跳过下载：{dest.name}", file=sys.stderr)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp, tmp.open("wb") as fh:
        total = resp.headers.get("Content-Length")
        total_mb = f"{int(total) / 1_048_576:.1f}MB" if total else "未知大小"
        print(f"  下载中（{total_mb}）：{url}", file=sys.stderr)
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    tmp.replace(dest)
    return dest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-transcribe podcast audio direct links with FunASR.",
    )
    parser.add_argument("urls", nargs="*", help="Audio direct links (.m4a/.mp3/...).")
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="File with one entry per line: 'URL' or 'URL | custom-name'.",
    )
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=Path("source/audio"),
        help="Where downloaded audio is cached (default: source/audio).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("source/transcripts"),
        help="Where transcripts are written (default: source/transcripts).",
    )
    parser.add_argument(
        "--device", choices=["auto", "cuda", "cpu"], default="auto",
        help="Inference device. 'auto' picks cuda when available, else cpu.",
    )
    parser.add_argument(
        "--model", default="paraformer-zh",
        help="ASR model (paraformer-zh for Chinese, paraformer-en for English).",
    )
    spk = parser.add_mutually_exclusive_group()
    spk.add_argument(
        "--spk", dest="spk_model", action="store_const", const="cam++",
        help="Enable cam++ speaker diarization (default).",
    )
    spk.add_argument(
        "--no-spk", dest="spk_model", action="store_const", const="",
        help="Disable speaker diarization (faster, plain text).",
    )
    parser.set_defaults(spk_model="cam++")
    parser.add_argument(
        "--hotword", default="",
        help="Space-separated hotwords to bias proper nouns (guest names, etc.).",
    )
    parser.add_argument(
        "--batch-size-s", type=int, default=300,
        help="Dynamic batch length in seconds (lower it on out-of-memory).",
    )
    parser.add_argument(
        "--force-download", action="store_true",
        help="Re-download even if the audio file already exists.",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-transcribe even if the transcript already exists.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_ffmpeg()

    jobs = parse_jobs(args.urls, args.from_file)
    if not jobs:
        print("没有可处理的链接。请传入 URL 或用 --from-file 指定列表。", file=sys.stderr)
        return 1

    device = resolve_device(args.device)
    print(
        f"共 {len(jobs)} 集；设备：{device}；模型：{args.model}；"
        f"说话人模型：{args.spk_model or '（关闭）'}",
        file=sys.stderr,
    )

    # Build the model once. If funasr isn't importable, fail fast before any
    # downloads happen.
    try:
        model = build_model(args.model, args.spk_model, device)
    except ImportError:
        print(
            "未安装 funasr。请先：pip install funasr modelscope torch torchaudio",
            file=sys.stderr,
        )
        return 1

    ok: list[str] = []
    failed: list[tuple[str, str]] = []

    for idx, job in enumerate(jobs, start=1):
        print(f"\n[{idx}/{len(jobs)}] {job.name}", file=sys.stderr)
        out_path = args.out_dir / f"{job.name}.md"
        if out_path.exists() and not args.overwrite:
            print(f"  转写稿已存在，跳过：{out_path}（用 --overwrite 覆盖）", file=sys.stderr)
            ok.append(job.name)
            continue

        try:
            audio_path = args.audio_dir / f"{job.name}{ext_from_url(job.url)}"
            download(job.url, audio_path, force=args.force_download)

            generate_kwargs: dict[str, Any] = {
                "input": str(audio_path),
                "batch_size_s": args.batch_size_s,
            }
            if args.hotword:
                generate_kwargs["hotword"] = args.hotword

            print("  转写中…", file=sys.stderr)
            results = model.generate(**generate_kwargs)
            if not results:
                raise RuntimeError("FunASR 未返回任何结果")

            markdown = render_markdown(
                results[0], model=args.model, spk_model=args.spk_model
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(markdown, encoding="utf-8")
            print(f"  ✓ 写出：{out_path}", file=sys.stderr)
            ok.append(job.name)
        except Exception as exc:  # keep going on a single bad episode
            print(f"  ✗ 失败：{exc}", file=sys.stderr)
            failed.append((job.name, str(exc)))

    print(f"\n完成：成功 {len(ok)}，失败 {len(failed)}。", file=sys.stderr)
    for name, err in failed:
        print(f"  失败 - {name}: {err}", file=sys.stderr)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
