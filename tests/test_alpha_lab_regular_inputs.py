from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

import pytest

from tests.test_alpha_lab_candidate_inputs import NOW, NAMES, collect as collect_daily
from tests.test_alpha_lab_regular_source import _pages


def module():
    return import_module("app.services.mirofish.alpha_lab.regular_inputs")


def test_overlay_retries_only_failed_symbol_and_seals_an_immutable_baseline(tmp_path):
    mod = module()
    daily_root = tmp_path / "candidate-desk" / "inputs"
    original = collect_daily(daily_root)
    baseline_files = {p: p.read_bytes() for p in daily_root.rglob("*.json")}
    calls = []

    class Provider:
        def fetch_session(self, symbol, session):
            calls.append(symbol)
            if calls == ["000660"]:
                raise RuntimeError("secret from failed request")
            pages = iter([[dict(row, stck_bsop_date=session.replace("-", "")) for row in page]
                          for page in _pages()])

            def request(*_):
                rows = next(pages)
                return SimpleNamespace(status_code=200, json=lambda: dict(
                    rt_cd="0", output1=dict(stck_shrn_iscd=symbol), output2=rows))

            return mod.regular_source.KISRegularProvider(request=request, clock=lambda: NOW).fetch_session(
                symbol, session)
    with pytest.raises(mod.RegularInputError) as error:
        mod.collect_inputs(tmp_path, now=NOW, provider=Provider())
    assert error.value.failed_symbols == ["000660"]
    overlay = tmp_path / "candidate-regular-v1" / "inputs"
    assert not (overlay / "current.json").exists()
    objects = {p: p.read_bytes() for p in (overlay / "objects").glob("*.json")}
    assert len(objects) == 1

    result = mod.collect_inputs(tmp_path, now=NOW, provider=Provider())
    assert calls == ["000660", "005930", "000660"]
    assert mod.load_inputs(tmp_path, now=NOW) == result
    assert result["provenance"]["baseline_input_fingerprint"] == original["input_fingerprint"]
    assert result["provenance"]["volume_basis"] == "KIS_published_daily"
    assert set(result["prices_by_symbol"]) == set(NAMES)
    corrected = result["prices_by_symbol"]["005930"][-1]
    assert (corrected["open"], corrected["high"], corrected["low"], corrected["close"]) == (101., 105., 98., 103.)
    assert corrected["volume"] == 10_000_000 and corrected["traded_value"] == 1_050_000_000
    assert result["regular_audit"]["005930"]["original_daily"]["close"] == 105.
    assert result["regular_audit"]["005930"]["regular_bar"]["volume"] == 1905
    assert all(p.read_bytes() == raw for p, raw in {**baseline_files, **objects}.items())
    assert all("secret from failed request" not in p.read_text(encoding="utf-8") for p in overlay.rglob("*.json"))

    # Re-seal the object and its reference to bypass the outer checksums.
    # Independent replay must still reject OHLC inconsistent with the raw pages.
    snapshot = result["provenance"]["snapshot_id"]
    manifest_path = overlay / "snapshots" / f"{snapshot}.json"
    manifest = mod.daily._read(manifest_path)
    assert manifest["regular_audit"] == result["regular_audit"]
    original_digest = manifest["objects"]["005930"]
    altered = mod.daily._read(overlay / "objects" / f"{original_digest}.json")
    altered["pages"][0]["response"]["output2"][0]["stck_prpr"] = "102"
    altered_digest = mod.daily._hash(altered)
    mod.daily._write(overlay / "objects" / f"{altered_digest}.json", altered)
    manifest["objects"]["005930"] = altered_digest
    mod.daily._write(manifest_path, manifest)
    with pytest.raises(ValueError, match="regular_inputs_integrity"):
        mod.load_inputs(tmp_path, now=NOW)
    with pytest.raises(ValueError, match="regular_inputs_integrity"):
        mod.collect_inputs(tmp_path, now=NOW, provider=Provider())
    assert calls == ["000660", "005930", "000660"]

    restored = dict(manifest, objects=dict(manifest["objects"], **{"005930": original_digest}))
    restored["regular_audit"]["005930"]["original_daily"]["close"] = 500.
    mod.daily._write(manifest_path, restored)
    with pytest.raises(ValueError, match="regular_inputs_integrity"):
        mod.load_inputs(tmp_path, now=NOW)


def test_stale_daily_session_cannot_collect(tmp_path):
    mod = module()
    collect_daily(tmp_path / "candidate-desk" / "inputs")

    class Provider:
        def fetch_session(self, *_):
            pytest.fail("stale daily session reached provider")

    with pytest.raises(ValueError, match="regular_inputs_stale"):
        mod.collect_inputs(tmp_path, provider=Provider(), now=NOW + timedelta(days=3))


def test_acquisition_code_is_part_of_source_identity(monkeypatch):
    mod = module()
    original = mod.source_contract()
    read_bytes = mod.Path.read_bytes

    def changed(path):
        data = read_bytes(path)
        return data + b"\n# revision" if path.name == "regular_inputs.py" else data

    monkeypatch.setattr(mod.Path, "read_bytes", changed)
    assert mod.source_contract() != original
