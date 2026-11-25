"""Synthetic coverage fixtures only; no market results or broker access."""
import json

import numpy as np
import pandas as pd
import pytest

from research.coverage import apply_history_boundaries, assess_coverage


def fixture_prices(periods=120):
    dates = pd.bdate_range("2024-01-02", periods=periods)
    records = []
    for symbol, base in (("OLD", 100.0), ("IPO", 80.0), ("SPY", 200.0)):
        for i, day in enumerate(dates):
            opening = base + i * 0.2
            closing = opening * (1 + 0.002 * np.sin(i))
            records.append({"date": day, "symbol": symbol, "open": opening,
                            "high": max(opening, closing) * 1.01,
                            "low": min(opening, closing) * 0.99,
                            "close": closing, "volume": 1000 + i})
    return dates, pd.DataFrame(records)


def config(**changes):
    result = {"universe": ["OLD", "IPO", "MISSING"], "benchmark": "SPY",
              "lookback": 5, "horizon": 5, "minimum_train_days": 10,
              "validation_days": 8, "test_days": 8}
    result.update(changes)
    return result


def by_symbol(report):
    return {r["symbol"]: r for r in report["symbols"]}


def test_short_ipo_history_never_truncates_older_stock_or_backfills_new_stock():
    dates, prices = fixture_prices()
    report = assess_coverage(prices, config(symbol_start_dates={"IPO": dates[-15].strftime("%Y-%m-%d")}))
    rows = by_symbol(report)
    assert rows["OLD"]["n_bars"] == 120
    assert rows["OLD"]["first"] == dates[0].strftime("%Y-%m-%d")
    assert rows["OLD"]["eligible"]
    assert rows["IPO"]["n_bars"] == 15
    assert rows["IPO"]["n_raw_bars"] == 120
    assert rows["IPO"]["removed_before_boundary"] == 105
    assert not rows["IPO"]["eligible"]
    assert rows["IPO"]["usable_feature_rows"] == 0
    assert rows["IPO"]["labeled_rows"] == 0
    assert rows["IPO"]["status"] == "short_history"
    assert rows["SPY"]["n_bars"] == 120
    assert report["eligible_symbols"] == ["OLD"]
    json.dumps(report, allow_nan=False)


def test_explicit_boundaries_are_inclusive_and_change_only_named_history():
    dates, prices = fixture_prices()
    original = prices.copy(deep=True)
    cutoff = dates[50].strftime("%Y-%m-%d")
    filtered, audit = apply_history_boundaries(prices, config(symbol_start_dates={"IPO": cutoff}))
    pd.testing.assert_frame_equal(prices, original)
    pd.testing.assert_frame_equal(filtered.loc[filtered.symbol.ne("IPO")],
                                  prices.loc[prices.symbol.ne("IPO")])
    assert filtered.loc[filtered.symbol.eq("IPO"), "date"].min() == dates[50]
    assert len(filtered.loc[filtered.symbol.eq("IPO")]) == 70
    assert audit[0]["n_removed"] == 50
    assert audit[0]["n_after"] == 70
    assert audit[0]["removed_last"] == dates[49].strftime("%Y-%m-%d")
    assert audit[0]["policy"] == "exclude_pre_boundary_no_backfill"
    json.dumps(audit, allow_nan=False)


def test_no_ipo_dates_are_inferred_or_hardcoded():
    dates, prices = fixture_prices()
    named = prices.copy()
    named.loc[named.symbol.eq("IPO"), "symbol"] = "CRWV"
    filtered, audit = apply_history_boundaries(named, config())
    assert len(filtered.loc[filtered.symbol.eq("CRWV")]) == len(dates)
    assert audit == []


def test_missing_requested_symbols_and_benchmark_are_explicit():
    _, prices = fixture_prices()
    rows = by_symbol(assess_coverage(prices, config()))
    assert rows["MISSING"]["first"] is None
    assert rows["MISSING"]["last"] is None
    assert rows["MISSING"]["n_bars"] == 0
    assert rows["MISSING"]["status"] == "missing_data"
    report = assess_coverage(prices.loc[prices.symbol.ne("SPY")], config())
    assert report["benchmark_first"] is None
    assert not report["eligible_symbols"]
    assert report["feature_assessment"] == "unavailable"
    assert all(not r["eligible"] for r in report["symbols"])
    assert any(w.startswith("benchmark_missing") for w in report["warnings"])


