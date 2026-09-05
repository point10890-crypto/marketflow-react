"""Studio 설정 — 경로/환경변수 중앙 관리.

모든 경로는 STUDIO_HOME(기본: marketing_studio 디렉토리) 기준 절대경로로 고정한다.
Windows 에서는 `C:\\marketing_studio` 에 통째로 복사해 사용한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parent.parent  # marketing_studio/

NAVER_LOGIN_URL = "https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fbrandconnect.naver.com%2F"
DEFAULT_BRANDCONNECT_URL = "https://brandconnect.naver.com/"
DEFAULT_DISCLOSURE = (
    "이 포스팅은 네이버 브랜드커넥트 제휴 마케팅 활동의 일환으로, "
    "링크를 통해 구매 시 일정 수수료를 제공받을 수 있습니다."
)


def _load_dotenv(path: Path) -> None:
    """python-dotenv 가 있으면 사용, 없으면 최소 파서로 대체 (기존 환경변수 우선)."""
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(path, override=False)
        return
    except Exception:
        pass
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


def _env(name: str, default: str = "", *aliases: str) -> str:
    for key in (name, *aliases):
        value = os.environ.get(key)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "")
    if raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    """런타임 설정. 생성 시 STUDIO_HOME/.env 를 읽는다 (이미 설정된 환경변수 우선)."""

    home: Path = field(default_factory=lambda: Path(_env("STUDIO_HOME", str(STUDIO_ROOT))))

    def __post_init__(self) -> None:
        self.home = Path(self.home).resolve()
        _load_dotenv(self.home / ".env")

        # 경로
        self.data_dir = self.home / "data"
        self.products_dir = self.data_dir / "products"
        self.campaigns_dir = self.data_dir / "campaigns"
        self.profile_dir = self.data_dir / "browser_profile"
        self.probe_dir = self.data_dir / "probe"
        self.output_dir = self.home / "output"
        self.blog_dir = self.output_dir / "blog"
        self.video_dir = self.output_dir / "videos"
        self.package_dir = self.output_dir / "packages"
        self.assets_dir = self.home / "assets"
        self.log_dir = self.home / "logs"
        self.db_path = self.data_dir / "studio.db"

        # 서버
        self.host = _env("STUDIO_HOST", "127.0.0.1")
        self.port = _env_int("STUDIO_PORT", 5080)

        # LLM
        self.llm_order = [
            p.strip().lower()
            for p in _env("STUDIO_LLM_ORDER", "gemini,deepseek,openai,anthropic").split(",")
            if p.strip()
        ]
        self.gemini_api_key = _env("GEMINI_API_KEY")
        self.deepseek_api_key = _env("DEEPSEEK_API_KEY")
        self.openai_api_key = _env("OPENAI_API_KEY")
        self.anthropic_api_key = _env("ANTHROPIC_API_KEY")
        self.gemini_model = _env("STUDIO_GEMINI_MODEL", "gemini-2.5-flash")
        self.deepseek_model = _env("STUDIO_DEEPSEEK_MODEL", "deepseek-chat", "DEEPSEEK_MODEL", "AI_DEEPSEEK_FAST_MODEL")
        self.deepseek_base_url = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.openai_model = _env("STUDIO_OPENAI_MODEL", "gpt-5.5", "OPENAI_FALLBACK_MODEL", "AI_OPENAI_FALLBACK_MODEL")
        self.openai_base_url = _env("OPENAI_BASE_URL", "https://api.openai.com")
        self.anthropic_model = _env("STUDIO_ANTHROPIC_MODEL", "claude-sonnet-5")
        self.llm_timeout = _env_int("STUDIO_LLM_TIMEOUT", 120)

        # 네이버 키워드 도구 (선택)
        self.naver_searchad_api_key = _env("NAVER_SEARCHAD_API_KEY")
        self.naver_searchad_secret = _env("NAVER_SEARCHAD_SECRET")
        self.naver_searchad_customer_id = _env("NAVER_SEARCHAD_CUSTOMER_ID")
        self.naver_client_id = _env("NAVER_CLIENT_ID")
        self.naver_client_secret = _env("NAVER_CLIENT_SECRET")

        # 크롤링
        self.brandconnect_url = _env("STUDIO_BRANDCONNECT_URL", DEFAULT_BRANDCONNECT_URL)
        self.headless = _env_bool("STUDIO_HEADLESS", True)
        self.chromium_path = _env("STUDIO_CHROMIUM_PATH") or None
        self.crawl_timeout_ms = _env_int("STUDIO_CRAWL_TIMEOUT_MS", 45000)
        self.min_screenshots = _env_int("STUDIO_MIN_SCREENSHOTS", 3)
        self.allow_file_urls = _env_bool("STUDIO_ALLOW_FILE_URLS", False)  # 테스트/오프라인 데모용

        # 영상
        self.ffmpeg_path = _env("STUDIO_FFMPEG") or None
        self.tts_voice = _env("STUDIO_TTS_VOICE", "ko-KR-SunHiNeural")
        self.tts_rate = _env("STUDIO_TTS_RATE", "+5%")
        self.font_path = _env("STUDIO_FONT_PATH") or None
        self.video_size = (1080, 1920)
        self.video_fps = _env_int("STUDIO_VIDEO_FPS", 30)

        # 콘텐츠
        self.blog_tone = _env("STUDIO_BLOG_TONE", "친근하고 솔직한")
        self.blog_length = _env_int("STUDIO_BLOG_LENGTH", 2000)
        self.disclosure = _env("STUDIO_DISCLOSURE", DEFAULT_DISCLOSURE)
        self.creator_name = _env("STUDIO_CREATOR_NAME", "")

    # ------------------------------------------------------------------
    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.products_dir,
            self.campaigns_dir,
            self.profile_dir,
            self.probe_dir,
            self.output_dir,
            self.blog_dir,
            self.video_dir,
            self.package_dir,
            self.assets_dir / "bgm",
            self.assets_dir / "fonts",
            self.log_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def llm_keys(self) -> dict[str, str]:
        return {
            "gemini": self.gemini_api_key,
            "deepseek": self.deepseek_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }

    def available_llm_providers(self) -> list[str]:
        keys = self.llm_keys()
        return [p for p in self.llm_order if keys.get(p)]

    def public_dict(self) -> dict:
        """API 키를 마스킹한 설정 요약 (UI 표시용)."""

        def mask(value: str) -> str:
            if not value:
                return ""
            return value[:4] + "…" + value[-2:] if len(value) > 8 else "설정됨"

        return {
            "home": str(self.home),
            "host": self.host,
            "port": self.port,
            "llm_order": self.llm_order,
            "llm_keys": {k: mask(v) for k, v in self.llm_keys().items()},
            "models": {
                "gemini": self.gemini_model,
                "deepseek": self.deepseek_model,
                "openai": self.openai_model,
                "anthropic": self.anthropic_model,
            },
            "naver_searchad": bool(self.naver_searchad_api_key and self.naver_searchad_secret and self.naver_searchad_customer_id),
            "naver_datalab": bool(self.naver_client_id and self.naver_client_secret),
            "brandconnect_url": self.brandconnect_url,
            "headless": self.headless,
            "allow_file_urls": self.allow_file_urls,
            "chromium_path": self.chromium_path or "",
            "ffmpeg_path": self.ffmpeg_path or "",
            "tts_voice": self.tts_voice,
            "tts_rate": self.tts_rate,
            "font_path": self.font_path or "",
            "blog_tone": self.blog_tone,
            "blog_length": self.blog_length,
            "disclosure": self.disclosure,
            "creator_name": self.creator_name,
        }


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings
