from datetime import datetime, timedelta, timezone
import logging

import pytest
from flask import Flask

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.routes import admin_mirofish as alpha_dashboard_route
from app.services.mirofish import alpha_dashboard


KST = timezone(timedelta(hours=9))


@pytest.fixture()
def admin_client():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-alpha-dashboard-secret',
    })
    client = app.test_client()
    with app.app_context():
        admin = User(
            email='alpha-dashboard-admin@test.local',
            name='Alpha Dashboard Admin',
            role='admin', status='approved', tier='premium',
        )
        admin.set_password('test-password-1234')
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


def _install_ready_sources(monkeypatch):
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'market_phase', lambda: {
        'phase': 'uptrend_broadening',
        'phase_label': '상승 추세 확산',
        'regime': 'RISK_ON',
        'breadth': 0.542,
        'breadth_change_5d': 0.031,
        'as_of': '2026-08-19',
    })
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'get_scanner_schedule_status', lambda now=None: {
        'enabled': True,
        'freshness': {'status': 'fresh'},
        'freshness_status': 'fresh',
        'source_files': [{'file': 'daily_prices.csv', 'freshness': 'fresh'}],
        'checked_at': '2026-08-20T08:40:00+09:00',
    })
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: {
        'run_id': 'scan_nonempty_1',
        'status': 'completed',
        'generated_at': '2026-08-20T08:30:00+09:00',
        'source': 'local_marketflow_artifacts',
        'freshness': {'status': 'fresh'},
        'source_files': [{'file': 'daily_prices.csv', 'freshness': 'fresh'}],
        'candidate_count': 1,
        'candidates': [{
            'rank': 1, 'symbol': '005930', 'name': '삼성전자',
            'display_name': '삼성전자', 'market': 'KOSPI',
            'alpha_score': 87.4, 'risk_score': 21.0,
            'action': 'BUY_CANDIDATE', 'horizon': '5d', 'price': 71500,
        }][:limit],
    })
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:01:00+00:00',
        'phase': {'phase': 'uptrend_broadening'},
        'open_positions': [{
            'symbol': '005930', 'name': '삼성전자',
            'entry_price': 70000, 'target_price': 75600, 'stop_price': 65100,
            'last_close': 71500, 'last_close_date': '2026-08-19',
            'unrealized_pct': 2.14, 'held_trading_days': 2,
        }],
        'pending': [{'symbol': '000660', 'name': 'SK하이닉스'}],
        'performance': {
            'window_days': 30, 'trades': 4, 'win_rate_pct': 75.0,
            'avg_return_pct': 2.5, 'cumulative_return_pct': 10.2,
            'recent': [], 'open_count': 1,
        },
        'rules': {'target_pct': 8.0, 'stop_pct': -7.0, 'max_hold_trading_days': 8},
        'disabled': False,
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_pipeline_operating_snapshot', lambda now=None: {
        'schema_version': 'mirofish.operating_workflow.v1',
        'generated_at': '2026-08-20T00:01:00+00:00',
        'date_kst': '2026-08-20',
        'workflow_id': 'wf_1',
        'workflow_status': 'completed',
        'current_stage_id': 'outcomes',
        'overall_status': 'ready',
        'stages': [{'id': 'top3', 'status': 'complete', 'count': 3, 'updated_at': '2026-08-20T06:00:00+00:00'}],
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days,
        'generated_at': '2026-08-20T00:02:00+00:00',
        'sample_size': 6,
        'workflow_count': 3,
        'summary': {
            'evaluated_count': 6, 'pending_count': 0,
            'hit_count': 4, 'miss_count': 2, 'hit_rate_pct': 66.67,
            'avg_forward_return_pct': 3.1,
        },
        'items': [],
    })


