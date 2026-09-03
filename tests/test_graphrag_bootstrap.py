# -*- coding: utf-8 -*-
"""GraphRAG entities.db 부트스트랩 (Phase 1-B2).

`populate_from_sources()` 는 있었지만 아무도 부팅 시 호출하지 않아 새 체크아웃에서는
초성·별칭·퍼지 검색이 죽은 코드였다. 부트스트랩은 없음/빈 DB/7일 경과 시만 적재하고,
멱등이며, 절대 raise 하지 않는다.
"""
from __future__ import annotations

import csv
import json
import os
import time

import pytest

from app.services.mirofish.graphrag import bootstrap
from app.services.mirofish.graphrag import resolver as graphrag_resolver
from app.services.mirofish.graphrag import storage as graphrag_storage


@pytest.fixture()
def graphrag_env(tmp_path, monkeypatch):
    """임시 데이터 디렉토리 + 소형 유니버스 CSV + 격리된 entities.db 경로."""
    with open(tmp_path / 'ticker_to_yahoo_map.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ticker', 'market', 'yahoo_ticker', 'name'])
        w.writerow(['005930', 'KOSPI', '005930.KS', '삼성전자'])
        w.writerow(['000660', 'KOSPI', '000660.KS', 'SK하이닉스'])
        w.writerow(['041190', 'KOSDAQ', '041190.KQ', '우리기술투자'])
    with open(tmp_path / 'dart_corp_codes.json', 'w', encoding='utf-8') as f:
        json.dump({'005930': '00126380'}, f)

    db_path = str(tmp_path / 'graphrag' / 'entities.db')
    monkeypatch.setattr(graphrag_resolver, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(graphrag_resolver, 'ENTITIES_DB', db_path)
    monkeypatch.setattr(graphrag_storage, 'ENTITIES_DB', db_path)
    monkeypatch.setattr(graphrag_storage, 'GRAPHRAG_ROOT', str(tmp_path / 'graphrag'))
    return {'data_dir': str(tmp_path), 'db': db_path}


def test_ensure_creates_db_then_skips_when_fresh(graphrag_env):
    first = bootstrap.ensure_entities_db()
    assert first['status'] == 'ok'
    assert first['reason'] == 'missing'
    assert first['entities'] == 3
    assert os.path.isfile(graphrag_env['db'])

    second = bootstrap.ensure_entities_db()
    assert second['status'] == 'skipped'
    assert second['reason'] == 'fresh'
    assert second['entities'] == 3

    forced = bootstrap.ensure_entities_db(force=True)
    assert forced['status'] == 'ok' and forced['reason'] == 'forced' and forced['entities'] == 3


def test_stale_db_is_repopulated_after_max_age(graphrag_env):
    bootstrap.ensure_entities_db()
    old = time.time() - 10 * 86400
    os.utime(graphrag_env['db'], (old, old))

    result = bootstrap.ensure_entities_db(max_age_days=7)
    assert result['status'] == 'ok'
    assert result['reason'] == 'stale'


def test_chosung_and_alias_search_come_alive_after_bootstrap(graphrag_env, monkeypatch):
    """부트스트랩 뒤에는 decision_brief 의 초성/별칭 검색이 실제로 동작해야 한다."""
    from app.services.mirofish import decision_brief

    monkeypatch.setattr(decision_brief, 'load_universe',
                        lambda: {'005930': '삼성전자', '000660': 'SK하이닉스', '041190': '우리기술투자'})

    # 부트스트랩 전: 리졸버는 빈 결과 → 초성 검색은 아무것도 못 찾는다
    assert decision_brief.search_symbols('ㅅㅅㅈㅈ')['candidates'] == []

    assert bootstrap.ensure_entities_db()['status'] == 'ok'

    hits = decision_brief.search_symbols('ㅅㅅㅈㅈ')['candidates']
    assert hits and hits[0]['symbol'] == '005930'
    assert hits[0]['name'] == '삼성전자'
    assert 'chosung' in hits[0]['reason']

    assert decision_brief.resolve_symbol('하닉') == ('000660', 'SK하이닉스')


def test_bootstrap_never_raises_and_reports_empty_universe(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'graphrag' / 'entities.db')
    monkeypatch.setattr(graphrag_resolver, 'DATA_DIR', str(tmp_path))  # CSV 없음
    monkeypatch.setattr(graphrag_resolver, 'ENTITIES_DB', db_path)
    monkeypatch.setattr(graphrag_storage, 'ENTITIES_DB', db_path)
    monkeypatch.setattr(graphrag_storage, 'GRAPHRAG_ROOT', str(tmp_path / 'graphrag'))

    result = bootstrap.ensure_entities_db()
    assert result['status'] == 'error'
    assert result['entities'] == 0
    assert 'ticker_to_yahoo_map' in result['error']

    def boom():
        raise RuntimeError('disk on fire')

    monkeypatch.setattr(graphrag_resolver, 'populate_from_sources', boom)
    result = bootstrap.ensure_entities_db(force=True)
    assert result['status'] == 'error'
    assert 'disk on fire' in result['error']


def test_scheduler_job_maps_status_to_bool(monkeypatch):
    import scheduler

    monkeypatch.setattr(bootstrap, 'ensure_entities_db', lambda **kw: {'status': 'skipped', 'reason': 'fresh', 'entities': 3})
    assert scheduler._run_graphrag_entities_bootstrap() is True
    monkeypatch.setattr(bootstrap, 'ensure_entities_db', lambda **kw: {'status': 'error', 'error': 'x', 'entities': 0})
    assert scheduler._run_graphrag_entities_bootstrap() is False
