> **2026-11-13 운영 인계 보완:** 아래 원안의 Task 14 전종목 FDR 수집, 종가베팅만 후보 선정, 기본 텔레그램 알림, v1 정규장 소스 가정은 [최신 인계 기록](../../forecast_league_handoff_2026_11_13.md)의 결정을 따른다. 기존 사용자 승인 범위에서 검증·통합하며 첫 자연 실행과 성과 성숙은 구분한다.

# 예측 리그 1단계 (원장·채점기·기준선·워커) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 예측을 시점 고정으로 기록하고 표준 사건 `E1`으로 자동 채점하는 원장을 만들고, 기준선 예측자 두 개가 매일 예측을 내고 채점되게 한다.

**Architecture:** `app/services/forecast_league/`가 SQLite(WAL) 파일 `data/forecast_league/league.db` 하나에 예측·근거 캡슐·가격 봉·해소·성적표·잡을 저장한다. `app/services/league_worker/`는 잡 큐를 비우고 종료하는 프로세스이며 miniPC 작업 스케줄러가 5분마다 실행한다. `scheduler.py`에는 잡을 큐에 넣는 호출 두 개만 추가한다.

**Tech Stack:** Python 3 표준 라이브러리(`sqlite3`, `hashlib`, `zlib`), 기존 `KISRegularProvider`(정규장 분봉), FinanceDataReader(기준선 입력용 일봉), pytest.

**설계서:** `docs/superpowers/specs/2026-11-12-forecast-league-design.md` §5, §7, §11, §12.

---

## 0. 선행 확인 결과 (2026-11-12 실측)

설계서 §5.7은 1단계 첫 작업으로 `daily_prices.csv`의 가격이 정규장 값인지 확인하라고 했다. 본PC의 `data/daily_prices.csv`(2026-07-31까지)와 당일 외부 조회로 확인한 결과는 다음과 같다.

1. **`daily_prices.csv`는 채점에 쓸 수 없다.** `scheduler.update_daily_prices()`는 마지막 날짜 다음 날부터만 덧붙이고 14:50대에 실행된다. 2026-04 이후 행의 대부분이 14:51~14:53 수집분이다(전체 628거래일 중 85일, 2026-05~06은 전 행). 15:30까지의 고가·저가·종가가 빠져 있고 이후에 교정되지 않는다. 시가가 0이거나 고가·저가 범위를 벗어난 행도 3.32% 있다.
2. **장 마감 후 당일 조회도 출처마다 값이 다르다.** 2026-11-12 20:11 KST에 시가총액 상위 25종목을 조회했더니, FinanceDataReader의 전 종목 목록과 종목별 일봉이 종가 25종목, 저가 10종목, 고가 1종목에서 달랐다. 시가는 모두 같았다. `docs/alpha_reliable_top3_research_2026_11_10.md`가 KIS 일봉에서 확인한 장후 가격 혼재와 같은 양상이다.
3. 어느 쪽이 정규장 값인지는 본PC에서 판정하지 못했다(본PC의 KIS MCP는 모의 서버라 대조 근거로 쓰지 않았다).

**이 계획의 결정:** 채점 가격은 `daily_prices.csv`가 아니라 리그 전용 봉 테이블에서 읽는다.

| 용도 | 기준(`basis`) | 출처 | 수집 시각 |
|---|---|---|---|
| 해소·채점 | `krx_regular` | 기존 `KISRegularProvider` (KIS J 분봉 09:00~15:30 재구성, 11-10에 49종목 검증) | 거래일 20:40 이후, 미해소 예측 종목만 |
| 기준선 입력(기저율, 20일 수익률) | `provider_daily` | FinanceDataReader 종목별 일봉 | 다음 날 07:30, 당일 봉은 저장하지 않음 |

`provider_daily`는 정규장 값이라는 보증이 없으므로 채점에는 절대 쓰지 않는다. 기준선의 입력 추정치로만 쓴다.

## 0.1 설계서와 달라지는 점

| 설계서 | 이 계획 | 이유 |
|---|---|---|
| §5.7 가격 출처는 `daily_prices.csv` 하나 | 위 표의 리그 전용 봉 | §0 실측. 설계서 §5.7의 "섞여 있으면 가격 출처부터 고친다"에 따름 |
| §7 상주 워커 + 워치독 | 5분 주기로 큐를 비우고 종료하는 작업 | 1단계 잡은 하루 두 번의 배치뿐이다. 상주 프로세스는 구독자 질문이 생기는 4단계에서 전환한다 |
| §5.6 기준선은 다른 예측자가 예측한 종목에 예측 | 1단계 후보 = 그날 종가베팅 V2 신호 종목 | 1단계에는 다른 예측자가 없다. 2단계에서 다른 예측자 종목의 합집합으로 넓힌다 |
| §5.1 `lessons`, `agent_run_events` 테이블 | 만들지 않음 | 3·5단계에서 쓰는 테이블 |
| §5.8 조회 API | 만들지 않음 | 성적표 화면과 함께 2단계에서 만든다 |
| §5.1 `scorecards.window` | 열 이름 `window_id`, 값은 `all` 하나 | `WINDOW`는 SQLite 예약어 |
| §5.7 `price_source_version` = 파일 수정 시각·행 수 | `krx_regular/kis-regular-j-minute-v1` | 출처가 파일이 아니라 계약 버전을 가진 수집기 |

`daily_prices.csv`를 쓰는 기존 엔진(가상 매매, 성과 추적 등)의 결과도 같은 문제의 영향을 받는다. 그 수정은 이 계획의 범위가 아니다(§ 마지막 "범위 밖").

## 파일 구조

```
app/services/forecast_league/
  __init__.py        패키지 설명
  paths.py           저장 위치 (env FORECAST_LEAGUE_DIR 로 덮어쓰기)
  clock.py           KST·거래일·제출 마감 계산
  db.py              스키마와 연결
  capsules.py        근거 캡슐 (내용 해시)
  ledger.py          예측자 등록, 예측 제출, 기권 기록
  events.py          E1 판정 (순수 함수)
  bars.py            가격 봉 저장소
  price_sources.py   봉 수집 (KIS 정규장, FDR 유니버스)
  resolver.py        미해소 예측 해소
  metrics.py         지표 (순수 함수)
  scorecards.py      성적표 집계
  derive.py          점수 → 확률 환산
  baselines.py       기준선 예측자 두 개
  candidates.py      1단계 후보 종목
app/services/league_worker/
  __init__.py
  jobs.py            영속 잡 큐
  handlers.py        잡 종류별 실행
  schedule.py        시간대별 잡 넣기
  __main__.py        drain 명령
scripts/audit_league_price_sources.py   가격 출처 점검 도구
deploy/register_league_worker_task.ps1  miniPC 작업 등록
tests/test_league_*.py                  모듈별 테스트
```

수정하는 기존 파일: `tests/conftest.py`(픽스처 1개), `scheduler.py`(함수 3개와 등록 2줄), `.gitignore`(1줄), `CLAUDE.md`(§18 추가).

## 공통 규칙

- 모든 명령은 워크트리 `/c/bitman_marketfloww/.worktrees/league-phase0`에서 실행한다. 원본 저장소 루트로 `cd` 하지 않는다.
- Python은 아래 변수로만 실행한다.

```bash
PROJECT="/c/bitman_marketfloww"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
WT="/c/bitman_marketfloww/.worktrees/league-phase0"
cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_ledger.py -q
```

- 브랜치: `feat/league-phase1-ledger` (`origin/main` `44225812` 기준, 이미 생성됨).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`를 붙인다.
- push, PR, 병합, miniPC 반영은 사용자 승인 후에만 한다.
- 8080 포트와 `backend/`는 건드리지 않는다.

---

### Task 1: 저장 위치, 시계, 스키마

**Files:**
- Create: `app/services/forecast_league/__init__.py`, `paths.py`, `clock.py`, `db.py`
- Modify: `tests/conftest.py` (파일 끝에 픽스처 추가), `.gitignore`
- Test: `tests/test_league_db.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/conftest.py` 끝에 추가:

```python
@pytest.fixture
def league_conn(tmp_path, monkeypatch):
    """격리된 예측 리그 DB 연결."""
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    from app.services.forecast_league import db
    with db.connect() as conn:
        yield conn
```

`tests/test_league_db.py`:

```python
import os
import sqlite3
from datetime import date, datetime, timezone

import pytest

from app.services.forecast_league import clock, db, paths

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731


def test_db_is_created_under_the_env_directory(league_conn, tmp_path):
    assert paths.db_path() == os.path.join(str(tmp_path / 'league'), 'league.db')
    assert os.path.isfile(paths.db_path())
    tables = {row[0] for row in league_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'forecasters', 'forecasts', 'abstentions', 'capsules', 'resolutions',
            'scorecards', 'bars', 'jobs'} <= tables
    assert league_conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'


def test_forecasts_and_capsules_cannot_be_changed(league_conn):
    league_conn.execute("INSERT INTO forecasters VALUES ('fx','1','engine','native','t')")
    league_conn.execute("INSERT INTO capsules VALUES ('h', x'00', 't')")
    league_conn.execute(
        "INSERT INTO forecasts VALUES ('f1','fx','1','005930','2026-11-12T06:30:00Z','E1',0.5,NULL,'h','',1,'t')")
    for statement in ("UPDATE forecasts SET probability=0.9", "DELETE FROM forecasts",
                      "UPDATE capsules SET payload=x'01'", "DELETE FROM capsules"):
        with pytest.raises(sqlite3.DatabaseError):
            league_conn.execute(statement)


def test_connect_rolls_back_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("INSERT INTO forecasters VALUES ('fx','1','engine','native','t')")
            raise RuntimeError('boom')
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM forecasters').fetchone()[0] == 0


def test_parse_ts_requires_an_offset():
    assert clock.parse_ts('2026-11-12T15:30:00+09:00') == datetime(2026, 11, 12, 6, 30, tzinfo=timezone.utc)
    assert clock.iso(clock.parse_ts('2026-11-12T15:30:00+09:00')) == '2026-11-12T06:30:00Z'
    with pytest.raises(ValueError):
        clock.parse_ts('2026-11-12T15:30:00')


def test_next_session_open_after():
    thursday_close = clock.parse_ts('2026-11-12T15:30:00+09:00')
    assert clock.iso(clock.next_session_open_after(thursday_close, WEEKDAYS)) == '2026-11-13T00:00:00Z'
    friday_close = clock.parse_ts('2026-11-13T15:30:00+09:00')
    assert clock.iso(clock.next_session_open_after(friday_close, WEEKDAYS)) == '2026-11-16T00:00:00Z'
    before_open = clock.parse_ts('2026-11-12T08:00:00+09:00')
    assert clock.iso(clock.next_session_open_after(before_open, WEEKDAYS)) == '2026-11-12T00:00:00Z'


def test_trading_day_helpers():
    assert clock.trading_days('2026-11-13', '2026-11-17', WEEKDAYS) == ['2026-11-13', '2026-11-16', '2026-11-17']
    assert clock.previous_trading_day(date(2026, 11, 16), WEEKDAYS) == date(2026, 11, 13)
    assert clock.close_ts('2026-11-12') == '2026-11-12T15:30:00+09:00'
    assert clock.kst_date(clock.parse_ts('2026-11-12T16:00:00Z')) == '2026-11-13'
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_db.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.forecast_league'`

- [ ] **Step 3: 구현**

`app/services/forecast_league/__init__.py`:

```python
"""예측 리그 — 예측을 시점 고정으로 기록하고 표준 사건으로 채점하는 원장.

설계: docs/superpowers/specs/2026-11-12-forecast-league-design.md
쓰기는 프로세스 내부 함수로만 한다. HTTP 쓰기 경로와 주문 경로는 없다.
"""
```

`app/services/forecast_league/paths.py`:

```python
"""예측 리그 저장 위치. 테스트와 호스트 이전은 env FORECAST_LEAGUE_DIR 로 덮어쓴다."""
from __future__ import annotations

import os

from app.utils.paths import DATA_DIR


def league_dir() -> str:
    return os.environ.get('FORECAST_LEAGUE_DIR') or os.path.join(DATA_DIR, 'forecast_league')


def db_path() -> str:
    return os.path.join(league_dir(), 'league.db')
```

`app/services/forecast_league/clock.py`:

```python
"""KST 시각, 거래일, 제출 마감 계산."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

KST = timezone(timedelta(hours=9))
SESSION_OPEN = time(9, 0)
TradingDay = Callable[[date], bool]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    """UTC 오프셋이 있는 ISO 시각만 받는다."""
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timestamp needs a UTC offset')
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def kst_date(value: datetime) -> str:
    return value.astimezone(KST).date().isoformat()


def close_ts(session_date: str) -> str:
    return f'{session_date}T15:30:00+09:00'


def is_trading_day(day: date) -> bool:
    """KRX 거래일 여부. 판정기를 못 부르면 평일은 거래일로 본다."""
    if day.weekday() >= 5:
        return False
    try:
        from app.services.kis_screener import _is_kr_trading_day
        return bool(_is_kr_trading_day(datetime.combine(day, time.min)))
    except Exception:
        return True


def next_session_open_after(ts: datetime, trading_day: TradingDay | None = None) -> datetime:
    """ts 보다 뒤에 오는 첫 정규장 시작 시각(UTC)."""
    check = trading_day or is_trading_day
    local = ts.astimezone(KST)
    day = local.date()
    for _ in range(30):
        opening = datetime.combine(day, SESSION_OPEN, KST)
        if check(day) and local < opening:
            return opening.astimezone(timezone.utc)
        day += timedelta(days=1)
    raise ValueError('no trading session within 30 days')


def trading_days(start: str, end: str, trading_day: TradingDay | None = None) -> list[str]:
    """start~end(포함) 사이의 거래일 목록."""
    check = trading_day or is_trading_day
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    days: list[str] = []
    while day <= last:
        if check(day):
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def previous_trading_day(day: date, trading_day: TradingDay | None = None) -> date:
    check = trading_day or is_trading_day
    cursor = day - timedelta(days=1)
    for _ in range(30):
        if check(cursor):
            return cursor
        cursor -= timedelta(days=1)
    raise ValueError('no trading session within 30 days')
```

`app/services/forecast_league/db.py`:

```python
"""league.db 스키마와 연결. forecasts 와 capsules 는 트리거로 수정·삭제를 막는다."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.services.forecast_league import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasters (
  forecaster_id TEXT NOT NULL, version TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('engine','agent','baseline')),
  probability_source TEXT NOT NULL CHECK (probability_source IN ('native','derived')),
  registered_at TEXT NOT NULL,
  PRIMARY KEY (forecaster_id, version)
);
CREATE TABLE IF NOT EXISTS capsules (
  capsule_hash TEXT PRIMARY KEY, payload BLOB NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id TEXT PRIMARY KEY, forecaster_id TEXT NOT NULL, version TEXT NOT NULL,
  stock_code TEXT NOT NULL, asof_ts TEXT NOT NULL, event_id TEXT NOT NULL,
  probability REAL NOT NULL, raw_score REAL, capsule_hash TEXT NOT NULL,
  source_ref TEXT NOT NULL DEFAULT '', official INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE (forecaster_id, version, stock_code, asof_ts, event_id),
  FOREIGN KEY (forecaster_id, version) REFERENCES forecasters (forecaster_id, version),
  FOREIGN KEY (capsule_hash) REFERENCES capsules (capsule_hash)
);
CREATE INDEX IF NOT EXISTS ix_forecasts_asof ON forecasts (asof_ts);
CREATE TABLE IF NOT EXISTS abstentions (
  forecaster_id TEXT NOT NULL, version TEXT NOT NULL, stock_code TEXT NOT NULL,
  asof_ts TEXT NOT NULL, event_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (forecaster_id, version, stock_code, asof_ts, event_id)
);
CREATE TABLE IF NOT EXISTS resolutions (
  forecast_id TEXT PRIMARY KEY REFERENCES forecasts (forecast_id),
  status TEXT NOT NULL CHECK (status IN ('resolved','void')),
  outcome INTEGER, resolved_at TEXT NOT NULL,
  entry_date TEXT, entry_price REAL, exit_date TEXT, exit_price REAL,
  exit_reason TEXT, net_return REAL, price_source_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scorecards (
  forecaster_id TEXT NOT NULL, version TEXT NOT NULL, event_id TEXT NOT NULL,
  window_id TEXT NOT NULL, status TEXT NOT NULL, n_resolved INTEGER NOT NULL,
  metrics_json TEXT NOT NULL, computed_at TEXT NOT NULL,
  PRIMARY KEY (forecaster_id, version, event_id, window_id)
);
CREATE TABLE IF NOT EXISTS bars (
  stock_code TEXT NOT NULL, session_date TEXT NOT NULL, basis TEXT NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  captured_at TEXT NOT NULL, evidence_hash TEXT,
  PRIMARY KEY (stock_code, session_date, basis)
);
CREATE INDEX IF NOT EXISTS ix_bars_basis_date ON bars (basis, session_date);
CREATE TABLE IF NOT EXISTS jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, args TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  not_before TEXT NOT NULL, result TEXT, last_error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS capsules_no_update BEFORE UPDATE ON capsules
BEGIN SELECT RAISE(ABORT, 'capsules are append-only'); END;
CREATE TRIGGER IF NOT EXISTS capsules_no_delete BEFORE DELETE ON capsules
BEGIN SELECT RAISE(ABORT, 'capsules are append-only'); END;
"""


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """정상 종료 시 커밋, 예외 시 롤백."""
    target = path or paths.db_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
```

