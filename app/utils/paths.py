"""
중앙 경로 상수 — 모든 모듈에서 import하여 사용
"""
import os

# 프로젝트 루트: app/utils/ → app/ → project root
_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_UTILS_DIR)
BASE_DIR = os.path.dirname(_APP_DIR)

# 데이터
DATA_DIR = os.path.join(BASE_DIR, 'data')

# US Market
US_MARKET_DIR = os.path.join(BASE_DIR, 'us_market')
US_OUTPUT_DIR = os.path.join(US_MARKET_DIR, 'output')
US_DATA_DIR = os.path.join(US_MARKET_DIR, 'data')
US_HISTORY_DIR = os.path.join(US_MARKET_DIR, 'history')
US_PREVIEW_DIR = os.path.join(BASE_DIR, 'us_market_preview', 'output')

# Crypto
CRYPTO_ANALYTICS_DIR = os.path.join(BASE_DIR, 'crypto-analytics')
CRYPTO_MARKET_DIR = os.path.join(CRYPTO_ANALYTICS_DIR, 'crypto_market')
CRYPTO_OUTPUT_DIR = os.path.join(CRYPTO_MARKET_DIR, 'output')

# 기타
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
TICKER_MAP_PATH = os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv')
