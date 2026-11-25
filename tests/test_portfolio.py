"""Deterministic offline fixtures; none of these prices are market evidence."""
import json

import numpy as np
import pandas as pd
import pytest

from research.portfolio import PortfolioConfig, backtest, make_order_drafts, target_weights


def risk_history():
    dates = pd.bdate_range("2024-01-01", periods=80)
    r = np.where(np.arange(80) % 2, 0.01, -0.01)
    return pd.DataFrame({"A": r, "B": 2 * r, "C": -r}, index=dates)


def fixture_frames():
    dates = pd.bdate_range("2024-01-01", periods=25)
    rows = []
    for i, date in enumerate(dates):
        for symbol in ("A", "B"):
            value = (99 if i % 2 else 101) if i < 10 else 100
            rows.append({"date": date, "symbol": symbol, "open": value, "close": value})
    prices = pd.DataFrame(rows)
    predictions = pd.DataFrame([{"date": d, "symbol": s, "score": 0.01 if s == "A" else 0.0}
                                for d in dates[10:21] for s in ("A", "B")])
    benchmark = pd.DataFrame({"date": dates, "open": 200.0, "close": 200.0})
    cfg = PortfolioConfig(capital=10000, top_k=1, max_weight=0.5,
                          min_cash_weight=0.2, target_annual_vol=10,
                          min_trade_value=0, cost_bps=10)
    return dates, prices, predictions, benchmark, cfg


def test_weights_respect_caps_cash_inverse_volatility_and_threshold():
    history = risk_history()
    weights, diag = target_weights(pd.Series({"A": 0.03, "B": 0.02, "C": 0.001}), history,
                                   PortfolioConfig(top_k=3, max_weight=0.8, target_annual_vol=10))
    assert weights["A"] == pytest.approx(2 * weights["B"])
    assert set(weights) == {"A", "B"}
    assert sum(weights.values()) <= 0.8 + 1e-12
    assert diag["cash_weight"] >= 0.2 - 1e-12
    assert diag["min_expected_excess"] == 0.002
    capped, _ = target_weights(pd.Series({"A": 0.03, "B": 0.02}), history, PortfolioConfig(target_annual_vol=10))
    assert max(capped.values()) <= 0.2


def test_correlated_covariance_risk_is_scaled_without_independence_shortcut():
    hist = risk_history()
    scores = pd.Series({"A": 0.02, "B": 0.01})
    weights, diag = target_weights(scores, hist, PortfolioConfig(top_k=2, max_weight=0.8,
                                                                target_annual_vol=0.03))
    w = np.array([weights[s] for s in diag["covariance_symbols"]])
    covariance = np.asarray(diag["annual_covariance"])
    assert covariance[0, 1] > 0
    assert float(np.sqrt(w @ covariance @ w)) <= 0.03 + 1e-12
    assert diag["risk_scale"] < 1
    assert sum(weights.values()) < 0.8
    assert diag["annual_vol_after_scale"] == pytest.approx(0.03)


def test_recent_shock_has_more_ewma_risk_and_reduces_positions():
    hist = risk_history()[["A"]]
    early, late = hist.copy(), hist.copy()
    early.iloc[-40, 0] = 0.30
    late.iloc[-1, 0] = 0.30
    cfg = PortfolioConfig(max_weight=0.8, target_annual_vol=0.1)
    early_w, early_d = target_weights(pd.Series({"A": 0.02}), early, cfg)
    late_w, late_d = target_weights(pd.Series({"A": 0.02}), late, cfg)
    assert late_d["asset_annual_vol"]["A"] > early_d["asset_annual_vol"]["A"]
    assert late_w["A"] < early_w["A"]


@pytest.mark.parametrize("scores", [{"A": 0.0}, {"A": -0.03}, {"A": 0.002}])
def test_no_economic_signal_is_cash(scores):
    weights, diag = target_weights(pd.Series(scores), risk_history(), PortfolioConfig())
    assert weights == {}
    assert diag["cash_weight"] == 1


def test_invalid_scores_raise_and_missing_history_remains_cash():
    with pytest.raises(ValueError, match="finite"):
        target_weights(pd.Series({"A": np.nan}), risk_history(), None)
    weights, diag = target_weights(pd.Series({"UNKNOWN": 0.02}), risk_history(), None)
    assert weights == {}
    assert diag["excluded"][0]["reason"] == "missing_risk_history"


def test_config_accepts_all_portfolio_settings_and_full_nested_config():
    cfg = {"capital": 10000, "top_k": 2, "max_weight": 0.3, "min_cash_weight": 0.2,
           "target_annual_vol": 0.15, "ewma_decay": 0.9, "cost_bps": 10,
           "rebalance_days": 5, "min_trade_value": 100, "risk_lookback": 60,
           "min_expected_excess": 0.002}
    scores = pd.Series({"A": 0.02})
    assert target_weights(scores, risk_history(), cfg) == target_weights(scores, risk_history(), {"horizon": 5, "portfolio": cfg})
    with pytest.raises(ValueError):
        PortfolioConfig(ewma_decay=1.0)


