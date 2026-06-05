"""Verify KRX holiday detection on miniPC."""
import os, sys
sys.path.insert(0, r"C:\bitman_marketfloww")
os.environ.setdefault("KIS_APP_KEY", "x")
os.environ.setdefault("KIS_APP_SECRET", "x")

from datetime import datetime
from app.services.kis_screener import is_market_open, _is_kr_trading_day

now = datetime.now()
print(f"NOW: {now.strftime('%Y-%m-%d %H:%M %A')}")
print(f"_is_kr_trading_day(NOW): {_is_kr_trading_day(now)}")
print(f"is_market_open(): {is_market_open()}")
