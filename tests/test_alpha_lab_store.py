from datetime import datetime, timezone
from copy import deepcopy

import pytest

from app.services.mirofish.alpha_lab import store


NOW = '2026-10-04T03:00:00Z'


def bars(end=14):
    return [dict(date=f'2026-09-{i+1:02}', open=100., high=101., low=99., close=100., volume=100.)
            for i in range(end)]


def candidate():
    return dict(symbol='005930', name='삼성전자', strategy_id='momentum', score=1., last_close=100.,
                plan=dict(entry_price=100., stop_price=96., target_price=108., loss_fraction=.04),
                risk=dict(weight=0., status='held', reasons=['research_only'], p=None, kelly_raw=None), reasons=[])


def report():
    return dict(schema_version=1, mode='research', as_of=NOW, candidates=[candidate()],
                provenance=dict(price_basis='provider_reported_unverified'),
                forward=dict(decisions=0, matured=0, win_rate=None, mean_net_return=None))


def test_freezes_first_decision_and_only_future_after_actual_decision_day(tmp_path):
    prices = {'005930': bars()}
    first = store.observe_and_freeze(tmp_path, report(), prices, now=NOW)
    assert first['matured'] == 0
    changed = report(); changed['candidates'][0]['score'] = 99.
    store.observe_and_freeze(tmp_path, changed, prices, now=NOW)
    journal = store.read_journal(tmp_path)
    assert len(journal['decisions']) == 1
    assert journal['decisions'][0]['candidates'][0]['score'] == 1.
    # A trade that happened after old price data but before today's decision is not prospective.
    prices['005930'].append(dict(date='2026-10-02', open=100., high=120., low=99., close=110., volume=100.))
    assert store.observe_and_freeze(tmp_path, report(), prices, now=NOW)['matured'] == 0
    prices['005930'].append(dict(date='2026-10-05', open=100., high=110., low=99., close=108., volume=100.))
    observed = store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-05T09:00:00Z')
    assert observed['matured'] == 1
    assert observed['win_rate'] == 1.
    assert store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]['entry_date'] == '2026-10-05'


def test_source_revision_blocks_observation_and_tampering_is_rejected(tmp_path):
    prices = {'005930': bars()}
    store.observe_and_freeze(tmp_path, report(), prices, now=NOW)
    prices['005930'][-1]['close'] = 101.
    store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-05T09:00:00Z')
    assert store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]['status'] == 'source_revision'
    path = tmp_path / 'forward.json'
    content = path.read_text(encoding='utf-8'); path.write_text(content.replace('삼성전자', 'FAKE'), encoding='utf-8')
    with pytest.raises(ValueError, match='integrity'):
        store.read_journal(tmp_path)


def test_zero_volume_next_open_is_unfilled_not_retried(tmp_path):
    prices = {'005930': bars()}; store.observe_and_freeze(tmp_path, report(), prices, now=NOW)
    prices['005930'].extend([dict(date='2026-10-05', open=100., high=110., low=99., close=108., volume=0.),
                              dict(date='2026-10-06', open=100., high=110., low=99., close=108., volume=100.)])
    assert store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-06T09:00:00Z')['matured'] == 0
    assert store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]['status'] == 'unfilled'


def test_status_corruption_failure_and_interruption_preserve_previous_report(tmp_path):
    store.publish(tmp_path, report(), now=NOW)
    store.set_running(tmp_path, now=NOW)
    assert store.read_status(tmp_path, now=NOW)['report'] == report()
    later = '2026-10-04T04:00:00Z'
    status = store.read_status(tmp_path, now=later)
    assert status['state'] == 'failed'
    assert status['error'] == 'scan_interrupted'
    store.set_failure(tmp_path, now=later)
    assert store.read_status(tmp_path, now=later)['report'] == report()
    (tmp_path / 'status.json').write_text('{broken', encoding='utf-8')
    assert store.read_status(tmp_path, now=later)['state'] == 'failed'


def test_publication_rejects_nonfinite_without_destroying_report(tmp_path):
    store.publish(tmp_path, report(), now=NOW)
    broken = report(); broken['candidates'][0]['score'] = float('nan')
    with pytest.raises(ValueError):
        store.publish(tmp_path, broken, now=NOW)
    assert store.read_status(tmp_path, now=NOW)['report'] == report()

def _closed_forward(root):
    prices = {'005930': bars()}
    store.observe_and_freeze(root, report(), prices, now=NOW)
    prices['005930'].append(dict(date='2026-10-05', open=100., high=110., low=99., close=108., volume=100.))
    store.observe_and_freeze(root, report(), prices, now='2026-10-05T09:00:00Z')
    return prices, deepcopy(store.read_journal(root)['decisions'][0]['outcomes'][0])


def test_closed_outcome_freezes_consumed_bars_and_records_revision_separately(tmp_path):
    prices, original = _closed_forward(tmp_path)
    prices['005930'][-1].update(high=101., low=95., close=100.)
    summary = store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-06T09:00:00Z')
    observed = store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]
    assert observed['net_return'] == original['net_return']
    assert observed['status'] == 'closed'
    assert observed['result_sha256'] == original['result_sha256']
    assert observed['consumed_ohlcv'] == original['consumed_ohlcv']
    assert observed['source_revisions']
    assert summary['matured'] == 0 and summary['counts']['source_revision'] >= 1
    assert summary['excluded_revised_closed'] == 1


