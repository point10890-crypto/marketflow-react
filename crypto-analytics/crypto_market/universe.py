from __future__ import annotations
from typing import List, Tuple
import ccxt

def liquidity_bucket_from_quote_volume(qv: float) -> str:
    if qv >= 50_000_000:
        return "A"
    if qv >= 10_000_000:
        return "B"
    return "C"

def build_universe_binance_usdt(exchange: ccxt.Exchange, top_n: int, min_quote_vol_usdt: float) -> List[Tuple[str, float]]:
    """
    Returns list of (symbol, quoteVolumeUSDT), sorted desc.
    Spot only. USDT pairs only.
    """
    tickers = exchange.fetch_tickers()
    items: List[Tuple[str, float]] = []

    banned_fragments = (
        "UP/", "DOWN/", "BULL/", "BEAR/", "3L/", "3S/",  # Leveraged tokens
        "EUR/", "GBP/", "AUD/", "TRY/", "BRL/", "JPY/", "RUB/", "NGN/",  # Fiat currencies
        "BIDR/", "IDRT/", "UAH/", "PLN/", "RON/", "ARS/", "ZAR/",  # More fiat
        "USDC/", "FDUSD/", "TUSD/", "DAI/", "BUSD/", "USDP/", "PYUSD/",  # Stablecoins
    )
    for sym, t in tickers.items():
        if not sym.endswith("/USDT"):
            continue
        if any(b in sym for b in banned_fragments):
            continue
        qv = t.get("quoteVolume", None)
        if qv is None:
            continue
        qv = float(qv)
        if qv < min_quote_vol_usdt:
            continue
        items.append((sym, qv))

    items.sort(key=lambda x: x[1], reverse=True)
    return items[:top_n]
