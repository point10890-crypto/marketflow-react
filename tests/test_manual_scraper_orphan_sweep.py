"""고아 스크래퍼 브라우저 정리 테스트.

2026-08-05 장애: `_close_selenium_driver` 는 정상 종료·예외를 모두 덮지만
프로세스가 강제 종료되면 finally 가 돌지 않는다. 워치독 재시작·재부팅마다
브라우저가 고아가 되어 07-31·08-02 자 잔해가 chrome 581 프로세스 9.72GB 를
점유했고, 15.4GB 머신의 가용 메모리가 1.16GB 로 떨어져 /api/health 가
10.7초까지 걸렸다. 앱이 죽은 것처럼 보였지만 우리 파이썬 10개는 0.09GB 였다.
"""
import subprocess
import sys
import threading
import time

import pytest

from app.services import manual_stock_analysis as M


def test_profile_prefix_is_specific_enough_to_spare_the_users_chrome():
    """접두어가 흔한 단어면 사용자의 실제 브라우저까지 죽인다."""
    assert M.SCRAPE_PROFILE_PREFIX.startswith('marketflow')
    assert len(M.SCRAPE_PROFILE_PREFIX) > 12


def test_sweep_targets_only_our_own_profile(monkeypatch, tmp_path):
    seen = {}

    def _run(cmd, **kwargs):
        seen['cmd'] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='3', stderr='')

    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'run', _run)
    monkeypatch.setattr(M.tempfile, 'gettempdir', lambda: str(tmp_path))

    assert M.sweep_orphan_browsers() == 3
    script = seen['cmd'][-1]
    assert M.SCRAPE_PROFILE_PREFIX in script
    assert "Name='chrome.exe'" in script


def test_sweep_removes_leftover_profile_directories(monkeypatch, tmp_path):
    """브라우저만 죽이고 프로필을 두면 임시 디스크가 계속 찬다."""
    ours = tmp_path / f'{M.SCRAPE_PROFILE_PREFIX}abc'
    ours.mkdir()
    theirs = tmp_path / 'some_other_temp_dir'
    theirs.mkdir()

    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'run',
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, stdout='0', stderr=''))
    monkeypatch.setattr(M.tempfile, 'gettempdir', lambda: str(tmp_path))

    M.sweep_orphan_browsers()

    assert not ours.exists()
    assert theirs.exists(), '우리 것이 아닌 디렉토리는 남아야 한다'


def test_sweep_is_a_noop_off_windows(monkeypatch):
    called = []
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: called.append(1))

    assert M.sweep_orphan_browsers() == 0
    assert called == []


@pytest.mark.parametrize('boom', [
    OSError('no powershell'),
    subprocess.TimeoutExpired('powershell', 30),
])
def test_sweep_failure_never_raises(monkeypatch, boom):
    """정리 실패가 앱 기동을 막으면 잔해보다 더 나쁘다."""
    monkeypatch.setattr(sys, 'platform', 'win32')

    def _boom(*a, **k):
        raise boom

    monkeypatch.setattr(subprocess, 'run', _boom)

    assert M.sweep_orphan_browsers() == 0


def test_boot_sweeps_even_when_the_loop_autostart_is_off(monkeypatch):
    """운영은 루프 자동시작을 끄고 쓰기도 한다. 잔해는 그와 무관하게 쌓인다."""
    done = threading.Event()
    monkeypatch.setattr(M, 'sweep_orphan_browsers', lambda *a, **k: done.set() or 0)
    monkeypatch.setattr(M, 'LOOP_BOOT_AUTOSTART', False)

    assert M.start_scraper_loop_on_boot() is False
    assert done.wait(timeout=5), '정리가 실행되지 않았다'


def test_boot_does_not_wait_for_the_sweep(monkeypatch):
    """이 함수의 계약은 '절대 블로킹하지 않는다' 다. 정리는 셸을 띄우므로 느리다."""
    monkeypatch.setattr(M, 'LOOP_BOOT_AUTOSTART', False)
    monkeypatch.setattr(M, 'sweep_orphan_browsers', lambda *a, **k: time.sleep(1.5) or 0)

    started = time.time()
    M.start_scraper_loop_on_boot()

    assert time.time() - started < 0.5


def test_boot_survives_a_sweep_failure(monkeypatch):
    raised = threading.Event()

    def _boom(*a, **k):
        raised.set()
        raise RuntimeError('sweep exploded')

    monkeypatch.setattr(M, 'sweep_orphan_browsers', _boom)
    monkeypatch.setattr(M, 'LOOP_BOOT_AUTOSTART', False)

    assert M.start_scraper_loop_on_boot() is False
    assert raised.wait(timeout=5)


# ── quit() 실패 시 강제 종료 ───────────────────────────────
# 2026-08-06: 어제 581개를 정리했는데 하루 만에 898개로 돌아왔다. 부팅 시 정리만
# 으로는 부족했다 — 10분 주기 루프가 사이클마다 하나씩 남기고 있었다.
# 원인은 _close_selenium_driver 의 `except Exception: pass` 로, quit() 이 실패해도
# 조용히 넘어가 Chrome 프로세스가 영원히 살아남았다.

class _Driver:
    def __init__(self, profile, fail=False):
        self._marketflow_user_data_dir = profile
        self.fail = fail
        self.quit_called = False

    def quit(self):
        self.quit_called = True
        if self.fail:
            raise RuntimeError('browser unresponsive')


def test_force_kill_runs_when_quit_raises(monkeypatch, tmp_path):
    profile = tmp_path / f'{M.SCRAPE_PROFILE_PREFIX}xyz'
    profile.mkdir()
    killed = []
    monkeypatch.setattr(M, 'kill_chrome_by_profile', lambda m, **k: killed.append(m) or 1)

    M._close_selenium_driver(_Driver(str(profile), fail=True))

    assert killed == [profile.name], 'quit() 실패 후 강제 종료가 없으면 브라우저가 영원히 남는다'
    assert not profile.exists()


def test_force_kill_also_runs_when_quit_succeeds(monkeypatch, tmp_path):
    """quit() 이 성공을 반환해도 프로세스가 남는 경우가 실제로 있었다."""
    profile = tmp_path / f'{M.SCRAPE_PROFILE_PREFIX}ok'
    profile.mkdir()
    killed = []
    monkeypatch.setattr(M, 'kill_chrome_by_profile', lambda m, **k: killed.append(m) or 0)

    driver = _Driver(str(profile))
    M._close_selenium_driver(driver)

    assert driver.quit_called
    assert killed == [profile.name]


def test_kill_targets_the_specific_profile_not_every_scrape_browser(monkeypatch):
    """진행 중인 다른 사이클의 브라우저까지 죽이면 안 된다."""
    seen = {}
    monkeypatch.setattr(sys, 'platform', 'win32')

    def _run(cmd, **kwargs):
        seen['script'] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, stdout='2', stderr='')

    monkeypatch.setattr(subprocess, 'run', _run)

    assert M.kill_chrome_by_profile('marketflow_manual_scrape_abc123') == 2
    assert 'marketflow_manual_scrape_abc123' in seen['script']


def test_kill_with_empty_marker_is_refused():
    """빈 marker 로 부르면 like '**' 가 되어 모든 Chrome 을 죽인다."""
    assert M.kill_chrome_by_profile('') == 0
