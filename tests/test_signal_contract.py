"""Signal.to_dict() contract test.

The frontend Signal interface depends on a *flat* dict shape with nested
score/checklist sub-dicts. CLAUDE.md §4 codifies this. If anyone reorders
or nests these keys differently, the dashboard silently breaks.
"""
from engine.models import Signal


REQUIRED_TOP_LEVEL = {
    "stock_code", "stock_name", "market", "sector", "grade",
    "score", "checklist",
    "current_price", "entry_price", "stop_price", "target_price",
    "quantity", "position_size", "r_value", "r_multiplier",
    "trading_value", "change_pct", "volume_ratio",
    "foreign_5d", "inst_5d",
    "news_items", "themes",
}

REQUIRED_SCORE_KEYS = {
    "news", "volume", "chart", "candle", "consolidation",
    "supply", "disclosure", "total",
}


def test_signal_to_dict_has_all_top_level_keys():
    d = Signal().to_dict()
    missing = REQUIRED_TOP_LEVEL - set(d.keys())
    assert not missing, f"Signal.to_dict() missing top-level keys: {missing}"


def test_signal_score_is_nested_dict_with_required_keys():
    d = Signal().to_dict()
    score = d.get("score")
    assert isinstance(score, dict), f"score must be a dict, got {type(score).__name__}"
    missing = REQUIRED_SCORE_KEYS - set(score.keys())
    assert not missing, f"score sub-dict missing keys: {missing}"


def test_signal_checklist_is_dict():
    d = Signal().to_dict()
    cl = d.get("checklist")
    assert isinstance(cl, dict), f"checklist must be a dict, got {type(cl).__name__}"
    # The frontend ChecklistDetail interface needs at least these flags
    for key in ("has_news", "volume_sufficient", "is_new_high"):
        assert key in cl, f"checklist missing required key: {key}"
