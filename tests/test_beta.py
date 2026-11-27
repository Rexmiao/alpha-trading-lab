"""Independent financial invariants for the daily Beta comparison engine."""
from copy import deepcopy
import json

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from hf_space import beta


@pytest.fixture(scope="module")
def prices():
    dates = xcals.get_calendar("XNYS", start="2022-01-01", end="2025-12-31").sessions[:500]
    rng = np.random.default_rng(173)
    market = rng.normal(.0003, .009, len(dates))
    rows = []
    for number in range(21):
        symbol = "SPY" if number == 20 else f"S{number:02d}"
        returns = market if symbol == "SPY" else .0001 + (.2 + number * .1) * market + rng.normal(0, .00008, len(dates))
        closes = (80. + number) * np.cumprod(1 + returns)
        opens = np.r_[80. + number, closes[:-1]] * (1 + .0002 * np.sin(np.arange(len(dates))))
        for day, op, close in zip(dates, opens, closes):
            rows.append({"date": day.date().isoformat(), "symbol": symbol, "open": op,
                         "high": max(op, close)*1.001, "low": min(op, close)*.999,
                         "close": close, "volume": 10000.})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def report(prices):
    return beta.run_beta_comparison(prices, beta_window=126, test_sessions=126)


def test_ols_recovers_centered_slope_intercept_and_residual_uncertainty():
    x = np.linspace(-.02, .03, 126)
    observed = beta.estimate_ols_beta(.0007 + 1.8*x, x)
    assert observed["beta"] == pytest.approx(1.8)
    assert observed["intercept_per_day"] == pytest.approx(.0007)
    assert observed["correlation"] == pytest.approx(1)
    assert observed["r_squared"] == pytest.approx(1)
    assert observed["standard_error"] < 1e-12
    assert observed["residual_vol"] < 1e-12
    assert observed["nobs"] == 126


def test_beta_is_not_relative_total_volatility():
    x = np.tile([-.01, -.01, .01, .01], 40)
    independent = np.tile([-.03, .03, -.03, .03], 40)
    observed = beta.estimate_ols_beta(.3*x+independent, x)
    assert observed["beta"] == pytest.approx(.3)
    assert observed["annual_vol"] > np.std(x, ddof=1)*np.sqrt(252)
    assert observed["correlation"] < .2


def test_finite_but_overflowing_returns_cannot_publish_successful_beta():
    with pytest.raises(beta.BetaError, match="numerical bounds"):
        beta.estimate_ols_beta([.1, -.1, .2, -.2], [1e300, -1e300, 1e300, -1e300])


def test_correlation_does_not_overflow_its_finite_squared_sums_product():
    x = np.array([1e100, -1e100, 2e100, -2e100])
    observed = beta.estimate_ols_beta(x, x)
    assert observed["beta"] == pytest.approx(1.)
    assert observed["correlation"] == pytest.approx(1.)
    assert observed["r_squared"] == pytest.approx(1.)


def test_extreme_annualization_fails_without_infinite_performance():
    with pytest.raises(beta.BetaError, match="numerical bounds"):
        beta._annualized_return(1e200, 20)
    assert beta._annualized_return(1., 20) == 0


@pytest.mark.parametrize("x,y", [([0, 0, 0], [1, 2, 3]), ([1, 2], [1, 2]),
                                  ([.01, .02, np.nan], [.1, .2, .3])])
def test_invalid_ols_has_no_silent_dropping_or_fake_zero_beta(x, y):
    with pytest.raises(beta.BetaError):
        beta.estimate_ols_beta(y, x)


def test_csv_round_trip_is_strict_and_does_not_load_paths(prices):
    parsed = beta.parse_beta_csv(prices.to_csv(index=False).encode())
    assert len(parsed) == len(prices)
    with pytest.raises(beta.BetaError):
        beta.parse_beta_csv("D:/private.csv")
    with pytest.raises(beta.BetaError):
        beta.parse_beta_csv(b"\xff\xfe")


@pytest.mark.parametrize("change", ["duplicate", "holiday", "gap", "ohlc", "boolean", "symbol", "date_time"])
def test_price_validation_refuses_ambiguous_daily_inputs(prices, change):
    data = prices.copy()
    if change == "duplicate":
        data = pd.concat([data, data.iloc[:1]])
    elif change == "holiday":
        data.loc[data.date.eq(data.date.iloc[0]), "date"] = "2022-01-01"
    elif change == "gap":
        day = sorted(data.date.unique())[200]
        data = data.loc[~data.date.eq(day)]
    elif change == "ohlc":
        data.loc[0, "high"] = data.loc[0, "low"] / 2
    elif change == "boolean":
        data["volume"] = data.volume.astype(object)
        data.loc[0, "volume"] = True
    elif change == "symbol":
        data.loc[0, "symbol"] = "https://example.invalid"
    else:
        data.loc[0, "date"] += "T00:00:00Z"
    with pytest.raises(beta.BetaError):
        beta.run_beta_comparison(data, test_sessions=126)


