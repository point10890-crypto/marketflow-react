"""Hypothesis replay validation tests with synthetic samples only."""

from app.services.mirofish import hypothesis_replay as hr


def _sample(symbol, ret, alpha, tags):
    return {
        'symbol': symbol,
        'return_pct': ret,
        'alpha_score': alpha,
        'ranking_score': alpha,
        'strategy_tags': list(tags),
        'entry_date': '2026-05-01',
    }


def _good_tag_samples():
    samples = []
    for idx in range(30):
        samples.append(_sample(f'A{idx:04d}', 5.0 + (idx % 3), 60.0 + idx, ('good_tag',)))
    for idx in range(30):
        samples.append(_sample(f'B{idx:04d}', -5.0 - (idx % 3), 60.0 + idx, ('other_tag',)))
    return samples


def _weak_tag_samples():
    samples = []
    for idx in range(30):
        samples.append(_sample(f'A{idx:04d}', 1.0, 60.0 + idx, ('weak_tag',)))
    for idx in range(30):
        samples.append(_sample(f'B{idx:04d}', 1.0, 60.0 + idx, ('other_tag',)))
    return samples


def _bad_tag_samples():
    samples = []
    for idx in range(30):
        samples.append(_sample(f'A{idx:04d}', -5.0 - (idx % 3), 60.0 + idx, ('bad_tag',)))
    for idx in range(30):
        samples.append(_sample(f'B{idx:04d}', 5.0 + (idx % 3), 60.0 + idx, ('other_tag',)))
    return samples


def test_replay_rejects_insufficient_samples(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **_kw: _good_tag_samples()[:10])

    report = hr.replay_tag_delta('good_tag', 1.0)

    assert report['status'] == 'rejected'
    assert report['passed'] is False
    assert report['reason'] == 'insufficient_samples'
    assert report['sample_count'] == 10
    assert report['tagged_count'] == 10
    assert report['bounded_delta'] == 1.0


def test_replay_accepts_positive_delta_with_ic_and_forward_return_gain(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **_kw: _good_tag_samples())
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('good_tag', 5.0)

    assert report['status'] == 'accepted'
    assert report['passed'] is True
    assert report['reason'] == 'replay_improves_ic_and_top_bucket_return'
    assert report['sample_count'] == 60
    assert report['tagged_count'] == 30
    assert report['bounded_delta'] == 2.0
    assert report['delta_was_clamped'] is True
    assert report['adjusted']['ic'] > report['baseline']['ic']
    assert (
        report['adjusted']['top_bucket_avg_return_pct']
        > report['baseline']['top_bucket_avg_return_pct']
    )
    assert report['lookahead_safe'] is True


def test_replay_rejects_negative_delta_that_hurts_good_tag(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **_kw: _good_tag_samples())
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('good_tag', -2.0)

    assert report['status'] == 'rejected'
    assert report['passed'] is False
    assert report['adjusted']['ic'] < report['baseline']['ic']


def test_replay_rejects_positive_delta_for_negative_evidence(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **_kw: _bad_tag_samples())
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('bad_tag', 2.0)

    assert report['status'] == 'rejected'
    assert report['passed'] is False
    assert report['cohort']['tagged_average_return_pct'] < 0
    assert report['adjusted']['ic'] < report['baseline']['ic']


def test_replay_rejects_weak_evidence_without_ic_or_top_return_gain(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **_kw: _weak_tag_samples())
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('weak_tag', 2.0)

    assert report['status'] == 'rejected'
    assert report['passed'] is False
    assert report['reason'] == 'insufficient_ic_and_top_return_gain'
    assert report['metric_delta']['ic'] == 0.0
    assert report['metric_delta']['top_bucket_avg_return_pct'] == 0.0


def test_replay_rejects_insufficient_tagged_samples(monkeypatch):
    samples = _good_tag_samples()
    for sample in samples:
        sample['strategy_tags'] = ['other_tag']
    samples[0]['strategy_tags'] = ['good_tag']
    monkeypatch.setattr(hr, '_collect_samples', lambda **_kw: samples)
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('good_tag', 1.0)

    assert report['status'] == 'rejected'
    assert report['passed'] is False
    assert report['reason'] == 'insufficient_tagged_samples'
    assert report['sample_count'] == 60
    assert report['tagged_count'] == 1
