# Multi-MCP Agentic Alpha Architecture

## Objective

The system optimizes for forward profit quality, not for filling a TOP 3 card.
It may publish zero, one, two, or three candidates. Zero means `cash_wait`.

## Evidence ownership

1. Market MCP owns KIS quotes, session state, regime, fear, and crash gates.
2. Technical MCP owns OHLCV, moving averages, trend, drawdown, and volatility.
3. Evidence MCP owns DART, news, GraphRAG facts, provenance, and freshness.
4. Memory MCP owns look-ahead-safe 1/3/5/20-day outcomes and false positives.
5. Debate MCP runs independent analysts and bull/bear cross-examination.
6. CIO MCP approves, rejects, sizes the candidate set, or selects cash wait.

LLMs never own symbols, prices, targets, stops, disclosures, or performance
numbers. Those fields must come from MCP tools or deterministic calculations.

## Execution graph

```text
KIS candidate detection
  -> parallel Market/Technical/Evidence/Memory MCP evidence packets
  -> deterministic profit-quality gate
  -> technical/fundamental/news/sentiment analysts
  -> bull vs bear cross-examination
  -> trader and risk-team review
  -> CIO approve/reject/cash-wait
  -> outcome memory and replay-safe evaluation
```

## Publication gate

- positive 5-day and 20-day trend
- current price at or above MA20
- trend score at least 8/15
- 20-day drawdown at most 15%
- positive current session
- CIO action BUY/STRONG_BUY/BUY_CANDIDATE
- CIO confidence at least 60

The system never backfills weak candidates to reach three.
