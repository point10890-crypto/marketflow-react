# 뉴스, 공시, 차트, API 데이터를 GraphRAG 입력용 표준 소스 패킷으로 정규화한다.
"""Source packet helpers for MiroFish Hybrid RAG.

This module is deliberately storage-neutral.  Today it normalizes MarketFlow's
file-backed artifacts into compact packets.  Later the same packet shape can be
served through MCP tools, written to a vector store, or projected into a graph
database without changing the analysis pipeline contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


SOURCE_TYPES = ('chart', 'filing', 'news', 'signal', 'api')


def collect_source_packets(
    *,
    resolved: dict[str, Any],
    price: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    briefings: list[dict[str, Any]] | None = None,
    dart: dict[str, Any] | None = None,
    kis: dict[str, Any] | None = None,
    max_packets: int = 32,
) -> list[dict[str, Any]]:
    """Return normalized context packets for chart, filing, news, signal, and API data."""
    packets: list[dict[str, Any]] = []
    display = _display_name(resolved)
    symbol = str((resolved or {}).get('symbol') or '')

    if isinstance(price, dict) and price.get('found'):
        packets.append(_packet(
            source_type='chart',
            source='daily_prices' if price.get('source') != 'kis_api' else 'kis_quote',
            title=f'{display} chart snapshot',
            text=(
                f"Chart snapshot for {display} ({symbol}): price={price.get('price')} KRW, "
                f"change_pct={price.get('change_pct')}, open={price.get('open')}, "
                f"high={price.get('high')}, low={price.get('low')}, volume={price.get('volume')}, "
                f"date={price.get('date')}."
            ),
            symbol=symbol,
            source_file=_first(price.get('sources')),
            observed_at=price.get('updated_at') or price.get('date'),
            confidence=0.9 if price.get('source') == 'kis_api' else 0.82,
            metadata=_compact_meta(price, exclude={'sources'}),
        ))

    if isinstance(kis, dict) and kis.get('found'):
        quote = kis.get('quote') or {}
        investor = kis.get('investor') or {}
        if quote:
            packets.append(_packet(
                source_type='api',
                source='KIS API',
                title=f'{display} KIS live quote',
                text=(
                    f"KIS live quote for {display} ({symbol}): price={quote.get('price')} KRW, "
                    f"change={quote.get('change')}, change_pct={quote.get('change_pct')}, "
                    f"trading_value={quote.get('trading_value')}, market_cap_eok={quote.get('market_cap_eok')}, "
                    f"per={quote.get('per')}, pbr={quote.get('pbr')}."
                ),
                symbol=symbol,
                source_file=_first(kis.get('sources')),
                observed_at=kis.get('fetched_at'),
                confidence=0.95,
                metadata=_compact_meta(quote),
            ))
        if investor:
            packets.append(_packet(
                source_type='api',
                source='KIS API',
                title=f'{display} KIS investor flow',
                text=(
                    f"KIS investor flow for {display} ({symbol}): "
                    f"foreign_net_qty={investor.get('foreign_net_qty')}, "
                    f"institution_net_qty={investor.get('institution_net_qty')}, "
                    f"individual_net_qty={investor.get('individual_net_qty')}."
                ),
                symbol=symbol,
                source_file=_first(kis.get('sources')),
                observed_at=kis.get('fetched_at'),
                confidence=0.92,
                metadata=_compact_meta(investor),
            ))

    if isinstance(dart, dict) and dart:
        latest = dart.get('latest') or {}
        latest_text = _json_preview(latest, limit=900)
        packets.append(_packet(
            source_type='filing',
            source='OpenDART cache',
            title=f"{display} DART financial filing snapshot",
            text=(
                f"DART filing snapshot for {display} ({symbol}), latest_year={dart.get('latest_year')}: "
                f"{latest_text}"
            ),
            symbol=symbol,
            source_file=dart.get('source_file'),
            observed_at=dart.get('latest_year'),
            confidence=0.78,
            metadata=_compact_meta(dart, exclude={'latest'}),
        ))

    for name, item in (signals or {}).items():
        if not isinstance(item, dict) or not item:
            continue
        packets.append(_packet(
            source_type='signal',
            source=str(name),
            title=f'{display} {name} signal',
            text=f"{name} signal for {display} ({symbol}): {_json_preview(item, limit=900)}",
            symbol=symbol,
            source_file=item.get('source_file'),
            observed_at=item.get('generated_at') or item.get('date') or item.get('updated_at'),
            confidence=0.72,
            metadata=_compact_meta(item, exclude={'source_file'}),
        ))

    for item in briefings or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text') or '').strip()
        if not text:
            continue
        packets.append(_packet(
            source_type='news',
            source=str(item.get('source') or 'briefing'),
            title=f"{display} briefing/news context",
            text=f"News or briefing context for {display} ({symbol}): {text}",
            symbol=symbol,
            source_file=item.get('source_file'),
            observed_at=item.get('modified_at'),
            confidence=0.68,
            metadata=_compact_meta(item, exclude={'text'}),
        ))

    return packets[:max(1, int(max_packets or 32))]


def build_hybrid_context(source_packets: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize source packet coverage for the run metadata and UI."""
    counts = {source_type: 0 for source_type in SOURCE_TYPES}
    files: set[str] = set()
    freshness: dict[str, int] = {}
    for packet in source_packets or []:
        source_type = str(packet.get('source_type') or 'unknown')
        if source_type in counts:
            counts[source_type] += 1
        source_file = packet.get('source_file')
        if source_file:
            files.add(str(source_file))
        status = str(packet.get('freshness') or 'unknown')
        freshness[status] = freshness.get(status, 0) + 1
    return {
        'mode': 'hybrid_rag_source_packets',
        'packet_count': len(source_packets or []),
        'source_type_counts': counts,
        'source_files': sorted(files),
        'freshness_counts': freshness,
        'ready_for_mcp': True,
    }


