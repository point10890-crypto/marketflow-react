from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import mcp_resource_catalog


def test_mcp_resource_catalog_prioritizes_alpha_relevant_sources():
    catalog = mcp_resource_catalog.list_mcp_resource_catalog(include_deferred=False)
    resource_ids = [item['id'] for item in catalog]

    assert resource_ids[:3] == ['kis_mcp', 'korea_stock_mcp', 'alpha_vantage_mcp']
    assert catalog[0]['recommended_for_alpha'] is True
    assert catalog[0]['read_only_required'] is True
    assert 'order' in catalog[0]['blocked_capabilities']
    assert 'softr_portal' not in resource_ids


def test_mcp_source_gap_evaluation_detects_required_coverage():
    scanner_run = {
        'id': 'mfas_test',
        'source_files': [
            'daily_prices.csv',
            'KIS API: inquire-price',
            'KIS API investor flow',
            'all_institutional_trend_data.csv',
            'OpenDART filing cache',
        ],
        'candidates': [
            {
                'symbol': '005930',
                'replay_context': {
                    'data_sources': ['DART', 'KIS API', 'capital_flow_confirmation'],
                },
            }
        ],
        'performance_advisory': {'hit_rate_pct': 58.2},
    }
    workflow = {
        'id': 'mcp_test',
        'top3': [
            {
                'symbol': '005930',
                'graphrag': {'entity_count': 12, 'mode': 'knowledge_graph'},
                'outcome': {'forward_return_pct': 3.2},
            }
        ],
        'outcome_summary': {'hit_rate_pct': 61.0},
    }

    gaps = mcp_resource_catalog.evaluate_mcp_source_gaps(
        scanner_run=scanner_run,
        workflow=workflow,
    )

    assert gaps['readiness'] == 'ready'
    assert gaps['required_missing'] == 0
    assert gaps['required_partial'] == 0
    assert gaps['required_covered'] == gaps['required_total']
    requirements = {item['id']: item for item in gaps['requirements']}
    assert requirements['kr_live_price']['status'] == 'covered'
    assert requirements['capital_flow']['status'] == 'covered'
    assert requirements['filing_fundamental']['status'] == 'covered'
    assert requirements['outcome_memory']['status'] == 'covered'


def test_mcp_source_gap_evaluation_blocks_when_required_roles_are_missing():
    scanner_run = {
        'id': 'mfas_weak',
        'source_files': ['daily_prices.csv', 'ticker_to_yahoo_map.csv'],
    }

    gaps = mcp_resource_catalog.evaluate_mcp_source_gaps(scanner_run=scanner_run)
    plan = mcp_resource_catalog.build_mcp_adoption_plan(source_gaps=gaps)

    assert gaps['readiness'] == 'blocked'
    assert gaps['required_missing'] >= 2
    assert any(item['id'] == 'kis_mcp' for item in plan['immediate'])
    assert any(item['id'] == 'korea_stock_mcp' for item in plan['immediate'])


def test_mcp_resource_snapshot_is_redacted_and_machine_readable():
    snapshot = mcp_resource_catalog.build_mcp_resource_snapshot(
        scanner_run=False,
        workflow=False,
        include_deferred=True,
    )

    assert snapshot['schema_version'] == mcp_resource_catalog.CATALOG_VERSION
    assert snapshot['rules']['orders_blocked'] is True
    assert snapshot['rules']['secrets_redacted'] is True
    assert snapshot['catalog_count'] >= 6
    assert snapshot['source_gaps']['readiness'] == 'unknown'
    assert 'api_key' not in str(snapshot).lower()


def test_admin_mirofish_mcp_resource_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/mcp/resources' in rules
    assert '/api/admin/mirofish/mcp/resources/<resource_id>' in rules