def test_order_drafts_trade_net_difference_sell_first_and_never_submit():
    cfg = PortfolioConfig(capital=10000, max_weight=0.8, min_trade_value=0)
    orders = make_order_drafts({"A": 0.4, "B": 0.4}, {"A": 100, "B": 100},
                               10000, {"A": 60}, "2024-01-31", "offline-test", cfg)
    assert [r["side"] for r in orders] == ["SELL", "BUY"]
    assert orders[0]["quantity"] < 60  # Sell only the difference, not the entire book.
    cash = 10000 - 6000
    for order in orders:
        assert order["quantity"] == abs(order["quantity_delta"])
        assert isinstance(order["quantity"], int)
        assert order["reference_only"] and order["requires_requote"] and order["no_submit"]
        assert order["account_scope"] == "independent_simulated_portfolio"
        cash -= order["quantity_delta"] * order["reference_price"] + order["estimated_one_way_cost"]
    assert cash >= 2000 - 1e-8
    json.dumps(orders, allow_nan=False)


def test_order_budget_includes_fees_even_when_cash_floor_is_zero():
    cfg = PortfolioConfig(max_weight=1, min_cash_weight=0, min_trade_value=0, cost_bps=100)
    orders = make_order_drafts({"A": 1}, {"A": 100}, 1000, config=cfg)
    assert orders[0]["quantity"] == 9
    assert sum(r["estimated_notional"] + r["estimated_one_way_cost"] for r in orders) <= 1000


def test_order_prices_do_not_select_future_close_or_fill_absent_history():
    prices = pd.DataFrame({"date": ["2024-01-01", "2024-01-03"], "symbol": ["A", "A"], "close": [100, 200]})
    cfg = PortfolioConfig(max_weight=0.8, min_trade_value=0)
    orders = make_order_drafts({"A": 0.5}, prices, 10000, as_of="2024-01-02", config=cfg)
    assert orders[0]["reference_price"] == 100
    with pytest.raises(ValueError, match="Missing"):
        make_order_drafts({"A": 0.5}, prices, 10000, as_of="2023-12-31", config=cfg)


def test_backtest_next_open_and_five_session_rebalance_calendar():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    prices.loc[(prices["date"] == dates[11]) & (prices["symbol"] == "A"), ["open", "close"]] = [125, 130]
    result = backtest(prices, predictions, benchmark, cfg)
    first = result["trades"][0]
    assert first["signal_date"] == dates[10].strftime("%Y-%m-%d")
    assert first["date"] == dates[11].strftime("%Y-%m-%d")
    assert first["price"] == 125
    assert [r["execution_date"] for r in result["rebalances"]] == [dates[i].strftime("%Y-%m-%d") for i in (11, 16, 21)]
    assert result["series"][0]["holdings"] == {}
    assert [r["date"] for r in result["series"]] == [d.strftime("%Y-%m-%d") for d in dates[10:]]
    json.dumps(result, allow_nan=False)


def test_backtest_cost_is_exactly_once_and_flat_hold_has_no_repeated_cost():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    result = backtest(prices, predictions, benchmark, cfg)
    assert len(result["trades"]) == 1
    cost = sum(t["notional"] * cfg.cost_bps / 10000 for t in result["trades"])
    assert result["metrics"]["total_cost"] == pytest.approx(cost)
    assert result["series"][-1]["equity"] == pytest.approx(cfg.capital - cost)
    assert result["series"][-1]["cash"] >= 0.2 * cfg.capital


def test_future_prices_do_not_change_first_signal_risk_or_target():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    before = backtest(prices, predictions, benchmark, cfg)
    altered = prices.copy()
    altered.loc[altered["date"] >= dates[12], ["open", "close"]] *= 3
    after = backtest(altered, predictions, benchmark, cfg)
    assert before["rebalances"][0]["weights"] == after["rebalances"][0]["weights"]
    assert before["rebalances"][0]["diagnostics"] == after["rebalances"][0]["diagnostics"]


def test_holdings_drift_revalued_at_rebalance_and_benchmark_holds_from_same_open():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    prices.loc[(prices["date"] >= dates[12]) & (prices["symbol"] == "A"), ["open", "close"]] = 120
    benchmark.loc[benchmark["date"] >= dates[11], "open"] = 250
    benchmark.loc[benchmark["date"] >= dates[11], "close"] = 260
    result = backtest(prices, predictions, benchmark, cfg)
    first_qty = result["trades"][0]["target_quantity"]
    first_cash = result["trades"][0]["cash_after"]
    assert result["rebalances"][1]["pre_trade_equity"] == pytest.approx(first_cash + first_qty * 120)
    assert result["series"][1]["benchmark_equity"] == pytest.approx(cfg.capital / 250 * 260)
    assert result["series"][-1]["benchmark_equity"] == result["series"][1]["benchmark_equity"]


def test_missing_execution_price_raises_without_future_fill():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    missing = prices.loc[~((prices["date"] == dates[11]) & (prices["symbol"] == "A"))]
    with pytest.raises(ValueError, match="Missing next-open"):
        backtest(missing, predictions, benchmark, cfg)


def test_last_day_signal_cannot_trade_without_next_open():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    terminal = predictions.loc[predictions["date"] == dates[20]].copy()
    terminal["date"] = dates[-1]
    result = backtest(prices, terminal, benchmark, cfg)
    assert result["trades"] == []
    assert result["rebalances"] == []
    assert result["series"][-1]["equity"] == cfg.capital


def test_all_zero_signal_backtest_stays_cash():
    dates, prices, predictions, benchmark, cfg = fixture_frames()
    predictions["score"] = 0
    result = backtest(prices, predictions, benchmark, cfg)
    assert result["trades"] == []
    assert all(s["equity"] == cfg.capital and s["cash_weight"] == 1 for s in result["series"])