def test_incomplete_exchange_day_is_rejected(prices, monkeypatch):
    monkeypatch.setattr(beta, "_now_utc", lambda: pd.Timestamp(max(prices.date), tz="UTC"))
    with pytest.raises(beta.BetaError, match="not-yet-completed"):
        beta.run_beta_comparison(prices, test_sessions=126)


def test_five_portfolios_share_dates_real_costs_and_ordinary_metrics(report):
    assert report["status"] == "success"
    assert {m["strategy"] for m in report["metrics"]} == set(beta.STRATEGY_IDS)
    curves = pd.DataFrame(report["equity"])
    for strategy in beta.STRATEGY_IDS:
        part = curves.loc[curves.strategy.eq(strategy)]
        assert len(part) == 126
        assert part.date.tolist() == curves.loc[curves.strategy.eq("spy_100"), "date"].tolist()
        assert part.cash.ge(0).all()
        metric = next(m for m in report["metrics"] if m["strategy"] == strategy)
        trades = [t for t in report["trades"] if t["strategy"] == strategy]
        assert metric["total_costs"] == pytest.approx(sum(t["notional"]*.001 for t in trades))
        assert metric["trade_count"] == len(trades)
        assert metric["total_return"] == pytest.approx(part.equity.iloc[-1]/100000-1)
        assert metric["alpha"] is None
    json.dumps(report, allow_nan=False)


def test_quantiles_are_based_on_signal_time_beta_and_equal_sized(report):
    first = {r["strategy"]: r for r in report["rebalances"] if r["kind"] == "evaluation_initialization"}
    assert set(first["high_beta"]["targets"]) == {"S16", "S17", "S18", "S19"}
    assert set(first["low_beta"]["targets"]) == {"S00", "S01", "S02", "S03"}
    assert len(first["equal_weight"]["targets"]) == 20
    assert sum(first["high_beta"]["targets"].values()) == pytest.approx(.8)


def test_spy_is_exempt_from_individual_stock_cap(report):
    grouped = {r["strategy"]: r for r in report["rebalances"] if r["kind"] == "evaluation_initialization"}
    assert grouped["spy_100"]["targets"] == {"SPY": 1.}
    assert grouped["spy_80"]["targets"] == {"SPY": .8}
    actual = {r["strategy"]: r["weight"] for r in report["weights"] if r["symbol"] == "SPY"}
    assert actual["spy_100"] > .95 and actual["spy_80"] > .7
    assert abs(next(m for m in report["metrics"] if m["strategy"] == "spy_100")["realized_beta"]-1) < .01


def test_monthly_rotation_can_leave_sold_stocks_without_demanding_zero_position_quotes(prices):
    """Three disjoint model selections must execute on one persistent book."""
    frame = beta.parse_beta_csv(prices.to_csv(index=False).encode())
    opens = frame.pivot(index="date", columns="symbol", values="open")
    closes = frame.pivot(index="date", columns="symbol", values="close")
    dates = closes.index
    start = len(dates)-126
    calendar = xcals.get_calendar("XNYS", start=dates[0], end="2025-12-31")
    formations = {start: (start-1, "evaluation_initialization")}
    for index in range(start, len(dates)-1):
        if pd.Timestamp(calendar.next_session(dates[index])).month != dates[index].month:
            formations[index+1] = (index, "calendar_month_end")
    # Keep three actual execution points so this tests full liquidation of A,
    # subsequent liquidation of B, and a new C allocation on the same ledger.
    formations = dict(list(formations.items())[:3])
    groups = [{f"S{i:02d}" for i in range(16, 20)},
              {f"S{i:02d}" for i in range(12, 16)},
              {f"S{i:02d}" for i in range(8, 12)}]
    measurements = {index: {f"S{i:02d}": {"symbol": f"S{i:02d}", "status": "success", "beta": .5}
                            for i in range(20)} for index in range(start-1, len(dates))}
    for group, (signal, _) in zip(groups, formations.values()):
        for symbol in group:
            measurements[signal][symbol]["beta"] = 2.
    config = {"capital": 100000., "cost_bps": 10., "max_weight": .2,
              "evaluation_indices": list(range(start, len(dates)))}
    metric, curves, trades, rebalances, weights, targets = beta._simulate(
        "high_beta", dates, opens, closes, measurements, formations, config, "SPY")
    assert metric["status"] == "success" and len(rebalances) == 3
    assert {row["symbol"] for row in weights if row["kind"] == "asset"} == groups[-1]
    final_execution = dates[list(formations)[-1]].date().isoformat()
    assert all(row["symbol"] not in groups[0] for row in trades if row["execution_date"] == final_execution)
    assert all(row["cash"] >= 0 for row in curves)