`.gitignore`의 `data/admin_mirofish/` 줄 아래에 추가:

```
data/forecast_league/
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_db.py -q`
Expected: `6 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league tests/conftest.py tests/test_league_db.py .gitignore && git commit -m "feat(league): add ledger schema, paths, and trading clock

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 2: 근거 캡슐

**Files:**
- Create: `app/services/forecast_league/capsules.py`
- Test: `tests/test_league_capsules.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.services.forecast_league import capsules


def test_same_content_is_stored_once(league_conn):
    first = capsules.put_capsule(league_conn, {'b': 2, 'a': '가'})
    second = capsules.put_capsule(league_conn, {'a': '가', 'b': 2})
    assert first == second and len(first) == 64
    assert league_conn.execute('SELECT COUNT(*) FROM capsules').fetchone()[0] == 1
    assert capsules.get_capsule(league_conn, first) == {'a': '가', 'b': 2}


def test_different_content_gets_a_different_hash(league_conn):
    assert capsules.put_capsule(league_conn, {'a': 1}) != capsules.put_capsule(league_conn, {'a': 2})


def test_missing_capsule_returns_none(league_conn):
    assert capsules.get_capsule(league_conn, '0' * 64) is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_capsules.py -q`
Expected: FAIL — `ImportError: cannot import name 'capsules'`

- [ ] **Step 3: 구현**

```python
"""근거 캡슐 — 예측 시점에 본 자료. 내용의 SHA-256 이 키다."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from typing import Any

from app.services.forecast_league import clock


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def put_capsule(conn: sqlite3.Connection, payload: Any) -> str:
    body = _canonical(payload)
    digest = hashlib.sha256(body).hexdigest()
    conn.execute('INSERT OR IGNORE INTO capsules (capsule_hash, payload, created_at) VALUES (?, ?, ?)',
                 (digest, zlib.compress(body), clock.iso(clock.now_utc())))
    return digest


def get_capsule(conn: sqlite3.Connection, capsule_hash: str) -> Any | None:
    row = conn.execute('SELECT payload FROM capsules WHERE capsule_hash = ?', (capsule_hash,)).fetchone()
    if row is None:
        return None
    return json.loads(zlib.decompress(row['payload']).decode('utf-8'))
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_capsules.py -q`
Expected: `3 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/capsules.py tests/test_league_capsules.py && git commit -m "feat(league): add content-addressed evidence capsules

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 3: 예측 제출 (원장)

**Files:**
- Create: `app/services/forecast_league/ledger.py`
- Test: `tests/test_league_ledger.py`

설계서 §5.3의 규칙 여섯 개를 그대로 구현한다. `created_at`은 호출자가 넘길 수 없다. 테스트는 모듈의 `_now`를 바꿔 시각을 고정한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from datetime import datetime, timezone

import pytest

from app.services.forecast_league import capsules, ledger

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
ASOF = '2026-11-12T15:30:00+09:00'          # 목요일 종가


def _at(monkeypatch, text):
    moment = datetime.fromisoformat(text).astimezone(timezone.utc)
    monkeypatch.setattr(ledger, '_now', lambda: moment)


def _ready(conn):
    ledger.register_forecaster(conn, 'fx', '1', 'engine', 'native')
    return capsules.put_capsule(conn, {'k': 1})


def _submit(conn, capsule, **over):
    args = dict(forecaster_id='fx', version='1', stock_code='005930', asof_ts=ASOF, event_id='E1',
                probability=0.4, capsule_hash=capsule, trading_day=WEEKDAYS)
    args.update(over)
    return ledger.submit_forecast(conn, **args)


def test_submission_is_recorded_with_server_time(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    forecast_id = _submit(league_conn, _ready(league_conn), raw_score=11.0, source_ref='run-1')
    row = league_conn.execute('SELECT * FROM forecasts WHERE forecast_id = ?', (forecast_id,)).fetchone()
    assert row['asof_ts'] == '2026-11-12T06:30:00Z'
    assert row['created_at'] == '2026-11-12T11:00:00Z'
    assert (row['probability'], row['raw_score'], row['source_ref'], row['official']) == (0.4, 11.0, 'run-1', 1)


def test_submission_at_or_after_the_next_open_is_rejected(league_conn, monkeypatch):
    capsule = _ready(league_conn)
    _at(monkeypatch, '2026-11-13T09:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule)
    assert error.value.code == 'late_submission'
    _at(monkeypatch, '2026-11-13T08:59:59+09:00')
    assert _submit(league_conn, capsule)


def test_friday_forecast_can_be_submitted_over_the_weekend(league_conn, monkeypatch):
    capsule = _ready(league_conn)
    _at(monkeypatch, '2026-11-15T22:00:00+09:00')
    assert _submit(league_conn, capsule, asof_ts='2026-11-13T15:30:00+09:00')
    _at(monkeypatch, '2026-11-16T09:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule, asof_ts='2026-11-13T15:30:00+09:00', stock_code='000660')
    assert error.value.code == 'late_submission'


def test_future_asof_is_rejected(league_conn, monkeypatch):
    capsule = _ready(league_conn)
    _at(monkeypatch, '2026-11-12T15:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule)
    assert error.value.code == 'asof_in_future'


@pytest.mark.parametrize('probability', [0.0, 0.019, 0.981, 1.0, float('nan'), True, '0.5'])
def test_probability_outside_the_range_is_rejected_not_clipped(league_conn, monkeypatch, probability):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, _ready(league_conn), probability=probability)
    assert error.value.code in {'probability_out_of_range', 'invalid_probability'}
    assert league_conn.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0] == 0


def test_boundary_probabilities_are_accepted(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    capsule = _ready(league_conn)
    assert _submit(league_conn, capsule, probability=0.02)
    assert _submit(league_conn, capsule, probability=0.98, stock_code='000660')


def test_duplicate_key_is_rejected(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    capsule = _ready(league_conn)
    _submit(league_conn, capsule)
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule, probability=0.9, asof_ts='2026-11-12T06:30:00Z')
    assert error.value.code == 'duplicate'


def test_missing_capsule_forecaster_event_or_code_is_rejected(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    capsule = _ready(league_conn)
    cases = [(dict(capsule_hash='0' * 64), 'capsule_missing'), (dict(forecaster_id='nobody'), 'unknown_forecaster'),
             (dict(event_id='E9'), 'unknown_event'), (dict(stock_code='5930'), 'invalid_stock_code'),
             (dict(asof_ts='2026-11-12T15:30:00'), 'invalid_asof')]
    for override, code in cases:
        with pytest.raises(ledger.SubmissionRejected) as error:
            _submit(league_conn, capsule, **override)
        assert error.value.code == code


def test_forecaster_registration_is_idempotent_but_not_mutable(league_conn):
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    assert league_conn.execute('SELECT COUNT(*) FROM forecasters').fetchone()[0] == 1
    with pytest.raises(ValueError):
        ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'derived')
    with pytest.raises(ValueError):
        ledger.register_forecaster(league_conn, 'fy', '1', 'robot', 'native')


def test_abstention_is_recorded_once(league_conn):
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    for _ in range(2):
        ledger.record_abstention(league_conn, forecaster_id='fx', version='1', stock_code='005930',
                                 asof_ts=ASOF, event_id='E1', reason='tool_failure')
    rows = league_conn.execute('SELECT asof_ts, reason FROM abstentions').fetchall()
    assert [tuple(row) for row in rows] == [('2026-11-12T06:30:00Z', 'tool_failure')]


def test_module_exposes_no_way_to_change_a_forecast():
    public = [name for name in dir(ledger) if not name.startswith('_')]
    assert not [name for name in public if any(word in name.lower() for word in
                                               ('update', 'delete', 'remove', 'edit', 'amend', 'replace'))]


def test_clamp_probability():
    assert ledger.clamp_probability(0.0) == 0.02
    assert ledger.clamp_probability(1.0) == 0.98
    assert ledger.clamp_probability(0.5) == 0.5
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_ledger.py -q`
Expected: FAIL — `ImportError: cannot import name 'ledger'`

- [ ] **Step 3: 구현**

```python
"""예측 제출과 기권 기록. 추가만 가능하고 제출 시각은 서버가 찍는다 (설계서 §5.3)."""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3

from app.services.forecast_league import clock

EVENT_IDS = frozenset({'E1'})
PROBABILITY_MIN = 0.02
PROBABILITY_MAX = 0.98
_KINDS = frozenset({'engine', 'agent', 'baseline'})
_SOURCES = frozenset({'native', 'derived'})
_STOCK_CODE = re.compile(r'[0-9]{6}')


class SubmissionRejected(ValueError):
    """제출 거부. code 가 사유다."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now():
    return clock.now_utc()


def clamp_probability(value: float) -> float:
    """환산·보정으로 계산한 확률을 제출 가능 범위로 옮긴다. 제출 함수는 범위 밖 값을 거부한다."""
    return min(PROBABILITY_MAX, max(PROBABILITY_MIN, float(value)))


def register_forecaster(conn: sqlite3.Connection, forecaster_id: str, version: str,
                        kind: str, probability_source: str) -> None:
    if kind not in _KINDS or probability_source not in _SOURCES:
        raise ValueError('unknown forecaster kind or probability source')
    row = conn.execute('SELECT kind, probability_source FROM forecasters WHERE forecaster_id = ? AND version = ?',
                       (forecaster_id, version)).fetchone()
    if row is None:
        conn.execute('INSERT INTO forecasters VALUES (?, ?, ?, ?, ?)',
                     (forecaster_id, version, kind, probability_source, clock.iso(_now())))
    elif (row['kind'], row['probability_source']) != (kind, probability_source):
        raise ValueError('a registered forecaster version cannot change; register a new version')


def _asof(asof_ts: str):
    try:
        return clock.parse_ts(asof_ts)
    except (ValueError, TypeError):
        raise SubmissionRejected('invalid_asof') from None


def submit_forecast(conn: sqlite3.Connection, *, forecaster_id: str, version: str, stock_code: str,
                    asof_ts: str, event_id: str, probability: float, capsule_hash: str,
                    raw_score: float | None = None, source_ref: str = '', official: bool = True,
                    trading_day: clock.TradingDay | None = None) -> str:
    if not isinstance(stock_code, str) or _STOCK_CODE.fullmatch(stock_code) is None:
        raise SubmissionRejected('invalid_stock_code')
    if event_id not in EVENT_IDS:
        raise SubmissionRejected('unknown_event')
    if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not math.isfinite(probability):
        raise SubmissionRejected('invalid_probability')
    if not PROBABILITY_MIN <= probability <= PROBABILITY_MAX:
        raise SubmissionRejected('probability_out_of_range')
    asof = _asof(asof_ts)
    created = _now()
    if asof > created:
        raise SubmissionRejected('asof_in_future')
    if created >= clock.next_session_open_after(asof, trading_day):
        raise SubmissionRejected('late_submission')
    if conn.execute('SELECT 1 FROM forecasters WHERE forecaster_id = ? AND version = ?',
                    (forecaster_id, version)).fetchone() is None:
        raise SubmissionRejected('unknown_forecaster')
    if conn.execute('SELECT 1 FROM capsules WHERE capsule_hash = ?', (capsule_hash,)).fetchone() is None:
        raise SubmissionRejected('capsule_missing')
    asof_text = clock.iso(asof)
    key = '|'.join((forecaster_id, version, stock_code, asof_text, event_id))
    forecast_id = 'f_' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    try:
        conn.execute(
            'INSERT INTO forecasts (forecast_id, forecaster_id, version, stock_code, asof_ts, event_id, '
            'probability, raw_score, capsule_hash, source_ref, official, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (forecast_id, forecaster_id, version, stock_code, asof_text, event_id, float(probability),
             None if raw_score is None else float(raw_score), capsule_hash, str(source_ref),
             1 if official else 0, clock.iso(created)))
    except sqlite3.IntegrityError:
        raise SubmissionRejected('duplicate') from None
    return forecast_id


def record_abstention(conn: sqlite3.Connection, *, forecaster_id: str, version: str, stock_code: str,
                      asof_ts: str, event_id: str, reason: str) -> None:
    conn.execute('INSERT OR IGNORE INTO abstentions VALUES (?, ?, ?, ?, ?, ?, ?)',
                 (forecaster_id, version, stock_code, clock.iso(_asof(asof_ts)), event_id,
                  str(reason)[:200], clock.iso(_now())))
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_ledger.py -q`
Expected: `18 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/ledger.py tests/test_league_ledger.py && git commit -m "feat(league): add append-only forecast submission with deadline checks

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 4: E1 판정

**Files:**
- Create: `app/services/forecast_league/events.py`
- Test: `tests/test_league_events.py`

`E1`은 가상 매매 엔진(`app/services/mirofish/paper_positions.py`)과 같은 규칙이다. 진입일을 1일째로 세어 8번째 거래일까지 본다. 각 거래일 안에서는 손절(저가)을 익절(고가)보다 먼저 본다. CIO SELL 청산은 `E1`에 없다. 적중(`outcome=1`)은 익절뿐이다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import pytest

from app.services.forecast_league import events
from app.services.mirofish import paper_positions as pp


def _bar(day, open_, high, low, close):
    return {'date': f'2026-01-{day:02d}', 'open': open_, 'high': high, 'low': low, 'close': close}


FLAT = [_bar(day, 100, 103, 97, 100) for day in range(2, 10)]   # 8 거래일, 어느 쪽도 닿지 않음


def test_target_hit_is_a_success():
    result = events.evaluate_e1([_bar(2, 100, 104, 98, 103), _bar(3, 103, 108.5, 102, 107)], cost_pct=0.23)
    assert (result['outcome'], result['exit_reason'], result['exit_date']) == (1, 'target', '2026-01-03')
    assert result['entry_price'] == 100 and result['exit_price'] == pytest.approx(108.0)
    assert result['gross_return_pct'] == pytest.approx(8.0)
    assert result['net_return_pct'] == pytest.approx(7.77)


def test_stop_hit_is_a_failure():
    result = events.evaluate_e1([_bar(2, 100, 101, 92.5, 94)], cost_pct=0.23)
    assert (result['outcome'], result['exit_reason']) == (0, 'stop')
    assert result['exit_price'] == pytest.approx(93.0)
    assert result['net_return_pct'] == pytest.approx(-7.23)


def test_both_touched_on_the_same_day_is_a_failure():
    result = events.evaluate_e1([_bar(2, 100, 110, 92, 105)], cost_pct=0.0)
    assert (result['outcome'], result['exit_reason']) == (0, 'stop')


def test_expiry_on_the_eighth_session_is_a_failure_at_the_close():
    bars = FLAT[:7] + [_bar(9, 100, 104, 99, 104)]
    result = events.evaluate_e1(bars, cost_pct=0.0)
    assert (result['outcome'], result['exit_reason'], result['exit_date']) == (0, 'expiry', '2026-01-09')
    assert result['gross_return_pct'] == pytest.approx(4.0)


