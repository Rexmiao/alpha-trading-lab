"""Public-data transport/normalization tests. All quotes are fictional fixtures."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from hf_space import history


SYMBOLS = ["AAA", "BBB", "CCC"]
NOW = datetime(2025, 1, 7, 16, tzinfo=timezone.utc)
DATES = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]


def payload(symbol):
    timestamps = [int(pd.Timestamp(day + " 14:30", tz="UTC").timestamp()) for day in DATES]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "currency": "USD", "exchangeTimezoneName": "America/New_York",
                 "instrumentType": "ETF" if symbol == "SPY" else "EQUITY", "dataGranularity": "1d"},
        "timestamp": timestamps,
        "indicators": {"quote": [{"open": [100, 102, 104, None], "high": [105, 107, 109, None],
            "low": [95, 97, 99, None], "close": [102, 104, 106, 108], "volume": [1000, 2000, 3000, None]}],
            "adjclose": [{"adjclose": [51, 52, 106, None]}]},
        "events": {"dividends": {"example": {"amount": .2}}, "splits": {"example": {"splitRatio": "2:1"}}},
    }]}}


class Response(BytesIO):
    status = 200

    def __init__(self, data, url):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self.url = url

    def geturl(self):
        return self.url


class Transport:
    def __init__(self, mutate=None):
        self.mutate = mutate
        self.requests = []
        self.bodies = {}

    def __call__(self, request, *, timeout):
        url = request.full_url
        self.requests.append((url, timeout, dict(request.header_items())))
        symbol = urlsplit(url).path.rsplit("/", 1)[1]
        data = payload(symbol)
        if self.mutate:
            self.mutate(symbol, data)
        body = json.dumps(data).encode("utf-8")
        self.bodies[symbol] = body
        return Response(body, url)


def result(payload):
    return payload["chart"]["result"][0]


def remove_bar(data, index):
    table = result(data)
    table["timestamp"].pop(index)
    for group, columns in (("quote", ["open", "high", "low", "close", "volume"]), ("adjclose", ["adjclose"])):
        for column in columns:
            table["indicators"][group][0][column].pop(index)


def test_fixed_requests_adjust_all_ohlc_keep_volume_and_export_auditable_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    transport = Transport()
    frame, provenance = history.fetch_history(SYMBOLS, sessions=3, opener=transport, now=NOW)
    assert list(tmp_path.iterdir()) == []
    assert tuple(frame.columns) == history.COLUMNS
    assert len(transport.requests) == 4
    assert frame.date.max() == pd.Timestamp("2025-01-06")  # today's incomplete data is excluded
    first = frame.loc[frame.symbol.eq("AAA")].iloc[0]
    assert [first.open, first.high, first.low, first.close, first.volume] == [50, 52.5, 47.5, 51, 1000]
    assert provenance["price_is_executable"] is False
    assert provenance["completed_before_et"] == "2025-01-07"
    assert provenance["start"] == "2025-01-02"
    assert provenance["end"] == "2025-01-06"
    assert provenance["coverage"]["AAA"]["rows"] == 3
    for url, timeout, headers in transport.requests:
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.netloc == "query1.finance.yahoo.com"
        assert parts.path.startswith("/v8/finance/chart/")
        assert parse_qs(parts.query) == {"range": ["2y"], "interval": ["1d"], "events": ["div,splits"]}
        assert 0 < timeout <= history.REQUEST_TIMEOUT_SECONDS
        assert not any(key.lower() in {"authorization", "cookie"} for key in headers)
    for symbol, response in provenance["responses"].items():
        assert response["sha256"] == hashlib.sha256(transport.bodies[symbol]).hexdigest()
        assert response["events"] == {"dividends": 1, "splits": 1}
        assert response["skipped_incomplete_bars"] == 1
    csv = frame.to_csv(index=False, date_format="%Y-%m-%d", lineterminator="\n").encode("utf-8")
    assert provenance["csv_sha256"] == hashlib.sha256(csv).hexdigest()
    assert provenance["csv_bytes"] == len(csv)
    pd.testing.assert_frame_equal(history.parse_csv(csv), frame)
    json.dumps(provenance, allow_nan=False)


def test_uses_new_york_date_even_when_utc_date_is_next_day():
    now = datetime(2025, 1, 7, 1, tzinfo=timezone.utc)  # still Jan 6 in New York
    frame, provenance = history.fetch_history(SYMBOLS, sessions=2, opener=Transport(), now=now)
    assert provenance["completed_before_et"] == "2025-01-06"
    assert frame.date.max() == pd.Timestamp("2025-01-03")


def test_missing_ipo_bar_and_whole_null_bar_are_not_filled():
    def mutate(symbol, data):
        if symbol == "BBB":
            remove_bar(data, 0)
        if symbol == "CCC":
            table = result(data)["indicators"]
            for name in ("open", "high", "low", "close", "volume"):
                table["quote"][0][name][1] = None
            table["adjclose"][0]["adjclose"][1] = None
    frame, provenance = history.fetch_history(SYMBOLS, sessions=3, opener=Transport(mutate), now=NOW)
    assert len(frame.loc[frame.symbol.eq("BBB")]) == 2
    assert len(frame.loc[frame.symbol.eq("CCC")]) == 2
    assert provenance["coverage"]["BBB"]["missing_benchmark_sessions"] == 1
    assert provenance["coverage"]["BBB"]["first_date"] == "2025-01-03"
    assert provenance["responses"]["CCC"]["skipped_empty_dates"] == ["2025-01-03"]
    assert provenance["no_gap_filling"] is True


@pytest.mark.parametrize("bad_symbols", [
    "AAA,BBB,CCC", ["AAA", "BBB"], ["AAA"] * 9, ["AAA", "AAA", "CCC"],
    ["SPY", "BBB", "CCC"], ["aaa", "BBB", "CCC"],
    ["https://example.com", "BBB", "CCC"], ["../SPY", "BBB", "CCC"],
    ["AAA?x=1", "BBB", "CCC"], ["AAA/BBB", "BBB", "CCC"],
    ["^GSPC", "BBB", "CCC"], ["AAA\n", "BBB", "CCC"],
])
def test_invalid_symbols_fail_before_network(bad_symbols):
    transport = Transport()
    with pytest.raises(history.HistoryError):
        history.fetch_history(bad_symbols, opener=transport, now=NOW)
    assert transport.requests == []


@pytest.mark.parametrize("benchmark,sessions,now", [
    ("https://localhost", 3, NOW), ("spy", 3, NOW), ("SPY", 0, NOW),
    ("SPY", 401, NOW), ("SPY", True, NOW), ("SPY", 3.0, NOW),
    ("SPY", 3, datetime(2025, 1, 7)),
])
def test_invalid_other_parameters_fail_before_network(benchmark, sessions, now):
    transport = Transport()
    with pytest.raises(history.HistoryError):
        history.fetch_history(SYMBOLS, benchmark, sessions, opener=transport, now=now)
    assert transport.requests == []


@pytest.mark.parametrize("status,code", [(429, "rate_limited"), (403, "access_denied"), (500, "http_error")])
def test_http_failures_are_explicit_and_never_retry(status, code):
    calls = []
    def opener(request, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, status, "provider detail must not leak", {}, None)
    with pytest.raises(history.HistoryError, match=f"HTTP {status}") as error:
        history.fetch_history(SYMBOLS, sessions=3, opener=opener, now=NOW)
    assert error.value.code == code and error.value.http_status == status
    assert len(calls) == 1
    assert "provider detail" not in str(error.value)


@pytest.mark.parametrize("failure", [URLError("private transport detail"), TimeoutError("private transport detail")])
def test_network_failures_have_no_fallback(failure):
    def opener(*args, **kwargs):
        raise failure
    with pytest.raises(history.HistoryError, match="no substitute") as error:
        history.fetch_history(SYMBOLS, sessions=3, opener=opener, now=NOW)
    assert "private transport detail" not in str(error.value)


@pytest.mark.parametrize("problem", ["currency", "timezone", "instrument", "missing_adjclose", "partial", "ohlc", "nan", "duplicate", "no_data"])
def test_unsupported_or_invalid_provider_data_is_refused(problem):
    def mutate(symbol, data):
        if symbol != "AAA":
            return
        table = result(data)
        if problem == "currency": table["meta"]["currency"] = "EUR"
        elif problem == "timezone": table["meta"]["exchangeTimezoneName"] = "Europe/London"
        elif problem == "instrument": table["meta"]["instrumentType"] = "MUTUALFUND"
        elif problem == "missing_adjclose": del table["indicators"]["adjclose"]
        elif problem == "partial": table["indicators"]["quote"][0]["volume"][0] = None
        elif problem == "ohlc": table["indicators"]["quote"][0]["high"][0] = 1
        elif problem == "nan": table["indicators"]["quote"][0]["close"][0] = float("nan")
        elif problem == "duplicate": table["timestamp"][1] = table["timestamp"][0]
        else: data["chart"]["result"] = None
    with pytest.raises(history.HistoryError):
        history.fetch_history(SYMBOLS, sessions=3, opener=Transport(mutate), now=NOW)


def test_benchmark_calendar_controls_tail_and_drops_other_stock_dates():
    def mutate(symbol, data):
        if symbol == "SPY": remove_bar(data, 1)
    frame, provenance = history.fetch_history(SYMBOLS, sessions=2, opener=Transport(mutate), now=NOW)
    assert set(frame.date) == {pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-06")}
    assert provenance["sessions"] == 2
    with pytest.raises(history.HistoryError, match="only 2 completed dates"):
        history.fetch_history(SYMBOLS, sessions=3, opener=Transport(mutate), now=NOW)


def test_response_size_and_total_budget_are_bounded(monkeypatch):
    def oversized(request, **kwargs):
        response = Response(b"{}", request.full_url)
        response.headers["Content-Length"] = str(history.MAX_RESPONSE_BYTES + 1)
        return response
    with pytest.raises(history.HistoryError, match="response limit"):
        history.fetch_history(SYMBOLS, sessions=3, opener=oversized, now=NOW)

    ticks = iter([0, 61])
    monkeypatch.setattr(history.time, "monotonic", lambda: next(ticks))
    transport = Transport()
    with pytest.raises(history.HistoryError, match="budget"):
        history.fetch_history(SYMBOLS, sessions=3, opener=transport, now=NOW)
    assert transport.requests == []


def test_redirected_response_is_rejected():
    def opener(request, **kwargs):
        return Response(b"{}", "http://127.0.0.1/prices")
    with pytest.raises(history.HistoryError, match="redirects"):
        history.fetch_history(SYMBOLS, sessions=3, opener=opener, now=NOW)
