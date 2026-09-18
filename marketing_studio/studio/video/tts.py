"""TTS — edge-tts(무료, 고품질 한국어) → 실패 시 무음 WAV (파이프라인은 항상 완주)."""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio.utils import clean_text
from studio.video.ffmpeg import probe_duration

log = logging.getLogger("studio.video.tts")

CHARS_PER_SECOND = 4.3


@dataclass
class TTSResult:
    path: str
    duration: float
    engine: str


def estimate_duration(text: str) -> float:
    n = len(clean_text(text).replace(" ", ""))
    return round(max(1.5, n / CHARS_PER_SECOND + 0.5), 2)


def write_silence_wav(path: str | Path, seconds: float, rate: int = 24000) -> str:
    frames = int(max(0.2, seconds) * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * frames)
    return str(path)


def edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:
        return False


def _run_async(coro: Any, timeout: float) -> Any:
    """어떤 스레드/이벤트루프 상황에서도 안전하게 코루틴 실행 (별도 스레드 + 새 루프)."""
    result: dict[str, Any] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
        except BaseException as e:  # noqa: BLE001
            result["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout + 5)
    if t.is_alive():
        raise TimeoutError("TTS 시간 초과")
    if "error" in result:
        raise result["error"]
    return result.get("value")


class TTS:
    def __init__(self, voice: str = "ko-KR-SunHiNeural", rate: str = "+5%", *, ffmpeg: str | None = None, engine: str = "auto", timeout: float = 90) -> None:
        self.voice = voice
        self.rate = rate
        self.ffmpeg = ffmpeg
        self.engine = engine
        self.timeout = timeout
        self.last_error = ""

    def _edge(self, text: str, out_path: Path) -> TTSResult:
        import edge_tts

        async def _save() -> None:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            await communicate.save(str(out_path))

        _run_async(_save(), self.timeout)
        if not out_path.exists() or out_path.stat().st_size < 500:
            raise RuntimeError("edge-tts 출력 파일이 비어 있음")
        duration = probe_duration(self.ffmpeg, out_path) if self.ffmpeg else None
        return TTSResult(str(out_path), duration or estimate_duration(text), "edge-tts")

    def _silent(self, text: str, out_path: Path) -> TTSResult:
        seconds = estimate_duration(text)
        write_silence_wav(out_path, seconds)
        return TTSResult(str(out_path), seconds, "silent")

    def synthesize(self, text: str, out_base: str | Path) -> TTSResult:
        """out_base 는 확장자 없는 경로. 엔진에 따라 .mp3 / .wav 생성."""
        text = clean_text(text)
        base = Path(out_base)
        base.parent.mkdir(parents=True, exist_ok=True)
        if not text:
            return self._silent("잠시만요", base.with_suffix(".wav"))
        engines = [self.engine] if self.engine != "auto" else ["edge", "silent"]
        for engine in engines:
            try:
                if engine == "edge" and edge_tts_available():
                    return self._edge(text, base.with_suffix(".mp3"))
                if engine == "silent":
                    return self._silent(text, base.with_suffix(".wav"))
            except Exception as e:
                self.last_error = f"{engine}: {str(e)[:200]}"
                log.warning("TTS %s 실패 → 다음 엔진: %s", engine, self.last_error)
        return self._silent(text, base.with_suffix(".wav"))