def test_undecided_until_enough_sessions_exist():
    assert events.evaluate_e1([], cost_pct=0.0) is None
    assert events.evaluate_e1(FLAT[:7], cost_pct=0.0) is None


def test_sessions_after_the_eighth_are_ignored():
    bars = FLAT + [_bar(12, 100, 200, 100, 200)]
    assert events.evaluate_e1(bars, cost_pct=0.0)['exit_reason'] == 'expiry'


def test_non_positive_entry_is_an_error():
    with pytest.raises(ValueError):
        events.evaluate_e1([_bar(2, 0, 1, 0, 1)], cost_pct=0.0)


@pytest.mark.parametrize('bars', [
    [_bar(2, 100, 104, 98, 103), _bar(3, 103, 108.5, 102, 107)],
    [_bar(2, 100, 101, 92.5, 94)],
    [_bar(2, 100, 110, 92, 105)],
    FLAT[:7] + [_bar(9, 100, 104, 99, 104)],
])
def test_matches_the_paper_position_engine(tmp_path, monkeypatch, bars):
    """CIO SELL 청산이 없는 사례에서 가상 매매 엔진과 같은 입력에 같은 결과."""
    monkeypatch.setattr(pp, 'LEDGER_PATH', str(tmp_path / 'paper.json'))
    for name in ('MIROFISH_PAPER_DISABLED', 'MIROFISH_PAPER_TARGET_PCT', 'MIROFISH_PAPER_STOP_PCT',
                 'MIROFISH_PAPER_MAX_DAYS'):
        monkeypatch.delenv(name, raising=False)
    pp.save_ledger({'pending': [{'symbol': '005930', 'name': 'x', 'market': '', 'detected_at': '2026-01-01',
                                 'workflow_id': '', 'run_id': '', 'score': None}], 'open': [], 'closed': []})
    feed = lambda symbol: bars  # noqa: E731
    pp.settle_pending(feed)
    paper = pp.evaluate_positions(feed, cio_actions={})[0]
    league = events.evaluate_e1(bars, cost_pct=0.0)
    assert league['exit_reason'] == paper['exit_reason']
    assert league['exit_date'] == paper['exit_date']
    assert league['exit_price'] == pytest.approx(paper['exit_price'], abs=1e-3)
    assert league['gross_return_pct'] == pytest.approx(paper['return_pct'], abs=0.006)
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_events.py -q`
Expected: FAIL — `ImportError: cannot import name 'events'`

- [ ] **Step 3: 구현**

```python
"""표준 사건 판정. 정의는 바꾸지 않는다 — 새 사건은 새 event_id 로 추가한다 (설계서 §5.2).

E1: 기준일 다음 거래일 시가에 진입해 8거래일 안에 +8% 에 닿으면 적중.
    -7% 에 먼저 닿거나, 같은 날 둘 다 닿거나, 8거래일째 종가까지 닿지 못하면 실패.
"""
from __future__ import annotations

from typing import Any

E1_TARGET_PCT = 8.0
E1_STOP_PCT = 7.0
E1_MAX_SESSIONS = 8


def evaluate_e1(bars: list[dict[str, Any]], *, cost_pct: float) -> dict[str, Any] | None:
    """bars: 진입일부터 날짜 오름차순으로 빠짐없이 이어진 봉. 아직 판정할 수 없으면 None."""
    if not bars:
        return None
    entry = float(bars[0]['open'])
    if entry <= 0:
        raise ValueError('entry open must be positive')
    target = entry * (1 + E1_TARGET_PCT / 100.0)
    stop = entry * (1 - E1_STOP_PCT / 100.0)

    def done(outcome: int, reason: str, exit_price: float, bar: dict[str, Any]) -> dict[str, Any]:
        gross = (exit_price / entry - 1) * 100.0
        return {'outcome': outcome, 'entry_date': str(bars[0]['date']), 'entry_price': entry,
                'exit_date': str(bar['date']), 'exit_price': exit_price, 'exit_reason': reason,
                'gross_return_pct': gross, 'net_return_pct': gross - float(cost_pct)}

    for held, bar in enumerate(bars[:E1_MAX_SESSIONS], start=1):
        if float(bar['low']) <= stop:
            return done(0, 'stop', stop, bar)
        if float(bar['high']) >= target:
            return done(1, 'target', target, bar)
        if held >= E1_MAX_SESSIONS:
            return done(0, 'expiry', float(bar['close']), bar)
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_events.py -q`
Expected: `11 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/events.py tests/test_league_events.py && git commit -m "feat(league): add E1 event evaluation matching the paper engine

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 5: 가격 봉 저장소

**Files:**
- Create: `app/services/forecast_league/bars.py`
- Test: `tests/test_league_bars.py`

`krx_regular` 봉은 한 번 저장하면 바꾸지 않는다. `provider_daily` 봉은 수정주가 재계산을 반영하려고 덮어쓸 수 있다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import pytest

from app.services.forecast_league import bars


def _put(conn, **over):
    args = dict(stock_code='005930', session_date='2026-11-12', basis=bars.BASIS_REGULAR,
                open=100.0, high=110.0, low=95.0, close=105.0, captured_at='2026-11-12T11:40:00Z')
    args.update(over)
    return bars.put_bar(conn, **args)


def test_regular_bar_is_stored_once_and_never_replaced(league_conn):
    assert _put(league_conn) is True
    assert _put(league_conn, close=999.0, high=999.0) is False
    assert [row['close'] for row in bars.get_bars(league_conn, '005930', bars.BASIS_REGULAR, '2026-11-01')] == [105.0]
    with pytest.raises(ValueError):
        _put(league_conn, replace=True)


def test_universe_bar_can_be_replaced(league_conn):
    _put(league_conn, basis=bars.BASIS_UNIVERSE)
    assert _put(league_conn, basis=bars.BASIS_UNIVERSE, close=50.0, low=45.0, open=50.0, high=55.0, replace=True) is True
    assert bars.get_bars(league_conn, '005930', bars.BASIS_UNIVERSE, '2026-11-01')[0]['close'] == 50.0


@pytest.mark.parametrize('over', [dict(open=0), dict(low=101.0), dict(high=104.0), dict(close=-1),
                                   dict(session_date='20261112'), dict(basis='other')])
def test_invalid_bars_are_not_stored(league_conn, over):
    assert _put(league_conn, **over) is False
    assert league_conn.execute('SELECT COUNT(*) FROM bars').fetchone()[0] == 0


def test_bars_are_returned_in_date_order_within_the_range(league_conn):
    for day in ('2026-11-13', '2026-11-11', '2026-11-12'):
        _put(league_conn, session_date=day)
    _put(league_conn, session_date='2026-11-12', stock_code='000660')
    rows = bars.get_bars(league_conn, '005930', bars.BASIS_REGULAR, '2026-11-12', '2026-11-13')
    assert [row['date'] for row in rows] == ['2026-11-12', '2026-11-13']
    assert set(rows[0]) == {'date', 'open', 'high', 'low', 'close'}
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_bars.py -q`
Expected: FAIL — `ImportError: cannot import name 'bars'`

- [ ] **Step 3: 구현**

```python
"""리그 전용 가격 봉.

krx_regular    정규장(09:00~15:30) 봉. 해소·채점에만 쓴다. 한 번 저장하면 바꾸지 않는다.
provider_daily 공급자 일봉. 정규장 보증이 없어 기준선의 입력 추정치로만 쓴다.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

BASIS_REGULAR = 'krx_regular'
BASIS_UNIVERSE = 'provider_daily'
REGULAR_SOURCE_VERSION = 'krx_regular/kis-regular-j-minute-v1'
_BASES = frozenset({BASIS_REGULAR, BASIS_UNIVERSE})


def _valid(session_date: str, basis: str, open_: float, high: float, low: float, close: float) -> bool:
    try:
        if basis not in _BASES or date.fromisoformat(session_date).isoformat() != session_date:
            return False
        open_, high, low, close = float(open_), float(high), float(low), float(close)
    except (TypeError, ValueError):
        return False
    return min(open_, high, low, close) > 0 and low <= min(open_, close) and high >= max(open_, close)


def put_bar(conn: sqlite3.Connection, *, stock_code: str, session_date: str, basis: str,
            open: float, high: float, low: float, close: float, captured_at: str,
            evidence_hash: str | None = None, replace: bool = False) -> bool:
    """저장했으면 True. 값이 봉으로 성립하지 않거나 이미 있으면 False."""
    if replace and basis == BASIS_REGULAR:
        raise ValueError('regular-session bars are never replaced')
    if not _valid(session_date, basis, open, high, low, close):
        return False
    verb = 'INSERT OR REPLACE' if replace else 'INSERT OR IGNORE'
    cursor = conn.execute(
        f'{verb} INTO bars (stock_code, session_date, basis, open, high, low, close, captured_at, evidence_hash) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (stock_code, session_date, basis, float(open), float(high), float(low), float(close),
         captured_at, evidence_hash))
    return cursor.rowcount == 1


def get_bars(conn: sqlite3.Connection, stock_code: str, basis: str, start_date: str,
             end_date: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        'SELECT session_date AS date, open, high, low, close FROM bars '
        'WHERE stock_code = ? AND basis = ? AND session_date >= ? AND session_date <= ? ORDER BY session_date',
        (stock_code, basis, start_date, end_date or '9999-12-31')).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_bars.py -q`
Expected: `9 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/bars.py tests/test_league_bars.py && git commit -m "feat(league): add league-owned price bar store with explicit basis

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 6: 해소기

**Files:**
- Create: `app/services/forecast_league/resolver.py`
- Test: `tests/test_league_resolver.py`

미해소 예측마다 진입일(기준 시각 뒤 첫 정규장)부터 거래일을 세고, 빠진 날이 나오기 전까지의 `krx_regular` 봉으로 `E1`을 판정한다. 진입일부터 20거래일이 지나도 판정하지 못하면 `void`로 닫는다(설계서 §11).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from datetime import datetime, timezone

import pytest

from app.services.forecast_league import bars, capsules, ledger, resolver

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
SESSIONS = ['2026-11-13', '2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20',
            '2026-11-23', '2026-11-24']


@pytest.fixture
def forecast(league_conn, monkeypatch):
    moment = datetime(2026, 11, 12, 11, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ledger, '_now', lambda: moment)
    monkeypatch.setattr(resolver, '_now', lambda: datetime(2026, 12, 1, tzinfo=timezone.utc))
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    return ledger.submit_forecast(
        league_conn, forecaster_id='fx', version='1', stock_code='005930',
        asof_ts='2026-11-12T15:30:00+09:00', event_id='E1', probability=0.4,
        capsule_hash=capsules.put_capsule(league_conn, {'k': 1}), trading_day=WEEKDAYS)


def _bar(conn, day, open_=100.0, high=103.0, low=97.0, close=100.0, basis=bars.BASIS_REGULAR):
    bars.put_bar(conn, stock_code='005930', session_date=day, basis=basis, open=open_, high=high,
                 low=low, close=close, captured_at='t')


def _row(conn, forecast_id):
    return conn.execute('SELECT * FROM resolutions WHERE forecast_id = ?', (forecast_id,)).fetchone()


def test_target_resolves_as_a_success(league_conn, forecast):
    _bar(league_conn, SESSIONS[0])
    _bar(league_conn, SESSIONS[1], high=108.5)
    summary = resolver.resolve_pending(league_conn, today='2026-11-16', trading_day=WEEKDAYS)
    row = _row(league_conn, forecast)
    assert summary == {'resolved': 1, 'void': 0, 'pending': 0}
    assert (row['status'], row['outcome'], row['exit_reason']) == ('resolved', 1, 'target')
    assert (row['entry_date'], row['exit_date'], row['entry_price']) == ('2026-11-13', '2026-11-16', 100.0)
    assert row['net_return'] == pytest.approx(7.77)
    assert row['price_source_version'] == bars.REGULAR_SOURCE_VERSION
    assert row['resolved_at'] == '2026-12-01T00:00:00Z'


def test_missing_session_keeps_the_forecast_pending(league_conn, forecast):
    _bar(league_conn, SESSIONS[0])
    _bar(league_conn, SESSIONS[2], high=120.0)          # 11-16 봉이 없으므로 11-17 은 쓰지 않는다
    summary = resolver.resolve_pending(league_conn, today='2026-11-17', trading_day=WEEKDAYS)
    assert summary == {'resolved': 0, 'void': 0, 'pending': 1}
    assert _row(league_conn, forecast) is None


def test_only_regular_session_bars_are_used(league_conn, forecast):
    _bar(league_conn, SESSIONS[0], high=120.0, basis=bars.BASIS_UNIVERSE)
    assert resolver.resolve_pending(league_conn, today='2026-11-13', trading_day=WEEKDAYS)['pending'] == 1


def test_expiry_resolves_as_a_failure(league_conn, forecast):
    for day in SESSIONS:
        _bar(league_conn, day)
    resolver.resolve_pending(league_conn, today='2026-11-24', trading_day=WEEKDAYS)
    row = _row(league_conn, forecast)
    assert (row['outcome'], row['exit_reason'], row['exit_date']) == (0, 'expiry', '2026-11-24')


def test_resolution_is_idempotent(league_conn, forecast):
    _bar(league_conn, SESSIONS[0], low=90.0)
    first = resolver.resolve_pending(league_conn, today='2026-11-13', trading_day=WEEKDAYS)
    second = resolver.resolve_pending(league_conn, today='2026-11-13', trading_day=WEEKDAYS)
    assert first['resolved'] == 1 and second == {'resolved': 0, 'void': 0, 'pending': 0}
    assert league_conn.execute('SELECT COUNT(*) FROM resolutions').fetchone()[0] == 1


def test_unresolvable_forecast_is_voided_after_twenty_sessions(league_conn, forecast):
    assert resolver.resolve_pending(league_conn, today='2026-12-10', trading_day=WEEKDAYS)['pending'] == 1
    summary = resolver.resolve_pending(league_conn, today='2026-12-11', trading_day=WEEKDAYS)  # 21번째 거래일
    row = _row(league_conn, forecast)
    assert summary == {'resolved': 0, 'void': 1, 'pending': 0}
    assert (row['status'], row['outcome'], row['net_return']) == ('void', None, None)


def test_forecast_is_not_resolved_before_its_entry_session(league_conn, forecast):
    assert resolver.resolve_pending(league_conn, today='2026-11-12', trading_day=WEEKDAYS) == {
        'resolved': 0, 'void': 0, 'pending': 1}
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_resolver.py -q`
Expected: FAIL — `ImportError: cannot import name 'resolver'`

- [ ] **Step 3: 구현**

```python
"""미해소 예측 해소. 정규장 봉만 쓰고, 같은 예측을 다시 해소해도 행이 늘지 않는다."""
from __future__ import annotations

import sqlite3

from app.services.forecast_league import bars, clock, events
from app.services.mirofish import costs

VOID_AFTER_SESSIONS = 20


def _now():
    return clock.now_utc()


def entry_date(asof_ts: str, trading_day: clock.TradingDay | None = None) -> str:
    """기준 시각 뒤 첫 정규장의 날짜."""
    return clock.kst_date(clock.next_session_open_after(clock.parse_ts(asof_ts), trading_day))


def unresolved(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        'SELECT f.forecast_id, f.stock_code, f.asof_ts FROM forecasts f '
        'LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE r.forecast_id IS NULL AND f.event_id = 'E1' ORDER BY f.asof_ts, f.forecast_id").fetchall()


def resolve_pending(conn: sqlite3.Connection, *, today: str,
                    trading_day: clock.TradingDay | None = None) -> dict[str, int]:
    summary = {'resolved': 0, 'void': 0, 'pending': 0}
    cost = costs.round_trip_cost_pct()
    for row in unresolved(conn):
        first = entry_date(row['asof_ts'], trading_day)
        expected = clock.trading_days(first, today, trading_day) if first <= today else []
        stored = {bar['date']: bar for bar in bars.get_bars(conn, row['stock_code'], bars.BASIS_REGULAR, first, today)}
        sequence = []
        for day in expected[:events.E1_MAX_SESSIONS]:
            if day not in stored:
                break
            sequence.append(stored[day])
        result = events.evaluate_e1(sequence, cost_pct=cost)
        if result is not None:
            conn.execute(
                'INSERT OR IGNORE INTO resolutions (forecast_id, status, outcome, resolved_at, entry_date, '
                "entry_price, exit_date, exit_price, exit_reason, net_return, price_source_version) "
                "VALUES (?, 'resolved', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row['forecast_id'], result['outcome'], clock.iso(_now()), result['entry_date'],
                 result['entry_price'], result['exit_date'], result['exit_price'], result['exit_reason'],
                 result['net_return_pct'], bars.REGULAR_SOURCE_VERSION))
            summary['resolved'] += 1
        elif len(expected) > VOID_AFTER_SESSIONS:
            conn.execute(
                'INSERT OR IGNORE INTO resolutions (forecast_id, status, resolved_at, price_source_version) '
                "VALUES (?, 'void', ?, ?)",
                (row['forecast_id'], clock.iso(_now()), bars.REGULAR_SOURCE_VERSION))
            summary['void'] += 1
        else:
            summary['pending'] += 1
    return summary
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_resolver.py -q`
Expected: `7 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/resolver.py tests/test_league_resolver.py && git commit -m "feat(league): resolve forecasts from regular-session bars with void after 20 sessions

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 7: 지표

**Files:**
- Create: `app/services/forecast_league/metrics.py`
- Test: `tests/test_league_metrics.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import math

import pytest

from app.services.forecast_league import metrics


def test_brier_and_log_loss():
    pairs = [(0.8, 1), (0.2, 0), (0.6, 0)]
    assert metrics.brier(pairs) == pytest.approx((0.04 + 0.04 + 0.36) / 3)
    assert metrics.log_loss(pairs) == pytest.approx(-(math.log(0.8) + math.log(0.8) + math.log(0.4)) / 3)


def test_calibration_groups_by_probability_bin():
    rows = metrics.calibration([(0.05, 0), (0.07, 1), (0.95, 1), (0.98, 1)], bins=10)
    assert rows == [
        {'lo': 0.0, 'hi': 0.1, 'n': 2, 'mean_probability': pytest.approx(0.06), 'hit_rate': 0.5},
        {'lo': 0.9, 'hi': 1.0, 'n': 2, 'mean_probability': pytest.approx(0.965), 'hit_rate': 1.0},
    ]


def test_top_k_precision_takes_the_highest_probabilities_per_day():
    rows = [
        {'asof_ts': 'd1', 'stock_code': 'a', 'probability': 0.9, 'outcome': 1},
        {'asof_ts': 'd1', 'stock_code': 'b', 'probability': 0.8, 'outcome': 0},
        {'asof_ts': 'd1', 'stock_code': 'c', 'probability': 0.1, 'outcome': 1},
        {'asof_ts': 'd2', 'stock_code': 'a', 'probability': 0.5, 'outcome': 1},
    ]
    assert metrics.top_k_precision(rows, k=2) == pytest.approx(2 / 3)
    assert metrics.top_k_precision([], k=2) is None


def test_block_bootstrap_is_deterministic_and_brackets_the_mean():
    rows = [{'entry_date': f'd{index % 10}', 'value': float(index % 4)} for index in range(200)]
    stat = lambda sample: sum(row['value'] for row in sample) / len(sample)  # noqa: E731
    first = metrics.block_bootstrap_ci(rows, stat)
    assert first == metrics.block_bootstrap_ci(rows, stat)
    assert first[0] <= stat(rows) <= first[1]


def test_block_bootstrap_resamples_whole_days():
    rows = [{'entry_date': 'd1', 'value': 0.0}] * 50 + [{'entry_date': 'd2', 'value': 1.0}] * 50
    seen = set()
    stat = lambda sample: seen.add(len(sample)) or sum(row['value'] for row in sample) / len(sample)  # noqa: E731
    low, high = metrics.block_bootstrap_ci(rows, stat, n_boot=200)
    assert seen == {100} and (low, high) == (0.0, 1.0)
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_metrics.py -q`
Expected: FAIL — `ImportError: cannot import name 'metrics'`

- [ ] **Step 3: 구현**

```python
"""채점 지표. 입출력만 있는 순수 함수."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Callable, Sequence


