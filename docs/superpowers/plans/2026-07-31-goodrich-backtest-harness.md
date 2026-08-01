# Goodrich 백테스트 하네스 + 랭커 비교 (Phase 1+2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Goodrich 랭킹 함수 후보들을 2년치 실데이터로 공정 비교해, 현행 `_score`보다 나은 것이 있는지를 통계적으로 판정 가능한 상태로 만든다.

**Architecture:** `app/services/mirofish/goodrich_backtest/` 신규 패키지. 과거 세션의 후보 유니버스를 일봉으로 재현(`universe.py`) → look-ahead 금지 신호 계산(`signals.py`) → 랭킹 함수들(`rankers.py`) → 기존 `goodrich_ledger.evaluate_pick`으로 평가하고 진입일 블록 부트스트랩으로 유의성 판정(`engine.py`). 프로덕션 파일은 읽기만 하고 쓰지 않는다.

**Tech Stack:** Python 3.12 (stdlib only — pandas/numpy 불필요), pytest, 기존 `goodrich_ledger` 재사용

**선행 spec:** [`docs/superpowers/specs/2026-07-31-goodrich-return-enhancement-design.md`](../specs/2026-07-31-goodrich-return-enhancement-design.md)

---

## 측정된 사실 (이 plan의 전제)

| 항목 | 값 |
|---|---|
| CSV 총 세션 | 628일 (2024-01-02 ~ 2026-07-31) |
| **중복 `(ticker, date)` 행** | **25,900키 / 28,784행, 9개 세션** — Task 1b 에서 제거 |
| **그 행의 장중에 수집된 행** | **262,976행 (15.1%)** — 저장된 "종가"가 장중 스냅샷. 82.8%는 후일 수집(종가 확정) |
| **사용 가능 세션** | **545일** (그 행의 장중에 수집된 비율 ≤50%). 2024 244/244, 2025 242/242, **2026 59/142** |
| 수집 종목 | 2,967개 |
| `change_rate` 컬럼 신뢰도 | **18.2%만 non-zero** → 연속 종가로 계산 필수 |
| 재현 유니버스 | 세션당 중앙값 54종목 (30~74) |
| 평가 가능 진입일 | T+1 626 / T+3 624 / T+5 622 / T+20 607 |
| 학습 / holdout | **408일 / 137일 (2025-09-04 분할)** — 사용 가능 545일의 75% 지점 |
| 표본 해상도 | 약 0.5%p (α=0.05, power=0.80) |

---

## File Structure

| 파일 | 책임 |
|---|---|
| `app/services/mirofish/goodrich_backtest/__init__.py` | 패키지 마커 + 공개 API re-export |
| `app/services/mirofish/goodrich_backtest/prices.py` | `daily_prices.csv` 1회 로드 → 조회 구조. 등락률을 연속 종가로 계산 |
| `app/services/mirofish/goodrich_backtest/universe.py` | 특정 날짜의 후보 유니버스 재현 (KIS 3소스 근사) + 시장 매핑 |
| `app/services/mirofish/goodrich_backtest/signals.py` | look-ahead safe 신호 계산 (순수 함수) |
| `app/services/mirofish/goodrich_backtest/rankers.py` | 랭킹 함수들. `baseline_current` = 현행 `_score` 재현 |
| `app/services/mirofish/goodrich_backtest/engine.py` | 백테스트 실행 + 진입일 블록 부트스트랩 |
| `scripts/run_goodrich_backtest.py` | CLI 진입점 — 결과를 JSON + 표로 출력 |
| `tests/test_goodrich_backtest_prices.py` | prices 단위 테스트 |
| `tests/test_goodrich_backtest_universe.py` | universe 단위 테스트 |
| `tests/test_goodrich_backtest_signals.py` | signals 단위 테스트 (**look-ahead 회귀 포함**) |
| `tests/test_goodrich_backtest_rankers.py` | rankers 단위 테스트 |
| `tests/test_goodrich_backtest_engine.py` | engine 단위 테스트 |

프로덕션 코드는 이 Phase에서 **수정하지 않는다**. 읽기 전용이다.

---

## Task 1: 가격 로더 (`prices.py`)

**Files:**
- Create: `app/services/mirofish/goodrich_backtest/__init__.py`
- Create: `app/services/mirofish/goodrich_backtest/prices.py`
- Test: `tests/test_goodrich_backtest_prices.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_goodrich_backtest_prices.py`:

```python
"""prices.py — daily_prices.csv 로더 단위 테스트."""
import csv

from app.services.mirofish.goodrich_backtest import prices as P


def _write_csv(path, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'ticker', 'date', 'name', 'current_price', 'change', 'change_rate',
            'high', 'low', 'open', 'volume', 'update_time',
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _row(ticker, date, close, volume, *, change_rate=0, high=None, low=None):
    return {
        'ticker': ticker, 'date': date, 'name': f'N{ticker}',
        'current_price': close, 'change': 0, 'change_rate': change_rate,
        'high': high if high is not None else close,
        'low': low if low is not None else close,
        'open': close, 'volume': volume, 'update_time': '',
    }


def test_load_builds_sorted_series_per_ticker(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('000660', '2024-01-03', 200, 10),
        _row('000660', '2024-01-02', 100, 20),
    ])

    book = P.load_prices(str(csv_path))

    assert book.sessions == ['2024-01-02', '2024-01-03']
    assert [bar.close for bar in book.series('000660')] == [100.0, 200.0]


def test_change_rate_is_computed_from_consecutive_closes(tmp_path):
    # change_rate 컬럼은 0 이지만 종가는 100 -> 110 이므로 +10% 여야 한다.
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('000660', '2024-01-02', 100, 10, change_rate=0),
        _row('000660', '2024-01-03', 110, 10, change_rate=0),
    ])

    book = P.load_prices(str(csv_path))

    assert book.change_pct('000660', '2024-01-03') == 10.0
    assert book.change_pct('000660', '2024-01-02') is None  # 이전 세션 없음


def test_rows_with_nonpositive_close_are_dropped(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('000660', '2024-01-02', 0, 10),
        _row('000660', '2024-01-03', 110, 10),
    ])

    book = P.load_prices(str(csv_path))

    assert [bar.date for bar in book.series('000660')] == ['2024-01-03']


def test_ledger_rows_exposes_shape_evaluate_pick_expects(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [_row('000660', '2024-01-02', 100, 10)])

    book = P.load_prices(str(csv_path))

    assert book.ledger_rows('000660') == [{'date': '2024-01-02', 'current_price': 100.0}]


def test_missing_file_returns_empty_book(tmp_path):
    book = P.load_prices(str(tmp_path / 'nope.csv'))

    assert book.sessions == []
    assert book.series('000660') == []
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_prices.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.services.mirofish.goodrich_backtest'`

- [ ] **Step 3: 구현**

`app/services/mirofish/goodrich_backtest/__init__.py`:

```python
"""Goodrich 랭킹 함수 백테스트 하네스.

프로덕션 파일을 읽기만 하며 어떤 산출물도 덮어쓰지 않는다.
"""
```

`app/services/mirofish/goodrich_backtest/prices.py`:

