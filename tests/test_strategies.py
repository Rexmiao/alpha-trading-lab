"""Constructed OHLCV fixtures only; no market data, broker or account access."""
import json

import numpy as np
import pandas as pd
import pytest

from hf_space.strategies import (STRATEGY_IDS, _parameters, _risk_allocation,
                                 _rule_signals, run_strategy_comparison)
from research.portfolio import PortfolioConfig, backtest, target_weights


def fixture_prices(periods=140, n_assets=6, declining=False):
    dates = pd.bdate_range("2020-01-02", periods=periods)
    rows = []
    for index, symbol in enumerate(["SPY"] + [f"A{x}" for x in range(n_assets)]):
        base = 70. + index * 10
        for offset, day in enumerate(dates):
            trend = (-.001 - index * .0001) if declining and index else .0003 + index * .0001
            close = base * np.exp(trend * offset + .004 * np.sin(offset * (1 + index * .1)))
            opening = close * (1 + .001 * np.cos(offset))
            rows.append({"date": day, "symbol": symbol, "open": opening,
                "high": max(opening, close) * 1.002, "low": min(opening, close) * .998,
                "close": close, "volume": 100000. + index})
    return pd.DataFrame(rows).sort_values(["date", "symbol"]).reset_index(drop=True)


def compare(prices, **kwargs):
    parameters = dict(benchmark="SPY", source="uploaded_csv", lookback=10,
        fast_window=3, slow_window=8, entry_window=5, exit_window=2, test_sessions=30)
    parameters.update(kwargs)
    return run_strategy_comparison(prices, **parameters)


def configuration(**kwargs):
    values = dict(rebalance_days=5, cost_bps=10, max_weight=.2, target_vol=.15,
        lookback=10, fast_window=3, slow_window=8, entry_window=5, exit_window=2, test_sessions=30)
    values.update(kwargs)
    return _parameters(**values)


def test_complete_comparison_has_same_dates_windows_cash_start_and_json_contract():
    result = compare(fixture_prices())
    assert result["status"] == "success"
    assert {row["strategy"] for row in result["metrics"]} == set(STRATEGY_IDS)
    all_dates = []
    for strategy in STRATEGY_IDS:
        curve = [row for row in result["equity"] if row["strategy"] == strategy]
        assert len(curve) == 30
        assert curve[0]["holdings"] == {}
        assert curve[0]["equity"] == 100000.
        all_dates.append([row["date"] for row in curve])
        weights = [row for row in result["weights"] if row["strategy"] == strategy]
        assert sum(row["weight"] for row in weights) == pytest.approx(1.)
        assert any(row["kind"] == "cash" and row["symbol"] == "__CASH__" for row in weights)
    assert all(sequence == all_dates[0] for sequence in all_dates)
    assert result["lineage"]["evaluation"]["warmup_bars"] == 61
    assert result["lineage"]["config"]["test_sessions"] == 30
    assert "hf_space/strategies.py" in result["lineage"]["code_sha256"]
    json.dumps(result, allow_nan=False)


def test_future_bars_do_not_change_past_factors_states_or_targets():
    prices = fixture_prices()
    dates = prices.date.unique()
    cutoff = dates[124]
    changed = prices.copy()
    future = changed.date.gt(cutoff) & changed.symbol.ne("SPY")
    changed.loc[future, ["open", "high", "low", "close"]] *= 1.4
    before, after = compare(prices), compare(changed)
    old = [row for row in before["signals"] if row["date"] <= str(cutoff)[:10]]
    new = [row for row in after["signals"] if row["date"] <= str(cutoff)[:10]]
    assert old == new
    old_rebalances = [row for row in before["rebalances"] if row["signal_date"] <= str(cutoff)[:10]]
    new_rebalances = [row for row in after["rebalances"] if row["signal_date"] <= str(cutoff)[:10]]
    assert [(row["strategy"], row["weights"], row["diagnostics"]) for row in old_rebalances] == [
        (row["strategy"], row["weights"], row["diagnostics"]) for row in new_rebalances]


def test_appending_future_history_keeps_existing_rule_records_identical():
    prices = fixture_prices()
    last = prices.date.unique()[110]
    config = configuration()
    prefix = _rule_signals(prices.loc[prices.date.le(last)], "SPY", config)
    full = _rule_signals(prices, "SPY", config)
    pd.testing.assert_frame_equal(prefix.reset_index(drop=True),
        full.loc[full.date.le(last)].reset_index(drop=True))


