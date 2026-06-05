import json

from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import deepseek_client


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def _sample_run():
    return {
        'id': 'mfas_test_123',
        'generated_at': '2026-05-05T00:00:00+00:00',
        'mode': 'deterministic_file_artifacts',
        'source': 'local_marketflow_artifacts',
        'freshness': {'status': 'fresh'},
        'candidates': [
            {
                'rank': 1,
                'symbol': '000001',
                'display_name': 'Alpha One',
                'market': 'KOSPI',
                'alpha_score': 82,
                'risk_score': 20,
                'ranking_score': 73,
                'action': 'BUY_CANDIDATE',
                'horizon': 'swing_5_20d',
                'strategy_tags': ['momentum', 'jongga_setup'],
                'price': {
                    'date': '2026-05-04',
                    'current_price': 1000,
                    'change_rate': 5.2,
                    'volume': 100000,
                    'trading_value': 100000000,
                },
                'evidence': [
                    {'source': 'daily_prices.csv', 'field': 'price_momentum', 'score': 10, 'value': 5.2}
                ],
            },
        ],
    }


def test_deepseek_status_without_key_is_safe(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)

    status = deepseek_client.get_deepseek_status()

    assert status['provider'] == 'deepseek'
    assert status['configured'] is False
    assert status['supported_endpoints']['chat_completions'] == '/chat/completions'


def test_deepseek_models_request_uses_bearer_token(monkeypatch):
    calls = []
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test')

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _FakeResponse(payload={'object': 'list', 'data': [{'id': 'deepseek-v4-flash'}]})

    monkeypatch.setattr(deepseek_client.requests, 'request', fake_request)

    result = deepseek_client.list_models()

    assert result['data'][0]['id'] == 'deepseek-v4-flash'
    assert calls[0][0] == 'GET'
    assert calls[0][1].endswith('/models')
    assert calls[0][2]['headers']['Authorization'] == 'Bearer sk-test'


