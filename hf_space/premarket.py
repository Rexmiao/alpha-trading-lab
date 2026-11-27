"""Frozen public *derived* opening-downside reference, not a broker data feed.

The asset contains dimensionless per-day sufficient statistics. It deliberately
contains no minute OHLCV, absolute security prices, account data or local paths.
All returned returns use fractions (0.01 means 1%); the input cutoff uses percent.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import mean

SYMBOLS = ("QQQ", "SPY", "DIA")
DEFINITIONS = ("fixed_0925", "fixed_0929", "ever_before_0925", "ever_before_open")
WINDOWS = (1, 5, 10, 15, 30)
SCHEMA = "premarket-public-derived/1"
RESULT_SCHEMA = "premarket-public-results/1"
REFERENCE_PATH = Path(__file__).with_name("assets") / "premarket_reference_365.json"
REFERENCE_SHA256 = "1b93af7a00e7c241ca9e2c76a9ae6234475c77c12170ba2d2ca086ed6cee7b60"
MAX_REFERENCE_BYTES = 2_000_000
START, END = "2025-11-27", "2026-11-27"
DROP_THRESHOLDS = (Fraction(1, 200), Fraction(1, 100), Fraction(1, 50))


class PremarketReferenceError(ValueError):
    """The reference or a requested configuration fails its declared contract."""


def _keys(value, keys, code):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PremarketReferenceError(code)


def _boolean(value):
    if type(value) is not bool:
        raise PremarketReferenceError("reference_boolean_required")


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise PremarketReferenceError("reference_numeric_out_of_range")


def _ratio(value):
    _keys(value, ("numerator", "denominator"), "reference_ratio_fields")
    n, d = value["numerator"], value["denominator"]
    if (not isinstance(n, str) or not re.fullmatch(r"-?(?:0|[1-9]\d{0,49})", n)
            or not isinstance(d, str) or not re.fullmatch(r"[1-9]\d{0,49}", d)):
        raise PremarketReferenceError("reference_ratio_integers")
    result = Fraction(int(n), int(d))
    if str(result.numerator) != n or str(result.denominator) != d:
        raise PremarketReferenceError("reference_ratio_not_reduced")
    return result


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise PremarketReferenceError("reference_hash_required")


def parse_threshold_pct(value) -> Decimal:
    """Accept a positive percent through 10, with at most six decimal places."""
    if isinstance(value, bool):
        raise PremarketReferenceError("invalid_threshold_pct")
    try:
        result = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise PremarketReferenceError("invalid_threshold_pct") from None
    if not result.is_finite() or result <= 0 or result > 10 or result.as_tuple().exponent < -6:
        raise PremarketReferenceError("threshold_pct_must_be_positive_up_to_10_with_6_decimals")
    return result


def validate_reference(reference: dict) -> dict:
    """Strict, bounded public schema: unknown fields are never silently accepted."""
    _keys(reference, ("schema_version", "reference_id", "provenance", "symbols"), "reference_root_fields")
    if reference["schema_version"] != SCHEMA or reference["reference_id"] != "moomoo-opening-365-2026-11-27-v1":
        raise PremarketReferenceError("reference_version_mismatch")
    p = reference["provenance"]
    _keys(p, ("source", "start", "end_exclusive", "natural_days", "trading_sessions", "timezone",
              "bar_label", "price_adjustment", "created_at_utc", "report_sha256", "engine_sha256",
              "runner_sha256", "calendar_sha256", "checkpoint_sha256", "source_page_hashes_sha256",
              "source_pages", "source_rows", "raw_minute_data_included", "historical_delivery_clocks_verified",
              "corporate_actions_audited", "publication_profile"), "reference_provenance_fields")
    expected = {"source": "moomoo_desktop_history", "start": START, "end_exclusive": END,
                "natural_days": 365, "trading_sessions": 250, "timezone": "America/New_York",
                "bar_label": "end", "price_adjustment": "raw_unadjusted", "source_pages": 222,
                "source_rows": 1100523, "raw_minute_data_included": False,
                "historical_delivery_clocks_verified": False, "corporate_actions_audited": False,
                "publication_profile": "dimensionless_daily_statistics_only"}
    if any(type(p[k]) is not type(v) or p[k] != v for k, v in expected.items()):
        raise PremarketReferenceError("reference_provenance_scope")
    try:
        timestamp = datetime.fromisoformat(p["created_at_utc"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise PremarketReferenceError("reference_timestamp_required") from None
    for key in ("report_sha256", "engine_sha256", "runner_sha256", "calendar_sha256", "source_page_hashes_sha256"):
        _hash(p[key])
    if not isinstance(p["checkpoint_sha256"], list) or len(p["checkpoint_sha256"]) != 2:
        raise PremarketReferenceError("reference_checkpoint_count")
    for value in p["checkpoint_sha256"]:
        _hash(value)
    _keys(reference["symbols"], SYMBOLS, "reference_symbols")
    expected_dates = None
    for symbol in SYMBOLS:
        days = reference["symbols"][symbol]
        if not isinstance(days, list) or len(days) != 250:
            raise PremarketReferenceError("reference_expected_250_days")
        dates = []
        for day in days:
            _keys(day, ("date", "base_eligible", "first30_complete", "full_rth_complete", "previous_close_valid", "outcome", "definitions"), "reference_day_fields")
            try:
                d = date.fromisoformat(day["date"])
                if d.isoformat() != day["date"] or d.weekday() > 4 or not START <= day["date"] < END:
                    raise ValueError
            except (TypeError, ValueError):
                raise PremarketReferenceError("reference_day_date") from None
            dates.append(day["date"])
            for flag in ("base_eligible", "first30_complete", "full_rth_complete", "previous_close_valid"):
                _boolean(day[flag])
            outcome = day["outcome"]
            if outcome is not None:
                _keys(outcome, ("max_drop_ratio", "return_30m_ratio", "windows"), "reference_outcome_fields")
                drop, ret = _ratio(outcome["max_drop_ratio"]), _ratio(outcome["return_30m_ratio"])
                if not 0 <= drop < 1 or not -1 < ret <= 10:
                    raise PremarketReferenceError("reference_outcome_range")
                if not isinstance(outcome["windows"], list) or len(outcome["windows"]) != len(WINDOWS):
                    raise PremarketReferenceError("reference_windows")
                last_drop = 0.
                for minutes, window in zip(WINDOWS, outcome["windows"]):
                    _keys(window, ("minutes", "max_drop_from_open", "return_at_window_end"), "reference_window_fields")
                    if type(window["minutes"]) is not int or window["minutes"] != minutes:
                        raise PremarketReferenceError("reference_window_minutes")
                    _number(window["max_drop_from_open"], last_drop, 1)
                    _number(window["return_at_window_end"], -1, 10)
                    last_drop = window["max_drop_from_open"]
                if abs(last_drop - float(drop)) > 1e-12 or abs(outcome["windows"][-1]["return_at_window_end"] - float(ret)) > 1e-12:
                    raise PremarketReferenceError("reference_window_30m_mismatch")
            if day["base_eligible"] != bool(day["first30_complete"] and day["previous_close_valid"] and outcome is not None):
                raise PremarketReferenceError("reference_base_eligibility")
            _keys(day["definitions"], DEFINITIONS, "reference_definitions")
            for definition in day["definitions"].values():
                _keys(definition, ("eligible", "condition_known", "window_complete", "return_ratio"), "reference_definition_fields")
                for flag in ("eligible", "condition_known", "window_complete"):
                    _boolean(definition[flag])
                ratio = definition["return_ratio"]
                if ratio is not None and not -1 < _ratio(ratio) <= 10:
                    raise PremarketReferenceError("reference_premarket_return_range")
                known = definition["window_complete"] and day["previous_close_valid"]
                if definition["condition_known"] != known or (known and ratio is None):
                    raise PremarketReferenceError("reference_condition_known")
                if definition["eligible"] != bool(day["base_eligible"] and known):
                    raise PremarketReferenceError("reference_definition_eligibility")
        if dates != sorted(set(dates)) or dates[0] != "2025-11-28" or dates[-1] != "2026-11-25":
            raise PremarketReferenceError("reference_date_order")
        if expected_dates is not None and expected_dates != dates:
            raise PremarketReferenceError("reference_calendar_inconsistent")
        expected_dates = dates
    return reference


def load_reference() -> dict:
    """Read only the bundled frozen derived asset, pinned to its release hash."""
    raw = REFERENCE_PATH.read_bytes()
    if len(raw) > MAX_REFERENCE_BYTES or hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise PremarketReferenceError("reference_file_hash_or_size")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise PremarketReferenceError("reference_json_invalid") from None
    return validate_reference(value)


def _interval(k, n):
    if not n:
        return {"k": k, "n": n, "proportion": None, "lower": None, "upper": None}
    p, z = k / n, 1.959963984540054
    z2 = z * z
    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return {"k": k, "n": n, "proportion": p, "lower": max(0., center - half), "upper": min(1., center + half)}


def _distribution(values):
    values = sorted(values)
    def q(quantile):
        if not values:
            return None
        pos = (len(values) - 1) * quantile
        lo, hi = math.floor(pos), math.ceil(pos)
        return values[lo] + (values[hi] - values[lo]) * (pos - lo)
    return {"n": len(values), "mean": mean(values) if values else None, "median": q(.5), "p75": q(.75), "p90": q(.9), "max": max(values) if values else None}


def _describe(days):
    drops = [_ratio(day["outcome"]["max_drop_ratio"]) for day in days]
    return {"n": len(days), "dates": [d["date"] for d in days], **_distribution([float(x) for x in drops]),
            "thresholds": [{"drop_threshold": float(t), **_interval(sum(x >= t for x in drops), len(days)),
                            "conditional_drop_distribution": _distribution([float(x) for x in drops if x >= t])} for t in DROP_THRESHOLDS],
            "negative_30m_close": _interval(sum(_ratio(d["outcome"]["return_30m_ratio"]) < 0 for d in days), len(days)),
            "windows": [{"minutes": minutes, "n": len(days), **_distribution([d["outcome"]["windows"][i]["max_drop_from_open"] for d in days])} for i, minutes in enumerate(WINDOWS)]}


def analyze_reference(reference: dict, *, threshold_pct="2.5", definition="fixed_0925", symbols=None) -> dict:
    """Re-select a fixed derived reference; never fetch prices or submit orders."""
    cutoff = parse_threshold_pct(threshold_pct)
    if definition not in DEFINITIONS:
        raise PremarketReferenceError("unknown_premarket_definition")
    selected = SYMBOLS if symbols is None else symbols
    if (not isinstance(selected, (list, tuple)) or not selected or any(s not in SYMBOLS for s in selected)
            or len(set(selected)) != len(selected)):
        raise PremarketReferenceError("invalid_selected_symbols")
    validate_reference(reference)
    threshold = Fraction(cutoff) / 100
    results = {}
    for symbol in selected:
        days = reference["symbols"][symbol]
        eligible = [d for d in days if d["definitions"][definition]["eligible"]]
        events = [d for d in eligible if _ratio(d["definitions"][definition]["return_ratio"]) > threshold]
        partial = [d["date"] for d in days if definition.startswith("ever")
                   and not d["definitions"][definition]["window_complete"]
                   and d["definitions"][definition]["return_ratio"] is not None
                   and _ratio(d["definitions"][definition]["return_ratio"]) > threshold]
        results[symbol] = {"events": _describe(events), "baseline_same_eligible_days": _describe(eligible),
            "eligible_days": len(eligible), "total_days": len(days), "partial_observed_hit_dates": partial,
            "status": "no_eligible_days" if not eligible else "no_events" if not events else "available",
            "event_rows": [{"date": d["date"], "premarket_return": float(_ratio(d["definitions"][definition]["return_ratio"])),
                            "max_drop_from_open": float(_ratio(d["outcome"]["max_drop_ratio"])),
                            "return_30m": float(_ratio(d["outcome"]["return_30m_ratio"])),
                            "windows": d["outcome"]["windows"]} for d in events],
            "coverage": {"base_eligible_days": sum(d["base_eligible"] for d in days),
                         "first30_complete_days": sum(d["first30_complete"] for d in days),
                         "full_rth_complete_days": sum(d["full_rth_complete"] for d in days),
                         "previous_close_valid_days": sum(d["previous_close_valid"] for d in days),
                         "condition_known_days": sum(d["definitions"][definition]["condition_known"] for d in days),
                         "complete_premarket_window_days": sum(d["definitions"][definition]["window_complete"] for d in days)}}
    return {"schema_version": RESULT_SCHEMA,
            "config": {"threshold_pct": format(cutoff.normalize(), "f"), "comparison": ">", "definition": definition,
                       "symbols": list(selected), "drop_thresholds": [.005, .01, .02], "execution_eligible": False,
                       "exploratory": True, "opening_window_et": "09:30-10:00"},
            "provenance": dict(reference["provenance"], reference_id=reference["reference_id"], reference_sha256=REFERENCE_SHA256),
            "results": results}
