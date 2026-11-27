"""Causal states, immediate prior session levels, and real ledger invariants."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hf_space import intraday as base
from hf_space import support_resistance as sr


DATES = [("2024-03-08", "14:30", 78), ("2024-03-11", "13:30", 78),
         ("2024-03-12", "13:30", 78), ("2024-03-13", "13:30", 78),
         ("2024-03-14", "13:30", 78)]


def prices(sessions=None, *, patterns=True):
    rows = []
    for day, opening, count in sessions or DATES[:3]:
        for index, stamp in enumerate(pd.date_range(f"{day}T{opening}:00Z", periods=count, freq="5min")):
            for symbol in ("AAA", "SPY"):
                op, high, low, close = (105., 105.05, 104.95, 105.) if symbol == "AAA" else (200., 200.05, 199.95, 200.)
                if symbol == "AAA" and patterns:
                    values = {1: (100.1, 100.2, 99.95, 100.05), 2: (100.05, 100.5, 100., 100.4),
                              8: (109.8, 110., 109.7, 109.95), 12: (110., 110.4, 109.8, 110.3),
                              13: (110.3, 110.6, 110., 110.4), 14: (110.4, 110.6, 110.2, 110.5)}
                    op, high, low, close = values.get(index, (op, high, low, close))
                if symbol == "AAA" and index == count - 1:
                    op, high, low, close = 105., 110., 100., 105.
                rows.append([stamp, symbol, op, high, low, close, 1000])
    return pd.DataFrame(rows, columns=base.COLUMNS)


def csv_bytes(frame):
    return frame.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode()


def cfg(**overrides):
    return {"band_bps": 10., "breakout_buffer_bps": 0., "confirmation_bars": 12,
            "execution_delay_bars": 0, **overrides}


def levels():
    return {"support": {"level_id": "S", "center": 100., "lower": 99.9, "upper": 100.1,
                        "available_at": "2024-03-08T21:00:00Z"},
            "resistance": {"level_id": "R", "center": 110., "lower": 109.89, "upper": 110.11,
                           "available_at": "2024-03-08T21:00:00Z"}, "previous_close": 105.}


def path(strategy, closes, *, lows=None, highs=None, **overrides):
    closes = np.asarray(closes, dtype=float)
    lows = np.asarray(lows, dtype=float) if lows is not None else closes - .01
    highs = np.asarray(highs, dtype=float) if highs is not None else closes + .01
    stamps = pd.date_range("2024-03-11T13:30:00Z", periods=78, freq="5min")
    return sr._state_path(strategy, "AAA", "2024-03-11", stamps, closes, highs, lows, levels(), cfg(**overrides))


@pytest.fixture(scope="module")
def result():
    return sr.run_sr_comparison(prices())


def test_schema_four_comparisons_and_component_hashes(result):
    assert result["status"] == "success"
    assert set(result) == {"source", "status", "metrics", "equity", "drawdown", "signals", "events",
                           "levels", "weights", "trades", "session_metrics", "coverage", "config", "lineage", "warnings"}
    assert {r["strategy"] for r in result["metrics"]} == {*sr.STRATEGY_IDS, "benchmark_rth"}
    assert all(m["n_sessions"] == 2 for m in result["metrics"])
    assert all(m["sharpe"] is None and m["annualized_volatility"] is None and m["annual_return"] is None for m in result["metrics"])
    assert result["coverage"]["evaluated_sessions"] == ["2024-03-11", "2024-03-12"]
    for module in (sr, base):
        key = f"hf_space/{Path(module.__file__).name}"
        assert result["lineage"]["code_sha256"][key] == hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    json.dumps(result, allow_nan=False)
    assert not result["lineage"]["orders_submitted"]
    assert not result["lineage"]["raw_OHLCV_in_report"]
    assert all("volume" not in r and "high" not in r and "low" not in r for r in result["signals"])


def test_levels_are_frozen_previous_complete_session_and_available_before_trade(result):
    first = [r for r in result["levels"] if r["session"] == "2024-03-11"]
    assert len(first) == 2
    support = next(r for r in first if r["type"] == "support")
    resistance = next(r for r in first if r["type"] == "resistance")
    # First teaching day actually reached 99.95 and 110.6, not today's values.
    assert support["center"] == 99.95
    assert resistance["center"] == 110.6
    assert support["source_session"] == "2024-03-08"
    assert support["available_at"] == "2024-03-08T21:00:00Z"
    assert all(pd.Timestamp(r["level_available_at"]) <= pd.Timestamp(r["available_at"]) for r in result["signals"])


def test_level_identity_includes_band_width_but_not_execution_costs(result):
    changed_band = sr.run_sr_comparison(prices(), band_bps=20)
    changed_cost = sr.run_sr_comparison(prices(), cost_bps=20)
    assert {r["level_id"] for r in changed_band["levels"]}.isdisjoint({r["level_id"] for r in result["levels"]})
    assert [r["level_id"] for r in changed_cost["levels"]] == [r["level_id"] for r in result["levels"]]


@pytest.mark.parametrize("price,band,buffer", [(1.79e308, 500, 0), (1.65e308, 500, 500)])
def test_nonfinite_derived_level_or_confirmation_threshold_fails_closed(price, band, buffer):
    frame = prices(patterns=False)
    frame[["open", "low", "close"]] = price * .5
    frame["high"] = price
    with pytest.raises(sr.SRError, match="Non-finite frozen"):
        sr.run_sr_comparison(frame, band_bps=band, breakout_buffer_bps=buffer)


@pytest.mark.parametrize("band,high,low", [(10, 100.1, 100.), (0, 100., 100.)])
def test_overlapping_or_identical_zones_fail_without_silent_repair(band, high, low):
    frame = prices(patterns=False)
    mask = frame.symbol.eq("AAA")
    frame.loc[mask, ["open", "close"]] = (high + low) / 2
    frame.loc[mask, "high"], frame.loc[mask, "low"] = high, low
    with pytest.raises(sr.SRError, match="Overlapping.*reduce band_bps"):
        sr.run_sr_comparison(frame, band_bps=band)


def test_reducing_band_width_can_resolve_distinct_narrow_zones():
    frame = prices(patterns=False)
    mask = frame.symbol.eq("AAA")
    frame.loc[mask, ["open", "close"]] = 100.05
    frame.loc[mask, "high"], frame.loc[mask, "low"] = 100.1, 100.
    assert sr.run_sr_comparison(frame, band_bps=1)["status"] == "success"


def test_bounce_requires_distinct_later_confirmation_and_persists():
    traces, events = path("support_bounce", [100.05, 100.3, 101., 102.], lows=[99.95, 100.2, 100.9, 101.9])
    assert [r["state"] for r in traces] == ["armed", "active", "active", "active"]
    assert [e["event"] for e in events] == ["setup_armed", "entry_confirmed"]
    assert events[0]["event_id"] == events[1]["event_id"]
    assert events[0]["available_at"] == "2024-03-11T13:35:00Z"
    assert events[1]["planned_execution_at"] == "2024-03-11T13:40:00Z"
    assert events[1]["execution_at"] is None


def test_bounce_cannot_confirm_on_touch_bar_even_when_close_above_band():
    traces, events = path("support_bounce", [100.4], lows=[99.95], highs=[100.5])
    assert traces[0]["state"] == "armed"
    assert all(e["event"] != "entry_confirmed" for e in events)


@pytest.mark.parametrize("last,reason", [(99.8, "close_below_frozen_band"), (109.9, "close_reached_resistance_lower")])
def test_bounce_close_confirmed_stop_or_target(last, reason):
    traces, events = path("support_bounce", [100.05, 100.3, last], lows=[99.95, 100.2, last-.01])
    assert traces[-1]["state"] == "flat"
    assert events[-1]["reason"] == reason
    assert events[-1]["planned_execution_at"] == "2024-03-11T13:45:00Z"


def test_shadow_below_support_does_not_stop_active_bounce():
    traces, _ = path("support_bounce", [100.05, 100.3, 100.4], lows=[99.95, 100.2, 98.])
    assert traces[-1]["state"] == "active"


def test_invalid_touch_close_does_not_arm_bounce():
    traces, events = path("support_bounce", [99.8], lows=[99.7], highs=[100.2])
    assert traces[0]["state"] == "flat" and not events


def test_bounce_arming_requires_previous_close_from_above():
    traces, events = path("support_bounce", [99.8, 100.05], lows=[99.7, 99.95], highs=[99.9, 100.1])
    assert all(r["state"] == "flat" for r in traces)
    assert not events


def test_confirmation_timeout_is_inclusive_and_expiry_precedes_late_confirmation():
    traces, events = path("support_bounce", [100.05, 100., 100.3], lows=[99.95, 99.95, 100.2], confirmation_bars=1)
    assert [r["state"] for r in traces] == ["armed", "armed", "flat"]
    assert events[-1]["event"] == "setup_expired"
    traces, _ = path("support_bounce", [100.05, 100.3], lows=[99.95, 100.2], confirmation_bars=1)
    assert traces[-1]["state"] == "active"


def test_armed_bounce_invalidates_before_confirmation():
    traces, events = path("support_bounce", [100.05, 99.8, 101.], lows=[99.95, 99.7, 100.9])
    assert [r["state"] for r in traces] == ["armed", "flat", "flat"]
    assert events[-1]["event"] == "setup_cancelled"


def test_breakout_is_close_upcross_not_touch_or_unchanged_above():
    traces, events = path("resistance_breakout", [110.1, 110.2, 110.3, 109.8, 110.3], highs=[111., 110.3, 110.4, 110., 110.4])
    assert [r["selected"] for r in traces] == [False, True, True, False, True]
    assert [e["event"] for e in events] == ["entry_confirmed", "exit_confirmed", "entry_confirmed"]


def test_first_bar_breakout_compares_previous_rth_close():
    traces, _ = path("resistance_breakout", [110.2])
    assert traces[0]["selected"]


def test_breakout_buffer_is_frozen_level_bps():
    traces, _ = path("resistance_breakout", [110.2, 110.23], breakout_buffer_bps=10)
    assert not traces[0]["selected"] and traces[1]["selected"]
    assert traces[0]["confirmation_threshold"] == pytest.approx(110.22)


def test_retest_must_follow_breakout_bar_and_overlap_frozen_band():
    traces, events = path("breakout_retest", [110.3, 110.4, 110.5], lows=[109.9, 110.3, 110.05])
    assert [r["state"] for r in traces] == ["armed", "armed", "active"]
    assert events[0]["touch_at"] is None
    assert events[-1]["touch_at"] == "2024-03-11T13:40:00Z"
    assert events[-1]["planned_execution_at"] == "2024-03-11T13:45:00Z"


def test_retest_touch_and_close_hold_can_confirm_on_same_later_bar():
    traces, events = path("breakout_retest", [110.3, 110.4], lows=[109.9, 110.])
    assert [r["state"] for r in traces] == ["armed", "active"]
    assert events[-1]["reason"] == "later_retouch_close_held_above_resistance"


@pytest.mark.parametrize("last,reason", [(109.8, "setup_cancelled"), (110.4, "setup_expired")])
def test_retest_invalidation_and_timeout(last, reason):
    traces, events = path("breakout_retest", [110.3, 110.4, last], lows=[110.2, 110.3, last-.01], confirmation_bars=1)
    assert traces[-1]["state"] == "flat"
    assert events[-1]["event"] == reason


def test_every_state_path_is_prefix_causal():
    closes = np.array([105., 100.05, 100.4, 110.3, 110.4, 109.7, 111.])
    lows = np.array([104.9, 99.95, 100.3, 109.9, 110., 109.6, 110.9])
    for strategy in sr.STRATEGY_IDS:
        full, events = path(strategy, closes, lows=lows)
        for length in range(1, len(closes)):
            prefix, prior_events = path(strategy, closes[:length], lows=lows[:length])
            assert prefix == full[:length]
            cutoff = prefix[-1]["timestamp"]
            assert prior_events == [r for r in events if r["timestamp"] <= cutoff]


def test_appending_future_session_preserves_all_historical_signals_events_and_trades(result):
    longer = sr.run_sr_comparison(prices(DATES[:4]))
    for key, date_key in (("signals", "session"), ("events", "session"), ("trades", "session"), ("equity", "session"), ("levels", "session")):
        assert [r for r in longer[key] if r[date_key] <= "2024-03-12"] == result[key]


def modify_day(frame, day, replacements):
    for index, values in replacements.items():
        stamp = pd.Timestamp(f"{day}T13:30:00Z") + pd.Timedelta(minutes=5*index)
        frame.loc[frame.symbol.eq("AAA") & frame.timestamp.eq(stamp), ["open", "high", "low", "close"]] = values


def breakout_frame(*, invalid=False, late=False):
    frame = prices(patterns=False)
    replacements = {}
    if late:
        replacements[73] = (110.2, 110.5, 110.1, 110.3)
        for i in (74, 75, 76):
            replacements[i] = (110.3, 110.5, 110.2, 110.4)
    else:
        replacements[1] = (110.2, 110.5, 110.1, 110.3)
        for i in range(2, 11):
            replacements[i] = (110.3, 110.5, 110.2, 110.4)
        replacements[2 if invalid else 11] = (109.8, 109.9, 109.6, 109.7)
    for day in ("2024-03-11", "2024-03-12"):
        modify_day(frame, day, replacements)
    return frame


def test_persistent_breakout_rebalances_only_on_selection_changes():
    result = sr.run_sr_comparison(breakout_frame())
    trades = [r for r in result["trades"] if r["strategy"] == "resistance_breakout"]
    first = [r for r in trades if r["session"] == "2024-03-11"]
    assert [r["side"] for r in first] == ["BUY", "SELL"]
    assert first[0]["execution_at"] == "2024-03-11T13:40:00Z"
    assert first[1]["execution_at"] == "2024-03-11T14:30:00Z"


def test_positive_delay_adds_whole_bar_without_same_close_fill():
    result = sr.run_sr_comparison(breakout_frame(), execution_delay_bars=2)
    buy = next(r for r in result["trades"] if r["strategy"] == "resistance_breakout" and r["side"] == "BUY")
    assert buy["signal_available_at"] == "2024-03-11T13:40:00Z"
    assert buy["execution_at"] == "2024-03-11T13:50:00Z"
    assert pd.Timestamp(buy["execution_at"]) - pd.Timestamp(buy["signal_available_at"]) == pd.Timedelta(minutes=10)


def test_integrated_retest_entry_links_later_touch_and_next_open_trade():
    frame = prices()
    warmup = prices(patterns=False)
    first_day = frame.timestamp.dt.strftime("%Y-%m-%d").eq("2024-03-08")
    frame.loc[first_day, ["open", "high", "low", "close"]] = warmup.loc[first_day, ["open", "high", "low", "close"]]
    result = sr.run_sr_comparison(frame)
    event = next(r for r in result["events"] if r["strategy"] == "breakout_retest" and r["event"] == "entry_confirmed")
    buy = next(r for r in result["trades"] if r["strategy"] == "breakout_retest" and r["side"] == "BUY")
    assert event["timestamp"] == "2024-03-11T14:35:00Z"
    assert event["touch_at"] == "2024-03-11T14:35:00Z"
    assert event["available_at"] == "2024-03-11T14:40:00Z"
    assert buy["execution_at"] == event["planned_execution_at"] == "2024-03-11T14:40:00Z"
    assert event["event_id"] in buy["signal_event_ids"]
    assert buy["signal_available_at"] == event["available_at"]


def test_invalidation_supersedes_pending_delayed_entry_and_records_cancel():
    result = sr.run_sr_comparison(breakout_frame(invalid=True), execution_delay_bars=2)
    first_buys = [r for r in result["trades"] if r["strategy"] == "resistance_breakout"
                  and r["session"] == "2024-03-11" and r["side"] == "BUY"]
    # A later valid recross may enter; the invalidated first signal must not fill.
    assert all(r["execution_at"] != "2024-03-11T13:50:00Z" for r in first_buys)
    cancel = next(r for r in result["events"] if r["strategy"] == "resistance_breakout" and r["event"] == "target_superseded")
    assert cancel["planned_execution_at"] == "2024-03-11T13:50:00Z"
    assert cancel["available_at"] == "2024-03-11T13:45:00Z"
    assert cancel["execution_at"] is None and cancel["signal_event_ids"]


def test_scheduled_eod_flatten_overrides_signals_no_overnight_or_close_exit():
    result = sr.run_sr_comparison(breakout_frame(late=True), execution_delay_bars=2)
    first = [r for r in result["trades"] if r["strategy"] == "resistance_breakout" and r["session"] == "2024-03-11"]
    assert [r["execution_at"] for r in first] == ["2024-03-11T19:50:00Z", "2024-03-11T19:55:00Z"]
    assert first[-1]["reason"] == "scheduled_last_bar_open_flatten"
    assert all(r["end_positions"] == 0 for r in result["session_metrics"])
    assert all(r["weight"] == 1 for r in result["weights"] if r["kind"] == "actual")


def test_cost_components_cash_integer_positions_and_exact_ledger_reconciliation(result):
    for metric in result["metrics"]:
        trades = [r for r in result["trades"] if r["strategy"] == metric["strategy"]]
        cash, positions = 100000., {}
        for trade in trades:
            assert isinstance(trade["quantity"], int)
            notional = trade["quantity"] * trade["reference_price"]
            assert trade["fee"] == pytest.approx(notional*.001)
            assert trade["spread_cost"] == pytest.approx(notional*.0001)
            assert trade["slippage_cost"] == pytest.approx(notional*.0001)
            cash -= trade["quantity_delta"] * trade["reference_price"] + trade["total_cost"]
            positions[trade["symbol"]] = positions.get(trade["symbol"], 0) + trade["quantity_delta"]
            assert positions[trade["symbol"]] >= 0 and cash >= -1e-7
        assert cash == pytest.approx(metric["final_equity"], abs=1e-7)
        assert not any(positions.values())
        assert sum(t["total_cost"] for t in trades) == pytest.approx(metric["total_cost"])
        assert metric["fee"] + metric["spread_cost"] + metric["slippage_cost"] == pytest.approx(metric["total_cost"])
    for row in result["weights"]:
        if row["kind"] == "target" and row["asset_kind"] == "asset":
            assert row["weight"] <= .2


def test_benchmark_uses_identical_evaluation_days_and_first_last_open(result):
    trades = [r for r in result["trades"] if r["strategy"] == "benchmark_rth"]
    assert len(trades) == 4
    assert [r["execution_at"] for r in trades[:2]] == ["2024-03-11T13:30:00Z", "2024-03-11T19:55:00Z"]
    assert {r["session"] for r in trades} == set(result["coverage"]["evaluated_sessions"])
    assert trades[0]["quantity"] * 200 > 99000


def test_missing_immediate_previous_session_does_not_bridge_gap():
    frame = prices(DATES)
    frame = frame.loc[~(frame.symbol.eq("AAA") & frame.timestamp.eq(pd.Timestamp("2024-03-11T15:00:00Z")))]
    result = sr.run_sr_comparison(frame)
    assert result["status"] == "success"
    assert result["coverage"]["evaluated_sessions"] == ["2024-03-13", "2024-03-14"]
    assert not any(r["session"] == "2024-03-12" for r in result["levels"])
    excluded = result["coverage"]["warmup_or_missing_previous_sessions"]
    assert any(r["session"] == "2024-03-12" and r["previous_exchange_session"] == "2024-03-11" for r in excluded)


def test_holiday_and_half_day_calendar_handles_prior_session_and_flat_time():
    sessions = [("2024-11-27", "14:30", 78), ("2024-11-29", "14:30", 42), ("2024-12-02", "14:30", 78)]
    result = sr.run_sr_comparison(prices(sessions, patterns=False))
    assert result["coverage"]["evaluated_sessions"] == ["2024-11-29", "2024-12-02"]
    assert next(r for r in result["levels"] if r["session"] == "2024-11-29")["source_session"] == "2024-11-27"
    friday = [r for r in result["trades"] if r["strategy"] == "benchmark_rth" and r["session"] == "2024-11-29"]
    assert friday[-1]["execution_at"] == "2024-11-29T17:55:00Z"


def test_future_current_day_high_does_not_revise_same_day_level(result):
    frame = prices()
    mask = frame.timestamp.eq(pd.Timestamp("2024-03-11T19:00:00Z")) & frame.symbol.eq("AAA")
    frame.loc[mask, "high"] = 1000.
    changed = sr.run_sr_comparison(frame)
    assert [r for r in changed["levels"] if r["session"] == "2024-03-11"] == [r for r in result["levels"] if r["session"] == "2024-03-11"]
    assert next(r for r in changed["levels"] if r["session"] == "2024-03-12" and r["type"] == "resistance")["center"] == 1000.


def test_non_rth_high_is_not_a_previous_rth_level(result):
    frame = prices()
    extra = frame.iloc[[0]].copy()
    extra["timestamp"] = pd.Timestamp("2024-03-08T13:00:00Z")
    extra["high"] = 1000.
    changed = sr.run_sr_comparison(pd.concat([frame, extra], ignore_index=True))
    assert changed["levels"] == result["levels"]
    assert changed["coverage"]["excluded_non_RTH_rows"] == 1


@pytest.mark.parametrize("count", [1, 2])
def test_at_least_two_evaluated_days_beyond_warmup_are_required(count):
    result = sr.run_sr_comparison(prices(DATES[:count]))
    assert result["status"] == "insufficient_history"
    assert not result["equity"] and not result["metrics"] and not result["trades"]


@pytest.mark.parametrize("change", ["duplicate", "bool", "malformed_ohlc", "missing_benchmark", "timestamp"])
def test_invalid_inputs_fail_explicitly(change):
    frame = prices()
    if change == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif change == "bool":
        frame["volume"] = frame.volume.astype(object)
        frame.loc[0, "volume"] = True
    elif change == "malformed_ohlc":
        frame.loc[0, "high"] = 1.
    elif change == "missing_benchmark":
        frame = frame.loc[frame.symbol.ne("SPY")]
    else:
        frame["timestamp"] = frame.timestamp.dt.tz_localize(None).astype(str)
    with pytest.raises(sr.SRError):
        sr.run_sr_comparison(frame)


@pytest.mark.parametrize("value", ["prices.csv", "https://example.test/x.csv", None])
def test_parser_does_not_accept_paths_or_urls(value):
    with pytest.raises(TypeError):
        sr.parse_sr_csv(value)


def test_parser_roundtrip_and_source_labels():
    frame = sr.parse_sr_csv(csv_bytes(prices()))
    assert frame.timestamp.dt.tz is not None
    assert sr.run_sr_comparison(frame, source="moomoo_snapshot")["source"] == "moomoo_snapshot"
    with pytest.raises(sr.SRError, match="no fallback"):
        sr.run_sr_comparison(frame, source="yahoo")


def test_worker_shared_with_existing_intraday_engine():
    assert base._BUSY.acquire(blocking=False)
    try:
        with pytest.raises(sr.SRError, match="busy"):
            sr.run_sr_comparison(prices())
    finally:
        base._BUSY.release()


@pytest.mark.parametrize("kwargs", [{"confirmation_bars": 0}, {"band_bps": -1}, {"execution_delay_bars": True}, {"cost_bps": float("inf")}])
def test_parameter_bounds(kwargs):
    with pytest.raises(sr.SRError):
        sr.run_sr_comparison(prices(), **kwargs)


def test_twenty_evaluated_days_enable_daily_not_minute_annualization():
    calendar = base._calendar("2024-03-08", "2024-04-15")
    sessions = calendar.sessions_in_range("2024-03-08", "2024-04-15")[:21]
    explicit = [(s.strftime("%Y-%m-%d"), calendar.session_open(s).strftime("%H:%M"), 78) for s in sessions]
    result = sr.run_sr_comparison(prices(explicit, patterns=False))
    assert len(result["coverage"]["evaluated_sessions"]) == 20
    for metric in result["metrics"]:
        returns = np.array([r["return"] for r in result["session_metrics"] if r["strategy"] == metric["strategy"]])
        assert metric["annualized_volatility"] == pytest.approx(returns.std(ddof=1)*math.sqrt(252))
        assert metric["annual_return"] is not None
