"""Chart symbol lookup keeps the existing member gate and local-only contract."""

import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

import app.auth.decorators as auth
import app.routes.admin_mirofish as routes
from app.models import db
from app.services.mirofish import live_data, store


SEARCH_PATH = '/api/admin/mirofish/targets/search'


@pytest.fixture
def ticker_source(tmp_path, monkeypatch):
    root = tmp_path / 'ticker_source'
    root.mkdir()
    ticker_map = root / 'ticker_to_yahoo_map.csv'
    ticker_map.write_text(
        'ticker,name,market,yahoo_ticker\n'
        '042700,한미반도체,KOSPI,042700.KS\n'
        '003690,코리안리,KOSPI,003690.KS\n'
        + ''.join(f'{900000 + index},반도체후보{index},KOSDAQ,{900000 + index}.KQ\n' for index in range(1, 11)),
        encoding='utf-8',
    )
    monkeypatch.setattr(live_data, 'REPO_ROOT', root)
    monkeypatch.setattr(live_data, 'DATA_DIR', root / 'data')
    monkeypatch.setattr(store, 'RUNS_ROOT', str(root / 'runs'))
    return root, ticker_map


@pytest.fixture
def client(monkeypatch, ticker_source):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SECRET_KEY='chart-symbol-search-test',
    )
    db.init_app(app)
    app.register_blueprint(routes.admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(
        id=1, email='fixture@example.test', status='approved', is_admin=True, is_aibain_active=False,
    ))
    return app.test_client()


@pytest.mark.parametrize('user, expected_status', [
    (None, 401),
    (SimpleNamespace(id=2, email='fixture@example.test', status='approved', is_admin=False, is_aibain_active=False), 403),
    (SimpleNamespace(id=3, email='fixture@example.test', status='approved', is_admin=False, is_aibain_active=True), 200),
    (SimpleNamespace(id=4, email='fixture@example.test', status='approved', is_admin=True, is_aibain_active=False), 200),
], ids=['unauthenticated', 'no_tier', 'active_ai_brain', 'admin'])
def test_symbol_search_uses_existing_ai_brain_access_gate(client, monkeypatch, user, expected_status):
    search = Mock(wraps=store.search_target_candidates)
    monkeypatch.setattr(routes.mirofish, 'search_target_candidates', search)
    monkeypatch.setattr(auth, '_get_current_user', lambda: user)

    result = client.get(SEARCH_PATH, query_string={'target': '한미반도체', 'limit': 8})

    assert result.status_code == expected_status
    if expected_status == 200:
        assert result.json['candidates'][0]['symbol'] == '042700'
        search.assert_called_once_with('한미반도체', limit=8)
    else:
        search.assert_not_called()


@pytest.mark.parametrize('target, match_type', [
    ('한미반도체', 'exact'),
    ('한미', 'name_prefix'),
    ('042700', 'symbol'),
    ('ㅎㅁㅂㄷㅊ', 'initial_exact'),
], ids=['name', 'partial_name', 'six_digit_code', 'korean_initials'])
def test_symbol_search_returns_a_local_equity_candidate_contract(client, target, match_type):
    result = client.get(SEARCH_PATH, query_string={'target': target, 'limit': 8})

    assert result.status_code == 200
    assert result.json == {
        'target': target,
        'source': 'ticker_map',
        'candidates': [{
            'symbol': '042700',
            'name': '한미반도체',
            'display_name': '한미반도체',
            'market': 'KOSPI',
            'yahoo_ticker': '042700.KS',
            'asset_type': 'equity',
            'score': {'exact': 125, 'name_prefix': 110, 'symbol': 120, 'initial_exact': 112}[match_type],
            'match_type': match_type,
        }],
    }


def test_symbol_search_obeys_requested_eight_candidate_limit(client):
    result = client.get(SEARCH_PATH, query_string={'target': '반도체', 'limit': 8})

    assert result.status_code == 200
    candidates = result.json['candidates']
    assert len(candidates) == 8
    assert [row['symbol'] for row in candidates] == [f'{900000 + index}' for index in range(1, 9)]
    assert len({row['symbol'] for row in candidates}) == 8


@pytest.mark.parametrize('limit', ['invalid', '8.5', ''])
def test_symbol_search_rejects_non_integer_limits_before_service(client, monkeypatch, limit):
    search = Mock(wraps=store.search_target_candidates)
    monkeypatch.setattr(routes.mirofish, 'search_target_candidates', search)

    result = client.get(SEARCH_PATH, query_string={'target': '한미반도체', 'limit': limit})

    assert result.status_code == 400
    search.assert_not_called()


@pytest.mark.parametrize('method', ['POST', 'PUT', 'DELETE'])
def test_symbol_search_does_not_accept_mutating_methods(client, monkeypatch, method):
    search = Mock(wraps=store.search_target_candidates)
    monkeypatch.setattr(routes.mirofish, 'search_target_candidates', search)

    assert client.open(SEARCH_PATH, method=method).status_code == 405
    search.assert_not_called()


def test_symbol_search_reads_only_the_local_map_without_kis_context_network_or_writes(client, monkeypatch, ticker_source):
    root, ticker_map = ticker_source
    before = ticker_map.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('Candidate lookup must only read the local ticker map')

    monkeypatch.setenv('MIROFISH_USE_KIS', '1')
    monkeypatch.setattr(live_data, 'build_context', forbidden)
    monkeypatch.setattr(live_data, 'load_kis_snapshot', forbidden)
    monkeypatch.setattr(live_data, '_fetch_kis_snapshot_uncached', forbidden)
    monkeypatch.setattr(store, 'resolve_target_snapshot', forbidden)
    monkeypatch.setattr(routes.mirofish, 'resolve_target_snapshot', forbidden)
    monkeypatch.setattr(store, 'create_run', forbidden)
    monkeypatch.setattr(store, 'write_json_atomic', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)

    result = client.get(SEARCH_PATH, query_string={'target': ' 한미반도체 ', 'limit': 8})

    assert result.status_code == 200
    assert result.json['target'] == '한미반도체'
    assert result.json['candidates'][0]['symbol'] == '042700'
    assert 'kis' not in result.json
    assert 'price' not in result.json
    assert ticker_map.read_bytes() == before
    assert list(root.iterdir()) == [ticker_map]


def test_blank_symbol_search_returns_no_candidates_without_loading_the_map(client, monkeypatch):
    def forbidden_map_read():
        raise AssertionError('Empty lookup must not read the map')

    monkeypatch.setattr(live_data, '_load_ticker_map', forbidden_map_read)

    result = client.get(SEARCH_PATH, query_string={'target': ' ', 'limit': 8})

    assert result.status_code == 200
    assert result.json == {'target': '', 'candidates': []}
