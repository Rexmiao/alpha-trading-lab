"""Public derived reference boundaries and independent historical regressions."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import pytest

from hf_space import premarket as p

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "state/premarket-365/20261127T200955569265Z/report.json"
INDEPENDENT = ROOT / "state/premarket-three-etf-review/browser-expected-1.25pct.json"


@pytest.fixture(scope="module")
def reference():
    return p.load_reference()


def test_public_asset_has_only_dimensionless_allowlisted_fields(reference):
    raw = p.REFERENCE_PATH.read_bytes()
    assert len(raw) < 2_000_000
    assert hashlib.sha256(raw).hexdigest() == p.REFERENCE_SHA256
    assert reference["provenance"]["report_sha256"] == "e51e209f52501b32365629e04c2671f0286fca786e0a5264f30280e45c6a581a"
    forbidden = {"open", "high", "low", "close", "volume", "open_price", "high_price", "low_price",
                 "close_price", "open_proxy", "low_30m", "premarket_price_or_high", "previous_rth_close",
                 "kl_list", "next_req_key", "capture_folder", "account", "token", "api_key"}
    def walk(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
        elif isinstance(value, str):
            assert "D:\\" not in value and "C:\\" not in value and "hf_" not in value
    walk(reference)
    assert reference["provenance"]["publication_profile"] == "dimensionless_daily_statistics_only"
    assert [len(reference["symbols"][s]) for s in p.SYMBOLS] == [250, 250, 250]


@pytest.mark.parametrize("level", ["root", "provenance", "day", "outcome", "definition", "window"])
def test_unknown_fields_cannot_smuggle_raw_prices_or_private_material(reference, level):
    modified = deepcopy(reference)
    day = modified["symbols"]["QQQ"][0]
    target = {"root": modified, "provenance": modified["provenance"], "day": day,
              "outcome": day["outcome"], "definition": day["definitions"]["fixed_0925"],
              "window": day["outcome"]["windows"][0]}[level]
    target["open_price"] = 123.45
    with pytest.raises(p.PremarketReferenceError):
        p.validate_reference(modified)


@pytest.mark.parametrize("value", [True, 0, -1, 11, "NaN", "Infinity", "0.0000001", "", None])
def test_invalid_threshold_is_rejected_before_reference_access(value):
    with pytest.raises(p.PremarketReferenceError):
        p.analyze_reference({}, threshold_pct=value)


@pytest.mark.parametrize("selected", [[], "QQQ", ["QQQ", "QQQ"], ["TQQQ"], [None]])
def test_unknown_or_duplicate_symbol_selection_rejected(reference, selected):
    with pytest.raises(p.PremarketReferenceError):
        p.analyze_reference(reference, symbols=selected)


def test_exact_gain_boundary_is_strict_even_beyond_float_precision(reference):
    modified = deepcopy(reference)
    day = modified["symbols"]["QQQ"][0]
    d = day["definitions"]["fixed_0925"]
    d["return_ratio"] = {"numerator": "1", "denominator": "80"}
    assert day["date"] not in p.analyze_reference(modified, threshold_pct="1.25", symbols=["QQQ"])["results"]["QQQ"]["events"]["dates"]
    above = Fraction(1, 80) + Fraction(1, 10**35)
    d["return_ratio"] = {"numerator": str(above.numerator), "denominator": str(above.denominator)}
    assert float(above) == .0125
    assert day["date"] in p.analyze_reference(modified, threshold_pct="1.25", symbols=["QQQ"])["results"]["QQQ"]["events"]["dates"]


@pytest.mark.parametrize("offset,expected", [(-1, 0), (0, 1), (1, 1)])
def test_exact_downside_inclusive_boundary(reference, offset, expected):
    modified = deepcopy(reference)
    day = modified["symbols"]["QQQ"][0]
    day["definitions"]["fixed_0925"]["return_ratio"] = {"numerator": "1", "denominator": "10"}
    value = Fraction(1, 200) + Fraction(offset, 10**35)
    day["outcome"]["max_drop_ratio"] = {"numerator": str(value.numerator), "denominator": str(value.denominator)}
    for w in day["outcome"]["windows"]:
        w["max_drop_from_open"] = float(value)
    result = p.analyze_reference(modified, threshold_pct="9", symbols=["QQQ"])["results"]["QQQ"]
    assert result["events"]["n"] == 1
    assert result["events"]["thresholds"][0]["k"] == expected


def test_unavailable_window_is_distinct_from_zero_events(reference):
    ever = p.analyze_reference(reference, definition="ever_before_open", symbols=["DIA"])["results"]["DIA"]
    assert ever["status"] == "no_eligible_days" and ever["eligible_days"] == 0
    assert ever["events"]["n"] == 0 and ever["events"]["mean"] is None
    assert ever["events"]["thresholds"][0]["proportion"] is None
    assert ever["partial_observed_hit_dates"] == ["2026-03-23", "2026-04-08", "2026-11-23"]
    fixed = p.analyze_reference(reference, threshold_pct="3", symbols=["DIA"])["results"]["DIA"]
    assert fixed["status"] == "no_events" and fixed["eligible_days"] == 236
    assert fixed["events"]["n"] == 0 and fixed["events"]["max"] is None
    assert fixed["baseline_same_eligible_days"]["n"] == 236


EXPECTED_N = {
    "QQQ": ((75,70,103,103),(30,30,50,51),(13,13,17,18),(4,5,9,11),(2,2,4,4),(2,2,2,2)),
    "SPY": ((40,41,49,49),(9,9,18,18),(3,3,3,3),(2,2,3,3),(2,2,3,3),(1,1,1,1)),
    "DIA": ((41,42,0,0),(11,11,0,0),(4,4,0,0),(3,3,0,0),(2,2,0,0),(0,0,0,0)),
}


def test_all_72_fixed_reference_sample_counts(reference):
    for i, cutoff in enumerate(("0.5", "1", "1.5", "2", "2.5", "3")):
        for j, definition in enumerate(p.DEFINITIONS):
            result = p.analyze_reference(reference, threshold_pct=cutoff, definition=definition)
            for symbol in p.SYMBOLS:
                assert result["results"][symbol]["events"]["n"] == EXPECTED_N[symbol][i][j]


def assert_close(actual, expected):
    if isinstance(expected, dict):
        for key, value in expected.items(): assert_close(actual[key], value)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected): assert_close(a, b)
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-12)
    else:
        assert actual == expected


@pytest.mark.skipif(not FROZEN.exists(), reason="Local private frozen report is not a public test fixture")
def test_all_72_full_summaries_match_the_frozen_report(reference):
    frozen = json.loads(FROZEN.read_bytes())
    for cutoff, per_symbol in frozen["threshold_sweep"].items():
        for definition in p.DEFINITIONS:
            result = p.analyze_reference(reference, threshold_pct=str(float(cutoff)*100), definition=definition)
            for symbol in p.SYMBOLS:
                for ours, old in (("events", "events"), ("baseline_same_eligible_days", "baseline_same_eligible_days")):
                    a = result["results"][symbol][ours]
                    b = per_symbol[symbol]["summary"][definition][old]
                    assert a["n"] == b["n"] and a["dates"] == b["dates"]
                    assert_close(a["thresholds"], b["thresholds"])
                    assert_close(a, {k: b["drop_distribution"][k] for k in ("mean", "median", "p90", "max")})
                    assert_close(a["negative_30m_close"], b["negative_30m_close"])


@pytest.mark.skipif(not INDEPENDENT.exists(), reason="Local independent audit is not a public fixture")
def test_custom_1_25_matches_all_12_independent_summaries(reference):
    expected = json.loads(INDEPENDENT.read_bytes())["definitions"]
    for definition, symbols in expected.items():
        result = p.analyze_reference(reference, threshold_pct="1.25", definition=definition)
        for symbol, b in symbols.items():
            a = result["results"][symbol]
            assert a["eligible_days"] == b["eligible"] and a["total_days"] == b["total"]
            assert a["partial_observed_hit_dates"] == b["partial_observed_hit_dates"]
            for ours, old in (("events", "events"), ("baseline_same_eligible_days", "baseline")):
                assert_close(a[ours], {k: b[old][k] for k in ("n", "dates", "mean", "median", "p90", "max")})
                for x, y in zip(a[ours]["thresholds"], b[old]["thresholds"]):
                    assert_close(x, {"k": y["k"], "n": y["n"], "proportion": y["p"], "lower": y["lower"], "upper": y["upper"]})


def test_corrupt_bundled_asset_never_falls_back_to_synthetic(reference, tmp_path, monkeypatch):
    bad = tmp_path / "reference.json"
    bad.write_text("{}")
    monkeypatch.setattr(p, "REFERENCE_PATH", bad)
    with pytest.raises(p.PremarketReferenceError, match="hash_or_size"):
        p.load_reference()


def test_export_is_safe_and_preserves_window_statistics(reference):
    result = p.analyze_reference(reference, threshold_pct="1.25", symbols=["DIA"])
    assert result["config"]["execution_eligible"] is False
    assert list(result["results"]) == ["DIA"]
    row = result["results"]["DIA"]["event_rows"][0]
    assert [w["minutes"] for w in row["windows"]] == [1,5,10,15,30]
    assert row["windows"][-1]["max_drop_from_open"] == pytest.approx(row["max_drop_from_open"])
    assert "kl_list" not in json.dumps(result) and "open_proxy" not in json.dumps(result)
