# -*- coding: utf-8 -*-
"""뉴스 RSS 상시 센서 (O1) — 공개 피드만 읽고, 깔때기를 통과한 사건만 원장에 남긴다.

의존성을 늘리지 않기 위해 stdlib XML 파서를 쓴다(feedparser 미설치).
robots/약관을 지키는 공개 RSS 만 대상이며, 로그인 뒤 콘텐츠·스크랩은 하지 않는다.

킬스위치
    OMNI_ENABLED=0                  전체 정지 (네트워크 접근 없음)
    OMNI_SOURCE_<NAME>_ENABLED=0    소스별 정지
    OMNI_NEWS_SOURCES               쉼표 구분 화이트리스트로 소스 제한
"""
from __future__ import annotations

import csv
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.services.omni import funnel, ledger

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
UNIVERSE_PATH = os.path.join(REPO_ROOT, 'data', 'korean_stocks_list.csv')
THEME_PATH = os.path.join(REPO_ROOT, 'data', 'omni', 'themes.json')

FETCH_TIMEOUT = 10
USER_AGENT = 'MarketFlowClaw/1.0 (+news sensor; contact via site)'

# 공개 RSS 만. 등급은 근거 계층 규칙에 따름 — 언론 보도는 B.
#
# 경제면 3개만 돌던 시절 종목 커버리지가 23종목에 그쳤다. 종목 언급 밀도가 높은
# 증시·기업면을 매체별로 추가한다. 아래 URL 은 전부 실측(2026-08-29)으로 응답과
# 파싱 가능성을 확인한 것만 남겼다 — 404/연결 리셋 후보는 등록하지 않는다.
SOURCES = [
    # 연합뉴스
    {'name': 'yonhap_economy', 'grade': 'B',
     'url': 'https://www.yna.co.kr/rss/economy.xml'},
    {'name': 'yonhap_market', 'grade': 'B',
     'url': 'https://www.yna.co.kr/rss/market.xml'},
    # 한국경제
    {'name': 'hankyung_economy', 'grade': 'B',
     'url': 'https://www.hankyung.com/feed/economy'},
    {'name': 'hankyung_finance', 'grade': 'B',
     'url': 'https://www.hankyung.com/feed/finance'},
    # 매일경제
    {'name': 'mk_economy', 'grade': 'B',
     'url': 'https://www.mk.co.kr/rss/30100041/'},
    {'name': 'mk_stock', 'grade': 'B',
     'url': 'https://www.mk.co.kr/rss/50200011/'},
    {'name': 'mk_company', 'grade': 'B',
     'url': 'https://www.mk.co.kr/rss/50100032/'},
    # 머니투데이
    {'name': 'mt_stock', 'grade': 'B',
     'url': 'https://rss.mt.co.kr/mt_news_stock.xml'},
    # 아시아경제
    {'name': 'asiae_stock', 'grade': 'B',
     'url': 'https://www.asiae.co.kr/rss/stock.htm'},
]

_universe_cache: dict[str, str] | None = None


def _env_flag(name: str, default: str = '1') -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def enabled() -> bool:
    return _env_flag('OMNI_ENABLED', '1')


def active_sources() -> list[dict[str, str]]:
    """킬스위치와 화이트리스트를 반영한 소스 목록."""
    allow = {s.strip() for s in os.environ.get('OMNI_NEWS_SOURCES', '').split(',') if s.strip()}
    out = []
    for src in SOURCES:
        name = src['name']
        if allow and name not in allow:
            continue
        if not _env_flag(f'OMNI_SOURCE_{name.upper()}_ENABLED', '1'):
            continue
        out.append(dict(src))
    return out


def load_universe() -> dict[str, str]:
    """종목 코드 → 종목명. 1단 결정론 매칭 사전."""
    global _universe_cache
    if _universe_cache is not None:
        return _universe_cache
    table: dict[str, str] = {}
    try:
        with open(UNIVERSE_PATH, encoding='utf-8-sig', newline='') as fp:
            for row in csv.DictReader(fp):
                code = str(row.get('ticker') or '').strip()
                name = str(row.get('name') or '').strip()
                if code and name:
                    table[code] = name
    except OSError as exc:
        logger.warning('[omni] universe load failed: %s', exc)
    _universe_cache = table
    return table


def load_themes() -> dict[str, str]:
    """키워드 → 테마. 파일이 없으면 빈 사전(테마 매칭은 선택 기능)."""
    import json
    try:
        with open(THEME_PATH, encoding='utf-8') as fp:
            data = json.load(fp)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _fetch(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    import requests

    resp = requests.get(url, timeout=timeout, headers={'User-Agent': USER_AGENT})
    resp.raise_for_status()
    return resp.text


def _text(node: Any, tag: str) -> str:
    child = node.find(tag)
    return (child.text or '').strip() if child is not None and child.text else ''


def _normalize_ts(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError):
        return raw[:40] or None


def parse_rss(xml_text: str, *, source: str, grade: str) -> list[dict[str, Any]]:
    """RSS/Atom 최소 파싱. 깨진 피드는 예외 대신 빈 목록으로 흘린다."""
    try:
        root = ET.fromstring(str(xml_text or ''))
    except ET.ParseError:
        return []

    items = root.findall('.//item')
    if not items:
        items = root.findall('.//{http://www.w3.org/2005/Atom}entry')

    out: list[dict[str, Any]] = []
    for node in items:
        title = _text(node, 'title') or _text(node, '{http://www.w3.org/2005/Atom}title')
        if not title:
            continue
        link = _text(node, 'link')
        if not link:
            atom_link = node.find('{http://www.w3.org/2005/Atom}link')
            link = atom_link.get('href', '') if atom_link is not None else ''
        summary = (_text(node, 'description')
                   or _text(node, '{http://www.w3.org/2005/Atom}summary'))
        published = (_text(node, 'pubDate')
                     or _text(node, '{http://www.w3.org/2005/Atom}updated'))
        out.append({
            'title': title, 'link': link, 'summary': summary,
            'published_ts': _normalize_ts(published),
            'source': source, 'grade': grade,
        })
    return out


def run_news_sweep() -> dict[str, Any]:
    """한 번의 수집 사이클. 실패한 소스는 격리하고 나머지는 그대로 수집한다."""
    started = datetime.now(timezone.utc).isoformat()
    if not enabled():
        return {'status': 'disabled', 'started_at': started,
                'fetched': 0, 'kept': 0, 'saved': 0, 'errors': {}}

    errors: dict[str, str] = {}
    raw_items: list[dict[str, Any]] = []
    sources = active_sources()

    for src in sources:
        try:
            xml_text = _fetch(src['url'])
            raw_items.extend(parse_rss(xml_text, source=src['name'], grade=src['grade']))
        except Exception as exc:  # noqa: BLE001 — 한 소스 장애가 전체를 막지 않는다
            errors[src['name']] = f'{type(exc).__name__}: {exc}'

    kept = funnel.run_funnel(raw_items, load_universe(), load_themes())
    saved = ledger.save_events(kept)

    return {
        'status': 'ok', 'started_at': started,
        'sources': [s['name'] for s in sources],
        'fetched': len(raw_items), 'kept': len(kept), 'saved': saved,
        'errors': errors,
    }
