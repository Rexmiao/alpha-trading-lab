"""Bounded GEX scenario mathematics, with no data source or trading connection.

Every grid point reprices the full supplied chain using European BSM gamma and
fixed per-contract IV (sticky strike). Inventory priors are declared heuristics,
not learned positions. An unsigned concentration curve is not dealer GEX.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path

import numpy as np


MODEL_IDS = ("fixed_call_put", "prior_inventory", "unsigned_concentration", "all_dealer_long", "all_dealer_short")
DTE_BUCKETS = ("0DTE", "1-2", "3-7", "8-30", "31-90", ">90")
MAX_CONTRACTS = 20000
MAX_GRID_POINTS = 401
MAX_GAMMA_CELLS = 4_000_000
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class GEXError(ValueError):
    """Incomplete inputs, unverifiable chain scope, or invalid mathematics."""


def _number(value, name, low=-1e15, high=1e15):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise GEXError(f"{name} must be numeric, not missing or a boolean.")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise GEXError(f"{name} must be finite and in [{low}, {high}].")
    return value


def _bucket(dte):
    return "0DTE" if dte == 0 else "1-2" if dte <= 2 else "3-7" if dte <= 7 else "8-30" if dte <= 30 else "31-90" if dte <= 90 else ">90"


def _contracts(raw, complete_chain_verified):
    if complete_chain_verified is not True:
        raise GEXError("A complete same-snapshot chain must be explicitly verified; no missing contracts are filled.")
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict(orient="records")
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= MAX_CONTRACTS:
        raise GEXError(f"Supply 1..{MAX_CONTRACTS} complete contract records.")
    records, identities, terms, underlyings = [], set(), set(), set()
    for item in raw:
        if not isinstance(item, dict):
            raise GEXError("Each contract must be a record.")
        required = {"underlying", "contract_id", "option_type", "strike", "expiry", "time_to_expiry_years",
                    "iv", "open_interest", "multiplier", "standard_terms_verified", "calendar_dte", "is_0dte"}
        if not required <= item.keys():
            raise GEXError("Contract fields, including OI, multiplier, IV and explicit expiry time, must not be missing.")
        underlying, identity, option_type = item["underlying"], item["contract_id"], item["option_type"]
        if not isinstance(underlying, str) or not underlying.strip() or len(underlying) > 32:
            raise GEXError("A single explicit underlying is required.")
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 160 or identity in identities:
            raise GEXError("Contract IDs must be nonempty and unique.")
        if not isinstance(option_type, str) or option_type not in {"call", "put"} or item["standard_terms_verified"] is not True:
            raise GEXError("Only explicitly verified standard call/put terms are supported; adjusted contracts are refused.")
        if item.get("is_adjusted") is True or item.get("adjusted") is True:
            raise GEXError("Explicitly adjusted contracts are refused even if standard_terms_verified was also asserted.")
        expiry = item["expiry"]
        try:
            if not isinstance(expiry, str) or date.fromisoformat(expiry).isoformat() != expiry:
                raise ValueError
        except ValueError:
            raise GEXError("expiry must be an explicit ISO calendar date.") from None
        dte, zero = item["calendar_dte"], item["is_0dte"]
        if isinstance(dte, (bool, np.bool_)) or not isinstance(dte, (int, np.integer)) or not 0 <= dte <= 10000:
            raise GEXError("calendar_dte must be a nonnegative integer; it is not inferred from fractional pricing T.")
        if type(zero) is not bool or zero != (dte == 0):
            raise GEXError("is_0dte must be explicitly supplied and agree with calendar_dte, independently of pricing T.")
        row = {"underlying": underlying, "contract_id": identity, "option_type": option_type, "expiry": expiry,
               "strike": _number(item["strike"], "strike", 1e-8, 1e9),
               "time_to_expiry_years": _number(item["time_to_expiry_years"], "time_to_expiry_years", 1e-10, 30),
               "iv": _number(item["iv"], "iv", 1e-8, 10),
               "open_interest": _number(item["open_interest"], "open_interest", 0, 1e12),
               "multiplier": _number(item["multiplier"], "multiplier", 1e-8, 1e6),
               "calendar_dte": int(dte), "is_0dte": zero, "bucket": _bucket(dte)}
        if not row["open_interest"].is_integer():
            raise GEXError("Observed open interest must contain whole contracts.")
        key = (underlying, expiry, option_type, row["strike"], row["time_to_expiry_years"])
        if key in terms:
            raise GEXError("Duplicate standard economic contract terms are refused, even with different IDs.")
        identities.add(identity)
        terms.add(key)
        underlyings.add(underlying)
        records.append(row)
    if len(underlyings) != 1:
        raise GEXError("Do not mix different underlyings in one GEX profile.")
    return sorted(records, key=lambda row: row["contract_id"])


def _gamma(spots, rows, rate, dividend_yield, iv_shift, time_shift):
    s = np.asarray(spots, dtype=float)[:, None]
    k = np.asarray([row["strike"] for row in rows])[None, :]
    t = np.asarray([row["time_to_expiry_years"] for row in rows])[None, :] - time_shift
    sigma = np.asarray([row["iv"] for row in rows])[None, :] + iv_shift
    if (t <= 0).any() or (sigma <= 0).any() or (sigma > 10).any():
        raise GEXError("IV shifts must retain positive finite IV and time shifts must remain before every expiry; no floors are inserted.")
    with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
        try:
            scale = sigma * np.sqrt(t)
            d1 = (np.log(s) - np.log(k) + (rate - dividend_yield + .5 * sigma ** 2) * t) / scale
            gamma = np.exp(-dividend_yield * t - .5 * d1 ** 2) / (math.sqrt(2 * math.pi) * s * scale)
        except FloatingPointError:
            raise GEXError("BSM inputs exceeded finite numerical range; no scenario was substituted.") from None
    if not np.isfinite(gamma).all() or (gamma < 0).any():
        raise GEXError("Gamma calculation did not produce finite nonnegative values.")
    return gamma


def _structural_zero(rows, weights, iv_shift, time_shift):
    # Under the declared BSM model, matching K/T/IV gamma functions are
    # identical for calls and puts. Exact coefficient cancellation proves a
    # zero curve; tiny sampled values or Gaussian underflow do not.
    groups = {}
    for row, weight in zip(rows, weights):
        key = (row["strike"], row["time_to_expiry_years"] - time_shift, row["iv"] + iv_shift)
        groups.setdefault(key, []).append(float(weight))
    return all(math.fsum(values) == 0. for values in groups.values())


def _roots(grid, values, gross_values, *, structural_zero=False):
    tolerance = 1e-12
    if structural_zero:
        return {"status": "structural_all_zero", "brackets": [], "grid_zeros": [],
                "zero_everywhere_in_declared_model": True, "root_count_is_exact": False,
                "scope": "BSM gamma coefficients cancel identically; no isolated zero-Gamma flip exists."}
    # Normalize by gross exposure, so a tiny positive tail is not mistaken for
    # cancellation. Zero gross exposure can reflect Gaussian underflow and is
    # an unresolved sample, never an isolated root.
    ratios = [float(value / gross) if gross > 0 else None for value, gross in zip(values, gross_values)]
    zeros = [float(price) for price, ratio in zip(grid, ratios) if ratio is not None and abs(ratio) <= tolerance]
    brackets = [{"lower": float(grid[index]), "upper": float(grid[index + 1])}
                for index in range(len(grid) - 1)
                if ratios[index] is not None and ratios[index + 1] is not None
                and abs(ratios[index]) > tolerance and abs(ratios[index + 1]) > tolerance
                and (ratios[index] < 0) != (ratios[index + 1] < 0)]
    unresolved = sum(ratio is None for ratio in ratios)
    if unresolved == len(grid):
        status = "numerically_unresolved_grid"
    elif len(brackets) + len(zeros) > 1:
        status = "multiple_candidates_on_grid"
    elif brackets:
        status = "crossing_bracket"
    elif zeros:
        status = "near_zero_grid_point"
    else:
        status = "no_root_detected_in_grid"
    return {"status": status, "brackets": brackets, "grid_zeros": zeros,
            "relative_cancellation_tolerance": tolerance, "unresolved_zero_gross_samples": unresolved,
            "zero_everywhere_in_declared_model": False,
            "root_count_is_exact": False,
            "scope": "Grid sign brackets and near-cancellation points only; zero-gross underflow samples are not roots. Off-grid or within-cell roots may be missed; no linear root is exact."}


def _sign(value):
    return "positive" if value > 1e-10 else "negative" if value < -1e-10 else "zero"


def run_gex_scenarios(contracts, *, spot, price_grid, rate=0., dividend_yield=0., iv_shift=0.,
        time_shift_years=0., prior_long_call=.6, prior_long_put=.35, dealer_fraction=.5,
        complete_chain_verified=False, source_kind="observed"):
    """Reprice declared inventory scenarios. No inventory fitting or direction forecast.

    complete_chain_verified is a caller declaration, not an automatic proof of
    market coverage. Calendar DTE/0DTE and fractional pricing time are separate.
    """
    if source_kind not in {"observed", "synthetic_demo"}:
        raise GEXError("source_kind must explicitly distinguish observed inputs from a synthetic_demo.")
    rows = _contracts(contracts, complete_chain_verified)
    spot = _number(spot, "spot", 1e-8, 1e9)
    rate, dividend_yield = _number(rate, "rate", -1, 2), _number(dividend_yield, "dividend_yield", -1, 2)
    iv_shift = _number(iv_shift, "iv_shift", -10, 10)
    time_shift_years = _number(time_shift_years, "time_shift_years", 0, 30)
    p_call, p_put = _number(prior_long_call, "prior_long_call", 0, 1), _number(prior_long_put, "prior_long_put", 0, 1)
    fraction = _number(dealer_fraction, "dealer_fraction", 0, 1)
    if not isinstance(price_grid, (list, tuple, np.ndarray)) or not 2 <= len(price_grid) <= MAX_GRID_POINTS:
        raise GEXError(f"price_grid must contain 2..{MAX_GRID_POINTS} explicit prices.")
    grid = [_number(value, "grid price", 1e-8, 1e9) for value in price_grid]
    if any(right <= left for left, right in zip(grid, grid[1:])):
        raise GEXError("price_grid must be strictly increasing, without duplicates.")
    if len(rows) * (len(grid) + 1) > MAX_GAMMA_CELLS:
        raise GEXError("The complete chain/grid exceeds the bounded computation budget; do not silently truncate it.")
    spots = [*grid, spot]
    gamma = _gamma(spots, rows, rate, dividend_yield, iv_shift, time_shift_years)
    oi = np.asarray([row["open_interest"] for row in rows])
    mult = np.asarray([row["multiplier"] for row in rows])
    calls = np.asarray([row["option_type"] == "call" for row in rows])
    q = {"fixed_call_put": np.where(calls, oi, -oi),
         "prior_inventory": oi * fraction * np.where(calls, 2 * p_call - 1, 2 * p_put - 1),
         "unsigned_concentration": oi, "all_dealer_long": oi, "all_dealer_short": -oi}
    models, expiry, buckets = {}, [], []
    current_unsigned = .01 * spot ** 2 * gamma[-1] * oi * mult
    with np.errstate(over="raise", invalid="raise"):
        try:
            for model in MODEL_IDS:
                per_contract = .01 * np.asarray(spots)[:, None] ** 2 * gamma * q[model] * mult
                values = per_contract.sum(axis=1)
                if not np.isfinite(values).all() or not np.isfinite(per_contract).all():
                    raise FloatingPointError
                models[model] = {"current_gex": float(values[-1]), "current_sign": _sign(values[-1]),
                    "curve": [{"spot": price, "gex": float(value)} for price, value in zip(grid, values[:-1])],
                    "roots": _roots(grid, values[:-1], np.abs(per_contract[:-1]).sum(axis=1),
                                    structural_zero=_structural_zero(rows, q[model] * mult, iv_shift, time_shift_years)),
                    "is_dealer_inventory_estimate": model != "unsigned_concentration",
                    "inventory_is_observed": False, "prior_is_calibrated": False,
                    "stress_extreme_not_probability": model in {"all_dealer_long", "all_dealer_short"}}
                for value in sorted({row["expiry"] for row in rows}):
                    expiry.append({"model": model, "expiry": value,
                                   "gex": float(per_contract[-1, [row["expiry"] == value for row in rows]].sum())})
                for bucket in DTE_BUCKETS:
                    buckets.append({"model": model, "bucket": bucket,
                                    "gex": float(per_contract[-1, [row["bucket"] == bucket for row in rows]].sum())})
        except FloatingPointError:
            raise GEXError("GEX aggregation exceeded finite numerical range.") from None
    peaks = {}
    for side in ("call", "put"):
        totals = {}
        for row, value in zip(rows, current_unsigned):
            if row["option_type"] == side:
                totals[row["strike"]] = totals.get(row["strike"], 0.) + float(value)
        maximum = max(totals.values(), default=0.)
        peaks[side] = [{"strike": strike, "unsigned_gamma_1pct": value} for strike, value in sorted(totals.items())
                       if maximum > 0 and math.isclose(value, maximum, rel_tol=1e-12, abs_tol=0.)]
    envelope = [{"spot": price, "lower": -float(value), "upper": float(value)}
                for price, value in zip(grid, [row["gex"] for row in models["unsigned_concentration"]["curve"]])]
    normalized_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    result = {"status": "success", "source_kind": source_kind, "underlying": rows[0]["underlying"], "spot": spot,
        "models": models, "expiry_contributions": expiry, "dte_contributions": buckets,
        "own_concentration_peaks": peaks, "peak_definition": "Own unsigned OI-times-Gamma concentration peaks, all ties; not vendor Call Wall/Put Wall.",
        "scenario_envelope": envelope,
        "current_sign_robustness": {"base_proxy_models_agree": models["fixed_call_put"]["current_sign"] == models["prior_inventory"]["current_sign"],
            "stress_extremes_are_not_equally_likely": True, "is_confidence_interval": False, "calibrated_probabilities": None},
        "config": {"rate": rate, "dividend_yield": dividend_yield, "iv_shift": iv_shift, "time_shift_years": time_shift_years,
            "prior_long_call": p_call, "prior_long_put": p_put, "dealer_fraction": fraction,
            "complete_chain_verified": True, "iv_rule": "sticky_strike_per_contract", "pricing_model": "European_BSM_approximation",
            "unit": "USD_delta_hedge_notional_per_1pct_spot_move", "dte_buckets": list(DTE_BUCKETS)},
        "lineage": {"engine": "gex_scenarios_v1", "code_sha256": _CODE_SHA256, "input_sha256": normalized_hash,
            "contract_count": len(rows), "grid_count": len(grid), "full_chain_repriced_at_each_grid_point": True,
            "complete_chain_is_caller_assertion": True, "pricing_time_is_explicit_not_inferred_from_dte": True,
            "dte_bucket_scope": "Original supplied snapshot calendar_dte/is_0dte; a pricing-time shift does not infer a new calendar day.",
            "dependencies": {"numpy": np.__version__},
            "point_in_time_audit_performed": False,
            "observed_history_eligibility": "Not audited: completeness/terms declarations do not establish available_at or OI-as-of alignment for historical features.",
            "direction_predictor": False, "orders_submitted": False, "network_access": False,
            "curve_sensitivity": "Explicit parallel IV and forward-time inputs only; no fitted smile, sticky-delta, missing-chain imputation or posterior.",
            "synthetic_fixture_is_market_history": False},
        "warnings": ["Inventory signs are scenarios, not observed dealer holdings or calibrated probabilities.",
            "Unsigned concentration is not signed dealer GEX; extrema are stress scenarios, not equally probable outcomes.",
            "Negative GEX does not predict a negative return: feedback can amplify either direction.",
            "European sticky-strike BSM is an explicit approximation, not a verified American-option valuation.",
            "Grid roots may be multiple, absent, outside the grid or missed within a cell. Near-cancellation points are tolerance-based; tail underflow is unresolved, not a flip.",
            "Scenario envelope is not a confidence interval. Original vendor GEX units and wall definitions are not inferred."]}
    if source_kind == "synthetic_demo":
        result["warnings"].insert(0, "Fictional TOY chain with explicitly assigned expiry times; no observed market or historical performance.")
    # This is a fail-closed check, not conversion of NaN/Infinity into null.
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, OverflowError):
        raise GEXError("The resulting report is not finite JSON.") from None
    return result


def advance_mm_inventory(q, *, mm_buys, mm_sells, classification="actual_mm_classified"):
    """Signed q increases for ALL MM buys, including buy-to-close. No OI clipping.

    Input labels and initial inventory are caller declarations. Aggressor BUY is
    not MM BUY; heuristic fractional flows must be explicitly marked heuristic.
    """
    if classification not in {"actual_mm_classified", "declared_heuristic"}:
        raise GEXError("Flow must be actual MM-classified or explicitly declared heuristic, not anonymous aggressor direction.")
    q = _number(q, "q")
    buys, sells = _number(mm_buys, "mm_buys", 0), _number(mm_sells, "mm_sells", 0)
    if classification == "actual_mm_classified" and (not buys.is_integer() or not sells.is_integer()):
        raise GEXError("Actual classified flow must contain whole contracts; fractional expected flows are heuristic.")
    updated = q + buys - sells
    if not math.isfinite(updated):
        raise GEXError("Inventory update is not finite.")
    return {"q_previous": q, "mm_buys": buys, "mm_sells": sells, "q_next": updated,
            "classification": classification, "probability_calibrated": False, "stale_oi_clipped": False,
            "scope": "Only the declared flow increment is computed; unknown initial inventory, expiry/exercise/adjustments and missing venues remain external audit requirements."}


def make_teaching_gex_contracts():
    """A complete fictional TOY chain: pricing T/DTE are assigned, not today's clock."""
    records = []
    for expiry, dte, t, strikes in (("2029-12-19", 0, .25 / 365, (95., 100., 105.)),
                                   ("2030-01-18", 30, 30 / 365, (90., 100., 110.))):
        for strike in strikes:
            for side in ("call", "put"):
                oi = (600 if side == "put" else 350) if strike == 100 else (400 if side == "call" else 120)
                records.append({"underlying": "TOY", "contract_id": f"TOY-{expiry}-{side}-{strike:g}",
                    "option_type": side, "strike": strike, "expiry": expiry, "time_to_expiry_years": t,
                    "iv": .25, "open_interest": oi, "multiplier": 100,
                    "standard_terms_verified": True, "calendar_dte": dte, "is_0dte": dte == 0})
    return records