def brier(pairs: Sequence[tuple[float, int]]) -> float:
    return sum((probability - outcome) ** 2 for probability, outcome in pairs) / len(pairs)


def log_loss(pairs: Sequence[tuple[float, int]]) -> float:
    total = sum(math.log(probability) if outcome else math.log(1 - probability) for probability, outcome in pairs)
    return -total / len(pairs)


def calibration(pairs: Sequence[tuple[float, int]], bins: int = 10) -> list[dict[str, Any]]:
    """확률 구간별 표본 수, 평균 확률, 실제 적중률. 표본이 없는 구간은 내지 않는다."""
    grouped: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for probability, outcome in pairs:
        grouped[min(int(probability * bins), bins - 1)].append((probability, outcome))
    return [{'lo': index / bins, 'hi': (index + 1) / bins, 'n': len(items),
             'mean_probability': sum(p for p, _ in items) / len(items),
             'hit_rate': sum(o for _, o in items) / len(items)}
            for index, items in sorted(grouped.items())]


def top_k_precision(rows: Sequence[dict[str, Any]], k: int = 3) -> float | None:
    """기준 시각별로 확률 상위 k개를 골랐을 때의 적중률."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row['asof_ts']].append(row)
    picks = [row for day in by_day.values()
             for row in sorted(day, key=lambda item: (-item['probability'], item['stock_code']))[:k]]
    return sum(row['outcome'] for row in picks) / len(picks) if picks else None


def block_bootstrap_ci(rows: Sequence[dict[str, Any]], stat: Callable[[list[dict[str, Any]]], float], *,
                       block_key: str = 'entry_date', n_boot: int = 1000, seed: int = 7,
                       alpha: float = 0.05) -> tuple[float, float]:
    """진입일 단위로 묶어 다시 뽑은 신뢰 구간. 같은 날 진입한 예측은 서로 독립이 아니다."""
    blocks: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        blocks[row[block_key]].append(row)
    groups = [blocks[key] for key in sorted(blocks)]
    rng = random.Random(seed)
    values = sorted(stat([row for _ in groups for row in rng.choice(groups)]) for _ in range(n_boot))
    low = values[int((alpha / 2) * (n_boot - 1))]
    high = values[int((1 - alpha / 2) * (n_boot - 1))]
    return low, high
```

`test_block_bootstrap_resamples_whole_days`는 두 날의 표본 수가 같아 다시 뽑은 표본 크기가 항상 100이다.

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_metrics.py -q`
Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/metrics.py tests/test_league_metrics.py && git commit -m "feat(league): add scoring metrics with day-block bootstrap intervals

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 8: 성적표

**Files:**
- Create: `app/services/forecast_league/scorecards.py`
- Test: `tests/test_league_scorecards.py`

공식 예측(`official=1`)만 집계한다. 해소 표본이 100건 미만이면 지표 없이 `insufficient`를 기록한다. 기준선 대비 차이는 `baseline_base_rate`와 종목·기준 시각이 같은 예측끼리만 비교한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import json

import pytest

from app.services.forecast_league import scorecards


def _seed(conn, forecaster, count, *, probability=0.6, hit_every=2, official=1, start=0, kind='engine'):
    conn.execute('INSERT OR IGNORE INTO forecasters VALUES (?, ?, ?, ?, ?)', (forecaster, '1', kind, 'native', 't'))
    conn.execute("INSERT OR IGNORE INTO capsules VALUES ('h', x'00', 't')")
    for index in range(start, start + count):
        day = f'2026-{1 + index // 28:02d}-{1 + index % 28:02d}'
        forecast_id = f'{forecaster}-{index}'
        conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)',
                     (forecast_id, forecaster, '1', '005930', f'{day}T06:30:00Z', 'E1', probability, 'h', '',
                      official, 't'))
        outcome = 1 if index % hit_every == 0 else 0
        conn.execute("INSERT INTO resolutions VALUES (?, 'resolved', ?, 't', ?, 100, ?, 108, 'target', ?, 'v')",
                     (forecast_id, outcome, day, day, 7.77 if outcome else -7.23))


def _card(conn, forecaster):
    row = conn.execute('SELECT * FROM scorecards WHERE forecaster_id = ?', (forecaster,)).fetchone()
    return row, json.loads(row['metrics_json'])


def test_fewer_than_one_hundred_resolved_is_insufficient(league_conn):
    _seed(league_conn, 'fx', 99)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved'], row['window_id']) == ('insufficient', 99, 'all')
    assert metrics == {'n_resolved': 99, 'n_void': 0, 'n_pending': 0}


def test_scored_card_has_every_metric(league_conn):
    _seed(league_conn, 'fx', 120)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved']) == ('scored', 120)
    assert metrics['hit_rate'] == pytest.approx(0.5)
    assert metrics['brier'] == pytest.approx(0.26)
    assert metrics['mean_net_return_pct'] == pytest.approx(0.27)
    assert metrics['top3_precision'] == pytest.approx(0.5)
    assert metrics['calibration'][0]['n'] == 120
    assert metrics['brier_ci95'][0] <= metrics['brier'] <= metrics['brier_ci95'][1]
    assert metrics['mean_net_return_ci95'][0] <= 0.27 <= metrics['mean_net_return_ci95'][1]
    assert metrics['baseline'] is None


def test_baseline_difference_uses_matched_forecasts_only(league_conn):
    _seed(league_conn, 'fx', 120, probability=0.6)
    _seed(league_conn, scorecards.BASELINE_ID, 100, probability=0.5, kind='baseline')
    scorecards.compute_scorecards(league_conn)
    _, metrics = _card(league_conn, 'fx')
    assert metrics['baseline']['forecaster_id'] == scorecards.BASELINE_ID
    assert metrics['baseline']['n_matched'] == 100
    assert metrics['baseline']['brier_diff'] == pytest.approx(0.26 - 0.25)
    _, baseline_metrics = _card(league_conn, scorecards.BASELINE_ID)
    assert baseline_metrics['baseline'] is None


def test_unofficial_void_and_pending_forecasts_are_not_scored(league_conn):
    _seed(league_conn, 'fx', 100)
    _seed(league_conn, 'fx', 30, official=0, start=100)
    league_conn.execute("INSERT INTO forecasts VALUES ('p1','fx','1','000660','2026-06-01T06:30:00Z','E1',0.5,NULL,'h','',1,'t')")
    league_conn.execute("INSERT INTO forecasts VALUES ('v1','fx','1','000660','2026-06-02T06:30:00Z','E1',0.5,NULL,'h','',1,'t')")
    league_conn.execute("INSERT INTO resolutions (forecast_id, status, resolved_at, price_source_version) VALUES ('v1','void','t','v')")
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert row['n_resolved'] == 100
    assert (metrics['n_void'], metrics['n_pending']) == (1, 1)


def test_recomputing_does_not_add_rows(league_conn):
    _seed(league_conn, 'fx', 120)
    first = scorecards.compute_scorecards(league_conn)
    before = _card(league_conn, 'fx')[1]
    second = scorecards.compute_scorecards(league_conn)
    assert len(first) == len(second) == 1
    assert league_conn.execute('SELECT COUNT(*) FROM scorecards').fetchone()[0] == 1
    assert _card(league_conn, 'fx')[1] == before
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_scorecards.py -q`
Expected: FAIL — `ImportError: cannot import name 'scorecards'`

- [ ] **Step 3: 구현**

```python
"""예측자별 성적표. 매번 전체를 다시 계산해 같은 키에 덮어쓴다 (멱등)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.services.forecast_league import clock, metrics

MIN_RESOLVED = 100
WINDOW_ALL = 'all'
BASELINE_ID = 'baseline_base_rate'
TOP_K = 3


def _rows(conn: sqlite3.Connection, forecaster_id: str, version: str, event_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        'SELECT f.stock_code, f.asof_ts, f.probability, r.status, r.outcome, r.entry_date, r.net_return '
        'FROM forecasts f LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id '
        'WHERE f.forecaster_id = ? AND f.version = ? AND f.event_id = ? AND f.official = 1',
        (forecaster_id, version, event_id))]


def _brier(rows: list[dict[str, Any]]) -> float:
    return metrics.brier([(row['probability'], row['outcome']) for row in rows])


def _mean_net(rows: list[dict[str, Any]]) -> float:
    return sum(row['net_return'] for row in rows) / len(rows)


def _baseline(conn: sqlite3.Connection, forecaster_id: str, event_id: str,
              resolved: list[dict[str, Any]]) -> dict[str, Any] | None:
    if forecaster_id == BASELINE_ID:
        return None
    reference = {(row['stock_code'], row['asof_ts']): row['probability'] for row in conn.execute(
        'SELECT f.stock_code, f.asof_ts, f.probability FROM forecasts f '
        'JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE f.forecaster_id = ? AND f.event_id = ? AND f.official = 1 AND r.status = 'resolved'",
        (BASELINE_ID, event_id))}
    matched = [(row, reference[(row['stock_code'], row['asof_ts'])]) for row in resolved
               if (row['stock_code'], row['asof_ts']) in reference]
    if not matched:
        return None
    own = metrics.brier([(row['probability'], row['outcome']) for row, _ in matched])
    base = metrics.brier([(probability, row['outcome']) for row, probability in matched])
    return {'forecaster_id': BASELINE_ID, 'n_matched': len(matched), 'brier_diff': own - base}


def compute_scorecards(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cards = []
    keys = conn.execute('SELECT DISTINCT forecaster_id, version, event_id FROM forecasts WHERE official = 1 '
                        'ORDER BY forecaster_id, version, event_id').fetchall()
    for key in keys:
        rows = _rows(conn, key['forecaster_id'], key['version'], key['event_id'])
        resolved = [row for row in rows if row['status'] == 'resolved']
        counts = {'n_resolved': len(resolved),
                  'n_void': sum(1 for row in rows if row['status'] == 'void'),
                  'n_pending': sum(1 for row in rows if row['status'] is None)}
        if len(resolved) < MIN_RESOLVED:
            status, body = 'insufficient', counts
        else:
            pairs = [(row['probability'], row['outcome']) for row in resolved]
            status = 'scored'
            body = {**counts,
                    'hit_rate': sum(outcome for _, outcome in pairs) / len(pairs),
                    'brier': metrics.brier(pairs),
                    'brier_ci95': list(metrics.block_bootstrap_ci(resolved, _brier)),
                    'log_loss': metrics.log_loss(pairs),
                    'calibration': metrics.calibration(pairs),
                    'top3_precision': metrics.top_k_precision(resolved, k=TOP_K),
                    'mean_net_return_pct': _mean_net(resolved),
                    'mean_net_return_ci95': list(metrics.block_bootstrap_ci(resolved, _mean_net)),
                    'baseline': _baseline(conn, key['forecaster_id'], key['event_id'], resolved)}
        conn.execute('INSERT OR REPLACE INTO scorecards VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     (key['forecaster_id'], key['version'], key['event_id'], WINDOW_ALL, status, len(resolved),
                      json.dumps(body, sort_keys=True), clock.iso(clock.now_utc())))
        cards.append({'forecaster_id': key['forecaster_id'], 'version': key['version'],
                      'event_id': key['event_id'], 'status': status, **body})
    return cards
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_scorecards.py -q`
Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/scorecards.py tests/test_league_scorecards.py && git commit -m "feat(league): add idempotent scorecards with a 100-sample gate

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 9: 점수 → 확률 환산

**Files:**
- Create: `app/services/forecast_league/derive.py`
- Test: `tests/test_league_derive.py`

"시점 이전 표본"은 청산일이 기준일(KST)보다 앞선 해소로 정의한다. 잡이 언제 돌았는지와 무관하게 결과가 같다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import pytest

from app.services.forecast_league import derive

ASOF = '2026-06-01T15:30:00+09:00'
EDGES = [0.5]


def _seed(conn, forecaster, count, *, score, outcome, exit_date='2026-05-01', start=0):
    conn.execute('INSERT OR IGNORE INTO forecasters VALUES (?, ?, ?, ?, ?)', (forecaster, '1', 'engine', 'derived', 't'))
    conn.execute("INSERT OR IGNORE INTO capsules VALUES ('h', x'00', 't')")
    for index in range(start, start + count):
        forecast_id = f'{forecaster}-{index}'
        conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, 0.5, ?, ?, ?, 1, ?)',
                     (forecast_id, forecaster, '1', '005930', f'2026-01-01T00:{index // 60:02d}:{index % 60:02d}Z',
                      'E1', score, 'h', '', 't'))
        conn.execute("INSERT INTO resolutions VALUES (?, 'resolved', ?, 't', ?, 100, ?, 100, 'expiry', 0, 'v')",
                     (forecast_id, outcome, exit_date, exit_date))


def _derive(conn, score, forecaster='fx'):
    return derive.derived_probability(conn, forecaster_id=forecaster, version='1', event_id='E1',
                                      raw_score=score, asof_ts=ASOF, bin_edges=EDGES, fallback=0.2)


def test_uses_the_score_bin_when_it_has_thirty_samples(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1)
    _seed(league_conn, 'fx', 30, score=0.1, outcome=0, start=30)
    assert _derive(league_conn, 0.8) == (0.98, 'score_bin')
    assert _derive(league_conn, 0.2) == (0.02, 'score_bin')


def test_falls_back_to_the_forecaster_overall_rate(league_conn):
    _seed(league_conn, 'fx', 29, score=0.9, outcome=1)
    _seed(league_conn, 'fx', 29, score=0.1, outcome=0, start=29)
    assert _derive(league_conn, 0.8) == (pytest.approx(0.5), 'forecaster_overall')


def test_falls_back_to_the_league_rate_then_to_the_given_value(league_conn):
    _seed(league_conn, 'other', 40, score=0.5, outcome=1)
    _seed(league_conn, 'other', 40, score=0.5, outcome=0, start=40)
    assert _derive(league_conn, 0.8) == (pytest.approx(0.5), 'league_base_rate')
    assert _derive(league_conn, 0.8, forecaster='other')[1] in {'score_bin', 'forecaster_overall'}


def test_uses_the_fallback_when_nothing_is_resolved(league_conn):
    assert _derive(league_conn, 0.8) == (0.2, 'fallback')


def test_samples_that_exit_on_or_after_the_asof_date_are_not_used(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1, exit_date='2026-05-29')
    _seed(league_conn, 'fx', 500, score=0.9, outcome=0, exit_date='2026-06-01', start=30)
    _seed(league_conn, 'fx', 500, score=0.9, outcome=0, exit_date='2026-06-02', start=530)
    assert _derive(league_conn, 0.8) == (0.98, 'score_bin')
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_derive.py -q`
Expected: FAIL — `ImportError: cannot import name 'derive'`

