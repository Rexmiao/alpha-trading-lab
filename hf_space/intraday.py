"""Independent, bounded five-minute RTH research; never a live execution service.

No daily-date conversion, network access, credentials, market-file reads or model
training. Complete-session screening is retrospective and shared by all rules.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from importlib.metadata import version, PackageNotFoundError
from io import BytesIO
import math
from pathlib import Path
import platform
import re
import threading

import numpy as np
import pandas as pd


COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
STRATEGY_IDS = ("intraday_momentum", "intraday_ma_trend", "opening_range_breakout")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50_000
CALENDAR_VERSION = "4.11.2"
BAR_DURATION = pd.Timedelta(minutes=5)
_BUSY = threading.BoundedSemaphore(1)
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")
_UTC_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)\Z")
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class IntradayError(ValueError):
    """Invalid research inputs, unavailable calendar, or a busy research worker."""


def _iso(value):
    return pd.Timestamp(value).isoformat().replace("+00:00", "Z")


def _now_utc():
    """Server clock boundary, injectable by monkeypatch in deterministic tests."""
    return pd.Timestamp.now(tz="UTC")


def _safe(value):
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return _iso(value)
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _integer(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not lower <= value <= upper:
        raise IntradayError(f"{name} must be an integer in [{lower}, {upper}].")
    return int(value)


def _number(value, name, lower, upper):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise IntradayError(f"{name} must be numeric.")
    value = float(value)
    if not math.isfinite(value) or not lower <= value <= upper:
        raise IntradayError(f"{name} must be finite and in [{lower}, {upper}].")
    return value


def _symbol(value):
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise IntradayError("Use uppercase stock/ETF symbols; URLs, paths and special symbols are not accepted.")
    return value


def _calendar(start, end):
    try:
        installed = version("exchange-calendars")
        if installed != CALENDAR_VERSION:
            raise IntradayError(f"This research requires exchange-calendars=={CALENDAR_VERSION}; found {installed}.")
        import exchange_calendars as xcals
        return xcals.get_calendar("XNYS", start=start, end=end)
    except (ImportError, PackageNotFoundError):
        raise IntradayError(f"Install the pinned research dependency exchange-calendars=={CALENDAR_VERSION}.") from None
    except IntradayError:
        raise
    except Exception as error:
        raise IntradayError(f"XNYS calendar could not cover these dates ({type(error).__name__}).") from None


def _validate(bars, benchmark, *, as_of=None):
    benchmark = _symbol(benchmark)
    if (not isinstance(bars, pd.DataFrame) or not bars.columns.is_unique
            or len(bars.columns) != len(COLUMNS) or set(bars.columns) != set(COLUMNS)):
        raise IntradayError("Provide exactly timestamp,symbol,open,high,low,close,volume.")
    if bars.empty or len(bars) > MAX_ROWS:
        raise IntradayError(f"Provide 1 to {MAX_ROWS} five-minute rows.")
    frame = bars.loc[:, list(COLUMNS)].copy()
    if frame.isna().any().any():
        raise IntradayError("Missing OHLCV or timestamps are not accepted; missing bars must remain absent.")
    try:
        if isinstance(frame.timestamp.dtype, pd.DatetimeTZDtype):
            if any(stamp.utcoffset().total_seconds() != 0 for stamp in frame.timestamp):
                raise IntradayError("Timestamps must use UTC, not local market time.")
            stamps = pd.to_datetime(frame.timestamp, utc=True)
        else:
            values = frame.timestamp.astype(str)
            if not values.str.fullmatch(_UTC_TEXT).all():
                raise IntradayError("timestamp must be UTC ISO text ending Z or +00:00, with seconds; it identifies bar start.")
            stamps = pd.to_datetime(values, utc=True, format="ISO8601", errors="raise")
        if ((stamps.dt.second != 0) | (stamps.dt.microsecond != 0) |
                (stamps.dt.nanosecond != 0) | (stamps.dt.minute % 5 != 0)).any():
            raise IntradayError("Only five-minute start timestamps on the UTC five-minute grid are supported.")
        if (stamps + BAR_DURATION > (as_of if as_of is not None else _now_utc())).any():
            raise IntradayError("Future or not-yet-completed five-minute bars are not accepted.")
        frame["timestamp"] = stamps
        frame["symbol"] = frame.symbol.map(_symbol)
        if frame.duplicated(["timestamp", "symbol"]).any():
            raise IntradayError("Duplicate timestamp/symbol bars are not accepted.")
        for column in COLUMNS[2:]:
            if frame[column].map(lambda item: isinstance(item, (bool, np.bool_))).any():
                raise IntradayError("Boolean OHLCV values are not accepted.")
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    except IntradayError:
        raise
    except (ValueError, TypeError, OverflowError):
        raise IntradayError("Invalid UTC timestamp or numeric OHLCV value.") from None
    if not np.isfinite(frame[list(COLUMNS[2:])].to_numpy()).all():
        raise IntradayError("OHLCV values must be finite.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame.volume < 0).any():
        raise IntradayError("Prices must be positive and volume nonnegative.")
    if ((frame.high < frame[["open", "low", "close"]].max(axis=1)) |
            (frame.low > frame[["open", "high", "close"]].min(axis=1))).any():
        raise IntradayError("Invalid OHLC: low <= open/close <= high is required.")
    symbols = sorted(frame.symbol.unique())
    if benchmark not in symbols or not 1 <= len(set(symbols) - {benchmark}) <= 12:
        raise IntradayError("Provide a separate benchmark and 1 to 12 stock symbols.")
    return frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def parse_intraday_csv(contents: bytes, benchmark="SPY"):
    """Accept bounded UTF-8 CSV bytes only; no filenames, URLs or daily parser."""
    if not isinstance(contents, bytes):
        raise TypeError("CSV contents must be bytes, never a filename or URL.")
    if not contents or len(contents) > MAX_UPLOAD_BYTES:
        raise IntradayError("Upload a nonempty intraday CSV no larger than 8 MiB.")
    try:
        frame = pd.read_csv(BytesIO(contents), encoding="utf-8-sig", keep_default_na=False,
            dtype={"timestamp": str, "symbol": str}, nrows=MAX_ROWS + 1,
            on_bad_lines="error", float_precision="round_trip")
    except (ValueError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        raise IntradayError("CSV could not be parsed as UTF-8 five-minute OHLCV.") from None
    return _validate(frame, benchmark)


def _complete_sessions(frame, *, as_of=None):
    as_of = _now_utc() if as_of is None else as_of
    local_dates = frame.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    first, last = local_dates.min(), local_dates.max()
    if (pd.Timestamp(last) - pd.Timestamp(first)).days > 1827:
        raise IntradayError("The bounded public research reader accepts at most five calendar years per upload.")
    # Calendar construction needs a nonempty range of actual sessions even for
    # a one-day/holiday upload; screening itself still uses only input dates.
    calendar = _calendar(pd.Timestamp(first) - pd.Timedelta(days=7),
                         pd.Timestamp(last) + pd.Timedelta(days=7))
    symbols = sorted(frame.symbol.unique())
    known = {symbol: set(group.timestamp) for symbol, group in frame.groupby("symbol")}
    complete, excluded, valid_slots = [], [], set()
    for session in calendar.sessions_in_range(first, last):
        opening, closing = calendar.session_open(session), calendar.session_close(session)
        expected = pd.date_range(opening, closing, freq="5min", inclusive="left")
        valid_slots.update(expected)
        missing = {}
        for symbol in symbols:
            absent = [stamp for stamp in expected if stamp not in known[symbol]]
            if absent:
                missing[symbol] = {"missing_bars": len(absent), "sample_utc": [_iso(stamp) for stamp in absent[:5]]}
        record = {"session": session.strftime("%Y-%m-%d"), "open": _iso(opening),
                  "close": _iso(closing), "expected_bars": len(expected)}
        if closing > as_of:
            excluded.append({**record, "reason": "session_not_completed", "by_symbol": missing})
        elif missing:
            excluded.append({**record, "reason": "missing_common_RTH_bars", "by_symbol": missing})
        else:
            complete.append({**record, "timestamps": expected})
    outside = ~frame.timestamp.isin(valid_slots)
    coverage = {"input_rows": len(frame), "input_symbols": symbols, "complete_session_count": len(complete),
        "complete_sessions": [{key: value for key, value in item.items() if key != "timestamps"} for item in complete],
        "excluded_sessions": excluded, "excluded_non_RTH_rows": int(outside.sum()),
        "excluded_non_RTH_by_symbol": frame.loc[outside].groupby("symbol").size().to_dict(),
        "no_gap_filling": True, "complete_session_screening_is_retrospective": True}
    return complete, coverage


def _rules(closes, highs, lows, cfg):
    n, assets = closes.shape
    momentum = np.full_like(closes, np.nan)
    length = cfg["lookback_bars"]
    if length < n:
        momentum[length:] = closes[length:] / closes[:-length] - 1
    table = pd.DataFrame(closes)
    fast = table.rolling(cfg["fast_bars"], min_periods=cfg["fast_bars"]).mean().to_numpy()
    slow = table.rolling(cfg["slow_bars"], min_periods=cfg["slow_bars"]).mean().to_numpy()
    ma_score = closes / slow - 1
    ma_eligible = (closes > slow) & (fast > slow)
    channel_score = np.full_like(closes, np.nan)
    channel_eligible = np.zeros((n, assets), dtype=bool)
    length = cfg["opening_range_bars"]
    if length < n:
        upper, lower = highs[:length].max(axis=0), lows[:length].min(axis=0)
        state = np.zeros(assets, dtype=bool)
        for i in range(length, n):
            state = np.where(closes[i] > upper, True, np.where(closes[i] < lower, False, state))
            channel_eligible[i] = state
            channel_score[i] = closes[i] / upper - 1
    return {"intraday_momentum": (momentum, momentum > 0, "within_session_historical_return"),
        "intraday_ma_trend": (ma_score, ma_eligible, "close_to_slow_SMA_minus_one"),
        "opening_range_breakout": (channel_score, channel_eligible, "close_to_frozen_opening_high_minus_one")}


def _account(cash, size):
    return {"cash": float(cash), "quantities": [0] * size, "total_cost": 0.0, "trade_count": 0}


def _equity(account, prices):
    return account["cash"] + sum(quantity * float(price) for quantity, price in zip(account["quantities"], prices))


def _trade(account, symbol, index, delta, reference_price, cfg, *, strategy, session,
           execution_at, signal_available_at, reason):
    if not delta:
        return None
    notional = abs(delta) * float(reference_price)
    fee = notional * cfg["cost_bps"] / 10000
    spread = notional * cfg["half_spread_bps"] / 10000
    slippage = notional * cfg["slippage_bps"] / 10000
    total = fee + spread + slippage
    account["cash"] += -math.copysign(notional, delta) - total
    account["quantities"][index] += delta
    account["total_cost"] += total
    account["trade_count"] += 1
    if account["cash"] < -1e-7 or account["quantities"][index] < 0:
        raise IntradayError("Internal cash/long-only invariant failed; no result is returned.")
    account["cash"] = max(0.0, account["cash"])
    impact = (cfg["half_spread_bps"] + cfg["slippage_bps"]) / 10000
    return {"strategy": strategy, "session": session, "symbol": symbol,
        "side": "BUY" if delta > 0 else "SELL", "quantity": abs(delta), "quantity_delta": delta,
        "reference_price": float(reference_price), "price": float(reference_price) * (1 + math.copysign(impact, delta)),
        "notional": notional, "fee": fee, "spread_cost": spread, "slippage_cost": slippage,
        "total_cost": total, "signal_available_at": signal_available_at, "execution_at": execution_at,
        "reason": reason, "cash_after": account["cash"], "position_after": account["quantities"][index]}


def _target_weights(selected, cfg):
    selected = np.asarray(selected, dtype=bool)
    weights = np.zeros(len(selected))
    if selected.any():
        weights[selected] = min((1 - cfg["cash_floor"]) / selected.sum(), cfg["max_weight"])
    return weights


def _rebalance(account, selected, prices, symbols, cfg, *, strategy, session,
               execution_at, signal_available_at, reason):
    weights = _target_weights(selected, cfg)
    equity = _equity(account, prices)
    rate = (cfg["cost_bps"] + cfg["half_spread_bps"] + cfg["slippage_bps"]) / 10000
    # Reserve an upper bound on costs (sell every old share + buy every target).
    # This keeps rounded post-cost targets within caps and cash nonnegative.
    old_value = equity - account["cash"]
    capital = max(0.0, equity - rate * (old_value + weights.sum() * equity))
    desired = [math.floor(weight * capital / float(price)) for weight, price in zip(weights, prices)]
    deltas = [quantity - current for quantity, current in zip(desired, account["quantities"])]
    trades = []
    for sign in (-1, 1):
        for index, delta in enumerate(deltas):
            if delta * sign > 0:
                trades.append(_trade(account, symbols[index], index, delta, prices[index], cfg,
                    strategy=strategy, session=session, execution_at=execution_at,
                    signal_available_at=signal_available_at, reason=reason))
    actual_equity = _equity(account, prices)
    if (not math.isfinite(actual_equity) or actual_equity <= 0
            or account["cash"] + 1e-7 < cfg["cash_floor"] * actual_equity):
        raise IntradayError("Internal portfolio budget invariant failed.")
    return trades


def _dependencies():
    return {name: version(name) for name in ("numpy", "pandas", "exchange-calendars", "pyluach",
                                            "toolz", "korean-lunar-calendar", "tzdata",
                                            "python-dateutil", "pytz", "six")}


def run_intraday_comparison(bars, benchmark="SPY", source="uploaded_csv", lookback_bars=6,
        fast_bars=3, slow_bars=12, opening_range_bars=6, rebalance_bars=1, max_weight=.2,
        cash_floor=.2, cost_bps=10, half_spread_bps=1, slippage_bps=1,
        execution_delay_bars=0, initial_cash=100000):
    """Run three long/cash rules on common, complete XNYS RTH sessions only."""
    if not _BUSY.acquire(blocking=False):
        raise IntradayError("The intraday CPU worker is busy; try again after the current run.")
    try:
        if source not in {"uploaded_csv", "synthetic"}:
            raise IntradayError("Intraday source must be uploaded_csv or synthetic; there is no online fallback.")
        config = {"lookback_bars": _integer(lookback_bars, "lookback_bars", 1, 60),
            "fast_bars": _integer(fast_bars, "fast_bars", 1, 60),
            "slow_bars": _integer(slow_bars, "slow_bars", 2, 78),
            "opening_range_bars": _integer(opening_range_bars, "opening_range_bars", 1, 30),
            "rebalance_bars": _integer(rebalance_bars, "rebalance_bars", 1, 30),
            "execution_delay_bars": _integer(execution_delay_bars, "execution_delay_bars", 0, 6),
            "max_weight": _number(max_weight, "max_weight", .01, 1),
            "cash_floor": _number(cash_floor, "cash_floor", 0, .95),
            "cost_bps": _number(cost_bps, "cost_bps", 0, 100),
            "half_spread_bps": _number(half_spread_bps, "half_spread_bps", 0, 100),
            "slippage_bps": _number(slippage_bps, "slippage_bps", 0, 100),
            "initial_cash": _number(initial_cash, "initial_cash", 100, 1_000_000_000)}
        if config["fast_bars"] >= config["slow_bars"]:
            raise IntradayError("fast_bars must be smaller than slow_bars.")
        config["common_warmup_bars"] = max(config["lookback_bars"], config["slow_bars"] - 1,
                                            config["opening_range_bars"])
        as_of = _now_utc()
        frame = _validate(bars, benchmark, as_of=as_of)
        sessions, coverage = _complete_sessions(frame, as_of=as_of)
        usable = []
        for session in sessions:
            count = len(session["timestamps"])
            if any(index % config["rebalance_bars"] == 0
                   and index + 1 + config["execution_delay_bars"] < count - 1
                   for index in range(config["common_warmup_bars"], count)):
                usable.append(session)
            else:
                coverage["excluded_sessions"].append({
                    **{key: value for key, value in session.items() if key != "timestamps"},
                    "reason": "insufficient_intraday_window", "by_symbol": {},
                    "common_warmup_bars": config["common_warmup_bars"],
                    "execution_delay_bars": config["execution_delay_bars"],
                    "rebalance_bars": config["rebalance_bars"]})
        coverage["usable_session_count"] = len(usable)
        coverage["usable_sessions"] = [
            {key: value for key, value in item.items() if key != "timestamps"} for item in usable]
        return _simulate(frame, benchmark, source, config, usable, coverage, as_of)
    finally:
        _BUSY.release()


def _simulate(frame, benchmark, source, cfg, sessions, coverage, as_of):
    symbols = sorted(set(frame.symbol) - {benchmark})
    canonical = frame.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode("utf-8")
    warnings = ["Five-minute OHLC execution is a research proxy, not a reconstruction of spreads, queues, partial fills or market impact.",
        "Complete-session screening uses later knowledge of data completeness; excluded sessions can bias a research sample."]
    if source == "synthetic":
        warnings.append("Synthetic teaching prices only, including BENCH: no real market or profitability evidence.")
    if len(sessions) < 20:
        warnings.append("Fewer than 20 complete sessions: Sharpe and annualized statistics are not reported.")
    if coverage["excluded_sessions"] or coverage["excluded_non_RTH_rows"]:
        warnings.append("Incomplete sessions and non-RTH rows were excluded explicitly; no bars or prices were filled.")
    result = {"source": source, "status": "success", "metrics": [], "equity": [], "signals": [],
              "weights": [], "trades": [], "session_metrics": [], "lineage": {}, "warnings": warnings}
    lineage = {"engine": "five_minute_RTH_rules_v1", "config": {"benchmark": benchmark, **cfg},
        "data": {"sha256": hashlib.sha256(canonical).hexdigest(), "rows": len(frame), "symbols": symbols,
            "benchmark": benchmark, "educational_only": source == "synthetic", "bar_minutes": 5,
            "timestamp_convention": "UTC bar start; complete OHLCV becomes available at start + 5 minutes"},
        "coverage": coverage, "as_of_utc": _iso(as_of), "calendar": {"name": "XNYS", "version": CALENDAR_VERSION,
            "timezone": "America/New_York", "DST_and_early_closes": True},
        "dependencies": {**_dependencies(), "python": platform.python_version()},
        "code_sha256": {"hf_space/intraday.py": _CODE_SHA256},
        "execution_proxy": {"signal_available_at": "bar end", "execution": "next bar open plus execution_delay_bars",
            "zero_delay": "same-boundary next-open zero-latency proxy; not a guaranteed executable quote",
            "positive_delay": "one full extra five-minute bar per delay unit",
            "end_of_day": "flatten at the scheduled last bar OPEN; cancel pending targets; no re-entry or overnight holdings",
            "costs": "fee, half-spread and slippage each charged once on reference-open executed notional, additively",
            "integer_sizing": "equal target weights, clipped by cap/cash floor, with conservative gross-turnover cost reserve",
            "risk_model": "none; no volatility targeting or minute-return annualization",
            "drawdown": "close-mark equity observations; intrabar high/low drawdown is not reconstructed"},
        "score_units": "past within-session returns or relative price distances; not forecasts of expected returns",
        "benchmark": {"policy": "buy integer benchmark shares at each RTH first open; exit last bar open; same costs; no cash-floor or asset-cap constraint", "trades": []}}
    result["lineage"] = lineage
    if len(sessions) < 2:
        result["status"] = "insufficient_history"
        result["warnings"].append("At least two common, complete RTH sessions with an executable window after shared warmup and delay are required.")
        return _safe(result)
    accounts = {strategy: _account(cfg["initial_cash"], len(symbols)) for strategy in STRATEGY_IDS}
    last_targets = {}
    bench = _account(cfg["initial_cash"], 1)
    peaks = {strategy: cfg["initial_cash"] for strategy in STRATEGY_IDS}
    rate = (cfg["cost_bps"] + cfg["half_spread_bps"] + cfg["slippage_bps"]) / 10000
    for session_info in sessions:
        session, stamps = session_info["session"], session_info["timestamps"]
        day = frame.loc[frame.timestamp.isin(stamps)]
        tables = {field: day.pivot(index="timestamp", columns="symbol", values=field).reindex(stamps)
                  for field in ("open", "high", "low", "close")}
        closes = tables["close"][symbols].to_numpy(float)
        rules = _rules(closes, tables["high"][symbols].to_numpy(float), tables["low"][symbols].to_numpy(float), cfg)
        pending = {strategy: {} for strategy in STRATEGY_IDS}
        day_start = {strategy: account["cash"] for strategy, account in accounts.items()}
        start_costs = {strategy: (account["total_cost"], account["trade_count"]) for strategy, account in accounts.items()}
        benchmark_start = bench["cash"]
        for index, stamp in enumerate(stamps):
            opens = tables["open"].loc[stamp, symbols].to_numpy(float)
            benchmark_open = float(tables["open"].at[stamp, benchmark])
            terminal = index == len(stamps) - 1
            if index == 0:
                quantity = math.floor(bench["cash"] / (benchmark_open * (1 + rate)))
                trade = _trade(bench, benchmark, 0, quantity, benchmark_open, cfg, strategy="benchmark_rth",
                    session=session, execution_at=_iso(stamp), signal_available_at=None, reason="scheduled_RTH_open")
                if trade:
                    lineage["benchmark"]["trades"].append(trade)
            elif terminal:
                trade = _trade(bench, benchmark, 0, -bench["quantities"][0], benchmark_open, cfg,
                    strategy="benchmark_rth", session=session, execution_at=_iso(stamp),
                    signal_available_at=None, reason="scheduled_last_bar_open_flatten")
                if trade:
                    lineage["benchmark"]["trades"].append(trade)
            benchmark_equity = _equity(bench, [float(tables["close"].at[stamp, benchmark])])
            for strategy, account in accounts.items():
                if terminal:
                    result["trades"].extend(_rebalance(account, np.zeros(len(symbols), dtype=bool), opens, symbols, cfg,
                        strategy=strategy, session=session, execution_at=_iso(stamp), signal_available_at=None,
                        reason="scheduled_last_bar_open_flatten"))
                    pending[strategy].clear()
                elif index in pending[strategy]:
                    eligible, available_at = pending[strategy].pop(index)
                    result["trades"].extend(_rebalance(account, eligible, opens, symbols, cfg, strategy=strategy,
                        session=session, execution_at=_iso(stamp), signal_available_at=available_at, reason="rule_rebalance"))
                    last_targets[strategy] = {"weights": _target_weights(eligible, cfg), "as_of": available_at,
                        "execution_at": _iso(stamp), "reference_prices": opens.copy(),
                        "quantities": list(account["quantities"]), "equity": _equity(account, opens)}
                equity = _equity(account, closes[index])
                if not math.isfinite(equity) or equity <= 0:
                    raise IntradayError("Non-finite research equity; check price magnitudes.")
                peaks[strategy] = max(peaks[strategy], equity)
                result["equity"].append({"timestamp": _iso(stamp + BAR_DURATION), "session": session,
                    "strategy": strategy, "equity": equity, "drawdown": equity / peaks[strategy] - 1,
                    "cash": account["cash"], "benchmark_equity": benchmark_equity, "benchmark_cash": bench["cash"]})
                scores, raw_eligible, unit = rules[strategy]
                execute_index = index + 1 + cfg["execution_delay_bars"]
                tradable = execute_index < len(stamps) - 1
                warmed_up = index >= cfg["common_warmup_bars"]
                anchored = index % cfg["rebalance_bars"] == 0
                eligible = raw_eligible[index] & tradable & warmed_up
                execution_at = _iso(stamps[execute_index]) if tradable and anchored and warmed_up else None
                available_at = _iso(stamp + BAR_DURATION)
                for asset_index, symbol in enumerate(symbols):
                    score = scores[index, asset_index]
                    status = "common_warmup" if not warmed_up else "insufficient_history" if not np.isfinite(score) else (
                        "session_entry_cutoff" if not tradable else "observe_only" if not anchored else
                        "eligible" if eligible[asset_index] else "rule_off")
                    result["signals"].append({"timestamp": _iso(stamp), "available_at": available_at,
                        "execution_at": execution_at, "session": session, "strategy": strategy, "symbol": symbol,
                        "score": float(score) if np.isfinite(score) else None, "score_unit": unit,
                        "rule_eligible": bool(raw_eligible[index, asset_index]), "eligible": bool(eligible[asset_index]), "status": status})
                if tradable and anchored and warmed_up:
                    pending[strategy][execute_index] = (eligible.copy(), available_at)
        for strategy, account in accounts.items():
            if any(account["quantities"]) or pending[strategy]:
                raise IntradayError("An end-of-day flat invariant failed.")
            previous_cost, previous_count = start_costs[strategy]
            result["session_metrics"].append({"strategy": strategy, "session": session,
                "return": account["cash"] / day_start[strategy] - 1, "equity": account["cash"],
                "total_cost": account["total_cost"] - previous_cost,
                "trade_count": account["trade_count"] - previous_count,
                "benchmark_return": bench["cash"] / benchmark_start - 1,
                "benchmark_equity": bench["cash"], "end_positions": 0})
    for strategy, account in accounts.items():
        observations = [row for row in result["session_metrics"] if row["strategy"] == strategy]
        returns = np.array([row["return"] for row in observations], dtype=float)
        std = float(returns.std(ddof=1))
        annual_vol = std * math.sqrt(252) if len(returns) >= 20 else None
        sharpe = float(returns.mean() / std * math.sqrt(252)) if len(returns) >= 20 and std > 1e-12 else None
        result["metrics"].append({"strategy": strategy, "status": "success",
            "total_return": account["cash"] / cfg["initial_cash"] - 1,
            "max_drawdown": min(row["drawdown"] for row in result["equity"] if row["strategy"] == strategy),
            "sharpe": sharpe, "annualized_volatility": annual_vol, "total_cost": account["total_cost"],
            "trade_count": account["trade_count"], "n_sessions": len(sessions)})
        snapshot = last_targets.get(strategy)
        target_weights = snapshot["weights"] if snapshot else np.zeros(len(symbols))
        for index, symbol in enumerate([*symbols, "__CASH__"]):
            cash_row = symbol == "__CASH__"
            value = 1 - float(target_weights.sum()) if cash_row else float(target_weights[index])
            result["weights"].append({"strategy": strategy, "symbol": symbol, "weight": value,
                "target_weight": value, "kind": "target", "asset_kind": "cash" if cash_row else "asset",
                "as_of": snapshot["as_of"] if snapshot else None,
                "execution_at": snapshot["execution_at"] if snapshot else None,
                "quantity_after_execution": None if cash_row or not snapshot else snapshot["quantities"][index],
                "reference_price": None if cash_row or not snapshot else float(snapshot["reference_prices"][index]),
                "scope": "historical_last_executable_target_reference_not_a_current_order" if snapshot else "no_executable_target"})
        result["weights"].append({"strategy": strategy, "symbol": "__CASH__", "weight": 1.0,
            "kind": "actual", "asset_kind": "cash", "as_of": sessions[-1]["close"],
            "scope": "actual_simulated_end_of_day_flat_state"})
    lineage["benchmark"]["total_cost"] = bench["total_cost"]
    lineage["benchmark"]["trade_count"] = bench["trade_count"]
    return _safe(result)


def make_synthetic_intraday_prices(days=5, seed=42):
    """Fixed historical XNYS sessions spanning March 2024 DST; fictional prices."""
    days = _integer(days, "days", 2, 40)
    seed = _integer(seed, "seed", 0, 2**32 - 1)
    calendar = _calendar("2024-03-08", "2024-05-10")
    sessions = calendar.sessions_in_range("2024-03-08", "2024-05-10")[:days]
    rng = np.random.default_rng(seed)
    symbols = ["BENCH", *[f"TOY{index + 1}" for index in range(6)]]
    previous = {symbol: 100.0 + 5 * index for index, symbol in enumerate(symbols)}
    rows = []
    for session in sessions:
        stamps = pd.date_range(calendar.session_open(session), calendar.session_close(session), freq="5min", inclusive="left")
        for stamp in stamps:
            common = rng.normal(.0001, .0014)
            for symbol in symbols:
                opening = previous[symbol] * math.exp(float(rng.normal(0, .0003)))
                close = opening * math.exp(float(common + rng.normal(0, .001)))
                spread = abs(float(rng.normal(.0005, .0002)))
                rows.append([stamp, symbol, opening, max(opening, close) * (1 + spread),
                    min(opening, close) / (1 + spread), close, int(rng.integers(1000, 50000))])
                previous[symbol] = close
    return _validate(pd.DataFrame(rows, columns=COLUMNS), "BENCH")
