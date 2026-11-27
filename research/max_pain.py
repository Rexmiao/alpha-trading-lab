"""Exact scoped Max Pain and frozen-target research; no feeds/accounts/orders.

All records are caller-supplied. Completeness and authoritative contract terms
are required attestations, not facts this mathematical prototype can discover.
No multiplier, missing OI, or timestamp is inferred from a symbol or a quote.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import hashlib
import json
import re


class MaxPainError(ValueError):
    pass


def _decimal(value, name, *, positive=False):
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, str, Decimal)):
        raise MaxPainError(f"{name} must be explicitly supplied as a finite decimal.")
    try:
        item = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MaxPainError(f"{name} must be a finite decimal.") from None
    if not item.is_finite() or (item <= 0 if positive else item < 0):
        raise MaxPainError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}.")
    # Bound hostile numeric input in a future upload adapter, without rounding.
    if len(item.as_tuple().digits) > 100 or abs(item.as_tuple().exponent) > 100:
        raise MaxPainError(f"{name} exceeds this bounded calculator's numeric limits.")
    return Fraction(item)


def _oi(value):
    if isinstance(value, bool) or value is None:
        raise MaxPainError("Missing/invalid open_interest is not zero.")
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,30}", value):
        return int(value)
    if not isinstance(value, int) or not 0 <= value < 10**30:
        raise MaxPainError("open_interest must be an explicitly observed nonnegative integer count.")
    return value


def _text(value):
    """Exact decimal text for rational arithmetic formed from decimal inputs."""
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 10
        item = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return item.rstrip("0").rstrip(".") if "." in item else item


def _iso_date(value, name):
    if not isinstance(value, str):
        raise MaxPainError(f"{name} must be YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise MaxPainError(f"{name} must be YYYY-MM-DD.") from None
    if parsed.isoformat() != value:
        raise MaxPainError(f"{name} must be YYYY-MM-DD.")
    return value


def _validated(snapshot):
    if not isinstance(snapshot, dict):
        raise MaxPainError("Provide an explicitly scoped single-expiry snapshot dictionary.")
    for flag in ("complete_chain", "pagination_complete", "no_visible_truncation", "terms_scope_verified"):
        if snapshot.get(flag) is not True:
            raise MaxPainError(f"{flag} must be explicitly verified; no partial-chain Max Pain is published.")
    if snapshot.get("rights_coverage") != ["CALL", "PUT"]:
        raise MaxPainError("Both CALL and PUT listing coverage must be audited, including zero-OI contracts.")
    if snapshot.get("common_settlement_reference_verified") is not True:
        raise MaxPainError("A common payoff currency and settlement price reference must be verified, not merely a common expiry date.")
    timestamps = {}
    for field in ("query_time", "retrieved_at", "vendor_updated_at", "available_at", "settlement_at"):
        value = snapshot.get(field)
        if value is None:
            continue
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
            if stamp is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise ValueError
        except (TypeError, ValueError):
            raise MaxPainError(f"{field} must be explicit UTC ISO time or unknown None.") from None
        timestamps[field] = stamp
    if snapshot.get("oi_effective_date") is not None:
        _iso_date(snapshot["oi_effective_date"], "oi_effective_date")
    if snapshot.get("point_in_time_timing_verified") is True:
        if any(snapshot.get(f) is None for f in ("query_time", "retrieved_at", "oi_effective_date", "available_at")):
            raise MaxPainError("point_in_time_timing_verified requires known query/retrieval/OI-effective/available timestamps.")
        if timestamps["query_time"] > timestamps["retrieved_at"]:
            raise MaxPainError("Query cannot occur after retrieval.")
    underlying, expiry = snapshot.get("underlying"), _iso_date(snapshot.get("expiry"), "expiry")
    if not isinstance(underlying, str) or not underlying.strip():
        raise MaxPainError("underlying is required.")
    contracts = snapshot.get("contracts")
    if not isinstance(contracts, list) or len(contracts) > 50_000:
        raise MaxPainError("Provide a bounded list of at most 50000 contracts.")
    expected = snapshot.get("listed_standard_contract_count")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != len(contracts):
        raise MaxPainError("Contract count must reconcile to independently audited listed standard contracts.")
    seen, rows = set(), []
    for contract in contracts:
        if not isinstance(contract, dict):
            raise MaxPainError("Each contract must be a dictionary.")
        identity = contract.get("contract_id")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise MaxPainError("Unique authoritative contract_id values are required; duplicates cannot be added twice.")
        seen.add(identity)
        if contract.get("underlying") != underlying or contract.get("expiry") != expiry:
            raise MaxPainError("Do not mix underlyings or expiries in a Max Pain calculation.")
        if contract.get("option_type") not in {"CALL", "PUT"}:
            raise MaxPainError("option_type must explicitly be CALL or PUT.")
        if contract.get("standard_linear_verified") is not True or contract.get("adjusted") is not False:
            raise MaxPainError("Adjusted, nonstandard, or unverified deliverables are unsupported, never repaired as 100 shares.")
        if contract.get("deliverable_kind") != "standard_linear_underlying":
            raise MaxPainError("Only verified standard linear underlying deliverables are supported.")
        if not isinstance(contract.get("multiplier_source"), str) or not contract["multiplier_source"].strip():
            raise MaxPainError("Authoritative multiplier_source is required; there is no implicit 100 multiplier.")
        if not isinstance(contract.get("terms_source"), str) or not contract["terms_source"].strip():
            raise MaxPainError("Authoritative terms_source is required to verify standard status.")
        strike = _decimal(contract.get("strike"), "strike")
        multiplier = _decimal(contract.get("multiplier"), "multiplier", positive=True)
        rows.append((identity, contract["option_type"], strike, _oi(contract.get("open_interest")), multiplier))
    return rows


def loss_at_price(snapshot, price):
    """Exact L(x) on x>=0; decimal text, never a rounded dollar PnL forecast."""
    rows, x = _validated(snapshot), _decimal(price, "settlement_price")
    loss = sum((oi * multiplier * max(x-strike if right == "CALL" else strike-x, 0)
                for _, right, strike, oi, multiplier in rows), Fraction(0))
    return _text(loss)


def loss_at_prices(snapshot, prices):
    """Exact batch payoffs in original order, including duplicate query prices.

    Returns ``list[Fraction]`` so rational queries such as Fraction(1,3) never
    become rounded decimal payoffs. Existing single-price decimal-text behavior
    is unchanged. Chart callers may convert individual values to float only for
    display. Validation occurs once, then sorted strike/query knots are swept:
    O(N log N + G log G), with no global snapshot cache or stale mutable state.
    Empty queries return [] AFTER the complete snapshot has been validated.
    """
    rows = _validated(snapshot)
    if not isinstance(prices, (list, tuple)) or len(prices) > 100_000:
        raise MaxPainError("prices must be a bounded list/tuple of at most 100000 query prices.")
    queries = []
    for index, price in enumerate(prices):
        if isinstance(price, Fraction):
            if price < 0 or abs(price.numerator) >= 10**200 or price.denominator >= 10**200:
                raise MaxPainError("settlement_price fraction must be nonnegative and within numeric limits.")
            value = price
        else:
            value = _decimal(price, "settlement_price")
        queries.append((value, index))
    if not queries:
        return []
    jumps = defaultdict(Fraction)
    loss, slope = Fraction(0), Fraction(0)
    for _, right, strike, oi, multiplier in rows:
        weight = oi * multiplier
        if not weight:
            continue
        jumps[strike] += weight
        if right == "PUT":
            loss += weight * strike
            slope -= weight
    knots = sorted(jumps)
    ordered = sorted(queries)
    result = [Fraction(0)] * len(queries)
    cursor, previous = 0, Fraction(0)
    for price, original_index in ordered:
        while cursor < len(knots) and knots[cursor] <= price:
            strike = knots[cursor]
            loss += slope * (strike-previous)
            slope += jumps[strike]
            previous, cursor = strike, cursor+1
        result[original_index] = loss + slope * (price-previous)
    return result


def compute_max_pain(snapshot):
    """Exact global minimizer interval of convex L(x), restricted to x>=0.

    Time: O(n log n) sorting, followed by O(n) grouped slope/loss prefix scan.
    An absent upper endpoint means +infinity, not the last displayed strike.
    """
    rows = _validated(snapshot)
    metadata = {key: snapshot.get(key) for key in (
        "source_name", "query_time", "retrieved_at", "vendor_updated_at", "oi_effective_date",
        "available_at", "settlement_kind", "settlement_at", "settlement_reference", "source_snapshot_sha256")}
    report = {"status": "unavailable", "reason": None, "underlying": snapshot["underlying"],
        "expiry": snapshot["expiry"], "domain": {"lower": "0", "upper": None, "upper_unbounded": True},
        "minimizer": None, "minimum_loss": None, "slope_table": [],
        "contract_count": len(rows), "positive_oi_contract_count": sum(oi > 0 for _, _, _, oi, _ in rows),
        "metadata": metadata, "source_kind": snapshot.get("source_kind", "unspecified"),
        "point_in_time_timing_verified": snapshot.get("point_in_time_timing_verified") is True,
        "validation_scope": "Caller-supplied audited attestations; this pure calculator cannot independently prove complete coverage or contract terms.",
        "method": "exact_rational_sorted_weighted_slopes_v1",
        "interpretation": "Fixed-OI theoretical expiry intrinsic payout minimum, not a forecast, dealer inventory estimate, premium PnL, or price attraction claim."}
    if not rows:
        report["reason"] = "no_contracts"
        return report
    if not report["positive_oi_contract_count"]:
        report["reason"] = "all_open_interest_zero_no_meaningful_target"
        return report
    grouped = defaultdict(lambda: [Fraction(0), Fraction(0)])
    put_weight, call_weight, loss = Fraction(0), Fraction(0), Fraction(0)
    for _, right, strike, oi, multiplier in rows:
        weight = oi * multiplier
        if not weight:
            continue
        grouped[strike][right == "PUT"] += weight
        if right == "PUT":
            put_weight += weight
            loss += weight * strike
        else:
            call_weight += weight
    strikes = sorted(grouped)
    slope, previous = -put_weight, Fraction(0)
    loss_zero = loss
    losses = {}
    cumulative = Fraction(0)
    lower = upper = None
    if put_weight == 0:
        lower, upper = Fraction(0), strikes[0]
    for index, strike in enumerate(strikes):
        calls, puts = grouped[strike]
        loss += slope * (strike - previous)
        left = slope
        slope += calls + puts
        losses[strike] = loss
        report["slope_table"].append({"strike": _text(strike), "call_oi_multiplier": _text(calls),
            "put_oi_multiplier": _text(puts), "loss": _text(loss),
            "slope_left": _text(left), "slope_right": _text(slope)})
        cumulative += calls + puts
        if lower is None and cumulative >= put_weight:
            lower = strike
            upper = strike if cumulative > put_weight else strikes[index+1] if index+1 < len(strikes) else None
        previous = strike
    assert lower is not None
    minimum = loss_zero if lower == 0 else losses[lower]
    report.update(status="success", reason=None, minimum_loss=_text(minimum),
        minimizer={"lower": _text(lower), "upper": _text(upper) if upper is not None else None,
                   "lower_inclusive": True, "upper_inclusive": upper is not None,
                   "upper_unbounded": upper is None, "kind": "point" if lower == upper else "interval"},
        total_call_oi_multiplier=_text(call_weight), total_put_oi_multiplier=_text(put_weight))
    return report


def distance_to_frozen_interval(price, lower, upper):
    """Nonnegative price distance to a frozen target set, preserving flat minima."""
    x, lo = _decimal(price, "price"), _decimal(lower, "lower")
    hi = _decimal(upper, "upper") if upper is not None else None
    if hi is not None and hi < lo:
        raise MaxPainError("upper must be at least lower.")
    distance = lo-x if x < lo else x-hi if hi is not None and x > hi else Fraction(0)
    return _text(distance)


def make_hand_snapshot(rows, *, multiplier=100):
    """Clearly fictional unit-test fixture; never a source of market evidence."""
    contracts = [{"contract_id": f"HAND{index}", "underlying": "TOY", "expiry": "2026-12-18",
                  "option_type": right, "strike": strike, "open_interest": oi,
                  "multiplier": multiplier, "multiplier_source": "fictional_hand_case_terms",
                  "terms_source": "fictional_hand_case_terms", "standard_linear_verified": True,
                  "adjusted": False, "deliverable_kind": "standard_linear_underlying"}
                 for index, (right, strike, oi) in enumerate(rows)]
    return {"underlying": "TOY", "expiry": "2026-12-18", "contracts": contracts,
            "complete_chain": True, "pagination_complete": True, "no_visible_truncation": True,
            "terms_scope_verified": True, "listed_standard_contract_count": len(contracts),
            "common_settlement_reference_verified": True,
            "rights_coverage": ["CALL", "PUT"], "source_name": "fictional_hand_cases",
            "source_kind": "synthetic_unit_test_only", "point_in_time_timing_verified": False}


TEACHING_EXAMPLES = ("unique_point", "flat_interval", "max_oi_difference", "calls_halfline", "puts_halfline", "all_zero")


def make_teaching_snapshot(example="flat_interval"):
    """Return explicit fictional TOY terms/OI; no spot input or market data."""
    cases = {
        "unique_point": [("CALL", 90, 1), ("CALL", 100, 1), ("PUT", 100, 1), ("PUT", 110, 1)],
        "flat_interval": [("CALL", 90, 1), ("PUT", 110, 1)],
        "max_oi_difference": [("CALL", 90, 100), ("PUT", 100, 1), ("CALL", 110, 101)],
        "calls_halfline": [("CALL", 90, 1), ("CALL", 110, 2), ("PUT", 100, 0)],
        "puts_halfline": [("PUT", 90, 1), ("PUT", 110, 2), ("CALL", 100, 0)],
        "all_zero": [("CALL", 90, 0), ("PUT", 110, 0)]}
    if example not in cases:
        raise MaxPainError("Unknown fictional teaching example.")
    result = make_hand_snapshot(cases[example], multiplier=100)
    result["source_kind"] = "synthetic_teaching"
    return result


def _timestamp(value, name):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
        if stamp is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError
    except (TypeError, ValueError):
        raise MaxPainError(f"{name} must be explicit UTC ISO time.") from None
    return stamp


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def freeze_target(report, *, origin_price, decision_at):
    """Freeze a successful, time-audited target for later research observations.

    An unverified current calculation remains descriptive and cannot be promoted
    into a historical point-in-time prediction by supplying today's price.
    """
    if not isinstance(report, dict) or report.get("status") != "success" or not report.get("minimizer"):
        raise MaxPainError("Only a successful nonzero-OI target can be frozen.")
    if report.get("point_in_time_timing_verified") is not True:
        raise MaxPainError("Unknown point-in-time availability cannot originate a predictive target.")
    decision = _timestamp(decision_at, "decision_at")
    known = _timestamp(report.get("metadata", {}).get("available_at"), "snapshot available_at")
    if known > decision:
        raise MaxPainError("Target snapshot was not available at decision_at.")
    price = _decimal(origin_price, "origin_price", positive=True)
    interval = dict(report["minimizer"])
    target = {"underlying": report["underlying"], "expiry": report["expiry"],
        "decision_at": decision.isoformat().replace("+00:00", "Z"),
        "snapshot_available_at": known.isoformat().replace("+00:00", "Z"),
        "origin_price": _text(price), "minimizer": interval,
        "initial_distance": distance_to_frozen_interval(_text(price), interval["lower"], interval["upper"]),
        "source_kind": report.get("source_kind"),
        "source_snapshot_sha256": report.get("metadata", {}).get("source_snapshot_sha256"),
        "scope": "frozen_original_interval_not_updated_by_later_OI"}
    target["target_id"] = _fingerprint(target)
    return target


def evaluate_frozen_target(target, observations, *, evaluation_as_of):
    """Measure later CLOSE observations against the SAME frozen target.

    Not-yet-available and nonfuture observations are excluded with reasons. No
    intrabar touch, settlement identity, independent-sample inference or trading
    performance is inferred from a list of prices.
    """
    if not isinstance(target, dict) or target.get("target_id") != _fingerprint({k: v for k, v in target.items() if k != "target_id"}):
        raise MaxPainError("Frozen target fingerprint mismatch.")
    if not isinstance(observations, list) or len(observations) > 100_000:
        raise MaxPainError("Provide a bounded list of at most 100000 future observations.")
    cutoff = _timestamp(evaluation_as_of, "evaluation_as_of")
    decision = _timestamp(target["decision_at"], "decision_at")
    if cutoff < decision:
        raise MaxPainError("evaluation_as_of cannot precede decision_at.")
    interval = target["minimizer"]
    initial = _decimal(target["initial_distance"], "initial_distance")
    origin = _decimal(target["origin_price"], "origin_price", positive=True)
    accepted, excluded, seen = [], [], set()
    for row in observations:
        if not isinstance(row, dict):
            raise MaxPainError("Each observation must explicitly name observed_at, available_at and price.")
        observed = _timestamp(row.get("observed_at"), "observation observed_at")
        available = _timestamp(row.get("available_at"), "observation available_at")
        price = _decimal(row.get("price"), "observation price", positive=True)
        if observed in seen:
            raise MaxPainError("Duplicate observation time; revisions require a separately frozen dataset version.")
        seen.add(observed)
        if available < observed:
            raise MaxPainError("An observation cannot be available before its price observation time.")
        reason = "not_after_decision" if observed <= decision else "not_available_at_evaluation" if available > cutoff else None
        if reason:
            excluded.append({"observed_at": row["observed_at"], "available_at": row["available_at"], "reason": reason})
            continue
        distance = _decimal(distance_to_frozen_interval(_text(price), interval["lower"], interval["upper"]), "distance")
        accepted.append({"observed_at": row["observed_at"], "available_at": row["available_at"],
            "price": _text(price), "distance": _text(distance), "distance_change_from_origin": _text(distance-initial),
            "distance_over_origin_price": float(distance / origin), "inside_frozen_interval": distance == 0})
    accepted.sort(key=lambda row: _timestamp(row["observed_at"], "observed_at"))
    return {"target_id": target["target_id"], "underlying": target["underlying"], "expiry": target["expiry"],
        "status": "success" if accepted else "no_available_future_observations", "source_kind": target["source_kind"],
        "evaluation_as_of": cutoff.isoformat().replace("+00:00", "Z"), "minimizer": dict(interval),
        "initial_distance": target["initial_distance"], "started_inside": initial == 0,
        "observations": accepted, "excluded": excluded,
        "first_close_inside_at": next((r["observed_at"] for r in accepted if r["inside_frozen_interval"]), None),
        "scope": "descriptive_future_close_distance_not_bar_touch_or_settlement_or_trade_return"}


def target_migration(previous_report, updated_report):
    """Report interval movement separately; never average expiries or outcomes."""
    for report in (previous_report, updated_report):
        if not isinstance(report, dict) or report.get("status") != "success":
            raise MaxPainError("Migration requires two successful descriptive calculations.")
    if any(previous_report.get(key) != updated_report.get(key) for key in ("underlying", "expiry")):
        raise MaxPainError("Target migration cannot mix underlyings or expiries.")
    old, new = previous_report["minimizer"], updated_report["minimizer"]
    return {"underlying": previous_report["underlying"], "expiry": previous_report["expiry"],
        "previous_interval": dict(old), "updated_interval": dict(new),
        "lower_change": _text(_decimal(new["lower"], "new lower") - _decimal(old["lower"], "old lower")),
        "upper_change": _text(_decimal(new["upper"], "new upper") - _decimal(old["upper"], "old upper"))
            if new["upper"] is not None and old["upper"] is not None else None,
        "scope": "interval_migration_only_not_price_convergence_or_predictive_evidence"}