- [ ] **Step 3: 구현**

```python
"""점수만 내는 예측자의 확률 환산 (설계서 §5.5). 기준일 이전에 청산된 표본만 쓴다."""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from typing import Sequence

from app.services.forecast_league import clock
from app.services.forecast_league.ledger import clamp_probability

MIN_SAMPLES = 30


def derived_probability(conn: sqlite3.Connection, *, forecaster_id: str, version: str, event_id: str,
                        raw_score: float, asof_ts: str, bin_edges: Sequence[float],
                        fallback: float) -> tuple[float, str]:
    """(확률, 근거) 를 반환한다. 근거: score_bin / forecaster_overall / league_base_rate / fallback."""
    asof_date = clock.kst_date(clock.parse_ts(asof_ts))
    own = conn.execute(
        'SELECT f.raw_score, r.outcome FROM forecasts f JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE f.forecaster_id = ? AND f.version = ? AND f.event_id = ? AND r.status = 'resolved' "
        'AND r.exit_date < ? AND f.raw_score IS NOT NULL',
        (forecaster_id, version, event_id, asof_date)).fetchall()
    target = bisect_right(bin_edges, raw_score)
    same_bin = [row['outcome'] for row in own if bisect_right(bin_edges, row['raw_score']) == target]
    if len(same_bin) >= MIN_SAMPLES:
        return clamp_probability(sum(same_bin) / len(same_bin)), 'score_bin'
    if len(own) >= MIN_SAMPLES:
        return clamp_probability(sum(row['outcome'] for row in own) / len(own)), 'forecaster_overall'
    league = conn.execute(
        'SELECT COUNT(*) AS n, COALESCE(SUM(r.outcome), 0) AS hits FROM forecasts f '
        'JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE f.event_id = ? AND f.official = 1 AND r.status = 'resolved' AND r.exit_date < ?",
        (event_id, asof_date)).fetchone()
    if league['n'] >= MIN_SAMPLES:
        return clamp_probability(league['hits'] / league['n']), 'league_base_rate'
    return clamp_probability(fallback), 'fallback'
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_derive.py -q`
Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/derive.py tests/test_league_derive.py && git commit -m "feat(league): derive probabilities from scores using only prior resolutions

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 10: 후보 종목과 기준선 예측자

**Files:**
- Create: `app/services/forecast_league/candidates.py`, `app/services/forecast_league/baselines.py`
- Test: `tests/test_league_baselines.py`

- `baseline_base_rate`: `provider_daily` 봉으로 직전 250거래일의 전 종목 `E1` 적중률을 계산해 모든 후보에 같은 확률을 낸다. 표본이 30건 미만이면 기권한다.
- `baseline_momentum`: 20거래일 수익률의 유니버스 내 순위(0~1)를 점수로 삼고 Task 9의 환산으로 확률을 낸다.
- 기준일의 `provider_daily` 봉이 하나도 없으면 `UniverseBarsMissing`을 던진다(잡이 재시도한다).
- 같은 기준일로 다시 실행해도 예측이 늘지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.forecast_league import bars, baselines, candidates, capsules, ledger

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
ASOF_DATE = '2026-11-12'


def _sessions(count, end=ASOF_DATE):
    days, cursor = [], date.fromisoformat(end)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _series(conn, code, days, *, start=100.0, step=0.0, spike_every=0):
    price = start
    for index, day in enumerate(days):
        high = price * (1.10 if spike_every and index % spike_every == 0 else 1.01)
        bars.put_bar(conn, stock_code=code, session_date=day, basis=bars.BASIS_UNIVERSE, open=price, high=high,
                     low=price * 0.99, close=price, captured_at='t')
        price += step


@pytest.fixture
def at_evening(monkeypatch):
    moment = datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc)   # 11-13 07:30 KST
    monkeypatch.setattr(ledger, '_now', lambda: moment)


def test_universe_base_rate_counts_decided_paths_only(league_conn):
    days = _sessions(30)
    _series(league_conn, '000001', days, spike_every=1)     # 매일 +10% 고가 → 모든 경로 적중
    _series(league_conn, '000002', days)                    # 한 번도 닿지 않음 → 8일 만기 실패
    result = baselines.universe_base_rate(league_conn, ASOF_DATE)
    assert result['hits'] == 29                              # 000001: 신호일 29개 모두 다음 날 적중
    assert result['n'] == 29 + 22                            # 000002: 8거래일이 남은 신호일만 판정
    assert result['rate'] == pytest.approx(29 / 51)


def test_universe_base_rate_ignores_bars_after_the_asof_date(league_conn):
    days = _sessions(30)
    _series(league_conn, '000002', days)
    before = baselines.universe_base_rate(league_conn, ASOF_DATE)
    _series(league_conn, '000002', ['2026-11-13', '2026-11-16'], spike_every=1)
    assert baselines.universe_base_rate(league_conn, ASOF_DATE) == before


def test_momentum_ranks_use_twenty_session_returns(league_conn):
    days = _sessions(21)
    _series(league_conn, '000001', days, step=1.0)
    _series(league_conn, '000002', days, step=0.0)
    _series(league_conn, '000003', days, step=-1.0)
    _series(league_conn, '000004', days[1:], step=5.0)       # 20개뿐 → 순위 없음
    ranks = baselines.momentum_ranks(league_conn, ASOF_DATE)
    assert ranks == {'000003': 0.0, '000002': 0.5, '000001': 1.0}


def test_baselines_submit_one_forecast_each_per_candidate(league_conn, at_evening):
    days = _sessions(60)
    for code in ('000001', '000002', '000003'):
        _series(league_conn, code, days, step=0.1, spike_every=3)
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001', '000002'],
                                         trading_day=WEEKDAYS)
    assert summary == {'submitted': 4, 'abstained': 0, 'duplicate': 0}
    rows = league_conn.execute('SELECT forecaster_id, stock_code, probability, raw_score, capsule_hash, asof_ts '
                               'FROM forecasts ORDER BY forecaster_id, stock_code').fetchall()
    assert [(row['forecaster_id'], row['stock_code']) for row in rows] == [
        ('baseline_base_rate', '000001'), ('baseline_base_rate', '000002'),
        ('baseline_momentum', '000001'), ('baseline_momentum', '000002')]
    assert {row['asof_ts'] for row in rows} == {'2026-11-12T06:30:00Z'}
    assert rows[0]['probability'] == rows[1]['probability'] and 0.02 <= rows[0]['probability'] <= 0.98
    assert rows[0]['raw_score'] is None and rows[2]['raw_score'] is not None
    capsule = capsules.get_capsule(league_conn, rows[2]['capsule_hash'])
    assert capsule['forecaster'] == 'baseline_momentum' and capsule['derived_from'] == 'fallback'
    kinds = {row['forecaster_id']: (row['kind'], row['probability_source'])
             for row in league_conn.execute('SELECT * FROM forecasters')}
    assert kinds == {'baseline_base_rate': ('baseline', 'native'), 'baseline_momentum': ('baseline', 'derived')}


def test_rerun_does_not_add_forecasts(league_conn, at_evening):
    days = _sessions(60)
    _series(league_conn, '000001', days, spike_every=3)
    _series(league_conn, '000002', days, step=0.1, spike_every=3)
    baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    again = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    assert again == {'submitted': 0, 'abstained': 0, 'duplicate': 2}
    assert league_conn.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0] == 2


def test_short_history_abstains(league_conn, at_evening):
    _series(league_conn, '000001', _sessions(60), spike_every=3)
    _series(league_conn, '000009', _sessions(5))
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000009'], trading_day=WEEKDAYS)
    assert summary == {'submitted': 1, 'abstained': 1, 'duplicate': 0}
    row = league_conn.execute('SELECT forecaster_id, reason FROM abstentions').fetchone()
    assert tuple(row) == ('baseline_momentum', 'momentum_history_short')


def test_too_few_base_rate_samples_abstains_for_both(league_conn, at_evening):
    _series(league_conn, '000001', _sessions(21))
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    assert summary == {'submitted': 0, 'abstained': 2, 'duplicate': 0}
    assert {row['reason'] for row in league_conn.execute('SELECT reason FROM abstentions')} == {'base_rate_insufficient'}


def test_late_run_records_abstentions_instead_of_forecasts(league_conn, monkeypatch):
    _series(league_conn, '000001', _sessions(60), spike_every=3)
    _series(league_conn, '000002', _sessions(60), step=0.1, spike_every=3)
    monkeypatch.setattr(ledger, '_now', lambda: datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc))  # 09:00 KST
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    assert summary == {'submitted': 0, 'abstained': 2, 'duplicate': 0}
    assert {row['reason'] for row in league_conn.execute('SELECT reason FROM abstentions')} == {'late_submission'}


def test_missing_universe_bars_for_the_asof_date_raises(league_conn, at_evening):
    _series(league_conn, '000001', _sessions(60, end='2026-11-11'))
    with pytest.raises(baselines.UniverseBarsMissing):
        baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)


def test_jongga_candidates_reads_the_daily_result_file(tmp_path):
    path = tmp_path / 'jongga_v2_results_20261112.json'
    path.write_text(json.dumps({'signals': [{'stock_code': '005930'}, {'stock_code': '000660'},
                                            {'stock_code': '005930'}, {'stock_code': 'ABC'}, {}]}), encoding='utf-8')
    assert candidates.jongga_candidates('2026-11-12', data_dir=str(tmp_path)) == ['000660', '005930']
    assert candidates.jongga_candidates('2026-11-13', data_dir=str(tmp_path)) == []
    path.write_text('not json', encoding='utf-8')
    assert candidates.jongga_candidates('2026-11-12', data_dir=str(tmp_path)) == []
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_baselines.py -q`
Expected: FAIL — `ImportError: cannot import name 'baselines'`

- [ ] **Step 3: 구현**

`app/services/forecast_league/candidates.py`:

```python
"""1단계 후보 종목 — 그날 종가베팅 V2 가 신호를 낸 종목. 결과 파일은 읽기만 한다.

2단계에서 다른 예측자가 예측한 종목의 합집합으로 넓힌다.
"""
from __future__ import annotations

import json
import os
import re

from app.utils.paths import DATA_DIR

_STOCK_CODE = re.compile(r'[0-9]{6}')


def jongga_candidates(asof_date: str, data_dir: str | None = None) -> list[str]:
    path = os.path.join(data_dir or DATA_DIR, f"jongga_v2_results_{asof_date.replace('-', '')}.json")
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    signals = payload.get('signals') if isinstance(payload, dict) else None
    codes = {str(item.get('stock_code') or '') for item in (signals or []) if isinstance(item, dict)}
    return sorted(code for code in codes if _STOCK_CODE.fullmatch(code))
