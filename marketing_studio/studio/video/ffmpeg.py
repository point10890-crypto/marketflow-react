"""ffmpeg 탐색/실행 — 명시 경로 → PATH → imageio-ffmpeg 내장 바이너리."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("studio.video.ffmpeg")

_WINDOWS_CANDIDATES = [
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\marketing_studio\tools\ffmpeg\bin\ffmpeg.exe",
]


class RenderError(RuntimeError):
    pass


def _valid(path: str | None) -> bool:
    if not path:
        return False
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20)
        return out.returncode == 0 and "ffmpeg" in (out.stdout or "").lower()
    except Exception:
        return False


def find_ffmpeg(explicit: str | None = None) -> str | None:
    candidates: list[str | None] = [explicit, os.environ.get("STUDIO_FFMPEG"), shutil.which("ffmpeg")]
    try:
        import imageio_ffmpeg  # type: ignore

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    candidates.extend(_WINDOWS_CANDIDATES)
    for c in candidates:
        if c and Path(c).exists() and _valid(c):
            return str(c)
    return None


def ffmpeg_version(path: str) -> str:
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"ffmpeg version (\S+)", out or "")
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


def run_ffmpeg(ffmpeg: str, args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"ffmpeg 시간 초과 ({timeout}s)") from e
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg 실패 (code {proc.returncode}): {(proc.stderr or '')[-600:]}")
    return proc


def probe_duration(ffmpeg: str, media_path: str | Path) -> float | None:
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-i", str(media_path), "-f", "null", "-"], capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return round(h * 3600 + mi * 60 + s, 3)
