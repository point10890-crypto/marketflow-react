"""Playwright 브라우저 세션 (영구 프로필 = 네이버 로그인 유지).

- `BrowserSession(profile_dir)` : 프로필 디렉토리에 쿠키/세션을 보관 → 한 번 로그인하면 계속 사용.
- `login_interactive()`        : 창을 띄워 사용자가 직접 네이버 로그인 (자동 로그인은 하지 않음 — 캡차/2단계 인증 대응).
- playwright 는 지연 import → 미설치 환경에서도 패키지 import 가능.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from studio.config import NAVER_LOGIN_URL

log = logging.getLogger("studio.crawler.session")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
"""


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except Exception:
        return False


class LoginRequired(RuntimeError):
    """네이버 로그인이 필요한 페이지에 비로그인 상태로 접근."""


class BrowserSession:
    """동기 Playwright 래퍼. `with BrowserSession(...) as s:` 로 사용."""

    def __init__(
        self,
        profile_dir: Path | str | None = None,
        *,
        headless: bool = True,
        chromium_path: str | None = None,
        viewport: tuple[int, int] = (1280, 900),
        user_agent: str = DEFAULT_UA,
        locale: str = "ko-KR",
        timeout_ms: int = 45000,
    ) -> None:
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.headless = headless
        self.chromium_path = chromium_path
        self.viewport = viewport
        self.user_agent = user_agent
        self.locale = locale
        self.timeout_ms = timeout_ms
        self._pw: Any = None
        self._browser: Any = None
        self.context: Any = None

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def start(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled", f"--lang={self.locale}"],
        }
        if self.chromium_path:
            launch_kwargs["executable_path"] = self.chromium_path
        ctx_kwargs: dict[str, Any] = {
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
            "user_agent": self.user_agent,
            "locale": self.locale,
            "timezone_id": "Asia/Seoul",
        }
        if self.profile_dir:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self.context = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **launch_kwargs, **ctx_kwargs)
        else:
            self._browser = self._pw.chromium.launch(**launch_kwargs)
            self.context = self._browser.new_context(**ctx_kwargs)
        self.context.set_default_timeout(self.timeout_ms)
        try:
            self.context.add_init_script(_STEALTH_JS)
        except Exception:
            pass
        return self

    def close(self) -> None:
        for closer in (
            lambda: self.context.close() if self.context else None,
            lambda: self._browser.close() if self._browser else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                closer()
            except Exception:
                pass
        self.context = self._browser = self._pw = None

    # ------------------------------------------------------------------ pages
    def new_page(self, viewport: tuple[int, int] | None = None) -> Any:
        page = self.context.new_page()
        if viewport:
            page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        return page

    def goto(self, page: Any, url: str, *, wait: str = "domcontentloaded", settle_ms: int = 1200) -> bool:
        try:
            page.goto(url, wait_until=wait, timeout=self.timeout_ms)
        except Exception as e:  # pragma: no cover - 네트워크 의존
            log.warning("goto 실패 %s: %s", url, e)
            return False
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        return True

    def scroll_to_bottom(self, page: Any, *, steps: int = 8, pause_ms: int = 500, step_px: int = 1400) -> None:
        for _ in range(steps):
            try:
                page.mouse.wheel(0, step_px)
                page.wait_for_timeout(pause_ms)
            except Exception:
                break
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
        except Exception:
            pass

    # ------------------------------------------------------------------ cookies / login
    def cookies(self) -> list[dict[str, Any]]:
        try:
            return list(self.context.cookies())
        except Exception:
            return []

    def is_naver_logged_in(self) -> bool:
        names = {c.get("name") for c in self.cookies() if "naver.com" in str(c.get("domain", ""))}
        return "NID_AUT" in names and "NID_SES" in names

    # ------------------------------------------------------------------ fetch
    def fetch_bytes(self, url: str, referer: str | None = None, timeout_ms: int = 20000) -> bytes | None:
        headers = {"Referer": referer} if referer else {}
        try:
            resp = self.context.request.get(url, headers=headers, timeout=timeout_ms)
            if resp.ok:
                return resp.body()
        except Exception as e:
            log.debug("fetch_bytes 실패 %s: %s", url, e)
        return None


# ---------------------------------------------------------------------- login helpers
def login_interactive(
    profile_dir: Path | str,
    *,
    chromium_path: str | None = None,
    url: str = NAVER_LOGIN_URL,
    wait_seconds: int = 600,
    poll_seconds: float = 2.0,
    on_status: Callable[[str], None] | None = None,
) -> bool:
    """헤드풀 브라우저를 열고 사용자가 직접 로그인할 때까지 대기. 로그인 쿠키 감지 시 True."""
    say = on_status or (lambda m: log.info(m))
    with BrowserSession(profile_dir, headless=False, chromium_path=chromium_path) as session:
        page = session.new_page()
        session.goto(page, url, settle_ms=500)
        if session.is_naver_logged_in():
            say("이미 로그인되어 있습니다.")
            return True
        say("브라우저 창에서 네이버 로그인을 완료해 주세요 (캡차/2단계 인증 포함).")
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if session.is_naver_logged_in():
                say("로그인 확인됨 — 세션이 저장되었습니다.")
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                return True
            try:
                page.wait_for_timeout(int(poll_seconds * 1000))
            except Exception:
                break  # 사용자가 창을 닫음
        return session.is_naver_logged_in()


def check_login_status(profile_dir: Path | str, *, chromium_path: str | None = None) -> bool:
    """헤드리스로 프로필을 열어 로그인 쿠키 존재 여부 확인."""
    try:
        with BrowserSession(profile_dir, headless=True, chromium_path=chromium_path, timeout_ms=15000) as session:
            return session.is_naver_logged_in()
    except Exception as e:
        log.warning("로그인 상태 확인 실패: %s", e)
        return False
