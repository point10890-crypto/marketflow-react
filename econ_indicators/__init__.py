#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Economic Indicators Dashboard - Module Initialization
======================================================
미국/한국 경제지표 통합 대시보드

Version: 2.0 (한국은행 데이터 통합)
"""

from typing import Dict, List

# ============================================================================
# 미국 지표 정의 (FRED + yfinance)
# ============================================================================

US_INDICATORS = {
    'Interest Rates': {
        'source': 'FRED',
        'indicators': {
            'DFF': 'Fed Funds Rate',
            'DTB3': '3-Month T-Bill',
            'DGS2': '2-Year Treasury',
            'DGS10': '10-Year Treasury',
            'DGS30': '30-Year Treasury',
        }
    },
    'Inflation': {
        'source': 'FRED',
        'indicators': {
            'CPIAUCSL': 'CPI All Items',
            'CPILFESL': 'Core CPI',
            'PCEPI': 'PCE Price Index',
            'PCEPILFE': 'Core PCE',
        }
    },
    'Employment': {
        'source': 'FRED',
        'indicators': {
            'UNRATE': 'Unemployment Rate',
            'PAYEMS': 'Nonfarm Payrolls',
            'ICSA': 'Initial Jobless Claims',
            'JTSJOL': 'Job Openings',
        }
    },
    'Money Supply': {
        'source': 'FRED',
        'indicators': {
            'M2SL': 'M2 Money Supply',
            'WALCL': 'Fed Balance Sheet',
        }
    },
    'Housing': {
        'source': 'FRED',
        'indicators': {
            'HOUST': 'Housing Starts',
            'PERMIT': 'Building Permits',
            'CSUSHPINSA': 'Case-Shiller Home Price',
        }
    },
    'Consumer': {
        'source': 'FRED',
        'indicators': {
            'RSAFS': 'Retail Sales',
            'UMCSENT': 'Consumer Sentiment',
            'PCE': 'Personal Consumption',
        }
    },
    'Manufacturing': {
        'source': 'FRED',
        'indicators': {
            'INDPRO': 'Industrial Production',
            'DGORDER': 'Durable Goods Orders',
        }
    },
    'Market Indices': {
        'source': 'yfinance',
        'indicators': {
            '^VIX': 'VIX Volatility',
            'SPY': 'S&P 500 ETF',
            'QQQ': 'Nasdaq 100 ETF',
            '^TNX': '10Y Treasury Yield',
        }
    },
}

# ============================================================================
# 한국 지표 정의 (한국은행 ECOS API)
# ============================================================================

KR_INDICATORS = {
    'Business Survey': {
        'source': 'BOK_ECOS',
        'indicators': {
            'BSI_MFG': {'code': '512Y001/I121Y', 'name': '제조업 BSI'},
            'BSI_NON_MFG': {'code': '512Y001/I122Y', 'name': '비제조업 BSI'},
            'ESI': {'code': '513Y001/I121Y', 'name': '경제심리지수'},
            'CSI': {'code': '511Y002/FME', 'name': '소비자심리지수'},
        }
    },
    'Interest Rates': {
        'source': 'BOK_ECOS',
        'indicators': {
            'BOK_BASE_RATE': {'code': '722Y001/0101000', 'name': '한은 기준금리'},
            'CD_91D': {'code': '817Y002/010502000', 'name': 'CD 91일물'},
            'GOVT_3Y': {'code': '817Y002/010101000', 'name': '국고채 3년'},
            'GOVT_10Y': {'code': '817Y002/010103000', 'name': '국고채 10년'},
        }
    },
    'Prices': {
        'source': 'BOK_ECOS',
        'indicators': {
            'CPI_KR': {'code': '901Y009/0', 'name': '소비자물가지수'},
            'PPI_KR': {'code': '901Y010/0', 'name': '생산자물가지수'},
        }
    },
    'Money & Credit': {
        'source': 'BOK_ECOS',
        'indicators': {
            'M2_KR': {'code': '101Y004/BBGA00', 'name': 'M2 통화량'},
            'HOUSEHOLD_CREDIT': {'code': '151Y001/I0AA', 'name': '가계신용'},
        }
    },
    'Trade': {
        'source': 'BOK_ECOS',
        'indicators': {
            'EXPORT': {'code': '403Y001/0001000', 'name': '수출'},
            'IMPORT': {'code': '403Y001/0002000', 'name': '수입'},
            'CURRENT_ACCOUNT': {'code': '301Y013/0001', 'name': '경상수지'},
        }
    },
    'Exchange Rate': {
        'source': 'BOK_ECOS',
        'indicators': {
            'USDKRW': {'code': '731Y003/0000001', 'name': '원/달러 환율'},
        }
    },
}

# ============================================================================
# 한국 섹터별 점수 시스템 정의
# ============================================================================

KR_SECTOR_SCORES = {
    'SEC': {
        'name_kr': '반도체/IT',
        'name_en': 'Semiconductor/IT',
        'related_indicators': ['BSI_MFG', 'EXPORT'],
        'description': 'K자형 성장의 핵심, AI반도체 호황',
        'weight': 1.5,
    },
    'CON': {
        'name_kr': '건설/부동산',
        'name_en': 'Construction/Real Estate',
        'related_indicators': ['HOUSEHOLD_CREDIT', 'CPI_KR'],
        'description': 'PF리스크, 건설투자 역성장',
        'weight': 1.2,
    },
    'FIN': {
        'name_kr': '금융/은행',
        'name_en': 'Finance/Banking',
        'related_indicators': ['BOK_BASE_RATE', 'HOUSEHOLD_CREDIT'],
        'description': '금리 정책 민감, 가계부채 리스크',
        'weight': 1.0,
    },
    'MFG': {
        'name_kr': '일반제조',
        'name_en': 'Manufacturing',
        'related_indicators': ['BSI_MFG', 'PPI_KR'],
        'description': '경기 동행지표',
        'weight': 1.0,
    },
    'SVC': {
        'name_kr': '서비스',
        'name_en': 'Services',
        'related_indicators': ['BSI_NON_MFG', 'CSI'],
        'description': '내수 경기, 소비심리',
        'weight': 1.0,
    },
    'EXP': {
        'name_kr': '수출/무역',
        'name_en': 'Export/Trade',
        'related_indicators': ['EXPORT', 'CURRENT_ACCOUNT', 'USDKRW'],
        'description': '대외 의존도, 반도체 견인',
        'weight': 1.3,
    },
    'EMP': {
        'name_kr': '고용/노동',
        'name_en': 'Employment',
        'related_indicators': ['ESI'],
        'description': '경기 후행지표',
        'weight': 0.8,
    },
    'CPI': {
        'name_kr': '물가/인플레',
        'name_en': 'Inflation',
        'related_indicators': ['CPI_KR', 'PPI_KR', 'USDKRW'],
        'description': '한은 목표 2%, 환율 영향',
        'weight': 1.0,
    },
}

# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'US_INDICATORS',
    'KR_INDICATORS', 
    'KR_SECTOR_SCORES',
]

# Lazy import for heavy modules
def get_multi_ai_forecaster():
    """Get MultiAIForecaster instance"""
    from .multi_ai_forecaster import MultiAIForecaster
    return MultiAIForecaster()
