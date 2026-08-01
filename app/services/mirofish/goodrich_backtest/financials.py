"""시점 정확 재무 신호.

회계연도로 자르면 안 된다. 삼성전자 FY2025 사업보고서는 **2026-03-10** 에
접수됐으므로, 2026년 1~2월 시점에는 존재하지 않는다. `scripts/collect_dart_financials.py`
가 저장한 `rcept_dt`(접수일자) 로 잘라야 한다. 실측상 정정공시 때문에 FY2023 이
2026-06 에 접수되는 경우도 있어, **회계연도가 아니라 접수일 기준 최신**을 골라야 한다.

접수 시각을 모르므로 접수일 당일은 배제한다 — `disclosures` 와 같은 규칙이다.

역할은 알파 발굴이 아니라 **회피**다. 자본잠식·고레버리지·영업적자는 T+1~T+5
구간에서도 급락 위험을 키운다. 재무를 못 받은 종목은 감점하지 않는다(중립) —
신규상장이나 수집 누락을 위험으로 오인하면 안 된다.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_FINANCIAL_DIR = os.path.join(REPO_ROOT, 'data', 'dart_financials')

MAX_SCORE = 2.0
MIN_SCORE = -3.0

CAPITAL_IMPAIRMENT_PENALTY = MIN_SCORE     # 자본잠식은 다른 항목을 볼 필요가 없다
HIGH_LEVERAGE_RATIO = 300.0
MID_LEVERAGE_RATIO = 200.0
STRONG_MARGIN_PCT = 10.0
FAIR_MARGIN_PCT = 5.0

NET_INCOME_KEYS = ('당기순이익(손실)', '당기순이익')


def _account(accounts: dict[str, float], *names: str) -> float | None:
    for name in names:
        value = accounts.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def metrics(snapshot: dict[str, Any] | None) -> dict[str, float | None]:
    """재무 스냅샷 -> 비율. 계산 불가 항목은 None."""
    accounts = (snapshot or {}).get('accounts') or {}
    equity = _account(accounts, '자본총계')
    debt = _account(accounts, '부채총계')
    revenue = _account(accounts, '매출액')
    operating = _account(accounts, '영업이익')
    net = _account(accounts, *NET_INCOME_KEYS)

    leverage = None
    if equity is not None and debt is not None and equity > 0:
        leverage = round(debt / equity * 100, 4)

    margin = None
    if revenue is not None and operating is not None and revenue > 0:
        margin = round(operating / revenue * 100, 4)

    return {
        'equity': equity,
        'leverage_pct': leverage,
        'operating_margin_pct': margin,
        'operating_profit': operating,
        'net_income': net,
    }


def health_score(snapshot: dict[str, Any] | None) -> float:
    """재무 건전성 점수. 스냅샷이 없으면 0(중립)."""
    if not snapshot:
        return 0.0
    values = metrics(snapshot)
    equity = values['equity']
    if equity is not None and equity <= 0:
        return CAPITAL_IMPAIRMENT_PENALTY      # 자본잠식

    score = 0.0
    leverage = values['leverage_pct']
    if leverage is not None:
        if leverage > HIGH_LEVERAGE_RATIO:
            score -= 1.5
        elif leverage > MID_LEVERAGE_RATIO:
            score -= 0.75

    operating = values['operating_profit']
    if operating is not None and operating < 0:
        score -= 1.0

    margin = values['operating_margin_pct']
    if margin is not None:
        if margin > STRONG_MARGIN_PCT:
            score += 1.0
        elif margin > FAIR_MARGIN_PCT:
            score += 0.5

    net = values['net_income']
    if net is not None and net < 0:
        score -= 0.5

    return round(max(MIN_SCORE, min(MAX_SCORE, score)), 4)


class FinancialBook:
    """티커별 재무 스냅샷. 조회는 항상 접수일 기준으로 잘린다."""

    def __init__(self, by_ticker: dict[str, list[dict[str, Any]]]):
        # 접수일 오름차순. 같은 날 접수는 회계연도가 큰 쪽을 뒤에 둔다.
        self._by_ticker = {
            ticker: sorted(rows, key=lambda r: (r.get('rcept_dt', ''), r.get('bsns_year', '')))
            for ticker, rows in by_ticker.items()
        }

    def tickers(self) -> list[str]:
        return sorted(self._by_ticker)

    def latest(self, ticker: str, date: str) -> dict[str, Any] | None:
        """date 이전에 접수된 것 중 가장 최근 스냅샷. 당일은 제외."""
        rows = self._by_ticker.get(ticker)
        if not rows:
            return None
        try:
            limit = datetime.date.fromisoformat(date).strftime('%Y%m%d')
        except ValueError:
            return None
        visible = [row for row in rows if row.get('rcept_dt', '') < limit]
        return visible[-1] if visible else None

    def health_score(self, ticker: str, date: str) -> float:
        return health_score(self.latest(ticker, date))

    def metrics(self, ticker: str, date: str) -> dict[str, float | None]:
        return metrics(self.latest(ticker, date))


def load_financials(directory: str | None = None) -> FinancialBook:
    """연도별 JSONL 을 읽어 FinancialBook 을 만든다. 없으면 빈 book."""
    target = directory or DEFAULT_FINANCIAL_DIR
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    if not os.path.isdir(target):
        return FinancialBook({})

    for path in sorted(glob.glob(os.path.join(target, '*.jsonl'))):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ticker = str(row.get('stock_code') or '').strip()
                if len(ticker) != 6 or not row.get('rcept_dt'):
                    continue
                by_ticker.setdefault(ticker, []).append(row)
    return FinancialBook(by_ticker)