def test_channel_excludes_today_high_retains_state_and_exits_on_previous_low():
    prices = fixture_prices(n_assets=3)
    dates = sorted(prices.date.unique())
    levels = {65: (105., 110., 104.5), 66: (104., 104.5, 103.5), 67: (99., 99.5, 98.5)}
    for offset in range(65):
        mask = prices.symbol.eq("A0") & prices.date.eq(dates[offset])
        value = 100. + .1 * (-1)**offset
        prices.loc[mask, ["open", "close", "high", "low"]] = [value, value, value + .2, value - .2]
    for offset, (close, high, low) in levels.items():
        mask = prices.symbol.eq("A0") & prices.date.eq(dates[offset])
        prices.loc[mask, ["open", "close", "high", "low"]] = [close, close, high, low]
    signals = _rule_signals(prices, "SPY", configuration())
    channel = signals.loc[signals.symbol.eq("A0") & signals.strategy.eq("channel_breakout")].set_index("date")
    assert channel.loc[dates[65], "event"] == "entry"  # Its own high=110 cannot suppress entry.
    assert channel.loc[dates[65], "eligible"]
    assert channel.loc[dates[66], "event"] == "hold"
    assert channel.loc[dates[66], "eligible"]
    assert channel.loc[dates[66], "score"] < 0  # Negative distance does not erase latched state.
    assert channel.loc[dates[67], "event"] == "exit"
    assert not channel.loc[dates[67], "eligible"]


def test_cross_sectional_selects_top_four_even_if_all_returns_negative():
    result = compare(fixture_prices(declining=True), cost_bps=50)
    latest = result["lineage"]["latest_weights_as_of"]
    selected = [row for row in result["signals"] if row["date"] == latest
        and row["strategy"] == "cross_sectional_momentum" and row["eligible"]]
    assert len(selected) == 4
    assert all(row["score"] < 0 for row in selected)
    assert all(row["score_unit"] == "historical_simple_return" for row in selected)
    assert [row for row in result["weights"] if row["strategy"] == "cross_sectional_momentum" and row["kind"] == "asset"]
    assert not [row for row in result["weights"] if row["strategy"] == "time_series_momentum" and row["kind"] == "asset"]
    assert result["lineage"]["latest_risk"]["cross_sectional_momentum"]["expected_return_gate"] is None


def test_rule_allocator_matches_shared_ewma_risk_math_without_forecast_gate():
    history = pd.DataFrame({"A": np.tile([.01, -.01], 40),
                            "B": np.tile([.02, -.02], 40)}, index=pd.bdate_range("2020-01-02", periods=80))
    cfg = PortfolioConfig(max_weight=.4, target_annual_vol=.03)
    weights, diag = _risk_allocation(["A", "B"], history, cfg)
    reference, original = target_weights(pd.Series({"A": .02, "B": .01}), history, cfg)
    assert weights == reference
    assert diag["annual_covariance"] == original["annual_covariance"]
    assert diag["annual_vol_after_scale"] <= .03 + 1e-12
    assert diag["risk_scale"] < 1
    assert diag["cash_weight"] >= .2


def test_cost_is_once_per_executed_side_and_integer_cash_is_feasible():
    prices = fixture_prices()
    result = compare(prices, cost_bps=25)
    for metric in result["metrics"]:
        trades = [row for row in result["trades"] if row["strategy"] == metric["strategy"]]
        assert metric["total_cost"] == pytest.approx(sum(row["notional"] * 25 / 10000 for row in trades))
        for trade in trades:
            assert isinstance(trade["quantity"], int)
            assert trade["cash_after"] >= -1e-7
        for rebalance in [row for row in result["rebalances"] if row["strategy"] == metric["strategy"]]:
            assert sum(rebalance["weights"].values()) <= .8 + 1e-12
            assert all(weight <= .2 + 1e-12 for weight in rebalance["weights"].values())
            assert rebalance["post_trade_equity"] == pytest.approx(rebalance["pre_trade_equity"] - rebalance["cost"])
    free = compare(prices, cost_bps=0)
    assert all(metric["total_cost"] == 0 for metric in free["metrics"])


