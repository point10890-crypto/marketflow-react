# -*- coding: utf-8 -*-
"""공개 Track Record API — 비로그인 200, 지연·마스킹 규칙, 당일 미노출, Pro 라우트는 여전히 잠김."""
import json
from datetime import date

import pytest

from app import create_app
from app.routes import public_track_record as ptr
from app.utils import json_cache


TODAY = date(2026, 9, 3)   # 목요일


def _archive(dir_, ymd: str, signals):
    payload = {
        'date': f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}',
        'filtered_count': len(signals),
        'signals': signals,
        'by_grade': {},
        'claude_picks': {'picks': [{'stock_name': '비공개 픽'}]},
    }
    (dir_ / f'jongga_v2_results_{ymd}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _sig(code, name, grade, chg, date_iso, total=9):
    return {
        'stock_code': code, 'stock_name': name, 'market': 'KOSPI', 'grade': grade,
        'signal_date': date_iso, 'change_pct': chg, 'entry_price': 10000,
        'score': {'total': total, 'news': 3, 'llm_reason': '비공개 사유'},
        'news_items': [{'title': '비공개 뉴스'}],
    }


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    json_cache.invalidate()
    monkeypatch.setattr(ptr, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ptr, '_today', lambda: TODAY)
    # 오늘(9/3) — 절대 나가면 안 된다
    _archive(tmp_path, '20260903', [_sig('005930', '삼성전자', 'S', 5.1, '2026-09-03')])
    # 어제(9/2 수) — 거래일 1일 경과 → 공개 + 마스킹
    _archive(tmp_path, '20260902', [_sig('000660', 'SK하이닉스', 'A', 3.2, '2026-09-02'),
                                    _sig('035420', 'NAVER', 'B', 1.1, '2026-09-02')])
    # 8/27(목) — 이후 주중 8/28, 8/31, 9/1, 9/2, 9/3 = 5일 → 마스킹 해제
    _archive(tmp_path, '20260827', [_sig('112610', '씨에스윈드', 'S', 18.5, '2026-08-27')])
    # 8/25(화) — 7 거래일 → 해제 + 사후 추적 있음
    _archive(tmp_path, '20260825', [_sig('009150', '삼성전기', 'A', 9.2, '2026-08-25')])
    (tmp_path / 'cumulative_performance.json').write_text(json.dumps({'signals': [
        {'stock_code': '009150', 'signal_date': '2026-08-25', 'outcome': 'TARGET_HIT',
         'outcome_date': '2026-08-28', 'roi_pct': 5.0, 'hold_roi_pct': 6.4, 'days_held': 3, 'max_high_pct': 7.1},
        # 가격 데이터가 없어 평가되지 않은 행 — pending 이어야 한다
        {'stock_code': '112610', 'signal_date': '2026-08-27', 'outcome': 'OPEN',
         'outcome_date': None, 'roi_pct': 0.0, 'hold_roi_pct': 0.0, 'days_held': 0, 'max_high_pct': 0},
    ]}), encoding='utf-8')
    yield tmp_path
    json_cache.invalidate()


@pytest.fixture()
def app(data_dir):
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'public-track-record-test',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def test_public_route_is_open_and_shared_cacheable(client):
    r = client.get('/api/public/track-record')
    assert r.status_code == 200
    assert r.headers['Cache-Control'] == 'public, max-age=600'
    body = r.get_json()
    assert body['schema_version'] == 'marketflow.public_track_record.v1'
    assert body['sample_size'] == 4
    assert body['methodology']['delay'] and body['disclaimer']


def test_pro_performance_route_still_gated(client):
    assert client.get('/api/kr/jongga-v2/performance').status_code in (401, 403)
    assert client.get('/api/kr/jongga-v2/latest').status_code in (401, 403)


def test_today_signal_never_leaks(client):
    body = client.get('/api/public/track-record').get_json()
    body.pop('generated_at')   # 서버 시각 — 데이터가 아니다
    dumped = json.dumps(body, ensure_ascii=False)
    assert '2026-09-03' not in dumped
    assert '삼성전자' not in dumped and '005930' not in dumped
    assert body['as_of'] == '2026-09-02'
    assert [d['date'] for d in body['days']] == ['2026-09-02', '2026-08-27', '2026-08-25']


def test_masking_rules(client):
    body = client.get('/api/public/track-record').get_json()
    rows = {r['date'] + ':' + r['grade']: r for r in body['signals']}
    young = rows['2026-09-02:A']
    assert young['masked'] is True
    assert young['stock_name'] == 'SK**' and young['stock_code'] is None
    assert rows['2026-09-02:B']['stock_name'] == 'NA**'
    old = rows['2026-08-27:S']
    assert old['masked'] is False
    assert old['stock_name'] == '씨에스윈드' and old['stock_code'] == '112610'
    assert body['masked_count'] == 2
    # 내부 필드는 어떤 행에도 없다
    dumped = json.dumps(body, ensure_ascii=False)
    for secret in ('비공개 사유', '비공개 뉴스', '비공개 픽', 'entry_price'):
        assert secret not in dumped


def test_forward_outcome_only_from_tracking_file(client):
    body = client.get('/api/public/track-record').get_json()
    rows = {r['date']: r for r in body['signals']}
    evaluated = rows['2026-08-25']
    assert evaluated['verification'] == 'closed'
    assert evaluated['forward_return'] == 5.0
    assert evaluated['forward']['outcome'] == 'TARGET_HIT'
    pending = rows['2026-08-27']
    assert pending['verification'] == 'pending' and pending['forward_return'] is None
    assert rows['2026-09-02']['verification'] == 'pending'
    v = body['verification']
    assert v == {'evaluated': 1, 'pending': 3, 'closed': 1, 'open': 0, 'wins': 1, 'losses': 0,
                 'win_rate': 100.0, 'avg_roi_pct': 5.0, 'avg_hold_roi_pct': 6.4}
    assert body['grade_stats']['A'] == {'count': 2, 'closed': 1, 'wins': 1, 'win_rate': 100.0, 'avg_roi_pct': 5.0}
    assert body['grade_stats']['S']['win_rate'] is None


def test_window_caps_at_60_visible_days(tmp_path, monkeypatch):
    json_cache.invalidate()
    from datetime import timedelta
    day = TODAY - timedelta(days=1)
    made = 0
    while made < 75:
        if day.weekday() < 5:
            _archive(tmp_path, day.strftime('%Y%m%d'), [_sig('000001', '종목', 'B', 1.0, day.isoformat())])
            made += 1
        day -= timedelta(days=1)
    out = ptr.build_track_record(str(tmp_path), today=TODAY)
    assert out['days_count'] == 60 and out['sample_size'] == 60
    assert out['date_range']['to'] == '2026-09-02'
    json_cache.invalidate()


def test_trading_day_delay_counts_weekdays_only():
    # 금요일 신호 → 토요일엔 0 (비공개), 월요일엔 1 (공개), 다음주 금요일엔 5 (마스킹 해제)
    fri = date(2026, 8, 28)
    assert ptr._trading_days_between(fri, date(2026, 8, 29)) == 0
    assert ptr._trading_days_between(fri, date(2026, 8, 31)) == 1
    assert ptr._trading_days_between(fri, date(2026, 9, 4)) == 5
    assert ptr.mask_name('삼성전자') == '삼성**'
    assert ptr.mask_name('SK') == 'S**'
    assert ptr.mask_name('') == '**'
