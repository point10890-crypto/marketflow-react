# MiroFish Hybrid RAG 소스 패킷 정규화 계층을 검증한다.
from __future__ import annotations

from app.services.mirofish import source_hub


def test_collect_source_packets_normalizes_news_filing_chart_signal_and_api():
    packets = source_hub.collect_source_packets(
        resolved={'symbol': '005930', 'display_name': 'Samsung Electronics'},
        price={
            'found': True,
            'price': 201000,
            'change_pct': -2.43,
            'open': 205000,
            'high': 207000,
            'low': 200500,
            'volume': 1234567,
            'date': '2026-05-08',
            'sources': ['data/daily_prices.csv'],
        },
        signals={
            'leading_screener': {
                'score': 84,
                'label': 'BUY_CANDIDATE',
                'source_file': 'data/screener_leading_latest.json',
                'generated_at': '2026-05-08T09:20:00+00:00',
            },
        },
        briefings=[
            {
                'source': 'market_briefing',
                'source_file': 'data/briefing/latest.json',
                'text': 'Samsung Electronics memory demand improved.',
                'modified_at': '2026-05-08T09:30:00+00:00',
            },
        ],
        dart={
            'latest_year': '2025',
            'latest': {'revenue': 1000, 'operating_profit': 120},
            'source_file': 'data/dart_deep/raw/005930_20260508.json',
        },
        kis={
            'found': True,
            'quote': {'price': 201000, 'change_pct': -2.43, 'trading_value': 1_000_000},
            'investor': {'foreign_net_qty': 12000, 'institution_net_qty': -3000},
            'sources': ['KIS API: inquire-price'],
            'fetched_at': '2026-05-08T09:31:00+00:00',
        },
    )

    source_types = {packet['source_type'] for packet in packets}

    assert {'chart', 'filing', 'news', 'signal', 'api'} <= source_types
    assert all(packet['symbol'] == '005930' for packet in packets)
    assert all(0 <= packet['confidence'] <= 1 for packet in packets)
    assert any('GraphRAG' not in packet['text'] for packet in packets)


def test_build_hybrid_context_counts_packet_coverage():
    packets = [
        {'source_type': 'chart', 'source_file': 'data/daily_prices.csv', 'freshness': 'fresh'},
        {'source_type': 'news', 'source_file': 'data/briefing/latest.json', 'freshness': 'recent'},
        {'source_type': 'news', 'source_file': 'data/briefing/latest.json', 'freshness': 'recent'},
    ]

    summary = source_hub.build_hybrid_context(packets)

    assert summary['mode'] == 'hybrid_rag_source_packets'
    assert summary['packet_count'] == 3
    assert summary['source_type_counts']['chart'] == 1
    assert summary['source_type_counts']['news'] == 2
    assert summary['ready_for_mcp'] is True
