"""Bounded daily Beta research. No market-file, broker, or network access.

OLS uses centered close-to-close raw research returns and an intercept. It is
not a Jensen-alpha estimator, a point-in-time market universe, or BAB. Portfolios
are long-only integer shares, with cash earning zero and next-open OHLC proxies.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from importlib.metadata import version, PackageNotFoundError
from io import BytesIO
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from hf_space.engine import _SIMULATION_LOCK, _DEPENDENCIES
from research.portfolio import PortfolioConfig, _plan


COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume")
STRATEGY_IDS = ("high_beta", "low_beta", "equal_weight", "spy_80", "spy_100")
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_ROWS = 80_000
MAX_SYMBOLS = 61
MAX_DATES = 1260
CALENDAR_VERSION = "4.11.2"
MIN_MARKET_VARIANCE = 1e-12
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class BetaError(ValueError):
    """Explicit invalid data, insufficient research history, or busy worker."""


def _now_utc():
    return pd.Timestamp.now(tz="UTC")


def _safe(value):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _integer(value, name, low, high):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not low <= value <= high:
        raise BetaError(f"{name} must be an integer in [{low}, {high}].")
    return int(value)


def _number(value, name, low, high):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise BetaError(f"{name} must be numeric.")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise BetaError(f"{name} must be finite and in [{low}, {high}].")
    return value


def _calendar(first, last):
    try:
        if version("exchange-calendars") != CALENDAR_VERSION:
            raise BetaError(f"Beta research requires exchange-calendars=={CALENDAR_VERSION}.")
        import exchange_calendars as xcals
        return xcals.get_calendar("XNYS", start=first, end=last)
    except (ImportError, PackageNotFoundError):
        raise BetaError(f"Install exchange-calendars=={CALENDAR_VERSION}.") from None
    except BetaError:
        raise
    except Exception:
        raise BetaError("XNYS calendar does not cover the requested dates.") from None


def _validate_prices(prices, benchmark="SPY"):
    if not isinstance(benchmark, str) or not _SYMBOL.fullmatch(benchmark):
        raise BetaError("Benchmark must be an uppercase stock/ETF symbol.")
    if not isinstance(prices, pd.DataFrame) or set(prices.columns) != set(COLUMNS):
        raise BetaError("Daily prices must have exactly date,symbol,open,high,low,close,volume.")
    if prices.empty or len(prices) > MAX_ROWS:
        raise BetaError(f"Provide 1 to {MAX_ROWS} daily rows.")
    frame = prices.loc[:, list(COLUMNS)].copy()
    if frame.isna().any().any():
        raise BetaError("Missing input fields are not accepted; absent stock sessions must remain absent rows.")
    try:
        if pd.api.types.is_datetime64_any_dtype(frame.date.dtype):
            dates = pd.to_datetime(frame.date, errors="raise")
            if dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
                raise BetaError("Daily dates must be timezone-free midnight dates.")
        else:
            raw_dates = frame.date.astype(str)
            if not raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
                raise BetaError("Daily dates must use YYYY-MM-DD.")
            dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="raise")
    except BetaError:
        raise
    except Exception:
        raise BetaError("Invalid daily dates.") from None
    frame["date"] = dates
    if not frame.symbol.map(lambda x: isinstance(x, str) and bool(_SYMBOL.fullmatch(x))).all():
        raise BetaError("Symbols must be uppercase stock/ETF symbols; paths and URLs are refused.")
    if frame.symbol.nunique() > MAX_SYMBOLS or frame.date.nunique() > MAX_DATES:
        raise BetaError(f"Limit the dataset to {MAX_SYMBOLS} securities and {MAX_DATES} dates.")
    if frame.duplicated(["date", "symbol"]).any():
        raise BetaError("Duplicate daily date/symbol rows.")
    for column in COLUMNS[2:]:
        if frame[column].map(lambda x: isinstance(x, (bool, np.bool_))).any():
            raise BetaError("Boolean OHLCV fields are not numeric prices or volume.")
        try:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        except Exception:
            raise BetaError("OHLCV fields must be numeric.") from None
    matrix = frame.loc[:, list(COLUMNS[2:])].to_numpy()
    if not np.isfinite(matrix).all() or (frame.loc[:, ["open", "high", "low", "close"]] <= 0).any().any() or (frame.volume < 0).any():
        raise BetaError("OHLCV must be finite, prices positive and volume nonnegative.")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (frame.low > frame[["open", "close", "high"]].min(axis=1)).any():
        raise BetaError("Daily OHLC values are inconsistent.")
    frame = frame.sort_values(["date", "symbol"]).reset_index(drop=True)
    benchmark_dates = pd.DatetimeIndex(frame.loc[frame.symbol.eq(benchmark), "date"])
    if benchmark_dates.empty:
        raise BetaError("Benchmark is missing.")
    if not frame.date.isin(benchmark_dates).all():
        raise BetaError("Every observed stock date must belong to the observed benchmark calendar.")
    end = benchmark_dates[-1] + pd.offsets.MonthEnd(1) + pd.Timedelta(days=7)
    calendar = _calendar(benchmark_dates[0] - pd.Timedelta(days=7), end)
    expected = calendar.sessions_in_range(benchmark_dates[0], benchmark_dates[-1])
    expected = pd.DatetimeIndex(expected).tz_localize(None)
    if not benchmark_dates.equals(expected):
        raise BetaError("Benchmark has missing or non-XNYS sessions; calendar gaps are not compressed or filled.")
    if calendar.session_close(benchmark_dates[-1]) > _now_utc():
        raise BetaError("Future or not-yet-completed exchange sessions are refused.")
    return frame, calendar


def parse_beta_csv(payload, benchmark="SPY"):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_UPLOAD_BYTES:
        raise BetaError("Upload a nonempty UTF-8 daily CSV up to 12 MiB.")
    try:
        payload.decode("utf-8-sig")
        data = pd.read_csv(BytesIO(payload), encoding="utf-8-sig")
    except Exception:
        raise BetaError("Daily CSV must be valid UTF-8 and parse as seven OHLCV columns.") from None
    return _validate_prices(data, benchmark)[0]


def estimate_ols_beta(stock_returns, market_returns):
    """Centered OLS with intercept; descriptive raw-return market model only."""
    try:
        y, x = np.asarray(stock_returns, dtype=float), np.asarray(market_returns, dtype=float)
    except (TypeError, ValueError):
        raise BetaError("OLS needs numeric return arrays.") from None
    if y.ndim != 1 or x.ndim != 1 or len(y) != len(x) or len(y) < 3:
        raise BetaError("OLS needs at least three aligned one-dimensional returns.")
    if not np.isfinite(y).all() or not np.isfinite(x).all():
        raise BetaError("OLS does not drop or fill missing common returns.")
    n = len(x)
    with np.errstate(over="ignore", invalid="ignore"):
        xc, yc = x - x.mean(), y - y.mean()
        xx, yy, xy = float(xc @ xc), float(yc @ yc), float(xc @ yc)
    if not all(math.isfinite(value) for value in (xx, yy, xy)):
        raise BetaError("OLS return statistics exceed finite numerical bounds.")
    if xx / (n - 1) <= MIN_MARKET_VARIANCE:
        raise BetaError("Market return variance is too small for a usable Beta estimate.")
    beta = xy / xx
    with np.errstate(over="ignore", invalid="ignore"):
        residuals = yc - beta * xc
        residual_variance = float(residuals @ residuals) / (n - 2)
    if not math.isfinite(beta) or not math.isfinite(residual_variance):
        raise BetaError("OLS coefficients exceed finite numerical bounds.")
    residual_variance = max(0.0, residual_variance)
    correlation = float(np.clip(xy / math.sqrt(xx) / math.sqrt(yy), -1, 1)) if yy > 1e-24 else None
    result = {"beta": beta, "correlation": correlation,
            "r_squared": correlation ** 2 if correlation is not None else None,
            "standard_error": math.sqrt(residual_variance / xx), "nobs": n,
            "annual_vol": math.sqrt(max(0., yy / (n - 1)) * 252),
            "residual_vol": math.sqrt(residual_variance * 252),
            "intercept_per_day": float(y.mean() - beta * x.mean()),
            "status": "success", "reason": None}
    if any(not math.isfinite(value) for value in result.values() if isinstance(value, (int, float))):
        raise BetaError("OLS estimates exceed finite numerical bounds.")
    return result


def _annualized_return(equity_ratio, periods):
    if not math.isfinite(equity_ratio) or equity_ratio <= 0 or periods <= 0:
        raise BetaError("Annualized return needs positive finite account growth and session count.")
    exponent = math.log(equity_ratio) * 252 / periods
    if not math.isfinite(exponent) or exponent > 700:
        raise BetaError("Annualized return exceeds finite numerical bounds; no infinite performance is reported.")
    return math.expm1(exponent)


def _measure(closes, benchmark, window, indices, calendar):
    returns = closes.pct_change(fill_method=None)
    market = returns[benchmark].to_numpy()
    symbols = sorted(s for s in closes.columns if s != benchmark)
    result = {}
    for index in sorted(indices):
        day = closes.index[index].date().isoformat()
        available_at = calendar.session_close(closes.index[index]).isoformat().replace("+00:00", "Z")
        measurements = {}
        for symbol in symbols:
            row = {"symbol": symbol, "date": day, "as_of": day,
                   "available_at": available_at,
                   "window": window, "beta": None, "correlation": None, "r_squared": None,
                   "standard_error": None, "nobs": 0, "annual_vol": None,
                   "residual_vol": None, "intercept_per_day": None,
                   "status": "unavailable", "reason": "insufficient_history"}
            if index >= window:
                y = returns[symbol].iloc[index-window+1:index+1].to_numpy()
                x = market[index-window+1:index+1]
                row["nobs"] = int((np.isfinite(x) & np.isfinite(y)).sum())
                if row["nobs"] == window:
                    try:
                        row.update(estimate_ols_beta(y, x))
                    except BetaError:
                        row["reason"] = "unusable_return_statistics"
                else:
                    row["reason"] = "missing_common_returns"
            measurements[symbol] = row
        result[index] = measurements
    return result, returns


def _targets(measurements, strategy, benchmark, max_weight):
    if strategy in {"spy_80", "spy_100"}:
        return {benchmark: .8 if strategy == "spy_80" else 1.0}
    eligible = sorted((row for row in measurements.values() if row["status"] == "success"),
                      key=lambda row: (row["beta"], row["symbol"]))
    if len(eligible) < 20:
        raise BetaError(f"At least 20 historically eligible stocks are required; found {len(eligible)}.")
    count = math.floor(.2 * len(eligible))
    if strategy == "low_beta":
        selected = eligible[:count]
    elif strategy == "high_beta":
        selected = sorted(eligible, key=lambda row: (-row["beta"], row["symbol"]))[:count]
    else:
        selected = eligible
    weight = min(.8 / len(selected), max_weight)
    return {row["symbol"]: weight for row in selected}


def _portfolio_beta(quantities, close_prices, equity, measurements, benchmark):
    beta = 0.0
    for symbol, quantity in quantities.items():
        if not quantity:
            continue
        row = measurements.get(symbol)
        coefficient = 1.0 if symbol == benchmark else row.get("beta") if row and row["status"] == "success" else None
        if coefficient is None:
            return None
        beta += quantity * float(close_prices[symbol]) / equity * coefficient
    return beta


def _simulate(strategy, dates, opens, closes, measurements, formations, config, benchmark):
    capital, cost_bps = config["capital"], config["cost_bps"]
    stock_group = strategy not in {"spy_80", "spy_100"}
    cash_floor = .2 if strategy != "spy_100" else 0.0
    planner = PortfolioConfig(capital=capital, max_weight=config["max_weight"] if stock_group else 1.0,
                              min_cash_weight=cash_floor, cost_bps=cost_bps, min_trade_value=0.)
    cash, quantities, peaks = capital, {}, capital
    curves, trades, rebalances, cost_total, turnover_notional = [], [], [], 0.0, 0.0
    last_target, last_signal, last_execution = {}, None, None
    for index in config["evaluation_indices"]:
        day = dates[index].date().isoformat()
        if index in formations:
            signal_index, kind = formations[index]
            signal_day = dates[signal_index].date().isoformat()
            weights = _targets(measurements[signal_index], strategy, benchmark, config["max_weight"])
            required = set(weights) | {s for s, qty in quantities.items() if qty}
            prices = {s: float(opens.iloc[index][s]) for s in required}
            if any(not math.isfinite(price) or price <= 0 for price in prices.values()):
                raise BetaError("Missing held or selected stock open; no fill, liquidation or price substitution is fabricated.")
            before = cash + sum(qty * prices[s] for s, qty in quantities.items() if qty)
            # An earlier rebalance may have sold a stock completely. Its zero
            # ledger entry is not a current position and must not demand a
            # fresh quote; genuine held-position prices remain mandatory.
            current = {symbol: qty for symbol, qty in quantities.items() if qty}
            plans, skipped = _plan(weights, prices, before, current, planner)
            for trade in plans:
                symbol, delta, price, cost = trade["symbol"], trade["quantity_delta"], trade["price"], trade["cost"]
                cash -= delta * price + cost
                quantities[symbol] = quantities.get(symbol, 0) + delta
                cost_total += cost
                turnover_notional += abs(delta * price)
                trades.append({"strategy": strategy, "signal_date": signal_day, "execution_date": day,
                               "symbol": symbol, "side": trade["side"], "quantity": trade["quantity"],
                               "price": price, "notional": trade["notional"], "cost": cost,
                               "price_basis": "next_observed_XNYS_session_open_proxy"})
            if cash < -max(1e-7, before * 1e-10) or any(qty < 0 for qty in quantities.values()):
                raise BetaError("Unfunded research trade or short position refused.")
            cash = max(0.0, cash)
            last_target, last_signal, last_execution = weights, signal_day, day
            rebalances.append({"strategy": strategy, "signal_date": signal_day, "execution_date": day,
                               "kind": kind, "eligible_stocks": sum(r["status"] == "success" for r in measurements[signal_index].values()),
                               "targets": weights, "skipped": skipped})
        held = {s: qty for s, qty in quantities.items() if qty}
        close_values = {s: float(closes.iloc[index][s]) for s in held}
        if any(not math.isfinite(price) or price <= 0 for price in close_values.values()):
            raise BetaError("Missing held stock close; valuation does not forward-fill or silently liquidate.")
        market_value = sum(qty * close_values[s] for s, qty in held.items())
        equity = cash + market_value
        if not math.isfinite(equity) or equity <= 0:
            raise BetaError("Invalid research account equity.")
        peaks = max(peaks, equity)
        curves.append({"date": day, "strategy": strategy, "equity": equity, "cash": cash,
                       "market_value": market_value, "drawdown": equity / peaks - 1,
                       "predicted_beta": _portfolio_beta(held, close_values, equity, measurements[index], benchmark),
                       "predicted_beta_as_of": day})
    final = curves[-1]
    actual = [{"strategy": strategy, "symbol": s, "kind": "asset", "quantity": int(qty),
               "weight": qty * float(closes.iloc[config["evaluation_indices"][-1]][s]) / final["equity"],
               "as_of": final["date"]} for s, qty in sorted(quantities.items()) if qty]
    actual.append({"strategy": strategy, "symbol": "__CASH__", "kind": "cash", "quantity": None,
                   "weight": cash / final["equity"], "as_of": final["date"]})
    targets = [{"strategy": strategy, "symbol": s, "kind": "asset", "weight": w,
                "signal_date": last_signal, "execution_date": last_execution,
                "scope": "last_executed_rebalance_target_not_current_weight"} for s, w in sorted(last_target.items())]
    targets.append({"strategy": strategy, "symbol": "__CASH__", "kind": "cash", "weight": 1 - sum(last_target.values()),
                    "signal_date": last_signal, "execution_date": last_execution,
                    "scope": "last_executed_rebalance_target_not_current_weight"})
    equity_values = np.array([capital] + [r["equity"] for r in curves])
    daily = equity_values[1:] / equity_values[:-1] - 1
    deviation = float(np.std(daily, ddof=1))
    realized = None
    if len(curves) >= 4:
        market = closes[benchmark].iloc[config["evaluation_indices"]].pct_change(fill_method=None).iloc[1:].to_numpy()
        try:
            realized = estimate_ols_beta(daily[1:], market)
        except BetaError:
            pass
    periods = len(curves)
    total = final["equity"] / capital - 1
    metric = {"strategy": strategy, "status": "success", "total_return": total,
              "annual_return": _annualized_return(final["equity"] / capital, periods),
              "annual_vol": deviation * math.sqrt(252),
              "sharpe": float(np.mean(daily) / deviation * math.sqrt(252)) if deviation > 1e-12 else None,
              "max_drawdown": min(r["drawdown"] for r in curves),
              "realized_beta": realized["beta"] if realized else None,
              "realized_r_squared": realized["r_squared"] if realized else None,
              "realized_beta_nobs": realized["nobs"] if realized else max(0, periods-1),
              "realized_beta_standard_error": realized["standard_error"] if realized else None,
              "latest_predicted_beta": final["predicted_beta"], "total_costs": cost_total,
              "trade_count": len(trades), "turnover": turnover_notional / capital,
              "final_equity": final["equity"], "cash_weight": cash / final["equity"],
              "initialization": "prior_close_selection_first_evaluation_open",
              "first_return_scope": "first_evaluation_open_to_close_including_initial_costs",
              "sharpe_risk_free_rate": 0.0, "alpha": None,
              "alpha_scope": "No Jensen alpha: raw research price returns and zero-interest cash."}
    return metric, curves, trades, rebalances, actual, targets


def run_beta_comparison(prices, *, benchmark="SPY", source="uploaded_csv", beta_window=126,
                        test_sessions=252, cost_bps=10, max_weight=.2, capital=100000):
    """One causal research run. Never queues CPU work or falls back to toy data."""
    if not _SIMULATION_LOCK.acquire(blocking=False):
        raise BetaError("Research worker is busy. Try again after the current run finishes.")
    try:
        return _run(prices, benchmark=benchmark, source=source, beta_window=beta_window,
                    test_sessions=test_sessions, cost_bps=cost_bps, max_weight=max_weight, capital=capital)
    finally:
        _SIMULATION_LOCK.release()


def _run(prices, *, benchmark, source, beta_window, test_sessions, cost_bps, max_weight, capital):
    if source not in {"uploaded_csv", "moomoo_daily_snapshot"}:
        raise BetaError("Source must be uploaded_csv or moomoo_daily_snapshot; no synthetic fallback is supported.")
    beta_window = _integer(beta_window, "beta_window", 126, 252)
    if beta_window not in {126, 252}:
        raise BetaError("Choose the predeclared 126 or 252 daily-return Beta window.")
    test_sessions = _integer(test_sessions, "test_sessions", 20, 504)
    cost_bps = _number(cost_bps, "cost_bps", 0, 50)
    max_weight = _number(max_weight, "max_weight", .05, .4)
    capital = _number(capital, "capital", 1000, 10_000_000)
    frame, calendar = _validate_prices(prices, benchmark)
    opens = frame.pivot(index="date", columns="symbol", values="open")
    closes = frame.pivot(index="date", columns="symbol", values="close")
    dates = pd.DatetimeIndex(frame.loc[frame.symbol.eq(benchmark), "date"])
    opens, closes = opens.reindex(dates), closes.reindex(dates)
    if len(dates) < beta_window + test_sessions + 1:
        raise BetaError(f"Need {beta_window + test_sessions + 1} benchmark price sessions for {beta_window} prior returns plus {test_sessions} evaluation sessions.")
    start = len(dates) - test_sessions
    indices = list(range(start, len(dates)))
    # Calendar month-ends, never the last observed day of an unfinished month.
    calendar_dates = pd.DatetimeIndex(calendar.sessions_in_range(dates[0], dates[-1] + pd.offsets.MonthEnd(1))).tz_localize(None)
    month_ends = set(pd.Series(calendar_dates, index=calendar_dates).groupby(calendar_dates.to_period("M")).max())
    formations = {start: (start - 1, "evaluation_initialization")}
    for index in range(start, len(dates)-1):
        if dates[index] in month_ends:
            formations[index+1] = (index, "calendar_month_end")
    measure_indices = set(indices) | {signal for signal, _ in formations.values()}
    measurements, returns = _measure(closes, benchmark, beta_window, measure_indices, calendar)
    # Insufficient qualifications abort the comparison instead of changing the
    # number of stocks, shortening history, or letting SPY appear successful alone.
    for signal_index, _ in formations.values():
        _targets(measurements[signal_index], "high_beta", benchmark, max_weight)
    canonical = frame.assign(date=frame.date.dt.strftime("%Y-%m-%d")).to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    normalized_hash = hashlib.sha256(canonical).hexdigest()
    config = {"benchmark": benchmark, "beta_window": beta_window, "test_sessions": test_sessions,
              "cost_bps": cost_bps, "max_weight": max_weight, "capital": capital,
              "stock_fraction": .2, "minimum_eligible_stocks": 20, "min_cash_weight": .2,
              "cash_annual_return": 0., "risk_free_rate_used": None,
              "return_basis": "raw_return_market_model", "price_basis": "supplied_daily_OHLC_research_prices",
              "rebalance_schedule": "XNYS_month_end_close_to_next_session_open_plus_initial_formation",
              "evaluation_indices": indices, "evaluation_start": dates[start].date().isoformat(),
              "evaluation_end": dates[-1].date().isoformat(), "annualization": 252,
              "estimator": "centered_OLS_with_intercept", "standard_error_method": "classical_OLS_not_HAC",
              "spy_benchmark_exempt_from_stock_cap": True, "leverage": False, "shorting": False}
    warnings = ["Historical thematic/visitor universe, not a reconstructed historical investable market or S&P index.",
                "Research price returns, not independently verified total returns. Cash earns zero; intercept is not Jensen alpha.",
                "Classical OLS standard errors assume uncorrelated homoskedastic residuals; they are descriptive, not robust inference.",
                "Next-session open is an OHLC execution proxy. Market impact, order-book depth and actual fills are not modelled.",
                "Stock/cash limits apply at rebalance targets; actual weights drift between rebalances.",
                "No signal Rank IC, leverage, shorting, Beta-cap or live orders are implemented by this comparison."]
    if source == "uploaded_csv":
        warnings.append("Visitor-supplied prices have not been independently verified.")
    large_moves = int(frame.groupby("symbol").close.pct_change(fill_method=None).abs().gt(.30).sum())
    if large_moves:
        warnings.append(f"{large_moves} supplied close-to-close moves exceed 30%; retained for review without automatic repair.")
    result = {"source": source, "status": "failed", "metrics": [], "equity": [], "drawdown": [],
              "estimates": list(measurements[len(dates)-1].values()),
              "beta_history": [row for index in indices for row in measurements[index].values()],
              "weights": [], "latest_targets": [], "trades": [], "rebalances": [], "warnings": warnings,
              "config": {key: value for key, value in config.items() if key != "evaluation_indices"}}
    statuses = {}
    for strategy in STRATEGY_IDS:
        try:
            metric, curves, trades, rebals, actual, targets = _simulate(strategy, dates, opens, closes, measurements,
                                                                     formations, config, benchmark)
            result["metrics"].append(metric)
            result["equity"].extend(curves)
            result["drawdown"].extend({"date": row["date"], "strategy": strategy, "drawdown": row["drawdown"]} for row in curves)
            result["trades"].extend(trades)
            result["rebalances"].extend(rebals)
            result["weights"].extend(actual)
            result["latest_targets"].extend(targets)
            statuses[strategy] = {"status": "success", "error": None}
        except (BetaError, ValueError) as error:
            statuses[strategy] = {"status": "failed", "error": str(error)}
            result["metrics"].append({"strategy": strategy, **statuses[strategy], "total_return": None,
                                      "sharpe": None, "max_drawdown": None, "realized_beta": None})
    successful = sum(row["status"] == "success" for row in statuses.values())
    result["status"] = "success" if successful == len(STRATEGY_IDS) else "partial" if successful else "failed"
    result["coverage"] = {"observed_rows": len(frame), "benchmark_sessions": len(dates),
                          "stock_count": closes.shape[1]-1, "evaluation_sessions": len(indices),
                          "latest_eligible_stocks": sum(row["status"] == "success" for row in measurements[len(dates)-1].values()),
                          "missing_stock_rows_preserved": int(closes.drop(columns=benchmark).isna().sum().sum()),
                          "latest_exclusions": [{"symbol": row["symbol"], "reason": row["reason"], "nobs": row["nobs"]}
                                                 for row in measurements[len(dates)-1].values() if row["status"] != "success"],
                          "formation_eligibility": [{"signal_date": dates[s].date().isoformat(),
                                                     "execution_date": dates[e].date().isoformat(), "kind": kind,
                                                     "eligible_stocks": sum(row["status"] == "success" for row in measurements[s].values())}
                                                    for e, (s, kind) in formations.items()]}
    result["lineage"] = {"engine": "daily_beta_comparison_v1", "code_sha256": _CODE_SHA256,
                          "dependencies": _DEPENDENCIES, "normalized_prices_sha256": normalized_hash,
                          "source": source, "rows": len(frame), "model_status": statuses,
                          "estimation_frequency": "daily_close_to_close", "session_calendar": "XNYS",
                          "calendar_version": CALENDAR_VERSION,
                          "beta_availability": "only complete common historical returns through signal close",
                          "availability_scope": "exchange-close research assumption; actual provider delivery/observation latency is not modelled",
                          "evaluation_initialization": "select once at preceding complete close, enter first evaluation open; monthly thereafter",
                          "realized_beta_scope": "regress net account close-to-close returns on benchmark close-to-close returns; first partial session omitted",
                          "predicted_beta_scope": "actual close weights times same-close trailing estimates; forecast exposure for subsequent returns",
                          "costs": "one-way cost_bps charged separately on every actual buy and sell",
                          "final_valuation": "last observed close; no invented final liquidation",
                          "raw_OHLCV_in_report": False, "orders_submitted": False,
                          "project_variation": "not S&P High/Low Beta, BAB, or a claim of market-neutral alpha"}
    return _safe(result)
