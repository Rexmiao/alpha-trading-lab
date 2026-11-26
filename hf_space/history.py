"""Bounded, uncached public daily history for the cloud research interface.

Only Yahoo's fixed HTTPS chart endpoint is used. This is an optional public
data source, not the primary moomoo CSV source or a brokerage connection.
No credentials, files, retry loops or synthetic fallback are used here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

import pandas as pd

from hf_space.engine import COLUMNS, parse_csv


ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/"
REQUEST_TIMEOUT_SECONDS = 12.0
TOTAL_BUDGET_SECONDS = 60.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PROVIDER_BARS = 800
MAX_SESSIONS = 400
_NEW_YORK = ZoneInfo("America/New_York")
_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")


class HistoryError(ValueError):
    """A public request or validation failed; no substitute data were returned."""

    def __init__(self, message, *, code="invalid_history", symbol=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.symbol = symbol
        self.http_status = http_status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even provider redirects cannot widen the permitted request destination.
        return None


def _ticker(value):
    if not isinstance(value, str) or _TICKER.fullmatch(value) is None:
        raise HistoryError("Use uppercase US stock/ETF tickers only, such as NVDA or SPY; URLs and paths are not accepted.", code="invalid_symbol")
    return value


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HistoryError("The 60-second public-data budget was exhausted. No partial dataset was returned.", code="time_budget")
    return min(REQUEST_TIMEOUT_SECONDS, remaining)


def _read_response(response, deadline):
    headers = getattr(response, "headers", {})
    length = headers.get("Content-Length")
    if length is not None:
        try:
            length = int(length)
        except (TypeError, ValueError):
            raise HistoryError("The public response has an invalid content length.", code="invalid_response") from None
        if not 0 <= length <= MAX_RESPONSE_BYTES:
            raise HistoryError("The public response exceeds the 2 MiB response limit.", code="response_limit")
    body = bytearray()
    reader = getattr(response, "read1", response.read)
    while True:
        timeout = _remaining(deadline)
        # urllib's socket read timeout is also reduced as the total deadline
        # approaches. read1 performs a bounded underlying socket read.
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(timeout)
        chunk = reader(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)))
        _remaining(deadline)
        if not isinstance(chunk, bytes):
            raise HistoryError("The public response was not a byte stream.", code="invalid_response")
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise HistoryError("The public response exceeds the 2 MiB response limit.", code="response_limit")


def _fetch(symbol, open_request, deadline):
    url = ENDPOINT + symbol + "?" + urlencode({"range": "2y", "interval": "1d", "events": "div,splits"})
    request = Request(url, headers={"User-Agent": "AlphaLab-PublicHistory/1.0", "Accept": "application/json"})
    try:
        with open_request(request, timeout=_remaining(deadline)) as response:
            if hasattr(response, "geturl") and response.geturl() != url:
                raise HistoryError("Public history redirects are not permitted.", code="redirect_refused", symbol=symbol)
            status = getattr(response, "status", 200)
            if status != 200:
                raise HTTPError(url, status, "", {}, None)
            contents = _read_response(response, deadline)
    except HTTPError as error:
        code = "rate_limited" if error.code == 429 else "access_denied" if error.code == 403 else "http_error"
        raise HistoryError(f"Yahoo history for {symbol} failed with HTTP {error.code}; no retries or substitute data were used.", code=code, symbol=symbol, http_status=error.code) from None
    except (TimeoutError, URLError, OSError) as error:
        code = "timeout" if isinstance(error, TimeoutError) else "network_error"
        raise HistoryError(f"The public history request for {symbol} failed ({code}); no substitute data were used.", code=code, symbol=symbol) from None
    try:
        payload = json.loads(contents.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, ValueError):
        raise HistoryError(f"Yahoo returned invalid JSON for {symbol}.", code="invalid_response", symbol=symbol) from None
    return payload, {"url": url, "sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents)}


def _number(value, *, symbol):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise HistoryError(f"Yahoo OHLCV/adjusted-close values for {symbol} must be finite numbers.", symbol=symbol)
    return float(value)


def _parse(payload, symbol, completed_before):
    try:
        chart = payload["chart"]
        if chart.get("error") is not None:
            raise HistoryError(f"Yahoo returned no usable history for {symbol}.", code="no_data", symbol=symbol)
        results = chart["result"]
        if not isinstance(results, list) or len(results) != 1:
            raise HistoryError(f"Yahoo returned no usable history for {symbol}.", code="no_data", symbol=symbol)
        result = results[0]
        meta = result["meta"]
        if (meta["symbol"] != symbol or meta["currency"] != "USD"
                or meta["exchangeTimezoneName"] != "America/New_York"
                or meta["instrumentType"] not in {"EQUITY", "ETF"}
                or meta.get("dataGranularity", "1d") != "1d"):
            raise HistoryError(f"Yahoo metadata for {symbol} does not describe the requested US daily stock/ETF in USD.", code="invalid_metadata", symbol=symbol)
        timestamps = result["timestamp"]
        if not isinstance(timestamps, list) or not 1 <= len(timestamps) <= MAX_PROVIDER_BARS:
            raise HistoryError(f"Yahoo returned an empty or oversized daily series for {symbol}.", code="no_data", symbol=symbol)
        quotes = result["indicators"]["quote"]
        adjusted = result["indicators"].get("adjclose")
        if not isinstance(quotes, list) or len(quotes) != 1 or not isinstance(adjusted, list) or len(adjusted) != 1:
            raise HistoryError(f"Yahoo adjusted close is required for {symbol}; raw and adjusted prices will not be mixed.", code="missing_adjusted_close", symbol=symbol)
        series = [quotes[0][column] for column in ("open", "high", "low", "close", "volume")] + [adjusted[0]["adjclose"]]
        if any(not isinstance(values, list) or len(values) != len(timestamps) for values in series):
            raise HistoryError(f"Yahoo daily arrays have inconsistent lengths for {symbol}.", symbol=symbol)
        events = result.get("events", {})
        if not isinstance(events, dict) or any(not isinstance(events.get(name, {}), dict) for name in ("dividends", "splits")):
            raise HistoryError(f"Yahoo corporate-action metadata is invalid for {symbol}.", symbol=symbol)
        rows, seen, factors, empty_dates = [], set(), [], []
        incomplete = 0
        for index, timestamp in enumerate(timestamps):
            if isinstance(timestamp, bool) or not isinstance(timestamp, int):
                raise HistoryError(f"Yahoo daily timestamps are invalid for {symbol}.", symbol=symbol)
            day = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(_NEW_YORK).date()
            if day in seen:
                raise HistoryError(f"Yahoo returned duplicate daily dates for {symbol}.", symbol=symbol)
            seen.add(day)
            if day >= completed_before:
                incomplete += 1
                continue
            if day.weekday() >= 5:
                raise HistoryError(f"Yahoo returned a weekend US stock bar for {symbol}.", symbol=symbol)
            values = [values[index] for values in series]
            if all(value is None for value in values):
                empty_dates.append(day.isoformat())
                continue
            if any(value is None for value in values):
                raise HistoryError(f"Yahoo returned a partially missing completed bar for {symbol} on {day}; gaps are not filled.", code="partial_bar", symbol=symbol)
            opening, high, low, close, volume, adjclose = [_number(value, symbol=symbol) for value in values]
            if (min(opening, high, low, close, adjclose) <= 0 or volume < 0
                    or high < max(opening, low, close) or low > min(opening, high, close)):
                raise HistoryError(f"Yahoo returned invalid completed OHLCV for {symbol} on {day}.", symbol=symbol)
            factor = adjclose / close
            prices = [value * factor for value in (opening, high, low, close)]
            if factor <= 0 or not math.isfinite(factor) or not all(math.isfinite(value) and value > 0 for value in prices):
                raise HistoryError(f"Yahoo price adjustment is invalid for {symbol} on {day}.", symbol=symbol)
            rows.append([day.isoformat(), symbol, *prices, volume])
            factors.append(factor)
        if not rows:
            raise HistoryError(f"No completed daily history is available for {symbol}.", code="no_data", symbol=symbol)
        return rows, {"provider_symbol": meta["symbol"], "currency": meta["currency"],
            "exchange_timezone": meta["exchangeTimezoneName"], "raw_bars": len(timestamps),
            "retained_completed_bars": len(rows), "skipped_incomplete_bars": incomplete,
            "skipped_empty_bars": len(empty_dates), "skipped_empty_dates": empty_dates,
            "events": {name: len(events.get(name, {})) for name in ("dividends", "splits")},
            "response_adjustment_factor_min": min(factors), "response_adjustment_factor_max": max(factors)}
    except HistoryError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, OSError):
        raise HistoryError(f"Yahoo returned incomplete or malformed daily history for {symbol}.", code="invalid_response", symbol=symbol) from None


def fetch_history(symbols, benchmark="SPY", sessions=400, *, opener=None, now=None):
    """Return validated seven-column prices and public-source provenance.

    ``opener`` may be an injected urllib-compatible callable (or object with
    ``open``) for offline tests. ``now`` is an aware datetime for the conservative
    date cutoff. Whole null bars may be skipped; partial completed bars fail.
    Sessions are the benchmark's last 1..400 available dates. IPO gaps remain.
    """
    if isinstance(symbols, (str, bytes)) or not isinstance(symbols, (list, tuple)) or not 3 <= len(symbols) <= 8:
        raise HistoryError("Choose 3 to 8 distinct stock/ETF tickers plus a separate benchmark.", code="invalid_symbols")
    symbols = [_ticker(symbol) for symbol in symbols]
    benchmark = _ticker(benchmark)
    if len(set(symbols)) != len(symbols) or benchmark in symbols:
        raise HistoryError("Stock tickers must be distinct and separate from the benchmark.", code="invalid_symbols")
    if isinstance(sessions, bool) or not isinstance(sessions, int) or not 1 <= sessions <= MAX_SESSIONS:
        raise HistoryError("sessions must be an integer from 1 to 400.", code="invalid_sessions")
    fetched_at = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(fetched_at, datetime) or fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise HistoryError("now must be a timezone-aware datetime.", code="invalid_clock")
    completed_before = fetched_at.astimezone(_NEW_YORK).date()
    if opener is None:
        open_request = build_opener(ProxyHandler({}), _NoRedirect()).open
    else:
        open_request = getattr(opener, "open", opener)
        if not callable(open_request):
            raise HistoryError("opener must be a callable HTTP test transport.", code="invalid_opener")
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    rows, responses = [], {}
    for symbol in [benchmark, *symbols]:
        payload, response = _fetch(symbol, open_request, deadline)
        ticker_rows, details = _parse(payload, symbol, completed_before)
        rows.extend(ticker_rows)
        responses[symbol] = {**response, **details}
        _remaining(deadline)
    frame = pd.DataFrame(rows, columns=COLUMNS)
    calendar = sorted(frame.loc[frame.symbol.eq(benchmark), "date"].unique())
    if len(calendar) < sessions:
        raise HistoryError(f"Benchmark {benchmark} has only {len(calendar)} completed dates; {sessions} were requested. No history was fabricated.", code="insufficient_benchmark", symbol=benchmark)
    calendar = calendar[-sessions:]
    frame = frame.loc[frame.date.isin(calendar)].copy()
    coverage = {}
    for symbol in [benchmark, *symbols]:
        dates = sorted(frame.loc[frame.symbol.eq(symbol), "date"].unique())
        if not dates:
            raise HistoryError(f"{symbol} has no bars in the selected benchmark window; IPO history is not backfilled.", code="no_window_data", symbol=symbol)
        coverage[symbol] = {"rows": len(dates), "first_date": dates[0], "last_date": dates[-1],
                            "missing_benchmark_sessions": sessions - len(dates)}
    # Reuse the same CSV/data boundary as guest uploads. No file is opened.
    prices = parse_csv(frame.to_csv(index=False).encode("utf-8"), benchmark=benchmark)
    snapshot = prices.to_csv(index=False, date_format="%Y-%m-%d", lineterminator="\n").encode("utf-8")
    _remaining(deadline)
    provenance = {"provider": "Yahoo Finance public chart", "source": "public_yahoo",
        "retrieved_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "symbols": symbols, "benchmark": benchmark, "requested_sessions": sessions,
        "sessions": len(calendar), "range": "2y", "interval": "1d",
        "events_requested": ["dividends", "splits"], "completed_before_et": completed_before.isoformat(),
        "start": calendar[0], "end": calendar[-1],
        "price_basis": "Yahoo adjclose/close multiplies each daily open, high, low and close; split/dividend-adjusted research prices, not original executable quotes.",
        "volume_basis": "Yahoo reported volume is retained unchanged; it is not rescaled by the price adjustment factor.",
        "price_is_executable": False, "no_gap_filling": True,
        "csv_sha256": hashlib.sha256(snapshot).hexdigest(), "csv_bytes": len(snapshot),
        "csv_encoding": "utf-8", "csv_line_ending": "LF", "csv_date_format": "%Y-%m-%d",
        "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS, "total_budget_seconds": TOTAL_BUDGET_SECONDS,
        "max_response_bytes": MAX_RESPONSE_BYTES, "coverage": coverage, "responses": responses}
    return prices, provenance
