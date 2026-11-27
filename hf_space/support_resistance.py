"""Causal, bounded previous-RTH support/resistance research; no broker access.

The three close-confirmed rules share the existing five-minute calendar,
long/cash ledger and next-open cost proxy. They are project rules, not a paper
replication, intrabar stop/OCO engine, or an instruction to submit orders.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import platform

import numpy as np
import pandas as pd

from hf_space import intraday as base

STRATEGY_IDS = ("support_bounce", "resistance_breakout", "breakout_retest")
SRError = base.IntradayError
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def parse_sr_csv(contents: bytes, benchmark="SPY"):
    """Strict bounded UTC bar-start CSV reader; no file paths or URLs."""
    return base.parse_intraday_csv(contents, benchmark)


def _levels(previous, session, symbol, cfg):
    support, resistance = float(previous.low.min()), float(previous.high.max())
    width = cfg["band_bps"] / 10000
    records = {}
    for kind, center in (("support", support), ("resistance", resistance)):
        lower, upper = center * (1 - width), center * (1 + width)
        if not all(math.isfinite(v) and v > 0 for v in (center, lower, upper)):
            raise SRError("Non-finite frozen support/resistance level; no result is returned.")
        records[kind] = {
            "level_id": f"previous_RTH_fixed_bps_v1:{previous.attrs['session']}:{symbol}:{kind}:band={cfg['band_bps']:.17g}",
            "symbol": symbol, "session": session, "type": kind,
            "source": "immediate_previous_complete_common_XNYS_RTH",
            "source_session": previous.attrs["session"],
            "source_available_at": previous.attrs["close"],
            "available_at": previous.attrs["close"], "center": center,
            "lower": lower, "upper": upper,
            "version": "previous_RTH_fixed_bps_v1"}
    if records["support"]["upper"] >= records["resistance"]["lower"]:
        raise SRError("Overlapping support/resistance bands: reduce band_bps; no ambiguous zone is traded.")
    records["previous_close"] = float(previous.close.iloc[-1])
    return records


def _state_path(strategy, symbol, session, stamps, closes, highs, lows, levels, cfg):
    """Prefix-causal state machine. ``stamps`` is the known exchange schedule.

    A setup ID identifies one touch/breakout cycle, not every bar spent in it.
    OHLC identifies a touch bar; it never reveals the order of its extrema.
    """
    support, resistance = levels["support"], levels["resistance"]
    level = support if strategy == "support_bounce" else resistance
    buffer = level["center"] * (cfg["breakout_buffer_bps"] / 10000)
    threshold, invalid = level["upper"] + buffer, level["lower"] - buffer
    if not all(math.isfinite(v) and v > 0 for v in (buffer + level["center"], threshold, invalid)):
        raise SRError("Non-finite frozen confirmation/invalidation threshold; no result is returned.")
    state, cycle, setup_index, touch_at = "flat", 0, None, None
    event_id = None
    traces, events = [], []
    previous_close = levels["previous_close"]
    for index in range(len(closes)):
        stamp, close = stamps[index], float(closes[index])
        before, previous_selected = state, state == "active"
        emitted = []

        def emit(event, reason, old, new, *, preplanned=False):
            available = stamp if preplanned else stamp + base.BAR_DURATION
            row = {"event_id": event_id,
                "event_row_id": f"{event_id or strategy + ':' + symbol + ':' + session}:{event}:{index}",
                "strategy": strategy, "symbol": symbol, "session": session,
                "level_id": level["level_id"], "event": event, "type": event,
                "reason": reason, "timestamp": base._iso(stamp),
                "available_at": base._iso(available), "planned_execution_at": None,
                "execution_at": base._iso(stamp) if preplanned else None,
                "touch_at": touch_at, "from_state": old, "to_state": new,
                "selected": new == "active", "signal_close": None if preplanned else close,
                "level_lower": level["lower"], "level_upper": level["upper"],
                "confirmation_threshold": threshold, "invalidation_threshold": invalid,
                "setup_age_bars": index - setup_index if setup_index is not None else None,
                "preplanned": preplanned}
            events.append(row)
            emitted.append(row)

        reason = "position_active" if state == "active" else "waiting_confirmation" if state == "armed" else "waiting_setup"
        if index == len(stamps) - 1:
            if state != "flat":
                emit("session_reset", "scheduled_last_bar_open_flatten", state, "flat", preplanned=True)
            state, setup_index, touch_at, event_id = "flat", None, None, None
            reason = "scheduled_last_bar_open_flatten"
        elif state == "active":
            stopped = close < invalid
            target = strategy == "support_bounce" and close >= resistance["lower"]
            if stopped or target:
                reason = "close_below_frozen_band" if stopped else "close_reached_resistance_lower"
                emit("exit_confirmed", reason, "active", "flat")
                state, setup_index, touch_at, event_id = "flat", None, None, None
        elif state == "armed":
            age = index - setup_index
            if close < invalid:
                reason = "close_invalidated_setup"
                emit("setup_cancelled", reason, "armed", "flat")
                state, setup_index, touch_at, event_id = "flat", None, None, None
            elif age > cfg["confirmation_bars"]:
                reason = "confirmation_window_expired"
                emit("setup_expired", reason, "armed", "flat")
                state, setup_index, touch_at, event_id = "flat", None, None, None
            elif age > 0 and close > threshold and (strategy == "support_bounce" or
                    (float(lows[index]) <= level["upper"] and float(highs[index]) >= level["lower"])):
                reason = "later_close_confirmed_bounce" if strategy == "support_bounce" else "later_retouch_close_held_above_resistance"
                if strategy == "breakout_retest":
                    touch_at = base._iso(stamp)
                emit("entry_confirmed", reason, "armed", "active")
                state = "active"
        else:
            overlap = float(lows[index]) <= level["upper"] and float(highs[index]) >= level["lower"]
            upward_cross = previous_close <= threshold and close > threshold
            if strategy == "support_bounce":
                if previous_close > level["upper"] and overlap and close >= level["lower"]:
                    cycle += 1
                    event_id = f"{strategy}:{symbol}:{session}:{cycle}"
                    setup_index, touch_at, state = index, base._iso(stamp), "armed"
                    reason = "support_touch_from_above"
                    emit("setup_armed", reason, "flat", "armed")
            elif upward_cross:
                cycle += 1
                event_id = f"{strategy}:{symbol}:{session}:{cycle}"
                setup_index = index
                if strategy == "resistance_breakout":
                    state, reason = "active", "close_crossed_resistance_upper"
                    emit("entry_confirmed", reason, "flat", "active")
                else:
                    state, reason = "armed", "breakout_waiting_later_retest"
                    emit("setup_armed", reason, "flat", "armed")
        selected = state == "active"
        execute_index = index + 1 + cfg["execution_delay_bars"]
        tradable = execute_index < len(stamps) - 1
        planned = base._iso(stamps[execute_index]) if tradable and selected != previous_selected else None
        for event in emitted:
            if event["event"] in {"entry_confirmed", "exit_confirmed"}:
                event["planned_execution_at"] = planned
        traces.append({"timestamp": base._iso(stamp), "available_at": base._iso(stamp + base.BAR_DURATION),
            "session": session, "strategy": strategy, "symbol": symbol,
            "state": state, "previous_state": before, "selected": selected,
            "rule_eligible": selected, "eligible": bool(selected and tradable),
            "selection_changed": selected != previous_selected,
            "execution_at": planned, "reason": reason,
            "status": "session_entry_cutoff" if selected and not tradable else state,
            "event_id": event_id, "touch_at": touch_at,
            "transition_event_ids": [r["event_id"] for r in emitted if r["event_id"]],
            "signal_close": close, "level_id": level["level_id"],
            "level_lower": level["lower"], "level_upper": level["upper"],
            "confirmation_threshold": threshold, "invalidation_threshold": invalid,
            "level_available_at": level["available_at"]})
        previous_close = close
    return traces, events


def _config(*, band_bps, breakout_buffer_bps, confirmation_bars, execution_delay_bars,
            max_weight, cash_floor, cost_bps, half_spread_bps, slippage_bps, initial_cash):
    return {"band_bps": base._number(band_bps, "band_bps", 0, 500),
        "breakout_buffer_bps": base._number(breakout_buffer_bps, "breakout_buffer_bps", 0, 500),
        "confirmation_bars": base._integer(confirmation_bars, "confirmation_bars", 1, 78),
        "execution_delay_bars": base._integer(execution_delay_bars, "execution_delay_bars", 0, 6),
        "max_weight": base._number(max_weight, "max_weight", .01, 1),
        "cash_floor": base._number(cash_floor, "cash_floor", 0, .95),
        "cost_bps": base._number(cost_bps, "cost_bps", 0, 100),
        "half_spread_bps": base._number(half_spread_bps, "half_spread_bps", 0, 100),
        "slippage_bps": base._number(slippage_bps, "slippage_bps", 0, 100),
        "initial_cash": base._number(initial_cash, "initial_cash", 100, 1_000_000_000)}


def run_sr_comparison(bars, *, benchmark="SPY", source="uploaded_csv", band_bps=10,
        breakout_buffer_bps=0, confirmation_bars=12, execution_delay_bars=0,
        max_weight=.2, cash_floor=.2, cost_bps=10, half_spread_bps=1,
        slippage_bps=1, initial_cash=100000):
    """Compare three prior-RTH-level rules and same-day SPY RTH, without orders."""
    if not base._BUSY.acquire(blocking=False):
        raise SRError("The intraday CPU worker is busy; try again after the current run.")
    try:
        if source not in {"moomoo_snapshot", "uploaded_csv", "synthetic"}:
            raise SRError("SR source must be moomoo_snapshot, uploaded_csv or synthetic; no fallback is allowed.")
        cfg = _config(band_bps=band_bps, breakout_buffer_bps=breakout_buffer_bps,
            confirmation_bars=confirmation_bars, execution_delay_bars=execution_delay_bars,
            max_weight=max_weight, cash_floor=cash_floor, cost_bps=cost_bps,
            half_spread_bps=half_spread_bps, slippage_bps=slippage_bps, initial_cash=initial_cash)
        return _run(bars, benchmark, source, cfg)
    except (OverflowError, FloatingPointError):
        raise SRError("Non-finite numerical research calculation; no result is returned.") from None
    finally:
        base._BUSY.release()


def _run(bars, benchmark, source, cfg):
    as_of = base._now_utc()
    frame = base._validate(bars, benchmark, as_of=as_of)
    sessions, coverage = base._complete_sessions(frame, as_of=as_of)
    symbols = sorted(set(frame.symbol) - {benchmark})
    first = frame.timestamp.min().normalize().tz_localize(None)
    last = frame.timestamp.max().normalize().tz_localize(None)
    calendar = base._calendar(first - pd.Timedelta(days=7), last + pd.Timedelta(days=7))
    by_session = {s["session"]: s for s in sessions}
    usable, skipped = [], []
    for session in sessions:
        previous = calendar.previous_session(pd.Timestamp(session["session"])).strftime("%Y-%m-%d")
        if previous in by_session:
            usable.append((session, by_session[previous]))
        else:
            skipped.append({"session": session["session"], "previous_exchange_session": previous,
                            "reason": "immediate_previous_exchange_session_not_complete_common"})
    coverage.update({"evaluated_session_count": len(usable), "usable_session_count": len(usable),
        "evaluated_sessions": [s["session"] for s, _ in usable],
        "warmup_or_missing_previous_sessions": skipped,
        "previous_level_session_policy": "immediate_previous_XNYS_session_only_no_gap_bridge"})
    canonical = frame.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode()
    result = {"source": source, "status": "success", "metrics": [], "equity": [], "drawdown": [],
        "signals": [], "events": [], "levels": [], "weights": [], "trades": [],
        "session_metrics": [], "coverage": coverage, "config": {"benchmark": benchmark, **cfg},
        "lineage": {"engine": "previous_RTH_support_resistance_v1", "as_of_utc": base._iso(as_of),
            "data": {"sha256": hashlib.sha256(canonical).hexdigest(), "rows": len(frame),
                "symbols": symbols, "benchmark": benchmark, "educational_only": source == "synthetic",
                "bar_minutes": 5, "timestamp_convention": "UTC bar start; OHLC available after five minutes"},
            "calendar": {"name": "XNYS", "version": base.CALENDAR_VERSION, "timezone": "America/New_York"},
            "dependencies": {**base._dependencies(), "python": platform.python_version()},
            "code_sha256": {"hf_space/support_resistance.py": _CODE_SHA256, "hf_space/intraday.py": base._CODE_SHA256},
            "execution_proxy": {"execution": "next bar open plus execution_delay_bars",
                "zero_delay": "same-boundary zero-latency OHLC proxy; no guaranteed executable quote",
                "end_of_day": "preplanned last bar open overrides pending targets; no re-entry or overnight",
                "rebalance": "only on change in strategy selection vector; persistent active states",
                "pending_targets": "latest close-known changed selection supersedes unexecuted targets; executed history is immutable",
                "costs": "fee + half-spread + slippage charged separately once per reference-open notional",
                "stops_targets": "completed-bar close-confirmed exits; no intrabar stop, OCO or favorable extrema ordering"},
            "level_policy": "immediate previous common complete XNYS RTH high/low, fixed symmetric bps bands",
            "level_overlap_policy": "support upper must be strictly below resistance lower; otherwise the run fails without zone repair",
            "touch_timestamp_scope": "touch_at identifies the bar start, not the unknown intrabar instant; event is available at bar end",
            "confirmation_window": "strict later bars with age 1..confirmation_bars inclusive; expire before age N+1 confirmation",
            "raw_OHLCV_in_report": False, "orders_submitted": False},
        "warnings": ["Project support/resistance rules, not a complete reproduction of a cited paper or evidence of profitability.",
            "Complete common-session screening uses later data completeness and may bias the sample; prices are never filled.",
            "Previous-day bands are frozen before the evaluated session; no pivot, ZigZag or full-sample clustering is used.",
            "Close-confirmed exits and next-open execution are OHLC proxies, without depth, queues, partial fills or market impact.",
            f"{benchmark} RTH benchmark is fully invested within each evaluated day and does not share stock caps/cash floor.",
            "Targets obey cap/cash constraints at rebalance; actual positions drift between selection changes."]}
    result["lineage"]["coverage"], result["lineage"]["config"] = coverage, result["config"]
    if source == "synthetic":
        result["warnings"].append("Synthetic teaching prices only; these are not market returns.")
    if len(usable) < 20:
        result["warnings"].append("Fewer than 20 evaluated sessions: no Sharpe or annualized statistics are reported.")
    if len(usable) < 2:
        result["status"] = "insufficient_history"
        result["warnings"].append("At least two evaluated complete common RTH sessions, each with its immediate previous complete common session, are required.")
        return base._safe(result)
    accounts = {s: base._account(cfg["initial_cash"], len(symbols)) for s in STRATEGY_IDS}
    accounts["benchmark_rth"] = base._account(cfg["initial_cash"], 1)
    peaks = dict.fromkeys(accounts, cfg["initial_cash"])
    last_targets = {}
    rate = (cfg["cost_bps"] + cfg["half_spread_bps"] + cfg["slippage_bps"]) / 10000
    for session, previous in usable:
        name, stamps = session["session"], session["timestamps"]
        day = frame.loc[frame.timestamp.isin(stamps)]
        prior = frame.loc[frame.timestamp.isin(previous["timestamps"])]
        tables = {field: day.pivot(index="timestamp", columns="symbol", values=field).reindex(stamps)
                  for field in ("open", "high", "low", "close")}
        # Preserve the explicit schedule/symbol order, then avoid pandas row
        # indexing inside the bar loop. These arrays expose the same supplied
        # bars as the existing tables; decision availability is unchanged.
        stock_opens = tables["open"].loc[:, symbols].to_numpy(float)
        stock_closes = tables["close"].loc[:, symbols].to_numpy(float)
        benchmark_opens = tables["open"][benchmark].to_numpy(float)
        benchmark_closes = tables["close"][benchmark].to_numpy(float)
        paths, pending = {}, {s: {} for s in STRATEGY_IDS}
        for symbol in symbols:
            history = prior.loc[prior.symbol.eq(symbol)].copy()
            history.attrs.update(session=previous["session"], close=previous["close"])
            levels = _levels(history, name, symbol, cfg)
            result["levels"].extend(levels[k] for k in ("support", "resistance"))
            for strategy in STRATEGY_IDS:
                path, events = _state_path(strategy, symbol, name, stamps,
                    tables["close"][symbol].to_numpy(), tables["high"][symbol].to_numpy(),
                    tables["low"][symbol].to_numpy(), levels, cfg)
                paths[(strategy, symbol)] = path
                result["signals"].extend(path)
                result["events"].extend(events)
        selected_before = {s: np.zeros(len(symbols), dtype=bool) for s in STRATEGY_IDS}
        day_start = {s: a["cash"] for s, a in accounts.items()}
        starts = {s: (a["total_cost"], a["trade_count"]) for s, a in accounts.items()}
        for index, stamp in enumerate(stamps):
            opening = stock_opens[index]
            closing = stock_closes[index]
            terminal = index == len(stamps) - 1
            bench = accounts["benchmark_rth"]
            benchmark_open = float(benchmark_opens[index])
            if index == 0 or terminal:
                quantity = math.floor(bench["cash"] / (benchmark_open * (1 + rate))) if index == 0 else -bench["quantities"][0]
                trade = base._trade(bench, benchmark, 0, quantity, benchmark_open, cfg,
                    strategy="benchmark_rth", session=name, execution_at=base._iso(stamp),
                    signal_available_at=None, reason="scheduled_RTH_open" if index == 0 else "scheduled_last_bar_open_flatten")
                if trade:
                    result["trades"].append(trade)
            for strategy in STRATEGY_IDS:
                account = accounts[strategy]
                target = None
                if terminal:
                    for cancelled_index, (_, cancelled_available, cancelled_ids) in pending[strategy].items():
                        result["events"].append(_cancel_event(strategy, name, stamp, stamps[cancelled_index],
                            cancelled_available, cancelled_ids, "scheduled_last_bar_open_cancel"))
                    target, available, ids = np.zeros(len(symbols), dtype=bool), None, []
                    pending[strategy].clear()
                    reason = "scheduled_last_bar_open_flatten"
                elif index in pending[strategy]:
                    target, available, ids = pending[strategy].pop(index)
                    reason = "selection_change"
                if target is not None:
                    trades = base._rebalance(account, target, opening, symbols, cfg, strategy=strategy,
                        session=name, execution_at=base._iso(stamp), signal_available_at=available, reason=reason)
                    for trade in trades:
                        trade["signal_event_ids"] = ids
                    result["trades"].extend(trades)
                    if not terminal:
                        last_targets[strategy] = {"weights": base._target_weights(target, cfg), "as_of": available,
                            "execution_at": base._iso(stamp), "quantities": list(account["quantities"]),
                            "reference_prices": opening.copy()}
                    result["events"].append({"event_id": None, "event_row_id": f"{strategy}:{name}:{index}:target_execution",
                        "strategy": strategy, "symbol": None, "session": name, "level_id": None,
                        "event": "target_execution", "type": "target_execution", "reason": reason,
                        "timestamp": base._iso(stamp), "available_at": available,
                        "planned_execution_at": base._iso(stamp), "execution_at": base._iso(stamp),
                        "touch_at": None, "from_state": None, "to_state": "flat" if terminal else "selection_applied",
                        "selected": bool(target.any()), "signal_event_ids": ids, "trade_count": len(trades),
                        "target_weights": dict(zip(symbols, base._target_weights(target, cfg)))} )
                path_rows = [paths[(strategy, symbol)][index] for symbol in symbols]
                selected = np.array([r["selected"] for r in path_rows], dtype=bool)
                execute_index = index + 1 + cfg["execution_delay_bars"]
                if not terminal and not np.array_equal(selected, selected_before[strategy]):
                    for cancelled_index, (_, cancelled_available, cancelled_ids) in pending[strategy].items():
                        result["events"].append(_cancel_event(strategy, name, stamp, stamps[cancelled_index],
                            cancelled_available, cancelled_ids, "newer_close_selection_superseded_pending"))
                    pending[strategy].clear()
                    if execute_index < len(stamps) - 1:
                        ids = sorted({event_id for r in path_rows
                                      for event_id in ([r["event_id"]] if r["event_id"] else []) + r["transition_event_ids"]})
                        pending[strategy][execute_index] = selected.copy(), base._iso(stamp + base.BAR_DURATION), ids
                selected_before[strategy] = selected
            for strategy, account in accounts.items():
                valuation = [float(benchmark_closes[index])] if strategy == "benchmark_rth" else closing
                equity = base._equity(account, valuation)
                if not math.isfinite(equity) or equity <= 0:
                    raise SRError("Non-finite research equity; no result is returned.")
                peaks[strategy] = max(peaks[strategy], equity)
                row = {"timestamp": base._iso(stamp + base.BAR_DURATION), "session": name,
                       "strategy": strategy, "equity": equity, "drawdown": equity / peaks[strategy] - 1,
                       "cash": account["cash"]}
                result["equity"].append(row)
                result["drawdown"].append({k: row[k] for k in ("timestamp", "session", "strategy", "drawdown")})
        for strategy, account in accounts.items():
            if any(account["quantities"]) or (strategy in pending and pending[strategy]):
                raise SRError("End-of-day flat invariant failed.")
            result["session_metrics"].append({"strategy": strategy, "session": name,
                "return": account["cash"] / day_start[strategy] - 1, "equity": account["cash"],
                "total_cost": account["total_cost"] - starts[strategy][0],
                "trade_count": account["trade_count"] - starts[strategy][1], "end_positions": 0})
    for strategy, account in accounts.items():
        observations = [r["return"] for r in result["session_metrics"] if r["strategy"] == strategy]
        returns = np.asarray(observations, dtype=float)
        deviation = float(returns.std(ddof=1))
        if not np.isfinite(returns).all() or not math.isfinite(deviation):
            raise SRError("Non-finite daily performance statistics; no result is returned.")
        total = account["cash"] / cfg["initial_cash"] - 1
        annual = math.expm1(math.log1p(total) * 252 / len(usable)) if len(usable) >= 20 else None
        trades = [t for t in result["trades"] if t["strategy"] == strategy]
        result["metrics"].append({"strategy": strategy, "status": "success", "total_return": total,
            "max_drawdown": min(r["drawdown"] for r in result["equity"] if r["strategy"] == strategy),
            "sharpe": float(returns.mean() / deviation * math.sqrt(252)) if len(usable) >= 20 and deviation > 1e-12 else None,
            "annualized_volatility": deviation * math.sqrt(252) if len(usable) >= 20 else None,
            "annual_return": annual, "total_cost": account["total_cost"],
            "fee": sum(t["fee"] for t in trades), "spread_cost": sum(t["spread_cost"] for t in trades),
            "slippage_cost": sum(t["slippage_cost"] for t in trades),
            "trade_count": account["trade_count"], "n_sessions": len(usable), "final_equity": account["cash"]})
        if strategy != "benchmark_rth":
            snapshot = last_targets.get(strategy)
            weights = snapshot["weights"] if snapshot else np.zeros(len(symbols))
            for index, symbol in enumerate([*symbols, "__CASH__"]):
                cash_row = symbol == "__CASH__"
                weight = 1 - float(weights.sum()) if cash_row else float(weights[index])
                result["weights"].append({"strategy": strategy, "symbol": symbol, "weight": weight,
                    "target_weight": weight, "kind": "target", "asset_kind": "cash" if cash_row else "asset",
                    "as_of": snapshot["as_of"] if snapshot else None, "execution_at": snapshot["execution_at"] if snapshot else None,
                    "quantity_after_execution": None if cash_row or not snapshot else snapshot["quantities"][index],
                    "reference_price": None if cash_row or not snapshot else float(snapshot["reference_prices"][index]),
                    "scope": "historical_last_executed_selection_target_not_a_current_order"})
        result["weights"].append({"strategy": strategy, "symbol": "__CASH__", "weight": 1.,
            "kind": "actual", "asset_kind": "cash", "as_of": usable[-1][0]["close"],
            "scope": "actual_simulated_end_of_day_flat_state"})
    result["events"].sort(key=lambda r: (r["timestamp"], r["strategy"], r["symbol"] or "", r["event_row_id"]))
    result["lineage"]["benchmark"] = {"strategy": "benchmark_rth", "symbol": benchmark,
        "policy": "integer benchmark shares from first RTH open to last bar open, same evaluated days/costs; no asset cap/cash-floor constraint"}
    return base._safe(result)


def _cancel_event(strategy, session, observed_stamp, cancelled_stamp, signal_available, ids, reason):
    preplanned = reason.startswith("scheduled_")
    available = observed_stamp if preplanned else observed_stamp + base.BAR_DURATION
    return {"event_id": None,
        "event_row_id": f"{strategy}:{session}:{base._iso(observed_stamp)}:{base._iso(cancelled_stamp)}:target_superseded",
        "strategy": strategy, "symbol": None, "session": session, "level_id": None,
        "event": "target_superseded", "type": "target_superseded", "reason": reason,
        "timestamp": base._iso(observed_stamp), "available_at": base._iso(available),
        "planned_execution_at": base._iso(cancelled_stamp), "execution_at": None,
        "touch_at": None, "from_state": "pending", "to_state": "cancelled",
        "selected": False, "signal_event_ids": ids, "original_signal_available_at": signal_available,
        "preplanned": preplanned}