```python
"""daily_prices.csv 로더.

`change_rate` 컬럼은 전체 1,736,800행 중 18.2% 에서만 0 이 아니다. 과거 구간은
대부분 0 이라 그대로 쓰면 유니버스가 비어버리므로, 등락률은 항상 연속 종가로
계산한다 (close_t / close_{t-1} - 1).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_PRICE_PATH = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')


@dataclass(frozen=True)
class Bar:
    date: str
    close: float
    volume: float

    @property
    def turnover(self) -> float:
        return self.close * self.volume


class PriceBook:
    """티커별 일봉 시계열. 모든 조회는 사전 계산된 인덱스를 쓴다."""

    def __init__(self, series: dict[str, list[Bar]]):
        self._series = series
        self._index: dict[str, dict[str, int]] = {
            ticker: {bar.date: i for i, bar in enumerate(bars)}
            for ticker, bars in series.items()
        }
        self.sessions: list[str] = sorted({bar.date for bars in series.values() for bar in bars})

    def tickers(self) -> list[str]:
        return sorted(self._series)

    def series(self, ticker: str) -> list[Bar]:
        return self._series.get(ticker, [])

    def bar(self, ticker: str, date: str) -> Bar | None:
        i = self._index.get(ticker, {}).get(date)
        return None if i is None else self._series[ticker][i]

    def prior_bars(self, ticker: str, date: str, count: int) -> list[Bar]:
        """date 직전 세션부터 과거로 count 개. date 자신은 포함하지 않는다."""
        i = self._index.get(ticker, {}).get(date)
        if i is None or i == 0:
            return []
        start = max(0, i - count)
        return self._series[ticker][start:i]

    def change_pct(self, ticker: str, date: str) -> float | None:
        """직전 세션 종가 대비 등락률(%). 이전 세션이 없으면 None."""
        i = self._index.get(ticker, {}).get(date)
        if i is None or i == 0:
            return None
        prev = self._series[ticker][i - 1].close
        if prev <= 0:
            return None
        return round((self._series[ticker][i].close / prev - 1) * 100, 4)

    def ledger_rows(self, ticker: str) -> list[dict[str, Any]]:
        """goodrich_ledger.evaluate_pick 이 기대하는 형태로 변환."""
        return [{'date': bar.date, 'current_price': bar.close} for bar in self._series.get(ticker, [])]


def load_prices(path: str | None = None) -> PriceBook:
    """CSV 를 1회 전체 순회해 PriceBook 을 만든다. 파일이 없으면 빈 book."""
    target = path or DEFAULT_PRICE_PATH
    raw: dict[str, list[Bar]] = {}
    if not os.path.isfile(target):
        return PriceBook({})
    with open(target, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = str(row.get('ticker') or '').strip().zfill(6)
            date = str(row.get('date') or '').strip()
            if not ticker or not date:
                continue
            try:
                close = float(row.get('current_price') or 0)
                volume = float(row.get('volume') or 0)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            raw.setdefault(ticker, []).append(Bar(date=date, close=close, volume=volume))
    for ticker in raw:
        raw[ticker].sort(key=lambda bar: bar.date)
    return PriceBook(raw)
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_prices.py -q
```
Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/__init__.py app/services/mirofish/goodrich_backtest/prices.py tests/test_goodrich_backtest_prices.py
git commit -m "feat(goodrich-backtest): price loader computing change from consecutive closes"
```

---

## Task 1b: 로더 결함 수정 — 중복 행·세션 품질

Task 1 의 코드 리뷰가 실데이터에서만 드러나는 결함을 찾았다. 합성 데이터 테스트는
전부 통과했지만 **실제 CSV 에서는 하네스의 존재 이유인 look-ahead 차단이 깨진다.**

**실측 근거**:

| 사실 | 값 |
|---|---|
| 중복 `(ticker, date)` | 25,900키 / 28,784행, **9개 세션** |
| 2026-04-02 중복 비율 | 2,884 / 2,967 종목 (사실상 전 종목) |
| 장중(15:00 이전) 수집 | 572,952행 (**33.0%**) |
| 장중수집 과반 세션 | 110일 — **전부 2026년**, 2024·2025 는 0일 |

**중복이 만드는 3가지 고장** (전부 조용히 일어남):

1. `prior_bars` 가 **조회일 자신을 반환** — 인덱스가 마지막 사본을 가리켜 슬라이스에
   같은 날짜의 앞 사본이 남는다. 2026-04-02 에 2,884종목이 `[..., 04-02, 04-02]` 를
   "과거"로 돌려준다. 진입일 종가·거래량이 그대로 신호에 들어간다.
2. `change_pct` 가 **같은 날을 자기 자신과 비교** — 005930 이 실제 −7.23% 인데
   +0.796% 를 반환한다. 그 세션에서 1,481종목의 부호가 뒤집히고, 실제 상승 383종목이
   1,520종목으로 보고된다. `MAX_DAILY_MOVE_PCT` 가드는 0 을 통과시키므로 못 잡는다.
3. `ledger_rows` 가 **`evaluate_pick` 의 호라이즌을 어긋나게 함** — 그 함수는
   `future[horizon - 1]` 로 위치 인덱싱한다. 005930 은 628 날짜에 638행이므로
   T+1 과 T+2 가 같은 날로 해석된다. 즉 전방수익률 자체가 틀린다.

**Files:**
- Modify: `app/services/mirofish/goodrich_backtest/prices.py`
- Modify: `tests/test_goodrich_backtest_prices.py`

- [ ] **Step 1: 회귀 테스트 추가 (실패 확인용)**

`tests/test_goodrich_backtest_prices.py` 끝에 추가:

```python
def test_duplicate_ticker_date_rows_are_collapsed(tmp_path):
    """실데이터에 25,900개의 중복 (ticker, date) 가 있다. 재스크랩 결과이며
    별개의 봉이 아니다. 마지막 update_time 을 남기고 하나로 합쳐야 한다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),   # 같은 날 재스크랩 (뒤가 최신)
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert [bar.date for bar in book.series('000660')] == ['2024-01-02', '2024-01-03']
    assert book.bar('000660', '2024-01-03').close == 110.0   # 최신 스크랩


def test_prior_bars_never_returns_the_queried_date_even_with_duplicates(tmp_path):
    """중복이 있어도 진입일이 '과거'로 새어나오면 안 된다 — 하네스의 핵심 성질."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert [b.date for b in book.prior_bars('000660', '2024-01-03', 5)] == ['2024-01-02']


