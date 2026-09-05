"""공용 유틸 — 안전 파싱/파일 쓰기/슬러그."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_WS_RE = re.compile(r"\s+")
_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3,})\s*원")
_PRICE_ANY_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})")
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_DATE_RE = re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})일?")
_DATE_SHORT_RE = re.compile(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})(?!\d)")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def short_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def clean_text(text: str | None, max_len: int | None = None) -> str:
    if not text:
        return ""
    out = _WS_RE.sub(" ", str(text)).strip()
    if max_len and len(out) > max_len:
        out = out[: max_len - 1].rstrip() + "…"
    return out


def slugify(text: str, max_len: int = 60, fallback: str = "item") -> str:
    """한글/영문/숫자 유지, 나머지는 하이픈. 파일명/URL 안전."""
    text = clean_text(text).lower()
    text = re.sub(r"[\[\]\(\)\{\}<>\"'`~!@#$%^&*+=|\\/:;,.?]", " ", text)
    text = re.sub(r"[^0-9a-z가-힣\- ]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if not text:
        text = fallback
    return text[:max_len].rstrip("-") or fallback


def parse_price(text: str | None) -> int | None:
    """'12,900원' / '₩12,900' / '12900' → 12900. 실패 시 None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text)
    m = _PRICE_RE.search(s)
    if not m:
        m = _PRICE_ANY_RE.search(s.replace("₩", ""))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_percent(text: str | None) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = _PERCENT_RE.search(str(text))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_period(text: str | None) -> str:
    """텍스트에서 날짜 구간을 'YYYY-MM-DD ~ YYYY-MM-DD' 로 정규화. 없으면 원문 정리본."""
    if not text:
        return ""
    s = clean_text(text)
    dates = [f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in _DATE_RE.findall(s)]
    if len(dates) >= 2:
        return f"{dates[0]} ~ {dates[1]}"
    if len(dates) == 1:
        return dates[0]
    shorts = _DATE_SHORT_RE.findall(s)
    if len(shorts) >= 2:
        year = datetime.now().year
        return f"{year}-{int(shorts[0][0]):02d}-{int(shorts[0][1]):02d} ~ {year}-{int(shorts[1][0]):02d}-{int(shorts[1][1]):02d}"
    return s[:80]


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def atomic_write_json(path: Path | str, data: Any) -> Path:
    return atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def read_json(path: Path | str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def unique(items: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        if item is None or item == "":
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def korean_char_count(text: str) -> int:
    """공백 제외 글자 수 (네이버 블로그 기준 '글자 수')."""
    return len(re.sub(r"\s+", "", text or ""))


def safe_relpath(path: Path | str, base: Path | str) -> str:
    """base 하위 경로면 상대경로 문자열, 아니면 절대경로 문자열."""
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def resolve_under(base: Path | str, rel: str) -> Path | None:
    """rel 이 base 안쪽을 가리킬 때만 절대경로를 돌려준다 (경로 탈출 방지)."""
    base_p = Path(base).resolve()
    target = (base_p / rel).resolve()
    try:
        target.relative_to(base_p)
    except ValueError:
        return None
    return target


_DIGIT_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}
_LATIN_FINAL = set("LMNRlmnr")


def has_final_consonant(word: str) -> bool:
    """마지막 글자 받침 여부 (한글/숫자/영문 근사)."""
    w = re.sub(r"[^0-9a-zA-Z가-힣]", "", word or "")
    if not w:
        return False
    ch = w[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch.isdigit():
        return _DIGIT_FINAL[ch]
    return ch in _LATIN_FINAL


def josa(word: str, with_final: str, without_final: str) -> str:
    """조사 선택: josa('청소기', '은', '는') → '는'. '으로/로' 는 ㄹ받침 예외 처리."""
    if not word:
        return without_final
    final = has_final_consonant(word)
    if with_final == "으로" and final:
        ch = re.sub(r"[^가-힣]", "", word)[-1:] 
        if ch and (ord(ch) - 0xAC00) % 28 == 8:  # ㄹ 받침
            return without_final
    return with_final if final else without_final


def j(word: str, pair: str) -> str:
    """word + 조사. pair 는 '은는' '이가' '을를' '과와' '으로' 형태."""
    table = {"은는": ("은", "는"), "이가": ("이", "가"), "을를": ("을", "를"), "과와": ("과", "와"), "으로": ("으로", "로")}
    a, b = table.get(pair, (pair, pair))
    return f"{word}{josa(word, a, b)}"