```

`app/services/forecast_league/baselines.py`:

```python
"""기준선 예측자 (설계서 §5.6). 우위는 이 둘을 이기는 것으로 정의한다.

입력은 provider_daily 봉이다. 정규장 보증이 없는 추정치이며 채점에는 쓰이지 않는다.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from app.services.forecast_league import bars, capsules, clock, derive, events, ledger

BASE_RATE_ID = 'baseline_base_rate'
MOMENTUM_ID = 'baseline_momentum'
VERSION = '1'
EVENT_ID = 'E1'
LOOKBACK_SESSIONS = 250
MOMENTUM_SESSIONS = 20
MIN_BASE_SAMPLES = 30
MOMENTUM_BIN_EDGES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


class UniverseBarsMissing(RuntimeError):
    """기준일의 유니버스 봉이 아직 없다. 수집 뒤에 다시 실행한다."""


def _recent_sessions(conn: sqlite3.Connection, asof_date: str, count: int) -> list[str]:
    rows = conn.execute('SELECT DISTINCT session_date FROM bars WHERE basis = ? AND session_date <= ? '
                        'ORDER BY session_date DESC LIMIT ?', (bars.BASIS_UNIVERSE, asof_date, count)).fetchall()
    return [row[0] for row in reversed(rows)]


def _series(conn: sqlite3.Connection, start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(
            'SELECT stock_code, session_date AS date, open, high, low, close FROM bars '
            'WHERE basis = ? AND session_date >= ? AND session_date <= ? ORDER BY stock_code, session_date',
            (bars.BASIS_UNIVERSE, start, end)):
        grouped[row['stock_code']].append(dict(row))
    return grouped


def universe_base_rate(conn: sqlite3.Connection, asof_date: str, *,
                       lookback: int = LOOKBACK_SESSIONS) -> dict[str, Any]:
    """직전 lookback 거래일의 전 종목 E1 적중률. 기준일까지의 봉으로 판정이 끝난 경로만 센다."""
    sessions = _recent_sessions(conn, asof_date, lookback + events.E1_MAX_SESSIONS + 1)
    if not sessions:
        return {'rate': None, 'n': 0, 'hits': 0}
    n = hits = 0
    for series in _series(conn, sessions[0], asof_date).values():
        for signal in range(len(series) - 1):
            result = events.evaluate_e1(series[signal + 1:signal + 1 + events.E1_MAX_SESSIONS], cost_pct=0.0)
            if result is not None:
                n += 1
                hits += result['outcome']
    return {'rate': hits / n if n else None, 'n': n, 'hits': hits}


def momentum_ranks(conn: sqlite3.Connection, asof_date: str, *,
                   sessions: int = MOMENTUM_SESSIONS) -> dict[str, float]:
    """20거래일 수익률의 유니버스 내 순위. 0 이 가장 낮고 1 이 가장 높다."""
    window = _recent_sessions(conn, asof_date, sessions + 1)
    if len(window) < sessions + 1 or window[-1] != asof_date:
        return {}
    returns = {}
    for code, series in _series(conn, window[0], asof_date).items():
        if len(series) == sessions + 1 and series[-1]['date'] == asof_date:
            returns[code] = series[-1]['close'] / series[0]['close'] - 1
    ordered = sorted(returns, key=lambda code: (returns[code], code))
    if len(ordered) < 2:
        return {}
    return {code: index / (len(ordered) - 1) for index, code in enumerate(ordered)}


def submit_baselines(conn: sqlite3.Connection, *, asof_date: str, stock_codes: Iterable[str],
                     trading_day: clock.TradingDay | None = None) -> dict[str, int]:
    if conn.execute('SELECT 1 FROM bars WHERE basis = ? AND session_date = ? LIMIT 1',
                    (bars.BASIS_UNIVERSE, asof_date)).fetchone() is None:
        raise UniverseBarsMissing(asof_date)
    ledger.register_forecaster(conn, BASE_RATE_ID, VERSION, 'baseline', 'native')
    ledger.register_forecaster(conn, MOMENTUM_ID, VERSION, 'baseline', 'derived')
    asof_ts = clock.close_ts(asof_date)
    base = universe_base_rate(conn, asof_date)
    ranks = momentum_ranks(conn, asof_date)
    summary = {'submitted': 0, 'abstained': 0, 'duplicate': 0}

    def abstain(forecaster_id: str, code: str, reason: str) -> None:
        ledger.record_abstention(conn, forecaster_id=forecaster_id, version=VERSION, stock_code=code,
                                 asof_ts=asof_ts, event_id=EVENT_ID, reason=reason)
        summary['abstained'] += 1

    def submit(forecaster_id: str, code: str, probability: float, raw_score: float | None,
               capsule: dict[str, Any]) -> None:
        try:
            ledger.submit_forecast(conn, forecaster_id=forecaster_id, version=VERSION, stock_code=code,
                                   asof_ts=asof_ts, event_id=EVENT_ID, probability=probability,
                                   raw_score=raw_score, capsule_hash=capsules.put_capsule(conn, capsule),
                                   source_ref=f'baseline:{asof_date}', trading_day=trading_day)
            summary['submitted'] += 1
        except ledger.SubmissionRejected as rejected:
            if rejected.code == 'duplicate':
                summary['duplicate'] += 1
            elif rejected.code == 'late_submission':
                abstain(forecaster_id, code, 'late_submission')
            else:
                raise

    for code in sorted(set(stock_codes)):
        if base['n'] < MIN_BASE_SAMPLES:
            abstain(BASE_RATE_ID, code, 'base_rate_insufficient')
            abstain(MOMENTUM_ID, code, 'base_rate_insufficient')
            continue
        inputs = {'asof_date': asof_date, 'price_basis': bars.BASIS_UNIVERSE,
                  'lookback_sessions': LOOKBACK_SESSIONS, 'base_rate': base}
        submit(BASE_RATE_ID, code, ledger.clamp_probability(base['rate']), None,
               {'forecaster': BASE_RATE_ID, **inputs})
        rank = ranks.get(code)
        if rank is None:
            abstain(MOMENTUM_ID, code, 'momentum_history_short')
            continue
        probability, basis = derive.derived_probability(
            conn, forecaster_id=MOMENTUM_ID, version=VERSION, event_id=EVENT_ID, raw_score=rank,
            asof_ts=asof_ts, bin_edges=MOMENTUM_BIN_EDGES, fallback=base['rate'])
        submit(MOMENTUM_ID, code, probability, rank,
               {'forecaster': MOMENTUM_ID, **inputs, 'momentum_sessions': MOMENTUM_SESSIONS,
                'rank': rank, 'universe_size': len(ranks), 'derived_from': basis})
    return summary
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_baselines.py -q`
Expected: `10 passed`

`test_universe_base_rate_counts_decided_paths_only`의 기대값이 맞지 않으면 구현이 아니라 계산을 먼저 확인한다. 30거래일에서 신호일은 0~28번째(29개)다. `000001`은 진입일 고가가 시가의 +10%라 29개 모두 적중이다. `000002`는 신호일 뒤에 8거래일이 남아야 만기 판정이 나므로 0~21번째(22개)만 표본이 된다.

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/candidates.py app/services/forecast_league/baselines.py tests/test_league_baselines.py && git commit -m "feat(league): add base-rate and momentum baseline forecasters

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 11: 봉 수집

**Files:**
- Create: `app/services/forecast_league/price_sources.py`
- Test: `tests/test_league_price_sources.py`

- 정규장 봉: 미해소 예측의 종목·거래일 가운데 아직 없는 것만 `KISRegularProvider.fetch_session(symbol, session)`으로 받는다. 반환값의 `bar`를 저장하고, 원문 페이지의 해시와 수집 계약 버전을 캡슐로 남긴다. 원문 전체는 저장하지 않는다(KIS가 약 1년간 보관하므로 다시 받을 수 있다).
- 당일 봉은 20:40 KST 이후에만 대상에 넣는다(공급자의 수집 가능 시각은 20:30).
- 유니버스 봉: 종목별 일봉을 받아 `provider_daily`로 저장한다. 오늘 날짜의 행은 저장하지 않는다. 최근 45일은 매번 다시 받아 덮어쓴다(수정주가 반영). 처음에는 420일을 받는다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services.forecast_league import bars, capsules, ledger, price_sources

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731


class FakeProvider:
    def __init__(self, failing=()):
        self.calls, self.failing = [], set(failing)

    def fetch_session(self, symbol, session):
        self.calls.append((symbol, session))
        if (symbol, session) in self.failing:
            error = ValueError('regular_boundaries')
            error.code = 'regular_boundaries'
            raise error
        return {'symbol': symbol, 'session': session, 'captured_at': '2026-11-13T11:45:00Z',
                'bar': {'open': 100.0, 'high': 110.0, 'low': 95.0, 'close': 105.0, 'volume': 10, 'traded_value': 1},
                'pages': [{'params': {}, 'response': {'output2': [1, 2, 3]}}],
                'source': {'version': 'kis-regular-j-minute-v1'}}


@pytest.fixture
def forecast(league_conn, monkeypatch):
    monkeypatch.setattr(ledger, '_now', lambda: datetime(2026, 11, 12, 11, 0, tzinfo=timezone.utc))
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    capsule = capsules.put_capsule(league_conn, {'k': 1})
    for code in ('005930', '000660'):
        ledger.submit_forecast(league_conn, forecaster_id='fx', version='1', stock_code=code,
                               asof_ts='2026-11-12T15:30:00+09:00', event_id='E1', probability=0.4,
                               capsule_hash=capsule, trading_day=WEEKDAYS)


def _targets(conn, now_kst):
    now = datetime.fromisoformat(now_kst).astimezone(timezone.utc)
    return price_sources.needed_regular_targets(conn, now=now, trading_day=WEEKDAYS)


def test_targets_cover_missing_sessions_of_unresolved_forecasts(league_conn, forecast):
    assert _targets(league_conn, '2026-11-12T21:00:00+09:00') == []            # 진입일 전
    assert _targets(league_conn, '2026-11-13T20:39:00+09:00') == []            # 당일은 20:40 이후
    assert _targets(league_conn, '2026-11-13T20:40:00+09:00') == [('000660', '2026-11-13'), ('005930', '2026-11-13')]
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-13', basis=bars.BASIS_REGULAR,
                 open=1, high=1, low=1, close=1, captured_at='t')
    assert _targets(league_conn, '2026-11-17T08:00:00+09:00') == [
        ('000660', '2026-11-13'), ('000660', '2026-11-16'), ('005930', '2026-11-16')]


def test_targets_stop_at_eight_sessions_and_skip_resolved(league_conn, forecast):
    assert len(_targets(league_conn, '2026-12-31T21:00:00+09:00')) == 16
    league_conn.execute("INSERT INTO resolutions (forecast_id, status, resolved_at, price_source_version) "
                        "SELECT forecast_id, 'void', 't', 'v' FROM forecasts WHERE stock_code = '005930'")
    assert {code for code, _ in _targets(league_conn, '2026-12-31T21:00:00+09:00')} == {'000660'}


def test_collect_stores_bars_with_compact_evidence(league_conn):
    provider = FakeProvider(failing={('000660', '2026-11-13')})
    summary = price_sources.collect_regular_bars(
        league_conn, provider=provider, targets=[('005930', '2026-11-13'), ('000660', '2026-11-13')])
    assert summary == {'stored': 1, 'failed': [['000660', '2026-11-13', 'regular_boundaries']]}
    row = league_conn.execute('SELECT * FROM bars').fetchone()
    assert (row['stock_code'], row['basis'], row['open'], row['high'], row['low'], row['close']) == (
        '005930', bars.BASIS_REGULAR, 100.0, 110.0, 95.0, 105.0)
    evidence = capsules.get_capsule(league_conn, row['evidence_hash'])
    assert evidence['source_version'] == 'kis-regular-j-minute-v1'
    assert len(evidence['pages_sha256']) == 64 and 'pages' not in evidence


def test_universe_sync_never_stores_todays_bar(league_conn, monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    requested = []

    def reader(code, start, end):
        requested.append((code, start, end))
        index = pd.to_datetime(['2026-11-11', '2026-11-12', '2026-11-13'])
        return pd.DataFrame({'Open': [100, 0, 100], 'High': [110, 110, 110], 'Low': [95, 95, 95],
                             'Close': [105, 105, 105]}, index=index)

    summary = price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', 'ABCDEF'],
                                               reader=reader)
    assert requested == [('005930', '2025-09-19', '2026-11-12')]              # 처음: 420일, 어제까지
    assert summary == {'codes': 1, 'stored': 1, 'failed': 0}                   # 11-12 는 시가 0, 11-13 은 오늘
    assert [row['session_date'] for row in league_conn.execute('SELECT session_date FROM bars')] == ['2026-11-11']


def test_universe_sync_refreshes_a_recent_window_and_survives_reader_errors(league_conn, monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-11', basis=bars.BASIS_UNIVERSE,
                 open=100, high=110, low=95, close=105, captured_at='t')
    requested = []

    def reader(code, start, end):
        requested.append(start)
        if code == '000660':
            raise RuntimeError('network')
        return pd.DataFrame({'Open': [50], 'High': [55], 'Low': [45], 'Close': [52]},
                            index=pd.to_datetime(['2026-11-11']))

    summary = price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', '000660'],
                                               reader=reader)
    assert set(requested) == {'2026-09-29'}                                     # 45일 창
    assert summary == {'codes': 2, 'stored': 1, 'failed': 1}
    assert league_conn.execute('SELECT close FROM bars').fetchone()[0] == 52.0  # 덮어씀
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_price_sources.py -q`
Expected: FAIL — `ImportError: cannot import name 'price_sources'`

- [ ] **Step 3: 구현**

```python
"""리그 가격 봉 수집.

정규장 봉은 기존 KISRegularProvider(분봉 09:00~15:30 재구성)로 받는다.
유니버스 봉은 공급자 일봉이며 당일 봉은 저장하지 않는다 — 장 마감 후에도 값이 바뀌는 것을 확인했다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Iterable

from app.services.forecast_league import bars, capsules, clock, events, resolver

REGULAR_READY = time(20, 40)          # 공급자의 수집 가능 시각(20:30)에 여유 10분
INITIAL_DAYS = 420
REFRESH_DAYS = 45
_STOCK_CODE = re.compile(r'[0-9]{6}')


def _now() -> datetime:
    return clock.now_utc()


def needed_regular_targets(conn: sqlite3.Connection, *, now: datetime,
                           trading_day: clock.TradingDay | None = None) -> list[tuple[str, str]]:
    """미해소 예측의 판정에 필요한데 아직 없는 (종목, 거래일)."""
    local = now.astimezone(clock.KST)
    last = local.date() if local.time() >= REGULAR_READY else local.date() - timedelta(days=1)
    targets: set[tuple[str, str]] = set()
    for row in resolver.unresolved(conn):
        first = resolver.entry_date(row['asof_ts'], trading_day)
        if first > last.isoformat():
            continue
        for day in clock.trading_days(first, last.isoformat(), trading_day)[:events.E1_MAX_SESSIONS]:
            targets.add((row['stock_code'], day))
    existing = {(row[0], row[1]) for row in conn.execute(
        'SELECT stock_code, session_date FROM bars WHERE basis = ?', (bars.BASIS_REGULAR,))}
    return sorted(targets - existing)


def collect_regular_bars(conn: sqlite3.Connection, *, provider: Any,
                         targets: Iterable[tuple[str, str]]) -> dict[str, Any]:
    stored, failed = 0, []
    for code, session in targets:
        try:
            result = provider.fetch_session(code, session)
            bar = result['bar']
            pages = json.dumps(result.get('pages'), sort_keys=True, ensure_ascii=False).encode('utf-8')
            evidence = capsules.put_capsule(conn, {
                'stock_code': code, 'session': session, 'bar': bar, 'captured_at': result['captured_at'],
                'source_version': (result.get('source') or {}).get('version'),
                'pages_sha256': hashlib.sha256(pages).hexdigest()})
            if bars.put_bar(conn, stock_code=code, session_date=session, basis=bars.BASIS_REGULAR,
                            open=bar['open'], high=bar['high'], low=bar['low'], close=bar['close'],
                            captured_at=result['captured_at'], evidence_hash=evidence):
                stored += 1
            conn.commit()
        except Exception as error:   # 한 종목의 실패가 나머지를 막지 않는다
            conn.rollback()
            failed.append([code, session, str(getattr(error, 'code', type(error).__name__))])
    return {'stored': stored, 'failed': failed}


def _listed_codes() -> list[str]:
    import FinanceDataReader as fdr
    return [str(code) for code in fdr.StockListing('KRX')['Code']]


def _read_daily(code: str, start: str, end: str):
    import FinanceDataReader as fdr
    return fdr.DataReader(code, start, end)


