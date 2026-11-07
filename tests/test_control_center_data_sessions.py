"""US data remains current until the next completed-session release is due."""
from datetime import datetime
import json

import pytest

from app.services.control_center import contracts, local_checks
from app.services.control_center.model import KST


def result(tmp_path, now, stamp, scheduled='07:00'):
    path = tmp_path / 'data.json'
    path.write_text(json.dumps({'timestamp': stamp, 'rows': [1]}), encoding='utf8')
    item = {'id': 'us', 'path': str(path), 'field': 'timestamp', 'max_age_hours': 30,
            'calendar': 'us_post_close', 'scheduled_time_kst': scheduled, 'grace_minutes': 120}
    return local_checks.check_data([item], datetime.fromisoformat(now).replace(tzinfo=KST))[0]


@pytest.mark.parametrize('now,stamp,expected', [
    ('2026-11-08T20:00:00', '2026-11-07T07:10:00', 'ok'),
    ('2026-11-09T23:00:00', '2026-11-07T07:10:00', 'ok'),
    ('2026-11-10T08:59:00', '2026-11-07T07:10:00', 'ok'),
    ('2026-11-10T09:00:00', '2026-11-07T07:10:00', 'warn'),
    ('2026-11-07T09:00:00', '2026-11-06T07:10:00', 'warn'),
    ('2026-11-09T23:00:00', '2026-11-06T07:10:00', 'warn'),
    ('2026-11-07T09:00:00', '2026-11-05T07:10:00', 'fail'),
    ('2026-11-07T08:59:00', '2026-11-06T07:10:00', 'ok'),
    ('2026-11-07T08:59:00', '2026-11-05T07:10:00', 'warn'),
    ('2026-11-07T09:00:00', '2026-11-08T07:10:00', 'unknown'),
    ('2026-11-07T09:00:00', 'invalid', 'unknown'),
])
def test_session_deadlines_preserve_weekend_and_stale_baselines(tmp_path, now, stamp, expected):
    assert result(tmp_path, now, stamp).status == expected


@pytest.mark.parametrize('now,stamp,expected', [
    # Independence Day observed July 3: July 2 is the latest completed session.
    ('2026-07-06T20:00:00', '2026-07-03T07:10:00', 'ok'),
    ('2026-07-06T20:00:00', '2026-07-02T07:10:00', 'warn'),
    # NY16:00 becomes KST06:00 in winter and KST05:00 in summer.
    ('2026-03-07T10:00:00', '2026-03-07T05:59:00', 'warn'),
    ('2026-03-07T10:00:00', '2026-03-07T06:01:00', 'ok'),
    ('2026-03-10T10:00:00', '2026-03-10T04:59:00', 'warn'),
    ('2026-03-10T10:00:00', '2026-03-10T05:01:00', 'ok'),
    ('2026-11-03T10:00:00', '2026-11-03T05:59:00', 'warn'),
    ('2026-11-03T10:00:00', '2026-11-03T06:01:00', 'ok'),
])
def test_exchange_holidays_and_dst(tmp_path, now, stamp, expected):
    assert result(tmp_path, now, stamp).status == expected


def test_vcp_has_its_own_release_deadline(tmp_path):
    assert result(tmp_path, '2026-11-07T09:59:00', '2026-11-06T08:10:00', '08:00').status == 'ok'
    assert result(tmp_path, '2026-11-07T10:00:00', '2026-11-06T08:10:00', '08:00').status == 'warn'


def test_reports_actual_age_and_expected_session_without_rewriting_source(tmp_path):
    checked = result(tmp_path, '2026-11-09T23:00:00', '2026-11-07T07:10:00')
    assert checked.value == 63.83
    assert checked.data['expected_session'] == '2026-11-06'
    assert checked.data['expected_release_at'] == '2026-11-07T07:00:00+09:00'
    assert checked.data['release_deadline_at'] == '2026-11-07T09:00:00+09:00'
    assert checked.data['data_timestamp'] == '2026-11-07T07:10:00+09:00'
    assert json.loads((tmp_path / 'data.json').read_text())['timestamp'] == '2026-11-07T07:10:00'


@pytest.mark.parametrize('scheduled', ['25:00', 'invalid', '05:00'])
def test_invalid_release_contract_cannot_report_healthy(tmp_path, scheduled):
    checked = result(tmp_path, '2026-11-09T23:00:00', '2026-11-07T07:10:00', scheduled)
    assert checked.status == 'unknown'


def test_only_four_requested_us_contracts_use_explicit_post_close_calendar():
    items = {item['id']: item for item in contracts.load()['data']}
    for key in ('us_briefing', 'us_heatmap', 'us_smart_money', 'us_vcp'):
        assert items[key]['calendar'] == 'us_post_close'
        assert items[key]['scheduled_time_kst'] == ('08:00' if key == 'us_vcp' else '07:00')
        assert items[key]['grace_minutes'] == 120
        assert items[key]['max_age_hours'] == 30
    assert items['us_earnings']['calendar'] == 'us_trading'
    assert items['kr_vcp']['calendar'] == 'kr_trading'
