"""Scientific and fail-closed checks on fictional inputs; no market data."""
import copy
import json
import math

import numpy as np
import pytest

from hf_space.gex_scenarios import (
    DTE_BUCKETS, GEXError, MODEL_IDS, advance_mm_inventory,
    make_teaching_gex_contracts, run_gex_scenarios,
)


def _single(side="call", **updates):
    row = {"underlying": "TOY", "contract_id": "TOY-one", "option_type": side,
           "strike": 100., "expiry": "2030-01-18", "time_to_expiry_years": 1.,
           "iv": .2, "open_interest": 10, "multiplier": 100,
           "standard_terms_verified": True, "calendar_dte": 365, "is_0dte": False}
    row.update(updates)
    return row


def _run(rows=None, **updates):
    params = dict(spot=100., price_grid=[90., 100., 110.], complete_chain_verified=True,
                  source_kind="synthetic_demo")
    params.update(updates)
    return run_gex_scenarios(rows or [_single()], **params)


def _bsm_price(s, k, t, iv, rate, dividend, side):
    normal = lambda z: .5 * (1 + math.erf(z / math.sqrt(2)))
    d1 = (math.log(s / k) + (rate - dividend + iv * iv / 2) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    call = s * math.exp(-dividend * t) * normal(d1) - k * math.exp(-rate * t) * normal(d2)
    return call if side == "call" else call - s * math.exp(-dividend * t) + k * math.exp(-rate * t)


@pytest.mark.parametrize("side", ["call", "put"])
def test_gamma_matches_independent_price_second_difference_and_units(side):
    rate, dividend, h = .04, .015, .01
    result = _run([_single(side)], rate=rate, dividend_yield=dividend)
    gamma = (_bsm_price(100 + h, 100, 1, .2, rate, dividend, side)
             - 2 * _bsm_price(100, 100, 1, .2, rate, dividend, side)
             + _bsm_price(100 - h, 100, 1, .2, rate, dividend, side)) / h ** 2
    unsigned = result["models"]["unsigned_concentration"]["current_gex"]
    assert unsigned == pytest.approx(.01 * 100 ** 2 * 10 * 100 * gamma, rel=2e-6)
    expected_sign = 1 if side == "call" else -1
    assert result["models"]["fixed_call_put"]["current_gex"] == expected_sign * unsigned
    assert result["config"]["unit"] == "USD_delta_hedge_notional_per_1pct_spot_move"


def test_each_spot_reprices_gamma_rather_than_only_rescaling_s_squared():
    result = _run([_single(time_to_expiry_years=.1)])
    curve = result["models"]["fixed_call_put"]["curve"]
    current, higher = curve[1]["gex"], curve[2]["gex"]
    assert not math.isclose(higher, current * (110 / 100) ** 2, rel_tol=.05)
    independent = _run([_single(time_to_expiry_years=.1)], spot=110.)
    assert higher == independent["models"]["fixed_call_put"]["current_gex"]
    assert result["lineage"]["full_chain_repriced_at_each_grid_point"] is True


def test_prior_formula_unsigned_scope_and_multiplier_scaling():
    call, put = _run(), _run([_single("put")])
    unsigned = call["models"]["unsigned_concentration"]["current_gex"]
    assert call["models"]["prior_inventory"]["current_gex"] == pytest.approx(unsigned * .5 * (2 * .6 - 1))
    assert put["models"]["prior_inventory"]["current_gex"] == pytest.approx(unsigned * .5 * (2 * .35 - 1))
    doubled = _run([_single(multiplier=200)])
    assert doubled["models"]["unsigned_concentration"]["current_gex"] == 2 * unsigned
    assert call["models"]["unsigned_concentration"]["is_dealer_inventory_estimate"] is False
    assert call["models"]["prior_inventory"]["prior_is_calibrated"] is False
    assert call["models"]["all_dealer_short"]["current_gex"] == -unsigned
    assert call["current_sign_robustness"]["is_confidence_interval"] is False
    assert call["current_sign_robustness"]["calibrated_probabilities"] is None


def test_multi_root_no_root_and_all_zero_remain_grid_approximations():
    result = _run(make_teaching_gex_contracts(), price_grid=list(range(80, 121)))
    roots = result["models"]["fixed_call_put"]["roots"]
    assert roots["status"] == "multiple_candidates_on_grid" and len(roots["brackets"]) >= 2
    assert roots["root_count_is_exact"] is False
    assert all(row["lower"] < row["upper"] for row in roots["brackets"])
    assert result["models"]["unsigned_concentration"]["roots"]["status"] == "no_root_detected_in_grid"
    neutral = _run(dealer_fraction=0.)
    assert neutral["models"]["prior_inventory"]["roots"]["status"] == "structural_all_zero"
    empty_exposure = _run([_single(open_interest=0)])
    assert all(row["roots"]["status"] == "structural_all_zero" for row in empty_exposure["models"].values())


def test_extreme_grid_underflow_is_not_reported_as_zero_gamma_flip():
    result = _run(make_teaching_gex_contracts(), price_grid=[1., 1e9])
    assert result["models"]["unsigned_concentration"]["current_gex"] > 1e6
    for model in result["models"].values():
        roots = model["roots"]
        assert roots["status"] == "numerically_unresolved_grid"
        assert roots["grid_zeros"] == [] and roots["brackets"] == []
        assert roots["zero_everywhere_in_declared_model"] is False
    assert result["lineage"]["point_in_time_audit_performed"] is False


def test_exact_call_put_gamma_cancellation_has_no_isolated_flip():
    rows = [_single("call", contract_id="TOY-call"), _single("put", contract_id="TOY-put")]
    result = _run(rows)
    roots = result["models"]["fixed_call_put"]["roots"]
    assert roots["status"] == "structural_all_zero"
    assert roots["zero_everywhere_in_declared_model"] is True
    assert roots["grid_zeros"] == [] and roots["brackets"] == []
    assert result["models"]["unsigned_concentration"]["current_gex"] > 0


def test_expiry_and_nonoverlapping_dte_contributions_sum_to_current():
    result = _run(make_teaching_gex_contracts())
    for model in MODEL_IDS:
        dte = [row for row in result["dte_contributions"] if row["model"] == model]
        expiry = [row for row in result["expiry_contributions"] if row["model"] == model]
        assert tuple(row["bucket"] for row in dte) == DTE_BUCKETS
        assert len(dte) == 6
        assert sum(row["gex"] for row in dte) == pytest.approx(result["models"][model]["current_gex"])
        assert sum(row["gex"] for row in expiry) == pytest.approx(result["models"][model]["current_gex"])
    # One-day calendar bucket can have sub-day pricing T without becoming 0DTE.
    row = _single(time_to_expiry_years=.1 / 365, calendar_dte=1)
    one_day = _run([row])
    contributions = [r for r in one_day["dte_contributions"] if r["model"] == "unsigned_concentration"]
    assert next(r["gex"] for r in contributions if r["bucket"] == "0DTE") == 0
    assert next(r["gex"] for r in contributions if r["bucket"] == "1-2") > 0


def test_unsigned_own_peaks_keep_all_ties_and_are_not_vendor_walls():
    spot = 100 * math.exp(-.5 * .2 ** 2)
    rows = [_single(strike=80., contract_id="TOY-low"), _single(strike=125., contract_id="TOY-high")]
    result = _run(rows, spot=spot)
    assert [row["strike"] for row in result["own_concentration_peaks"]["call"]] == [80., 125.]
    assert result["own_concentration_peaks"]["put"] == []
    assert "not vendor" in result["peak_definition"]
    assert result["own_concentration_peaks"]["call"][0]["strike"] < spot < result["own_concentration_peaks"]["call"][1]["strike"]


def test_explicit_iv_and_time_sensitivities_reprice_without_expiry_floors():
    baseline = _run()
    larger_iv = _run(iv_shift=.1)
    less_time = _run(time_shift_years=.5)
    assert larger_iv["models"]["unsigned_concentration"]["current_gex"] < baseline["models"]["unsigned_concentration"]["current_gex"]
    assert less_time["models"]["unsigned_concentration"]["current_gex"] > baseline["models"]["unsigned_concentration"]["current_gex"]
    with pytest.raises(GEXError):
        _run(iv_shift=-.2)
    with pytest.raises(GEXError):
        _run(time_shift_years=1.)


def test_tiny_unequal_concentrations_are_not_mislabeled_tied_peaks():
    rows = [_single(strike=160., iv=.05, contract_id="TOY-tail-one"),
            _single(strike=170., iv=.05, contract_id="TOY-tail-two")]
    result = _run(rows)
    assert [row["strike"] for row in result["own_concentration_peaks"]["call"]] == [160.]


@pytest.mark.parametrize("field,value", [
    ("strike", 0), ("strike", float("inf")), ("iv", None), ("iv", float("nan")),
    ("iv", 0), ("open_interest", -1), ("open_interest", 2.5), ("open_interest", True),
    ("multiplier", 0), ("multiplier", "100"), ("time_to_expiry_years", 0),
    ("time_to_expiry_years", None), ("standard_terms_verified", False),
    ("calendar_dte", None), ("calendar_dte", -1), ("is_0dte", None),
    ("option_type", "CALL"), ("option_type", ["call"]), ("expiry", "unknown"),
    ("is_adjusted", True), ("adjusted", True),
])
def test_missing_adjusted_nonfinite_or_invalid_contract_values_fail(field, value):
    with pytest.raises(GEXError):
        _run([_single(**{field: value})])


def test_unverified_chain_missing_fields_duplicates_and_multiple_underlyings_fail():
    with pytest.raises(GEXError):
        _run(complete_chain_verified=False)
    row = _single()
    del row["open_interest"]
    with pytest.raises(GEXError):
        _run([row])
    with pytest.raises(GEXError):
        _run([_single(), _single()])
    with pytest.raises(GEXError):
        _run([_single(), _single(contract_id="different-id")])
    with pytest.raises(GEXError):
        _run([_single(), _single(underlying="OTHER", contract_id="other")])
    with pytest.raises(GEXError):
        _run([_single(calendar_dte=0, is_0dte=False)])


@pytest.mark.parametrize("grid", [[100.], [100., 100.], [110., 100.], [0., 100.], [float("nan"), 100.], ["90", 100.]])
def test_invalid_grid_fails_without_sorting_filling_or_null_conversion(grid):
    with pytest.raises(GEXError):
        _run(price_grid=grid)


@pytest.mark.parametrize("parameter,value", [("spot", float("nan")), ("rate", float("inf")),
                                           ("iv_shift", True), ("prior_long_call", 1.1),
                                           ("prior_long_put", -.1), ("dealer_fraction", None)])
def test_invalid_configuration_fails(parameter, value):
    with pytest.raises(GEXError):
        _run(**{parameter: value})


def test_bounds_do_not_silently_truncate_and_input_is_not_mutated(monkeypatch):
    from hf_space import gex_scenarios as core
    rows = make_teaching_gex_contracts()
    before = copy.deepcopy(rows)
    result = _run(rows)
    assert rows == before
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result["lineage"]["contract_count"] == len(rows)
    monkeypatch.setattr(core, "MAX_GAMMA_CELLS", 1)
    with pytest.raises(GEXError, match="truncate"):
        _run(rows)


def test_mm_buy_close_increases_signed_inventory_without_stale_oi_clipping():
    # Buy-close reduces a short book: -20 + 7 = -13. Opening/closing does not
    # reverse the buy sign. Sell-close removes long inventory in the same way.
    assert advance_mm_inventory(-20, mm_buys=7, mm_sells=0)["q_next"] == -13
    assert advance_mm_inventory(20, mm_buys=0, mm_sells=7)["q_next"] == 13
    assert advance_mm_inventory(20, mm_buys=100, mm_sells=100)["q_next"] == 20
    flow = advance_mm_inventory(20, mm_buys=100, mm_sells=0)
    assert flow["q_next"] == 120 and flow["stale_oi_clipped"] is False
    fractional = advance_mm_inventory(0, mm_buys=.6, mm_sells=.2, classification="declared_heuristic")
    assert fractional["q_next"] == pytest.approx(.4) and fractional["probability_calibrated"] is False
    with pytest.raises(GEXError):
        advance_mm_inventory(0, mm_buys=.6, mm_sells=0)
    with pytest.raises(GEXError):
        advance_mm_inventory(0, mm_buys=2, mm_sells=0, classification="anonymous_aggressor_buy")


def test_negative_gex_can_amplify_up_or_down_and_is_not_a_bearish_forecast():
    result = _run([_single("put")])
    gex = result["models"]["fixed_call_put"]["current_gex"]
    assert gex < 0
    gamma_book = gex / (.01 * result["spot"] ** 2)
    assert -gamma_book * 1. > 0  # Up move -> buy hedge.
    assert -gamma_book * -1. < 0  # Down move -> sell hedge.
    assert result["lineage"]["direction_predictor"] is False
    assert result["lineage"]["orders_submitted"] is False
    assert result["lineage"]["synthetic_fixture_is_market_history"] is False