def sync_universe_bars(conn: sqlite3.Connection, *, today: str, codes: Iterable[str] | None = None,
                       reader: Callable[[str, str, str], Any] | None = None) -> dict[str, int]:
    """어제까지의 공급자 일봉을 받아 저장한다. 최근 창은 덮어쓴다."""
    read = reader or _read_daily
    selected = [code for code in (codes if codes is not None else _listed_codes())
                if _STOCK_CODE.fullmatch(str(code))]
    has_any = conn.execute('SELECT 1 FROM bars WHERE basis = ? LIMIT 1', (bars.BASIS_UNIVERSE,)).fetchone()
    day = date.fromisoformat(today)
    start = (day - timedelta(days=REFRESH_DAYS if has_any else INITIAL_DAYS)).isoformat()
    end = (day - timedelta(days=1)).isoformat()
    captured = clock.iso(_now())
    stored = failed = 0
    for index, code in enumerate(selected, start=1):
        try:
            frame = read(code, start, end)
            for stamp, row in (frame.iterrows() if frame is not None else ()):
                session = stamp.strftime('%Y-%m-%d')
                if session >= today:
                    continue
                if bars.put_bar(conn, stock_code=code, session_date=session, basis=bars.BASIS_UNIVERSE,
                                open=row['Open'], high=row['High'], low=row['Low'], close=row['Close'],
                                captured_at=captured, replace=True):
                    stored += 1
        except Exception:
            failed += 1
        if index % 200 == 0:
            conn.commit()
    conn.commit()
    return {'codes': len(selected), 'stored': stored, 'failed': failed}
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_price_sources.py -q`
Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/forecast_league/price_sources.py tests/test_league_price_sources.py && git commit -m "feat(league): collect regular-session and universe bars

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 12: 잡 큐와 워커

**Files:**
- Create: `app/services/league_worker/__init__.py`, `jobs.py`, `handlers.py`, `schedule.py`, `__main__.py`
- Test: `tests/test_league_worker.py`

워커는 큐에 있는 잡을 순서대로 실행하고 종료한다. 실패한 잡은 5분 뒤 다시 대기 상태가 되고, 세 번 실패하면 `failed`로 남기고 개인봇으로 알린다(설계서 §11: 시스템 메시지는 개인봇만).

| 시간대 | 넣는 잡 |
|---|---|
| `morning` (평일 07:30) | `sync_universe(today)` → `submit_baselines(asof_date=직전 거래일)` |
| `evening` (평일 20:45) | `collect_regular(today)` → `resolve(today)` → `score(today)` |

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.forecast_league import baselines, db
from app.services.league_worker import __main__ as worker, handlers, jobs, schedule

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
T0 = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock_at(monkeypatch):
    state = {'now': T0}
    monkeypatch.setattr(jobs, '_now', lambda: state['now'])
    return state


def _statuses(conn):
    return [(row['kind'], row['status'], row['attempts']) for row in conn.execute('SELECT * FROM jobs ORDER BY job_id')]


def test_enqueue_is_deduplicated(league_conn, clock_at):
    assert jobs.enqueue(league_conn, 'score', {'today': '2026-11-13'}, 'score:2026-11-13') is True
    assert jobs.enqueue(league_conn, 'score', {'today': '2026-11-13'}, 'score:2026-11-13') is False
    assert _statuses(league_conn) == [('score', 'queued', 0)]


def test_jobs_are_claimed_in_order_and_completed(league_conn, clock_at):
    jobs.enqueue(league_conn, 'a', {}, 'a')
    jobs.enqueue(league_conn, 'b', {}, 'b')
    first = jobs.claim_next(league_conn)
    assert (first['kind'], first['attempts']) == ('a', 1)
    jobs.complete(league_conn, first['job_id'], {'ok': 1})
    assert jobs.claim_next(league_conn)['kind'] == 'b'
    assert jobs.claim_next(league_conn) is None
    assert json.loads(league_conn.execute("SELECT result FROM jobs WHERE kind = 'a'").fetchone()[0]) == {'ok': 1}


def test_failed_job_waits_then_fails_for_good_on_the_third_attempt(league_conn, clock_at):
    jobs.enqueue(league_conn, 'a', {}, 'a')
    job = jobs.claim_next(league_conn)
    assert jobs.fail(league_conn, job['job_id'], 'boom') is False
    assert jobs.claim_next(league_conn) is None                       # 5분 대기
    clock_at['now'] = T0 + timedelta(minutes=5)
    assert jobs.fail(league_conn, jobs.claim_next(league_conn)['job_id'], 'boom') is False
    clock_at['now'] = T0 + timedelta(minutes=10)
    assert jobs.fail(league_conn, jobs.claim_next(league_conn)['job_id'], 'boom') is True
    row = league_conn.execute('SELECT status, attempts, last_error FROM jobs').fetchone()
    assert tuple(row) == ('failed', 3, 'boom')


def test_running_jobs_are_requeued_on_restart(league_conn, clock_at):
    jobs.enqueue(league_conn, 'a', {}, 'a')
    jobs.claim_next(league_conn)
    assert jobs.recover_running(league_conn) == 1
    assert _statuses(league_conn) == [('a', 'queued', 1)]


def test_schedule_enqueues_each_slot_once(league_conn, clock_at):
    assert schedule.enqueue_slot(league_conn, 'morning', date(2026, 11, 16), trading_day=WEEKDAYS) == 2
    assert schedule.enqueue_slot(league_conn, 'morning', date(2026, 11, 16), trading_day=WEEKDAYS) == 0
    assert schedule.enqueue_slot(league_conn, 'evening', date(2026, 11, 16), trading_day=WEEKDAYS) == 3
    rows = [(row['kind'], json.loads(row['args'])) for row in league_conn.execute('SELECT * FROM jobs ORDER BY job_id')]
    assert rows == [('sync_universe', {'today': '2026-11-16'}),
                    ('submit_baselines', {'asof_date': '2026-11-13'}),       # 월요일 아침 → 금요일 기준
                    ('collect_regular', {'today': '2026-11-16'}),
                    ('resolve', {'today': '2026-11-16'}), ('score', {'today': '2026-11-16'})]
    with pytest.raises(ValueError):
        schedule.enqueue_slot(league_conn, 'noon', date(2026, 11, 16))


def test_drain_runs_jobs_and_records_failures(tmp_path, monkeypatch, clock_at):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    alerts = []
    monkeypatch.setattr(worker, '_alert', alerts.append)

    def explode(conn, args):
        raise baselines.UniverseBarsMissing('2026-11-12')

    monkeypatch.setattr(handlers, 'HANDLERS', {'ok': lambda conn, args: {'echo': args['x']}, 'bad': explode})
    with db.connect() as conn:
        jobs.enqueue(conn, 'ok', {'x': 1}, 'ok')
        jobs.enqueue(conn, 'bad', {}, 'bad')
        jobs.enqueue(conn, 'unknown', {}, 'unknown')
    assert worker.drain() == 3
    with db.connect() as conn:
        assert _statuses(conn) == [('ok', 'done', 1), ('bad', 'queued', 1), ('unknown', 'queued', 1)]
    assert alerts == []
    for minutes in (5, 10):
        clock_at['now'] = T0 + timedelta(minutes=minutes)
        worker.drain()
    with db.connect() as conn:
        assert _statuses(conn) == [('ok', 'done', 1), ('bad', 'failed', 3), ('unknown', 'failed', 3)]
    assert len(alerts) == 2 and 'bad' in alerts[0] and 'UniverseBarsMissing' in alerts[0]


def test_handlers_cover_every_scheduled_kind():
    assert set(handlers.HANDLERS) == {'sync_universe', 'submit_baselines', 'collect_regular', 'resolve', 'score'}


def test_cli_dispatches_drain_and_enqueue(tmp_path, monkeypatch, clock_at, capsys):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    monkeypatch.setattr(handlers, 'HANDLERS', {})
    assert worker.main(['enqueue', 'evening']) == 0
    assert worker.main(['status']) == 0
    assert '"queued": 3' in capsys.readouterr().out
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_worker.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.league_worker'`

- [ ] **Step 3: 구현**

`app/services/league_worker/__init__.py`:

```python
"""예측 리그 워커 — league.db 의 잡 큐를 비우고 종료한다.

실행: python -m app.services.league_worker drain   (miniPC 작업 스케줄러가 5분마다 실행)
"""
```

`app/services/league_worker/jobs.py`:

```python
"""영속 잡 큐. 같은 dedupe_key 는 한 번만 들어간다."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any

from app.services.forecast_league import clock

MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)


def _now():
    return clock.now_utc()


def enqueue(conn: sqlite3.Connection, kind: str, args: dict[str, Any], dedupe_key: str) -> bool:
    stamp = clock.iso(_now())
    cursor = conn.execute(
        'INSERT OR IGNORE INTO jobs (kind, args, dedupe_key, status, attempts, not_before, created_at, updated_at) '
        "VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)",
        (kind, json.dumps(args, sort_keys=True), dedupe_key, stamp, stamp, stamp))
    return cursor.rowcount == 1


def recover_running(conn: sqlite3.Connection) -> int:
    """중단된 실행이 남긴 running 잡을 대기 상태로 되돌린다."""
    cursor = conn.execute("UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
                          (clock.iso(_now()),))
    return cursor.rowcount


def claim_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    stamp = clock.iso(_now())
    row = conn.execute("SELECT * FROM jobs WHERE status = 'queued' AND not_before <= ? ORDER BY job_id LIMIT 1",
                       (stamp,)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE job_id = ?",
                 (stamp, row['job_id']))
    return {**dict(row), 'status': 'running', 'attempts': row['attempts'] + 1}


def complete(conn: sqlite3.Connection, job_id: int, result: Any) -> None:
    conn.execute("UPDATE jobs SET status = 'done', result = ?, last_error = NULL, updated_at = ? WHERE job_id = ?",
                 (json.dumps(result, sort_keys=True, default=str), clock.iso(_now()), job_id))


def fail(conn: sqlite3.Connection, job_id: int, error: str) -> bool:
    """실패를 기록한다. 더 재시도하지 않으면 True."""
    attempts = conn.execute('SELECT attempts FROM jobs WHERE job_id = ?', (job_id,)).fetchone()['attempts']
    final = attempts >= MAX_ATTEMPTS
    now = _now()
    conn.execute('UPDATE jobs SET status = ?, last_error = ?, not_before = ?, updated_at = ? WHERE job_id = ?',
                 ('failed' if final else 'queued', error[:500], clock.iso(now + RETRY_DELAY), clock.iso(now), job_id))
    return final


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {row['status']: row['n'] for row in conn.execute('SELECT status, COUNT(*) AS n FROM jobs GROUP BY status')}
```

`app/services/league_worker/handlers.py`:

```python
"""잡 종류별 실행. 로직은 forecast_league 에 있고 여기서는 연결만 한다."""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from app.services.forecast_league import baselines, candidates, clock, price_sources, resolver, scorecards


def _sync_universe(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    return price_sources.sync_universe_bars(conn, today=args['today'])


def _submit_baselines(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    codes = candidates.jongga_candidates(args['asof_date'])
    return {'candidates': len(codes),
            **baselines.submit_baselines(conn, asof_date=args['asof_date'], stock_codes=codes)}


def _collect_regular(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.mirofish.alpha_lab.regular_source import KISRegularProvider
    targets = price_sources.needed_regular_targets(conn, now=clock.now_utc())
    return price_sources.collect_regular_bars(conn, provider=KISRegularProvider(), targets=targets)


def _resolve(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    return resolver.resolve_pending(conn, today=args['today'])


def _score(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    cards = scorecards.compute_scorecards(conn)
    return {'scorecards': len(cards), 'scored': sum(1 for card in cards if card['status'] == 'scored')}


HANDLERS: dict[str, Callable[[sqlite3.Connection, dict[str, Any]], Any]] = {
    'sync_universe': _sync_universe,
    'submit_baselines': _submit_baselines,
    'collect_regular': _collect_regular,
    'resolve': _resolve,
    'score': _score,
}
```

`app/services/league_worker/schedule.py`:

```python
"""시간대별로 넣을 잡. scheduler.py 는 이 함수만 부른다."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.services.forecast_league import clock
from app.services.league_worker import jobs


def enqueue_slot(conn: sqlite3.Connection, slot: str, today: date,
                 trading_day: clock.TradingDay | None = None) -> int:
    day = today.isoformat()
    if slot == 'morning':
        asof = clock.previous_trading_day(today, trading_day).isoformat()
        planned = [('sync_universe', {'today': day}, f'sync_universe:{day}'),
                   ('submit_baselines', {'asof_date': asof}, f'submit_baselines:{asof}')]
    elif slot == 'evening':
        planned = [(kind, {'today': day}, f'{kind}:{day}') for kind in ('collect_regular', 'resolve', 'score')]
    else:
        raise ValueError(f'unknown slot: {slot}')
    return sum(1 for kind, args, key in planned if jobs.enqueue(conn, kind, args, key))
```

`app/services/league_worker/__main__.py`:

```python
"""예측 리그 워커 CLI.

  drain              대기 중인 잡을 순서대로 실행하고 종료
  enqueue <slot>     morning / evening 잡을 큐에 넣기 (수동 실행용)
  status             잡 상태별 개수
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

from app.services.forecast_league import clock, db
from app.services.league_worker import handlers, jobs, schedule

logger = logging.getLogger('league_worker')
MAX_JOBS_PER_RUN = 50


def _alert(message: str) -> None:
    """시스템 메시지 — 개인봇으로만 보낸다."""
    try:
        from app.utils.scheduler import _send_telegram
        _send_telegram(message, channel=False)
    except Exception:
        logger.exception('alert failed')


def drain() -> int:
    """실행한 잡 수를 반환한다."""
    ran = 0
    with db.connect() as conn:
        jobs.recover_running(conn)
        conn.commit()
        while ran < MAX_JOBS_PER_RUN:
            job = jobs.claim_next(conn)
            conn.commit()
            if job is None:
                break
            ran += 1
            try:
                result = handlers.HANDLERS[job['kind']](conn, json.loads(job['args']))
                conn.commit()
                jobs.complete(conn, job['job_id'], result)
                logger.info('job %s %s done: %s', job['job_id'], job['kind'], result)
            except Exception as error:
                conn.rollback()
                reason = f'{type(error).__name__}: {error}'
                logger.exception('job %s %s failed', job['job_id'], job['kind'])
                if jobs.fail(conn, job['job_id'], reason):
                    _alert(f"[예측 리그] 잡 실패(재시도 종료): {job['kind']} #{job['job_id']} — {reason[:200]}")
            conn.commit()
    return ran


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m app.services.league_worker')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('drain')
    commands.add_parser('status')
    commands.add_parser('enqueue').add_argument('slot', choices=['morning', 'evening'])
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    if options.command == 'drain':
        print(json.dumps({'ran': drain()}))
    elif options.command == 'enqueue':
        with db.connect() as conn:
            added = schedule.enqueue_slot(conn, options.slot, datetime.now(clock.KST).date())
        print(json.dumps({'enqueued': added}))
    else:
        with db.connect() as conn:
            print(json.dumps(jobs.counts(conn), sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_worker.py -q`
Expected: `8 passed`

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add app/services/league_worker tests/test_league_worker.py && git commit -m "feat(league): add persistent job queue and drain worker

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 13: 스케줄러 연결, 작업 등록 스크립트, 점검 도구, 문서

**Files:**
- Modify: `scheduler.py` (함수 3개, 등록 2줄), `CLAUDE.md` (§18 추가)
- Create: `deploy/register_league_worker_task.ps1`, `scripts/audit_league_price_sources.py`
- Test: `tests/test_league_scheduler_hook.py`, `tests/test_league_price_audit.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_league_scheduler_hook.py`:

```python
import re
from pathlib import Path

import scheduler
from app.services.forecast_league import db

ROOT = Path(__file__).resolve().parent.parent


def test_scheduler_only_enqueues_league_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    assert scheduler.run_league_morning() is True
    assert scheduler.run_league_evening() is True
    with db.connect() as conn:
        kinds = [row['kind'] for row in conn.execute('SELECT kind FROM jobs ORDER BY job_id')]
        statuses = {row['status'] for row in conn.execute('SELECT status FROM jobs')}
    assert kinds == ['sync_universe', 'submit_baselines', 'collect_regular', 'resolve', 'score']
    assert statuses == {'queued'}                      # 스케줄러는 실행하지 않는다


def test_scheduler_registers_both_slots_on_weekdays():
    source = (ROOT / 'scheduler.py').read_text(encoding='utf-8')
    assert re.search(r"\.at\('07:30'\)\.do\(\s*self\._with_record\(run_league_morning, 'league_morning'", source)
    assert re.search(r"\.at\('20:45'\)\.do\(\s*self\._with_record\(run_league_evening, 'league_evening'", source)


def test_register_script_targets_the_drain_command():
    script = (ROOT / 'deploy' / 'register_league_worker_task.ps1').read_text(encoding='utf-8')
    assert '-X utf8 -m app.services.league_worker drain' in script
    assert "MINIPC-NQYLP" in script and "'SYSTEM'" in script
    assert 'Unregister-ScheduledTask' not in script
```

`tests/test_league_price_audit.py`:

```python
import csv
import importlib.util
from pathlib import Path

from app.services.forecast_league import bars

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'audit_league_price_sources.py'
spec = importlib.util.spec_from_file_location('audit_league_price_sources', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_preclose_share_counts_rows_captured_before_the_close(tmp_path):
    path = tmp_path / 'daily_prices.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['ticker', 'date', 'name', 'current_price', 'change', 'change_rate', 'high', 'low',
                         'open', 'volume', 'update_time'])
        writer.writerow(['005930', '2026-07-30', 'x', 1, 0, 0, 1, 1, 1, 1, '2026-07-30 14:52:15'])
        writer.writerow(['005930', '2026-07-31', 'x', 1, 0, 0, 1, 1, 1, 1, '2026-07-31 16:10:00'])
        writer.writerow(['005930', '2026-06-30', 'x', 1, 0, 0, 1, 1, 1, 1, '2026-07-02 20:00:00'])
    assert audit.preclose_share(str(path)) == {
        '2026-06': {'rows': 1, 'pre_close': 0}, '2026-07': {'rows': 2, 'pre_close': 1}}


def test_compare_bases_counts_field_mismatches(league_conn):
    def put(code, basis, **over):
        values = dict(open=100.0, high=110.0, low=95.0, close=105.0)
        values.update(over)
        bars.put_bar(league_conn, stock_code=code, session_date='2026-11-12', basis=basis, captured_at='t', **values)

    put('005930', bars.BASIS_REGULAR)
    put('005930', bars.BASIS_UNIVERSE, close=104.0, low=94.0)
    put('000660', bars.BASIS_REGULAR)
    put('000660', bars.BASIS_UNIVERSE)
    put('035420', bars.BASIS_REGULAR)                    # 한쪽에만 있음 → 비교하지 않음
    assert audit.compare_bases(league_conn, '2026-11-12') == {
        'session': '2026-11-12', 'compared': 2, 'mismatch': {'open': 0, 'high': 0, 'low': 1, 'close': 1}}
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_scheduler_hook.py tests/test_league_price_audit.py -q`
Expected: FAIL — `AttributeError: module 'scheduler' has no attribute 'run_league_morning'`, 스크립트 파일 없음

