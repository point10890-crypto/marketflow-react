"""GraphRAG Phase A + B endpoint tests.

청사진 ``docs/mirofish_graphrag_analysis_endpoint_implementation_blueprint_2026_05_14.md``
§13 테스트 계획에 대응:

1. status — admin 인증 필수 + payload 골격
2. entities/resolve — exact + prefix 복수 후보
3. entities/resolve — 초성 매치
4. entities/resolve — corp_code 역방향
5. entities/resolve — yahoo ticker
6. status — entities.db 적재 후 phase.B_resolver=True

격리 전략:
- ``create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})``
  로 운영 DB 와 분리.
- ``resolver.DATA_DIR`` / ``resolver.ENTITIES_DB`` /
  ``storage.ENTITIES_DB`` 를 ``tmp_path_factory`` 기반 임시 경로로 monkeypatch.
- ``populate_from_sources()`` 는 module-scope fixture 에서 단 1회 실행 →
  6개 테스트가 같은 SQLite 파일을 공유 (빠른 실행).
"""

from __future__ import annotations

import csv
import json
import os

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.services.mirofish.graphrag import populate_from_sources
from app.services.mirofish.graphrag import resolver as graphrag_resolver
from app.services.mirofish.graphrag import storage as graphrag_storage


# ── module-scope fixtures: 격리된 entities.db + admin app 1세트 ──

@pytest.fixture(scope='module')
def graphrag_paths(tmp_path_factory):
    """임시 디렉토리에 seed 데이터 작성 + module 동안 유효한 경로 dict 반환."""
    tmp = tmp_path_factory.mktemp('graphrag_data')

    # 1) ticker_to_yahoo_map.csv — 청사진 시나리오용 핵심 종목 5개
    ticker_csv = tmp / 'ticker_to_yahoo_map.csv'
    with open(ticker_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ticker', 'market', 'yahoo_ticker', 'name'])
        writer.writerow(['005930', 'KOSPI', '005930.KS', '삼성전자'])
        writer.writerow(['006400', 'KOSPI', '006400.KS', '삼성SDI'])
        writer.writerow(['028260', 'KOSPI', '028260.KS', '삼성물산'])
        writer.writerow(['000660', 'KOSPI', '000660.KS', 'SK하이닉스'])
        writer.writerow(['000150', 'KOSPI', '000150.KS', '두산'])

    # 2) dart_corp_codes.json — 삼성전자만 청사진 §5.1 명시값 (00126380)
    corp_json = tmp / 'dart_corp_codes.json'
    with open(corp_json, 'w', encoding='utf-8') as f:
        json.dump({'005930': '00126380'}, f, ensure_ascii=False)

    # 3) entities.db 도 같은 디렉토리에 둠 (test 격리)
    entities_db = tmp / 'entities.db'

    return {
        'data_dir': str(tmp),
        'entities_db': str(entities_db),
        'graphrag_root': str(tmp),
    }


@pytest.fixture(scope='module', autouse=True)
def patched_graphrag(graphrag_paths):
    """resolver / storage 모듈 상수를 tmp 경로로 교체.

    monkeypatch fixture 는 function-scope 이므로 module-scope 에서는
    원본 값을 명시적으로 백업 + teardown 에서 복원.
    """
    original = {
        'resolver_DATA_DIR': graphrag_resolver.DATA_DIR,
        'resolver_ENTITIES_DB': graphrag_resolver.ENTITIES_DB,
        'storage_ENTITIES_DB': graphrag_storage.ENTITIES_DB,
        'storage_GRAPHRAG_ROOT': graphrag_storage.GRAPHRAG_ROOT,
    }
    graphrag_resolver.DATA_DIR = graphrag_paths['data_dir']
    graphrag_resolver.ENTITIES_DB = graphrag_paths['entities_db']
    graphrag_storage.ENTITIES_DB = graphrag_paths['entities_db']
    graphrag_storage.GRAPHRAG_ROOT = graphrag_paths['graphrag_root']

    yield

    graphrag_resolver.DATA_DIR = original['resolver_DATA_DIR']
    graphrag_resolver.ENTITIES_DB = original['resolver_ENTITIES_DB']
    graphrag_storage.ENTITIES_DB = original['storage_ENTITIES_DB']
    graphrag_storage.GRAPHRAG_ROOT = original['storage_GRAPHRAG_ROOT']


@pytest.fixture(scope='module')
def populated_db(patched_graphrag, graphrag_paths):
    """entities.db 에 seed 데이터 1회 적재.

    이미 적재된 entities.db 가 있으면 재사용 (멱등).
    """
    if not os.path.exists(graphrag_paths['entities_db']):
        result = populate_from_sources()
        assert result['entities_upserted'] >= 5, \
            f'expected >=5 entities, got {result}'
    return graphrag_paths


@pytest.fixture(scope='module')
def app(populated_db):
    """격리된 Flask 앱 + in-memory SQLite DB + admin user 1명.

    background worker 비활성화 (TESTING=True) → 테스트 끝나도 thread leak 없음.
    """
    flask_app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-graphrag-secret',
    })
    return flask_app


