#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Explain - Grok Collections RAG for market context
"""
from __future__ import annotations
from typing import List, Optional

from market_gate import MarketGateResult
from grok_collections import search_collections, SearchResult


def explain_market_with_collections(
    result: MarketGateResult,
    snapshots_collection_id: Optional[str] = None,
    playbook_collection_id: Optional[str] = None,
) -> str:
    """
    Use Grok Collections to find similar past snapshots and relevant playbook entries.
    
    Returns formatted markdown string.
    """
    lines: List[str] = []
    lines.append(f"# Market Gate Explanation")
    lines.append(f"**Gate**: {result.gate} (Score: {result.score}/100)")
    lines.append("")
    
    # 1. Similar Past Snapshots
    lines.append("## 📊 Similar Past Snapshots")
    if snapshots_collection_id:
        query = (
            f"Find market snapshots similar to: gate={result.gate}, score≈{result.score}, "
            f"btc_atrp≈{result.metrics.get('btc_atrp_14_pct', 'N/A')}, "
            f"alt_breadth≈{result.metrics.get('alt_breadth_above_ema50', 'N/A')}."
        )
        
        hits = search_collections(
            query=query,
            collection_ids=[snapshots_collection_id],
            retrieval_mode="hybrid",
            top_k=5,
        )
        
        if hits:
            for h in hits:
                lines.append(f"- **{h.name}**: {h.snippet}")
        else:
            lines.append("- (검색 결과 없음)")
    else:
        lines.append("- (Snapshots collection 미설정)")
    
    lines.append("")
    
    # 2. Playbook / Preconditions
    lines.append("## 📖 Playbook: 이 상황에서의 전략")
    if playbook_collection_id:
        query2 = (
            f"Crypto market playbook for gate={result.gate}, "
            f"BTC trend conditions, volatility levels, alt breadth. "
            f"What are the preconditions for liquidity inflow and uptrend?"
        )
        
        hits2 = search_collections(
            query=query2,
            collection_ids=[playbook_collection_id],
            retrieval_mode="hybrid",
            top_k=5,
        )
        
        if hits2:
            for h in hits2:
                lines.append(f"- **{h.name}**: {h.snippet}")
        else:
            lines.append("- (검색 결과 없음)")
    else:
        lines.append("- (Playbook collection 미설정)")
    
    return "\n".join(lines)


def format_gate_reasons(result: MarketGateResult) -> str:
    """Gate 상태에 대한 간단한 요약"""
    emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[result.gate]
    
    lines = [
        f"{emoji} **Market Gate: {result.gate}** (Score: {result.score}/100)",
        "",
        "### Why?",
    ]
    
    for r in result.reasons:
        lines.append(f"- {r}")
    
    if result.gate != "GREEN":
        lines.append("")
        lines.append("### What needs to change?")
        
        components = result.metrics.get("gate_score_components", {})
        weak_areas = sorted(components.items(), key=lambda x: x[1])[:2]
        
        for area, score in weak_areas:
            if area == "trend" and score < 20:
                lines.append("→ BTC가 EMA50 위로 복귀 필요")
            elif area == "volatility" and score < 10:
                lines.append("→ ATR% 안정화 필요")
            elif area == "participation" and score < 10:
                lines.append("→ 거래량 증가 필요")
            elif area == "breadth" and score < 10:
                lines.append("→ 알트 breadth 회복 필요")
    
    return "\n".join(lines)