def test_only_anchor_signals_trade_next_open_and_final_signal_does_not_execute():
    prices = fixture_prices()
    result = compare(prices, test_sessions=31)
    dates = sorted(prices.date.unique())
    expected_signals = dates[-31::5]
    expected_execution = [dates[dates.index(day) + 1] for day in expected_signals if day != dates[-1]]
    for strategy in STRATEGY_IDS:
        logs = [row for row in result["rebalances"] if row["strategy"] == strategy]
        assert [row["execution_date"] for row in logs] == [str(day)[:10] for day in expected_execution]
    for trade in result["trades"]:
        expected = prices.loc[prices.symbol.eq(trade["symbol"]) & prices.date.eq(pd.Timestamp(trade["date"])), "open"].item()
        assert trade["price"] == expected
        assert trade["date"] > trade["signal_date"]
    final = [row for row in result["signals"] if row["date"] == str(dates[-1])[:10]]
    assert final and all(not row["execution_available"] for row in final)
    assert any(not row["rebalance_signal"] for row in result["signals"])


def test_gap_and_new_listing_have_explicit_shared_warmup_status_no_price_fill():
    prices = fixture_prices(n_assets=3)
    dates = sorted(prices.date.unique())
    keep = ~((prices.symbol.eq("A0") & prices.date.eq(dates[-5])) |
             (prices.symbol.eq("A1") & prices.date.lt(dates[-25])))
    result = compare(prices.loc[keep])
    gap = [row for row in result["signals"] if row["symbol"] == "A0" and row["date"] == str(dates[-5])[:10]]
    assert len(gap) == 4 and all(row["status"] == "missing_bar" and not row["eligible"] for row in gap)
    recent_ipo = [row for row in result["signals"] if row["symbol"] == "A1"]
    assert all(row["status"] in {"missing_bar", "insufficient_history"} and not row["eligible"] for row in recent_ipo)
    assert any(metric["status"] == "failed" and "Missing held-position" in metric["error"] for metric in result["metrics"])


def test_too_short_input_does_not_substitute_different_strategy_windows():
    result = compare(fixture_prices(periods=80), test_sessions=30)
    assert result["status"] == "insufficient_history"
    assert len(result["metrics"]) == 4
    assert all(row["status"] == "insufficient_history" and row["total_return"] is None for row in result["metrics"])
    assert result["equity"] == [] and result["weights"] == []
    assert not result["lineage"]["evaluation"]["benchmark_warmup_sufficient"]


def test_all_new_listings_fail_with_explicit_insufficient_history():
    prices = fixture_prices(n_assets=3)
    cutoff = sorted(prices.date.unique())[-20]
    limited = prices.loc[prices.symbol.eq("SPY") | prices.date.ge(cutoff)]
    result = compare(limited)
    assert result["status"] == "insufficient_history"
    assert result["equity"] == []


@pytest.mark.parametrize("changes", [{"source": "unknown"}, {"fast_window": 10, "slow_window": 5},
    {"cost_bps": 51}, {"rebalance_days": 0}, {"test_sessions": 1}])
def test_invalid_parameters_are_rejected(changes):
    with pytest.raises(ValueError):
        compare(fixture_prices(), **changes)


def test_daily_validation_rejects_duplicate_intraday_and_nonfinite_input():
    prices = fixture_prices()
    with pytest.raises(ValueError, match="Duplicate"):
        compare(pd.concat([prices, prices.iloc[:1]], ignore_index=True))
    intraday = prices.copy()
    intraday.loc[0, "date"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="daily dates"):
        compare(intraday)
    invalid = prices.copy()
    invalid.loc[0, "close"] = np.nan
    with pytest.raises(ValueError, match="Missing"):
        compare(invalid)


def test_callback_backtest_receives_only_past_and_rejects_excess_weights():
    prices = fixture_prices()
    bench = prices.loc[prices.symbol.eq("SPY")]
    stocks = prices.loc[prices.symbol.ne("SPY")]
    dates = sorted(prices.date.unique())
    predictions = pd.DataFrame({"date": dates[-20:], "symbol": "A0", "score": -100.})
    received = []

    def allocate(scores, history, config):
        received.append(history.index.max())
        return {"A0": .2}, {"not_a_return_forecast": True}

    result = backtest(stocks, predictions, bench, allocation_fn=allocate)
    assert received == [pd.Timestamp(row["signal_date"]) for row in result["rebalances"]]
    assert result["trades"]  # Negative raw scores do not pass through forecast gating.
    with pytest.raises(ValueError, match="position cap"):
        backtest(stocks, predictions, bench, allocation_fn=lambda scores, history, cfg: ({"A0": .9}, {}))
