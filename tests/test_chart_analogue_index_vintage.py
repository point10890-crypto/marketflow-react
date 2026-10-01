"""A full evaluation run must hold one saved price vintage across all labels."""

import pytest

from app.services.mirofish import chart_analogue
from tests.test_chart_analogue_outcomes import arguments, install


def test_preloaded_outcomes_keep_original_arrays_when_index_is_republished(tmp_path, monkeypatch):
    root, _, sessions = install(tmp_path)
    original_index = chart_analogue._load(full=True, index_root=root)
    install(tmp_path, overrides=lambda index, row: {'current_price': 2 * (100 + index)})

    def forbidden_reload(*args, **kwargs):
        pytest.fail('Every symbol in an evaluation must use the already loaded vintage')

    monkeypatch.setattr(chart_analogue, '_load', forbidden_reload)
    result = chart_analogue.observed_outcomes(**arguments(root, sessions), _loaded_index=original_index)
    assert result['reference']['evaluated_close'] == 100
    assert result['trade_horizons'][0]['entry_close'] == 101
    assert result['trade_horizons'][0]['gross_return_pct'] == pytest.approx(4.950495)
