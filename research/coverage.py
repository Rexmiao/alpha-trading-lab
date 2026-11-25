"""Offline per-security history coverage without shortening the whole universe.

Start dates are user-supplied research boundaries, not verified IPO assertions.
Coverage flags describe data availability; they never fill missing observations
or silently remove securities from a training universe.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import re

import numpy as np
import pandas as pd

from research.data import build_dataset


def _symbol(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("coverage_invalid_symbol")
    return value.strip().upper().removeprefix("US.")


def _session_date(value):
    if isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError("coverage_dates_must_be_explicit_session_dates")
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("coverage_missing_date")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("America/New_York").tz_localize(None)
    return stamp.normalize()


def _iso(value):
    return None if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def _frame(prices):
    if not isinstance(prices, pd.DataFrame) or not {"date", "symbol"}.issubset(prices.columns):
        raise ValueError("coverage_prices_require_date_and_symbol")
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"].map(_session_date))
    # Canonicalization is confined to the copy; callers retain their raw frame.
    frame["symbol"] = frame["symbol"].map(_symbol)
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("duplicate_daily_bar")
    return frame


def _boundaries(config):
    if not isinstance(config, Mapping):
        raise TypeError("Coverage config must be a mapping.")
    supplied = config.get("symbol_start_dates", {})
    if not isinstance(supplied, Mapping):
        raise ValueError("symbol_start_dates_must_be_a_mapping")
    result = {}
    for symbol, value in supplied.items():
        key = _symbol(symbol)
        if key in result:
            raise ValueError("duplicate_symbol_start_boundary")
        if not isinstance(value, (str, date, datetime, pd.Timestamp)):
            raise ValueError("invalid_symbol_start_date")
        if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("symbol_start_date_requires_iso_date")
        result[key] = _session_date(value)
    return result


def apply_history_boundaries(prices, config):
    """Exclude only each configured symbol's pre-boundary bars and audit it.

    No default dates are inferred from ticker names, listing claims or other
    securities. No backward fill, synthetic history or global intersection is
    applied. The returned dates are normalized exchange-session dates.
    """
    frame = _frame(prices)
    boundaries = _boundaries(config)
    keep = pd.Series(True, index=frame.index)
    records = []
    for symbol, boundary in sorted(boundaries.items()):
        observed = frame.loc[frame.symbol.eq(symbol)]
        removed = observed.loc[observed.date.lt(boundary)]
        retained = observed.loc[observed.date.ge(boundary)]
        keep &= ~(frame.symbol.eq(symbol) & frame.date.lt(boundary))
        records.append({"symbol": symbol, "start_date": _iso(boundary),
                        "n_before": int(len(observed)), "n_removed": int(len(removed)),
                        "n_after": int(len(retained)),
                        "observed_first_before": _iso(observed.date.min()) if len(observed) else None,
                        "observed_first_after": _iso(retained.date.min()) if len(retained) else None,
                        "removed_first": _iso(removed.date.min()) if len(removed) else None,
                        "removed_last": _iso(removed.date.max()) if len(removed) else None,
                        "policy": "exclude_pre_boundary_no_backfill",
                        "boundary_source": "config.symbol_start_dates_not_independently_verified"})
    return frame.loc[keep].copy(), records


def _requirements(config):
    defaults = {"lookback": 30, "horizon": 5, "minimum_train_days": 120,
                "validation_days": 50, "test_days": 100}
    settings = {}
    for key, default in defaults.items():
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < (5 if key == "lookback" else 1):
            raise ValueError("invalid_coverage_parameter:" + key)
        settings[key] = int(value)
    warmup = max(settings["lookback"], 20)
    lookahead = settings["horizon"] + 1
    purge_buffer = 2 * lookahead
    partition_days = settings["minimum_train_days"] + settings["validation_days"] + settings["test_days"]
    return {**settings, "warmup_bars": warmup, "label_lookahead_bars": lookahead,
            "purge_buffer_bars": purge_buffer,
            "minimum_labeled_rows_estimate": partition_days + purge_buffer,
            "minimum_bars_estimate": warmup + lookahead + partition_days + purge_buffer,
            "estimate_policy": "conservative_per_symbol_preflight_not_a_global_split_guarantee"}


def assess_coverage(prices, config, benchmark_symbol=None):
    """Return JSON-safe coverage and warnings for each requested/observed symbol.

    Feature availability is calculated once using the existing dataset builder.
    The builder reindexes every symbol on the benchmark calendar independently;
    an IPO never truncates another stock's older usable history. ``eligible`` is
    a conservative history precheck, not permission to trade or proof that the
    stock participates in every eventual global chronological partition.
    """
    raw = _frame(prices)
    filtered, audit = apply_history_boundaries(raw, config)
    requirements = _requirements(config)
    benchmark_symbol = _symbol(benchmark_symbol or config.get("benchmark", "SPY"))
    boundaries = _boundaries(config)
    audit_map = {r["symbol"]: r for r in audit}
    universe = config.get("universe", [])
    if not isinstance(universe, (list, tuple)):
        raise ValueError("coverage_universe_must_be_a_list")
    symbols = list(dict.fromkeys([_symbol(s) for s in universe] + sorted(raw.symbol.unique().tolist())
                                + sorted(boundaries) + [benchmark_symbol]))
    benchmark_dates = pd.DatetimeIndex(sorted(filtered.loc[filtered.symbol.eq(benchmark_symbol), "date"].unique()))
    benchmark_present = len(benchmark_dates) > 0
    feature_counts, labeled_counts = {}, {}
    warnings = []
    feature_assessment = "unavailable"
    required_fields = {"open", "high", "low", "close", "volume"}
    missing_fields = sorted(required_fields - set(filtered.columns))
    stock_present = not filtered.loc[~filtered.symbol.eq(benchmark_symbol)].empty
    if not benchmark_present:
        warnings.append("benchmark_missing: no alignment calendar or excess-return labels available")
    elif missing_fields:
        warnings.append("feature_fields_missing:" + ",".join(missing_fields))
    elif stock_present:
        numeric = filtered[list(required_fields)].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype=float)).all():
            warnings.append("feature_inputs_nonfinite_or_nonnumeric: feature availability not certified")
        elif (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric.volume < 0).any():
            warnings.append("feature_inputs_invalid_prices_or_volume: feature availability not certified")
        elif (numeric.low > numeric[["open", "close"]].min(axis=1)).any() or (numeric.high < numeric[["open", "close"]].max(axis=1)).any():
            warnings.append("feature_inputs_inconsistent_ohlc: feature availability not certified")
        else:
            feature_prices = filtered.copy()
            feature_prices[numeric.columns] = numeric
            dataset, _, _ = build_dataset(feature_prices, benchmark_symbol,
                                           horizon=requirements["horizon"], lookback=requirements["lookback"])
            feature_counts = dataset.groupby("symbol").size().astype(int).to_dict()
            labeled_counts = dataset.dropna(subset=["target", "label_end"]).groupby("symbol").size().astype(int).to_dict()
            feature_assessment = "computed_once_with_research.data.build_dataset"
    elif benchmark_present:
        warnings.append("stock_universe_missing: benchmark alone cannot train an equity predictor")
    records = []
    for symbol in symbols:
        observed = filtered.loc[filtered.symbol.eq(symbol)].sort_values("date")
        n_bars = int(len(observed))
        first = observed.date.min() if n_bars else None
        last = observed.date.max() if n_bars else None
        own_dates = pd.DatetimeIndex(observed.date)
        is_benchmark = symbol == benchmark_symbol
        missing_dates = pd.DatetimeIndex([])
        outside_dates = pd.DatetimeIndex([])
        stale_sessions = 0
        if benchmark_present and n_bars and not is_benchmark:
            active_calendar = benchmark_dates[(benchmark_dates >= first) & (benchmark_dates <= last)]
            missing_dates = active_calendar.difference(own_dates)
            outside_dates = own_dates.difference(benchmark_dates)
            stale_sessions = int((benchmark_dates > last).sum())
        own_warnings = []
        if not n_bars:
            own_warnings.append("no_observations_after_history_boundary")
        if n_bars < requirements["minimum_bars_estimate"]:
            own_warnings.append("short_history_for_conservative_independent_split")
        if len(missing_dates):
            own_warnings.append("missing_sessions_within_observed_history_no_fill")
        if len(outside_dates):
            own_warnings.append("observed_dates_absent_from_benchmark_calendar")
        if stale_sessions:
            own_warnings.append("latest_benchmark_session_unavailable")
        removed = int(audit_map.get(symbol, {}).get("n_removed", 0))
        if removed:
            own_warnings.append("pre_boundary_history_excluded")
        computed = feature_assessment.startswith("computed_once") and not is_benchmark
        feature_rows = int(feature_counts.get(symbol, 0)) if computed else None
        labeled_rows = int(labeled_counts.get(symbol, 0)) if computed else None
        enough_bars = n_bars >= requirements["minimum_bars_estimate"]
        eligible = bool(benchmark_present and enough_bars and not len(outside_dates)
                        and ((is_benchmark and n_bars > 0) or
                             (computed and labeled_rows >= requirements["minimum_labeled_rows_estimate"])))
        if not benchmark_present:
            status = "benchmark_missing"
        elif not n_bars:
            status = "missing_data"
        elif not enough_bars:
            status = "short_history"
        elif not is_benchmark and not computed:
            status = "feature_assessment_unavailable"
        elif eligible:
            status = "sufficient_history_with_warnings" if own_warnings else "sufficient_history"
        else:
            status = "insufficient_usable_history"
        records.append({"symbol": symbol, "is_benchmark": is_benchmark,
                        "first": _iso(first), "last": _iso(last), "n_bars": n_bars,
                        "n_raw_bars": int(raw.symbol.eq(symbol).sum()),
                        "boundary_start": _iso(boundaries.get(symbol)),
                        "removed_before_boundary": removed,
                        "usable_feature_rows": feature_rows, "labeled_rows": labeled_rows,
                        "eligible": eligible, "status": status, "warnings": own_warnings,
                        "missing_benchmark_sessions": int(len(missing_dates)),
                        "missing_session_dates": [_iso(d) for d in missing_dates],
                        "non_benchmark_session_dates": [_iso(d) for d in outside_dates],
                        "stale_benchmark_sessions": stale_sessions,
                        "latest_session_available": bool(n_bars and benchmark_present and last == benchmark_dates[-1])})
    return {"benchmark_symbol": benchmark_symbol,
            "benchmark_first": _iso(benchmark_dates[0]) if benchmark_present else None,
            "benchmark_last": _iso(benchmark_dates[-1]) if benchmark_present else None,
            "requirements": requirements, "symbols": records,
            "eligible_symbols": [r["symbol"] for r in records if r["eligible"] and not r["is_benchmark"]],
            "feature_assessment": feature_assessment, "history_boundaries": audit,
            "warnings": warnings,
            "policy": "independent_symbol_history_no_global_minimum_start_no_backfill",
            "eligibility_scope": "coverage_preflight_only_not_trade_authorization_or_split_validation"}