def _packet(
    *,
    source_type: str,
    source: str,
    title: str,
    text: str,
    symbol: str,
    source_file: str | None,
    observed_at: Any,
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed = str(observed_at or '').strip()
    return {
        'id': _packet_id(source_type, source, symbol, title),
        'source_type': source_type,
        'source': source,
        'title': title,
        'text': _compact_text(text, 1400),
        'symbol': symbol or None,
        'source_file': source_file or None,
        'observed_at': observed or None,
        'freshness': _freshness(observed),
        'confidence': max(0.0, min(1.0, float(confidence))),
        'metadata': metadata or {},
    }


def _display_name(resolved: dict[str, Any] | None) -> str:
    resolved = resolved or {}
    return str(resolved.get('display_name') or resolved.get('name') or resolved.get('symbol') or 'target')


def _packet_id(source_type: str, source: str, symbol: str, title: str) -> str:
    raw = f'{source_type}:{source}:{symbol}:{title}'.lower()
    return ''.join(ch if ch.isalnum() else '_' for ch in raw).strip('_')[:120]


def _freshness(value: str) -> str:
    if not value:
        return 'unknown'
    parsed = _parse_datetime(value)
    if parsed is None:
        return 'unknown'
    age_days = (datetime.now(timezone.utc) - parsed).total_seconds() / 86400
    if age_days <= 2:
        return 'fresh'
    if age_days <= 7:
        return 'recent'
    return 'stale'


def _parse_datetime(value: str) -> datetime | None:
    value = str(value or '').strip()
    if not value:
        return None
    if len(value) == 4 and value.isdigit():
        return datetime(int(value), 12, 31, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(value[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _compact_text(text: str, limit: int) -> str:
    compact = ' '.join(str(text or '').split())
    return compact if len(compact) <= limit else compact[:limit - 1] + '...'


def _json_preview(value: Any, *, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return _compact_text(text, limit)


def _compact_meta(value: dict[str, Any], *, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    out: dict[str, Any] = {}
    for key, item in (value or {}).items():
        if key in exclude:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            out[str(key)] = item
    return out


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None
