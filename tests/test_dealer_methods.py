"""Method availability must not upgrade assumptions or samples to inventory truth."""
import json

import pytest

from research.dealer_methods import (
    CAPABILITY_IDS, METHOD_IDS, DealerMethodError, initial_inventory_sensitivity,
    method_catalog,
)


def _rows(**kwargs):
    return {row["id"]: row for row in method_catalog(**kwargs)}


def test_default_catalog_has_existing_scenarios_but_no_claim_of_observed_stock():
    rows = _rows()
    assert tuple(rows) == METHOD_IDS
    assert len(rows) == 9
    for method in ("squeezemetrics", "layered_inventory_prior", "unsigned_concentration", "shadow_gamma"):
        assert rows[method]["status"] == "EXISTING_SCENARIO"
    assert rows["net_buying_pressure"]["status"] == "PROXY_ONLY"
    assert rows["mm_capacity_flow"]["status"] == "BLOCKED"
    assert all(row["identifies"]["q"] is False and not row["execution_eligible"] for row in rows.values())
    assert all(not row["identifies"]["calibrated_mm_probability"] for row in rows.values())


def test_capacity_sample_requires_actual_side_audit_capabilities_not_just_generic_trades():
    partial = _rows(capabilities={"mm_capacity_sample", "trade_quantity"})["mm_capacity_flow"]
    assert partial["status"] == "BLOCKED"
    assert partial["missing"] == ["contract_identity", "execution_ids"]
    ready = _rows(capabilities={"mm_capacity_sample", "trade_quantity", "contract_identity", "execution_ids"})["mm_capacity_flow"]
    assert ready["status"] == "SAMPLE_AUDIT_READY"
    assert ready["identifies"]["observed_mm_side_flow"] is True
    assert ready["identifies"]["complete_delta_q"] is False
    assert ready["identifies"]["q"] is False
    assert ready["outputs"] == ["sampled_observed_mm_side_flow"]


def test_data_declarations_cannot_enable_unimplemented_estimators_or_full_shadow_model():
    rows = _rows(capabilities=CAPABILITY_IDS)
    for method in ("latent_inventory", "demand_based_pricing", "complex_leg_reconstruction"):
        assert rows[method]["missing"] == []
        assert rows[method]["status"] == "BLOCKED"
        assert rows[method]["outputs"] == []
    assert "not the paper's full shadow-Gamma" in rows["shadow_gamma"]["limitations"][0]
    assert "not implemented" in rows["layered_inventory_prior"]["limitations"][0]


def test_language_switch_preserves_machine_readable_capability_contract_and_default_is_english():
    en, zh = method_catalog(), method_catalog("zh")
    assert en[0]["label"] == "Fixed Call+/Put− baseline"
    assert zh[0]["label"] == "固定Call正／Put负基线"
    for a, b in zip(en, zh):
        assert a["label"] != b["label"]
        for key in ("id", "status", "missing", "requirements", "outputs", "identifies", "evidence"):
            assert a[key] == b[key]
    json.dumps(en, allow_nan=False)
    json.dumps(zh, allow_nan=False)


def test_catalog_callers_cannot_mutate_future_results():
    rows = method_catalog()
    rows[0]["identifies"]["q"] = True
    rows[0]["requirements"].clear()
    fresh = method_catalog()[0]
    assert fresh["identifies"]["q"] is False
    assert fresh["requirements"]


@pytest.mark.parametrize("kwargs", [
    {"language": "de"}, {"capabilities": "mm_capacity_sample"},
    {"capabilities": {"made_up_signal"}}, {"capabilities": {"mm_capacity_sample": 1}},
])
def test_bad_catalog_declarations_fail_closed(kwargs):
    with pytest.raises(DealerMethodError):
        method_catalog(**kwargs)


def test_unknown_q0_never_defaults_to_zero_even_with_positive_classified_flow():
    r = initial_inventory_sensitivity(100, inventory_scope="SPY-call/C1/day", flow_scope="SPY-call/C1/day",
                                      assume_no_other_changes=True)
    assert r["q"] is None and r["scenario_lower"] is None
    assert r["scenario_direction"] == "DIRECTION_UNKNOWN"
    assert r["reason"] == "UNKNOWN_INITIAL_INVENTORY"


def test_same_buy_flow_can_leave_short_or_long_inventory_under_declared_q0_scenarios():
    args = {"inventory_scope": "TOY-call/C1/2030-01-02", "flow_scope": "TOY-call/C1/2030-01-02",
            "assume_no_other_changes": True}
    short = initial_inventory_sensitivity(20, q0_lower=-100, q0_upper=-50, **args)
    long = initial_inventory_sensitivity(20, q0_lower=10, q0_upper=30, **args)
    unresolved = initial_inventory_sensitivity(20, q0_lower=-30, q0_upper=30, **args)
    assert (short["scenario_lower"], short["scenario_upper"]) == (-80, -30)
    assert short["scenario_direction"] == "NEGATIVE_SCENARIO_RANGE"
    assert long["scenario_direction"] == "POSITIVE_SCENARIO_RANGE"
    assert unresolved["scenario_direction"] == "DIRECTION_UNKNOWN"
    assert all(r["q"] is None and r["calibrated_probability"] is None for r in (short, long, unresolved))


def test_other_missing_changes_must_be_explicitly_assumed_before_scenario_range_is_computed():
    r = initial_inventory_sensitivity(10, q0_lower=1, q0_upper=5, inventory_scope="same", flow_scope="same")
    assert r["scenario_lower"] is None
    assert r["reason"] == "OTHER_CHANGES_NOT_BOUNDED"
    exact_zero = initial_inventory_sensitivity(-10, q0_lower=10, q0_upper=10, inventory_scope="same", flow_scope="same",
                                             assume_no_other_changes=True)
    assert exact_zero["scenario_direction"] == "ZERO_SCENARIO_RANGE"
    assert exact_zero["q"] is None


@pytest.mark.parametrize("updates", [
    {"inventory_scope": "yesterday"}, {"flow_scope": ""}, {"q0_upper": None},
    {"q0_lower": 30}, {"q0_lower": float("nan")}, {"delta_q": float("inf")},
    {"delta_q": True}, {"q0_lower": "1"}, {"assume_no_other_changes": 1},
])
def test_sensitivity_rejects_cross_scope_invalid_numbers_or_incomplete_ranges(updates):
    args = {"delta_q": 10, "q0_lower": 1, "q0_upper": 5, "inventory_scope": "same", "flow_scope": "same"}
    args.update(updates)
    with pytest.raises(DealerMethodError):
        initial_inventory_sensitivity(**args)