def test_dashboard_normalizes_five_source_backed_services(monkeypatch):
    _install_ready_sources(monkeypatch)

    result = alpha_dashboard.get_alpha_service_dashboard(
        candidate_limit=5,
        outcome_days=30,
        outcome_limit=10,
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    assert result['schema_version'] == 'mirofish.alpha_service_dashboard.v1'
    assert result['date_kst'] == '2026-08-20'
    assert [service['id'] for service in result['services']] == [
        'market_brief', 'score_leaders', 'intraday_flow',
        'trade_signals', 'performance_brief',
    ]
    market = result['services'][0]
    assert [(metric['key'], metric['value'], metric['unit']) for metric in market['metrics']] == [
        ('regime', 'RISK_ON', None),
        ('breadth', 54.2, '%'),
        ('breadth_change_5d', 3.1, '%p'),
    ]
    leaders = result['services'][1]
    assert leaders['items'][0]['symbol'] == '005930'
    assert leaders['provenance']['sources'][0]['run_id'] == 'scan_nonempty_1'
    assert result['services'][2]['items'][0]['last_close_date'] == '2026-08-19'
    performance = result['services'][4]['items']
    assert [item['source'] for item in performance] == ['paper_30d', 'workflow_outcomes']
    assert performance[0]['sample_count'] == 4
    assert performance[1]['sample_count'] == 6


def test_dashboard_marks_no_trade_samples_empty_instead_of_zero_success(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: None)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:00:00+00:00',
        'phase': {}, 'open_positions': [], 'pending': [],
        'performance': {
            'window_days': 30, 'trades': 0, 'win_rate_pct': 0.0,
            'avg_return_pct': 0.0, 'cumulative_return_pct': 0.0,
            'recent': [], 'open_count': 0,
        },
        'rules': {}, 'disabled': False,
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days, 'generated_at': '2026-08-20T00:00:00+00:00',
        'sample_size': 0, 'workflow_count': 0,
        'summary': {
            'evaluated_count': 0, 'pending_count': 0,
            'hit_count': 0, 'miss_count': 0,
            'hit_rate_pct': None, 'avg_forward_return_pct': None,
        },
        'items': [],
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 19, 0, tzinfo=KST),
    )

    assert result['status'] == 'empty'
    assert result['services'][1]['data_status'] == 'empty'
    performance = result['services'][4]
    assert performance['data_status'] == 'empty'
    assert all(item['win_rate'] is None for item in performance['items'])


def test_dashboard_does_not_count_pending_workflow_outcomes_as_evaluated_samples(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: None)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:00:00+00:00',
        'phase': {}, 'open_positions': [], 'pending': [],
        'performance': {
            'window_days': 30, 'trades': 0, 'win_rate_pct': 0.0,
            'avg_return_pct': 0.0, 'cumulative_return_pct': 0.0,
            'recent': [], 'open_count': 0,
        },
        'rules': {}, 'disabled': False,
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days, 'generated_at': '2026-08-20T00:00:00+00:00',
        'sample_size': 3, 'workflow_count': 1,
        'summary': {
            'evaluated_count': 0, 'pending_count': 3,
            'hit_count': 0, 'miss_count': 0,
            'hit_rate_pct': None, 'avg_forward_return_pct': None,
        },
        'items': [{'status': 'pending'}] * 3,
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 19, 0, tzinfo=KST),
    )

    workflow_outcomes = result['services'][4]['items'][1]
    assert workflow_outcomes['sample_count'] == 0
    assert workflow_outcomes['win_rate'] is None
    assert workflow_outcomes['average_return_pct'] is None
    assert result['services'][4]['data_status'] == 'empty'
    assert result['status'] == 'empty'


