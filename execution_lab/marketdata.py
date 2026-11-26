"""Local five-minute quote capture for an explicitly started runtime.

Importing opens no connection and reads no credential. Only quote commands are
allowed. No broker/account SDK, account selection, money or order method is
present. Completed provider end labels become UTC bar starts, without filling.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd


COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
CALENDAR_VERSION = "4.11.2"
BAR = pd.Timedelta(minutes=5)
PUBLICATION_LAG_SECONDS = 10
_NY = ZoneInfo("America/New_York")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")
_ALLOWED_COMMANDS = frozenset({"subscribe", "get-kline", "get-security-snapshot"})
_SNAPSHOT_DOC = "https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-market-snapshot.html"


class MarketDataError(ValueError):
    """A safe reason code, plus local audit references; never provider stderr."""

    def __init__(self, code, provenance=None):
        self.code = code
        self.provenance = provenance or {}
        super().__init__(code)


def _utc(value):
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None or pd.isna(stamp):
            raise ValueError()
        return stamp.tz_convert("UTC")
    except (ValueError, TypeError, OverflowError):
        raise MarketDataError("TIMEZONE_AWARE_AS_OF_REQUIRED") from None


def _iso(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _calendar(as_of):
    try:
        if version("exchange-calendars") != CALENDAR_VERSION:
            raise MarketDataError("PINNED_CALENDAR_VERSION_REQUIRED")
        import exchange_calendars as xcals
        day = _utc(as_of).tz_convert(_NY).date()
        return xcals.get_calendar("XNYS", start=str(day - timedelta(days=10)),
                                  end=str(day + timedelta(days=60)))
    except MarketDataError:
        raise
    except (ImportError, PackageNotFoundError):
        raise MarketDataError("CALENDAR_DEPENDENCY_UNAVAILABLE") from None
    except Exception:
        raise MarketDataError("CALENDAR_RANGE_UNAVAILABLE") from None


def _next(as_of, calendar):
    day = as_of.tz_convert(_NY).date()
    for session in calendar.sessions_in_range(str(day), str(day + timedelta(days=45))):
        ends = pd.date_range(calendar.session_open(session) + BAR,
                            calendar.session_close(session), freq="5min")
        captures = ends + pd.Timedelta(seconds=PUBLICATION_LAG_SECONDS)
        future = captures[captures > as_of]
        if len(future):
            return future[0].to_pydatetime()
    raise MarketDataError("NO_NEXT_CAPTURE_IN_CALENDAR")


def next_capture_at(as_of):
    """First strictly future XNYS bar-end + 10s, skipping holidays and closes."""
    stamp = _utc(as_of)
    return _next(stamp, _calendar(stamp))


def market_state(as_of):
    """Pure calendar decision; no credential, quote, SDK or network access.

    On a session date, READY after close permits one final-bar catch-up. The
    caller must deduplicate expected_bar_end before requesting and must not
    treat quote READY as permission to enter a trade outside market hours.
    """
    stamp = _utc(as_of)
    calendar = _calendar(stamp)
    day = stamp.tz_convert(_NY).date()
    state = {"status": "MARKET_CLOSED", "session": str(day), "as_of": stamp.to_pydatetime(),
             "session_open": None, "session_close": None, "expected_bar_end": None,
             "expected_bar_start": None, "capture_at": None,
             "next_capture_at": _next(stamp, calendar), "market_is_open": False,
             "new_entry_allowed": False, "calendar": "XNYS", "calendar_version": CALENDAR_VERSION}
    if not calendar.is_session(str(day)):
        return state
    opening, closing = calendar.session_open(str(day)), calendar.session_close(str(day))
    state.update(session_open=opening.to_pydatetime(), session_close=closing.to_pydatetime(),
                 market_is_open=bool(opening <= stamp < closing))
    ends = pd.date_range(opening + BAR, closing, freq="5min")
    ready = ends[ends + pd.Timedelta(seconds=PUBLICATION_LAG_SECONDS) <= stamp]
    if not len(ready):
        state["status"] = "WAITING_FOR_COMPLETED_BAR"
        return state
    end = ready[-1]
    state.update(status="READY", expected_bar_end=end.to_pydatetime(),
                 expected_bar_start=(end - BAR).to_pydatetime(),
                 capture_at=(end + pd.Timedelta(seconds=PUBLICATION_LAG_SECONDS)).to_pydatetime(),
                 new_entry_allowed=bool(opening <= stamp < closing and end < closing))
    return state


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return _iso(value)
    return value


def _empty():
    return pd.DataFrame({"timestamp": pd.Series([], dtype="datetime64[ns, UTC]"),
                         "symbol": pd.Series([], dtype=str),
                         **{name: pd.Series([], dtype=float) for name in COLUMNS[2:]}})


def _symbols(values):
    if isinstance(values, (str, bytes)):
        raise MarketDataError("INVALID_SYMBOLS")
    try:
        values = list(values)
    except TypeError:
        raise MarketDataError("INVALID_SYMBOLS") from None
    if (not 1 <= len(values) <= 13 or any(not isinstance(value, str) or not _SYMBOL.fullmatch(value) for value in values)
            or len(set(values)) != len(values)):
        raise MarketDataError("INVALID_SYMBOLS")
    return sorted(values)


def _snapshot_quotes(payload, symbols, *, as_of, observed_at, state):
    """Installed Host snake-case contract; event time is never receipt time.

    Host help uses cur_price (the SDK calls it last_price). The official quote
    protocol describes US update_time as Eastern time; optional Unix-second
    update_timestamp must agree. Snapshot bid/ask have no independent event
    time, so their freshness cannot be asserted independently of current price.
    """
    try:
        entries = payload["s2c"]["snapshot_list"]
        if not isinstance(entries, list):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise MarketDataError("INVALID_SNAPSHOT_RESPONSE") from None
    quotes = {}
    for entry in entries:
        try:
            basic = entry["basic"]
            security = basic["security"]
            symbol = security["code"]
            if security["market"] != 11 or symbol not in symbols or symbol in quotes:
                raise MarketDataError("SNAPSHOT_SYMBOL_MISMATCH")
            if basic.get("is_suspend") is True or basic.get("is_suspended") is True:
                raise MarketDataError("SUSPENDED_SNAPSHOT_SECURITY")
            # No naive UTC assumption, no timestamp reconstructed from now.
            wall = pd.Timestamp(basic["update_time"])
            if wall.tzinfo is not None or pd.isna(wall):
                raise ValueError()
            event = wall.tz_localize(_NY, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
            if basic.get("update_timestamp") is not None:
                epoch_value = basic["update_timestamp"]
                if isinstance(epoch_value, bool) or not math.isfinite(float(epoch_value)):
                    raise ValueError()
                epoch = pd.Timestamp(float(epoch_value), unit="s", tz="UTC")
                if abs((event-epoch).total_seconds()) >= 1:
                    raise ValueError()
            if not _utc(state["session_open"]) <= event < _utc(state["session_close"]):
                raise MarketDataError("NON_RTH_SNAPSHOT_EVENT")
            if not 0 <= (as_of-event).total_seconds() < 5 or not 0 <= (observed_at-event).total_seconds() < 5:
                raise MarketDataError("STALE_OR_FUTURE_SNAPSHOT_QUOTE")
            value = basic["cur_price"]
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
                raise MarketDataError("INVALID_SNAPSHOT_PRICE")
            last = float(value)
            book = {}
            for side in ("bid", "ask"):
                candidate = basic.get(side+"_price")
                if isinstance(candidate, bool):
                    raise MarketDataError("INVALID_SNAPSHOT_BOOK")
                if candidate is None or candidate == 0:
                    book[side] = None
                elif not math.isfinite(float(candidate)) or float(candidate) < 0:
                    raise MarketDataError("INVALID_SNAPSHOT_BOOK")
                else:
                    book[side] = float(candidate)
            has_book = book["bid"] is not None and book["ask"] is not None
            if has_book and book["bid"] > book["ask"]:
                raise MarketDataError("CROSSED_SNAPSHOT_BOOK")
            quotes[symbol] = {"price": last, "last_price": last, "timestamp": _iso(event),
                "buy_price": book["ask"] if has_book else last,
                "sell_price": book["bid"] if has_book else last,
                "bid_price": book["bid"], "ask_price": book["ask"],
                "reference_kind": "snapshot_bid_ask" if has_book else "last_trade_limit_reference",
                "timestamp_basis": "provider_current_price_update_time",
                "bid_ask_timestamp_independently_verified": False, "execution_guarantee": False,
                "observed_at": _iso(observed_at), "source": "moomoo_desktop_host_snapshot"}
        except MarketDataError:
            raise
        except (KeyError, ValueError, TypeError, OverflowError):
            raise MarketDataError("INVALID_SNAPSHOT_FIELDS_OR_EVENT_TIME") from None
    if set(quotes) != set(symbols):
        raise MarketDataError("INCOMPLETE_SNAPSHOT_QUOTE_BATCH")
    return quotes


def _write_new(path, contents):
    with path.open("xb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def _default_runner(argv, *, env, timeout):
    return subprocess.run(argv, env=env, timeout=timeout, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _credential():
    """Existing Host AppKey only, in process memory; never on the command line."""
    supplied = os.environ.get("OPENAPI_HOST_APPKEY", "").strip()
    if supplied:
        return supplied
    folder = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not folder:
        raise MarketDataError("HOST_CREDENTIAL_NOT_CONFIGURED")
    protected = Path(folder) / "PcrMarketWatch" / "moomoo-appkey.dpapi"
    if not protected.is_file():
        raise MarketDataError("HOST_CREDENTIAL_NOT_CONFIGURED")
    command = ("$ErrorActionPreference='Stop'; $encoded=Get-Content -LiteralPath "
               "$env:ALPHA_PROTECTED_KEY_PATH -Raw; $value=ConvertTo-SecureString $encoded; "
               "$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($value); "
               "try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr))} "
               "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}")
    env = dict(os.environ, ALPHA_PROTECTED_KEY_PATH=str(protected))
    env["PSModulePath"] = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) /
                              "System32" / "WindowsPowerShell" / "v1.0" / "Modules")
    try:
        response = _default_runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                   env=env, timeout=10)
        key = response.stdout.decode("utf8").strip() if response.returncode == 0 else ""
        if not key:
            raise ValueError()
        return key
    except Exception:
        raise MarketDataError("PROTECTED_HOST_CREDENTIAL_UNAVAILABLE") from None


def _business_error(text):
    ret = re.search(r"\bret_type\s*=\s*(-?\d{1,10})(?!\d)", text)
    err = re.search(r"\berr_code\s*=\s*(-?\d{1,10})(?!\d)", text)
    if re.search(r"subscribe|订阅", text, re.I):
        code = "SUBSCRIPTION_REQUIRED"
    elif re.search(r"appkey|auth|permission|认证|鉴权|权限", text, re.I):
        code = "AUTH_OR_PERMISSION"
    else:
        code = "QUOTE_PROVIDER_REJECTED"
    return {"code": code, "ret_type": int(ret[1]) if ret else None,
            "err_code": int(err[1]) if err else None}


def _normalize(payload, symbol, state, observed_at):
    expected_ends = pd.date_range(_utc(state["session_open"]) + BAR,
                                 _utc(state["expected_bar_end"]), freq="5min")
    allowed_ends = set(expected_ends)
    rows, seen, ignored = [], set(), {"other_session": 0, "not_due_or_future": 0, "non_RTH": 0, "blank": 0}
    try:
        bars = payload["s2c"]["kl_list"]
        if not isinstance(bars, list):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise MarketDataError("INVALID_QUOTE_RESPONSE") from None
    for item in bars:
        try:
            wall = pd.Timestamp(item["time"])
            if wall.tzinfo is not None:
                raise ValueError()
            end = wall.tz_localize("America/New_York", ambiguous="raise", nonexistent="raise").tz_convert("UTC")
            if item.get("timestamp") is not None:
                epoch = float(item["timestamp"])
                epoch = pd.Timestamp(epoch, unit="s" if abs(epoch) < 1e11 else "ms", tz="UTC")
                if abs((epoch - end).total_seconds()) > .001:
                    raise ValueError()
        except Exception:
            raise MarketDataError("INVALID_PROVIDER_BAR_TIME") from None
        if end.tz_convert(_NY).strftime("%Y-%m-%d") != state["session"]:
            ignored["other_session"] += 1
            continue
        if end == _utc(state["session_open"]) and item.get("is_blank") is not True:
            raise MarketDataError("UNVERIFIED_PROVIDER_BAR_LABEL")
        if (_utc(state["session_open"]) < end <= _utc(state["session_close"]) and
                (end.minute % 5 or end.second or end.microsecond or end.nanosecond)):
            raise MarketDataError("QUOTE_INTERVAL_MISMATCH")
        if end > _utc(observed_at) or end > _utc(state["as_of"]) or end > _utc(state["expected_bar_end"]):
            ignored["not_due_or_future"] += 1
            continue
        if end not in allowed_ends:
            ignored["non_RTH"] += 1
            continue
        if item.get("is_blank") is True:
            ignored["blank"] += 1
            continue
        if end in seen:
            raise MarketDataError("DUPLICATE_COMPLETED_BAR")
        seen.add(end)
        record = {"timestamp": end - BAR, "symbol": symbol}
        for column in COLUMNS[2:]:
            value = item.get(column + "_price", item.get(column))
            if value is None or isinstance(value, bool):
                raise MarketDataError("INVALID_COMPLETED_OHLCV")
            try:
                value = float(value)
            except (ValueError, TypeError):
                raise MarketDataError("INVALID_COMPLETED_OHLCV") from None
            if not math.isfinite(value) or value < 0 or column != "volume" and value == 0:
                raise MarketDataError("INVALID_COMPLETED_OHLCV")
            record[column] = value
        if record["high"] < max(record["open"], record["low"], record["close"]) or record["low"] > min(record["open"], record["high"], record["close"]):
            raise MarketDataError("INVALID_COMPLETED_OHLC")
        rows.append(record)
    missing = sorted(allowed_ends - seen)
    diagnostics = {"symbol": symbol, "expected_bars": len(expected_ends), "observed_complete_bars": len(rows),
                   "missing_bars": len(missing), "missing_end_sample": [_iso(value) for value in missing[:5]],
                   "latest_selected_bar_end": _iso(max(seen)) if seen else None, "ignored": ignored}
    if missing:
        error = MarketDataError("STALE_OR_INCOMPLETE_QUOTE_BATCH")
        error.symbol_diagnostic = diagnostics
        raise error
    return sorted(rows, key=lambda value: value["timestamp"]), diagnostics


class MoomooDesktopSource:
    """Read the complete current-session prefix, atomically usable as a batch.

    runner(argv, *, env, timeout) and credential_loader() can be injected for
    deterministic fake-CLI tests. They are never invoked for a closed session.
    """

    def __init__(self, *, cli_path=None, host=None, runner=None, credential_loader=None,
                 clock=None, timeout_seconds=15):
        self.cli_path = str(cli_path or os.environ.get("ALPHA_MOOMOO_CLI") or
                            Path(os.environ.get("APPDATA", "")) / "moomoo" / "2.0" / "OpenAPI" / "moomooapp-cli.exe")
        self.host = host or os.environ.get("OPENAPI_HOST_URL", "http://127.0.0.1:22222")
        parsed = urlsplit(self.host)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise MarketDataError("LOCAL_HOST_REQUIRED")
        self.runner = runner or _default_runner
        self.credential_loader = credential_loader or _credential
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
            raise MarketDataError("INVALID_QUOTE_TIMEOUT")
        self.timeout = float(timeout_seconds)
        self._injected_runner = runner is not None

    def _call(self, command, args, key, directory, provenance, filename):
        if command not in _ALLOWED_COMMANDS:
            raise MarketDataError("QUOTE_COMMAND_NOT_ALLOWED")
        try:
            response = self.runner([self.cli_path, "--raw", command, *args],
                env=dict(os.environ, OPENAPI_HOST_URL=self.host, OPENAPI_HOST_APPKEY=key), timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise MarketDataError("QUOTE_REQUEST_TIMEOUT") from None
        except Exception:
            raise MarketDataError("QUOTE_CLI_UNAVAILABLE") from None
        stdout = response.stdout.encode("utf8") if isinstance(response.stdout, str) else response.stdout or b""
        stderr = response.stderr.encode("utf8") if isinstance(response.stderr, str) else response.stderr or b""
        if len(stdout) > 8_000_000:
            raise MarketDataError("QUOTE_RESPONSE_TOO_LARGE")
        if response.returncode:
            diagnostic = _business_error(stderr[:4096].decode("utf8", errors="replace").replace(key, "[REDACTED]"))
            provenance["provider_error"] = {**diagnostic, "cli_exit_code": response.returncode, "stderr_bytes": len(stderr)}
            raise MarketDataError(diagnostic["code"])
        try:
            payload = json.loads(stdout.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            raise MarketDataError("INVALID_QUOTE_RESPONSE") from None
        if payload.get("ret_type") != 0:
            provenance["provider_error"] = {name: payload.get(name) if type(payload.get(name)) is int else None
                                            for name in ("ret_type", "err_code")}
            code = _business_error(str(payload.get("ret_msg", "")))["code"]
            raise MarketDataError(code)
        if key.encode("utf8") in stdout:
            raise MarketDataError("CREDENTIAL_MATERIAL_IN_QUOTE_RESPONSE")
        provenance["files"].append(_write_new(directory / filename, stdout))
        return payload

    def read_quotes(self, symbols, as_of, runtime_dir):
        """RTH snapshot references, all event ages strictly below five seconds.

        This makes one quote-only snapshot request and never creates a quote
        subscription, upgrades permission, queries an account or sends an order.
        Price/side references are not guaranteed executable quotes. No real
        snapshot response was used to implement this help-confirmed contract;
        actual permission and field acceptance need a later RTH acceptance run.
        """
        symbols = _symbols(symbols)
        stamp, started = _utc(as_of), _utc(self.clock())
        if stamp > started:
            raise MarketDataError("FUTURE_AS_OF_NOT_ALLOWED")
        state = market_state(stamp)
        directory = Path(runtime_dir).expanduser().resolve() / "snapshots" / (
            "quotes-" + started.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex)
        directory.mkdir(parents=True, exist_ok=False)
        provenance = {"status": "REQUESTED", "source": "moomoo_desktop_host_snapshot", "read_only": True,
            "host": self.host, "symbols": symbols, "requested_as_of": _iso(stamp),
            "observed_at_start": _iso(started), "calendar": _json_safe(state), "files": [],
            "snapshot_dir": str(directory), "manifest_path": str(directory / "manifest.json"),
            "event_time_basis": "basic.update_time in America/New_York; optional update_timestamp seconds cross-check",
            "contract_basis": "installed moomooapp-cli get-security-snapshot --help; related official quote protocol",
            "related_protocol_documentation": _SNAPSHOT_DOC,
            "new_subscriptions": False, "account_queries": False, "order_methods": False,
            "execution_guarantee": False, "bid_ask_timestamp_independently_verified": False}
        failure, quotes = None, None
        try:
            if not state["market_is_open"]:
                raise MarketDataError("MARKET_CLOSED")
            if not self._injected_runner and not Path(self.cli_path).is_file():
                raise MarketDataError("QUOTE_NOT_CONFIGURED")
            key = self.credential_loader()
            if not isinstance(key, str) or not key.strip():
                raise MarketDataError("QUOTE_NOT_CONFIGURED")
            payload = self._call("get-security-snapshot", ["US."+symbol for symbol in symbols],
                                 key, directory, provenance, "snapshot-raw.json")
            key = None
            observed = _utc(self.clock())
            if observed < started:
                raise MarketDataError("CLOCK_REGRESSION_DURING_QUOTE")
            if not market_state(observed)["market_is_open"]:
                raise MarketDataError("MARKET_CLOSED_DURING_QUOTE")
            quotes = _snapshot_quotes(payload, symbols, as_of=stamp, observed_at=observed, state=state)
            provenance.update(status="READY", quotes=quotes, as_of=_iso(min(_utc(value["timestamp"]) for value in quotes.values())),
                              oldest_quote_age_seconds=max((observed-_utc(value["timestamp"])).total_seconds()
                                                           for value in quotes.values()))
        except MarketDataError as error:
            # The adapter does not request new permission or purchase data when
            # the existing account cannot use this command.
            code = ("QUOTE_NOT_CONFIGURED" if error.code in {"AUTH_OR_PERMISSION", "SUBSCRIPTION_REQUIRED",
                "HOST_CREDENTIAL_NOT_CONFIGURED", "PROTECTED_HOST_CREDENTIAL_UNAVAILABLE"} else error.code)
            failure = MarketDataError(code)
            provenance.update(status="NOT_CONFIGURED" if code == "QUOTE_NOT_CONFIGURED" else "FAILED",
                              error_code=code)
        except Exception:
            failure = MarketDataError("QUOTE_CAPTURE_FAILED")
            provenance.update(status="FAILED", error_code=failure.code)
        provenance["observed_at_end"] = _iso(self.clock())
        document = json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2).encode("utf8")
        manifest = _write_new(directory / "manifest.json", document)
        if failure:
            raise MarketDataError(failure.code, provenance) from None
        for quote in quotes.values():
            quote["provenance"] = {"manifest_path": str(directory / "manifest.json"),
                                   "manifest_sha256": manifest["sha256"], "raw_sha256": provenance["files"][0]["sha256"]}
        return quotes

    def read_completed(self, symbols, as_of, runtime_dir):
        symbols = _symbols(symbols)
        stamp, started = _utc(as_of), _utc(self.clock())
        if stamp > started:
            raise MarketDataError("FUTURE_AS_OF_NOT_ALLOWED")
        state = market_state(stamp)
        directory = Path(runtime_dir).expanduser().resolve() / "snapshots" / (
            "market-" + started.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex)
        directory.mkdir(parents=True, exist_ok=False)
        provenance = {"status": state["status"], "source": "moomoo_desktop_host", "read_only": True,
            "host": self.host, "symbols": symbols, "requested_as_of": _iso(stamp),
            "observed_at_start": _iso(started), "calendar": _json_safe(state), "files": [], "coverage": [],
            "snapshot_dir": str(directory), "manifest_path": str(directory / "manifest.json"),
            "normalization": {"provider_timestamp_label": "bar_end", "conversion": "subtract_5_minutes",
                "verification_source": "Observed Host 1m-to-5m right-end OHLC alignment; native five-minute volume retained"},
            "no_fill": True, "account_queries": False, "order_methods": False}
        frame = _empty()
        failure = None
        try:
            if state["status"] == "READY":
                if not self._injected_runner and not Path(self.cli_path).is_file():
                    raise MarketDataError("QUOTE_CLI_UNAVAILABLE")
                key = self.credential_loader()
                if not isinstance(key, str) or not key.strip():
                    raise MarketDataError("HOST_CREDENTIAL_NOT_CONFIGURED")
                self._call("subscribe", ["--sub-type-list", "7", "--is-sub-or-un-sub", "--no-is-reg-or-un-reg-push",
                    "--no-extended-time", "--session", "rth", *["US." + symbol for symbol in symbols]],
                    key, directory, provenance, "subscribe-response.json")
                records = []
                for symbol in symbols:
                    payload = self._call("get-kline", ["--rehab-type", "0", "--kl-type", "6", "--req-num", "1000", "--security", "US." + symbol],
                        key, directory, provenance, symbol + "-raw.json")
                    if payload.get("s2c", {}).get("security", {}).get("code", symbol) != symbol:
                        raise MarketDataError("QUOTE_SYMBOL_MISMATCH")
                    rows, diagnostic = _normalize(payload, symbol, state, _utc(self.clock()))
                    records.extend(rows)
                    provenance["coverage"].append(diagnostic)
                key = None
                frame = pd.DataFrame(records, columns=COLUMNS).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
                csv = frame.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode("utf8")
                provenance["normalized_csv"] = _write_new(directory / "bars.csv", csv)
                provenance.update(status="READY", as_of=_iso(state["expected_bar_end"]),
                    latest_bar_start=_iso(state["expected_bar_start"]), rows=len(frame),
                    market_is_open=state["market_is_open"], new_entry_allowed=state["new_entry_allowed"])
        except MarketDataError as error:
            failure = error
            provenance.update(status="FAILED", error_code=error.code)
            if hasattr(error, "symbol_diagnostic"):
                provenance["coverage"].append(error.symbol_diagnostic)
        except Exception:
            failure = MarketDataError("QUOTE_CAPTURE_FAILED")
            provenance.update(status="FAILED", error_code=failure.code)
        provenance["observed_at_end"] = _iso(self.clock())
        document = json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2).encode("utf8")
        _write_new(directory / "manifest.json", document)
        if failure is not None:
            raise MarketDataError(failure.code, provenance) from None
        return frame, provenance


def make_quote_provider(*, runtime_dir, source=None):
    """Runtime callable (symbols, as_of) -> quote map; construction is offline."""
    reader = source if source is not None else MoomooDesktopSource()
    if runtime_dir is None or not hasattr(reader, "read_quotes"):
        raise MarketDataError("QUOTE_NOT_CONFIGURED")

    def quote_provider(symbols, as_of):
        return reader.read_quotes(symbols, as_of, runtime_dir)

    return quote_provider
