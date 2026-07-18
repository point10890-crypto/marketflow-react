import json

from app.services.mirofish.tradingagents import learning


def _analysis(symbol='005930', stance='bullish', verdict='BUY'):
    return {
        'symbol': symbol,
        'method': 'mixed',
        'analyst_reports': [
            {'role': 'technical', 'stance': stance, 'score': 35},
            {'role': 'fundamentals', 'stance': 'neutral', 'score': 2},
        ],
        'research_debate': {'manager': {'stance': 'bull', 'confidence': 72}},
        'verdict': {'verdict': verdict, 'confidence': 76},
    }


def test_decision_record_preserves_before_after_and_agent_stances():
    record = learning.build_decision_record(
        'wf_1',
        [{'symbol': '005930', 'name': '삼성전자', 'score': 80}, {'symbol': '000660', 'score': 75}],
        [{'symbol': '005930', 'name': '삼성전자', 'score': 85}, {'symbol': '035420', 'score': 77}],
        [_analysis()],
        reference_date='2026-07-18',
    )
    assert record['intervention'] == {
        'promoted': ['035420'], 'removed': ['000660'], 'retained': ['005930']
    }
    assert record['analyses']['005930']['agents']['technical']['stance'] == 'bullish'
    assert record['status'] == 'pending'


def test_attach_outcomes_scores_only_replay_safe_observations():
    record = learning.build_decision_record(
        'wf_1', [], [], [_analysis(), _analysis('000660', 'bearish', 'SELL')], reference_date='2026-07-18'
    )
    result = learning.attach_forward_outcomes(record, [
        {'symbol': '005930', 'status': 'evaluated', 'lookahead_safe': True,
         'entry_date': '2026-07-19', 'exit_date': '2026-07-24', 'forward_return_pct': 4.2},
        {'symbol': '000660', 'status': 'evaluated', 'lookahead_safe': False,
         'entry_date': '2026-07-17', 'exit_date': '2026-07-24', 'forward_return_pct': -8},
    ])
    assert result['outcomes']['005930']['verdict_correct'] is True
    assert result['outcomes']['005930']['agent_accuracy']['technical'] is True
    assert result['outcomes']['000660']['eligible_for_learning'] is False
    assert 'verdict_correct' not in result['outcomes']['000660']
    assert result['eligible_outcome_count'] == 1


def test_aggregate_requires_samples_and_emits_bounded_advisories():
    records = []
    for index in range(5):
        record = learning.build_decision_record(
            f'wf_{index}', [], [], [_analysis()], reference_date='2026-07-01'
        )
        records.append(learning.attach_forward_outcomes(record, [{
            'symbol': '005930', 'status': 'evaluated', 'lookahead_safe': True,
            'entry_date': '2026-07-02', 'exit_date': '2026-07-07',
            'forward_return_pct': 3 if index < 4 else -3,
        }]))
    aggregate = learning.aggregate_learning(records, min_samples=5)
    assert aggregate['agent_accuracy']['technical']['sample_count'] == 5
    assert aggregate['agent_accuracy']['technical']['hit_rate_pct'] == 80.0
    assert aggregate['agent_accuracy']['technical']['adjustment_ready'] is True
    assert {'scope': 'agent', 'key': 'technical', 'signal': 'reliable', 'suggested_weight_delta': 0.05} in aggregate['lessons']
    assert aggregate['lookahead_safe_only'] is True


def test_atomic_memory_round_trip(tmp_path):
    path = tmp_path / 'learning' / 'memory.json'
    payload = {'schema_version': 1, 'lessons': [{'key': 'technical'}]}
    learning.save_memory(str(path), payload)
    assert learning.load_memory(str(path)) == payload
    assert json.loads(path.read_text(encoding='utf-8')) == payload
    assert learning.load_memory(str(tmp_path / 'missing.json'), default={}) == {}


def test_persist_workflow_learning_normalizes_tracker_horizon_and_builds_policy(tmp_path):
    workflows_root = tmp_path / 'workflows'
    memory_path = tmp_path / 'memory.json'
    records = []
    for index in range(5):
        record, memory = learning.persist_workflow_learning(
            f'wf_{index}',
            [{'candidate': {'symbol': '005930', 'display_name': 'Samsung'}, 'final_score': 80}],
            [{'candidate': {'symbol': '005930', 'display_name': 'Samsung'}, 'ta_adjusted_score': 84}],
            [_analysis()],
            [{'symbol': '005930', 'status': 'partial', 'lookahead_safe': True,
              'entry_date': '2026-07-02', 'primary_horizon': 5,
              'horizons': {'5': {'exit_date': '2026-07-09', 'return_pct': 3.0}}}],
            reference_date='2026-07-01', workflows_root=str(workflows_root),
            memory_path=str(memory_path), min_samples=5,
        )
        records.append(record)
    assert records[-1]['eligible_outcome_count'] == 1
    assert memory['agent_accuracy']['technical']['hit_rate_pct'] == 100.0
    policy = learning.get_workflow_policy(str(memory_path))
    assert policy['sample_count'] == 5
    assert policy['lookahead_safe'] is True
    assert policy['verdict_weights']['BUY'] > 1.0
