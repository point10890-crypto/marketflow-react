from pathlib import Path

from conftest import requires_ffmpeg
from PIL import Image

from studio.video.ffmpeg import find_ffmpeg, probe_duration
from studio.video.fonts import find_font, load_font
from studio.video.renderer import RenderScene, VideoRenderer, srt_from_scenes
from studio.video.slides import compose_slide, compose_thumbnail, wrap_text
from studio.video.tts import TTS, estimate_duration, write_silence_wav


def test_wrap_text_and_slides(tmp_path, sample_image):
    from PIL import ImageDraw

    font = load_font(find_font(), 40)
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = wrap_text(draw, "아주 긴 문장을 화면 폭에 맞춰서 여러 줄로 나눠야 합니다 정말로", font, 400, max_lines=2)
    assert 1 <= len(lines) <= 2 and lines[-1].endswith("…") or len(lines) <= 2
    assert wrap_text(draw, "가나다라마바사아자차카타파하" * 3, font, 300)  # 공백 없는 문자열도 처리
    out = compose_slide(out_path=tmp_path / "s.png", image_path=sample_image, caption="무선청소기 고민 끝", subtitle="내레이션", title="상품", label="POINT 1", progress=0.5, font_path=find_font())
    assert Image.open(out).size == (1080, 1920)
    out2 = compose_slide(out_path=tmp_path / "s2.png", image_path=None, caption="이미지 없음", size=(720, 1280))
    assert Image.open(out2).size == (720, 1280)
    thumb = compose_thumbnail(out_path=tmp_path / "t.png", image_path=sample_image, title="제목")
    assert Path(thumb).exists()


def test_silent_tts(tmp_path):
    tts = TTS(engine="silent")
    r = tts.synthesize("첫 번째, 강력 흡입력 210W 로 카펫 먼지까지.", tmp_path / "a")
    assert r.engine == "silent" and r.path.endswith(".wav") and 3 < r.duration < 8
    assert estimate_duration("") == 1.5
    p = write_silence_wav(tmp_path / "b.wav", 1.0)
    assert Path(p).stat().st_size > 40000
    auto = TTS(engine="auto", timeout=1)
    r2 = auto.synthesize("", tmp_path / "c")
    assert r2.engine == "silent"


def test_srt():
    srt = srt_from_scenes([RenderScene("a.png", None, 2.5, caption="자막", narration="내레이션"), RenderScene("b.png", None, 1.0, caption="둘")])
    assert "00:00:00,000 --> 00:00:02,500" in srt and "00:00:02,500 --> 00:00:03,500" in srt and "내레이션" in srt


@requires_ffmpeg
def test_render_video(tmp_path, sample_image):
    ffmpeg = find_ffmpeg()
    s1 = compose_slide(out_path=tmp_path / "s1.png", image_path=sample_image, caption="하나")
    s2 = compose_slide(out_path=tmp_path / "s2.png", image_path=None, caption="둘")
    wav = write_silence_wav(tmp_path / "a.wav", 1.5)
    result = VideoRenderer(ffmpeg, size=(540, 960), fps=24).render(
        [RenderScene(s1, wav, 1.5, "하나", "n1"), RenderScene(s2, None, 1.2, "둘", "n2")], tmp_path / "out.mp4", kenburns=True,
    )
    assert Path(result.path).stat().st_size > 10000 and Path(result.srt).exists() and Path(result.thumbnail).exists()
    assert 2.4 <= (probe_duration(ffmpeg, result.path) or 0) <= 3.4
    assert result.scenes == 2 and result.warnings == []
