"""Bounded, local-only audit of Cboe's public capacity-labelled examples.

The free TBT file samples *participant sides*.  A signed sum of those observed
sides is not the full interval's inventory change and is never an inventory
stock.  This module does not download, publish, train, or connect to a broker.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


class CboeSampleError(ValueError):
    """Safe validation failure; messages do not echo raw records or paths."""


TBT_SAMPLE_SHA256 = "6c99e69e43d259e81bc31334574579cf9c623f5e77ff596cacf268712cd3262c"
OPEN_CLOSE_SAMPLE_SHA256 = "445cd9d658dc06028c286e09d4ac4818bd5884d7da8addd7509f3a0fa4840552"
SCHEMA_VERSION = "cboe-public-sample-audit-v1"
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 96 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 32
DEFAULT_MAX_ROWS = 200_000
MAX_CONTRACT_ROWS = 2_000
_SYMBOL = re.compile(r"[A-Za-z0-9^][A-Za-z0-9._^/-]{0,31}\Z")
_CAPACITIES = {"MarketMaker", "Customer", "ProCustomer", "Firm", "BrokerDealer"}
_TBT_REQUIRED = {
    "transact_time", "trading_dt", "underlying", "osi_root", "expire_date",
    "call_put_flag", "strike_price", "size", "price", "side", "capacity",
    "open_close", "exec_id", "complex_exec_id", "session",
}
_OPEN_CLOSE_REQUIRED = {
    "option_symbol", "expiration_date", "strike_price", "mm_buy_qty",
    "mm_buy_vol", "mm_sell_qty", "mm_sell_vol",
}


def _number(value, *, integer=False, positive=False) -> Decimal:
    if isinstance(value, bool):
        raise CboeSampleError("invalid_numeric_field")
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise CboeSampleError("invalid_numeric_field") from None
    if not d.is_finite() or d < 0 or (positive and d == 0):
        raise CboeSampleError("invalid_numeric_field")
    if integer and d != d.to_integral_value():
        raise CboeSampleError("noninteger_contract_quantity")
    if d > Decimal("1e15"):
        raise CboeSampleError("numeric_bound_exceeded")
    if len(d.as_tuple().digits) > 64 or d.as_tuple().exponent < -100:
        raise CboeSampleError("numeric_precision_bound_exceeded")
    return d


def _signed_number(value) -> Decimal:
    if isinstance(value, bool):
        raise CboeSampleError("invalid_numeric_field")
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise CboeSampleError("invalid_numeric_field") from None
    if not d.is_finite() or abs(d) > Decimal("1e15"):
        raise CboeSampleError("invalid_numeric_field")
    if len(d.as_tuple().digits) > 64 or d.as_tuple().exponent < -100:
        raise CboeSampleError("numeric_precision_bound_exceeded")
    return d


def _decimal_text(value: Decimal) -> str:
    # Decimal.normalize() obeys context precision and can merge distinct
    # >28-digit strikes. Formatting the original value does not round it.
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _date(value) -> str:
    text = str(value).strip()
    try:
        d = datetime.strptime(text, "%Y%m%d").date() if re.fullmatch(r"\d{8}", text) else date.fromisoformat(text)
    except (ValueError, TypeError):
        raise CboeSampleError("invalid_date") from None
    return d.isoformat()


def _local_datetime(value) -> datetime:
    text = str(value).strip()
    if not re.fullmatch(r"(?:\d{8} |\d{4}-\d{2}-\d{2}[ T])\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", text):
        raise CboeSampleError("invalid_source_timestamp")
    try:
        d = datetime.strptime(text, "%Y%m%d %H:%M:%S") if re.match(r"^\d{8} ", text) else datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise CboeSampleError("invalid_source_timestamp") from None
    if d.tzinfo is not None:
        raise CboeSampleError("unexpected_source_timestamp_timezone")
    return d


def _received(value) -> str | None:
    if value is None:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise CboeSampleError("invalid_received_at") from None
    if d.tzinfo is None:
        raise CboeSampleError("received_at_requires_timezone")
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value, *, symbol=False) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or any(ord(c) < 32 for c in text):
        raise CboeSampleError("invalid_identity_field")
    if symbol and not _SYMBOL.fullmatch(text):
        raise CboeSampleError("invalid_symbol")
    return text


def contract_key(root, expiry, call_put, strike, *, venue="C1") -> str:
    """Exact source series key; deliverable/multiplier remain unverified.

    The option root is preserved (SPY != 1SPY); this is deliberately not a
    claim that adjusted deliverables have been identified.
    """
    root = _text(root, symbol=True)
    venue = _text(venue, symbol=True)
    cp = str(call_put).strip().upper()
    if cp not in {"C", "P"}:
        raise CboeSampleError("invalid_call_put")
    return "|".join((venue, root, _date(expiry), cp, _decimal_text(_number(strike, positive=True))))


def observed_mm_change(buy_contracts, sell_contracts) -> int:
    """MM buys increase long-minus-short, including buys to close shorts."""
    return int(_number(buy_contracts, integer=True) - _number(sell_contracts, integer=True))


def gex_change_from_inventory_change(delta_q, *, spot, multiplier, gamma) -> dict:
    """Declared-input arithmetic for a *change*, never a stock GEX estimate.

    The caller must separately establish matching contract/time/units.  This
    helper supplies no historical Greeks and does not assert that match.
    """
    dq = _signed_number(delta_q)
    s = _number(spot, positive=True)
    m = _number(multiplier, positive=True)
    g = _number(gamma)
    value = Decimal("0.01") * s * s * dq * m * g
    return {
        "declared_delta_q": _decimal_text(dq),
        "gex_change_1pct": float(value),
        "unit": "USD_delta_hedge_notional_per_1pct_spot_move",
        "quantity_kind": "inventory_change_not_stock",
        "contemporaneous_inputs_verified": False,
        "inventory_q": None,
        "net_inventory_gex": None,
        "execution_eligible": False,
    }


def _empty_flow() -> dict:
    return {"side_records": 0, "mm_buy_contracts": 0, "mm_sell_contracts": 0,
            "mm_unknown_side_contracts": 0, "unknown_capacity_contracts": 0}


def _flow_record(flow, *, size, side, capacity):
    flow["side_records"] += 1
    if capacity == "MarketMaker":
        key = {"B": "mm_buy_contracts", "S": "mm_sell_contracts"}.get(side, "mm_unknown_side_contracts")
        flow[key] += size
    elif capacity not in _CAPACITIES:
        flow["unknown_capacity_contracts"] += size


def _finish_flow(flow) -> dict:
    return {**flow, "sampled_observed_mm_signed_contracts":
            flow["mm_buy_contracts"] - flow["mm_sell_contracts"],
            "full_interval_delta_q": None, "inventory_q": None}


def _limits(max_rows, max_contract_rows):
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= DEFAULT_MAX_ROWS:
        raise CboeSampleError("invalid_row_limit")
    if isinstance(max_contract_rows, bool) or not isinstance(max_contract_rows, int) or not 0 <= max_contract_rows <= MAX_CONTRACT_ROWS:
        raise CboeSampleError("invalid_summary_limit")


def _underlying_filter(values):
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise CboeSampleError("invalid_underlying_filter")
    wanted = {_text(x, symbol=True) for x in values}
    if not 1 <= len(wanted) <= 20:
        raise CboeSampleError("invalid_underlying_filter")
    return wanted


def audit_tbt_rows(rows: Iterable[Mapping], *, source_id="in_memory_declared_input",
                   raw_sha256=None, received_at=None, underlyings=None,
                   max_rows=DEFAULT_MAX_ROWS, max_contract_rows=500) -> dict:
    """Aggregate declared TBT side rows; do not return a raw trade table.

    ``raw_sha256`` is lineage supplied by the caller, not source authentication.
    Official ZIP loader additionally verifies its expected known download hash.
    """
    _limits(max_rows, max_contract_rows)
    received_at = _received(received_at)
    wanted = _underlying_filter(underlyings)
    source_id = _text(source_id)
    count, selected, option_count, quarantined = 0, 0, 0, 0
    capacity_counts, side_counts, underlying_counts = Counter(), Counter(), Counter()
    option_capacity_counts, quarantine_capacities, option_underlying_counts = Counter(), Counter(), Counter()
    totals = _empty_flow()
    by_cp, contracts, buckets, groups = {}, {}, {}, {}
    dates, times, complex_groups, exact_rows = set(), [], set(), set()
    quote_counts, quote_quantity = Counter(), Counter()
    open_close_missing = mm_open_close_missing = complex_rows = 0
    for count, row in enumerate(rows, 1):
        if count > max_rows:
            raise CboeSampleError("row_bound_exceeded")
        if not isinstance(row, Mapping) or not _TBT_REQUIRED.issubset(row) or None in row:
            raise CboeSampleError("invalid_tbt_schema")
        underlying = _text(row["underlying"], symbol=True)
        if wanted is not None and underlying not in wanted:
            continue
        signature = tuple(sorted((str(k), str(v)) for k, v in row.items()))
        if signature in exact_rows:
            raise CboeSampleError("exact_duplicate_tbt_side_record")
        exact_rows.add(signature)
        selected += 1
        trading_date = _date(row["trading_dt"])
        timestamp = _local_datetime(row["transact_time"])
        size = int(_number(row["size"], integer=True, positive=True))
        price = _number(row["price"])
        side = str(row["side"] or "").strip()
        capacity = str(row["capacity"] or "").strip()
        capacity = capacity if capacity in _CAPACITIES else "UNKNOWN"
        execution = _text(row["exec_id"])
        session = _text(row["session"])
        complex_id = str(row["complex_exec_id"] or "").strip()
        if len(complex_id) > 128 or any(ord(c) < 32 for c in complex_id):
            raise CboeSampleError("invalid_complex_identity")
        dates.add(trading_date)
        times.append(timestamp.isoformat(sep=" "))
        capacity_counts[capacity] += 1
        side_counts[side if side in {"B", "S"} else "UNKNOWN"] += 1
        underlying_counts[underlying] += 1
        oc_missing = not str(row["open_close"] or "").strip()
        open_close_missing += oc_missing
        mm_open_close_missing += oc_missing and capacity == "MarketMaker"
        if complex_id:
            complex_rows += 1
            complex_groups.add((trading_date, complex_id))
        cp = str(row["call_put_flag"] or "").strip().upper()
        if cp not in {"C", "P"}:
            # The official sample includes blank-root/blank-right/zero-strike
            # apparent stock legs, including all its unexplained side=T rows.
            # Their quantity units are not verified option contracts.
            quarantined += 1
            quarantine_capacities[capacity] += 1
            continue
        key = contract_key(row["osi_root"], row["expire_date"], cp, row["strike_price"])
        root, expiry, cp, strike = key.split("|")[1:]
        option_count += 1
        option_capacity_counts[capacity] += 1
        option_underlying_counts[underlying] += 1
        if capacity == "MarketMaker":
            position = "invalid_nbbo"
            try:
                bid = _number(row.get("nbbo_bid"), positive=True)
                ask = _number(row.get("nbbo_ask"), positive=True)
                if bid < ask:
                    position = "at_or_below_bid" if price <= bid else "at_or_above_ask" if price >= ask else "inside"
            except CboeSampleError:
                pass
            qkey = (side if side in {"B", "S"} else "UNKNOWN") + "_" + position
            quote_counts[qkey] += 1
            quote_quantity[qkey] += size
        groupkey = (trading_date, key, execution)
        if groupkey not in groups:
            groups[groupkey] = {"rows": 0, "B": 0, "S": 0, "B_records": 0, "S_records": 0, "mm_B": 0, "mm_S": 0,
                                "unknown_capacity": False, "unknown_side": False}
        group = groups[groupkey]
        group["rows"] += 1
        if side in {"B", "S"}:
            group[side] += size
            group[side + "_records"] += 1
            if capacity == "MarketMaker":
                group["mm_" + side] += size
        else:
            group["unknown_side"] = True
        group["unknown_capacity"] |= capacity == "UNKNOWN"
        cpkey = (underlying, cp)
        contract_meta = {"contract_key": key, "underlying": underlying, "option_root": root,
                         "expiry": expiry, "call_put": cp, "strike_decimal": strike,
                         "venue": "C1", "multiplier": None, "deliverable": None,
                         "terms_verified": False}
        if key in contracts and contracts[key]["underlying"] != underlying:
            raise CboeSampleError("inconsistent_underlying_mapping")
        if key not in contracts:
            contracts[key] = {**contract_meta, **_empty_flow()}
        bucket = timestamp.replace(minute=(timestamp.minute // 5) * 5, second=0, microsecond=0).isoformat(sep=" ")
        bucketkey = (trading_date, underlying, cp, session, bucket)
        for target in (totals, by_cp.setdefault(cpkey, _empty_flow()), contracts[key], buckets.setdefault(bucketkey, _empty_flow())):
            _flow_record(target, size=size, side=side, capacity=capacity)
    group_counts = Counter()
    both_mm_cancelled = 0
    classes = Counter()
    for group in groups.values():
        group_counts["single_record_groups"] += group["rows"] == 1
        both = group["B"] > 0 and group["S"] > 0
        group_counts["both_B_S_groups"] += both
        group_counts["missing_B_or_S_groups"] += not both
        balanced = both and group["B"] == group["S"] and not group["unknown_side"]
        group_counts["balanced_B_S_groups"] += balanced
        group_counts["unbalanced_B_S_groups"] += both and not balanced
        complete_pair = balanced and group["rows"] == 2 and group["B_records"] == group["S_records"] == 1
        if complete_pair and not group["unknown_capacity"]:
            buy_mm, sell_mm = group["mm_B"] > 0, group["mm_S"] > 0
            label = "both" if buy_mm and sell_mm else "buyer_only" if buy_mm else "seller_only" if sell_mm else "neither"
            classes[label] += 1
            if group["mm_B"] == group["B"] and group["mm_S"] == group["S"]:
                both_mm_cancelled += 1
        else:
            classes["counterparty_or_quantity_unknown"] += 1
    contract_rows = [_finish_flow(x) for x in contracts.values()]
    contract_rows.sort(key=lambda x: (-x["side_records"], x["contract_key"]))
    return {
        "schema_version": SCHEMA_VERSION, "source_kind": "cboe_tbt_partial_side_sample",
        "source_id": source_id, "raw_sha256": raw_sha256,
        "source_schema": "Cboe public 2025-03-28 TBT sample; bundled v1.0",
        "venue_scope": ["C1"], "capacity_provenance": "exchange_reported_in_declared_input",
        "received_at": received_at, "available_at": received_at,
        "historical_first_available_at": None, "source_timezone": None,
        "source_timezone_assumption": "America/New_York not independently verified for event fields",
        "source_time_converted_to_utc": False,
        "trading_dates": sorted(dates), "source_event_min": min(times) if times else None,
        "source_event_max": max(times) if times else None,
        "rows_scanned": count, "side_records": selected,
        "option_side_records": option_count, "quarantined_instrument_side_records": quarantined,
        "option_capacity_counts": dict(sorted(option_capacity_counts.items())),
        "quarantined_capacity_counts": dict(sorted(quarantine_capacities.items())),
        "option_underlying_side_records": dict(sorted(option_underlying_counts.items())),
        "capacity_counts": dict(sorted(capacity_counts.items())), "side_counts": dict(sorted(side_counts.items())),
        "underlying_side_records": dict(sorted(underlying_counts.items())),
        "open_close_missing_records": open_close_missing,
        "mm_open_close_missing_records": mm_open_close_missing,
        "complex_side_records": complex_rows, "observed_complex_id_groups": len(complex_groups),
        "execution_groups": len(groups), "group_counts": dict(group_counts),
        "execution_group_scope": "C/P option rows only; quarantined instruments excluded",
        "observed_balanced_group_mm_presence_classes": dict(classes),
        "four_class_labels_require_exactly_one_row_per_side": True,
        "balanced_all_MM_groups_net_cancelled": both_mm_cancelled,
        "observed_totals": _finish_flow(totals),
        "mm_quote_position_side_records": dict(sorted(quote_counts.items())),
        "mm_quote_position_contracts": dict(sorted(quote_quantity.items())),
        "quote_position_is_aggressor_truth": False,
        "quote_position_includes_complex_legs": True,
        "quote_event_time_causality_independently_verified": False,
        "correction_handling_verified": False,
        "underlying_call_put": [{"underlying": u, "call_put": cp, **_finish_flow(flow)} for (u, cp), flow in sorted(by_cp.items())],
        "contract_count": len(contracts), "contract_summaries": contract_rows[:max_contract_rows],
        "contract_summaries_truncated": len(contract_rows) > max_contract_rows,
        "time_buckets": [{"trading_date": d, "underlying": u, "call_put": cp,
                          "session": s, "bucket_start_source_local": b, **_finish_flow(flow)}
                         for (d, u, cp, s, b), flow in sorted(buckets.items())],
        "identification_status": "SAMPLED_CAPACITY_ONLY", "inventory_q": None,
        "full_interval_delta_q": None, "net_inventory_gex": None,
        "sampling_mechanism_verified": False, "sampling_expansion_applied": False,
        "counterparty_missing_means_non_MM": False, "calibrated_mm_probabilities": None,
        "independent_oos_dates": 0, "execution_eligible": False,
        "public_distribution_rights_verified": False,
        "limitations": ["participant_side_sample_not_complete_executions", "unknown_initial_inventory",
                        "single_venue_not_full_market", "missing_sides_not_non_MM",
                        "unsupported_instruments_quarantined_not_assumed_contract_units",
                        "no_historical_Greeks_join", "no_accuracy_or_calibration_claim"],
    }


def _csv_bytes_from_zip(data: bytes, *, marker: str, depth=0) -> tuple[bytes, list[str]]:
    if depth > 2:
        raise CboeSampleError("archive_nesting_exceeded")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise CboeSampleError("invalid_zip") from None
    with z:
        members = z.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise CboeSampleError("archive_member_bound_exceeded")
        candidates = []
        for info in members:
            p = PurePosixPath(info.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or ":" in info.filename:
                raise CboeSampleError("unsafe_archive_member")
            if info.flag_bits & 1 or info.file_size > MAX_MEMBER_BYTES:
                raise CboeSampleError("archive_member_bound_exceeded")
            if not info.is_dir() and marker.lower() in info.filename.lower() and info.filename.lower().endswith((".csv", ".zip")):
                candidates.append(info)
        csv_candidates = [i for i in candidates if i.filename.lower().endswith(".csv")]
        chosen = csv_candidates if csv_candidates else [i for i in candidates if i.filename.lower().endswith(".zip")]
        if len(chosen) != 1:
            raise CboeSampleError("ambiguous_or_missing_csv_member")
        info = chosen[0]
        try:
            payload = z.read(info)
        except (zipfile.BadZipFile, RuntimeError, OSError):
            raise CboeSampleError("invalid_zip_member") from None
        if len(payload) != info.file_size or len(payload) > MAX_MEMBER_BYTES:
            raise CboeSampleError("archive_member_bound_exceeded")
        name = PurePosixPath(info.filename).name
        if name.lower().endswith(".csv"):
            return payload, [name]
        inner, names = _csv_bytes_from_zip(payload, marker=marker, depth=depth + 1)
        return inner, [name, *names]


def _load_csv(path, *, marker, expected_sha256) -> tuple[csv.DictReader, dict]:
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_INPUT_BYTES:
        raise CboeSampleError("input_missing_or_bound_exceeded")
    with p.open("rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise CboeSampleError("input_bound_exceeded")
    digest = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256)) or digest != expected_sha256:
        raise CboeSampleError("source_sha256_mismatch")
    payload, members = _csv_bytes_from_zip(data, marker=marker)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CboeSampleError("invalid_csv_encoding") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or len(reader.fieldnames) > 128 or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise CboeSampleError("invalid_csv_header")
    return reader, {"raw_sha256": digest, "csv_sha256": hashlib.sha256(payload).hexdigest(),
                    "source_archive_member_names": members, "expected_download_hash_matched": True}


def audit_tbt_sample(path, *, underlyings=None, received_at=None,
                     max_rows=DEFAULT_MAX_ROWS, max_contract_rows=500,
                     expected_sha256=TBT_SAMPLE_SHA256) -> dict:
    reader, lineage = _load_csv(path, marker="TBT", expected_sha256=expected_sha256)
    result = audit_tbt_rows(reader, source_id="Cboe DataShop sample/289", received_at=received_at,
                            underlyings=underlyings, max_rows=max_rows, max_contract_rows=max_contract_rows,
                            raw_sha256=lineage["raw_sha256"])
    result["lineage"] = lineage
    return result


def audit_open_close_rows(rows: Iterable[Mapping], *, kind="eod", source_id="in_memory_declared_input",
                         raw_sha256=None, received_at=None, underlyings=None,
                         max_rows=DEFAULT_MAX_ROWS, max_contract_rows=500) -> dict:
    """Audit sample snapshot totals; never difference unmatched sample files."""
    _limits(max_rows, max_contract_rows)
    if kind not in {"eod", "10m", "1m"}:
        raise CboeSampleError("invalid_open_close_kind")
    wanted = _underlying_filter(underlyings)
    count = selected = 0
    dates, timestamps, seen = set(), set(), set()
    summaries, by_cp = [], {}
    buy = sell = buy_trades = sell_trades = 0
    for count, row in enumerate(rows, 1):
        if count > max_rows:
            raise CboeSampleError("row_bound_exceeded")
        if not isinstance(row, Mapping) or not _OPEN_CLOSE_REQUIRED.issubset(row) or None in row:
            raise CboeSampleError("invalid_open_close_schema")
        ufield = "underlying_symbol" if kind == "eod" else "underlying"
        cpfield = "call_put_flag" if kind == "eod" else "call_or_put"
        tfield = "quote_date" if kind == "eod" else "trade_datetime"
        if not {ufield, cpfield, tfield}.issubset(row):
            raise CboeSampleError("invalid_open_close_schema")
        underlying = _text(row[ufield], symbol=True)
        if wanted is not None and underlying not in wanted:
            continue
        key = contract_key(row["option_symbol"], row["expiration_date"], row[cpfield], row["strike_price"])
        stamp = _date(row[tfield]) if kind == "eod" else _local_datetime(row[tfield]).isoformat(sep=" ")
        if (stamp, key) in seen:
            raise CboeSampleError("duplicate_open_close_series_snapshot")
        seen.add((stamp, key))
        dates.add(stamp[:10])
        timestamps.add(stamp)
        selected += 1
        bv, sv, bq, sq = [int(_number(row[x], integer=True)) for x in ("mm_buy_vol", "mm_sell_vol", "mm_buy_qty", "mm_sell_qty")]
        buy += bv
        sell += sv
        buy_trades += bq
        sell_trades += sq
        cp = key.split("|")[3]
        cpflow = by_cp.setdefault((underlying, cp), {"series_snapshot_rows": 0, "mm_buy_contracts": 0, "mm_sell_contracts": 0})
        cpflow["series_snapshot_rows"] += 1
        cpflow["mm_buy_contracts"] += bv
        cpflow["mm_sell_contracts"] += sv
        summaries.append({"contract_key": key, "underlying": underlying, "snapshot_source_local": stamp,
                          "mm_buy_contracts": bv, "mm_sell_contracts": sv,
                          "sampled_observed_mm_signed_contracts": bv - sv,
                          "mm_buy_trade_count": bq, "mm_sell_trade_count": sq,
                          "inventory_q": None, "multiplier": None, "terms_verified": False})
    if len(timestamps) > 1:
        raise CboeSampleError("one_snapshot_only_do_not_sum_cumulative_files")
    summaries.sort(key=lambda x: (-(x["mm_buy_contracts"] + x["mm_sell_contracts"]), x["contract_key"]))
    received_at = _received(received_at)
    return {
        "schema_version": SCHEMA_VERSION, "source_kind": "cboe_open_close_partial_sample",
        "source_id": _text(source_id), "raw_sha256": raw_sha256, "snapshot_kind": kind,
        "venue_scope": ["C1"], "source_timezone": None,
        "source_timezone_assumption": "America/New_York not independently verified for event fields",
        "received_at": received_at, "available_at": received_at,
        "historical_first_available_at": None, "trading_dates": sorted(dates),
        "snapshot_source_local": next(iter(timestamps), None),
        "rows_scanned": count, "series_snapshot_rows": selected,
        "mm_buy_contracts": buy, "mm_sell_contracts": sell,
        "sampled_observed_mm_signed_contracts": buy - sell,
        "mm_buy_trade_count": buy_trades, "mm_sell_trade_count": sell_trades,
        "underlying_call_put": [{"underlying": u, "call_put": cp, **v,
                                  "sampled_observed_mm_signed_contracts": v["mm_buy_contracts"] - v["mm_sell_contracts"]}
                                 for (u, cp), v in sorted(by_cp.items())],
        "contract_summaries": summaries[:max_contract_rows],
        "contract_summaries_truncated": len(summaries) > max_contract_rows,
        "cumulative_intraday": kind != "eod", "interval_difference_performed": False,
        "quantity_field": "mm_buy_vol/mm_sell_vol", "qty_fields_are_trade_counts": True,
        "identification_status": "SAMPLED_CAPACITY_ONLY", "inventory_q": None,
        "full_interval_delta_q": None, "net_inventory_gex": None,
        "sampling_mechanism_verified": False, "execution_eligible": False,
        "public_distribution_rights_verified": False,
        "limitations": ["sample_completeness_unverified", "no_initial_inventory",
                        "cumulative_snapshot_not_interval_flow", "do_not_difference_unmatched_samples"],
    }


def audit_open_close_sample(path, *, kind="eod", underlyings=None, received_at=None,
                            max_rows=DEFAULT_MAX_ROWS, max_contract_rows=500,
                            expected_sha256=OPEN_CLOSE_SAMPLE_SHA256) -> dict:
    if kind not in {"eod", "10m", "1m"}:
        raise CboeSampleError("invalid_open_close_kind")
    marker = {"eod": "C1OpenClose_", "10m": "12_30", "1m": "13_16"}[kind]
    reader, lineage = _load_csv(path, marker=marker, expected_sha256=expected_sha256)
    result = audit_open_close_rows(reader, kind=kind, source_id="Cboe DataShop sample/218",
                                   received_at=received_at, underlyings=underlyings,
                                   max_rows=max_rows, max_contract_rows=max_contract_rows,
                                   raw_sha256=lineage["raw_sha256"])
    result["lineage"] = lineage
    return result


def difference_open_close_cumulative(previous: Mapping, current: Mapping, *,
                                      same_contract_scope_verified=False) -> dict:
    """Difference two declared cumulative observations, preserving revisions.

    Caller must establish complete identical scope; the free samples do not.
    Negative changes are revision diagnostics, not negative execution sizes.
    """
    if same_contract_scope_verified is not True:
        raise CboeSampleError("matching_complete_contract_scope_required")
    required = {"contract_key", "trading_date", "session", "snapshot_source_local", "mm_buy_contracts", "mm_sell_contracts"}
    if not required.issubset(previous) or not required.issubset(current):
        raise CboeSampleError("invalid_cumulative_observation")
    for k in ("contract_key", "trading_date", "session"):
        if previous[k] != current[k]:
            raise CboeSampleError("cumulative_scope_or_session_reset")
    if _local_datetime(current["snapshot_source_local"]) <= _local_datetime(previous["snapshot_source_local"]):
        raise CboeSampleError("cumulative_time_not_increasing")
    b = int(_number(current["mm_buy_contracts"], integer=True) - _number(previous["mm_buy_contracts"], integer=True))
    s = int(_number(current["mm_sell_contracts"], integer=True) - _number(previous["mm_sell_contracts"], integer=True))
    revision = b < 0 or s < 0
    return {"buy_cumulative_difference": b, "sell_cumulative_difference": s,
            "net_cumulative_difference": b - s,
            "observed_interval_delta_q": None if revision else b - s,
            "revision_or_scope_diagnostic": revision, "inventory_q": None,
            "identification_status": "REVISION_REQUIRES_AUDIT" if revision else "OBSERVED_CHANGE_STOCK_UNIDENTIFIED",
            "execution_eligible": False}
