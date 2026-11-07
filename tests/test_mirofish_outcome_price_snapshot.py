"""One feedback cycle shares one price read without changing replay results."""
import json
import builtins
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.mirofish import autonomous_mcp as feedback
from app.services.mirofish import outcome_tracker as outcomes


@pytest.fixture
def replay(tmp_path, monkeypatch):
    price_path = tmp_path / 'prices.csv'
    rows = ['ticker,date,current_price,high,low,volume']
    for symbol, multiplier in [('000001', 1), ('000002', -1), ('UNUSED', 3)]:
        for day in range(1, 27):
            price = 100 + day * multiplier
            rows.append(f'{symbol},2026-05-{day:02},{price},{price + 2},{price - 2},1000')
    price_path.write_text('\n'.join(rows), encoding='utf-8')
    monkeypatch.setattr(outcomes, 'PRICE_HISTORY_PATH', str(price_path))
    monkeypatch.setattr(outcomes, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(feedback, 'LEARNING_FEEDBACK_PATH', tmp_path / 'feedback.json')
    monkeypatch.setattr(feedback, '_audit', lambda *args, **kwargs: None)
    monkeypatch.setattr(feedback.learning_policy, 'build_learning_policy', lambda *args, **kwargs: {})

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 8, tzinfo=timezone.utc)

    monkeypatch.setattr(outcomes, 'datetime', FrozenDatetime)
    monkeypatch.setattr(feedback, 'datetime', FrozenDatetime)
    records = []
    for index in range(50):
        symbol = ['000001', '000002', 'MISSING'][index % 3]
        candidate = {'symbol': symbol, 'rank': index % 3 + 1, 'price': {'date': '2026-05-01', 'current_price': 100},
                     'strategy_tags': ['momentum'], 'alpha_score': 80, 'risk_score': 20}
        if index % 10 in (1, 2):
            candidate['price']['date'] = '2026-05-24' if index % 10 == 1 else '2026-05-15'
        if index % 10 == 3:
            candidate['price']['current_price'] = 0
        records.append({'id': f'wfmcp_snapshot_{index:03}', 'status': 'completed',
                        'analysis_runs': [{'symbol': symbol, 'candidate': candidate}]})
    monkeypatch.setattr(feedback.workflow, 'list_workflows', lambda limit: [{'id': r['id']} for r in records[:limit]])
    monkeypatch.setattr(feedback.workflow, 'read_workflow', lambda identifier: next(r for r in records if r['id'] == identifier))
    return tmp_path, price_path, records


def test_fifty_workflow_batch_reads_once_and_matches_individual_replay_exactly(replay, monkeypatch):
    root, price_path, records = replay
    expected = {record['id']: outcomes.refresh_workflow_outcomes(record['id'], workflow=record) for record in records}
    expected_feedback = feedback._build_learning_feedback(
        [{'workflow_id': key, 'status': value['status'], 'summary': value['summary']} for key, value in expected.items()],
        [item for value in expected.values() for item in value['items']], [],
    )
    real_load = outcomes._load_price_history
    reads = []
    def load(path, symbols):
        reads.append(set(symbols))
        return real_load(path, symbols)
    monkeypatch.setattr(outcomes, '_load_price_history', load)
    csv_opens = []
    def open_file(path, *args, **kwargs):
        if Path(path) == price_path:
            csv_opens.append(path)
        return builtins.open(path, *args, **kwargs)
    monkeypatch.setattr(outcomes, 'open', open_file, raising=False)
    actual_feedback = feedback.refresh_learning_feedback_trusted(limit=50)
    assert actual_feedback == expected_feedback
    assert len(reads) == 1
    assert len(csv_opens) == 1
    assert reads[0] == {'000001', '000002', 'MISSING'}
    for identifier, previous in expected.items():
        saved = json.loads((root / 'workflows' / identifier / 'outcomes.json').read_text())
        assert saved == previous
        assert saved['price_history']['symbols_loaded'] == 1
    assert {'evaluated', 'partial', 'pending', 'missing_entry'} <= {
        item['status'] for value in expected.values() for item in value['items']
    }


def test_empty_or_unfinished_batch_does_not_read_prices(replay, monkeypatch):
    _, _, records = replay
    for record in records:
        record['status'] = 'running'
    monkeypatch.setattr(outcomes, '_load_price_history', lambda *a: pytest.fail('no completed workflows'))
    result = feedback.refresh_learning_feedback_trusted(limit=50)
    assert result['workflow_count'] == 0 and result['errors'] == []


def test_one_failed_workflow_keeps_previous_file_and_other_completed_results(replay, monkeypatch):
    root, _, records = replay
    failure_id = records[1]['id']
    old = outcomes.refresh_workflow_outcomes(failure_id, workflow=records[1])
    original_bytes = (root / 'workflows' / failure_id / 'outcomes.json').read_bytes()
    real_write = outcomes.write_json_atomic
    def write(path, data, **kwargs):
        if failure_id in str(path):
            raise OSError('injected workflow write failure')
        return real_write(path, data, **kwargs)
    monkeypatch.setattr(outcomes, 'write_json_atomic', write)
    first = feedback.refresh_learning_feedback_trusted(limit=3)
    assert first['workflow_count'] == 2 and len(first['errors']) == 1
    assert first['errors'][0]['workflow_id'] == failure_id
    assert (root / 'workflows' / failure_id / 'outcomes.json').read_bytes() == original_bytes
    completed = {r['id']: (root / 'workflows' / r['id'] / 'outcomes.json').read_bytes() for r in (records[0], records[2])}
    monkeypatch.setattr(outcomes, 'write_json_atomic', real_write)
    recovered = feedback.refresh_learning_feedback_trusted(limit=3)
    assert recovered['workflow_count'] == 3 and recovered['errors'] == []
    assert outcomes.read_workflow_outcomes(failure_id) == old
    for identifier, content in completed.items():
        assert (root / 'workflows' / identifier / 'outcomes.json').read_bytes() == content


