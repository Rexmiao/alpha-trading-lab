"""Daily rule comparisons, entirely in memory; no broker or order submission.

Factors below are historical observations/rule states, never forecasts of future
excess return. All four rules share the same evaluation dates, warmup eligibility,
integer-share next-open simulator and risk/cost policy.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from hf_space.engine import (_CODE_SHA256, _DEPENDENCIES, _SIMULATION_LOCK, _integer,
                             _json_safe, _number, _symbol, _validate_prices)
from research.portfolio import PortfolioConfig, backtest


STRATEGY_IDS = (
    "cross_sectional_momentum", "time_series_momentum",
    "moving_average_trend", "channel_breakout",
)
_STRATEGIES_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _parameters(rebalance_days, cost_bps, max_weight, target_vol, lookback,
                fast_window, slow_window, entry_window, exit_window, test_sessions):
    result = {
        "rebalance_days": _integer(rebalance_days, "rebalance_days", 1, 20),
        "cost_bps": _number(cost_bps, "cost_bps", 0, 50),
        "max_weight": _number(max_weight, "max_weight", .1, .4),
        "target_vol": _number(target_vol, "target_vol", .05, .3),
        "lookback": _integer(lookback, "lookback", 2, 252),
        "fast_window": _integer(fast_window, "fast_window", 2, 252),
        "slow_window": _integer(slow_window, "slow_window", 3, 400),
        "entry_window": _integer(entry_window, "entry_window", 2, 252),
        "exit_window": _integer(exit_window, "exit_window", 2, 252),
        "test_sessions": _integer(test_sessions, "test_sessions", 2, 252),
        "top_k_cross_sectional": 4, "risk_lookback": 60,
        "min_cash_weight": .2, "ewma_decay": .94, "capital": 100000., "min_trade_value": 0.,
    }
    if result["fast_window"] >= result["slow_window"]:
        raise ValueError("fast_window must be smaller than slow_window.")
    if result["exit_window"] > result["entry_window"]:
        raise ValueError("exit_window must not exceed entry_window.")
    result["common_warmup_bars"] = max(
        result["lookback"] + 1, result["slow_window"],
        result["entry_window"] + 1, result["exit_window"] + 1,
        result["risk_lookback"] + 1)
    return result


def _rule_signals(prices, benchmark, config):
    """Causal factors on the benchmark calendar; no price filling or row shifts.

    Breakout state is warmed on prior observed bars but no position is opened
    before evaluation. Missing windows preserve its latent state and block
    eligibility; they are never interpreted as an exit signal.
    """
    dates = pd.DatetimeIndex(prices.loc[prices.symbol.eq(benchmark), "date"])
    stocks = prices.loc[~prices.symbol.eq(benchmark)]
    symbols = sorted(stocks.symbol.unique())
    matrices = {column: stocks.pivot(index="date", columns="symbol", values=column)
                .reindex(index=dates, columns=symbols) for column in ("close", "high", "low")}
    close, high, low = (matrices[x] for x in ("close", "high", "low"))
    present = close.notna()
    common_ready = present.rolling(config["common_warmup_bars"],
        min_periods=config["common_warmup_bars"]).sum().eq(config["common_warmup_bars"])
    momentum = close / close.shift(config["lookback"]) - 1
    momentum_ready = present.rolling(config["lookback"] + 1,
        min_periods=config["lookback"] + 1).sum().eq(config["lookback"] + 1)
    momentum = momentum.where(momentum_ready)
    fast = close.rolling(config["fast_window"], min_periods=config["fast_window"]).mean()
    slow = close.rolling(config["slow_window"], min_periods=config["slow_window"]).mean()
    entry = high.shift(1).rolling(config["entry_window"], min_periods=config["entry_window"]).max()
    exit_level = low.shift(1).rolling(config["exit_window"], min_periods=config["exit_window"]).min()
    channel_active = {symbol: False for symbol in symbols}
    records = []
    for day in dates:
        ranked = sorted((symbol for symbol in symbols if common_ready.at[day, symbol]
                         and pd.notna(momentum.at[day, symbol])),
                        key=lambda symbol: (-float(momentum.at[day, symbol]), symbol))
        selected = set(ranked[:config["top_k_cross_sectional"]])
        for symbol in symbols:
            current = close.at[day, symbol]
            mom, ma = momentum.at[day, symbol], slow.at[day, symbol]
            channel_ok = all(pd.notna(x) for x in
                             (current, entry.at[day, symbol], exit_level.at[day, symbol]))
            channel_event = "missing_window"
            if channel_ok:
                if channel_active[symbol] and current < exit_level.at[day, symbol]:
                    channel_active[symbol] = False
                    channel_event = "exit"
                elif not channel_active[symbol] and current > entry.at[day, symbol]:
                    channel_active[symbol] = True
                    channel_event = "entry"
                else:
                    channel_event = "hold" if channel_active[symbol] else "off"
            rules = {
                "cross_sectional_momentum": (mom, symbol in selected, "historical_simple_return",
                                              "rank_selected" if symbol in selected else "not_selected"),
                "time_series_momentum": (mom, pd.notna(mom) and mom > 0,
                                          "historical_simple_return", "positive" if pd.notna(mom) and mom > 0 else "off"),
                "moving_average_trend": (current / ma - 1 if pd.notna(ma) and pd.notna(current) else np.nan,
                    pd.notna(ma) and pd.notna(current) and pd.notna(fast.at[day, symbol])
                    and current > ma and fast.at[day, symbol] > ma,
                    "close_to_slow_average_fraction", "trend_on" if pd.notna(ma) and pd.notna(current)
                    and current > ma and fast.at[day, symbol] > ma else "off"),
                "channel_breakout": (current / entry.at[day, symbol] - 1 if channel_ok else np.nan,
                    channel_active[symbol], "close_to_previous_entry_high_fraction", channel_event),
            }
            for strategy, (factor, active, unit, event) in rules.items():
                if pd.isna(current):
                    status = "missing_bar"
                elif not common_ready.at[day, symbol] or not np.isfinite(factor):
                    status = "insufficient_history"
                elif active:
                    status = "eligible"
                else:
                    status = "not_selected" if strategy == "cross_sectional_momentum" else "rule_off"
                records.append({"date": day, "symbol": symbol, "strategy": strategy,
                    "score": float(factor) if np.isfinite(factor) else None,
                    "score_unit": unit, "eligible": status == "eligible", "status": status,
                    "rule_active": bool(active), "event": event,
                    "common_history_ready": bool(common_ready.at[day, symbol])})
    return pd.DataFrame.from_records(records)


def _risk_allocation(selected, history_returns, cfg):
    """Same historical EWMA/cap/cash mathematics as portfolio.target_weights.

    Selection is a rule state, so no expected-return or round-trip-cost gate is
    applied. Costs are charged only by actual simulated trades, once per side.
    """
    history = history_returns.sort_index().tail(cfg.risk_lookback)
    diagnostic = {"method": "normalized_zero_mean_ewma_second_moment",
        "annualization": 252, "ewma_decay": cfg.ewma_decay, "selected": [],
        "excluded": [], "history_observations": 0, "risk_scale": 0.,
        "annual_vol_before_scale": 0., "annual_vol_after_scale": 0., "cash_weight": 1.,
        "signal_semantics": "rule_eligibility_not_expected_return", "expected_return_gate": None,
        "cap_policy": "cap_without_redistribution"}
    candidates = []
    for symbol in sorted(selected):
        if symbol not in history:
            diagnostic["excluded"].append({"symbol": symbol, "reason": "missing_risk_history"})
            continue
        values = history[symbol].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if np.isinf(values).any() or (finite <= -1).any():
            raise ValueError(f"Invalid historical simple returns for {symbol}.")
        if len(finite) < 2 or not np.any(np.abs(finite) > 1e-12):
            diagnostic["excluded"].append({"symbol": symbol, "reason": "insufficient_nonzero_risk_history"})
            continue
        candidates.append(symbol)
    if not candidates:
        return {}, diagnostic
    common = history[candidates].dropna()
    if len(common) < 2:
        return {}, diagnostic
    matrix = common.to_numpy(dtype=float)
    decay = cfg.ewma_decay ** np.arange(len(matrix) - 1, -1, -1)
    decay /= decay.sum()
    covariance = (matrix.T * decay) @ matrix * 252
    volatility = np.sqrt(np.maximum(np.diag(covariance), 0))
    if not np.isfinite(volatility).all() or (volatility <= 1e-12).any():
        return {}, diagnostic
    inverse = 1 / volatility
    capped = np.minimum(inverse / inverse.sum() * (1 - cfg.min_cash_weight), cfg.max_weight)
    risk_before = float(np.sqrt(max(float(capped @ covariance @ capped), 0)))
    scale = min(1., cfg.target_annual_vol / risk_before) if risk_before > 0 else 1.
    final = capped * scale
    diagnostic.update(selected=candidates, history_observations=len(common), risk_scale=float(scale),
        annual_vol_before_scale=risk_before, annual_vol_after_scale=risk_before * scale,
        cash_weight=float(1 - final.sum()), history_end=str(common.index[-1]),
        covariance_symbols=candidates, annual_covariance=covariance.tolist(),
        asset_annual_vol={s: float(v) for s, v in zip(candidates, volatility)})
    return {symbol: float(weight) for symbol, weight in zip(candidates, final) if weight > 0}, diagnostic


def run_strategy_comparison(prices, *, benchmark, source, rebalance_days=5,
                            cost_bps=10, max_weight=.2, target_vol=.15,
                            lookback=60, fast_window=50, slow_window=200,
                            entry_window=55, exit_window=20, test_sessions=60):
    """Compare four fixed daily rules; no fitting, parameter search or I/O.

    The final ``test_sessions`` benchmark dates are a common evaluation window,
    not an untouched model test set. Each asset requires the same complete
    longest warmup window. Empty portfolios are valid cash outcomes. Latest
    weights are references after the final close, never assumed final fills.
    """
    if not _SIMULATION_LOCK.acquire(blocking=False):
        raise ValueError("The shared CPU is running another simulation. Please try again shortly.")
    try:
        return _run_comparison(prices, benchmark, source, rebalance_days, cost_bps,
            max_weight, target_vol, lookback, fast_window, slow_window,
            entry_window, exit_window, test_sessions)
    finally:
        _SIMULATION_LOCK.release()


def _run_comparison(prices, benchmark, source, rebalance_days, cost_bps, max_weight,
                    target_vol, lookback, fast_window, slow_window, entry_window,
                    exit_window, test_sessions):
    if source not in {"synthetic", "uploaded_csv", "online_history"}:
        raise ValueError("source must be synthetic, uploaded_csv or online_history.")
    benchmark = _symbol(benchmark)
    prices = _validate_prices(prices, benchmark)
    settings = _parameters(rebalance_days, cost_bps, max_weight, target_vol, lookback,
        fast_window, slow_window, entry_window, exit_window, test_sessions)
    cfg = PortfolioConfig(capital=settings["capital"], max_weight=settings["max_weight"],
        min_cash_weight=settings["min_cash_weight"], target_annual_vol=settings["target_vol"],
        ewma_decay=settings["ewma_decay"], cost_bps=settings["cost_bps"],
        rebalance_days=settings["rebalance_days"], min_trade_value=settings["min_trade_value"],
        risk_lookback=settings["risk_lookback"], min_expected_excess=0)
    benchmark_prices = prices.loc[prices.symbol.eq(benchmark), ["date", "open", "close"]]
    dates = pd.DatetimeIndex(benchmark_prices.date)
    stocks = prices.loc[~prices.symbol.eq(benchmark)]
    canonical = prices.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.17g").encode("utf8")
    all_signals = _rule_signals(prices, benchmark, settings)
    evaluation_dates = dates[-test_sessions:]
    evaluated = all_signals.loc[all_signals.date.isin(evaluation_dates)].copy()
    anchor_dates = set(evaluation_dates[::settings["rebalance_days"]])
    evaluated["rebalance_signal"] = evaluated.date.isin(anchor_dates)
    evaluated["execution_available"] = evaluated.date.lt(dates[-1])
    warnings = [
        "Daily rules only; no broker, account, live quote or order submission is connected.",
        "Rule scores describe historical factors/state, not expected returns or proven alpha. No expected-return cost threshold is applied.",
        "All strategies use one evaluation window and common longest complete warmup; new listings and gaps are not filled.",
        "Parameter comparisons are exploratory; this evaluation window is not an untouched model test set.",
        "Adjusted OHLC are execution-price approximations; corporate actions, historical membership and delistings are not reconstructed.",
        "Latest reference weights are after-close targets; non-rebalance signals are displayed without trading, and the final signal has no invented fill.",
    ]
    if source == "synthetic":
        warnings.insert(0, "ILLUSTRATIVE SYNTHETIC DATA ONLY: fictional teaching prices and weekday calendar; returns are not market evidence.")
    elif source == "uploaded_csv":
        warnings.append("Visitor-supplied daily prices are unverified; no independent market-price verification has been performed.")
    if len(prices) < len(dates) * prices.symbol.nunique():
        warnings.append("Missing stock sessions are preserved. A missing held-position open/close fails that strategy instead of fabricating a fill or liquidation.")
    large_moves = int(prices.groupby("symbol").close.pct_change(fill_method=None).abs().gt(.30).sum())
    if large_moves:
        warnings.append(f"{large_moves} observed close-to-close moves exceed 30%; retained for review, not silently corrected.")
    enough_benchmark = len(dates) >= settings["common_warmup_bars"] + test_sessions - 1
    statuses, latest_risk = {}, {}
    result = {"source": source, "status": "failed", "metrics": [], "equity": [],
              "signals": [], "weights": [], "trades": [], "rebalances": [],
              "lineage": {}, "warnings": warnings}
    historical_returns = stocks.pivot(index="date", columns="symbol", values="close").reindex(dates).pct_change(fill_method=None)
    for strategy in STRATEGY_IDS:
        observed = evaluated.loc[evaluated.strategy.eq(strategy)]
        try:
            if not enough_benchmark or not observed.common_history_ready.any():
                statuses[strategy] = {"status": "insufficient_history", "error":
                    f"Need {settings['common_warmup_bars']} complete warmup bars and exactly {test_sessions} common evaluation sessions; no shortened comparison is substituted."}
                result["metrics"].append({"strategy": strategy, **statuses[strategy],
                    "total_return": None, "sharpe": None, "max_drawdown": None})
                continue
            # The simulator's score column carries a binary scheduling mask,
            # explicitly not a fabricated return forecast. Raw factors and
            # missing-data states remain separately visible in signals.
            mask = observed[["date", "symbol", "eligible"]].rename(columns={"eligible": "score"})
            mask["score"] = mask.score.astype(float)

            def allocate(scores, history, allocation_config):
                selected = list(scores.index[scores.gt(0)])
                return _risk_allocation(selected, history, allocation_config)

            simulation = backtest(stocks, mask, benchmark_prices, cfg, allocation_fn=allocate)
            final = observed.loc[observed.date.eq(dates[-1])]
            weights, risk = _risk_allocation(final.loc[final.eligible, "symbol"], historical_returns, cfg)
            latest_risk[strategy] = risk
            result["metrics"].append({"strategy": strategy, "status": "success",
                **simulation["metrics"], "n_evaluation_sessions": len(evaluation_dates),
                "score_semantics": "historical_factor_or_rule_state_not_expected_return"})
            result["equity"].extend({"strategy": strategy, **row} for row in simulation["series"])
            result["trades"].extend({"strategy": strategy, **row} for row in simulation["trades"])
            result["rebalances"].extend({"strategy": strategy, **row} for row in simulation["rebalances"])
            result["weights"].extend({"strategy": strategy, "symbol": symbol, "weight": weight,
                "kind": "asset", "signal_date": dates[-1].strftime("%Y-%m-%d"),
                "reference_only": True} for symbol, weight in sorted(weights.items()))
            result["weights"].append({"strategy": strategy, "symbol": "__CASH__", "kind": "cash",
                "weight": 1 - sum(weights.values()), "signal_date": dates[-1].strftime("%Y-%m-%d"),
                "reference_only": True})
            statuses[strategy] = {"status": "success", "error": None}
        except Exception as exc:
            statuses[strategy] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            result["metrics"].append({"strategy": strategy, **statuses[strategy],
                "total_return": None, "sharpe": None, "max_drawdown": None})
    successes = sum(item["status"] == "success" for item in statuses.values())
    result["status"] = "success" if successes == len(STRATEGY_IDS) else "partial" if successes else (
        "insufficient_history" if all(item["status"] == "insufficient_history" for item in statuses.values()) else "failed")
    evaluated["date"] = evaluated.date.dt.strftime("%Y-%m-%d")
    result["signals"] = evaluated.to_dict("records")
    result["lineage"] = {
        "engine": "daily_rule_comparison_v1", "config": settings, "dependencies": dict(_DEPENDENCIES),
        "data": {"source": source, "educational_only": source == "synthetic",
            "sha256": hashlib.sha256(canonical).hexdigest(), "rows": len(prices),
            "symbols": sorted(prices.symbol.unique()), "benchmark": benchmark,
            "start": dates[0].strftime("%Y-%m-%d"), "end": dates[-1].strftime("%Y-%m-%d"),
            "large_move_count": large_moves, "calendar": "synthetic weekdays, not exchange holidays"
                if source == "synthetic" else "observed benchmark sessions; exchange completeness not independently verified"},
        "evaluation": {"requested_sessions": test_sessions, "sessions": len(evaluation_dates),
            "start": evaluation_dates[0].strftime("%Y-%m-%d"), "end": evaluation_dates[-1].strftime("%Y-%m-%d"),
            "warmup_bars": settings["common_warmup_bars"], "benchmark_warmup_sufficient": enough_benchmark,
            "initial_holdings": "all strategies start with cash; no warmup-period positions",
            "rebalance_signal_dates": [day.strftime("%Y-%m-%d") for day in evaluation_dates[::cfg.rebalance_days]],
            "execution": "signal close -> next observed benchmark session actual open",
            "final_mark": "final close mark-to-market; no terminal liquidation or next-open invention",
            "score_units": "historical simple returns, close/slowMA-1, close/previousEntryHigh-1; not expected excess returns",
            "breakout_state": "update after each observed close; only rebalance anchors execute that day's state",
            "risk_observations": "last 60 calendar-aligned historical daily returns, zero-mean normalized EWMA",
            "costs": "actual integer-share executed notional, one charge per side; no forecast cost gate"},
        "strategy_status": statuses, "latest_risk": latest_risk,
        "latest_weights_as_of": dates[-1].strftime("%Y-%m-%d"),
        "latest_weights_scope": "hypothetical after-close target; not an executed portfolio or order",
        "code_sha256": {**_CODE_SHA256, "hf_space/strategies.py": _STRATEGIES_SHA256},
        "storage": "In-memory computation only; no local market, model, account or credential files read or written.",
    }
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    return _json_safe(result)