def test_change_pct_uses_the_previous_calendar_session_not_a_duplicate(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    # 110/100-1 = +10%. 110/105-1 = +4.76% (중복 비교) 가 나오면 실패.
    assert book.change_pct('000660', '2024-01-03') == 10.0


def test_ledger_rows_emit_one_row_per_date(tmp_path):
    """evaluate_pick 은 future[horizon-1] 로 위치 인덱싱하므로 중복이 있으면
    T+1 과 T+2 가 같은 날로 해석된다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    dates = [r['date'] for r in book.ledger_rows('000660')]
    assert dates == sorted(set(dates))


def test_blank_ticker_is_skipped_not_filed_under_000000(tmp_path):
    """zfill 이 먼저 돌면 ''.zfill(6) == '000000' 이라 빈 티커 가드가 죽는다."""
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('', '2024-01-02', 100, 10),
        _row('000660', '2024-01-02', 200, 10),
    ])

    book = P.load_prices(str(csv_path))

    assert book.tickers() == ['000660']


def test_unparseable_volume_keeps_the_price_bar(tmp_path):
    """거래량 파싱 실패로 봉을 버리면 계열에 구멍이 생겨 change_pct 가
    1일 수익률을 2일 수익률로 바꿔버린다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [_row('000660', '2024-01-02', 100, 10), _row('000660', '2024-01-03', 110, 10)]
    rows[1]['volume'] = 'N/A'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert [b.date for b in book.series('000660')] == ['2024-01-02', '2024-01-03']
    assert book.bar('000660', '2024-01-03').volume == 0.0


def test_nan_and_inf_closes_are_rejected(tmp_path):
    """float('nan') <= 0 은 False 라 양수 가드를 통과한다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [_row('000660', '2024-01-02', 100, 10), _row('000660', '2024-01-03', 110, 10)]
    rows[0]['current_price'] = 'nan'
    rows[1]['current_price'] = 'inf'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert book.series('000660') == []


def test_series_does_not_expose_the_internal_list(tmp_path):
    """호출부가 정렬/추가하면 인덱스가 어긋나 bar() 가 조용히 틀린 값을 준다."""
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [_row('000660', '2024-01-02', 100, 10)])

    book = P.load_prices(str(csv_path))
    got = book.series('000660')
    got.clear()

    assert len(book.series('000660')) == 1


def test_usable_sessions_drops_intraday_captured_days(tmp_path):
    """저장된 '종가' 가 장중 스냅샷인 세션은 수익률 계산의 근거가 못 된다.
    실데이터에서 110세션(전부 2026년)이 장중수집 과반이다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000661', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 110, 10),
        _row('000661', '2024-01-03', 110, 10),
    ]
    rows[0]['update_time'] = '2024-01-02 15:40:00'
    rows[1]['update_time'] = '2024-01-02 15:41:00'
    rows[2]['update_time'] = '2024-01-03 12:00:00'   # 장중
    rows[3]['update_time'] = '2024-01-03 11:00:00'   # 장중
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert book.sessions == ['2024-01-02', '2024-01-03']
    assert book.usable_sessions() == ['2024-01-02']
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_prices.py -q
```
Expected: 신규 9개 중 다수 FAIL (중복 미제거, `usable_sessions` 미존재 등)

- [ ] **Step 3: `prices.py` 수정**

전체 파일을 아래로 교체한다:

```python
"""daily_prices.csv 로더.

이 스크래퍼 출력은 신뢰할 수 없다. 실측된 결함 세 가지를 로더에서 흡수한다.

1. `change_rate` 컬럼이 1,736,800행 중 18.2% 에서만 0 이 아니다. 값이 있으면
   그것이 권위 있는 값(벤더가 공식 전일종가 대비 계산)이므로 우선 쓰고,
   없으면 연속 종가로 유도한다. 단위는 **퍼센트**다.
2. 같은 `(ticker, date)` 가 25,900건 중복된다(9개 세션, 장중 재스크랩).
   합치지 않으면 `prior_bars` 가 조회일을 과거로 돌려주고, `change_pct` 가
   같은 날을 자기와 비교하며, `evaluate_pick` 의 위치 인덱싱이 어긋난다.
   가장 늦은 `update_time` 을 남긴다.
3. 33.0% 의 행이 15:00 이전에 수집됐다 — 저장된 "종가" 가 장중 스냅샷이다.
   장중수집이 과반인 세션은 `usable_sessions()` 에서 제외한다.
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_PRICE_PATH = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')

# 한국 정규장은 15:30 에 마감한다(종가 단일가 15:20~15:30). 그 전에 수집된 값은
# 체결 진행 중의 스냅샷이므로 종가가 아니다. 실측 분포도 이를 뒷받침한다:
# 82.8% 는 행 날짜보다 뒤에 수집돼 종가가 확정된 것이고, 15.1% 는 당일 장중,
# 2.1% 만 당일 15:30 이후다.
CLOSE_CAPTURE_TIME = '15:30'
MAX_INTRADAY_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class Bar:
    date: str
    close: float
    volume: float
    change_rate: float | None = None

    @property
    def turnover(self) -> float:
        return self.close * self.volume


class PriceBook:
    """티커별 일봉 시계열. 모든 조회는 사전 계산된 인덱스를 쓴다."""

    def __init__(self, series: dict[str, list[Bar]], *, intraday_share: dict[str, float] | None = None):
        self._series = series
        self._index: dict[str, dict[str, int]] = {
            ticker: {bar.date: i for i, bar in enumerate(bars)}
            for ticker, bars in series.items()
        }
        self._intraday_share = intraday_share or {}
        self.sessions: list[str] = sorted({bar.date for bars in series.values() for bar in bars})

    def tickers(self) -> list[str]:
        return sorted(self._series)

    def series(self, ticker: str) -> list[Bar]:
        return list(self._series.get(ticker, ()))

    def bar(self, ticker: str, date: str) -> Bar | None:
        idx = self._index.get(ticker)
        if idx is None:
            return None
        i = idx.get(date)
        return None if i is None else self._series[ticker][i]

    def prior_bars(self, ticker: str, date: str, count: int) -> list[Bar]:
        """date 직전 세션부터 과거로 count 개. date 자신은 절대 포함하지 않는다."""
        idx = self._index.get(ticker)
        if idx is None:
            return []
        i = idx.get(date)
        if i is None:
            return []
        return self._series[ticker][max(0, i - count):i]

    def change_pct(self, ticker: str, date: str) -> float | None:
        """등락률(%). change_rate 컬럼이 있으면 그것을, 없으면 연속 종가로 유도."""
        idx = self._index.get(ticker)
        if idx is None:
            return None
        i = idx.get(date)
        if i is None:
            return None
        bar = self._series[ticker][i]
        if bar.change_rate is not None:
            return bar.change_rate
        if i == 0:
            return None
        prev = self._series[ticker][i - 1].close
        if prev <= 0:
            return None
        return round((bar.close / prev - 1) * 100, 4)

    def ledger_rows(self, ticker: str) -> list[dict[str, Any]]:
        """goodrich_ledger.evaluate_pick 이 기대하는 형태. 날짜당 정확히 한 행."""
        return [{'date': bar.date, 'current_price': bar.close} for bar in self._series.get(ticker, ())]

    def usable_sessions(self, *, max_intraday_share: float = MAX_INTRADAY_SHARE) -> list[str]:
        """장중 수집이 과반이 아닌 세션만. 저장된 종가를 믿을 수 있는 날들이다."""
        return [
            date for date in self.sessions
            if self._intraday_share.get(date, 0.0) <= max_intraday_share
        ]


def _is_intraday_capture(date: str, update_time: str) -> bool:
    """이 행이 그 날의 장중에 수집됐는가 — 즉 close 가 종가가 아닌가.

    수집 시각만 보면 안 된다. 15:04 는 행 날짜와 같은 날이면 장중이지만,
    다음 날이면 이미 확정된 종가를 읽은 것이다.
    """
    if len(update_time) < 16:
        return False   # 판단 근거 없음 — 배제하지 않는다
    captured_date, captured_time = update_time[:10], update_time[11:16]
    if captured_date > date:
        return False   # 후일 수집 = 종가 확정
    if captured_date < date:
        return False   # 행 날짜보다 이른 수집 — 별개 이상이며 여기서 다루지 않는다
    return captured_time < CLOSE_CAPTURE_TIME


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_prices(path: str | None = None) -> PriceBook:
    """CSV 를 1회 전체 순회해 PriceBook 을 만든다. 파일이 없으면 빈 book."""
    target = path or DEFAULT_PRICE_PATH
    if not os.path.isfile(target):
        return PriceBook({})

    # (ticker, date) -> (update_time, Bar). 가장 늦은 update_time 만 남긴다.
    latest: dict[tuple[str, str], tuple[str, Bar]] = {}
    capture: dict[str, list[int]] = {}   # date -> [장중 수집 수, 전체]

    with open(target, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = str(row.get('ticker') or '').strip()
            date = str(row.get('date') or '').strip()
            if not ticker or not date:
                continue
            ticker = ticker.zfill(6)

            close = _finite(row.get('current_price'))
            if close is None or close <= 0:
                continue
            volume = _finite(row.get('volume')) or 0.0
            change_rate = _finite(row.get('change_rate'))
            if change_rate == 0:
                change_rate = None   # 0 은 '미기록' 과 구분되지 않는다

            update_time = str(row.get('update_time') or '')
            counts = capture.setdefault(date, [0, 0])
            counts[1] += 1
            if _is_intraday_capture(date, update_time):
                counts[0] += 1

            key = (ticker, date)
            previous = latest.get(key)
            if previous is None or update_time >= previous[0]:
                latest[key] = (update_time, Bar(
                    date=date, close=close, volume=volume, change_rate=change_rate,
                ))

    by_ticker: dict[str, list[Bar]] = {}
    for (ticker, _date), (_update_time, bar) in latest.items():
        by_ticker.setdefault(ticker, []).append(bar)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda bar: bar.date)

    intraday_share = {
        date: (intraday / total if total else 0.0)
        for date, (intraday, total) in capture.items()
    }
    return PriceBook(by_ticker, intraday_share=intraday_share)
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_prices.py -q
```
Expected: `16 passed` (기존 5 + 신규 11)

- [ ] **Step 5: 실데이터 재검증**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from app.services.mirofish.goodrich_backtest import prices as P
book = P.load_prices()
print('sessions', len(book.sessions), 'usable', len(book.usable_sessions()), 'tickers', len(book.tickers()))
# 중복이 남아 있으면 날짜당 2행이 된다
rows = book.ledger_rows('005930')
dates = [r['date'] for r in rows]
print('005930 rows', len(rows), 'unique dates', len(set(dates)), '-> dedup', len(rows) == len(set(dates)))
# 리뷰가 지목한 세션에서 prior_bars 가 조회일을 흘리는지
leak = sum(1 for t in book.tickers()[:500]
           if any(b.date >= '2026-04-02' for b in book.prior_bars(t, '2026-04-02', 5)))
print('2026-04-02 look-ahead leaks in first 500 tickers:', leak, '(0 이어야 함)')
print('005930 change on 2026-04-02:', book.change_pct('005930', '2026-04-02'), '(약 -7.23% 여야 함)')
"
```
Expected: `usable` 545, dedup True, leaks 0

- [ ] **Step 6: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/prices.py tests/test_goodrich_backtest_prices.py
git commit -m "fix(goodrich-backtest): collapse duplicate bars and flag intraday-captured sessions"
```

---

## Task 2: 유니버스 재현 (`universe.py`)

**Files:**
- Create: `app/services/mirofish/goodrich_backtest/universe.py`
- Test: `tests/test_goodrich_backtest_universe.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_goodrich_backtest_universe.py`:

```python
"""universe.py — KIS 3소스 유니버스 재현 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest import universe as U


def _book(spec):
    """spec: {ticker: [(date, close, volume), ...]}"""
    return PriceBook({
        ticker: [Bar(date=d, close=c, volume=v) for d, c, v in bars]
        for ticker, bars in spec.items()
    })


def test_only_positive_change_names_enter_universe():
    book = _book({
        '000001': [('2024-01-02', 100, 1000), ('2024-01-03', 110, 1000)],  # +10%
        '000002': [('2024-01-02', 100, 1000), ('2024-01-03', 90, 1000)],   # -10%
    })

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    assert [c.symbol for c in got] == ['000001']


def test_union_of_three_sources():
    """소스마다 승자가 달라야 합집합이 3종목이 된다.

    000001 등락률 1위(+29%, 가격제한폭 안) / 000002 거래대금 1위 / 000003 거래량급증 1위.
    셋 다 ±31% 안에 있어야 corrupt-data 필터에 걸리지 않는다.
    """
    book = _book({
        # change +29%, turnover 129,000, surge 1.0
        '000001': [('2024-01-02', 100, 1000), ('2024-01-03', 129, 1000)],
        # change +0.1%, turnover 100,100,000, surge 1.0
        '000002': [('2024-01-02', 100000, 1000), ('2024-01-03', 100100, 1000)],
        # change +1%, turnover 50,500, surge 500.0
        '000003': [('2024-01-02', 100, 1), ('2024-01-03', 101, 500)],
    })

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=1)

    assert {c.symbol for c in got} == {'000001', '000002', '000003'}


def test_first_session_yields_nothing_because_change_is_unknown():
    book = _book({'000001': [('2024-01-02', 100, 1000)]})

    assert U.reconstruct_universe('2024-01-02', book, per_source_top_n=10) == []


