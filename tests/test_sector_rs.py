"""sector_rs (O'Neil 가중 상대강도) 단위 테스트.

알파 스캐너 Plan B — 시장 전체 상대강도 백분위(1~99)로
'섹터 동조/시장 후행 반등' 과 '진짜 주도주' 를 구분한다.
"""
import json
import os
import time

import pytest

from app.services.mirofish import sector_rs


def _closes(*returns_per_day: float, start: float = 1000.0, days: int | None = None):
    """일별 수익률 시퀀스로 종가 리스트 생성 (chronological)."""
    closes = [start]
    for r in returns_per_day:
        closes.append(closes[-1] * (1 + r))
    if days is not None:
        while len(closes) < days:
            closes.append(closes[-1])
    return closes


class TestWeightedReturn:
    def test_full_history_uses_oneil_weights(self):
        # 252일 이상 — 4개 구간 모두 사용: 0.4·R3m + 0.2·R6m + 0.2·R9m + 0.2·R12m
        closes = [100.0] * 300
        closes[-1] = 110.0  # 마지막 날 +10% → 모든 구간 수익률 +10%
        wr = sector_rs.compute_weighted_return(closes)
        assert wr == pytest.approx(0.10, abs=1e-6)

    def test_differentiated_horizons(self):
        # 12개월 전 100 → 9개월 전 100 → 6개월 전 100 → 3개월 전 100 → 현재 120
        # R3m=20%, R6m=20%, R9m=20%, R12m=20% 가 되도록 마지막 63일 구간에서만 상승
        closes = [100.0] * 253
        closes[-1] = 120.0
        wr = sector_rs.compute_weighted_return(closes)
        assert wr == pytest.approx(0.20, abs=1e-6)

    def test_young_ticker_renormalizes_weights(self):
        # 상장 4개월 (85일) — 3m 구간만 가용 → 가중치 전부 3m 으로 renormalize
        closes = [100.0] * 85
        closes[-1] = 130.0
        wr = sector_rs.compute_weighted_return(closes)
        assert wr == pytest.approx(0.30, abs=1e-6)

    def test_too_short_history_returns_none(self):
        closes = [100.0] * 30  # 63일 미만
        assert sector_rs.compute_weighted_return(closes) is None

    def test_zero_base_price_returns_none(self):
        closes = [0.0] * 70
        assert sector_rs.compute_weighted_return(closes) is None


class TestBuildRatings:
    def test_percentile_rank_spans_1_to_99(self):
        universe = {}
        # 100개 종목, 수익률 선형 분포
        for i in range(100):
            closes = [100.0] * 70
            closes[-1] = 100.0 + i  # 0% ~ +99%
            universe[f'{i:06d}'] = closes
        result = sector_rs.build_rs_ratings(universe)
        entries = result['entries']
        assert len(entries) == 100
        ratings = [e['rs_rating'] for e in entries.values()]
        assert min(ratings) == 1
        assert max(ratings) == 99
        # 최고 수익률 종목이 99
        assert entries['000099']['rs_rating'] == 99
        assert entries['000000']['rs_rating'] == 1

    def test_short_history_excluded_from_universe(self):
        universe = {
            'AAAAAA': _closes(days=70),
            'BBBBBB': [100.0] * 10,  # 너무 짧음
        }
        result = sector_rs.build_rs_ratings(universe)
        assert 'AAAAAA' in result['entries']
        assert 'BBBBBB' not in result['entries']
        assert result['universe_size'] == 2
        assert result['rated_count'] == 1


class TestArtifactCache:
    def test_cache_roundtrip(self, tmp_path):
        universe = {'AAAAAA': [100.0] * 69 + [120.0]}
        built = sector_rs.build_rs_ratings(universe)
        path = tmp_path / 'alpha_rs_ratings.json'
        sector_rs.write_rs_artifact(str(path), built)

        loaded = sector_rs.get_rs_ratings(data_root=str(tmp_path), allow_compute=False)
        assert loaded['entries']['AAAAAA']['rs_rating'] >= 1
        assert loaded.get('generated_at')

    def test_missing_cache_without_compute_returns_empty(self, tmp_path):
        loaded = sector_rs.get_rs_ratings(data_root=str(tmp_path), allow_compute=False)
        assert loaded['entries'] == {}

    def test_stale_cache_detected(self, tmp_path):
        path = tmp_path / 'alpha_rs_ratings.json'
        stale = {'generated_at': '2020-01-01T00:00:00+00:00', 'entries': {'AAAAAA': {'rs_rating': 50}}}
        path.write_text(json.dumps(stale), encoding='utf-8')
        assert sector_rs.is_artifact_stale(str(path), max_age_hours=20) is True

    def test_fresh_cache_not_stale(self, tmp_path):
        path = tmp_path / 'alpha_rs_ratings.json'
        built = sector_rs.build_rs_ratings({'AAAAAA': [100.0] * 70})
        sector_rs.write_rs_artifact(str(path), built)
        assert sector_rs.is_artifact_stale(str(path), max_age_hours=20) is False


class TestScoreAdjustment:
    def test_market_leader_bonus(self):
        adj = sector_rs.score_rs_adjustment({'rs_rating': 92})
        assert adj['alpha_delta'] == 4.0
        assert adj['tag'] == 'rs_market_leader'

    def test_strong_rs_bonus(self):
        adj = sector_rs.score_rs_adjustment({'rs_rating': 75})
        assert adj['alpha_delta'] == 2.0
        assert adj['tag'] == 'rs_strong'

    def test_laggard_penalty(self):
        adj = sector_rs.score_rs_adjustment({'rs_rating': 20})
        assert adj['alpha_delta'] == -4.0
        assert adj['tag'] == 'rs_laggard'

    def test_mid_rating_neutral(self):
        adj = sector_rs.score_rs_adjustment({'rs_rating': 55})
        assert adj['alpha_delta'] == 0.0
        assert adj['tag'] is None

    def test_missing_entry_neutral(self):
        adj = sector_rs.score_rs_adjustment(None)
        assert adj['alpha_delta'] == 0.0
        assert adj['tag'] is None

    def test_env_disabled_neutral(self, monkeypatch):
        monkeypatch.setenv('MIROFISH_RS_RATING_DISABLED', '1')
        adj = sector_rs.score_rs_adjustment({'rs_rating': 92})
        assert adj['alpha_delta'] == 0.0
        assert adj['tag'] is None