def test_deepseek_summarizes_scanner_run_as_json(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test')
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({'method': method, 'url': url, 'payload': kwargs.get('json')})
        return _FakeResponse(payload={
            'model': 'deepseek-v4-flash',
            'choices': [{
                'finish_reason': 'stop',
                'message': {
                    'content': json.dumps({
                        'summary_title_ko': '알파 후보 요약',
                        'portfolio_note_ko': '숫자 기반 후보입니다.',
                        'candidates': [{
                            'rank': 1,
                            'symbol': '000001',
                            'display_name': 'Alpha One',
                            'market': 'KOSPI',
                            'action_ko': '매수 후보',
                            'thesis_ko': '모멘텀이 확인됩니다.',
                            'risk_ko': '리스크 점검 필요.',
                            'next_check_ko': '거래대금 지속 확인.',
                        }],
                    }, ensure_ascii=False)
                },
            }],
            'usage': {'total_tokens': 100},
        })

    monkeypatch.setattr(deepseek_client.requests, 'request', fake_request)

    result = deepseek_client.summarize_scanner_run(_sample_run(), limit=1)

    assert result['summary']['candidates'][0]['symbol'] == '000001'
    assert result['usage']['total_tokens'] == 100
    assert captured['method'] == 'POST'
    assert captured['url'].endswith('/chat/completions')
    assert captured['payload']['response_format'] == {'type': 'json_object'}
    assert captured['payload']['thinking'] == {'type': 'disabled'}
    assert '000001' in captured['payload']['messages'][1]['content']


def test_deepseek_rerank_uses_v4_reasoning_overlay(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test')
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({'method': method, 'url': url, 'payload': kwargs.get('json')})
        return _FakeResponse(payload={
            'model': 'deepseek-v4-pro',
            'choices': [{
                'finish_reason': 'stop',
                'message': {
                    'content': json.dumps({
                        'portfolio_note_ko': '증거 충돌이 낮은 후보를 우선합니다.',
                        'items': [{
                            'symbol': '000001',
                            'deepseek_conviction': 88,
                            'ranking_adjustment': 6,
                            'risk_flags': ['낮은 과열'],
                            'positive_evidence': ['다중 소스 확인'],
                            'rationale_ko': '수급과 가격 근거가 동시에 확인됩니다.',
                        }],
                    }, ensure_ascii=False)
                },
            }],
            'usage': {'total_tokens': 321},
        })

    monkeypatch.setattr(deepseek_client.requests, 'request', fake_request)

    result = deepseek_client.rerank_scanner_candidates(_sample_run()['candidates'], limit=1)

    assert result['model'] == 'deepseek-v4-pro'
    assert result['overlay']['items'][0]['symbol'] == '000001'
    assert result['reasoning_effort'] == 'max'
    assert captured['method'] == 'POST'
    assert captured['payload']['temperature'] == 0.0
    assert captured['payload']['thinking'] == {'type': 'enabled'}
    assert captured['payload']['response_format'] == {'type': 'json_object'}
    assert 'bounded KR stock scanner rerank overlay' in captured['payload']['messages'][1]['content']


def test_deepseek_json_parser_accepts_fenced_object(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test')

    def fake_request(method, url, **kwargs):
        return _FakeResponse(payload={
            'model': 'deepseek-v4-pro',
            'choices': [{
                'finish_reason': 'stop',
                'message': {
                    'content': '```json\n{"portfolio_note_ko":"ok","items":[]}\n```'
                },
            }],
        })

    monkeypatch.setattr(deepseek_client.requests, 'request', fake_request)

    result = deepseek_client.rerank_scanner_candidates(_sample_run()['candidates'], limit=1)

    assert result['overlay']['portfolio_note_ko'] == 'ok'


def test_deepseek_summary_telegram_message_preserves_ticker_and_escapes_html():
    message = deepseek_client.build_summary_telegram_message({
        'run_id': 'mfas_test_123',
        'model': 'deepseek-v4-flash',
        'usage': {'total_tokens': 100},
        'summary': {
            'summary_title_ko': '요약 <테스트>',
            'portfolio_note_ko': '알파 > 리스크',
            'candidates': [{
                'rank': 1,
                'symbol': '000001',
                'display_name': 'Alpha <One>',
                'market': 'KOSPI',
                'action_ko': '매수 후보',
                'thesis_ko': '가격 모멘텀이 강합니다.',
                'risk_ko': '과열 여부 확인.',
                'next_check_ko': '거래대금 확인.',
            }],
        },
    })

    assert '<code>000001</code>' in message
    assert 'Alpha &lt;One&gt;' in message
    assert '알파 &gt; 리스크' in message


def test_admin_mirofish_deepseek_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/deepseek/status' in rules
    assert '/api/admin/mirofish/deepseek/scanner-summary' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/deepseek-summary' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/deepseek-summary/telegram' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/artifacts/deepseek_rerank.json' in rules


def test_scanner_deepseek_telegram_route_forces_personal_bot(monkeypatch):
    import app.routes.admin_mirofish as route_module

    app = Flask(__name__)
    calls = []

    monkeypatch.setattr('app.services.mirofish.read_scanner_run', lambda run_id: _sample_run())
    monkeypatch.setattr('app.services.mirofish.build_summary_telegram_message', lambda summary: 'message')

    def fake_send(message, channel=True):
        calls.append({'message': message, 'channel': channel})
        return True

    monkeypatch.setattr('app.utils.scheduler._send_telegram_long', fake_send)

    with app.test_request_context(json={'summary': {'run_id': 'mfas_test_123'}, 'channel': True}):
        response = route_module.send_scanner_deepseek_summary_to_telegram.__wrapped__('mfas_test_123')

    assert response.status_code == 200
    assert calls == [{'message': 'message', 'channel': False}]


def test_scanner_telegram_route_falls_back_when_deepseek_unconfigured(monkeypatch):
    import app.routes.admin_mirofish as route_module

    app = Flask(__name__)
    calls = []

    monkeypatch.setattr('app.services.mirofish.read_scanner_run', lambda run_id: _sample_run())
    monkeypatch.setattr(
        'app.services.mirofish.summarize_scanner_run_with_deepseek',
        lambda *args, **kwargs: (_ for _ in ()).throw(deepseek_client.DeepSeekError('DEEPSEEK_API_KEY is not configured')),
    )

    def fake_send(message, channel=True):
        calls.append({'message': message, 'channel': channel})
        return True

    monkeypatch.setattr('app.utils.scheduler._send_telegram_long', fake_send)

    with app.test_request_context(json={'limit': 1}):
        response = route_module.send_scanner_deepseek_summary_to_telegram.__wrapped__('mfas_test_123')

    payload = response.get_json()
    assert response.status_code == 200
    assert payload['provider'] == 'scanner_fallback'
    assert payload['message_source'] == 'scanner_fallback'
    assert payload['fallback_reason'] == 'DEEPSEEK_API_KEY is not configured'
    assert payload['summary'] is None
    assert calls[0]['channel'] is False
    assert '<code>000001</code>' in calls[0]['message']
