"""16:00 vcp_all 이 '보존'을 '실패'로 읽지 않는지 검증.

2026-07-28 ~ 08-10 사이 거래일마다 🚨 vcp_all 2회 시도 모두 실패 알림이 나갔다.
KR·US 는 매번 통과했고 CRYPTO 만 떨어졌는데, 그 CRYPTO 도 스캔은 정상이었다.
크립토 전면 하락으로 stage2=0 이 나왔고 스캐너가 last-known-good 을 지키려
저장을 건너뛰자, run_vcp_enhanced_scan 의 "mtime 5분" 검사가 그걸 실패로 읽었다.

핵심은 검사를 무르게 만드는 게 아니라 두 경우를 가르는 것이다:
  - 스캐너가 일부러 안 썼다 (보존)          → 성공. 단 보존본의 freshness 는 계속 검사.
  - 스캐너가 죽어서 못 썼다 / 안 돌았다      → 실패. 알림은 그대로 나가야 한다.
"""
import json
import os
import time
from unittest.mock import patch

import pytest

import scheduler
from scheduler import run_vcp_enhanced_scan


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler.Config, 'DATA_DIR', str(tmp_path))
    return tmp_path


def _write_result(data_dir, age_sec, signals=(('BTC',),)):
    """결과 파일을 age_sec 초 전 것으로 만든다 (이번 실행이 안 쓴 상태)."""
    path = data_dir / 'vcp_crypto_latest.json'
    path.write_text(json.dumps({
        'metadata': {'market': 'CRYPTO'},
        'summary': {'total_screened': 50, 'stage2_passed': 1},
        'signals': [{'symbol': s[0]} for s in signals],
    }), encoding='utf-8')
    old = time.time() - age_sec
    os.utime(path, (old, old))
    return path


def _write_status(data_dir, outcome, age_sec=5):
    path = data_dir / 'vcp_crypto_scan_status.json'
    path.write_text(json.dumps({
        'outcome': outcome,
        'scanned_at': '2026-08-10T16:04:23',
        'summary': {'total_screened': 50, 'stage2_passed': 0, 'download_failed': 7},
    }), encoding='utf-8')
    stamp = time.time() - age_sec
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture(autouse=True)
def _no_side_effects():
    with patch('scheduler.send_telegram'), patch('scheduler.time.sleep'):
        yield


def test_deliberate_preserve_is_not_a_failure(data_dir):
    """이번 장애의 회귀 테스트. 4시간 전 파일 + 이번 실행의 'preserved' 상태 = 성공."""
    _write_result(data_dir, age_sec=4 * 3600)
    _write_status(data_dir, 'preserved')

    with patch('scheduler.run_command', return_value=True):
        assert run_vcp_enhanced_scan('CRYPTO') is True


def test_a_dead_scan_is_still_a_failure(data_dir):
    """상태 파일이 없으면 = 스캐너가 저장 단계까지 못 갔다. 실패로 남아야 한다."""
    _write_result(data_dir, age_sec=4 * 3600)

    with patch('scheduler.run_command', return_value=True):
        assert run_vcp_enhanced_scan('CRYPTO') is False


def test_a_stale_status_does_not_excuse_a_stale_result(data_dir):
    """지난주의 'preserved' 상태가 오늘의 실패를 영구히 가려주면 안 된다."""
    _write_result(data_dir, age_sec=4 * 3600)
    _write_status(data_dir, 'preserved', age_sec=6 * 3600)

    with patch('scheduler.run_command', return_value=True):
        assert run_vcp_enhanced_scan('CRYPTO') is False


def test_preserved_but_too_old_to_use_is_a_failure(data_dir):
    """보존본이 크립토 허용치(12h)를 넘겼으면 진짜 장애다 — 알림이 나가야 한다."""
    _write_result(data_dir, age_sec=20 * 3600)
    _write_status(data_dir, 'preserved')

    with patch('scheduler.run_command', return_value=True):
        assert run_vcp_enhanced_scan('CRYPTO') is False


def test_a_fresh_save_still_passes_without_any_status(data_dir):
    """정상 경로(방금 저장)는 상태 파일 유무와 무관하게 그대로 통과해야 한다."""
    _write_result(data_dir, age_sec=5)

    with patch('scheduler.run_command', return_value=True):
        assert run_vcp_enhanced_scan('CRYPTO') is True


def test_a_failed_subprocess_is_still_a_failure(data_dir):
    """스캐너가 0 이 아닌 코드로 죽으면 보존 상태가 있어도 실패다."""
    _write_result(data_dir, age_sec=4 * 3600)
    _write_status(data_dir, 'preserved')

    with patch('scheduler.run_command', return_value=False):
        assert run_vcp_enhanced_scan('CRYPTO') is False