def test_calendar_gaps_reported_without_filling_and_late_start_is_not_a_gap():
    dates, prices = fixture_prices()
    missing = prices.symbol.eq("OLD") & prices.date.eq(dates[60])
    report = assess_coverage(prices.loc[~missing], config(symbol_start_dates={"IPO": dates[25].strftime("%Y-%m-%d")}))
    rows = by_symbol(report)
    assert rows["OLD"]["missing_benchmark_sessions"] == 1
    assert rows["OLD"]["missing_session_dates"] == [dates[60].strftime("%Y-%m-%d")]
    assert rows["OLD"]["n_bars"] == 119
    assert rows["OLD"]["usable_feature_rows"] < 99
    assert rows["IPO"]["missing_benchmark_sessions"] == 0
    assert rows["IPO"]["first"] == dates[25].strftime("%Y-%m-%d")


def test_latest_missing_stock_session_is_distinct_from_interior_gaps():
    dates, prices = fixture_prices()
    filtered = prices.loc[~(prices.symbol.eq("OLD") & prices.date.ge(dates[-3]))]
    rows = by_symbol(assess_coverage(filtered, config()))
    assert rows["OLD"]["stale_benchmark_sessions"] == 3
    assert not rows["OLD"]["latest_session_available"]
    assert rows["OLD"]["missing_benchmark_sessions"] == 0
    assert rows["IPO"]["latest_session_available"]


def test_dates_not_on_benchmark_calendar_are_visible_not_silently_certified():
    _, prices = fixture_prices()
    extra = prices.loc[prices.symbol.eq("OLD")].iloc[[0]].copy()
    extra["date"] = pd.Timestamp("2024-01-06")  # Synthetic weekend observation.
    report = assess_coverage(pd.concat([prices, extra], ignore_index=True), config())
    row = by_symbol(report)["OLD"]
    assert row["non_benchmark_session_dates"] == ["2024-01-06"]
    assert not row["eligible"]


def test_conservative_requirements_include_feature_warmup_and_two_purges():
    _, prices = fixture_prices()
    settings = config(lookback=30, horizon=5, minimum_train_days=120, validation_days=50, test_days=100)
    report = assess_coverage(prices, settings)
    req = report["requirements"]
    assert req["warmup_bars"] == 30
    assert req["label_lookahead_bars"] == 6
    assert req["purge_buffer_bars"] == 12
    assert req["minimum_bars_estimate"] == 318
    assert not report["eligible_symbols"]


def test_normalized_string_dates_match_timestamp_dates_and_boundary_config():
    dates, prices = fixture_prices()
    string_dates = prices.copy()
    string_dates["date"] = string_dates.date.dt.strftime("%Y-%m-%d")
    setting = config(symbol_start_dates={"US.IPO": dates[30].strftime("%Y-%m-%d")})
    first = assess_coverage(prices, setting)
    second = assess_coverage(string_dates, setting)
    assert first == second


def test_duplicate_normalized_symbol_date_and_invalid_dates_rejected():
    _, prices = fixture_prices()
    duplicate = pd.concat([prices, prices.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate_daily_bar"):
        assess_coverage(duplicate, config())
    with pytest.raises(ValueError):
        apply_history_boundaries(prices, config(symbol_start_dates={"IPO": "2025-02-30"}))
    with pytest.raises(ValueError, match="iso_date"):
        apply_history_boundaries(prices, config(symbol_start_dates={"IPO": "2025/02/24"}))


def test_boundary_after_all_history_reports_removal_and_missing_configured_symbol():
    _, prices = fixture_prices()
    filtered, audit = apply_history_boundaries(prices, config(symbol_start_dates={"IPO": "2099-01-01", "NEW": "2025-01-01"}))
    assert "IPO" not in filtered.symbol.values
    records = {r["symbol"]: r for r in audit}
    assert records["IPO"]["n_removed"] == 120
    assert records["IPO"]["observed_first_after"] is None
    assert records["NEW"]["n_before"] == 0
    assert records["NEW"]["n_after"] == 0


def test_missing_ohlc_fields_return_unavailable_assessment_not_fake_feature_counts():
    _, prices = fixture_prices()
    report = assess_coverage(prices[["date", "symbol"]], config())
    assert report["feature_assessment"] == "unavailable"
    assert any(w.startswith("feature_fields_missing") for w in report["warnings"])
    assert by_symbol(report)["OLD"]["usable_feature_rows"] is None
    assert not by_symbol(report)["OLD"]["eligible"]


def test_empty_input_is_json_serializable_and_does_not_manufacture_history():
    prices = pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    report = assess_coverage(prices, config())
    assert all(r["n_bars"] == 0 for r in report["symbols"])
    assert report["eligible_symbols"] == []
    json.dumps(report, allow_nan=False)