@pytest.fixture(scope='module')
def admin_token(app):
    """app 안에서 admin user 1명 생성 후 발급된 토큰 반환."""
    with app.app_context():
        admin = User(
            email='graphrag-admin@test.local',
            name='GraphRAG Test Admin',
            role='admin',
            status='approved',
            tier='premium',
        )
        admin.set_password('test-password-1234')
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)
    return token


@pytest.fixture
def client(app):
    return app.test_client()


def _auth(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


# ── 1) status: admin 인증 필수 + payload 구조 검증 ───────────────────

def test_graphrag_status_admin_required(client, admin_token):
    """토큰 없으면 401, 있으면 200 + 청사진 §12 응답 골격."""
    # 토큰 미첨부 → 401 (admin_required 의 _get_current_user None)
    no_auth = client.get('/api/admin/mirofish/graphrag/status')
    assert no_auth.status_code in (401, 403), \
        f'expected 401/403 without token, got {no_auth.status_code}'

    # admin 토큰 → 200
    resp = client.get(
        '/api/admin/mirofish/graphrag/status',
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, \
        f'expected 200 with admin token, got {resp.status_code}: {resp.get_data(as_text=True)[:200]}'
    data = resp.get_json()
    assert data['service'] == 'mirofish-graphrag'
    assert 'phase' in data and 'A_skeleton' in data['phase']
    assert data['phase']['A_skeleton'] is True
    assert 'storage' in data
    assert 'entities' in data
    assert 'flags' in data
    assert 'asof' in data


# ── 2) entities/resolve: exact + prefix → 복수 후보 ───────────────────

def test_entity_resolve_exact_and_prefix(client, admin_token):
    """``삼성`` 입력 → 삼성전자 exact + 삼성SDI/삼성물산 prefix."""
    resp = client.get(
        '/api/admin/mirofish/graphrag/entities/resolve?q=삼성',
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, \
        f'expected 200, got {resp.status_code}: {resp.get_data(as_text=True)[:200]}'
    data = resp.get_json()
    matches = data.get('matches', [])
    assert len(matches) >= 2, \
        f'expected >=2 candidates for "삼성", got {len(matches)}: {[m.get("name") for m in matches]}'

    names = [m.get('name') for m in matches]
    # 삼성전자, 삼성SDI, 삼성물산 중 최소 2개는 포함되어야 한다
    samsung_hits = [n for n in names if n and n.startswith('삼성')]
    assert len(samsung_hits) >= 2, \
        f'expected multiple 삼성-prefixed names, got {names}'

    # 모든 후보가 confidence 와 match_reason 을 포함해야 한다 (계약)
    for m in matches:
        assert 'confidence' in m, f'match missing confidence: {m}'
        assert 'match_reason' in m, f'match missing match_reason: {m}'
        assert 0 < m['confidence'] <= 1.01  # hint_market 보너스 허용


# ── 3) entities/resolve: 초성 매치 (한글 자모만) ──────────────────────

def test_entity_resolve_chosung(client, admin_token):
    """``ㄷㅅ`` (두산 초성) → 두산 종목 반환."""
    resp = client.get(
        '/api/admin/mirofish/graphrag/entities/resolve?q=ㄷㅅ',
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, \
        f'expected 200 for chosung query, got {resp.status_code}'
    data = resp.get_json()
    matches = data.get('matches', [])
    assert len(matches) >= 1, \
        f'expected >=1 match for "ㄷㅅ", got {len(matches)}'

    # 두산 (chosung 'ㄷㅅ') 이 후보에 포함되어야 한다
    names = [m.get('name') for m in matches]
    assert '두산' in names, \
        f'expected "두산" in chosung matches, got {names}'

    # 매치 이유가 초성 계열이어야 한다
    doosan = next(m for m in matches if m.get('name') == '두산')
    assert doosan['match_reason'] in ('chosung_exact', 'chosung_prefix'), \
        f'expected chosung match_reason for 두산, got {doosan["match_reason"]}'


# ── 4) entities/resolve: corp_code 역방향 ───────────────────────────

def test_entity_resolve_corp_code_reverse(client, admin_token):
    """``00126380`` (DART corp_code) → 삼성전자 entity (kr:005930)."""
    resp = client.get(
        '/api/admin/mirofish/graphrag/entities/resolve?q=00126380',
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, \
        f'expected 200, got {resp.status_code}'
    data = resp.get_json()
    matches = data.get('matches', [])
    assert len(matches) >= 1, \
        f'expected >=1 match for corp_code 00126380, got {len(matches)}'

    top = matches[0]
    assert top['entity_id'] == 'kr:005930', \
        f'expected kr:005930 for corp_code 00126380, got {top["entity_id"]}'
    assert top['match_reason'] == 'corp_code_reverse', \
        f'expected match_reason corp_code_reverse, got {top["match_reason"]}'
    assert top['confidence'] >= 0.98, \
        f'expected confidence >=0.98 for direct corp_code, got {top["confidence"]}'

    # external_ids 가 함께 붙어 있어야 한다 (_attach_external_ids 결과)
    assert 'ids' in top, f'expected ids dict attached, got keys={list(top.keys())}'
    assert top['ids'].get('corp_code') == '00126380'


# ── 5) entities/resolve: yahoo ticker ───────────────────────────────

def test_entity_resolve_yahoo_ticker(client, admin_token):
    """``005930.KS`` → kr:005930 (삼성전자)."""
    resp = client.get(
        '/api/admin/mirofish/graphrag/entities/resolve?q=005930.KS',
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, \
        f'expected 200, got {resp.status_code}'
    data = resp.get_json()
    matches = data.get('matches', [])
    assert len(matches) >= 1, \
        f'expected >=1 match for 005930.KS, got {len(matches)}'

    top = matches[0]
    assert top['entity_id'] == 'kr:005930', \
        f'expected kr:005930 for yahoo 005930.KS, got {top["entity_id"]}'
    assert top['match_reason'] == 'yahoo_ticker', \
        f'expected match_reason yahoo_ticker, got {top["match_reason"]}'
    # external_ids.yahoo_ticker 가 원본 형식과 일치
    assert top.get('ids', {}).get('yahoo_ticker') == '005930.KS'


# ── 6) status: 적재 후 phase.B_resolver=True ─────────────────────────

def test_status_reflects_phase_b_after_init(client, admin_token):
    """populated_db fixture 실행 후 status 가 Phase B 완료를 반영하는지."""
    resp = client.get(
        '/api/admin/mirofish/graphrag/status',
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # Phase A 는 무조건 True
    assert data['phase']['A_skeleton'] is True
    # entities.db 가 적재됐으므로 Phase B 도 True
    assert data['phase']['B_resolver'] is True, \
        f'expected phase.B_resolver=True after populate_from_sources, got phase={data["phase"]}'
    # entities 카운트 검증
    entities = data.get('entities', {})
    assert entities.get('present') is True, \
        f'expected entities.present=True, got {entities}'
    assert entities.get('entity_count', 0) >= 5, \
        f'expected entity_count>=5 (seeded 5 tickers), got {entities.get("entity_count")}'
    # state 가 ready 여야 한다 (root 존재 + db 존재 + count>0)
    assert data['state'] == 'ready', \
        f'expected state=ready, got {data["state"]}'
    assert data['ready'] is True
    # endpoints_live 도 갱신되어야 한다
    assert data['endpoints_live']['entities_resolve'] is True
    assert data['endpoints_live']['entities_get'] is True
