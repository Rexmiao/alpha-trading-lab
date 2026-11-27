"""Private, revision-pinned moomoo daily research input; never broker access.

Prices remain in the caller's server-side session. Only the explicitly sanitized
provenance is suitable for a public result; this module offers no download route.
The existing five-minute snapshot namespace and pointer are never used here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import hashlib
import os
import re
import time

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from hf_space.snapshot_source import (DATASET_ID, HUB_HOST, METADATA_LIMIT,
    TOTAL_TIMEOUT, SnapshotError, _SnapshotRedirect, _get, _integer, _instant,
    _iso, _json, _HEX40, _HEX64, ProxyHandler, build_opener)


DailySnapshotError = SnapshotError
COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume")
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_ROWS = 80_000
MAX_DATES = 1260
MAX_STOCKS = 60
PRICE_BASIS = "moomoo_forward_adjusted_ohlcv"
SESSION = "provider_daily"
DATE_CONVENTION = "exchange_session_date"
BOUNDARY_POLICY = "configured_symbol_start_dates_applied"
KNOWN_START_DATES = {"SNDK": "2025-02-24", "CRWV": "2025-03-28", "NBIS": "2024-10-21"}
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")


def _now(now=None):
    try:
        stamp = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
        if stamp.tzinfo is None:
            raise ValueError
        return stamp.tz_convert("UTC")
    except (TypeError, ValueError, OverflowError):
        raise DailySnapshotError("A timezone-aware current time is required.", code="INVALID_CLOCK") from None


def daily_calendar(frame):
    """Build the bounded XNYS calendar for observed daily session dates."""
    days = pd.DatetimeIndex(frame.date.unique()).sort_values()
    if not len(days) or len(days) > MAX_DATES or (days[-1] - days[0]).days > 3653:
        raise DailySnapshotError("Daily dates exceed the bounded research range.", code="INVALID_PRICES")
    try:
        return xcals.get_calendar("XNYS", start=days[0] - pd.Timedelta(days=7),
                                  end=days[-1] + pd.Timedelta(days=7))
    except (ValueError, TypeError, OverflowError):
        raise DailySnapshotError("Daily dates could not be checked against the exchange calendar.", code="INVALID_PRICES") from None


def parse_daily_csv(contents, *, now=None, start_dates=None):
    """Parse bounded UTF-8 daily OHLCV without filling any missing observations.

    ``start_dates`` is a caller-explicit boundary check, never automatic trimming.
    The publisher and private reader supply the same known identity boundaries.
    Missing per-symbol bars are left for the Beta engine's causal eligibility.
    """
    if not isinstance(contents, bytes) or not 0 < len(contents) <= MAX_UPLOAD_BYTES:
        raise DailySnapshotError("Provide a daily CSV no larger than 12 MiB.", code="SIZE_LIMIT")
    try:
        frame = pd.read_csv(StringIO(contents.decode("utf-8-sig")), dtype={"date": str, "symbol": str},
                            keep_default_na=False, on_bad_lines="error")
        if tuple(frame.columns) != COLUMNS or not 1 <= len(frame) <= MAX_ROWS:
            raise ValueError
        if not frame.date.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
            raise ValueError
        frame["date"] = pd.to_datetime(frame.date, format="%Y-%m-%d", errors="raise")
        if not frame.symbol.map(lambda value: isinstance(value, str) and _SYMBOL.fullmatch(value) is not None).all():
            raise ValueError
        symbols = set(frame.symbol)
        if "SPY" not in symbols or not 2 <= len(symbols) <= MAX_STOCKS + 1:
            raise ValueError
        if frame.duplicated(["date", "symbol"]).any():
            raise ValueError
        for name in COLUMNS[2:]:
            frame[name] = pd.to_numeric(frame[name], errors="raise")
        numbers = frame.loc[:, COLUMNS[2:]].to_numpy(dtype=float)
        if (not np.isfinite(numbers).all() or (numbers[:, :4] <= 0).any() or (numbers[:, 4] < 0).any()
                or (frame.high < frame[["open", "low", "close"]].max(axis=1)).any()
                or (frame.low > frame[["open", "high", "close"]].min(axis=1)).any()):
            raise ValueError
    except (UnicodeError, ValueError, TypeError, OverflowError, pd.errors.ParserError):
        raise DailySnapshotError("Daily CSV failed its date, symbol or OHLCV checks.", code="INVALID_PRICES") from None
    stamp = _now(now)
    if frame.date.max().date() > stamp.tz_convert("America/New_York").date():
        raise DailySnapshotError("Future daily bars are not accepted.", code="INVALID_PRICES")
    calendar = daily_calendar(frame)
    days = pd.DatetimeIndex(frame.date.unique()).sort_values()
    if not days.isin(calendar.sessions).all():
        raise DailySnapshotError("Daily dates must be actual XNYS sessions.", code="INVALID_PRICES")
    # A conservative post-close buffer matches the local daily collector policy.
    final_close = calendar.session_close(days[-1])
    if final_close + pd.Timedelta(minutes=20) > stamp:
        raise DailySnapshotError("The last daily session has not completed its publication buffer.", code="INVALID_PRICES")
    if start_dates is not None:
        if not isinstance(start_dates, dict):
            raise DailySnapshotError("Daily identity boundaries are invalid.", code="INVALID_PRICES")
        for symbol, start in start_dates.items():
            if symbol not in symbols or not isinstance(start, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
                raise DailySnapshotError("Daily identity boundaries are invalid.", code="INVALID_PRICES")
            try:
                boundary = pd.Timestamp(start)
            except (ValueError, OverflowError):
                raise DailySnapshotError("Daily identity boundaries are invalid.", code="INVALID_PRICES") from None
            if (frame.loc[frame.symbol.eq(symbol), "date"] < boundary).any():
                raise DailySnapshotError("Daily CSV contains observations before a disclosed identity boundary.", code="INVALID_PRICES")
    return frame.sort_values(["date", "symbol"]).reset_index(drop=True)


def validate_normalization(value, symbols):
    """Return an allowlisted date/identity contract; never free-form source text."""
    if (not isinstance(value, dict) or value.get("completed_session_verified") is not True
            or value.get("calendar") != "XNYS" or value.get("boundary_policy") != BOUNDARY_POLICY):
        raise DailySnapshotError("Verified completed sessions and identity boundaries are required.")
    boundaries = value.get("symbol_start_dates")
    expected = {symbol: day for symbol, day in KNOWN_START_DATES.items() if symbol in symbols}
    if boundaries != expected:
        raise DailySnapshotError("The daily identity boundary declaration does not match the supported symbols.")
    return {"completed_session_verified": True, "calendar": "XNYS",
            "boundary_policy": BOUNDARY_POLICY, "symbol_start_dates": dict(sorted(expected.items()))}


def fetch_moomoo_daily_snapshot(*, opener=None, now=None):
    """Return (daily prices, sanitized provenance) pinned to one private commit.

    Uses only the dataset-specific read token and fixed daily paths. No fallback
    to HF_TOKEN, a broker, public quote service, local files or synthetic input.
    """
    dataset = os.environ.get("ALPHA_SNAPSHOT_DATASET", "")
    token = os.environ.get("ALPHA_SNAPSHOT_READ_TOKEN", "")
    if not dataset or not token:
        raise DailySnapshotError("Private moomoo daily snapshots are not configured.", code="NOT_CONFIGURED")
    if (dataset != DATASET_ID or not isinstance(token, str) or not 1 <= len(token) <= 2048
            or any(not 33 <= ord(char) <= 126 for char in token)):
        raise DailySnapshotError("The dedicated daily snapshot configuration is invalid.", code="INVALID_CONFIGURATION")
    stamp, deadline = _now(now), time.monotonic() + TOTAL_TIMEOUT
    open_request = opener if opener is not None else build_opener(ProxyHandler({}), _SnapshotRedirect()).open
    info = _json(_get(f"https://{HUB_HOST}/api/datasets/{dataset}/revision/main", token,
                      open_request, METADATA_LIMIT, deadline))
    if info.get("private") is not True:
        raise DailySnapshotError("The daily snapshot dataset must be private.", code="NOT_PRIVATE")
    revision = info.get("sha")
    if info.get("id") != DATASET_ID or not isinstance(revision, str) or _HEX40.fullmatch(revision) is None:
        raise DailySnapshotError("The daily dataset identity or revision is invalid.")
    base = f"https://{HUB_HOST}/datasets/{dataset}/resolve/{revision}/"
    latest = _json(_get(base + "daily/latest.json", token, open_request, METADATA_LIMIT, deadline))
    identifier = latest.get("snapshot_id")
    if (type(latest.get("schema_version")) is not int or latest["schema_version"] != 1
            or not isinstance(identifier, str) or _HEX64.fullmatch(identifier) is None):
        raise DailySnapshotError("The daily snapshot pointer is invalid.")
    folder = f"daily/snapshots/{identifier}"
    csv_path, manifest_path = folder + "/bars.csv", folder + "/manifest.json"
    if latest.get("csv_path") != csv_path or latest.get("manifest_path") != manifest_path:
        raise DailySnapshotError("Daily paths must match the fixed content-addressed layout.", code="INVALID_PATH")
    manifest = _json(_get(base + manifest_path, token, open_request, METADATA_LIMIT, deadline))
    expected = {"schema_version": 1, "source": "moomoo", "frequency": "1d", "benchmark": "SPY",
        "session": SESSION, "date_convention": DATE_CONVENTION, "price_basis": PRICE_BASIS, "rehab_type": 1}
    if any(manifest.get(key) != value or isinstance(value, int) and type(manifest.get(key)) is not int
           for key, value in expected.items()):
        raise DailySnapshotError("The daily snapshot manifest does not match the moomoo contract.")
    csv = manifest.get("csv")
    if not isinstance(csv, dict) or csv.get("path") != csv_path or csv.get("sha256") != identifier:
        raise DailySnapshotError("The daily CSV path or hash is invalid.", code="INVALID_PATH")
    byte_count = _integer(csv.get("bytes"), 1, MAX_UPLOAD_BYTES)
    row_count = _integer(csv.get("rows"), 1, MAX_ROWS)
    symbols = manifest.get("symbols")
    if (not isinstance(symbols, list) or not 2 <= len(symbols) <= MAX_STOCKS + 1
            or any(not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None for symbol in symbols)
            or len(set(symbols)) != len(symbols) or "SPY" not in symbols):
        raise DailySnapshotError("The daily snapshot symbols are invalid.")
    normalization = validate_normalization(manifest.get("normalization"), symbols)
    created, collected, as_of = (_instant(manifest.get(key)) for key in ("created_at", "collected_at", "as_of"))
    if as_of > collected or collected > created or created > stamp:
        raise DailySnapshotError("Daily snapshot timestamps are inconsistent or in the future.")
    contents = _get(base + csv_path, token, open_request, min(MAX_UPLOAD_BYTES, byte_count), deadline)
    if len(contents) != byte_count or hashlib.sha256(contents).hexdigest() != identifier:
        raise DailySnapshotError("Daily CSV failed its byte-count or SHA256 check.", code="HASH_MISMATCH")
    try:
        prices = parse_daily_csv(contents, now=stamp, start_dates=normalization["symbol_start_dates"])
    except (DailySnapshotError, ValueError, TypeError):
        raise DailySnapshotError("The private daily snapshot failed OHLCV or session validation.", code="INVALID_PRICES") from None
    if len(prices) != row_count or set(prices.symbol) != set(symbols):
        raise DailySnapshotError("The daily CSV rows or symbols differ from the manifest.")
    last_date = prices.date.max()
    if daily_calendar(prices).session_close(last_date) != as_of or manifest.get("last_session") != str(last_date.date()):
        raise DailySnapshotError("Daily as_of must identify the final completed exchange session close.")
    provenance = {"provider": "moomoo_private_daily_snapshot", "source": "moomoo_daily_snapshot",
        "dataset": DATASET_ID, "private_verified": True, "revision": revision, "snapshot_id": identifier,
        "created_at": _iso(created), "collected_at": _iso(collected), "as_of": _iso(as_of),
        "retrieved_at": _iso(stamp), "benchmark": "SPY", "symbols": sorted(symbols), "frequency": "1d",
        "session": SESSION, "date_convention": DATE_CONVENTION, "price_basis": PRICE_BASIS, "rehab_type": 1,
        "first_session": str(prices.date.min().date()), "last_session": str(last_date.date()),
        "session_count": int(prices.date.nunique()), "csv_sha256": identifier, "csv_bytes": byte_count,
        "csv_rows": row_count, "raw_download_available": False, "normalization": normalization}
    return prices, provenance
