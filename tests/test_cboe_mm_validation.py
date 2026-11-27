"""Private runner contracts using declared fictional observations only."""
from datetime import datetime, timezone
import json

import pytest

from scripts import run_cboe_mm_validation as runner


def _contract(u="SPY", buy=10, sell=5):
    return {"contract_key": f"C1|{u}|2025-03-28|P|558", "underlying": u,
            "mm_buy_contracts": buy, "mm_sell_contracts": sell,
            "sampled_observed_mm_signed_contracts": buy - sell,
            "snapshot_source_local": "2025-03-28", "inventory_q": None}


def _audit(rows, *, truncated=False):
    return {"contract_summaries": rows, "contract_summaries_truncated": truncated,
            "trading_dates": ["2025-03-28"]}


def test_exact_series_join_exposes_sampling_flip_without_treating_eod_as_inventory_truth():
    left = _audit([_contract(buy=20, sell=10), _contract("QQQ", 3, 0)])
    right = _audit([_contract(buy=4, sell=8), _contract("QQQ", 6, 0)])
    r = runner.compare_contract_samples([left], [right])
    assert r["overlapping_contracts_with_observed_tbt_MM_sides"] == 2
    assert r["sign_comparison_counts"] == {"same_nonzero_sign": 1, "strict_opposite_nonzero": 1}
    assert r["selected_failure_example"]["tbt_sample_signed_side_sum"] == 10
    assert r["selected_failure_example"]["eod_sample_signed_side_sum"] == -4
    assert r["inventory_direction_accuracy"] is None and r["classification_accuracy"] is None
    assert r["eod_completeness_verified"] is False


def test_different_option_roots_remain_separate_without_assumed_deliverables():
    original = _contract("SPY", 10, 2)
    adjusted = {**_contract("SPY", 0, 3), "contract_key": "C1|2SPY|2025-03-28|P|558"}
    r = runner.compare_contract_samples([_audit([original, adjusted])], [_audit([original, adjusted])])
    assert r["overlapping_contracts_with_observed_tbt_MM_sides"] == 2
    assert r["root_equals_underlying_comparison_contracts"] == 1
    assert r["different_root_overlap_examples"][0]["source_option_root"] == "2SPY"
    assert r["different_root_overlap_examples"][0]["multiplier"] is None


@pytest.mark.parametrize("which", ["truncated", "different_day", "duplicate_scope"])
def test_comparison_refuses_silent_truncation_cross_date_or_duplicated_scope(which):
    left, right = _audit([_contract()]), _audit([_contract()])
    if which == "truncated":
        left["contract_summaries_truncated"] = True
    elif which == "different_day":
        right["trading_dates"] = ["2025-03-29"]
    else:
        left["contract_summaries"].append(_contract())
    with pytest.raises(ValueError):
        runner.compare_contract_samples([left], [right])


def _fake_report(monkeypatch):
    def fake_tbt(path, *, underlyings=None, max_contract_rows=0):
        rows = [_contract("SPY", 20, 10), _contract("QQQ", 3, 0)]
        if underlyings:
            rows = [r for r in rows if r["underlying"] in underlyings]
        result = _audit(rows)
        buys = sum(r["mm_buy_contracts"] for r in rows)
        sells = sum(r["mm_sell_contracts"] for r in rows)
        result.update({"raw_sha256": "a" * 64, "side_records": 5, "option_side_records": 4,
                       "quarantined_instrument_side_records": 1,
                       "observed_totals": {"mm_buy_contracts": buys, "mm_sell_contracts": sells,
                                           "sampled_observed_mm_signed_contracts": buys-sells},
                       "underlying_call_put": [{**r, "call_put": "P"} for r in rows]})
        return result

    def fake_oc(path, *, kind="eod", underlyings=None, max_contract_rows=0):
        rows = [_contract("SPY", 4, 8), _contract("QQQ", 6, 0)]
        if underlyings:
            rows = [r for r in rows if r["underlying"] in underlyings]
        result = _audit(rows)
        result["raw_sha256"] = "b" * 64
        return result
    monkeypatch.setattr(runner, "audit_tbt_sample", fake_tbt)
    monkeypatch.setattr(runner, "audit_open_close_sample", fake_oc)
    return runner.build_report("declared-tbt", "declared-oc", created_at="2026-11-27T18:00:00Z")


def test_report_keeps_hypothetical_gex_separate_and_never_fabricates_a_moomoo_join(monkeypatch):
    r = _fake_report(monkeypatch)
    assert r["inventory_q"] is None and r["full_interval_delta_q"] is None
    assert r["net_inventory_gex"] is None and r["calibrated_mm_probabilities"] is None
    assert r["teaching_gex_scenarios"]["source_kind"] == "synthetic_demo"
    assert r["teaching_gex_scenarios"]["underlying"] == "TOY"
    assert r["moomoo_alignment"]["overlapping_capture_dates"] == []
    assert r["moomoo_alignment"]["same_date_matched_trade_labels"] == 0
    assert len(r["methods"]["en"]) == len(r["methods"]["zh"]) == 9
    assert all(row["q"] is None for row in r["declared_q0_sensitivity"])
    assert r["lineage"]["report_generated_at_is_historical_available_at"] is False
    json.dumps(r, allow_nan=False)


def test_html_is_self_contained_english_default_bilingual_and_escapes_labels(monkeypatch):
    r = _fake_report(monkeypatch)
    r["methods"]["en"][0]["label"] = "<script src='malicious'>"
    page = runner.render_html(r)
    assert '<html lang="en">' in page
    assert 'data-language="en"' in page
    assert "data-lang='en'" in page and "data-lang='zh'" in page
    assert "connect-src 'none'" in page
    assert "<script src=" not in page and "fetch(" not in page
    assert "&lt;script src=" in page
    assert "SYNTHETIC_DEMO" in page and "Actual q = unknown" in page
    assert "<svg" in page
    assert "https://" not in page and "http://" not in page


def test_writer_keeps_derived_outputs_in_private_state_and_never_overwrites(monkeypatch, tmp_path):
    report = _fake_report(monkeypatch)
    allowed = tmp_path / "private-state"
    monkeypatch.setattr(runner, "OUTPUT_ROOT", allowed)
    with pytest.raises(ValueError, match="private_state"):
        runner.write_report(report, tmp_path / "public-web")

    class FrozenClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 27, 18, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runner, "datetime", FrozenClock)
    target = runner.write_report(report, allowed)
    original = (target / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.write_report(report, allowed)
    assert (target / "report.json").read_bytes() == original
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"report.json", "report.html"}
    assert not manifest["public_distribution_rights_verified"]