- [ ] **Step 3: 구현**

`scheduler.py` — `def update_daily_prices():` 정의 바로 위에 추가:

```python
def _enqueue_league_slot(slot: str) -> bool:
    """예측 리그 잡을 큐에 넣기만 한다. 실행은 league_worker 프로세스가 한다."""
    from app.services.forecast_league import clock as league_clock, db as league_db
    from app.services.league_worker import schedule as league_schedule
    with league_db.connect() as conn:
        added = league_schedule.enqueue_slot(conn, slot, datetime.now(league_clock.KST).date())
    logger.info(f"📒 예측 리그 {slot} 잡 {added}건 큐 등록")
    return True


def run_league_morning():
    return _enqueue_league_slot('morning')


def run_league_evening():
    return _enqueue_league_slot('evening')


```

`scheduler.py` — 등록부에서 아래 두 줄을 찾는다.

```python
        for day in weekdays:
            # 08:55 — KIS 토큰 웜업 (장 시작 5분 전 자격증명/네트워크 사전 검증)
```

그 사이에 다음을 넣는다(들여쓰기는 `# 08:55` 주석과 같다).

```python
            # 07:30 / 20:45 — 예측 리그 잡 큐 등록 (기준선 제출 / 정규장 봉 수집·해소·채점)
            getattr(schedule.every(), day).at('07:30').do(
                self._with_record(run_league_morning, 'league_morning',
                                  max_retries=1, retry_delay=300))
            getattr(schedule.every(), day).at('20:45').do(
                self._with_record(run_league_evening, 'league_evening',
                                  max_retries=1, retry_delay=300))
```

`deploy/register_league_worker_task.ps1`:

```powershell
# Install the Forecast League drain task. It empties the job queue in league.db and exits.
# Preview on any machine: powershell -NoProfile -File deploy/register_league_worker_task.ps1 -Plan
# Apply on the MiniPC in an elevated shell after the tests pass.
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$Plan)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$ExpectedRoot = 'C:\bitman_marketfloww'
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$Name = 'MarketFlow-LeagueWorker'
$Arguments = '-X utf8 -m app.services.league_worker drain'
$EveryMinutes = 5
$LimitMinutes = 30
$task = [pscustomobject]@{
    Name=$Name; EveryMinutes=$EveryMinutes; LimitMinutes=$LimitMinutes
    Execute=$Python; WorkingDirectory=$Project; Arguments=$Arguments
}
if ($Plan) { $task | ConvertTo-Json -Depth 3; return }
if ($env:COMPUTERNAME -ne 'MINIPC-NQYLP' -or $Project -ne $ExpectedRoot) {
    throw 'Registration is restricted to MINIPC-NQYLP at C:\bitman_marketfloww.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Project virtualenv Python is missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $Project 'app\services\league_worker\__main__.py') -PathType Leaf)) {
    throw 'League worker source is missing.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$role = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $role.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Registration needs an elevated administrator shell for the SYSTEM task principal.'
}
# Never replace a task that someone else owns.
$existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
if ($existing) {
    $actions = @($existing.Actions)
    if ($actions.Count -ne 1 -or $actions[0].Execute -ne $Python -or
        $actions[0].WorkingDirectory -ne $Project -or $actions[0].Arguments -ne $Arguments) {
        throw "Existing task $Name has a different owner or command; it was not replaced."
    }
}
if (-not $PSCmdlet.ShouldProcess($Name, 'Register Forecast League drain task')) { return }
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Project
$startup = New-ScheduledTaskTrigger -AtStartup
$startup.Delay = 'PT4M'
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(4) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMinutes)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($startup, $repeat) `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Registered ${Name}: every $EveryMinutes min, limit $LimitMinutes min."
```

`scripts/audit_league_price_sources.py`:

```python
# -*- coding: utf-8 -*-
"""예측 리그 가격 출처 점검 (읽기 전용).

  --csv              data/daily_prices.csv 에서 장 마감(15:40) 전에 수집된 당일 행의 월별 수
  --session DATE     league.db 에서 같은 종목·같은 날의 krx_regular 봉과 provider_daily 봉이 다른 수

두 번째 점검은 provider_daily 가 정규장 값과 얼마나 다른지 알려 준다. 채점은 krx_regular 만 쓴다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

PRE_CLOSE_BEFORE = '15:40'
FIELDS = ('open', 'high', 'low', 'close')


def preclose_share(csv_path: str) -> dict[str, dict[str, int]]:
    months: dict[str, dict[str, int]] = defaultdict(lambda: {'rows': 0, 'pre_close': 0})
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            day, stamp = (row.get('date') or '').strip(), (row.get('update_time') or '').strip()
            if len(day) != 10:
                continue
            bucket = months[day[:7]]
            bucket['rows'] += 1
            if stamp[:10] == day and stamp[11:16] < PRE_CLOSE_BEFORE:
                bucket['pre_close'] += 1
    return {month: dict(months[month]) for month in sorted(months)}


def compare_bases(conn, session: str) -> dict:
    from app.services.forecast_league import bars
    rows = conn.execute(
        'SELECT r.open AS ro, r.high AS rh, r.low AS rl, r.close AS rc, '
        'u.open AS uo, u.high AS uh, u.low AS ul, u.close AS uc FROM bars r '
        'JOIN bars u ON u.stock_code = r.stock_code AND u.session_date = r.session_date '
        'WHERE r.basis = ? AND u.basis = ? AND r.session_date = ?',
        (bars.BASIS_REGULAR, bars.BASIS_UNIVERSE, session)).fetchall()
    mismatch = {field: 0 for field in FIELDS}
    for row in rows:
        for field in FIELDS:
            if row['r' + field[0]] != row['u' + field[0]]:
                mismatch[field] += 1
    return {'session': session, 'compared': len(rows), 'mismatch': mismatch}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', action='store_true')
    parser.add_argument('--session')
    options = parser.parse_args(argv)
    report: dict = {}
    if options.csv:
        report['daily_prices_preclose'] = preclose_share(os.path.join(BASE_DIR, 'data', 'daily_prices.csv'))
    if options.session:
        from app.services.forecast_league import db
        with db.connect() as conn:
            report['bases'] = compare_bases(conn, options.session)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

`CLAUDE.md` 끝에 추가:

```markdown

---

## 18. 예측 리그 (Forecast League) 1단계 — 2026-11-12

- 설계: `docs/superpowers/specs/2026-11-12-forecast-league-design.md` · 계획: `docs/superpowers/plans/2026-11-12-forecast-league-phase1-ledger.md`
- `app/services/forecast_league/` = 예측을 시점 고정으로 기록하고 표준 사건 `E1`(다음 거래일 시가 진입, 8거래일 내 +8%, −7% 먼저면 실패)으로 채점하는 원장. 저장소는 `data/forecast_league/league.db` 하나(git 제외).
- 쓰기는 `ledger.submit_forecast()`뿐이다. 수정·삭제 함수와 HTTP 쓰기 경로는 없다. `forecasts`·`capsules`는 트리거로 수정·삭제가 막혀 있다.
- **채점 가격은 `daily_prices.csv`가 아니다.** 그 파일은 14:50대 장중 수집분이 교정 없이 남는다. 채점은 `bars` 테이블의 `krx_regular` 봉(기존 `KISRegularProvider` 분봉 재구성)만 쓴다. `provider_daily` 봉은 기준선 입력 전용이다.
- 워커: `python -m app.services.league_worker {drain|enqueue <morning|evening>|status}`. miniPC 작업 `MarketFlow-LeagueWorker`(SYSTEM, 5분 주기, `deploy/register_league_worker_task.ps1`)가 `drain`을 실행한다.
- `scheduler.py`는 평일 07:30(`league_morning`)과 20:45(`league_evening`)에 잡을 큐에 넣기만 한다.
- 해소 표본이 100건 미만인 예측자의 성적표는 `insufficient`다. 주문·매매 경로는 없다.
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_league_scheduler_hook.py tests/test_league_price_audit.py -q`
Expected: `5 passed`

Run: `cd "$WT" && powershell -NoProfile -File deploy/register_league_worker_task.ps1 -Plan`
Expected: `Name`이 `MarketFlow-LeagueWorker`, `Arguments`가 `-X utf8 -m app.services.league_worker drain`인 JSON. 작업은 등록되지 않는다.

- [ ] **Step 5: 커밋**

```bash
cd "$WT" && git add scheduler.py CLAUDE.md deploy/register_league_worker_task.ps1 scripts/audit_league_price_sources.py tests/test_league_scheduler_hook.py tests/test_league_price_audit.py && git commit -m "feat(league): enqueue league jobs from the scheduler and add the drain task script

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 14: 전체 검증과 반영

**Files:** 없음 (검증과 승인 단계)

- [ ] **Step 1: 리그 테스트 전체**

Run: `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q -k league`
Expected: `97 passed` (Task 1~13 합계: 6+3+18+11+9+7+5+5+5+10+5+8+5)

- [ ] **Step 2: 실제 데이터로 한 번 돌려 보기 (본PC, 격리된 폴더)**

네트워크로 FinanceDataReader를 부른다. 저장 위치를 스크래치 폴더로 돌려 프로젝트 데이터에 쓰지 않는다. KIS 호출(`collect_regular`)은 하지 않는다.

```bash
cd "$WT" && export FORECAST_LEAGUE_DIR="$TEMP/league_phase1_trial" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from datetime import date
from app.services.forecast_league import baselines, clock, db, price_sources
today = date.today()
asof = clock.previous_trading_day(today).isoformat()
with db.connect() as conn:
    print(price_sources.sync_universe_bars(conn, today=today.isoformat()))
    print('base rate', baselines.universe_base_rate(conn, asof))
    ranks = baselines.momentum_ranks(conn, asof)
    print('momentum universe', len(ranks))
"
```

Expected: `codes`가 2,500 이상, `failed`가 `codes`의 5% 미만, `base rate`의 `n`이 10만 이상이고 `rate`가 0과 1 사이, `momentum universe`가 2,000 이상. 실행 시간과 `rate` 값을 기록해 보고에 넣는다. 어느 하나라도 벗어나면 멈추고 원인을 확인한다.

- [ ] **Step 3: 전체 테스트 스위트**

Run (백그라운드, 약 30분): `cd "$WT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q > "$TEMP/league_phase1_pytest.log" 2>&1; echo "PYTEST_EXIT=$?" >> "$TEMP/league_phase1_pytest.log"`
Expected: `PYTEST_EXIT=0`, 실패 0. 기준선은 0단계 종료 시점의 `6691 passed, 5 skipped`에 이 계획의 97건을 더한 수다.

- [ ] **Step 4: 최종 코드 리뷰**

`superpowers:requesting-code-review`로 `origin/main..HEAD` 전체를 검토한다. 중점: 제출 마감 계산, `asof` 이후 표본 차단(Task 9, 10), `krx_regular` 외 봉이 해소에 쓰이지 않는지, `scheduler.py` 변경이 등록 두 줄과 함수 세 개뿐인지.

- [ ] **Step 5: 사용자에게 보고하고 승인받기**

보고에 넣을 것: 커밋 목록, 테스트 결과, Step 2의 실측 수치, §0.1의 설계 변경 일곱 가지, 아래 운영 영향.

- miniPC에 새 작업 `MarketFlow-LeagueWorker`가 5분마다 실행된다.
- 평일 07:30에 FinanceDataReader로 약 2,900종목의 일봉을 받는다(처음 한 번은 420일치).
- 평일 20:45 이후 미해소 예측 종목 수 × 최대 4쪽의 KIS 분봉 요청이 나간다. 후보가 하루 30종목이면 8거래일 누적으로 밤마다 최대 약 1,000건이다.
- 워커 잡이 세 번 실패하면 개인봇으로 알림이 간다.

승인 항목(각각 따로): push, `main` 대상 PR, 병합, miniPC 반영.

- [ ] **Step 6: miniPC 반영 (승인 후)**

1. miniPC에서 `main`을 받는다(`.claude/skills/git-sync.md`).
2. 관리자 권한 셸에서 `powershell -ExecutionPolicy Bypass -File C:\bitman_marketfloww\deploy\register_league_worker_task.ps1`.
3. 스케줄러가 새 등록 두 줄을 읽으려면 스케줄러 프로세스를 다시 시작해야 한다. Flask는 이 변경과 무관하므로 재시작하지 않는다. 스케줄러 재시작 방법과 시점은 사용자가 정한다.
4. 수동으로 한 번 실행해 확인한다.

```powershell
cd C:\bitman_marketfloww
.venv\Scripts\python.exe -X utf8 -m app.services.league_worker enqueue morning
.venv\Scripts\python.exe -X utf8 -m app.services.league_worker drain
.venv\Scripts\python.exe -X utf8 -m app.services.league_worker status
```

Expected: `status`에 `done`이 2. `failed`가 있으면 `league.db`의 `jobs.last_error`를 본다.

- [ ] **Step 7: 운영 확인 (1단계 완료 기준)**

반영 후 첫 거래일 저녁 잡이 끝난 뒤 miniPC에서 확인한다.

```powershell
.venv\Scripts\python.exe -X utf8 -c "from app.services.forecast_league import db; c=db.connect().__enter__(); print([tuple(r) for r in c.execute('SELECT forecaster_id, COUNT(*) FROM forecasts GROUP BY 1')]); print([tuple(r) for r in c.execute('SELECT basis, COUNT(*) FROM bars GROUP BY 1')]); print([tuple(r) for r in c.execute('SELECT forecaster_id, status, n_resolved FROM scorecards')]); print([tuple(r) for r in c.execute('SELECT kind, status, last_error FROM jobs ORDER BY job_id DESC LIMIT 8')])"
.venv\Scripts\python.exe -X utf8 scripts\audit_league_price_sources.py --csv --session <그날 날짜>
```

완료 기준: 기준선 두 개의 예측이 있고, `krx_regular` 봉이 쌓이며, `scorecards`에 기준선 행이 생긴다(처음에는 `insufficient`). 점검 도구의 `bases.mismatch`로 `provider_daily`가 정규장 값과 얼마나 다른지 기록한다. 첫 해소는 진입 후 최대 8거래일 뒤에 나온다.

---

## 범위 밖

- `daily_prices.csv`의 장중 수집분 교정과, 그 파일을 쓰는 기존 엔진(가상 매매, 성과 추적, 국면 분류 등)의 재검증. 별도 과제로 다룬다.
- 조회 API, 성적표 화면, 기존 엔진 어댑터(2단계).
- 상주 워커와 워치독(4단계).
- 독립 거래소(KRX 공식 API) 가격 검증. 현재 정규장 봉은 같은 공급자(KIS)의 다른 엔드포인트로 교차 확인한 값이다.

## 알려진 한계

- 정규장 봉은 KIS 분봉에 의존한다. KIS가 분봉을 약 1년만 보관하므로 그보다 오래 수집이 밀린 예측은 `void`가 된다.
- 거래일 판정은 `holidays` 라이브러리와 `kis_screener`의 KRX 휴장 목록을 쓴다. 목록에 없는 임시 휴장일이 생기면 그날 봉이 없어 해소가 멈추고, 20거래일 뒤 `void`가 된다. 휴장 목록에 날짜를 추가하면 풀린다.
- `provider_daily` 봉은 수정주가 반영 시점이 종목마다 다를 수 있다. 최근 45일은 매일 다시 받지만 그보다 오래된 구간에 분할이 있으면 기저율 표본 몇 건이 왜곡된다.
- 기준선 모멘텀의 환산 확률은 해소 표본이 쌓이기 전까지 기저율과 같다(설계서 §14).
- 후보가 종가베팅 신호 종목뿐이라 하루 예측 수는 기준선 2개 × 신호 종목 수다. 해소 100건 도달 시점은 Task 14 Step 7 이후 일주일의 실제 수로 추정한다.
