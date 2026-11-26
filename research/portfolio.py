"""Offline portfolio construction, reference order drafts and OHLC simulation.

No broker client is imported here. Scores are decimal expected excess returns.
Risk is an annualized, zero-mean EWMA second-moment estimate, including asset
covariances. Backtests use integer shares and charge each executed side once.
"""
from dataclasses import asdict, dataclass, fields
from collections.abc import Mapping
import math

import numpy as np
import pandas as pd


@dataclass
class PortfolioConfig:
    capital: float = 100000.0
    top_k: int = 4
    max_weight: float = 0.2
    min_cash_weight: float = 0.2
    target_annual_vol: float = 0.15
    ewma_decay: float = 0.94
    cost_bps: float = 10.0
    rebalance_days: int = 5
    min_trade_value: float = 100.0
    risk_lookback: int = 60
    min_expected_excess: float = 0.002

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Portfolio parameter {name} must be finite numeric.")
        for name in ("top_k", "rebalance_days", "risk_lookback"):
            value = getattr(self, name)
            if int(value) != value or value < (2 if name == "risk_lookback" else 1):
                raise ValueError(f"Invalid portfolio parameter {name}.")
            setattr(self, name, int(value))
        if self.capital <= 0 or not 0 < self.max_weight <= 1 or not 0 <= self.min_cash_weight <= 1:
            raise ValueError("Capital, position cap or cash floor is invalid.")
        if self.target_annual_vol < 0 or not 0 < self.ewma_decay < 1:
            raise ValueError("Risk budget or EWMA decay is invalid.")
        if not 0 <= self.cost_bps < 10000 or self.min_trade_value < 0 or self.min_expected_excess < 0:
            raise ValueError("Costs, trade minimum or expected-excess threshold is invalid.")


