"""TradingAgents deep-verification layer (KR-native port).

Ports the TradingAgents (TauricResearch, Apache-2.0) multi-agent methodology
into MarketFlow to deep-verify AI Brain TOP3 detections.

Pipeline (built incrementally):
    data_hub  -> gather a KR-native data bundle for one target
    analysts  -> four analyst reports (fundamentals/news/sentiment/technical)
    (later)   -> bull/bear debate, trader, risk, portfolio manager

Every module reuses existing MiroFish infrastructure (live_data,
technical_analysis, sector_rs, llm_client) and degrades gracefully: each data
source is isolated so one failure never aborts the bundle, and every LLM step
has a deterministic rule fallback.
"""
