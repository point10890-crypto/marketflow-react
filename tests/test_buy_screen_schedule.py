# -*- coding: utf-8 -*-
"""AI 매수 후보 선별 작업의 스케줄 등록 회귀 테스트.

정규 스케줄에만 넣고 놓친-스케줄 복구 목록에서 빠뜨리면, 데몬이 죽어 있던
날의 슬롯은 영영 복구되지 않는다(scheduler.py 의 catch-up 주석 참고).
"""
from __future__ import annotations

import inspect

import scheduler


def test_config_defaults_are_sane():
    cfg = scheduler.Config
    assert cfg.BUY_SCREEN_TARGET == 100
    # 로컬 daily_prices.csv 는 14:50 KR 갱신 작업이 채운다 — 그 뒤여야 한다.
    hour, minute = (int(x) for x in cfg.BUY_SCREEN_TIME.split(':'))
    assert hour * 60 + minute > 14 * 60 + 50
    # 구독자 채널 발송은 명시적으로 켜야 한다.
    assert cfg.BUY_SCREEN_TO_CHANNEL is False


def test_registered_in_weekday_schedule():
    src = inspect.getsource(scheduler.Scheduler.setup_schedules)
    assert 'Config.BUY_SCREEN_TIME' in src
    assert "'buy_screen'" in src


def test_registered_in_missed_schedule_recovery():
    src = inspect.getsource(scheduler.check_and_run_missed_tasks)
    assert "'buy_screen'" in src, "놓친 스케줄 복구 목록에 buy_screen 이 없다"
    assert '_run_buy_candidate_screen' in src


def test_runner_passes_channel_flag_only_when_enabled(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0
        stdout = ''
        stderr = ''

    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        return _Result()

    monkeypatch.setattr(scheduler.subprocess, 'run', fake_run)
    monkeypatch.setattr(scheduler.os.path, 'exists', lambda p: True)

    import pandas as pd
    monkeypatch.setattr(pd, 'read_csv', lambda *a, **k: pd.DataFrame({'x': range(100)}))

    monkeypatch.setattr(scheduler.Config, 'BUY_SCREEN_TO_CHANNEL', False)
    assert scheduler._run_buy_candidate_screen() is True
    assert '--channel' not in captured['cmd']
    assert '--target' in captured['cmd']

    monkeypatch.setattr(scheduler.Config, 'BUY_SCREEN_TO_CHANNEL', True)
    scheduler._run_buy_candidate_screen()
    assert '--channel' in captured['cmd']


def test_runner_reports_failure_on_nonzero_exit(monkeypatch):
    class _Result:
        returncode = 1
        stdout = ''
        stderr = 'boom'

    monkeypatch.setattr(scheduler.subprocess, 'run', lambda cmd, **k: _Result())
    assert scheduler._run_buy_candidate_screen() is False