def test_candidate_carries_fields_ranking_needs():
    book = _book({'000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 20)]})

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    c = got[0]
    assert c.symbol == '000001'
    assert c.date == '2024-01-03'
    assert c.close == 110.0
    assert c.change_pct == 10.0
    assert c.turnover == 110.0 * 20


def test_market_is_attached_so_benchmark_can_be_chosen():
    book = _book({
        '000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)],
        '000002': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)],
    })
    markets = {'000001': 'KOSPI', '000002': 'KOSDAQ'}

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10, markets=markets)

    assert {c.symbol: c.market for c in got} == {'000001': 'KOSPI', '000002': 'KOSDAQ'}


def test_unknown_market_is_empty_string_not_a_guess():
    book = _book({'000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)]})

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10, markets={})

    assert got[0].market == ''


def test_impossible_daily_move_is_rejected_as_corrupt_data():
    """한국 가격제한폭은 ±30%. 초과분은 물리적으로 불가능하므로 데이터 오류다.

    실측: daily_prices.csv 에 616건(466종목)이 이 범위를 넘는다. 예) 052670 이
    2,080 -> 610,000 (+29,227%). 하나라도 랭킹에 들어오면 평균 초과수익이 통째로
    오염되므로 후보 단계에서 배제한다.
    """
    book = _book({
        '000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)],      # +10% 정상
        '000002': [('2024-01-02', 100, 10), ('2024-01-03', 30000, 10)],    # +29,900% 오류
    })

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    assert [c.symbol for c in got] == ['000001']


def test_limit_up_at_the_boundary_is_kept():
    """정상 상한가(+29.9%)는 버리지 않는다."""
    book = _book({'000001': [('2024-01-02', 100, 10), ('2024-01-03', 129.9, 10)]})

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    assert [c.symbol for c in got] == ['000001']


def test_load_markets_reads_ticker_map(tmp_path):
    path = tmp_path / 'ticker_to_yahoo_map.csv'
    path.write_text(
        'ticker,market,yahoo_ticker,name\n'
        '005930,KOSPI,005930.KS,삼성전자\n'
        '247540,KOSDAQ,247540.KQ,에코프로비엠\n',
        encoding='utf-8',
    )

    assert U.load_markets(str(path)) == {'005930': 'KOSPI', '247540': 'KOSDAQ'}


def test_universe_is_deterministic():
    book = _book({
        f'{i:06d}': [('2024-01-02', 100, 10), ('2024-01-03', 100 + i, 10)]
        for i in range(1, 6)
    })

    first = [c.symbol for c in U.reconstruct_universe('2024-01-03', book, per_source_top_n=3)]
    second = [c.symbol for c in U.reconstruct_universe('2024-01-03', book, per_source_top_n=3)]

    assert first == second
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_universe.py -q
```
Expected: `ModuleNotFoundError: No module named '...goodrich_backtest.universe'`

- [ ] **Step 3: 구현**

`app/services/mirofish/goodrich_backtest/universe.py`:

```python
"""과거 세션의 Goodrich 후보 유니버스를 일봉으로 재현.

라이브 kis_screener 는 세 개 순위 API 를 합집합으로 쓴다:
  - fetch_volume_rank(token, "3")  거래대금 순위   -> close * volume
  - fetch_fluctuation_rank(token)  등락률 순위     -> 연속 종가 등락률
  - fetch_volume_rank(token, "1")  거래량 급증     -> volume / 20일 평균거래량

goodrich_client 는 여기에 change_pct > 0 필터를 적용한다. 재현도 동일하게 맞춘다.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

from app.services.mirofish.goodrich_backtest.prices import PriceBook

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_TICKER_MAP_PATH = os.path.join(REPO_ROOT, 'data', 'ticker_to_yahoo_map.csv')

VOLUME_SURGE_WINDOW = 20

# 한국 가격제한폭은 ±30%. 이를 넘는 일간 변동은 체결로 발생할 수 없으므로
# 데이터 오류다 (실측 616건 / 466종목). 1%p 여유를 둔다.
MAX_DAILY_MOVE_PCT = 31.0


@dataclass(frozen=True)
class Candidate:
    symbol: str
    date: str
    close: float
    volume: float
    change_pct: float
    turnover: float
    volume_surge: float
    market: str = ''


def load_markets(path: str | None = None) -> dict[str, str]:
    """티커 -> 시장(KOSPI/KOSDAQ). 벤치마크 지수를 고르는 데 쓴다.

    원장이 `market` 을 기록하지 않아 코스닥 종목까지 KOSPI 지수와 비교되던 결함이
    있었다(측정 문서 1.2절). 백테스트에서는 같은 실수를 반복하지 않는다.
    """
    target = path or DEFAULT_TICKER_MAP_PATH
    if not os.path.isfile(target):
        return {}
    out: dict[str, str] = {}
    with open(target, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = str(row.get('ticker') or '').strip().zfill(6)
            market = str(row.get('market') or '').strip().upper()
            if ticker and market:
                out[ticker] = market
    return out


def reconstruct_universe(
    date: str,
    book: PriceBook,
    *,
    per_source_top_n: int = 30,
    markets: dict[str, str] | None = None,
) -> list[Candidate]:
    """date 세션의 후보 유니버스. per_source_top_n 은 소스별 상위 N (합집합)."""
    market_by_ticker = markets if markets is not None else load_markets()
    rows: list[Candidate] = []
    for ticker in book.tickers():
        bar = book.bar(ticker, date)
        if bar is None:
            continue
        change = book.change_pct(ticker, date)
        if change is None:
            continue
        if abs(change) > MAX_DAILY_MOVE_PCT:
            continue  # 가격제한폭 초과 = 데이터 오류
        prior = book.prior_bars(ticker, date, VOLUME_SURGE_WINDOW)
        avg_volume = sum(b.volume for b in prior) / len(prior) if prior else 0.0
        surge = bar.volume / avg_volume if avg_volume > 0 else 0.0
        rows.append(Candidate(
            symbol=ticker,
            date=date,
            close=bar.close,
            volume=bar.volume,
            change_pct=change,
            turnover=bar.turnover,
            volume_surge=surge,
            market=market_by_ticker.get(ticker, ''),
        ))

    if not rows:
        return []

    def top(key, n):
        # 동점은 symbol 오름차순으로 깨서 결정적으로 만든다.
        return sorted(rows, key=lambda c: (-key(c), c.symbol))[:n]

    selected = {}
    for candidate in (
        top(lambda c: c.turnover, per_source_top_n)
        + top(lambda c: c.change_pct, per_source_top_n)
        + top(lambda c: c.volume_surge, per_source_top_n)
    ):
        if candidate.change_pct > 0:
            selected[candidate.symbol] = candidate

    return [selected[symbol] for symbol in sorted(selected)]
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_universe.py -q
```
Expected: `10 passed`

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/universe.py tests/test_goodrich_backtest_universe.py
git commit -m "feat(goodrich-backtest): reconstruct candidate universe with market mapping"
```

---

## Task 3: 신호 라이브러리 (`signals.py`)

**Files:**
- Create: `app/services/mirofish/goodrich_backtest/signals.py`
- Test: `tests/test_goodrich_backtest_signals.py`

- [ ] **Step 1: 실패하는 테스트 작성 (look-ahead 회귀 포함)**

`tests/test_goodrich_backtest_signals.py`:

```python
"""signals.py — look-ahead safe 신호 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest import signals as S


def _book(bars, ticker='000001'):
    return PriceBook({ticker: [Bar(date=d, close=c, volume=v) for d, c, v in bars]})


def test_pullback_depth_is_zero_at_the_high():
    bars = [(f'2024-01-{d:02d}', 100 + d, 10) for d in range(2, 12)]
    book = _book(bars)

    # 마지막 세션이 구간 최고가이므로 눌림 깊이 0
    assert S.pullback_depth('000001', '2024-01-11', book, window=10) == 0.0


def test_pullback_depth_measures_drop_from_prior_high():
    bars = [('2024-01-02', 100, 10), ('2024-01-03', 200, 10), ('2024-01-04', 150, 10)]
    book = _book(bars)

    # 직전 고점 200 대비 150 -> 25% 하락
    assert S.pullback_depth('000001', '2024-01-04', book, window=10) == 25.0


def test_volatility_norm_uses_prior_sessions_only():
    bars = [('2024-01-02', 100, 10), ('2024-01-03', 110, 10), ('2024-01-04', 100, 10)]
    book = _book(bars)

    value = S.volatility_norm('000001', '2024-01-04', book, window=10)

    assert value > 0


def test_overheat_sums_recent_gains():
    bars = [('2024-01-02', 100, 10), ('2024-01-03', 110, 10), ('2024-01-04', 121, 10)]
    book = _book(bars)

    # 2일간 +10%, +10% => 약 20%
    assert 19.0 <= S.overheat('000001', '2024-01-04', book, window=2) <= 21.0


def test_liquidity_grows_with_turnover():
    small = _book([('2024-01-02', 100, 10), ('2024-01-03', 100, 10)])
    large = _book([('2024-01-02', 100, 10), ('2024-01-03', 100, 1_000_000)])

    assert S.liquidity('000001', '2024-01-03', large) > S.liquidity('000001', '2024-01-03', small)


def test_signals_ignore_future_sessions():
    """look-ahead 회귀 — 미래 세션을 덧붙여도 값이 변하면 안 된다."""
    base = [('2024-01-02', 100, 10), ('2024-01-03', 110, 10), ('2024-01-04', 120, 10)]
    future = base + [('2024-01-05', 500, 999), ('2024-01-08', 900, 999)]

    book_a = _book(base)
    book_b = _book(future)

    for fn in (S.pullback_depth, S.volatility_norm, S.overheat):
        assert fn('000001', '2024-01-04', book_a) == fn('000001', '2024-01-04', book_b), fn.__name__
    assert S.liquidity('000001', '2024-01-04', book_a) == S.liquidity('000001', '2024-01-04', book_b)


def test_missing_history_returns_neutral_defaults():
    book = _book([('2024-01-02', 100, 10)])

    assert S.pullback_depth('000001', '2024-01-02', book) == 0.0
    assert S.volatility_norm('000001', '2024-01-02', book) == 0.0
    assert S.overheat('000001', '2024-01-02', book) == 0.0


def test_rs_rating_reads_artifact_and_defaults_when_absent():
    ratings = {'entries': {'000001': {'rs_rating': 88}}}

    assert S.rs_rating('000001', ratings) == 88
    assert S.rs_rating('999999', ratings) == 50  # 미상은 중립
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_signals.py -q
```
Expected: `ModuleNotFoundError: No module named '...goodrich_backtest.signals'`

- [ ] **Step 3: 구현**

`app/services/mirofish/goodrich_backtest/signals.py`:

```python
"""look-ahead safe 신호.

모든 함수는 순수 함수이며, 진입일 `date` 시점까지의 데이터만 읽는다.
미래 세션을 주입해도 값이 바뀌지 않는다 (테스트로 강제).
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

from app.services.mirofish.goodrich_backtest.prices import PriceBook

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
RS_RATINGS_PATH = os.path.join(REPO_ROOT, 'data', 'alpha_rs_ratings.json')

NEUTRAL_RS = 50


def pullback_depth(ticker: str, date: str, book: PriceBook, *, window: int = 20) -> float:
    """최근 window 세션(당일 포함) 고점 대비 하락률(%). 고점이면 0."""
    bars = book.prior_bars(ticker, date, window)
    bar = book.bar(ticker, date)
    if bar is None:
        return 0.0
    highest = max([b.close for b in bars] + [bar.close])
    if highest <= 0:
        return 0.0
    return round((highest - bar.close) / highest * 100, 4)


def volatility_norm(ticker: str, date: str, book: PriceBook, *, window: int = 14) -> float:
    """직전 window 세션 일간수익률 표준편차(%). 이력이 없으면 0."""
    bars = book.prior_bars(ticker, date, window + 1)
    if len(bars) < 3:
        return 0.0
    rets = []
    for prev, cur in zip(bars, bars[1:]):
        if prev.close > 0:
            rets.append((cur.close / prev.close - 1) * 100)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var), 4)


def overheat(ticker: str, date: str, book: PriceBook, *, window: int = 3) -> float:
    """최근 window 세션 누적 상승률(%). 현 _score 의 문제항을 페널티로 쓰기 위한 값."""
    bars = book.prior_bars(ticker, date, window)
    bar = book.bar(ticker, date)
    if bar is None or not bars:
        return 0.0
    base = bars[0].close
    if base <= 0:
        return 0.0
    return round((bar.close / base - 1) * 100, 4)


def liquidity(ticker: str, date: str, book: PriceBook) -> float:
    """거래대금 로그 스케일 (0~1 근방). 체결 가능성 대리변수."""
    bar = book.bar(ticker, date)
    if bar is None or bar.turnover <= 0:
        return 0.0
    return round(min(math.log10(max(bar.turnover, 1)) / 14, 1.0), 4)


def load_rs_ratings(path: str | None = None) -> dict[str, Any]:
    """alpha_rs_ratings.json 로드. 없으면 빈 entries."""
    target = path or RS_RATINGS_PATH
    if not os.path.isfile(target):
        return {'entries': {}}
    try:
        with open(target, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {'entries': {}}
    return payload if isinstance(payload.get('entries'), dict) else {'entries': {}}


def rs_rating(ticker: str, ratings: dict[str, Any]) -> int:
    """O'Neil 상대강도 백분위(1~99). 미상은 중립 50."""
    entry = (ratings or {}).get('entries', {}).get(ticker)
    if not isinstance(entry, dict):
        return NEUTRAL_RS
    try:
        return int(entry.get('rs_rating'))
    except (TypeError, ValueError):
        return NEUTRAL_RS
```

> **RS 주의**: `alpha_rs_ratings.json` 은 **오늘자 스냅샷 한 장**이다. 과거 세션에 그대로 적용하면
> look-ahead 다. Task 5 에서 백테스트가 RS 를 쓸 때는 `signals.rs_from_book()` (Task 5 에서 추가)
> 로 과거 시점 RS 를 재계산한다. 이 함수는 라이브 프로덕션 경로 전용이다.

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_signals.py -q
```
Expected: `8 passed`

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/signals.py tests/test_goodrich_backtest_signals.py
git commit -m "feat(goodrich-backtest): look-ahead safe signal library"
```

---

## Task 4: 시점 정확 RS (`signals.rs_from_book`)

RS 아티팩트는 오늘자 한 장뿐이라 과거 백테스트에 쓰면 look-ahead 다.
`sector_rs` 의 공식을 과거 시점으로 재계산한다.

**Files:**
- Modify: `app/services/mirofish/goodrich_backtest/signals.py` (함수 추가)
- Modify: `tests/test_goodrich_backtest_signals.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_goodrich_backtest_signals.py` 끝에 추가:

```python
def test_rs_from_book_ranks_stronger_performer_higher():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    # 3개월(63세션) 이상 필요하므로 70세션을 만든다.
    dates = [f'2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}' for i in range(70)]
    strong = [Bar(date=d, close=100 + i * 2, volume=10) for i, d in enumerate(dates)]
    weak = [Bar(date=d, close=100 - i * 0.5, volume=10) for i, d in enumerate(dates)]
    book = PriceBook({'000001': strong, '000002': weak})

    ratings = S.rs_from_book(dates[-1], book)

    assert ratings['000001'] > ratings['000002']
    assert 1 <= ratings['000002'] <= 99


def test_rs_from_book_excludes_short_history():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    dates = [f'2024-01-{i + 1:02d}' for i in range(10)]
    book = PriceBook({'000001': [Bar(date=d, close=100 + i, volume=10) for i, d in enumerate(dates)]})

    assert S.rs_from_book(dates[-1], book) == {}


def test_rs_from_book_ignores_future_sessions():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    dates = [f'2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}' for i in range(70)]
    base = [Bar(date=d, close=100 + i, volume=10) for i, d in enumerate(dates)]
    future = base + [Bar(date='2025-01-01', close=99999, volume=10)]

    a = S.rs_from_book(dates[-1], PriceBook({'000001': base, '000002': base}))
    b = S.rs_from_book(dates[-1], PriceBook({'000001': future, '000002': future}))

    assert a == b
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_signals.py -q -k rs_from_book
```
Expected: `AttributeError: module ... has no attribute 'rs_from_book'`

- [ ] **Step 3: 구현**

`app/services/mirofish/goodrich_backtest/signals.py` 끝에 추가:

```python
# O'Neil 가중 상대강도 — app/services/mirofish/sector_rs.py 와 동일한 공식이지만
# 과거 시점 기준으로 재계산한다. 아티팩트(alpha_rs_ratings.json)는 오늘자 한 장뿐이라
# 백테스트에 그대로 쓰면 look-ahead 가 된다.
RS_HORIZONS: tuple[tuple[int, float], ...] = (
    (63, 0.4),
    (126, 0.2),
    (189, 0.2),
    (252, 0.2),
)
RS_MIN_HISTORY = 63


def _weighted_return(closes: list[float]) -> float | None:
    """closes 는 과거->현재 순서. 가용 구간만으로 가중치를 재정규화."""
    n = len(closes)
    if n < RS_MIN_HISTORY:
        return None
    last = closes[-1]
    if last <= 0:
        return None
    weighted = 0.0
    weight_sum = 0.0
    for lookback, weight in RS_HORIZONS:
        idx = n - 1 - lookback
        if idx < 0:
            continue
        base = closes[idx]
        if base <= 0:
            continue
        weighted += weight * (last / base - 1.0)
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return weighted / weight_sum


def rs_from_book(date: str, book: PriceBook) -> dict[str, int]:
    """date 시점 기준 RS 백분위(1~99). date 이후 세션은 절대 보지 않는다."""
    scored: dict[str, float] = {}
    for ticker in book.tickers():
        bars = book.prior_bars(ticker, date, 10_000)
        bar = book.bar(ticker, date)
        if bar is None:
            continue
        closes = [b.close for b in bars] + [bar.close]
        value = _weighted_return(closes)
        if value is not None:
            scored[ticker] = value

    total = len(scored)
    if total == 0:
        return {}
    ordered = sorted(scored.items(), key=lambda kv: kv[1])
    if total == 1:
        return {ordered[0][0]: NEUTRAL_RS}
    return {
        ticker: int(1 + round(rank / (total - 1) * 98))
        for rank, (ticker, _) in enumerate(ordered)
    }
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_signals.py -q
```
Expected: `11 passed`

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/signals.py tests/test_goodrich_backtest_signals.py
git commit -m "feat(goodrich-backtest): point-in-time RS so backtests avoid look-ahead"
```

---

## Task 5: 랭커 (`rankers.py`)

**Files:**
- Create: `app/services/mirofish/goodrich_backtest/rankers.py`
- Test: `tests/test_goodrich_backtest_rankers.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_goodrich_backtest_rankers.py`:

```python
"""rankers.py — 랭킹 함수 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest.universe import Candidate
from app.services.mirofish.goodrich_backtest import rankers as R


def _candidate(symbol, change_pct=1.0, turnover=1e9, close=100.0, surge=1.0, market='KOSPI'):
    return Candidate(
        symbol=symbol, date='2024-01-03', close=close, volume=turnover / close,
        change_pct=change_pct, turnover=turnover, volume_surge=surge, market=market,
    )


def _ctx(book=None, rs=None):
    return R.RankContext(
        date='2024-01-03',
        book=book or PriceBook({}),
        rs_ratings=rs or {},
    )


def test_all_rankers_are_registered():
    assert set(R.RANKERS) == {
        'baseline_current', 'rs_led', 'pullback', 'low_volatility', 'composite',
    }


def test_baseline_reproduces_goodrich_score_shape():
    """현행 _score: 50 + range_position*25 + momentum*0.8 + liquidity*20.

    일봉에는 장중 고저가 없으므로 range_position 은 1.0 으로 고정한다
    (종가 = 당일 고가 가정). 등락률이 클수록 점수가 커지는 성질이 핵심이다.
    """
    ctx = _ctx()
    low = R.RANKERS['baseline_current'](_candidate('000001', change_pct=1.0), ctx)
    high = R.RANKERS['baseline_current'](_candidate('000002', change_pct=12.0), ctx)

    assert high > low


def test_baseline_caps_momentum_at_15_like_production():
    ctx = _ctx()
    at_cap = R.RANKERS['baseline_current'](_candidate('000001', change_pct=15.0), ctx)
    beyond = R.RANKERS['baseline_current'](_candidate('000002', change_pct=40.0), ctx)

    assert at_cap == beyond


def test_rs_led_prefers_higher_rs():
    ctx = _ctx(rs={'000001': 95, '000002': 20})

    assert R.RANKERS['rs_led'](_candidate('000001'), ctx) > R.RANKERS['rs_led'](_candidate('000002'), ctx)


def test_pullback_penalises_overheated_names():
    bars = [Bar(date=f'2024-01-{d:02d}', close=100.0, volume=10) for d in range(1, 3)]
    hot = bars + [Bar(date='2024-01-03', close=150.0, volume=10)]
    calm = bars + [Bar(date='2024-01-03', close=101.0, volume=10)]
    ctx_hot = _ctx(book=PriceBook({'000001': hot}))
    ctx_calm = _ctx(book=PriceBook({'000001': calm}))

    hot_score = R.RANKERS['pullback'](_candidate('000001', change_pct=50.0), ctx_hot)
    calm_score = R.RANKERS['pullback'](_candidate('000001', change_pct=1.0), ctx_calm)

    assert calm_score > hot_score


def test_rankers_are_deterministic():
    ctx = _ctx(rs={'000001': 70})
    candidate = _candidate('000001')

    for name, fn in R.RANKERS.items():
        assert fn(candidate, ctx) == fn(candidate, ctx), name


def test_rank_candidates_sorts_descending_and_breaks_ties_by_symbol():
    ctx = _ctx()
    rows = [_candidate('000002', change_pct=5.0), _candidate('000001', change_pct=5.0)]

    ordered = R.rank_candidates(rows, R.RANKERS['baseline_current'], ctx)

    assert [c.symbol for c, _ in ordered] == ['000001', '000002']
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_rankers.py -q
```
Expected: `ModuleNotFoundError: No module named '...goodrich_backtest.rankers'`

- [ ] **Step 3: 구현**

`app/services/mirofish/goodrich_backtest/rankers.py`:

```python
"""비교 대상 랭킹 함수들.

baseline_current 는 현행 GoodrichTradingOS `_score` 의 재현이며, 개선 주장의
기준선이다. 반드시 함께 돌린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.services.mirofish.goodrich_backtest import signals as S
from app.services.mirofish.goodrich_backtest.prices import PriceBook
from app.services.mirofish.goodrich_backtest.universe import Candidate


@dataclass(frozen=True)
class RankContext:
    date: str
    book: PriceBook
    rs_ratings: dict[str, int]


Ranker = Callable[[Candidate, RankContext], float]


def baseline_current(candidate: Candidate, ctx: RankContext) -> float:
    """현행 _score 재현.

    원본: 50 + range_position*25 + momentum*0.8 + liquidity*20
    일봉에는 장중 고저가 없으므로 range_position 은 1.0 으로 고정한다.
    이는 baseline 을 유리하게 잡는 방향(종가=고가 가정)이라 개선 주장이
    과대평가되지 않는다.
    """
    momentum = max(min(candidate.change_pct, 15), -15)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    return round(50 + 1.0 * 25 + momentum * 0.8 + liquidity * 20, 4)


def rs_led(candidate: Candidate, ctx: RankContext) -> float:
    """상대강도 주도 + 유동성 가산."""
    rs = ctx.rs_ratings.get(candidate.symbol, S.NEUTRAL_RS)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    return round(rs + liquidity * 10, 4)


def pullback(candidate: Candidate, ctx: RankContext) -> float:
    """눌림목 선호 — 과열도를 감점한다."""
    depth = S.pullback_depth(candidate.symbol, ctx.date, ctx.book, window=20)
    heat = S.overheat(candidate.symbol, ctx.date, ctx.book, window=3)
    rs = ctx.rs_ratings.get(candidate.symbol, S.NEUTRAL_RS)
    return round(rs * 0.5 + depth * 1.5 - heat * 1.0, 4)


def low_volatility(candidate: Candidate, ctx: RankContext) -> float:
    """변동성 대비 유동성 — 폭탄 회피형.

    spec §5.3 은 수급 연속성(flow_persistence)도 신호로 열거하지만,
    `all_institutional_trend_data.csv` 는 티커당 1행 스냅샷이라 과거 시점 값을
    복원할 수 없다. 스냅샷을 과거 세션에 적용하면 look-ahead 이므로 이 랭커는
    수급을 쓰지 않는다. 수급 신호는 시계열 적재가 생긴 뒤에 다룬다.
    """
    volatility = S.volatility_norm(candidate.symbol, ctx.date, ctx.book, window=14)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    penalty = min(volatility, 20.0)
    return round(liquidity * 50 - penalty * 2.0, 4)


def composite(candidate: Candidate, ctx: RankContext) -> float:
    """위 신호들의 단순 결합. 파라미터를 늘리지 않는다."""
    rs = ctx.rs_ratings.get(candidate.symbol, S.NEUTRAL_RS)
    depth = S.pullback_depth(candidate.symbol, ctx.date, ctx.book, window=20)
    heat = S.overheat(candidate.symbol, ctx.date, ctx.book, window=3)
    volatility = S.volatility_norm(candidate.symbol, ctx.date, ctx.book, window=14)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    return round(
        rs * 0.4 + depth * 0.8 - heat * 0.8 - min(volatility, 20.0) * 1.0 + liquidity * 20,
        4,
    )


RANKERS: dict[str, Ranker] = {
    'baseline_current': baseline_current,
    'rs_led': rs_led,
    'pullback': pullback,
    'low_volatility': low_volatility,
    'composite': composite,
}


def rank_candidates(
    candidates: list[Candidate],
    ranker: Ranker,
    ctx: RankContext,
) -> list[tuple[Candidate, float]]:
    """점수 내림차순. 동점은 symbol 오름차순으로 깨서 결정적으로 만든다."""
    scored = [(candidate, ranker(candidate, ctx)) for candidate in candidates]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0].symbol))
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_rankers.py -q
```
Expected: `7 passed`

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/rankers.py tests/test_goodrich_backtest_rankers.py
git commit -m "feat(goodrich-backtest): ranker set with current formula as baseline"
```

---

## Task 6: 백테스트 엔진 + 부트스트랩 (`engine.py`)

**Files:**
- Create: `app/services/mirofish/goodrich_backtest/engine.py`
- Test: `tests/test_goodrich_backtest_engine.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_goodrich_backtest_engine.py`:

```python
"""engine.py — 백테스트 실행 + 유의성 판정 단위 테스트."""
from app.services.mirofish.goodrich_backtest import engine as E


def test_block_bootstrap_interval_excludes_zero_for_clear_shift():
    # 매 진입일 신규가 baseline 보다 일관되게 +2%p
    diffs_by_day = {f'2024-01-{d:02d}': [2.0, 2.0, 2.0] for d in range(1, 29)}

    lo, hi = E.bootstrap_interval(diffs_by_day, iterations=500, seed=7)

    assert lo > 0
    assert hi > lo


def test_block_bootstrap_interval_includes_zero_for_noise():
    diffs_by_day = {
        f'2024-01-{d:02d}': [5.0 if d % 2 else -5.0]
        for d in range(1, 29)
    }

    lo, hi = E.bootstrap_interval(diffs_by_day, iterations=500, seed=7)

    assert lo < 0 < hi


def test_bootstrap_is_reproducible_with_same_seed():
    diffs_by_day = {f'2024-01-{d:02d}': [float(d % 5) - 2] for d in range(1, 29)}

    first = E.bootstrap_interval(diffs_by_day, iterations=300, seed=11)
    second = E.bootstrap_interval(diffs_by_day, iterations=300, seed=11)

    assert first == second


def test_bootstrap_returns_none_for_empty_input():
    assert E.bootstrap_interval({}, iterations=100, seed=1) is None


def test_verdict_requires_interval_to_exclude_zero():
    assert E.verdict((0.4, 1.2)) == 'improved'
    assert E.verdict((-1.2, -0.4)) == 'worse'
    assert E.verdict((-0.3, 0.9)) == 'inconclusive'
    assert E.verdict(None) == 'inconclusive'


def test_split_dates_reserves_holdout():
    dates = ['2025-12-30', '2026-01-02', '2026-07-31']

    train, holdout = E.split_dates(dates, holdout_start='2025-09-04')

    assert train == ['2025-12-30']
    assert holdout == ['2026-01-02', '2026-07-31']


def test_corrupt_price_path_is_rejected_so_fake_returns_never_enter():
    """진입은 정상이어도 보유 구간에 가격제한폭 초과가 있으면 그 픽을 버린다.

    예) 2,080 -> 610,000 같은 오류가 출구가 되면 +29,000% 수익이 평균을 지배한다.
    """
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    clean = PriceBook({'000001': [
        Bar(date='2024-01-02', close=100, volume=10),
        Bar(date='2024-01-03', close=105, volume=10),
        Bar(date='2024-01-04', close=110, volume=10),
    ]})
    dirty = PriceBook({'000001': [
        Bar(date='2024-01-02', close=100, volume=10),
        Bar(date='2024-01-03', close=105, volume=10),
        Bar(date='2024-01-04', close=99999, volume=10),
    ]})

    assert E.has_clean_path(clean, '000001', '2024-01-02', '2024-01-04') is True
    assert E.has_clean_path(dirty, '000001', '2024-01-02', '2024-01-04') is False


def test_clean_path_ignores_sessions_outside_the_holding_window():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    book = PriceBook({'000001': [
        Bar(date='2024-01-02', close=100, volume=10),
        Bar(date='2024-01-03', close=105, volume=10),
        Bar(date='2024-01-04', close=99999, volume=10),  # 보유 구간 밖
    ]})

    assert E.has_clean_path(book, '000001', '2024-01-02', '2024-01-03') is True


def test_benchmark_follows_the_candidate_market():
    """코스닥 종목을 KOSPI 지수와 비교하던 원장 결함을 백테스트가 반복하지 않는다."""
    from app.services.mirofish.goodrich_backtest.universe import Candidate

    def _c(symbol, market):
        return Candidate(symbol=symbol, date='2024-01-03', close=100.0, volume=10,
                         change_pct=1.0, turnover=1000.0, volume_surge=1.0, market=market)

    assert E.benchmark_for(_c('000001', 'KOSPI')) == '069500'
    assert E.benchmark_for(_c('000002', 'KOSDAQ')) == '229200'
    assert E.benchmark_for(_c('000003', '')) == '069500'  # 미상은 대표지수
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_engine.py -q
```
Expected: `ModuleNotFoundError: No module named '...goodrich_backtest.engine'`

- [ ] **Step 3: 구현**

`app/services/mirofish/goodrich_backtest/engine.py`:

```python
"""백테스트 실행 + 유의성 판정.

평가는 goodrich_ledger.evaluate_pick 을 재사용한다 — look-ahead 차단,
날짜 정렬 벤치마크, 왕복 비용 로직이 이미 검증돼 있으므로 중복 구현하지 않는다.

유효 표본은 픽 수가 아니라 **진입일 수**다. 같은 날 픽들은 같은 시장 충격을
공유하므로, 부트스트랩은 진입일 단위로 블록 재표집한다.
"""

from __future__ import annotations

import random
import statistics
from typing import Any

from app.services.mirofish import goodrich_ledger as ledger
from app.services.mirofish.goodrich_backtest import rankers as R
from app.services.mirofish.goodrich_backtest import signals as S
from app.services.mirofish.goodrich_backtest.prices import PriceBook
from app.services.mirofish.goodrich_backtest.universe import (
    MAX_DAILY_MOVE_PCT,
    Candidate,
    load_markets,
    reconstruct_universe,
)


def split_dates(dates: list[str], *, holdout_start: str) -> tuple[list[str], list[str]]:
    """holdout_start 이상은 holdout. 후보 선정에 쓰지 않는다."""
    train = [d for d in dates if d < holdout_start]
    holdout = [d for d in dates if d >= holdout_start]
    return train, holdout


def benchmark_for(candidate: Candidate) -> str:
    """후보의 시장에 맞는 지수 프록시. ledger 의 해석기를 그대로 쓴다."""
    return ledger.benchmark_ticker({'market': candidate.market})


def has_clean_path(book: PriceBook, ticker: str, entry_date: str, exit_date: str) -> bool:
    """보유 구간 [entry_date, exit_date] 안에 가격제한폭 초과가 없는지.

    universe 필터는 진입일 등락률만 본다. 출구 가격이 오염된 경우
    (예: 2,080 -> 610,000) 가짜 수익이 평균을 지배하므로 여기서 한 번 더 막는다.
    """
    window = [
        bar for bar in book.series(ticker)
        if entry_date <= bar.date <= exit_date
    ]
    for prev, cur in zip(window, window[1:]):
        if prev.close <= 0:
            return False
        if abs(cur.close / prev.close - 1) * 100 > MAX_DAILY_MOVE_PCT:
            return False
    return True


def run_ranker(
    ranker_name: str,
    dates: list[str],
    book: PriceBook,
    *,
    top_k: int = 3,
    horizon: int = 3,
    per_source_top_n: int = 30,
) -> dict[str, list[float]]:
    """진입일별 TOP-k 픽의 초과수익(%) 목록.

    반환: {진입일: [초과수익, ...]}  — 평가 불가한 픽은 제외한다.
    """
    ranker = R.RANKERS[ranker_name]
    markets = load_markets()
    benchmark_cache: dict[str, list[dict[str, Any]]] = {}
    out: dict[str, list[float]] = {}

    for date in dates:
        candidates = reconstruct_universe(
            date, book, per_source_top_n=per_source_top_n, markets=markets,
        )
        if len(candidates) < top_k:
            continue
        ctx = R.RankContext(date=date, book=book, rs_ratings=S.rs_from_book(date, book))
        picks = R.rank_candidates(candidates, ranker, ctx)[:top_k]

        values = []
        for candidate, _score in picks:
            ticker = benchmark_for(candidate)
            if ticker not in benchmark_cache:
                benchmark_cache[ticker] = book.ledger_rows(ticker)
            evaluation = ledger.evaluate_pick(
                {
                    'symbol': candidate.symbol,
                    'entry_date': date,
                    'entry_price': candidate.close,
                    'cycle_id': f'bt_{date}',
                    'market': candidate.market,
                },
                book.ledger_rows(candidate.symbol),
                benchmark_cache[ticker],
                horizons=(horizon,),
            )
            row = (evaluation.get('horizons') or {}).get(str(horizon)) or {}
            excess = row.get('net_excess_return_pct')
            exit_date = str(row.get('exit_date') or '')
            if excess is None or not exit_date:
                continue
            if not has_clean_path(book, candidate.symbol, date, exit_date):
                continue  # 보유 구간에 데이터 오류 -> 수익률을 신뢰할 수 없다
            values.append(float(excess))
        if values:
            out[date] = values
    return out


def paired_daily_diff(
    challenger: dict[str, list[float]],
    baseline: dict[str, list[float]],
) -> dict[str, list[float]]:
    """같은 진입일에서 (신규 평균 - baseline 평균). 양쪽에 있는 날만 쓴다."""
    diffs: dict[str, list[float]] = {}
    for date in sorted(set(challenger) & set(baseline)):
        a, b = challenger[date], baseline[date]
        if a and b:
            diffs[date] = [statistics.mean(a) - statistics.mean(b)]
    return diffs


def bootstrap_interval(
    diffs_by_day: dict[str, list[float]],
    *,
    iterations: int = 2000,
    seed: int = 20260731,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """진입일 블록 부트스트랩 신뢰구간. 입력이 비면 None."""
    days = sorted(diffs_by_day)
    if not days:
        return None
    rng = random.Random(seed)
    n = len(days)
    means = []
    for _ in range(iterations):
        sample = []
        for _ in range(n):
            sample.extend(diffs_by_day[days[rng.randrange(n)]])
        if sample:
            means.append(statistics.mean(sample))
    if not means:
        return None
    means.sort()
    tail = (1 - confidence) / 2
    lo = means[int(tail * (len(means) - 1))]
    hi = means[int((1 - tail) * (len(means) - 1))]
    return round(lo, 4), round(hi, 4)


def verdict(interval: tuple[float, float] | None) -> str:
    """구간이 0 을 배제할 때만 판정한다."""
    if interval is None:
        return 'inconclusive'
    lo, hi = interval
    if lo > 0:
        return 'improved'
    if hi < 0:
        return 'worse'
    return 'inconclusive'


def compare(
    challenger_name: str,
    dates: list[str],
    book: PriceBook,
    *,
    top_k: int = 3,
    horizon: int = 3,
) -> dict[str, Any]:
    """challenger 를 baseline_current 와 같은 조건에서 비교한다."""
    challenger = run_ranker(challenger_name, dates, book, top_k=top_k, horizon=horizon)
    baseline = run_ranker('baseline_current', dates, book, top_k=top_k, horizon=horizon)
    diffs = paired_daily_diff(challenger, baseline)
    interval = bootstrap_interval(diffs)

    def mean_of(bucket: dict[str, list[float]]) -> float | None:
        flat = [v for values in bucket.values() for v in values]
        return round(statistics.mean(flat), 4) if flat else None

    return {
        'ranker': challenger_name,
        'horizon_days': horizon,
        'entry_days': len(diffs),
        'challenger_mean_excess_pct': mean_of(challenger),
        'baseline_mean_excess_pct': mean_of(baseline),
        'diff_ci95': interval,
        'verdict': verdict(interval),
    }
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_goodrich_backtest_engine.py -q
```
Expected: `9 passed`

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add app/services/mirofish/goodrich_backtest/engine.py tests/test_goodrich_backtest_engine.py
git commit -m "feat(goodrich-backtest): engine with entry-day block bootstrap and per-market benchmark"
```

---

## Task 7: CLI 진입점

**Files:**
- Create: `scripts/run_goodrich_backtest.py`

- [ ] **Step 1: 구현**

`scripts/run_goodrich_backtest.py`:

```python
"""Goodrich 랭커 비교 실행.

사용:
  python scripts/run_goodrich_backtest.py --horizon 3
  python scripts/run_goodrich_backtest.py --horizon 3 --segment holdout
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.services.mirofish.goodrich_backtest import engine, prices, rankers  # noqa: E402

HOLDOUT_START = '2025-09-04'  # 사용 가능 545세션의 75% 지점


def main() -> int:
    parser = argparse.ArgumentParser(description='Goodrich 랭커 비교')
    parser.add_argument('--horizon', type=int, default=3, help='보유 세션 수 (기본 3)')
    parser.add_argument('--top-k', type=int, default=3, help='진입일당 픽 수 (기본 3)')
    parser.add_argument('--segment', choices=('train', 'holdout', 'all'), default='all')
    parser.add_argument('--out', default=os.path.join(BASE_DIR, 'data', 'goodrich_backtest_result.json'))
    args = parser.parse_args()

    started = time.time()
    book = prices.load_prices()
    if not book.sessions:
        print('daily_prices.csv 를 읽지 못했습니다.')
        return 1

    train, holdout = engine.split_dates(book.usable_sessions(), holdout_start=HOLDOUT_START)
    dates = {'train': train, 'holdout': holdout, 'all': book.sessions}[args.segment]
    print(f'세션 {len(book.sessions)}일 | 대상 구간 {args.segment} {len(dates)}일 '
          f'| horizon T+{args.horizon} | top{args.top_k}')

    results = []
    for name in rankers.RANKERS:
        if name == 'baseline_current':
            continue
        result = engine.compare(name, dates, book, top_k=args.top_k, horizon=args.horizon)
        results.append(result)
        ci = result['diff_ci95']
        ci_text = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else 'n/a'
        print(f"  {name:18} 진입일 {result['entry_days']:>4}  "
              f"신규 {result['challenger_mean_excess_pct']}%  "
              f"baseline {result['baseline_mean_excess_pct']}%  "
              f"차이95%CI {ci_text}  -> {result['verdict']}")

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'segment': args.segment,
        'horizon_days': args.horizon,
        'top_k': args.top_k,
        'session_count': len(dates),
        'results': results,
        'elapsed_sec': round(time.time() - started, 1),
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'저장: {args.out}  ({payload["elapsed_sec"]}s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 2: 학습 구간에서 동작 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" scripts/run_goodrich_backtest.py --horizon 3 --segment train
```
Expected: 4개 랭커(baseline 제외) 각각에 대해 `진입일`, `신규`, `baseline`, `차이95%CI`, `verdict` 가 출력되고 `data/goodrich_backtest_result.json` 이 생성된다. 진입일 수는 480 내외.

- [ ] **Step 3: 전체 테스트 회귀 확인**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q -k "goodrich"
```
Expected: 신규 45개 + 기존 Goodrich 테스트 전부 통과

- [ ] **Step 4: 커밋**

```bash
cd /c/bitman_marketfloww
git add scripts/run_goodrich_backtest.py
git commit -m "feat(goodrich-backtest): CLI entry point for ranker comparison"
```

---

## Task 8: Phase 2 판정 실행 및 보고

**Files:**
- Create: `docs/goodrich_ranker_comparison_2026_07_31.md`

- [ ] **Step 1: 학습 구간 실행 (호라이즌 3종)**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
for H in 1 3 5; do
  PYTHONIOENCODING=utf-8 "$PYTHON" scripts/run_goodrich_backtest.py \
    --horizon $H --segment train --out data/goodrich_bt_train_T$H.json
done
```

- [ ] **Step 2: 학습 구간에서 후보 좁히기**

`verdict == 'improved'` 인 랭커만 다음 단계로 보낸다.
하나도 없으면 **Step 3 을 건너뛰고 Step 4 로 가서 "개선 없음"으로 보고한다.**
holdout 은 후보 선정에 쓰지 않는다.

- [ ] **Step 3: holdout 최종 확인 (학습에서 살아남은 랭커만)**

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
for H in 1 3 5; do
  PYTHONIOENCODING=utf-8 "$PYTHON" scripts/run_goodrich_backtest.py \
    --horizon $H --segment holdout --out data/goodrich_bt_holdout_T$H.json
done
```

- [ ] **Step 4: 결과 문서 작성**

`docs/goodrich_ranker_comparison_2026_07_31.md` 에 아래 항목을 채운다:

1. 실행 조건 — 세션 수, 학습/holdout 진입일 수, horizon, top_k
2. 랭커별 결과 표 — 진입일, 신규 평균 초과수익, baseline 평균 초과수익, 차이 95% CI, verdict
3. 학습 → holdout 일관성 — 학습에서 improved 였던 것이 holdout 에서도 유지되는지
4. **레짐별 성과** (spec §6.2) — `app/services/mirofish/intelligence/regime.py::read_regime_timeline()`
   으로 각 진입일의 레짐(RISK_ON / NEUTRAL / RISK_OFF)을 붙이고, 레짐별로 2번 표를 나눠 싣는다.
   현 표본이 급락 국면 1회뿐이었던 한계를 반복하지 않기 위함이다. 타임라인이 없으면
   `build_regime_timeline()` 을 먼저 실행한다.
5. **판정** — spec §6.3 규칙에 따라, holdout CI 가 0 을 배제하는 랭커가 있는지
6. 한계 — 유니버스 재현 오차, 수급 신호 미포함(시계열 부재), 표본 해상도(약 0.5%p) 미만
   차이는 주장하지 않음

**개선이 확인되지 않으면 그 사실을 그대로 쓴다.** spec §6.3 에 따라 Phase 3 으로
진행하지 않으며, 이는 잘못된 변경을 프로덕션에 넣지 않았다는 점에서 유효한 결과다.

- [ ] **Step 5: 커밋**

```bash
cd /c/bitman_marketfloww
git add docs/goodrich_ranker_comparison_2026_07_31.md data/goodrich_bt_*.json
git commit -m "docs: Goodrich ranker comparison results"
```

---

## 완료 조건

- [ ] Task 1~6: 5개 모듈 + 단위 테스트 **45개** 통과
      (prices 5 / universe 10 / signals 11 / rankers 7 / engine 9
       — look-ahead 회귀 3건, 데이터 오염 차단 4건 포함)
- [ ] Task 7: CLI 로 학습 구간 실행 성공, 결과 JSON 생성
- [ ] Task 8: 학습 → holdout 순서로 판정, 레짐별 성과 포함, 결과 문서 커밋
- [ ] 프로덕션 파일 무변경 확인 — 아래가 **빈 출력**이어야 한다:
      ```bash
      git diff --stat HEAD -- app/services/mirofish/goodrich_client.py \
        app/services/mirofish/goodrich_ledger.py scripts/run_goodrich_intraday_cycle.py
      ```
- [ ] 기존 Goodrich 테스트 스위트 회귀 없음:
      ```bash
      PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/ -q -k "goodrich or mirofish"
      ```

## 범위 밖 (Phase 3+)

- `goodrich_ranker.py` 프로덕션 랭커
- Goodrich 계약 확장 (`ranked_candidates`)
- 2제품 분리 / 등급 UI
- 원장 `market` 필드 기록 수정