def test_dashboard_pending_paper_signal_keeps_overall_status_nonempty(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: None)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:00:00+00:00',
        'phase': {}, 'open_positions': [],
        'pending': [{'symbol': '000660', 'name': 'SK하이닉스'}],
        'performance': {
            'window_days': 30, 'trades': 0, 'win_rate_pct': 0.0,
            'avg_return_pct': 0.0, 'cumulative_return_pct': 0.0,
            'recent': [], 'open_count': 0,
        },
        'rules': {}, 'disabled': False,
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days, 'generated_at': '2026-08-20T00:00:00+00:00',
        'sample_size': 0, 'workflow_count': 0,
        'summary': {
            'evaluated_count': 0, 'pending_count': 0,
            'hit_count': 0, 'miss_count': 0,
            'hit_rate_pct': None, 'avg_forward_return_pct': None,
        },
        'items': [],
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 15, 5, tzinfo=KST),
    )

    assert result['status'] == 'ready'
    trade_signals = result['services'][3]
    assert trade_signals['items'][0]['count'] == 1


def test_dashboard_excludes_non_mapping_pending_items_and_marks_paper_partial(monkeypatch):
    _install_ready_sources(monkeypatch)
    paper = alpha_dashboard.paper_orchestrator.paper_overview()
    paper['pending'].extend(['not-a-signal', 7, None])
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: paper)

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 15, 5, tzinfo=KST),
    )

    trade_signals = result['services'][3]
    assert trade_signals['data_status'] == 'partial'
    assert trade_signals['items'][0]['count'] == 1
    assert trade_signals['warnings'] == [{
        'section': 'paper_overview',
        'code': 'source_data_invalid',
        'message': 'paper_overview 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    }]
    assert result['status'] == 'partial'


def test_dashboard_keeps_latest_nonempty_run_stale_provenance(monkeypatch):
    _install_ready_sources(monkeypatch)
    stale = alpha_dashboard.alpha_scanner.read_latest_scanner_candidates()
    stale['freshness'] = {'status': 'stale'}
    monkeypatch.setattr(
        alpha_dashboard.alpha_scanner,
        'read_latest_scanner_candidates',
        lambda limit=5: stale,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    leaders = next(service for service in result['services'] if service['id'] == 'score_leaders')
    assert leaders['data_status'] == 'stale'
    assert leaders['provenance']['sources'][0]['run_id'] == 'scan_nonempty_1'
    assert result['status'] == 'stale'


def test_dashboard_marks_old_nonempty_run_stale_without_borrowing_schedule_freshness(monkeypatch):
    _install_ready_sources(monkeypatch)
    old_run = alpha_dashboard.alpha_scanner.read_latest_scanner_candidates()
    old_run['generated_at'] = '2026-08-14T23:30:00+00:00'
    old_run['freshness'] = {'status': 'fresh'}
    monkeypatch.setattr(
        alpha_dashboard.alpha_scanner,
        'read_latest_scanner_candidates',
        lambda limit=5: old_run,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    leaders = result['services'][1]
    candidate_source, schedule_source = leaders['provenance']['sources']
    assert leaders['data_status'] == 'stale'
    assert candidate_source['run_id'] == 'scan_nonempty_1'
    assert candidate_source['as_of'] == '2026-08-14T23:30:00+00:00'
    assert candidate_source['freshness'] == 'stale'
    assert schedule_source['freshness'] == 'fresh'


def test_dashboard_isolates_one_source_failure(monkeypatch, caplog):
    _install_ready_sources(monkeypatch)

    def fail_paper():
        raise ValueError('corrupt ledger path must not leak')

    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', fail_paper)

    with caplog.at_level(logging.ERROR, logger=alpha_dashboard.__name__):
        result = alpha_dashboard.get_alpha_service_dashboard(
            now=datetime(2026, 8, 20, 15, 20, tzinfo=KST),
        )

    assert result['status'] == 'partial'
    assert len(result['services']) == 5
    assert next(s for s in result['services'] if s['id'] == 'score_leaders')['data_status'] == 'ready'
    intraday = next(s for s in result['services'] if s['id'] == 'intraday_flow')
    assert intraday['data_status'] == 'partial'
    assert intraday['warnings'] == [{
        'section': 'paper_overview',
        'code': 'source_read_failed',
        'message': 'paper_overview 데이터를 읽지 못했습니다.',
        'severity': 'error',
    }]
    assert result['warnings'] == [{
        'section': 'paper_overview',
        'code': 'source_read_failed',
        'message': 'paper_overview 데이터를 읽지 못했습니다.',
        'severity': 'error',
    }]
    assert 'corrupt ledger path' not in str(result)
    assert 'alpha dashboard source read failed: paper_overview' in caplog.text


def test_dashboard_isolates_malformed_source_shape_to_affected_services(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(
        alpha_dashboard.paper_orchestrator,
        'paper_overview',
        lambda: ['malformed-paper-shape'],
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 15, 20, tzinfo=KST),
    )

    assert result['status'] == 'partial'
    assert result['services'][1]['data_status'] == 'ready'
    assert result['services'][2]['data_status'] == 'partial'
    assert result['services'][3]['data_status'] == 'partial'
    assert result['services'][4]['data_status'] == 'partial'
    assert result['warnings'] == [{
        'section': 'paper_overview',
        'code': 'source_data_invalid',
        'message': 'paper_overview 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    }]


def test_dashboard_nulls_invalid_market_number_and_marks_only_market_partial(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'market_phase', lambda: {
        'phase': 'uptrend_broadening',
        'phase_label': '상승 추세 확산',
        'regime': 'RISK_ON',
        'breadth': 'not-a-number',
        'breadth_change_5d': 0.031,
        'as_of': '2026-08-19',
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    market = result['services'][0]
    breadth = next(metric for metric in market['metrics'] if metric['key'] == 'breadth')
    assert market['data_status'] == 'partial'
    assert breadth['value'] is None
    assert result['services'][1]['data_status'] == 'ready'
    assert result['warnings'] == [{
        'section': 'market_phase',
        'code': 'source_data_invalid',
        'message': 'market_phase 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    }]


def test_dashboard_isolates_malformed_nested_source_shapes(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: {
        'run_id': 'bad-run', 'generated_at': '2026-08-20T08:30:00+09:00',
        'freshness': 'fresh', 'candidates': ['not-a-candidate'],
    })
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:00:00+00:00',
        'open_positions': ['not-a-position'], 'pending': 'not-a-list',
        'performance': 'not-a-mapping',
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_pipeline_operating_snapshot', lambda now=None: {
        'generated_at': '2026-08-20T00:00:00+00:00',
        'workflow_id': 'bad-workflow', 'stages': ['not-a-stage'],
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days, 'generated_at': '2026-08-20T00:00:00+00:00',
        'summary': 'not-a-mapping', 'items': [],
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 15, 20, tzinfo=KST),
    )

    assert len(result['services']) == 5
    assert result['status'] == 'partial'
    assert result['services'][0]['data_status'] == 'ready'
    assert [service['data_status'] for service in result['services'][1:]] == [
        'partial', 'partial', 'partial', 'partial',
    ]
    assert {warning['section'] for warning in result['warnings']} == {
        'latest_nonempty_run', 'paper_overview',
        'pipeline_operating_snapshot', 'workflow_outcomes',
    }


def test_dashboard_nulls_invalid_nested_numbers_without_returning_500(monkeypatch):
    _install_ready_sources(monkeypatch)
    leaders = alpha_dashboard.alpha_scanner.read_latest_scanner_candidates()
    leaders['candidates'][0].update({
        'alpha_score': 'bad-score', 'risk_score': {'value': 'bad-risk'},
        'price': 'bad-price',
    })
    monkeypatch.setattr(
        alpha_dashboard.alpha_scanner,
        'read_latest_scanner_candidates',
        lambda limit=5: leaders,
    )
    paper = alpha_dashboard.paper_orchestrator.paper_overview()
    paper['performance']['trades'] = 'bad-trade-count'
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: paper)
    pipeline = alpha_dashboard.pipeline_overview.get_pipeline_operating_snapshot()
    pipeline['stages'][0]['count'] = 'bad-stage-count'
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda now=None: pipeline,
    )
    outcomes = alpha_dashboard.pipeline_overview.get_outcomes_board()
    outcomes['summary']['evaluated_count'] = 'bad-evaluated-count'
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_outcomes_board',
        lambda days=30, limit=10: outcomes,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 15, 20, tzinfo=KST),
    )

    assert result['status'] == 'partial'
    candidate = result['services'][1]['items'][0]
    assert candidate['alpha_score'] is None
    assert candidate['risk_score'] is None
    assert candidate['price'] is None
    assert result['services'][3]['items'][2]['count'] is None
    assert result['services'][3]['items'][3]['count'] is None
    assert result['services'][4]['items'][0]['sample_count'] is None
    assert result['services'][4]['items'][1]['sample_count'] is None


def test_dashboard_marks_leaders_partial_when_schedule_source_fails(monkeypatch):
    _install_ready_sources(monkeypatch)

    def fail_schedule(now=None):
        raise RuntimeError('schedule source failed')

    monkeypatch.setattr(
        alpha_dashboard.alpha_scanner,
        'get_scanner_schedule_status',
        fail_schedule,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    leaders = result['services'][1]
    assert leaders['data_status'] == 'partial'
    assert result['status'] == 'partial'


def test_dashboard_read_path_never_runs_or_writes(monkeypatch):
    _install_ready_sources(monkeypatch)
    forbidden_calls = []

    def forbidden(name):
        def fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(f'forbidden side effect: {name}')
        return fail

    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'create_scanner_run', forbidden('create_scanner_run'))
    monkeypatch.setattr(
        alpha_dashboard.alpha_scanner,
        'run_scanner_realtime_monitor_check',
        forbidden('monitor_check'),
    )
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'run_intraday_watch', forbidden('intraday_watch'))
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_today_snapshot',
        forbidden('pipeline_today'),
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 12, 0, tzinfo=KST),
    )

    assert result['services'][2]['schedule']['phase'] == 'due'
    assert forbidden_calls == []


def test_dashboard_marks_market_phase_without_as_of_as_stale_fallback(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'market_phase', lambda: {
        'phase': 'leader_market',
        'phase_label': '주도주 장세',
        'regime': 'NEUTRAL',
        'breadth': 0.51,
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    market = result['services'][0]
    assert market['data_status'] == 'stale'
    assert market['provenance']['sources'][0]['fallback'] is True
    assert market['provenance']['sources'][0]['freshness'] == 'unknown'


@pytest.mark.parametrize(('service_id', 'hour', 'minute', 'second', 'expected'), [
    ('market_brief', 7, 59, 0, 'upcoming'),
    ('market_brief', 8, 0, 0, 'due'),
    ('market_brief', 8, 14, 59, 'due'),
    ('market_brief', 8, 15, 0, 'elapsed'),
    ('intraday_flow', 8, 59, 0, 'upcoming'),
    ('intraday_flow', 9, 0, 0, 'due'),
    ('intraday_flow', 15, 29, 59, 'due'),
    ('intraday_flow', 15, 30, 0, 'elapsed'),
])
def test_dashboard_uses_exact_schedule_boundaries(
    monkeypatch, service_id, hour, minute, second, expected,
):
    _install_ready_sources(monkeypatch)

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, hour, minute, second, tzinfo=KST),
    )

    service = next(item for item in result['services'] if item['id'] == service_id)
    assert service['schedule']['phase'] == expected


def test_dashboard_hides_unrealized_return_without_dated_close(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:01:00+00:00',
        'phase': {},
        'open_positions': [{
            'symbol': '005930', 'name': '삼성전자',
            'entry_price': 70000, 'target_price': 75600, 'stop_price': 65100,
            'last_close': 71500, 'last_close_date': None,
            'unrealized_pct': 2.14, 'held_trading_days': 2,
        }],
        'pending': [],
        'performance': {'window_days': 30, 'trades': 0, 'open_count': 1},
        'rules': {}, 'disabled': False,
    })

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 12, 0, tzinfo=KST),
    )

    intraday = result['services'][2]
    assert intraday['data_status'] == 'stale'
    assert intraday['items'][0]['unrealized_pct'] is None