def test_snapshot_source_change_aborts_before_overwriting_completed_outcome(replay):
    root, price_path, records = replay
    record = records[0]
    previous = outcomes.refresh_workflow_outcomes(record['id'], workflow=record)
    snapshot = outcomes.load_price_history_snapshot(['000001'])
    price_path.write_text(price_path.read_text() + '\n000001,2026-05-27,150,151,149,1000', encoding='utf-8')
    with pytest.raises(RuntimeError, match='price_history_changed'):
        outcomes.refresh_workflow_outcomes(record['id'], workflow=record, price_history_snapshot=snapshot)
    assert outcomes.read_workflow_outcomes(record['id']) == previous


def test_direct_refresh_remains_compatible_and_uses_custom_replay_parameters(replay):
    _, _, records = replay
    direct = outcomes.refresh_workflow_outcomes(records[0]['id'], workflow=records[0],
                                               horizons=(1, 3), target_return_pct=2.0, stop_loss_pct=-2.0)
    snapshot = outcomes.load_price_history_snapshot(['000001', '000002'])
    shared = outcomes.refresh_workflow_outcomes(records[0]['id'], workflow=records[0],
                                               horizons=(1, 3), target_return_pct=2.0, stop_loss_pct=-2.0,
                                               price_history_snapshot=snapshot)
    assert shared == direct


def test_changed_source_during_union_read_does_not_replace_any_outcome(replay, monkeypatch):
    root, price_path, records = replay
    record = records[0]
    old = outcomes.refresh_workflow_outcomes(record['id'], workflow=record)
    real_load = outcomes._load_price_history
    def load_then_change(path, symbols):
        history = real_load(path, symbols)
        price_path.write_text(price_path.read_text() + '\n', encoding='utf-8')
        return history
    monkeypatch.setattr(outcomes, '_load_price_history', load_then_change)
    with pytest.raises(RuntimeError, match='price_history_changed_during_snapshot'):
        feedback.refresh_learning_feedback_trusted(limit=3)
    assert outcomes.read_workflow_outcomes(record['id']) == old
    assert not (root / 'workflows' / records[1]['id'] / 'outcomes.json').exists()


def test_snapshot_rejects_another_source_or_unloaded_symbols(replay):
    root, _, records = replay
    snapshot = outcomes.load_price_history_snapshot(['000001'])
    with pytest.raises(ValueError, match='snapshot_missing_symbols'):
        outcomes.refresh_workflow_outcomes(records[1]['id'], workflow=records[1], price_history_snapshot=snapshot)
    with pytest.raises(ValueError, match='snapshot_path_mismatch'):
        outcomes.refresh_workflow_outcomes(records[0]['id'], workflow=records[0],
                                          price_history_path=str(root / 'another.csv'), price_history_snapshot=snapshot)


def test_missing_price_file_preserves_direct_metadata_and_pending_result(replay):
    _, price_path, records = replay
    price_path.unlink()
    direct = outcomes.refresh_workflow_outcomes(records[0]['id'], workflow=records[0])
    snapshot = outcomes.load_price_history_snapshot(['000001', '000002'])
    shared = outcomes.refresh_workflow_outcomes(records[0]['id'], workflow=records[0], price_history_snapshot=snapshot)
    assert shared == direct
    assert shared['price_history']['exists'] is False
    assert shared['price_history']['symbols_loaded'] == 0


def test_source_change_after_shared_load_preserves_previous_feedback_and_fails_action(replay, monkeypatch):
    from app.services.mirofish import agent_actions
    root, price_path, _ = replay
    previous = b'{"service":"previous-valid-feedback"}'
    (root / 'feedback.json').write_bytes(previous)
    real_load = outcomes.load_price_history_snapshot
    def load_then_change(*args, **kwargs):
        snapshot = real_load(*args, **kwargs)
        price_path.write_text(price_path.read_text() + '\n', encoding='utf-8')
        return snapshot
    monkeypatch.setattr(outcomes, 'load_price_history_snapshot', load_then_change)
    result = agent_actions.execute_decisions([{'action': 'refresh_outcomes'}], dry_run=False)
    assert result[0]['status'] == 'error'
    assert 'price_history_changed' in result[0]['reason']
    assert (root / 'feedback.json').read_bytes() == previous


def test_source_change_mid_batch_preserves_successful_workflow_and_previous_feedback(replay, monkeypatch):
    root, price_path, records = replay
    feedback.refresh_learning_feedback_trusted(limit=3)
    previous_feedback = (root / 'feedback.json').read_bytes()
    previous_files = {record['id']: (root / 'workflows' / record['id'] / 'outcomes.json').read_bytes()
                      for record in records[:3]}
    calls = []
    real_refresh = outcomes.refresh_workflow_outcomes
    def refresh_then_change(identifier, **kwargs):
        result = real_refresh(identifier, **kwargs)
        calls.append(identifier)
        if len(calls) == 1:
            price_path.write_text(price_path.read_text() + '\n', encoding='utf-8')
        return result
    monkeypatch.setattr(outcomes, 'refresh_workflow_outcomes', refresh_then_change)
    with pytest.raises(RuntimeError, match='price_history_changed'):
        feedback.refresh_learning_feedback_trusted(limit=3)
    assert calls == [records[0]['id']]
    assert (root / 'feedback.json').read_bytes() == previous_feedback
    for identifier, content in previous_files.items():
        assert (root / 'workflows' / identifier / 'outcomes.json').read_bytes() == content