def test_closed_result_survives_irrelevant_later_missing_sessions(tmp_path):
    prices, original = _closed_forward(tmp_path)
    prices['005930'].append(dict(date='2026-10-07', open=108., high=109., low=107., close=108., volume=100.))
    prices['000660'] = [dict(date='2026-10-06', open=100., high=101., low=99., close=100., volume=100.)]
    summary = store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-07T09:00:00Z')
    observed = store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]
    assert observed['net_return'] == original['net_return']
    assert observed['status'] == 'closed'
    assert summary['matured'] == 1


def test_terminal_unfilled_does_not_retroactively_gain_an_entry(tmp_path):
    prices = {'005930': bars()}
    store.observe_and_freeze(tmp_path, report(), prices, now=NOW)
    prices['005930'].append(dict(date='2026-10-05', open=100., high=110., low=99., close=108., volume=0.))
    store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-05T09:00:00Z')
    original = deepcopy(store.read_journal(tmp_path)['decisions'][0]['outcomes'][0])
    prices['005930'][-1]['volume'] = 100.
    store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-06T09:00:00Z')
    observed = store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]
    assert observed['status'] == 'unfilled' and observed['net_return'] is None
    assert observed['result_sha256'] == original['result_sha256']
    assert observed['source_revisions']


def test_outcome_and_revision_metadata_tampering_are_rejected(tmp_path):
    import json
    _closed_forward(tmp_path)
    path = tmp_path / 'forward.json'
    pristine = json.loads(path.read_text(encoding='utf-8'))
    for field, value in (('net_return', 999.), ('source_revisions', [{'reason': 'hidden_revision'}])):
        changed = deepcopy(pristine)
        changed['decisions'][0]['outcomes'][0][field] = value
        path.write_text(json.dumps(changed), encoding='utf-8')
        with pytest.raises(ValueError, match='integrity'):
            store.read_journal(tmp_path)
    path.write_text(json.dumps(pristine), encoding='utf-8')

def test_journal_decision_removal_is_not_accepted_as_a_valid_history(tmp_path):
    import json
    _closed_forward(tmp_path)
    path = tmp_path / 'forward.json'
    changed = json.loads(path.read_text(encoding='utf-8'))
    changed['decisions'] = []
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ValueError, match='integrity'):
        store.read_journal(tmp_path)


def test_open_entry_revision_does_not_reprice_or_close_the_observed_result(tmp_path):
    prices = {'005930': bars()}
    store.observe_and_freeze(tmp_path, report(), prices, now=NOW)
    prices['005930'].append(dict(date='2026-10-05', open=100., high=101., low=99., close=100., volume=100.))
    store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-05T09:00:00Z')
    original = deepcopy(store.read_journal(tmp_path)['decisions'][0]['outcomes'][0])
    assert original['status'] == 'open'
    prices['005930'][-1].update(open=101., high=102., low=100., close=101.)
    prices['005930'].append(dict(date='2026-10-06', open=101., high=110., low=100., close=108., volume=100.))
    summary = store.observe_and_freeze(tmp_path, report(), prices, now='2026-10-06T09:00:00Z')
    observed = store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]
    assert observed['status'] == 'open' and observed['net_return'] is None
    assert observed['result_sha256'] == original['result_sha256']
    assert observed['consumed_ohlcv'] == original['consumed_ohlcv']
    assert observed['source_revisions']
    assert summary['matured'] == 0


def test_missing_already_observed_entry_defers_open_result_until_quotes_return(tmp_path):
    prices = {'005930': bars()}
    store.observe_and_freeze(tmp_path, report(), prices, now=NOW)
    entry = dict(date='2026-10-05', open=100., high=101., low=99., close=100., volume=100.)
    observation = report(); observation['candidates'] = []
    prices['005930'].append(entry)
    store.observe_and_freeze(tmp_path, observation, prices, now='2026-10-05T09:00:00Z')
    original = deepcopy(store.read_journal(tmp_path)['decisions'][0]['outcomes'][0])
    exit_bar = dict(date='2026-10-06', open=100., high=110., low=99., close=108., volume=100.)
    prices['005930'] = bars() + [exit_bar]
    summary = store.observe_and_freeze(tmp_path, observation, prices, now='2026-10-06T09:00:00Z')
    observed = store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]
    assert observed['status'] == 'open' and observed['net_return'] is None
    assert observed['result_sha256'] == original['result_sha256']
    assert summary['matured'] == 0
    prices['005930'] = bars() + [entry, exit_bar]
    summary = store.observe_and_freeze(tmp_path, observation, prices, now='2026-10-07T09:00:00Z')
    assert store.read_journal(tmp_path)['decisions'][0]['outcomes'][0]['status'] == 'closed'
    assert summary['matured'] == 1
