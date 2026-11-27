"""Calendar, selection, missing-data and probability contracts for event studies."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
import random
from zoneinfo import ZoneInfo

import pytest

from research.premarket_events import analyze_symbol, analyze_symbol_thresholds, PremarketError, wilson_interval

NY = ZoneInfo("America/New_York")
DAY = "2025-11-28"
PREVIOUS = "2025-11-26"  # Thanksgiving 11/27 is deliberately not a session.


def dt(day, clock):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=NY)


def bar(day, clock, *, o=103., h=103.2, l=102.8, c=103., volume=100):
    stamp = dt(day, clock)
    return {"time": stamp.strftime("%Y-%m-%d %H:%M:%S"), "timestamp": stamp.timestamp(),
            "open_price": o, "high_price": h, "low_price": l, "close_price": c,
            "volume": volume, "is_blank": False}


def calendar(day=DAY, previous=PREVIOUS, previous_close="16:00:00", close="13:00:00"):
    return {previous: {"open": dt(previous, "09:30:00").isoformat(), "close": dt(previous, previous_close).isoformat()},
            day: {"open": dt(day, "09:30:00").isoformat(), "close": dt(day, close).isoformat()}}


def observations(day=DAY, previous=PREVIOUS, previous_close="16:00:00", preprice=103.):
    result = [bar(previous, previous_close, o=100, h=100, l=100, c=100)]
    for minute in range(1, 331):
        clock = (dt(day, "04:00:00") + timedelta(minutes=minute)).strftime("%H:%M:%S")
        result.append(bar(day, clock, o=preprice, h=preprice, l=preprice, c=preprice))
    for minute in range(1, 31):
        clock = (dt(day, "09:30:00") + timedelta(minutes=minute)).strftime("%H:%M:%S")
        result.append(bar(day, clock))
    low = next(r for r in result if r["time"] == day + " 09:48:00")
    low.update(open_price=101., high_price=101.2, low_price=100., close_price=100.5)
    return result


def run(rows=None, *, day=DAY, previous=PREVIOUS, sessions=None, **kwargs):
    return analyze_symbol(observations(day, previous) if rows is None else rows,
        symbol="QQQ", sessions=sessions or calendar(day, previous), start=day,
        end_exclusive=(date.fromisoformat(day) + timedelta(days=1)).isoformat(), bar_label="end", **kwargs)


def at(rows, clock, day=DAY):
    return next(r for r in rows if r["time"] == day + " " + clock)


def test_exact_calendar_prev_and_opening_window_not_full_day():
    r = run()
    day = r["daily"][0]
    assert day["previous_session_date"] == PREVIOUS
    assert day["previous_rth_close"] == 100
    assert day["quality"]["first30"]["complete"]
    assert not day["quality"]["full_rth"]["complete"]
    assert day["base_eligible"]
    assert day["outcome"]["low_bar_start_et"].endswith("09:47:00-05:00")
    assert day["outcome"]["max_drop_from_open"] == pytest.approx(3 / 103)
    assert r["summary"]["fixed_0925"]["events"]["thresholds"][1]["k"] == 1
    assert r["claims"]["execution_eligible"] is False


def test_later_day_low_is_not_part_of_first_half_hour():
    rows = observations()
    rows.append(bar(DAY, "10:01:00", o=70, h=75, l=60, c=65))
    d = run(rows)["daily"][0]
    assert d["outcome"]["low_30m"] == 100
    assert d["outcome"]["windows"][-1]["minutes"] == 30


def test_strict_threshold_and_fixed_snapshot_not_bar_after_cutoff():
    rows = observations()
    at(rows, "09:25:00").update(open_price=102.5, high_price=102.5, low_price=102.5, close_price=102.5)
    at(rows, "09:26:00").update(open_price=110., high_price=110., low_price=110., close_price=110.)
    d = run(rows)["daily"][0]
    assert d["definitions"]["fixed_0925"]["condition_known"]
    assert d["definitions"]["fixed_0925"]["triggered"] is False
    assert d["definitions"]["fixed_0925"]["premarket_return"] == .025
    assert d["definitions"]["fixed_0929"]["triggered"] is True


@pytest.mark.parametrize("low,expected_hits", [
    ("102.485000000000000001", 0),
    ("102.485", 1),
    ("102.484999999999999999", 1),
])
def test_drop_threshold_counts_use_exact_source_prices_not_rounded_float(low, expected_hits):
    rows = observations()
    at(rows, "09:48:00").update(open_price=103, high_price=103, low_price=low, close_price=103)
    r = run(rows, thresholds=(.005,))
    # All three ratios round to the same binary float, while exact source
    # prices put them on different sides of the inclusive 0.5% drop threshold.
    assert r["daily"][0]["outcome"]["max_drop_from_open"] == .005
    for stats in (r["summary"]["fixed_0925"]["events"],
                  r["summary"]["fixed_0925"]["baseline_same_eligible_days"],
                  r["baseline_all_valid_opening_days"]):
        assert stats["thresholds"][0]["k"] == expected_hits
        assert stats["thresholds"][0]["conditional_drop_distribution"]["n"] == expected_hits
    assert "exact_open_low" not in json.dumps(r, allow_nan=False)


def test_missing_fixed_bar_is_unknown_no_forward_fill():
    rows = [r for r in observations() if r["time"] != DAY + " 09:25:00"]
    r = run(rows); d = r["daily"][0]
    fixed = d["definitions"]["fixed_0925"]
    assert fixed["triggered"] is None
    assert fixed["quality"]["counts"]["missing"] == 1
    assert r["summary"]["fixed_0925"]["events"]["n"] == 0
    assert r["summary"]["fixed_0929"]["events"]["n"] == 1
    assert d["definitions"]["ever_before_0925"]["observed_hit_in_incomplete_window"] is True
    assert not d["definitions"]["ever_before_0925"]["analysis_eligible"]


@pytest.mark.parametrize("change,status", [({"volume": 0}, "zero_volume"), ({"is_blank": True}, "blank")])
def test_blank_zero_and_missing_are_separate_quality_states(change, status):
    rows = observations(); at(rows, "09:25:00").update(change)
    d = run(rows)["daily"][0]
    assert d["definitions"]["fixed_0925"]["quality"]["counts"][status] == 1
    assert d["definitions"]["fixed_0925"]["triggered"] is None
    assert d["definitions"]["fixed_0929"]["triggered"] is True


def test_fixed_snapshot_does_not_require_complete_early_premarket():
    rows = [r for r in observations() if r["time"] != DAY + " 05:00:00"]
    r = run(rows)
    assert r["summary"]["fixed_0925"]["events"]["n"] == 1
    assert r["summary"]["ever_before_open"]["events"]["n"] == 0
    assert r["summary"]["ever_before_open"]["incomplete_window_observed_hit_dates"] == [DAY]


def test_incomplete_ever_no_hit_stays_unknown_not_false():
    rows = observations(preprice=101.)
    rows = [r for r in rows if r["time"] != DAY + " 05:00:00"]
    d = run(rows)["daily"][0]
    e = d["definitions"]["ever_before_open"]
    assert e["triggered"] is None
    assert e["observed_hit_in_incomplete_window"] is False
    assert e["condition_known"] is False


def test_previous_close_does_not_fall_back_to_older_session():
    rows = [r for r in observations() if r["time"][:10] != PREVIOUS]
    older = "2025-11-25"
    rows.append(bar(older, "16:00:00", o=100, h=100, l=100, c=100))
    cal = calendar(); cal[older] = {"open": dt(older, "09:30:00").isoformat(), "close": dt(older, "16:00:00").isoformat()}
    d = run(rows, sessions=cal)["daily"][0]
    assert d["previous_session_date"] == PREVIOUS
    assert d["previous_rth_close"] is None
    assert d["definitions"]["fixed_0925"]["triggered"] is None


def test_halfday_previous_close_uses_calendar_not_1600():
    previous, day = "2025-11-28", "2025-12-01"
    rows = observations(day, previous, "13:00:00")
    rows.append(bar(previous, "16:00:00", o=50, h=50, l=50, c=50))
    d = run(rows, day=day, previous=previous,
            sessions=calendar(day, previous, previous_close="13:00:00", close="16:00:00"))["daily"][0]
    assert d["previous_rth_close"] == 100
    assert d["definitions"]["fixed_0925"]["premarket_return"] == .03


def test_dst_is_derived_from_new_york_dates_and_unix_timestamp():
    previous, day = "2025-03-07", "2025-03-10"
    r = run(observations(day, previous), day=day, previous=previous,
            sessions=calendar(day, previous, close="16:00:00"))
    assert r["daily"][0]["session_open_et"].endswith("09:30:00-04:00")
    assert r["daily"][0]["quality"]["first30"]["complete"]


def test_duplicate_source_bar_is_not_silently_double_counted_or_deduplicated():
    rows = observations(); rows.append(deepcopy(at(rows, "09:31:00")))
    r = run(rows)
    assert r["input_diagnostics"]["duplicate_timestamp_rows"] == 1
    assert r["daily"][0]["quality"]["first30"]["counts"]["duplicate"] == 1
    assert r["summary"]["fixed_0925"]["triggered_but_outcome_excluded_dates"] == [DAY]
    assert r["summary"]["fixed_0925"]["events"]["n"] == 0


def test_timestamp_disagreement_quarantined_without_shift():
    rows = observations(); at(rows, "09:31:00")["timestamp"] += 3600
    r = run(rows)
    q = r["daily"][0]["quality"]["first30"]
    assert q["reason_counts"]["timestamp_timezone_disagreement"] == 1
    assert r["daily"][0]["outcome"] is None


def test_unfinished_capture_does_not_complete_future_bars():
    r = run(observed_at=dt(DAY, "09:45:30").isoformat())
    assert r["daily"][0]["quality"]["first30"]["counts"]["future"] == 15
    assert r["daily"][0]["definitions"]["fixed_0925"]["triggered"] is True
    assert r["summary"]["fixed_0925"]["events"]["n"] == 0


def test_zero_events_does_not_return_zero_probability():
    r = run(observations(preprice=101.))
    stats = r["summary"]["fixed_0925"]["events"]
    assert stats["n"] == 0
    assert stats["drop_distribution"]["mean"] is None
    assert stats["thresholds"][0]["proportion"] is None
    assert r["summary"]["fixed_0925"]["baseline_same_eligible_days"]["n"] == 1


def test_full_rth_is_explicit_optional_and_not_confused_with_first30():
    r = run(require_full_rth=True)
    assert r["daily"][0]["quality"]["first30"]["complete"]
    assert not r["daily"][0]["base_eligible"]
    assert "full_rth_quality_incomplete" in r["daily"][0]["exclusion_reasons"]


def test_invalid_ohlc_is_not_fixed_by_sorting_prices():
    rows = observations(); at(rows, "09:31:00")["low_price"] = 105
    d = run(rows)["daily"][0]
    assert not d["quality"]["first30"]["complete"]
    assert d["quality"]["first30"]["reason_counts"]["invalid_ohlc"] == 1


def test_corporate_action_exclusion_is_caller_supplied_not_inferred():
    r = run(corporate_action_dates=[DAY])
    assert not r["daily"][0]["definitions"]["fixed_0925"]["condition_known"]
    assert r["claims"]["corporate_actions_independently_reconstructed"] is False
    assert r["claims"]["corporate_action_dates"] == [DAY]


def test_input_order_does_not_change_daily_results():
    rows = observations(); shuffled = deepcopy(rows); random.Random(3).shuffle(shuffled)
    assert run(rows)["daily"] == run(shuffled)["daily"]


def test_last_close_price_is_not_used_as_previous_session_close():
    rows = observations()
    for r in rows:
        r["last_close_price"] = 1
    assert run(rows)["daily"][0]["previous_rth_close"] == 100


def test_wilson_interval_known_counts_and_unknown_denominator():
    ci = wilson_interval(10, 20)
    assert ci["proportion"] == .5
    assert ci["lower"] == pytest.approx(.2992980081982123)
    assert ci["upper"] == pytest.approx(.7007019918017877)
    assert wilson_interval(0, 0)["proportion"] is None
    assert wilson_interval(0, 3)["upper"] > .5
    with pytest.raises(PremarketError): wilson_interval(4, 3)


def test_no_decimal_nan_or_private_state_in_serialized_report():
    encoded = json.dumps(run(), allow_nan=False)
    assert "NOT_CALIBRATED" not in encoded  # No fitted probability model exists.
    assert "point_in_time_delivery_verified" in encoded


def test_mixed_symbols_and_undeclared_bar_labels_fail():
    rows = observations(); rows[0]["symbol"] = "SPY"
    with pytest.raises(PremarketError, match="mixed_symbol"):
        run(rows)
    with pytest.raises(PremarketError, match="end_label"):
        analyze_symbol([], symbol="QQQ", sessions=calendar(), start=DAY,
                       end_exclusive="2025-11-29", bar_label="start")


def test_missing_calendar_predecessor_is_not_a_weekday_guess():
    cal = {DAY: calendar()[DAY]}
    d = run(sessions=cal)["daily"][0]
    assert d["previous_session_date"] is None
    assert not d["base_eligible"]


def test_dia_is_a_separate_allowed_symbol_not_pooled_with_other_etfs():
    rows = observations()
    for row in rows:
        row["symbol"] = "US.DIA"
    result = analyze_symbol(rows, symbol="DIA", sessions=calendar(), start=DAY,
                            end_exclusive="2025-11-29", bar_label="end")
    assert result["symbol"] == "DIA"
    assert result["daily"][0]["symbol"] == "DIA"
    assert result["summary"]["fixed_0925"]["events"]["n"] == 1
    assert result["claims"]["symbols_pooled"] is False
    with pytest.raises(PremarketError, match="mixed_symbol"):
        run(rows)


@pytest.mark.parametrize("price,hit", [
    ("102.4999999999999999999999999999999", False),
    ("102.5", False),
    ("102.5000000000000000000000000000001", True),
])
def test_premarket_gain_selection_uses_exact_rational_even_beyond_decimal_context(price, hit):
    result = run(observations(preprice=price))
    for definition in result["daily"][0]["definitions"].values():
        # Display values can coincide; only the reduced integer ratio selects.
        assert definition["premarket_return"] == .025
        assert definition["triggered"] is hit
        exact = definition["exact_premarket_return"]
        assert isinstance(exact["numerator"], str)
        assert isinstance(exact["denominator"], str)
        assert int(exact["denominator"]) > 0
    json.dumps(result, allow_nan=False)


def sweep(rows=None, values=("0.005", "0.025", "0.03", "0.04"), **kwargs):
    return analyze_symbol_thresholds(observations() if rows is None else rows,
        symbol="QQQ", sessions=calendar(), start=DAY,
        end_exclusive="2025-11-29", bar_label="end", premarket_thresholds=values, **kwargs)


@pytest.mark.parametrize("missing", [None, "05:00:00", "09:48:00"])
def test_batch_matches_separate_analysis_for_complete_and_incomplete_windows(missing):
    rows = observations()
    if missing is not None:
        rows = [r for r in rows if r["time"] != DAY + " " + missing]
    results = sweep(rows)
    assert list(results) == ["0.005", "0.025", "0.03", "0.04"]
    for threshold, result in results.items():
        assert result == run(rows, premarket_threshold=threshold)


def test_batch_scans_a_one_use_source_once_and_does_not_share_mutable_outputs():
    class OneUse:
        reads = 0
        def __iter__(self):
            self.reads += 1
            assert self.reads == 1
            yield from observations()
    rows = OneUse()
    results = sweep(rows)
    assert rows.reads == 1
    results["0.005"]["daily"][0]["quality"]["first30"]["complete"] = False
    assert results["0.025"]["daily"][0]["quality"]["first30"]["complete"]


def test_threshold_changes_keep_quality_eligibility_and_baseline_fixed():
    rows = [r for r in observations() if r["time"] != DAY + " 05:00:00"]
    results = sweep(rows, values=("0.025", "0.05"))
    lower, higher = results.values()
    assert lower["coverage"] == higher["coverage"]
    assert lower["baseline_all_valid_opening_days"] == higher["baseline_all_valid_opening_days"]
    for name in lower["summary"]:
        assert lower["summary"][name]["baseline_same_eligible_days"] == higher["summary"][name]["baseline_same_eligible_days"]
    low_def = lower["daily"][0]["definitions"]["ever_before_open"]
    high_def = higher["daily"][0]["definitions"]["ever_before_open"]
    assert low_def["triggered"] is high_def["triggered"] is None
    assert low_def["observed_hit_in_incomplete_window"] is True
    assert high_def["observed_hit_in_incomplete_window"] is False
    assert higher["summary"]["fixed_0925"]["events"]["n"] == 0
    assert higher["summary"]["fixed_0925"]["events"]["thresholds"][0]["proportion"] is None


@pytest.mark.parametrize("values", [(), (0,), (-.01,), (True,), ("NaN",), ("Infinity",),
                                      (1,), (".025", ".0250"), tuple((i + 1) / 100 for i in range(11))])
def test_batch_invalid_threshold_grid_is_rejected_before_source_iteration(values):
    def forbidden():
        pytest.fail("invalid configuration consumed source")
        yield
    with pytest.raises(PremarketError, match="invalid_thresholds"):
        sweep(forbidden(), values=values)


def test_batch_canonical_keys_and_exact_outcome_sufficient_statistics():
    result = sweep(values=("0.01000", "0.0250"))["0.025"]
    assert result["premarket_threshold_exact"] == "0.025"
    outcome = result["daily"][0]["outcome"]
    assert outcome["exact_max_drop"] == {"numerator": "3", "denominator": "103"}
    assert outcome["exact_return_30m"] == {"numerator": "0", "denominator": "1"}
    assert "raw_rows" not in result