def test_month_end_close_signal_executes_next_session_open(report, prices):
    dates = list(sorted(prices.date.unique()))
    cal = xcals.get_calendar("XNYS", start=dates[0], end="2025-12-31")
    for row in report["rebalances"]:
        assert dates.index(row["execution_date"]) == dates.index(row["signal_date"])+1
        if row["kind"] == "calendar_month_end":
            assert pd.Timestamp(cal.next_session(row["signal_date"])).month != pd.Timestamp(row["signal_date"]).month
    assert all(t["signal_date"] < t["execution_date"] for t in report["trades"])


def test_price_jumps_are_flagged_not_repaired(prices):
    data = prices.copy()
    last = data.date.max()
    chosen = data.symbol.eq("S19") & data.date.eq(last)
    data.loc[chosen, ["open", "high", "low", "close"]] *= 2
    result = beta.run_beta_comparison(data, test_sessions=126)
    assert any("exceed 30%" in value for value in result["warnings"])
    last_values = next(r for r in result["estimates"] if r["symbol"] == "S19")
    assert last_values["annual_vol"] > .3


def test_missing_past_price_excludes_history_without_future_eligibility_filter(prices):
    data = prices.copy()
    cut = sorted(data.date.unique())[-126-50]
    data = data.loc[~(data.symbol.eq("S00") & data.date.eq(cut))]
    with pytest.raises(beta.BetaError, match="At least 20"):
        beta.run_beta_comparison(data, test_sessions=126)


def test_missing_held_close_fails_strategy_without_fabricating_exit(prices, report):
    # Last day isolates held-price failure before another monthly formation
    # would independently fail the twenty-stock qualification threshold.
    day = report["config"]["evaluation_end"]
    data = prices.loc[~(prices.symbol.eq("S19") & prices.date.eq(day))]
    result = beta.run_beta_comparison(data, test_sessions=126)
    high = next(m for m in result["metrics"] if m["strategy"] == "high_beta")
    assert high["status"] == "failed"
    assert "Missing held" in high["error"]
    assert not any(t["strategy"] == "high_beta" for t in result["trades"])


def test_append_future_preserves_earlier_measurements_signals_and_trades(prices):
    days = sorted(prices.date.unique())
    before = beta.run_beta_comparison(prices.loc[prices.date.le(days[-21])], test_sessions=126)
    after = beta.run_beta_comparison(prices, test_sessions=146)
    end = days[-21]
    assert before["beta_history"] == [r for r in after["beta_history"] if r["date"] <= end]
    assert before["trades"] == [r for r in after["trades"] if r["execution_date"] <= end]
    assert before["rebalances"] == [r for r in after["rebalances"] if r["execution_date"] <= end]
    assert before["equity"] == [r for r in after["equity"] if r["date"] <= end]


def test_higher_costs_reduce_terminal_equity_for_same_price_path(prices):
    free = beta.run_beta_comparison(prices, cost_bps=0, test_sessions=126)
    costly = beta.run_beta_comparison(prices, cost_bps=30, test_sessions=126)
    for left, right in zip(free["metrics"], costly["metrics"]):
        assert left["strategy"] == right["strategy"]
        assert left["final_equity"] > right["final_equity"]


def test_no_fictitious_final_trade_and_current_weights_are_distinct_from_targets(report):
    final = report["config"]["evaluation_end"]
    assert all(t["side"] != "SELL" or t["execution_date"] != final for t in report["trades"])
    assert any(w["kind"] == "asset" and w["quantity"] > 0 for w in report["weights"])
    assert all(row["scope"] == "last_executed_rebalance_target_not_current_weight" for row in report["latest_targets"])
    for strategy in beta.STRATEGY_IDS:
        assert sum(w["weight"] for w in report["weights"] if w["strategy"] == strategy) == pytest.approx(1.)


def test_run_refuses_source_fallback_and_busy_worker(prices):
    with pytest.raises(beta.BetaError, match="Source"):
        beta.run_beta_comparison(prices, source="synthetic")
    assert beta._SIMULATION_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(beta.BetaError, match="busy"):
            beta.run_beta_comparison(prices)
    finally:
        beta._SIMULATION_LOCK.release()