def test_dashboard_nulls_malformed_nested_close_date_without_crashing(monkeypatch):
    _install_ready_sources(monkeypatch)
    paper = alpha_dashboard.paper_orchestrator.paper_overview()
    paper['open_positions'].append({
        **paper['open_positions'][0],
        'symbol': '000660',
        'name': 'SK하이닉스',
        'last_close_date': ['2026-08-19'],
    })
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: paper)

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 12, 0, tzinfo=KST),
    )

    intraday = result['services'][2]
    malformed_position = next(
        item for item in intraday['items'] if item['symbol'] == '000660'
    )
    assert intraday['data_status'] == 'partial'
    assert intraday['as_of'] == '2026-08-19'
    assert malformed_position['last_close_date'] is None
    assert malformed_position['unrealized_pct'] is None
    assert intraday['warnings'] == [{
        'section': 'paper_overview',
        'code': 'source_data_invalid',
        'message': 'paper_overview 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    }]


def test_dashboard_marks_trade_signals_stale_from_old_top3_stage(monkeypatch):
    _install_ready_sources(monkeypatch)
    pipeline = alpha_dashboard.pipeline_overview.get_pipeline_operating_snapshot()
    pipeline['generated_at'] = '2026-08-20T08:39:00+09:00'
    pipeline['stages'][0]['updated_at'] = '2026-08-18T05:00:00+00:00'
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda now=None: pipeline,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 15, 20, tzinfo=KST),
    )

    trade_signals = result['services'][3]
    pipeline_source = trade_signals['provenance']['sources'][1]
    assert trade_signals['data_status'] == 'stale'
    assert trade_signals['as_of'] == '2026-08-18T05:00:00+00:00'
    assert pipeline_source['as_of'] == '2026-08-18T05:00:00+00:00'
    assert pipeline_source['freshness'] == 'stale'
    assert result['status'] == 'stale'


