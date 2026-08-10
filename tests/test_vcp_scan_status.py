"""스캔이 결과 파일을 '일부러' 안 쓴 것을 호출자가 알 수 있어야 한다.

2026-07-28 ~ 08-10 장애: 16:00 vcp_all 이 거래일마다 2회 시도 후 실패 알림을
띄웠다. 실제로는 KR·US 다 성공했고 CRYPTO 만 실패로 집계됐는데, 그 CRYPTO 도
스캔 자체는 정상이었다.

크립토가 전면 하락추세라 stage2 통과가 0 이었고(실측: 43/50 이 366봉 정상
수신 후 전부 Stage 4), _save_result() 가 last-known-good 을 지키느라 저장을
건너뛰었다. 저장을 건너뛰면 결과 파일 mtime 이 그대로다. scheduler 는 mtime
만 보고 "갱신 안 됨 = 스캔 실패" 로 읽었다.

'의도적 보존' 과 '스캔이 죽어서 아무것도 못 씀' 은 mtime 으로 구분되지 않는다.
스캐너가 매 실행마다 상태를 남겨서 그 둘을 갈라준다.
"""
import json
import time

import pytest

import vcp_enhanced_scanner as V


def _payload(screened, stage2, signals, download_failed=0):
    return {
        'metadata': {'market': 'CRYPTO'},
        'summary': {
            'total_screened': screened,
            'stage2_passed': stage2,
            'download_failed': download_failed,
        },
        'signals': signals,
    }


def _status(tmp_path, name='vcp_crypto_scan_status.json'):
    return json.loads((tmp_path / name).read_text(encoding='utf-8'))


def test_preserving_last_good_reports_itself(tmp_path, monkeypatch):
    """저장을 건너뛰었으면 건너뛰었다고 남겨야 한다 — 이게 없어서 오탐이 났다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text(json.dumps(_payload(50, 1, [{'symbol': 'MKR'}])), encoding='utf-8')

    outcome = V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    assert outcome == 'preserved'
    assert _status(tmp_path)['outcome'] == 'preserved'


def test_a_normal_save_reports_itself_too(tmp_path, monkeypatch):
    """보존 때만 상태를 남기면, 상태 파일이 낡았을 때 그게 '스캔이 안 돌았다'인지
    '이번엔 정상 저장했다'인지 다시 알 수 없어진다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))

    outcome = V._save_result(_payload(50, 2, [{'symbol': 'NEW'}]), 'vcp_crypto_latest.json')

    assert outcome == 'saved'
    assert _status(tmp_path)['outcome'] == 'saved'


def test_status_carries_the_evidence_that_settles_outage_vs_downtrend(tmp_path, monkeypatch):
    """stage2=0 하나로는 소스가 죽은 건지 시장이 죽은 건지 못 가른다.
    다운로드 실패 수가 그 둘을 가르는 유일한 증거인데 지금은 버려지고 있다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text(json.dumps(_payload(50, 1, [{'symbol': 'MKR'}])), encoding='utf-8')

    V._save_result(_payload(50, 0, [], download_failed=7), 'vcp_crypto_latest.json')

    summary = _status(tmp_path)['summary']
    assert summary['download_failed'] == 7
    assert summary['stage2_passed'] == 0
    assert summary['total_screened'] == 50


def test_status_is_timestamped(tmp_path, monkeypatch):
    """호출자는 '이번 실행이 남긴 상태'만 신뢰해야 한다. 시각이 없으면 판단 불가."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))

    before = time.time()
    V._save_result(_payload(50, 2, [{'symbol': 'NEW'}]), 'vcp_crypto_latest.json')

    written = (tmp_path / 'vcp_crypto_scan_status.json').stat().st_mtime
    assert written >= before - 1
    assert _status(tmp_path)['scanned_at']


@pytest.mark.parametrize('filename,status_name', [
    ('vcp_us_latest.json', 'vcp_us_scan_status.json'),
    ('vcp_kr_latest.json', 'vcp_kr_scan_status.json'),
])
def test_every_market_gets_its_own_status(tmp_path, monkeypatch, filename, status_name):
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / filename
    path.write_text(json.dumps(_payload(500, 4, [{'symbol': 'KEEP'}])), encoding='utf-8')

    V._save_result(_payload(500, 0, []), filename)

    assert _status(tmp_path, status_name)['outcome'] == 'preserved'


def test_status_never_clobbers_the_result_file(tmp_path, monkeypatch):
    """상태 파일 경로는 결과 파일명에서 파생된다. 파생이 실패해 같은 이름이 나오면
    결과를 상태로 덮어써 데이터를 통째로 날린다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))

    V._save_result(_payload(50, 2, [{'symbol': 'NEW'}]), 'vcp_oddball.json')

    kept = json.loads((tmp_path / 'vcp_oddball.json').read_text(encoding='utf-8'))
    assert kept['signals'] == [{'symbol': 'NEW'}], '결과 파일이 상태 파일로 덮였다'
