"""ffmpeg 렌더러 — 장면별 클립(이미지+오디오, 켄번즈 줌) → concat → BGM 믹스 → MP4 + 썸네일 + SRT."""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from studio.video.ffmpeg import RenderError, probe_duration, run_ffmpeg

log = logging.getLogger("studio.video.renderer")


@dataclass
class RenderScene:
    image: str
    audio: str | None
    duration: float
    caption: str = ""
    narration: str = ""


@dataclass
class RenderResult:
    path: str
    duration: float
    thumbnail: str = ""
    srt: str = ""
    scenes: int = 0
    warnings: list[str] = field(default_factory=list)


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_from_scenes(scenes: list[RenderScene]) -> str:
    out: list[str] = []
    t = 0.0
    for i, sc in enumerate(scenes, 1):
        text = sc.narration or sc.caption
        out += [str(i), f"{_srt_time(t)} --> {_srt_time(t + sc.duration)}", text, ""]
        t += sc.duration
    return "\n".join(out)


class VideoRenderer:
    def __init__(self, ffmpeg: str, *, size: tuple[int, int] = (1080, 1920), fps: int = 30) -> None:
        self.ffmpeg = ffmpeg
        self.size = size
        self.fps = fps

    def _render_scene(self, sc: RenderScene, out: Path, *, kenburns: bool) -> None:
        w, h = self.size
        frames = max(1, int(round(sc.duration * self.fps)))
        if kenburns:
            vf = (
                f"scale={w * 3 // 2}:{h * 3 // 2},"
                f"zoompan=z='min(zoom+0.0006,1.10)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={self.fps},"
                f"format=yuv420p"
            )
            video_in = ["-i", sc.image]
        else:
            vf = f"scale={w}:{h},format=yuv420p"
            video_in = ["-loop", "1", "-framerate", str(self.fps), "-i", sc.image]
        if sc.audio and Path(sc.audio).exists():
            audio_in = ["-i", sc.audio]
        else:
            audio_in = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        args = [
            *video_in, *audio_in,
            "-t", f"{sc.duration:.3f}",
            "-vf", vf,
            "-af", "apad",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(self.fps),
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        run_ffmpeg(self.ffmpeg, args, timeout=max(120, int(sc.duration * 20)))

    def render(
        self,
        scenes: list[RenderScene],
        out_path: str | Path,
        *,
        bgm_path: str | None = None,
        bgm_volume: float = 0.12,
        kenburns: bool = True,
        thumbnail_src: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> RenderResult:
        if not scenes:
            raise RenderError("장면이 없습니다")
        say = progress or (lambda m: log.info(m))
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        work = out_path.parent / f".work_{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        try:
            clips: list[Path] = []
            for i, sc in enumerate(scenes):
                clip = work / f"scene_{i:02d}.mp4"
                say(f"장면 {i + 1}/{len(scenes)} 렌더링 ({sc.duration:.1f}s)")
                try:
                    self._render_scene(sc, clip, kenburns=kenburns)
                except RenderError as e:
                    if kenburns:
                        warnings.append(f"장면 {i + 1} 켄번즈 실패 → 정지 화면: {e}")
                        self._render_scene(sc, clip, kenburns=False)
                    else:
                        raise
                clips.append(clip)
            list_file = work / "list.txt"
            list_file.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
            concat = work / "concat.mp4"
            say("장면 이어붙이기")
            try:
                run_ffmpeg(self.ffmpeg, ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(concat)])
            except RenderError:
                run_ffmpeg(self.ffmpeg, ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(concat)])
            final_src = concat
            if bgm_path and Path(bgm_path).exists():
                say("배경음악 믹스")
                mixed = work / "mixed.mp4"
                try:
                    run_ffmpeg(self.ffmpeg, [
                        "-i", str(concat), "-stream_loop", "-1", "-i", bgm_path,
                        "-filter_complex", f"[1:a]volume={bgm_volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(mixed),
                    ])
                    final_src = mixed
                except RenderError as e:
                    warnings.append(f"BGM 믹스 실패 → 원본 오디오 유지: {e}")
            shutil.move(str(final_src), str(out_path))
            duration = probe_duration(self.ffmpeg, out_path) or round(sum(s.duration for s in scenes), 2)
            thumb = out_path.with_name(out_path.stem + "_thumb.png")
            src_thumb = thumbnail_src or scenes[0].image
            try:
                shutil.copyfile(src_thumb, thumb)
            except OSError:
                thumb = Path("")
            srt = out_path.with_suffix(".srt")
            srt.write_text(srt_from_scenes(scenes), encoding="utf-8")
            return RenderResult(path=str(out_path), duration=duration, thumbnail=str(thumb) if thumb else "", srt=str(srt), scenes=len(scenes), warnings=warnings)
        finally:
            shutil.rmtree(work, ignore_errors=True)