def test_dashboard_evaluates_top3_stage_day_after_converting_to_kst(monkeypatch):
    _install_ready_sources(monkeypatch)
    pipeline = alpha_dashboard.pipeline_overview.get_pipeline_operating_snapshot()
    pipeline['stages'][0]['updated_at'] = '2026-08-19T15:30:00+00:00'
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda now=None: pipeline,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    trade_signals = result['services'][3]
    assert trade_signals['data_status'] == 'ready'
    assert trade_signals['provenance']['sources'][1]['freshness'] == 'fresh'


def test_dashboard_keeps_true_zero_top3_stage_ready_without_fabricating_timestamp(monkeypatch):
    _install_ready_sources(monkeypatch)
    pipeline = alpha_dashboard.pipeline_overview.get_pipeline_operating_snapshot()
    pipeline['stages'][0].update({
        'status': 'waiting', 'count': 0, 'updated_at': None,
    })
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda now=None: pipeline,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    trade_signals = result['services'][3]
    pipeline_source = trade_signals['provenance']['sources'][1]
    assert trade_signals['data_status'] == 'ready'
    assert trade_signals['items'][3]['count'] == 0
    assert trade_signals['as_of'] is None
    assert pipeline_source['as_of'] is None
    assert pipeline_source['freshness'] == 'unknown'


