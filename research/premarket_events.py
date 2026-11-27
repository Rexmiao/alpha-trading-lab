"""Pure, calendar-supplied minute-bar event statistics for QQQ, SPY and DIA.

These are descriptive historical-bar frequencies, not executable backtests or
calibrated forecasts. Unknown observations never become zero-return events.
The collector, credentials, calendar acquisition and publication live elsewhere.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
from statistics import mean
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DEFINITIONS = ("fixed_0925", "fixed_0929", "ever_before_0925", "ever_before_open")
DEFAULT_THRESHOLDS = (.005, .01, .02)
DEFAULT_PREMARKET_THRESHOLDS = (.005, .01, .015, .02, .025, .03)
MAX_ROWS = 2_000_000
SCHEMA_VERSION = "premarket-events-v1"


class PremarketError(ValueError):
    """A malformed declaration, rather than an unavailable market observation."""


def _date(value) -> date:
    if isinstance(value, datetime):
        raise PremarketError("date_not_datetime_required")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise PremarketError("invalid_date") from None


def _aware(value) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise PremarketError("invalid_aware_time") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PremarketError("timezone_required")
    return dt


def _local(day: date, clock: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), NY)


def _decimal(value, *, positive=False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid_numeric") from None
    if not result.is_finite() or result < 0 or (positive and result == 0) or result > Decimal("1e15"):
        raise ValueError("invalid_numeric")
    return result


def _thresholds(values):
    try:
        result = tuple(_decimal(x, positive=True) for x in values)
    except (TypeError, ValueError):
        raise PremarketError("invalid_thresholds") from None
    if not result or len(result) > 10 or len(set(result)) != len(result) or any(x >= 1 for x in result):
        raise PremarketError("invalid_thresholds")
    return result


def _threshold_key(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".")


def _return_ratio(price: Decimal, reference: Decimal) -> dict:
    """Reduced exact return sufficient statistic, with no minute OHLCV table."""
    value = (Fraction(price) - Fraction(reference)) / Fraction(reference)
    return _ratio(value)


def _ratio(value: Fraction) -> dict:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _fraction(ratio: Mapping) -> Fraction:
    return Fraction(int(ratio["numerator"]), int(ratio["denominator"]))


def _calendar(sessions: Mapping) -> dict[date, dict]:
    if not isinstance(sessions, Mapping) or not sessions:
        raise PremarketError("calendar_sessions_required")
    out = {}
    for day, raw in sessions.items():
        d = _date(day)
        if not isinstance(raw, Mapping) or not {"open", "close"} <= raw.keys():
            raise PremarketError("calendar_open_close_required")
        opening, closing = _aware(raw["open"]).astimezone(NY), _aware(raw["close"]).astimezone(NY)
        if (opening.date() != d or closing.date() != d or opening.time() != time(9, 30)
                or closing <= opening or opening.second or closing.second or opening.microsecond or closing.microsecond
                or closing - opening < timedelta(minutes=30)):
            raise PremarketError("unsupported_calendar_session")
        out[d] = {"open": opening, "close": closing}
    return out


def _row_time(value) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("invalid_bar_time") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(NY)


def _status(raw, dt, observed_at):
    if dt.second or dt.microsecond:
        return {"status": "invalid", "reason": "nonminute_time"}
    if observed_at is not None and dt > observed_at:
        return {"status": "future", "reason": "bar_not_finished_at_capture"}
    blank = raw.get("is_blank")
    if blank in ("true", "True"):
        blank = True
    elif blank in ("false", "False"):
        blank = False
    if type(blank) is not bool:
        return {"status": "invalid", "reason": "blank_flag_unknown"}
    if blank:
        return {"status": "blank", "reason": "provider_blank"}
    try:
        stamp = _decimal(raw.get("timestamp"))
        if abs(float(stamp) - dt.timestamp()) > .001:
            return {"status": "invalid", "reason": "timestamp_timezone_disagreement"}
        o, h, l, c = [_decimal(raw.get(k), positive=True) for k in
                      ("open_price", "high_price", "low_price", "close_price")]
        volume = _decimal(raw.get("volume"))
        if not l <= min(o, c) <= max(o, c) <= h:
            return {"status": "invalid", "reason": "invalid_ohlc"}
    except ValueError:
        return {"status": "invalid", "reason": "invalid_ohlcv_or_timestamp"}
    if volume == 0:
        return {"status": "zero_volume", "reason": "no_verified_trade_in_minute"}
    return {"status": "valid", "open": o, "high": h, "low": l, "close": c, "volume": volume}


def _window(index, ends):
    counts = Counter()
    reasons = Counter()
    valid = []
    for dt in ends:
        row = index.get(dt)
        counts["missing" if row is None else row["status"]] += 1
        if row is not None and row["status"] != "valid":
            reasons[row.get("reason", row["status"])] += 1
        if row is not None and row["status"] == "valid":
            valid.append((dt, row))
    return {"complete": len(valid) == len(ends), "expected_minutes": len(ends),
            "counts": dict(sorted(counts.items())), "reason_counts": dict(sorted(reasons.items()))}, valid


def _endpoints(start: datetime, end: datetime):
    return [start + timedelta(minutes=i) for i in range(1, int((end - start).total_seconds() // 60) + 1)]


def _quantiles(values):
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "mean": None, "median": None, "p75": None, "p90": None, "max": None}
    def q(p):
        pos = (len(ordered) - 1) * p
        low = int(math.floor(pos)); high = int(math.ceil(pos))
        return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)
    return {"n": len(ordered), "mean": mean(ordered), "median": q(.5), "p75": q(.75), "p90": q(.9), "max": ordered[-1]}


def wilson_interval(k: int, n: int) -> dict:
    """95% Wilson reference interval, with no small-sample forecast claim."""
    if type(k) is not int or type(n) is not int or not 0 <= k <= n:
        raise PremarketError("invalid_binomial_counts")
    if n == 0:
        return {"k": 0, "n": 0, "proportion": None, "lower": None, "upper": None}
    z = 1.959963984540054
    phat = k / n; z2 = z * z; denominator = 1 + z2 / n
    centre = (phat + z2 / (2 * n)) / denominator
    radius = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n)) / denominator
    return {"k": k, "n": n, "proportion": phat, "lower": max(0., centre - radius), "upper": min(1., centre + radius)}


def _outcome_stats(days, thresholds):
    drops = [d["outcome"]["max_drop_from_open"] for d in days]
    def hit(day, threshold):
        return _fraction(day["outcome"]["exact_max_drop"]) >= Fraction(threshold)
    return {"n": len(days), "dates": [d["date"] for d in days],
        "drop_distribution": _quantiles(drops),
        "thresholds": [{"drop_threshold": float(t), **wilson_interval(sum(hit(d, t) for d in days), len(drops)),
                        "conditional_drop_distribution": _quantiles([d["outcome"]["max_drop_from_open"] for d in days if hit(d, t)])} for t in thresholds],
        "negative_30m_close": wilson_interval(sum(_fraction(d["outcome"]["exact_return_30m"]) < 0 for d in days), len(days))}


def _summaries(daily, drop_thresholds):
    summaries = {}
    for name in DEFINITIONS:
        eligible = [d for d in daily if d["definitions"][name]["analysis_eligible"]]
        events = [d for d in eligible if d["definitions"][name]["triggered"]]
        known = [d for d in daily if d["definitions"][name]["condition_known"]]
        observed_triggers = [d for d in known if d["definitions"][name]["triggered"]]
        summaries[name] = {"calendar_sessions": len(daily), "condition_known_days": len(known),
            "eligible_days": len(eligible), "observed_trigger_days_before_outcome_quality": len(observed_triggers),
            "triggered_but_outcome_excluded_dates": [d["date"] for d in observed_triggers if not d["definitions"][name]["analysis_eligible"]],
            "incomplete_window_observed_hit_dates": [d["date"] for d in daily if d["definitions"][name]["observed_hit_in_incomplete_window"] is True],
            "events": _outcome_stats(events, drop_thresholds),
            "baseline_same_eligible_days": _outcome_stats(eligible, drop_thresholds),
            "excluded_reason_counts": dict(sorted(Counter(reason for d in daily if not d["definitions"][name]["analysis_eligible"] for reason in d["definitions"][name]["exclusion_reasons"]).items()))}
    return summaries


def _analyze_symbol_base(rows: Iterable[Mapping], *, symbol: str, sessions: Mapping,
                   start, end_exclusive, bar_label: str, observed_at=None,
                   require_full_rth: bool = False, premarket_threshold=.025,
                   thresholds=DEFAULT_THRESHOLDS, corporate_action_dates=()) -> dict:
    """Analyze one symbol using explicit exchange sessions and end-labelled bars.

    Session values are aware ISO/datetime ``open`` and ``close`` fields keyed by
    exchange date. Include at least one preceding session to resolve yesterday's
    close; missing prior data are never skipped backward. Ever-high main results
    require a complete positive-volume minute window, while incomplete observed
    hits are separately flagged. No minutes or symbols are pooled as trials.
    """
    if symbol not in {"QQQ", "SPY", "DIA"}:
        raise PremarketError("symbol_must_be_QQQ_SPY_or_DIA")
    if bar_label not in {"end", "bar-end", "bar_end"}:
        raise PremarketError("explicit_verified_end_label_required")
    if type(require_full_rth) is not bool:
        raise PremarketError("require_full_rth_must_be_bool")
    begin, end = _date(start), _date(end_exclusive)
    if begin >= end:
        raise PremarketError("invalid_research_window")
    threshold = _thresholds([premarket_threshold])[0]
    drop_thresholds = _thresholds(thresholds)
    calendar = _calendar(sessions)
    dates = sorted(calendar)
    studied = [d for d in dates if begin <= d < end]
    if not studied:
        raise PremarketError("no_calendar_sessions_in_research_window")
    prev_map = {d: dates[i - 1] if i else None for i, d in enumerate(dates)}
    required_dates = set(studied) | {prev_map[d] for d in studied if prev_map[d] is not None}
    actions = {_date(d) for d in corporate_action_dates}
    capture = _aware(observed_at).astimezone(NY) if observed_at is not None else None
    index = {d: {} for d in required_dates}
    diagnostics = Counter()
    for n, raw in enumerate(rows, 1):
        if n > MAX_ROWS:
            raise PremarketError("input_row_bound_exceeded")
        diagnostics["rows_scanned"] += 1
        if not isinstance(raw, Mapping):
            diagnostics["unassigned_invalid_rows"] += 1; continue
        found_symbol = str(raw.get("symbol", raw.get("code", symbol))).removeprefix("US.")
        if found_symbol != symbol:
            raise PremarketError("mixed_symbol_rows")
        try:
            dt = _row_time(raw.get("time"))
        except ValueError:
            diagnostics["unassigned_invalid_time_rows"] += 1; continue
        d = dt.date()
        if d not in required_dates:
            diagnostics["outside_required_calendar_dates"] += 1; continue
        if dt <= _local(d, "04:00:00") or dt > calendar[d]["close"]:
            diagnostics["outside_premarket_and_rth"] += 1; continue
        if dt in index[d]:
            diagnostics["duplicate_timestamp_rows"] += 1
            index[d][dt] = {"status": "duplicate", "reason": "duplicate_source_bar"}
            continue
        normalized = _status(raw, dt, capture)
        diagnostics[normalized["status"] + "_rows_in_relevant_windows"] += 1
        index[d][dt] = normalized
    daily = []
    for d in studied:
        day_index = index[d]; cal = calendar[d]; previous = prev_map[d]
        first_ends = _endpoints(cal["open"], cal["open"] + timedelta(minutes=30))
        rth_ends = _endpoints(cal["open"], cal["close"])
        q30, first = _window(day_index, first_ends)
        qrth, _ = _window(day_index, rth_ends)
        prior_row = index.get(previous, {}).get(calendar[previous]["close"]) if previous is not None else None
        previous_valid = prior_row is not None and prior_row["status"] == "valid"
        previous_close = prior_row["close"] if previous_valid else None
        reasons = []
        if not previous_valid: reasons.append("previous_actual_session_close_unavailable")
        if not q30["complete"]: reasons.append("first30_minute_quality_incomplete")
        if require_full_rth and not qrth["complete"]: reasons.append("full_rth_quality_incomplete")
        if d in actions: reasons.append("corporate_action_day_excluded")
        record = {"date": d.isoformat(), "symbol": symbol,
            "previous_session_date": previous.isoformat() if previous is not None else None,
            "previous_rth_close": float(previous_close) if previous_close is not None else None,
            "session_open_et": cal["open"].isoformat(), "session_close_et": cal["close"].isoformat(),
            "quality": {"first30": q30, "full_rth": qrth, "previous_close_valid": previous_valid},
            "base_eligible": not reasons, "exclusion_reasons": reasons, "outcome": None, "definitions": {}}
        if q30["complete"]:
            opening = first[0][1]["open"]
            low_dt, low = min(first, key=lambda pair: pair[1]["low"])
            windows = []
            for count in (1, 5, 10, 15, 30):
                t, lowest = min(first[:count], key=lambda pair: pair[1]["low"])
                windows.append({"minutes": count, "lowest_price": float(lowest["low"]),
                    "low_bar_start_et": (t - timedelta(minutes=1)).isoformat(), "low_bar_end_et": t.isoformat(),
                    "max_drop_from_open": float(max(Decimal(0), 1 - lowest["low"] / opening)),
                    "return_at_window_end": float(first[count - 1][1]["close"] / opening - 1)})
            record["outcome"] = {"open_proxy": float(opening), "low_30m": float(low["low"]),
                "low_bar_start_et": (low_dt - timedelta(minutes=1)).isoformat(), "low_bar_end_et": low_dt.isoformat(),
                "max_drop_from_open": float(max(Decimal(0), 1 - low["low"] / opening)),
                "close_30m": float(first[-1][1]["close"]), "return_30m": float(first[-1][1]["close"] / opening - 1),
                "exact_max_drop": _ratio((Fraction(opening) - Fraction(low["low"])) / Fraction(opening)),
                "exact_return_30m": _return_ratio(first[-1][1]["close"], opening),
                "windows": windows, "gap_already_filled_at_open": bool(opening <= previous_close) if previous_valid else None,
                "gap_filled_after_open": bool(opening > previous_close and low["low"] <= previous_close) if previous_valid else None}
        pre_windows = {
            "fixed_0925": [_local(d, "09:25:00")], "fixed_0929": [_local(d, "09:29:00")],
            "ever_before_0925": _endpoints(_local(d, "04:00:00"), _local(d, "09:25:00")),
            "ever_before_open": _endpoints(_local(d, "04:00:00"), cal["open"])}
        for name, endpoints in pre_windows.items():
            quality, observed = _window(day_index, endpoints)
            highest = max((row["high"] for _, row in observed), default=None)
            price = observed[0][1]["close"] if name.startswith("fixed") and quality["complete"] else highest
            exact_return = _return_ratio(price, previous_close) if price is not None and previous_valid else None
            observed_hit = bool(_fraction(exact_return) > Fraction(threshold)) if exact_return is not None and name.startswith("ever") else None
            known = quality["complete"] and previous_valid and d not in actions
            triggered = bool(_fraction(exact_return) > Fraction(threshold)) if known else None
            dreasons = list(reasons)
            if not quality["complete"]: dreasons.append("premarket_window_quality_incomplete")
            definition = {"condition_known": known, "triggered": triggered,
                "analysis_eligible": known and not reasons,
                "premarket_price_or_high": float(price) if price is not None else None,
                "premarket_return": float(price / previous_close - 1) if price is not None and previous_valid else None,
                "exact_premarket_return": exact_return,
                "quality": quality, "exclusion_reasons": sorted(set(dreasons)),
                "observed_hit_in_incomplete_window": observed_hit if not quality["complete"] else None}
            record["definitions"][name] = definition
        daily.append(record)
    summaries = _summaries(daily, drop_thresholds)
    baseline = [d for d in daily if d["base_eligible"]]
    return {"schema_version": SCHEMA_VERSION, "symbol": symbol, "start": begin.isoformat(), "end_exclusive": end.isoformat(),
        "calendar_sessions": len(studied), "bar_label": "end", "required_first30_minutes": 30,
        "require_full_rth": require_full_rth, "premarket_threshold": float(threshold),
        "premarket_threshold_exact": _threshold_key(threshold),
        "comparison": "strictly_greater_than", "drop_thresholds": [float(x) for x in drop_thresholds],
        "observed_at": _aware(observed_at).isoformat() if observed_at is not None else None,
        "input_diagnostics": dict(sorted(diagnostics.items())), "daily": daily, "summary": summaries,
        "baseline_all_valid_opening_days": _outcome_stats(baseline, drop_thresholds),
        "coverage": {"calendar_sessions": len(daily), "valid_opening_days": len(baseline),
            "first30_complete_days": sum(d["quality"]["first30"]["complete"] for d in daily),
            "full_rth_complete_days": sum(d["quality"]["full_rth"]["complete"] for d in daily),
            "previous_close_valid_days": sum(d["quality"]["previous_close_valid"] for d in daily)},
        "claims": {"descriptive_historical_bar_statistics": True, "point_in_time_delivery_verified": False,
            "forecast_calibration_performed": False, "out_of_sample_strategy_test": False,
            "wilson_assumes_approximately_independent_dates": True, "symbols_pooled": False,
            "corporate_action_dates": sorted(d.isoformat() for d in actions),
            "corporate_actions_independently_reconstructed": False, "execution_eligible": False}}


def analyze_symbol(rows: Iterable[Mapping], *, symbol: str, sessions: Mapping,
                   start, end_exclusive, bar_label: str, observed_at=None,
                   require_full_rth: bool = False, premarket_threshold=.025,
                   thresholds=DEFAULT_THRESHOLDS, corporate_action_dates=()) -> dict:
    """Analyze QQQ, SPY or DIA at one strictly positive premarket threshold.

    Thresholds are fractions: ``.025`` means 2.5%. Exact reduced return ratios
    are sufficient statistics for reproducible threshold selection. Displayed
    floating-point returns must not be used to decide equality at a boundary.
    All supplied-calendar, quality and no-forward-filling rules are unchanged.
    """
    return _analyze_symbol_base(rows, symbol=symbol, sessions=sessions, start=start,
        end_exclusive=end_exclusive, bar_label=bar_label, observed_at=observed_at,
        require_full_rth=require_full_rth, premarket_threshold=premarket_threshold,
        thresholds=thresholds, corporate_action_dates=corporate_action_dates)


def analyze_symbol_thresholds(rows: Iterable[Mapping], *, symbol: str,
                   sessions: Mapping, start, end_exclusive, bar_label: str,
                   premarket_thresholds=DEFAULT_PREMARKET_THRESHOLDS,
                   observed_at=None, require_full_rth: bool = False,
                   thresholds=DEFAULT_THRESHOLDS, corporate_action_dates=()) -> dict:
    """Compare declared thresholds while scanning the minute source only once.

    Returns canonical fractional Decimal keys (e.g. ``"0.025"``), each mapped
    to the same contract as :func:`analyze_symbol`. The grid is exploratory:
    these comparisons do not select a best rule or establish out-of-sample
    predictive value. Each result owns its data, so altering one cannot change
    another. The maximum number of distinct thresholds is ten.
    """
    values = _thresholds(premarket_thresholds)
    drop_thresholds = _thresholds(thresholds)
    base = _analyze_symbol_base(rows, symbol=symbol, sessions=sessions, start=start,
        end_exclusive=end_exclusive, bar_label=bar_label, observed_at=observed_at,
        require_full_rth=require_full_rth, premarket_threshold=values[0],
        thresholds=drop_thresholds, corporate_action_dates=corporate_action_dates)
    results = {}
    for threshold in values:
        result = deepcopy(base)
        result["premarket_threshold"] = float(threshold)
        result["premarket_threshold_exact"] = _threshold_key(threshold)
        for day in result["daily"]:
            for name, definition in day["definitions"].items():
                exact = definition["exact_premarket_return"]
                hit = _fraction(exact) > Fraction(threshold) if exact is not None else None
                definition["triggered"] = bool(hit) if definition["condition_known"] else None
                definition["observed_hit_in_incomplete_window"] = (
                    bool(hit) if name.startswith("ever") and not definition["quality"]["complete"] and hit is not None else None)
        result["summary"] = _summaries(result["daily"], drop_thresholds)
        results[_threshold_key(threshold)] = result
    return results
