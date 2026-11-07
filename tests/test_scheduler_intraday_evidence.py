"""Paper intraday success means every held symbol was checked, including no holdings."""
from datetime import datetime
import json

import pytest

import scheduler
from app.services import kis_screener
from app.services.mirofish import paper_orchestrator as paper


@pytest.fixture
def quotes(monkeypatch):
    monkeypatch.setattr(paper.pp, 'load_ledger', lambda: {'open': [{'symbol': '005930'}, {'symbol': '000660'}]})
    monkeypatch.setattr(kis_screener, 'get_token', lambda: 'test-token')
    monkeypatch.setattr(paper.pp, 'intraday_check', lambda data: [])
    return monkeypatch


def test_no_positions_is_a_completed_check_without_price_calls(quotes):
    quotes.setattr(paper.pp, 'load_ledger', lambda: {'open': []})
    quotes.setattr(kis_screener, 'get_token', lambda: pytest.fail('no holdings need no token'))
    result = paper.run_intraday_watch()
    assert result['status'] == 'completed'
    assert result['expected'] == result['checked'] == 0
    assert result['missing_symbols'] == []


def test_partial_quotes_keep_completed_checks_but_do_not_claim_success(quotes):
    quotes.setattr(kis_screener, 'fetch_price_detail',
                  lambda _, symbol: {'stck_prpr': '70000'} if symbol == '005930' else {})
    observed = []
    quotes.setattr(paper.pp, 'intraday_check', lambda data: observed.append(data) or [])
    result = paper.run_intraday_watch()
    assert result['status'] == 'partial'
    assert result['expected'] == 2 and result['checked'] == 1
    assert result['missing_symbols'] == ['000660']
    assert observed == [{'005930': {'price': 70000.0}}]


def test_failed_token_is_not_equivalent_to_no_positions(quotes):
    def unavailable():
        raise RuntimeError('upstream unavailable')
    quotes.setattr(kis_screener, 'get_token', unavailable)
    result = paper.run_intraday_watch()
    assert result['status'] == 'failed'
    assert result['expected'] == 2 and result['checked'] == 0
    assert result['missing_symbols'] == ['000660', '005930']


@pytest.mark.parametrize('price', [None, '', 'NaN', 'Infinity', '0', '-1'])
def test_invalid_quote_cannot_count_as_a_checked_position(quotes, price):
    quotes.setattr(kis_screener, 'fetch_price_detail', lambda *_: {'stck_prpr': price})
    quotes.setattr(paper.pp, 'intraday_check', lambda _: pytest.fail('invalid quote must not reach exit rules'))
    result = paper.run_intraday_watch()
    assert result['status'] == 'failed' and result['checked'] == 0


def test_duplicate_positions_need_one_quote_per_symbol(quotes):
    quotes.setattr(paper.pp, 'load_ledger', lambda: {'open': [{'symbol': '005930'}, {'symbol': '005930'}]})
    calls = []
    quotes.setattr(kis_screener, 'fetch_price_detail', lambda _, symbol: calls.append(symbol) or {'stck_prpr': '70000'})
    result = paper.run_intraday_watch()
    assert result['status'] == 'completed' and result['checked'] == result['expected'] == 1
    assert calls == ['005930']


@pytest.fixture
def clock(tmp_path, monkeypatch):
    class FrozenDatetime(datetime):
        current = datetime(2026, 11, 9, 9, 5)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(scheduler, 'datetime', FrozenDatetime)
    monkeypatch.setattr(scheduler, '_LAST_RUN_FILE', str(tmp_path / 'scheduler_last_run.json'))
    monkeypatch.setattr(scheduler, 'check_storage', lambda *_: {'status': 'healthy'})
    monkeypatch.setattr(scheduler, 'send_telegram', lambda *a, **k: True)
    return FrozenDatetime, tmp_path / 'scheduler_last_run.json'


def test_registered_intraday_jobs_record_every_successful_slot(clock, monkeypatch):
    frozen, path = clock
    monkeypatch.setattr(paper, 'run_intraday_watch', lambda: {
        'status': 'completed', 'expected': 0, 'checked': 0, 'missing_symbols': [], 'exits': [], 'message': '',
    })
    scheduler.schedule.clear()
    try:
        scheduler.Scheduler().setup_schedules()
        jobs = [j for j in scheduler.schedule.jobs
                if j.job_func.__name__.endswith('[alpha_intraday_watch]')]
        assert len(jobs) == 5 * len(scheduler.Config.ALPHA_INTRADAY_TIMES)
        jobs[0].job_func()
        assert json.loads(path.read_text())['alpha_intraday_watch'] == '2026-11-09T09:05:00'
        frozen.current = datetime(2026, 11, 9, 9, 15)
        jobs[1].job_func()
        assert json.loads(path.read_text())['alpha_intraday_watch'] == '2026-11-09T09:15:00'
    finally:
        scheduler.schedule.clear()


@pytest.mark.parametrize('result', [
    {'status': 'partial', 'expected': 2, 'checked': 1, 'missing_symbols': ['000660']},
    {'status': 'failed', 'expected': 2, 'checked': 0, 'missing_symbols': ['000660', '005930']},
    {'checked': 0, 'exits': [], 'message': ''},
])
def test_incomplete_intraday_check_never_records_success(clock, monkeypatch, result):
    _, path = clock
    calls = []
    monkeypatch.setattr(paper, 'run_intraday_watch', lambda: calls.append(1) or result)
    wrapped = scheduler.Scheduler._with_record(scheduler._run_alpha_intraday_watch,
                                               'alpha_intraday_watch', max_retries=0)
    assert wrapped() is False
    assert len(calls) == 1
    assert not path.exists()


@pytest.mark.parametrize('now', [datetime(2026, 11, 8, 10), datetime(2026, 12, 25, 10), datetime(2026, 11, 9, 17)])
def test_closed_market_does_not_execute_or_record_intraday(clock, monkeypatch, now):
    frozen, path = clock
    frozen.current = now
    monkeypatch.setattr(paper, 'run_intraday_watch', lambda: pytest.fail('closed market must not query'))
    wrapped = scheduler.Scheduler._with_record(scheduler._run_alpha_intraday_watch,
                                               'alpha_intraday_watch', max_retries=0)
    assert wrapped() is False
    assert not path.exists()
