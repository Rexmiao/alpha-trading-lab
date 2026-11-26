"""Fake CLI records only: no moomoo, SDK, account or network is contacted."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from execution_lab.marketdata import (COLUMNS, MarketDataError, MoomooDesktopSource,
                                     make_quote_provider, market_state, next_capture_at)


AS_OF = pd.Timestamp("2024-03-11T13:45:10Z")
FAKE_SECRET = "FICTIONAL_LOCAL_HOST_KEY_NOT_REAL"


def provider_rows(symbol="SPY", *, ends=None):
    ends = ends if ends is not None else pd.date_range("2024-03-11T13:35Z", periods=3, freq="5min")
    result = []
    for index, end in enumerate(ends):
        price = 100 + index + (10 if symbol == "NVDA" else 0)
        result.append({"time": end.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": end.timestamp(), "open_price": price, "high_price": price + 1,
            "low_price": price - 1, "close_price": price + .5, "volume": 1000 + index, "is_blank": False})
    return result


class FakeCLI:
    def __init__(self, by_symbol=None, failure=None):
        self.by_symbol = by_symbol or {symbol: provider_rows(symbol) for symbol in ("SPY", "NVDA")}
        self.failure = failure
        self.calls = []

    def __call__(self, argv, *, env, timeout):
        self.calls.append({"argv": argv, "timeout": timeout})
        assert env["OPENAPI_HOST_APPKEY"] == FAKE_SECRET
        assert argv[1] == "--raw"
        command = argv[2]
        assert command in {"subscribe", "get-kline"}
        assert all(word not in argv for word in ("get-acc-list", "place-order", "accinfo-query"))
        if command == "subscribe":
            assert "--no-is-reg-or-un-reg-push" in argv and "--no-extended-time" in argv
            assert argv[argv.index("--sub-type-list") + 1] == "7"
            payload = {"ret_type": 0, "err_code": 0, "s2c": {}}
        else:
            assert argv[argv.index("--kl-type") + 1] == "6"
            assert argv[argv.index("--req-num") + 1] == "1000"
            assert argv[argv.index("--rehab-type") + 1] == "0"
            symbol = argv[-1].removeprefix("US.")
            if self.failure:
                return self.failure(argv)
            payload = {"ret_type": 0, "err_code": 0, "s2c": {
                "security": {"market": 11, "code": symbol}, "kl_list": self.by_symbol[symbol]}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")


def source(fake=None, *, now=AS_OF):
    return MoomooDesktopSource(cli_path="FICTIONAL_CLI", runner=fake or FakeCLI(),
        credential_loader=lambda: FAKE_SECRET, clock=lambda: now.to_pydatetime())


def test_ready_batch_returns_complete_current_prefix_utc_starts_and_snapshot_hashes(tmp_path):
    fake = FakeCLI()
    frame, provenance = source(fake).read_completed(["SPY", "NVDA"], AS_OF, tmp_path)
    assert list(frame.columns) == list(COLUMNS)
    assert len(frame) == 6 and str(frame.timestamp.dtype) == "datetime64[ns, UTC]"
    assert frame.timestamp.min() == pd.Timestamp("2024-03-11T13:30Z")
    assert frame.timestamp.max() == pd.Timestamp("2024-03-11T13:40Z")
    assert provenance["status"] == "READY" and provenance["as_of"] == "2024-03-11T13:45:00Z"
    assert len(fake.calls) == 3
    for item in provenance["files"] + [provenance["normalized_csv"]]:
        contents = Path(item["path"]).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == item["sha256"]
    manifest = Path(provenance["manifest_path"]).read_text(encoding="utf8")
    assert FAKE_SECRET not in manifest
    assert all(row["missing_bars"] == 0 for row in provenance["coverage"])


def test_calendar_observes_dst_half_day_and_holiday_without_rpc():
    winter = market_state("2024-03-08T14:35:10Z")
    summer = market_state("2024-03-11T13:35:10Z")
    assert winter["session_open"].hour == 14 and summer["session_open"].hour == 13
    holiday = market_state("2026-11-26T17:00:00Z")
    assert holiday["status"] == "MARKET_CLOSED"
    assert holiday["next_capture_at"] == datetime(2026, 11, 27, 14, 35, 10, tzinfo=timezone.utc)
    half_day = market_state("2026-11-27T18:00:10Z")
    assert half_day["status"] == "READY" and half_day["session_close"].hour == 18
    assert half_day["expected_bar_end"] == half_day["session_close"]
    assert not half_day["market_is_open"] and not half_day["new_entry_allowed"]
    assert next_capture_at("2024-03-08T21:00:10Z") == datetime(2024, 3, 11, 13, 35, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("as_of,status", [("2026-11-26T17:00Z", "MARKET_CLOSED"),
                                          ("2024-03-11T13:35:09Z", "WAITING_FOR_COMPLETED_BAR")])
def test_closed_or_not_due_never_reads_key_or_runs_cli(tmp_path, as_of, status):
    def forbidden(*args, **kwargs):
        raise AssertionError("No key read or CLI call is permitted")
    stamp = pd.Timestamp(as_of)
    obj = MoomooDesktopSource(runner=forbidden, credential_loader=forbidden, clock=lambda: stamp)
    frame, provenance = obj.read_completed(["SPY"], stamp, tmp_path)
    assert frame.empty and provenance["status"] == status
    assert provenance["files"] == []
    assert Path(provenance["manifest_path"]).is_file()


def test_publication_lag_keeps_just_ended_bar_out_until_plus_ten_seconds(tmp_path):
    now = pd.Timestamp("2024-03-11T13:45:09Z")
    frame, provenance = source(now=now).read_completed(["SPY", "NVDA"], now, tmp_path)
    assert len(frame) == 4
    assert provenance["as_of"] == "2024-03-11T13:40:00Z"
    assert all(item["ignored"]["not_due_or_future"] == 1 for item in provenance["coverage"])


def test_in_progress_and_future_bars_are_not_used_or_filled(tmp_path):
    future_ends = pd.date_range("2024-03-11T13:35Z", periods=5, freq="5min")
    fake = FakeCLI({symbol: provider_rows(symbol, ends=future_ends) for symbol in ("SPY", "NVDA")})
    frame, provenance = source(fake).read_completed(["SPY", "NVDA"], AS_OF, tmp_path)
    assert len(frame) == 6
    assert frame.timestamp.max() + pd.Timedelta(minutes=5) <= AS_OF
    assert all(item["ignored"]["not_due_or_future"] == 2 for item in provenance["coverage"])


@pytest.mark.parametrize("removed", [0, 1, 2])
def test_any_stock_missing_a_required_bar_fails_the_whole_batch(tmp_path, removed):
    records = provider_rows("NVDA")
    records.pop(removed)
    fake = FakeCLI({"SPY": provider_rows(), "NVDA": records})
    with pytest.raises(MarketDataError, match="STALE_OR_INCOMPLETE_QUOTE_BATCH") as captured:
        source(fake).read_completed(["SPY", "NVDA"], AS_OF, tmp_path)
    info = captured.value.provenance
    assert info["status"] == "FAILED" and "normalized_csv" not in info
    assert any(row["missing_bars"] == 1 for row in info["coverage"])
    assert not list(Path(info["snapshot_dir"]).glob("bars.csv"))


def test_previous_session_is_not_used_as_today_and_never_fills_ipo_or_missing_history(tmp_path):
    old = provider_rows(ends=pd.date_range("2024-03-08T14:35Z", periods=3, freq="5min"))
    fake = FakeCLI({"SPY": old})
    with pytest.raises(MarketDataError, match="STALE_OR_INCOMPLETE_QUOTE_BATCH"):
        source(fake).read_completed(["SPY"], AS_OF, tmp_path)


@pytest.mark.parametrize("kind,expected", [("duplicate", "DUPLICATE_COMPLETED_BAR"),
    ("blank", "STALE_OR_INCOMPLETE_QUOTE_BATCH"), ("price", "INVALID_COMPLETED_OHLC"),
    ("epoch", "INVALID_PROVIDER_BAR_TIME"), ("bar_start", "UNVERIFIED_PROVIDER_BAR_LABEL"),
    ("one_minute", "QUOTE_INTERVAL_MISMATCH")])
def test_invalid_or_changed_provider_contract_fails_closed(tmp_path, kind, expected):
    records = provider_rows()
    if kind == "duplicate":
        records.append(dict(records[0]))
    elif kind == "blank":
        records[0]["is_blank"] = True
    elif kind == "price":
        records[0]["high_price"] = 1
    elif kind == "epoch":
        records[0]["timestamp"] += 60
    else:
        end = pd.Timestamp("2024-03-11T13:30Z" if kind == "bar_start" else "2024-03-11T13:36Z")
        records += provider_rows(ends=[end])
    with pytest.raises(MarketDataError, match=expected):
        source(FakeCLI({"SPY": records})).read_completed(["SPY"], AS_OF, tmp_path)


def test_current_session_capture_is_immutable_even_for_same_asof(tmp_path):
    obj = source()
    first, a = obj.read_completed(["SPY"], AS_OF, tmp_path)
    first_manifest = Path(a["manifest_path"]).read_bytes()
    second, b = obj.read_completed(["SPY"], AS_OF, tmp_path)
    assert a["snapshot_dir"] != b["snapshot_dir"]
    assert Path(a["manifest_path"]).read_bytes() == first_manifest
    pd.testing.assert_frame_equal(first, second)
    assert a["normalized_csv"]["sha256"] == b["normalized_csv"]["sha256"]


def test_cli_stderr_business_error_is_classified_without_key_or_raw_stderr(tmp_path):
    def rejected(argv):
        text = '{"error":"business error ret_type=-1 err_code=-1002: 先订阅; key=' + FAKE_SECRET + '"}'
        return subprocess.CompletedProcess(argv, 1, b"", text.encode())
    with pytest.raises(MarketDataError, match="SUBSCRIPTION_REQUIRED") as captured:
        source(FakeCLI(failure=rejected)).read_completed(["SPY"], AS_OF, tmp_path)
    provenance = captured.value.provenance
    assert provenance["provider_error"]["err_code"] == -1002
    assert FAKE_SECRET not in json.dumps(provenance)
    assert FAKE_SECRET not in Path(provenance["manifest_path"]).read_text(encoding="utf8")


def test_timeout_is_finite_and_does_not_turn_into_an_empty_success(tmp_path):
    def timed_out(argv):
        raise subprocess.TimeoutExpired("not logged", 15)
    with pytest.raises(MarketDataError, match="QUOTE_REQUEST_TIMEOUT") as captured:
        source(FakeCLI(failure=timed_out)).read_completed(["SPY"], AS_OF, tmp_path)
    assert captured.value.provenance["status"] == "FAILED"


def test_success_response_echoing_key_is_rejected_before_raw_snapshot_write(tmp_path):
    def leaked(argv):
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ret_type": 0, "debug": FAKE_SECRET,
            "s2c": {"kl_list": provider_rows()}}).encode(), b"")
    with pytest.raises(MarketDataError, match="CREDENTIAL_MATERIAL_IN_QUOTE_RESPONSE") as captured:
        source(FakeCLI(failure=leaked)).read_completed(["SPY"], AS_OF, tmp_path)
    for artifact in Path(captured.value.provenance["snapshot_dir"]).iterdir():
        assert FAKE_SECRET.encode() not in artifact.read_bytes()


def test_input_bounds_and_future_asof_are_rejected_before_quote_requests(tmp_path):
    with pytest.raises(MarketDataError, match="LOCAL_HOST_REQUIRED"):
        MoomooDesktopSource(host="https://example.invalid")
    with pytest.raises(MarketDataError, match="TIMEZONE_AWARE_AS_OF_REQUIRED"):
        market_state("2024-03-11 09:40:00")
    with pytest.raises(MarketDataError, match="INVALID_SYMBOLS"):
        source().read_completed(["SPY", "SPY"], AS_OF, tmp_path)
    with pytest.raises(MarketDataError, match="FUTURE_AS_OF_NOT_ALLOWED"):
        source().read_completed(["SPY"], AS_OF + pd.Timedelta(seconds=1), tmp_path)


def snapshot_basic(symbol="SPY", *, event=AS_OF-pd.Timedelta(seconds=1), book=True):
    basic = {"security": {"market": 11, "code": symbol}, "is_suspend": False,
             "cur_price": 100.0, "update_time": event.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S"),
             "update_timestamp": event.timestamp()}
    if book:
        basic.update(bid_price=99.95, ask_price=100.05)
    return basic


class SnapshotCLI:
    def __init__(self, records=None, *, error=None, after_request=None):
        self.records = records if records is not None else [snapshot_basic("NVDA"), snapshot_basic("SPY")]
        self.error, self.after_request, self.calls = error, after_request, []

    def __call__(self, argv, *, env, timeout):
        self.calls.append(argv)
        assert argv[1:3] == ["--raw", "get-security-snapshot"]
        assert env["OPENAPI_HOST_APPKEY"] == FAKE_SECRET
        assert all(word.startswith("US.") for word in argv[3:])
        if self.after_request:
            self.after_request()
        if self.error:
            return subprocess.CompletedProcess(argv, 1, b"", self.error.encode())
        payload = {"ret_type": 0, "s2c": {"snapshot_list": [{"basic": basic} for basic in self.records]}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")


def test_snapshot_provider_preserves_event_time_and_side_references_without_subscription(tmp_path):
    fake = SnapshotCLI()
    reader = source(fake)
    provider = make_quote_provider(runtime_dir=tmp_path, source=reader)
    assert not fake.calls
    result = provider(["SPY", "NVDA"], AS_OF)
    assert len(fake.calls) == 1 and set(result) == {"SPY", "NVDA"}
    quote = result["SPY"]
    assert quote["timestamp"] == "2024-03-11T13:45:09Z"  # provider event, not 13:45:10 receipt
    assert quote["price"] == 100 and quote["buy_price"] == 100.05 and quote["sell_price"] == 99.95
    assert quote["reference_kind"] == "snapshot_bid_ask"
    assert not quote["execution_guarantee"] and not quote["bid_ask_timestamp_independently_verified"]
    path = Path(quote["provenance"]["manifest_path"])
    manifest = path.read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == quote["provenance"]["manifest_sha256"]
    assert FAKE_SECRET.encode() not in manifest
    assert json.loads(manifest)["new_subscriptions"] is False


def test_snapshot_missing_book_is_explicit_last_trade_limit_reference(tmp_path):
    quote = source(SnapshotCLI([snapshot_basic(book=False)])).read_quotes(["SPY"], AS_OF, tmp_path)["SPY"]
    assert quote["price"] == quote["buy_price"] == quote["sell_price"] == 100
    assert quote["reference_kind"] == "last_trade_limit_reference" and not quote["execution_guarantee"]


@pytest.mark.parametrize("age", [5, 6, 15*60, -1])
def test_delayed_or_future_snapshot_does_not_forge_now_or_return_partial_batch(tmp_path, age):
    fake = SnapshotCLI([snapshot_basic("SPY"), snapshot_basic("NVDA", event=AS_OF-pd.Timedelta(seconds=age))])
    with pytest.raises(MarketDataError, match="STALE_OR_FUTURE_SNAPSHOT_QUOTE") as captured:
        source(fake).read_quotes(["SPY", "NVDA"], AS_OF, tmp_path)
    assert captured.value.provenance["status"] == "FAILED"
    assert "quotes" not in captured.value.provenance


@pytest.mark.parametrize("change,expected", [("no_time", "INVALID_SNAPSHOT_FIELDS_OR_EVENT_TIME"),
    ("bad_epoch", "INVALID_SNAPSHOT_FIELDS_OR_EVENT_TIME"), ("missing", "INCOMPLETE_SNAPSHOT_QUOTE_BATCH"),
    ("duplicate", "SNAPSHOT_SYMBOL_MISMATCH"), ("wrong_market", "SNAPSHOT_SYMBOL_MISMATCH"),
    ("crossed", "CROSSED_SNAPSHOT_BOOK"), ("suspended", "SUSPENDED_SNAPSHOT_SECURITY")])
def test_snapshot_contract_mismatches_fail_closed(tmp_path, change, expected):
    basic = snapshot_basic()
    records = [basic]
    if change == "no_time":
        del basic["update_time"]
    elif change == "bad_epoch":
        basic["update_timestamp"] += 3600
    elif change == "missing":
        records = []
    elif change == "duplicate":
        records.append(dict(basic))
    elif change == "wrong_market":
        basic["security"]["market"] = 1
    elif change == "crossed":
        basic["bid_price"] = 101
    else:
        basic["is_suspend"] = True
    with pytest.raises(MarketDataError, match=expected):
        source(SnapshotCLI(records)).read_quotes(["SPY"], AS_OF, tmp_path)


def test_quote_freshness_is_rechecked_after_slow_snapshot_response(tmp_path):
    current = [AS_OF]
    fake = SnapshotCLI([snapshot_basic()], after_request=lambda: current.__setitem__(0, AS_OF+pd.Timedelta(seconds=6)))
    reader = MoomooDesktopSource(runner=fake, credential_loader=lambda: FAKE_SECRET, clock=lambda: current[0])
    with pytest.raises(MarketDataError, match="STALE_OR_FUTURE_SNAPSHOT_QUOTE"):
        reader.read_quotes(["SPY"], AS_OF, tmp_path)


def test_quote_holiday_never_reads_key_or_requests_rpc(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("No request or key read on a holiday")
    holiday = pd.Timestamp("2026-11-26T16:00Z")
    reader = MoomooDesktopSource(runner=forbidden, credential_loader=forbidden, clock=lambda: holiday)
    with pytest.raises(MarketDataError, match="MARKET_CLOSED") as captured:
        reader.read_quotes(["SPY"], holiday, tmp_path)
    assert captured.value.provenance["files"] == []


def test_snapshot_permission_denial_is_not_configured_and_does_not_subscribe(tmp_path):
    fake = SnapshotCLI(error="permission denied; appkey="+FAKE_SECRET)
    with pytest.raises(MarketDataError, match="QUOTE_NOT_CONFIGURED") as captured:
        source(fake).read_quotes(["SPY"], AS_OF, tmp_path)
    assert len(fake.calls) == 1 and captured.value.provenance["status"] == "NOT_CONFIGURED"
    assert FAKE_SECRET not in json.dumps(captured.value.provenance)
    assert FAKE_SECRET not in Path(captured.value.provenance["manifest_path"]).read_text(encoding="utf8")
