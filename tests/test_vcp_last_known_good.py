"""빈 스캔 결과가 멀쩡한 결과를 덮지 않는지 검증.

2026-08-06 장애: 크립토 VCP 대시보드가 비어 있었다. 스캔은 매번 돌고 파일도
갱신되고 있었는데 내용이 늘 signals=[] 였다.

같은 파일에 쓰는 생산자가 둘이다. 16:21 에 crypto-analytics 스캔이 시그널 1건을
저장했고, 16:26·16:27 에 이 Enhanced 스캔이 stage2=0 (screened=50) 으로 두 번
덮어썼다. scheduler 의 self-verify 는 그 이상을 정확히 짚어냈지만
("yfinance 일시 장애 의심") 저장이 끝난 뒤에 도는 검사라 이미 늦었다.
"""
import json
import os
import time

import pytest

import vcp_enhanced_scanner as V


def _payload(screened, stage2, signals):
    return {
        'metadata': {'market': 'CRYPTO'},
        'summary': {'total_screened': screened, 'stage2_passed': stage2},
        'signals': signals,
    }


def test_outage_shape_is_recognised():
    """훑기는 했는데 1차 관문조차 0 이면 시장이 조용한 게 아니라 소스가 죽은 쪽이다."""
    assert V._looks_like_a_data_outage(_payload(50, 0, [])) is True


def test_a_genuinely_quiet_market_is_not_an_outage():
    """stage2 를 통과한 종목이 있는데 최종 시그널이 없는 것은 정상이다."""
    assert V._looks_like_a_data_outage(_payload(50, 3, [])) is False


def test_zero_screened_is_not_treated_as_an_outage():
    """아무것도 훑지 못한 경우는 별개 문제 — 여기서 판단하지 않는다."""
    assert V._looks_like_a_data_outage(_payload(0, 0, [])) is False


def test_empty_result_does_not_overwrite_existing_signals(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    good = _payload(50, 1, [{'symbol': 'MKR'}])
    path.write_text(json.dumps(good), encoding='utf-8')

    V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    kept = json.loads(path.read_text(encoding='utf-8'))
    assert kept['signals'] == [{'symbol': 'MKR'}], '빈 결과가 멀쩡한 결과를 덮었다'


def test_empty_result_does_not_write_an_empty_archive_either(tmp_path, monkeypatch):
    """아카이브만 빈 값으로 남으면 그날 기록이 통째로 사라진다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text(json.dumps(_payload(50, 1, [{'symbol': 'MKR'}])), encoding='utf-8')

    V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    archives = list(tmp_path.glob('vcp_crypto_2*.json'))
    assert archives == [], f'빈 아카이브가 생성됐다: {archives}'


def test_a_real_result_always_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text(json.dumps(_payload(50, 1, [{'symbol': 'OLD'}])), encoding='utf-8')

    V._save_result(_payload(50, 2, [{'symbol': 'NEW'}]), 'vcp_crypto_latest.json')

    assert json.loads(path.read_text(encoding='utf-8'))['signals'] == [{'symbol': 'NEW'}]


def test_empty_result_writes_when_nothing_worth_keeping_exists(tmp_path, monkeypatch):
    """지킬 게 없으면 빈 결과라도 남겨야 한다 — 파일이 아예 없는 것보다 낫다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))

    V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    written = json.loads((tmp_path / 'vcp_crypto_latest.json').read_text(encoding='utf-8'))
    assert written['summary']['total_screened'] == 50


def test_empty_result_writes_when_the_previous_one_was_also_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text(json.dumps(_payload(50, 0, [])), encoding='utf-8')

    V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    assert json.loads(path.read_text(encoding='utf-8'))['summary']['stage2_passed'] == 0


def test_a_stale_good_result_stops_being_protected(tmp_path, monkeypatch):
    """며칠 지난 시그널을 계속 붙들면 대시보드가 옛날 것을 오늘처럼 보여준다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text(json.dumps(_payload(50, 1, [{'symbol': 'ANCIENT'}])), encoding='utf-8')
    old = time.time() - (V.LAST_GOOD_MAX_AGE_SEC + 600)
    os.utime(path, (old, old))

    V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    assert json.loads(path.read_text(encoding='utf-8'))['signals'] == []


def test_unreadable_previous_file_does_not_block_the_write(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / 'vcp_crypto_latest.json'
    path.write_text('{broken', encoding='utf-8')

    V._save_result(_payload(50, 0, []), 'vcp_crypto_latest.json')

    assert json.loads(path.read_text(encoding='utf-8'))['summary']['total_screened'] == 50


@pytest.mark.parametrize('filename', ['vcp_us_latest.json', 'vcp_kr_latest.json'])
def test_the_guard_applies_to_every_market(tmp_path, monkeypatch, filename):
    """같은 저장 경로를 US·KR 도 쓴다. 크립토만 고치면 나머지가 같은 식으로 비워진다."""
    monkeypatch.setattr(V, 'DATA_DIR', str(tmp_path))
    path = tmp_path / filename
    path.write_text(json.dumps(_payload(500, 4, [{'symbol': 'KEEP'}])), encoding='utf-8')

    V._save_result(_payload(500, 0, []), filename)

    assert json.loads(path.read_text(encoding='utf-8'))['signals'] == [{'symbol': 'KEEP'}]