def test_dashboard_marks_missing_top3_stage_partial(monkeypatch):
    _install_ready_sources(monkeypatch)
    pipeline = alpha_dashboard.pipeline_overview.get_pipeline_operating_snapshot()
    pipeline['stages'] = []
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda now=None: pipeline,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    trade_signals = result['services'][3]
    assert trade_signals['data_status'] == 'partial'
    assert trade_signals['warnings'] == [{
        'section': 'pipeline_operating_snapshot',
        'code': 'source_data_invalid',
        'message': 'pipeline_operating_snapshot 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    }]
    assert result['status'] == 'partial'


def test_dashboard_marks_undated_nonzero_top3_stage_stale_with_warning(monkeypatch):
    _install_ready_sources(monkeypatch)
    pipeline = alpha_dashboard.pipeline_overview.get_pipeline_operating_snapshot()
    pipeline['stages'][0].update({
        'status': 'complete', 'count': 3, 'updated_at': None,
    })
    monkeypatch.setattr(
        alpha_dashboard.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda now=None: pipeline,
    )

    result = alpha_dashboard.get_alpha_service_dashboard(
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    trade_signals = result['services'][3]
    pipeline_source = trade_signals['provenance']['sources'][1]
    assert trade_signals['data_status'] == 'stale'
    assert pipeline_source['as_of'] is None
    assert pipeline_source['freshness'] == 'unknown'
    assert trade_signals['warnings'] == [{
        'section': 'pipeline_operating_snapshot',
        'code': 'source_freshness_unknown',
        'message': 'pipeline TOP3 기준 시각을 확인할 수 없습니다.',
        'severity': 'warning',
    }]
    assert result['status'] == 'stale'


def test_alpha_dashboard_route_forwards_strict_query_and_disables_cache(admin_client, monkeypatch):
    captured = {}

    def fake_dashboard(**kwargs):
        captured.update(kwargs)
        return {'schema_version': 'mirofish.alpha_service_dashboard.v1', 'services': []}

    monkeypatch.setattr('app.services.mirofish.get_alpha_service_dashboard', fake_dashboard)
    response = admin_client.get(
        '/api/admin/mirofish/alpha-dashboard?candidate_limit=7&outcome_days=60&outcome_limit=12'
    )

    assert response.status_code == 200
    assert captured == {'candidate_limit': 7, 'outcome_days': 60, 'outcome_limit': 12}
    assert 'no-store' in response.headers['Cache-Control']


def test_alpha_dashboard_route_requires_authentication():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-alpha-dashboard-noauth-secret',
    })

    response = app.test_client().get('/api/admin/mirofish/alpha-dashboard')

    assert response.status_code == 401


@pytest.mark.parametrize(('query', 'message'), [
    ('candidate_limit=0', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=21', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=1.5', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=%205%20', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=%2B5', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=true', 'candidate_limit must be an integer between 1 and 20'),
    ('outcome_days=181', 'outcome_days must be an integer between 1 and 180'),
    ('outcome_limit=51', 'outcome_limit must be an integer between 1 and 50'),
])
def test_alpha_dashboard_route_rejects_invalid_query(admin_client, query, message):
    response = admin_client.get(f'/api/admin/mirofish/alpha-dashboard?{query}')

    assert response.status_code == 400
    assert response.get_json() == {'error': 'invalid_query', 'message': message}
    assert 'no-store' in response.headers['Cache-Control']


def test_alpha_dashboard_invalid_query_sets_no_store_at_route_boundary():
    app = Flask(__name__)

    with app.test_request_context(
        '/api/admin/mirofish/alpha-dashboard?candidate_limit=0'
    ):
        response, status = alpha_dashboard_route.alpha_service_dashboard.__wrapped__()

    assert status == 400
    assert 'no-store' in response.headers['Cache-Control']


def test_alpha_dashboard_route_uses_query_defaults(admin_client, monkeypatch):
    captured = {}

    def fake_dashboard(**kwargs):
        captured.update(kwargs)
        return {'schema_version': 'mirofish.alpha_service_dashboard.v1', 'services': []}

    monkeypatch.setattr('app.services.mirofish.get_alpha_service_dashboard', fake_dashboard)

    response = admin_client.get('/api/admin/mirofish/alpha-dashboard')

    assert response.status_code == 200
    assert captured == {'candidate_limit': 5, 'outcome_days': 30, 'outcome_limit': 10}