def _config(config=None):
    if isinstance(config, PortfolioConfig):
        return config
    if config is None:
        return PortfolioConfig()
    if not isinstance(config, Mapping):
        raise TypeError("Config must be a PortfolioConfig or mapping.")
    if "portfolio" in config:
        values = dict(config["portfolio"])
        values.setdefault("rebalance_days", config.get("horizon", 5))
    else:
        values = dict(config)
    allowed = {f.name for f in fields(PortfolioConfig)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown portfolio parameters: {sorted(unknown)}")
    return PortfolioConfig(**values)


def _weights(weights):
    result = {str(k): float(v) for k, v in dict(weights).items()}
    if any(not math.isfinite(v) or v < 0 for v in result.values()) or sum(result.values()) > 1 + 1e-10:
        raise ValueError("Weights must be finite, long-only and sum to at most one.")
    return {k: v for k, v in result.items() if v > 0}


def target_weights(scores, history_returns, config=None):
    """Return target weights and auditable risk diagnostics using history only.

    The caller must truncate history to the signal time; ``backtest`` does so.
    Nonpositive and below-threshold forecasts are not invested. Missing risk
    history is never imputed: assets without two observations are excluded, and
    fewer than two complete common observations results in cash.
    """
    cfg = _config(config)
    if not isinstance(scores, pd.Series) or scores.index.has_duplicates:
        raise ValueError("Scores must be a Series with unique symbol keys.")
    scores = scores.copy()
    scores.index = scores.index.map(str)
    if scores.index.has_duplicates:
        raise ValueError("Score symbol keys must be unique.")
    scores = pd.to_numeric(scores, errors="raise")
    if not np.isfinite(scores.to_numpy(dtype=float)).all():
        raise ValueError("Scores must be finite; absent signals must be explicit.")
    if not isinstance(history_returns, pd.DataFrame) or history_returns.index.has_duplicates or history_returns.columns.has_duplicates:
        raise ValueError("History must have unique dates and symbol columns.")
    hist = history_returns.copy().sort_index().tail(cfg.risk_lookback)
    hist.columns = hist.columns.map(str)
    diag = {"method": "normalized_zero_mean_ewma_second_moment", "annualization": 252,
            "ewma_decay": cfg.ewma_decay, "risk_scale": 0.0, "annual_vol_before_scale": 0.0,
            "annual_vol_after_scale": 0.0, "cash_weight": 1.0, "selected": [],
            "history_observations": 0, "min_expected_excess": cfg.min_expected_excess,
            "estimated_round_trip_cost": 2 * cfg.cost_bps / 10000,
            "excluded": [], "warnings": []}
    ranked = sorted(((str(k), float(v)) for k, v in scores.items()
                     if v > cfg.min_expected_excess), key=lambda kv: (-kv[1], kv[0]))
    candidates = []
    for symbol, _ in ranked:
        if symbol not in hist.columns:
            diag["excluded"].append({"symbol": symbol, "reason": "missing_risk_history"})
            continue
        values = pd.to_numeric(hist[symbol], errors="raise").to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if np.isinf(values).any() or (finite <= -1).any():
            raise ValueError(f"Invalid historical simple returns for {symbol}.")
        if len(finite) < 2 or not np.any(np.abs(finite) > 1e-12):
            diag["excluded"].append({"symbol": symbol, "reason": "insufficient_nonzero_risk_history"})
            continue
        candidates.append(symbol)
        if len(candidates) == cfg.top_k:
            break
    if not candidates or cfg.min_cash_weight == 1 or cfg.target_annual_vol == 0:
        diag["warnings"].append("No eligible risk-budgeted signal; hold cash.")
        return {}, diag
    common = hist[candidates].apply(pd.to_numeric, errors="raise").dropna()
    if len(common) < 2:
        diag["warnings"].append("Fewer than two common historical returns; hold cash.")
        return {}, diag
    matrix = common.to_numpy(dtype=float)
    decay = cfg.ewma_decay ** np.arange(len(matrix) - 1, -1, -1)
    decay /= decay.sum()
    covariance = (matrix.T * decay) @ matrix * 252
    vols = np.sqrt(np.maximum(np.diag(covariance), 0))
    if not np.isfinite(vols).all() or np.any(vols <= 1e-12):
        diag["warnings"].append("Unusable volatility estimate; hold cash.")
        return {}, diag
    inverse = 1 / vols
    preliminary = inverse / inverse.sum() * (1 - cfg.min_cash_weight)
    capped = np.minimum(preliminary, cfg.max_weight)
    risk_before = float(np.sqrt(max(float(capped @ covariance @ capped), 0)))
    scale = min(1.0, cfg.target_annual_vol / risk_before) if risk_before > 0 else 1.0
    final = capped * scale
    weights = {symbol: float(weight) for symbol, weight in zip(candidates, final) if weight > 0}
    diag.update(selected=candidates, history_observations=len(common), risk_scale=float(scale),
                annual_vol_before_scale=risk_before, annual_vol_after_scale=risk_before * scale,
                cash_weight=float(1 - final.sum()),
                asset_annual_vol={s: float(v) for s, v in zip(candidates, vols)},
                covariance_symbols=candidates, annual_covariance=covariance.tolist(),
                cap_policy="cap_without_redistribution")
    if len(common):
        diag["history_end"] = str(common.index[-1])
    return weights, diag


def _price_mapping(prices, as_of=None):
    if isinstance(prices, pd.DataFrame):
        if not {"symbol", "close"}.issubset(prices.columns):
            raise ValueError("Reference prices need symbol and close columns.")
        frame = prices.copy()
        if "date" in frame:
            frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
            if as_of is not None:
                frame = frame.loc[frame["date"] <= pd.Timestamp(as_of).normalize()]
            frame = frame.sort_values("date").drop_duplicates("symbol", keep="last")
        elif frame["symbol"].duplicated().any():
            raise ValueError("Duplicate undated reference prices.")
        result = dict(zip(frame["symbol"].map(str), frame["close"]))
    else:
        result = dict(prices)
    result = {str(k): float(v) for k, v in result.items()}
    if any(not math.isfinite(v) or v <= 0 for v in result.values()):
        raise ValueError("Reference prices must be finite and positive.")
    return result


def _quantities(current_quantities=None):
    result = {}
    for symbol, qty in dict({} if current_quantities is None else current_quantities).items():
        value = float(qty)
        if not math.isfinite(value) or value < 0 or int(value) != value:
            raise ValueError("Current quantities must be nonnegative integer shares.")
        if value:
            result[str(symbol)] = int(value)
    return result


def _plan(weights, prices, capital, current, cfg):
    """Self-financing integer-share planning; never spend reserved cash or fees."""
    symbols = sorted(set(weights) | set(current))
    missing = set(symbols) - set(prices)
    if missing:
        raise ValueError(f"Missing executable/reference prices: {sorted(missing)}")
    current_value = sum(current.get(s, 0) * prices[s] for s in symbols)
    if current_value > capital + max(1e-7, capital * 1e-10):
        raise ValueError("Current long holdings exceed simulated portfolio equity.")
    fee_rate = cfg.cost_bps / 10000
    # Solve post-cost equity against the continuous target before rounding down.
    lo, hi = 0.0, float(capital)
    for _ in range(64):
        mid = (lo + hi) / 2
        fees = fee_rate * sum(abs(weights.get(s, 0) * mid - current.get(s, 0) * prices[s]) for s in symbols)
        if mid + fees > capital:
            hi = mid
        else:
            lo = mid
    requested = {s: int(math.floor(weights.get(s, 0) * lo / prices[s] + 1e-12)) for s in symbols}
    desired = dict(requested)
    skipped = []
    for s in symbols:
        delta = desired[s] - current.get(s, 0)
        if delta and abs(delta) * prices[s] < cfg.min_trade_value:
            desired[s] = current.get(s, 0)
            skipped.append({"symbol": s, "reason": "below_min_trade_value"})
    cash = capital - current_value
    for s in symbols:
        delta = desired[s] - current.get(s, 0)
        if delta < 0:
            cash += -delta * prices[s] * (1 - fee_rate)
    buy_symbols = [s for s in symbols if desired[s] > current.get(s, 0)]
    buy_need = sum((desired[s] - current.get(s, 0)) * prices[s] * (1 + fee_rate) for s in buy_symbols)
    available = max(0.0, cash - cfg.min_cash_weight * capital)
    ratio = min(1.0, available / buy_need) if buy_need else 1.0
    for s in buy_symbols:
        delta = int(math.floor((desired[s] - current.get(s, 0)) * ratio + 1e-12))
        if delta and delta * prices[s] < cfg.min_trade_value:
            delta = 0
            skipped.append({"symbol": s, "reason": "below_min_trade_value_after_cash_budget"})
        desired[s] = current.get(s, 0) + delta
    plans = []
    for s in symbols:
        delta = desired[s] - current.get(s, 0)
        if delta:
            notional = abs(delta) * prices[s]
            plans.append({"symbol": s, "side": "BUY" if delta > 0 else "SELL",
                          "quantity": abs(delta), "quantity_delta": delta,
                          "current_quantity": current.get(s, 0), "target_quantity": desired[s],
                          "requested_target_quantity": requested[s], "price": prices[s],
                          "notional": notional, "cost": notional * fee_rate})
    plans.sort(key=lambda p: (p["side"] != "SELL", p["symbol"]))
    return plans, skipped


def make_order_drafts(weights, prices, capital, current_quantities=None, as_of=None, run_id=None, config=None):
    """Make local, reference-only drafts against an independent simulated book."""
    cfg = _config(config)
    weights = _weights(weights)
    if any(w > cfg.max_weight + 1e-10 for w in weights.values()) or sum(weights.values()) > 1 - cfg.min_cash_weight + 1e-10:
        raise ValueError("Draft weights violate position cap or cash floor.")
    capital = float(capital)
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("Simulated capital must be positive and finite.")
    reference = _price_mapping(prices, as_of)
    current = _quantities(current_quantities)
    plans, _ = _plan(weights, reference, capital, current, cfg)
    result = []
    for plan in plans:
        row = dict(plan)
        row.update(reference_price=row.pop("price"), estimated_notional=row.pop("notional"),
                   estimated_one_way_cost=row.pop("cost"), target_weight=weights.get(row["symbol"], 0),
                   as_of=str(as_of) if as_of is not None else None, run_id=run_id,
                   status="DRAFT", reference_only=True, requires_requote=True, no_submit=True,
                   account_scope="independent_simulated_portfolio", order_type="REFERENCE_DRAFT",
                   price_basis="last_completed_daily_close_reference",
                   capital_basis="user_configured_simulated_equity")
        result.append(row)
    return result


def _dated(frame, required, name):
    if not isinstance(frame, pd.DataFrame) or not set(required).issubset(frame.columns):
        raise ValueError(f"{name} needs columns {required}.")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    if out["date"].isna().any():
        raise ValueError(f"Missing {name} dates.")
    if "symbol" in required:
        out["symbol"] = out["symbol"].map(str)
    keys = ["date", "symbol"] if "symbol" in required else ["date"]
    if out.duplicated(keys).any():
        raise ValueError(f"Duplicate {name} keys.")
    for col in set(required) - {"date", "symbol"}:
        out[col] = pd.to_numeric(out[col], errors="raise")
        if not np.isfinite(out[col].to_numpy(dtype=float)).all():
            raise ValueError(f"Nonfinite {name} {col}.")
        if col in {"open", "close"} and (out[col] <= 0).any():
            raise ValueError(f"Nonpositive {name} prices.")
    return out.sort_values(keys)


def backtest(prices, predictions, benchmark, config=None, *, allocation_fn=None):
    """Simulate post-close signals at next session's actual open, offline only.

    Benchmark dates are the trading calendar. Positions drift daily. The
    benchmark buys and holds at the first eligible execution open without
    benchmark fees; strategy costs are deducted from cash exactly once.
    The final session is marked at close, without inventing a next open.
    An optional allocation_fn(scores, historical_returns, config) returns
    (weights, diagnostics). It receives history only through the signal close;
    rule-based allocators can use explicit eligibility instead of interpreting
    historical factors as expected excess returns. The default is unchanged.
    """
    cfg = _config(config)
    if allocation_fn is not None and not callable(allocation_fn):
        raise TypeError("allocation_fn must be callable.")
    allocate = target_weights if allocation_fn is None else allocation_fn
    px = _dated(prices, ["date", "symbol", "open", "close"], "prices")
    pred = _dated(predictions, ["date", "symbol", "score"], "predictions")
    bench = _dated(benchmark, ["date", "open", "close"], "benchmark")
    if pred.empty or bench.empty:
        return {"series": [], "trades": [], "metrics": {}, "rebalances": [],
                "warnings": ["No prediction or benchmark dates; no simulated performance."]}
    dates = pd.DatetimeIndex(bench["date"])
    if not set(pred["date"]).issubset(set(dates)):
        raise ValueError("Every prediction date must belong to the benchmark trading calendar.")
    unknown = set(pred["symbol"]) - set(px["symbol"])
    if unknown:
        raise ValueError(f"Prediction symbols have no price history: {sorted(unknown)}")
    closes = px.pivot(index="date", columns="symbol", values="close").reindex(dates)
    opens = px.pivot(index="date", columns="symbol", values="open").reindex(dates)
    history_returns = closes.pct_change(fill_method=None)
    grouped = {d: g.set_index("symbol")["score"] for d, g in pred.groupby("date")}
    start = dates.get_loc(pred["date"].min())
    last_signal = dates.get_loc(pred["date"].max())
    signal_positions = set(range(start, last_signal + 1, cfg.rebalance_days))
    # A signal only becomes an execution when a subsequent observed session exists.
    executions = {i + 1: i for i in signal_positions if i + 1 < len(dates)}
    cash, quantities = float(cfg.capital), {}
    benchmark_quantity = 0.0
    peak, previous_equity = float(cfg.capital), float(cfg.capital)
    series, trades, logs = [], [], []
    total_cost = 0.0
    for i in range(start, len(dates)):
        date = dates[i]
        turnover = 0.0
        if i in executions:
            signal_date = dates[executions[i]]
            scores = grouped.get(signal_date, pd.Series(dtype=float))
            weights, diagnostic = allocate(scores, history_returns.loc[:signal_date], cfg)
            weights = _weights(weights)
            if (any(w > cfg.max_weight + 1e-10 for w in weights.values()) or
                    sum(weights.values()) > 1 - cfg.min_cash_weight + 1e-10):
                raise ValueError("Allocator exceeded the configured position cap or cash floor.")
            needed = set(quantities) | set(weights)
            execution_prices = {s: float(opens.at[date, s]) for s in needed}
            if any(not math.isfinite(v) or v <= 0 for v in execution_prices.values()):
                raise ValueError(f"Missing next-open executable price on {date.date()}.")
            equity_before = cash + sum(q * execution_prices[s] for s, q in quantities.items())
            plans, skipped = _plan(weights, execution_prices, equity_before, quantities, cfg)
            day_cost = 0.0
            for plan in plans:
                delta = plan["quantity_delta"]
                cash -= delta * plan["price"] + plan["cost"]
                quantities[plan["symbol"]] = plan["target_quantity"]
                if quantities[plan["symbol"]] == 0:
                    del quantities[plan["symbol"]]
                day_cost += plan["cost"]
                trades.append({**plan, "date": date.strftime("%Y-%m-%d"),
                               "signal_date": signal_date.strftime("%Y-%m-%d"),
                               "execution_basis": "actual_next_session_open",
                               "cash_after": float(cash), "simulated": True})
            if cash < -1e-6:
                raise RuntimeError("Simulated cash became negative.")
            cash = max(cash, 0.0)
            total_cost += day_cost
            turnover = sum(p["notional"] for p in plans) / equity_before if equity_before else 0.0
            logs.append({"signal_date": signal_date.strftime("%Y-%m-%d"),
                         "execution_date": date.strftime("%Y-%m-%d"), "weights": weights,
                         "diagnostics": diagnostic, "pre_trade_equity": float(equity_before),
                         "post_trade_equity": float(equity_before - day_cost),
                         "cost": float(day_cost), "turnover": float(turnover),
                         "cash_after": float(cash), "holdings": dict(quantities), "skipped": skipped})
        if i == start + 1:
            benchmark_quantity = cfg.capital / float(bench.iloc[i]["open"])
        marks = {s: float(closes.at[date, s]) for s in quantities}
        if any(not math.isfinite(v) or v <= 0 for v in marks.values()):
            raise ValueError(f"Missing held-position close on {date.date()}.")
        equity = cash + sum(q * marks[s] for s, q in quantities.items())
        peak = max(peak, equity)
        benchmark_equity = benchmark_quantity * float(bench.iloc[i]["close"]) if benchmark_quantity else cfg.capital
        series.append({"date": date.strftime("%Y-%m-%d"), "equity": float(equity),
                       "drawdown": float(equity / peak - 1), "benchmark_equity": float(benchmark_equity),
                       "cash_weight": float(cash / equity) if equity else 1.0,
                       "turnover": float(turnover), "cash": float(cash), "holdings": dict(quantities),
                       "daily_return": float(equity / previous_equity - 1)})
        previous_equity = equity
    observations = max(0, len(series) - 1)
    returns = np.array([x["daily_return"] for x in series[1:]], dtype=float)
    daily_std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    total_return = series[-1]["equity"] / cfg.capital - 1
    annualized = float((1 + total_return) ** (252 / observations) - 1) if observations and total_return > -1 else None
    metrics = {"total_return": float(total_return), "annualized_return": annualized,
               "annualized_volatility": daily_std * math.sqrt(252),
               "sharpe": float(returns.mean() / daily_std * math.sqrt(252)) if daily_std else None,
               "max_drawdown": float(min(x["drawdown"] for x in series)),
               "benchmark_total_return": float(series[-1]["benchmark_equity"] / cfg.capital - 1),
               "total_cost": float(total_cost), "total_turnover": float(sum(x["turnover"] for x in series)),
               "trade_count": len(trades), "rebalance_count": len(logs),
               "turnover_definition": "sum_abs_executed_notional/pre_trade_equity",
               "benchmark_policy": "buy_hold_first_execution_open_no_benchmark_fees",
               "quantity_policy": "integer_shares", "rebalance_days": cfg.rebalance_days,
               "cost_bps_per_executed_side": cfg.cost_bps}
    return {"series": series, "trades": trades, "metrics": metrics, "rebalances": logs,
            "warnings": ["Offline simulation only; adjusted OHLC are executable-price approximations.",
                         "Final close is mark-to-market, not an invented final next-open execution."]}
