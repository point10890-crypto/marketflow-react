"""
📁 중앙 데이터 경로 설정

모든 데이터 파일 경로를 한 곳에서 관리합니다.
코드에서 직접 경로를 하드코딩하지 말고 이 모듈을 import하세요.

사용법:
    from config.data_paths import DATA_PATHS
    
    df = pd.read_csv(DATA_PATHS.KR_DAILY_PRICES)
    signals = pd.read_csv(DATA_PATHS.KR_SIGNALS)
"""

from pathlib import Path

# 프로젝트 루트와 데이터 루트
PROJECT_ROOT = Path(__file__).parent.parent
DATA_ROOT = PROJECT_ROOT / "data"


class DataPaths:
    """데이터 파일 경로 모음"""
    
    def __init__(self):
        self.ROOT = DATA_ROOT
        
        # ============================================================
        # 🇰🇷 KR Market
        # ============================================================
        self.KR_ROOT = DATA_ROOT / "kr_market"
        
        # Prices
        self.KR_DAILY_PRICES = self.KR_ROOT / "prices" / "daily_prices.csv"
        
        # Signals
        self.KR_SIGNALS = self.KR_ROOT / "signals" / "smart_money_picks.csv"
        self.KR_SIGNALS_LOG = self.KR_ROOT / "signals" / "signals_log.csv"
        self.KR_HISTORICAL_SIGNALS = self.KR_ROOT / "signals" / "historical_signals.csv"
        self.KR_HISTORICAL_SIGNALS_RETURNS = self.KR_ROOT / "signals" / "historical_signals_with_returns.csv"
        
        # Institutional
        self.KR_INSTITUTIONAL_TREND = self.KR_ROOT / "institutional" / "all_institutional_trend_data.csv"
        self.KR_INSTITUTIONAL_META = self.KR_ROOT / "institutional" / "all_institutional_metadata.csv"
        self.KR_INSTITUTIONAL_SUMMARY = self.KR_ROOT / "institutional" / "institutional_summary.csv"
        self.KR_INSTITUTIONAL_HISTORY = self.KR_ROOT / "institutional" / "historical_institutional_data.csv"
        
        # Backtest
        self.KR_BACKTEST = self.KR_ROOT / "backtest" / "backtest_results.csv"
        self.KR_BACKTEST_ADVANCED = self.KR_ROOT / "backtest" / "backtest_results_advanced.csv"
        self.KR_BACKTEST_FINAL = self.KR_ROOT / "backtest" / "final_backtest_results.csv"
        self.KR_CLOSING_BET_BACKTEST = self.KR_ROOT / "backtest" / "closing_bet_optimization_results.csv"
        
        # AI
        self.KR_AI_ANALYSIS = self.KR_ROOT / "ai" / "kr_ai_analysis.json"
        self.KR_DAILY_REPORT = self.KR_ROOT / "ai" / "daily_report.json"
        self.KR_STRATEGY_PERFORMANCE = self.KR_ROOT / "ai" / "strategy_performance.json"
        
        # History
        self.KR_HISTORY = self.KR_ROOT / "history"
        
        # Other
        self.KR_TICKER_MAP = self.KR_ROOT / "ticker_to_yahoo_map.csv"
        
        # ============================================================
        # 🇺🇸 US Market
        # ============================================================
        self.US_ROOT = DATA_ROOT / "us_market"
        
        # Signals
        self.US_SIGNALS = self.US_ROOT / "signals" / "smart_money_picks.csv"
        self.US_SIGNALS_V2 = self.US_ROOT / "signals" / "smart_money_picks_v2.csv"
        self.US_SUPER_PERFORMANCE = self.US_ROOT / "signals" / "super_performance_picks.csv"
        self.US_SIGNALS_CURRENT = self.US_ROOT / "signals" / "smart_money_current.json"
        
        # Macro
        self.US_MACRO_ANALYSIS = self.US_ROOT / "macro" / "macro_analysis.json"
        self.US_MACRO_ANALYSIS_EN = self.US_ROOT / "macro" / "macro_analysis_en.json"
        self.US_MACRO_GPT = self.US_ROOT / "macro" / "macro_analysis_gpt.json"
        self.US_MACRO_GPT_EN = self.US_ROOT / "macro" / "macro_analysis_gpt_en.json"
        self.US_ETF_FLOW = self.US_ROOT / "macro" / "etf_flow_analysis.json"
        self.US_SECTOR_HEATMAP = self.US_ROOT / "macro" / "sector_heatmap.json"
        self.US_OPTIONS_FLOW = self.US_ROOT / "macro" / "options_flow.json"
        
        # AI
        self.US_AI_SUMMARIES = self.US_ROOT / "ai" / "ai_summaries.json"
        self.US_TOP10_REPORT = self.US_ROOT / "ai" / "final_top10_report.json"
        self.US_EARNINGS = self.US_ROOT / "ai" / "earnings_analysis.json"
        
        # Other
        self.US_DAILY_PRICES = self.US_ROOT / "us_daily_prices.csv"
        self.US_VOLUME = self.US_ROOT / "us_volume_analysis.csv"
        self.US_ETF_FLOWS_CSV = self.US_ROOT / "us_etf_flows.csv"
        self.US_13F = self.US_ROOT / "us_13f_holdings.csv"
        self.US_PORTFOLIO_RISK = self.US_ROOT / "portfolio_risk.json"
        self.US_INSIDER = self.US_ROOT / "insider_moves.json"
        
        # History
        self.US_HISTORY = self.US_ROOT / "history"
        
        # ============================================================
        # ₿ Crypto
        # ============================================================
        self.CRYPTO_ROOT = DATA_ROOT / "crypto"
        self.CRYPTO_TIMELINE = self.CRYPTO_ROOT / "timeline" / "timeline_events.json"
        self.CRYPTO_BACKTEST = self.CRYPTO_ROOT / "backtest"
        
        # ============================================================
        # 📈 Economic
        # ============================================================
        self.ECON_ROOT = DATA_ROOT / "econ"
        self.ECON_BOK = self.ECON_ROOT / "bok"
        self.ECON_FRED = self.ECON_ROOT / "fred"
        
        # ============================================================
        # 📋 Common
        # ============================================================
        self.COMMON_ROOT = DATA_ROOT / "common"
        self.KR_STOCKS_LIST = self.COMMON_ROOT / "korean_stocks_list.csv"
        self.US_STOCKS_LIST = self.COMMON_ROOT / "us_stocks_list.csv"
    
    def ensure_dirs(self):
        """모든 데이터 디렉토리 생성"""
        dirs = [
            self.KR_ROOT / "prices",
            self.KR_ROOT / "signals",
            self.KR_ROOT / "institutional",
            self.KR_ROOT / "backtest",
            self.KR_ROOT / "ai",
            self.KR_HISTORY,
            self.US_ROOT / "signals",
            self.US_ROOT / "macro",
            self.US_ROOT / "ai",
            self.US_HISTORY,
            self.CRYPTO_ROOT / "timeline",
            self.CRYPTO_BACKTEST,
            self.ECON_BOK,
            self.ECON_FRED,
            self.COMMON_ROOT,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


# 싱글톤 인스턴스
DATA_PATHS = DataPaths()


# 레거시 호환성을 위한 함수들
def get_kr_daily_prices_path() -> Path:
    return DATA_PATHS.KR_DAILY_PRICES

def get_kr_signals_path() -> Path:
    return DATA_PATHS.KR_SIGNALS

def get_us_signals_path() -> Path:
    return DATA_PATHS.US_SIGNALS

def get_kr_stocks_list_path() -> Path:
    return DATA_PATHS.KR_STOCKS_LIST


if __name__ == "__main__":
    # 테스트
    print("📁 데이터 경로 설정")
    print(f"   DATA_ROOT: {DATA_PATHS.ROOT}")
    print(f"   KR_DAILY_PRICES: {DATA_PATHS.KR_DAILY_PRICES}")
    print(f"   KR_SIGNALS: {DATA_PATHS.KR_SIGNALS}")
    print(f"   US_SIGNALS: {DATA_PATHS.US_SIGNALS}")
    print(f"   KR_STOCKS_LIST: {DATA_PATHS.KR_STOCKS_LIST}")
    
    # 파일 존재 확인
    print()
    files_to_check = [
        DATA_PATHS.KR_DAILY_PRICES,
        DATA_PATHS.KR_SIGNALS,
        DATA_PATHS.US_SIGNALS,
        DATA_PATHS.KR_STOCKS_LIST,
    ]
    for f in files_to_check:
        status = "✅" if f.exists() else "❌"
        print(f"   {status} {f.name}")
