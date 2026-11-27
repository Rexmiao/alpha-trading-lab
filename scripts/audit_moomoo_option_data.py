"""Bounded foreground audit of the existing desktop quote route, not inventory inference.

Successful quote responses stay under ignored state/. No account, order, REST
credential, scheduler, upload or numerical dealer-inventory estimate exists here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = frozenset({"subscribe", "get-basic-qot", "get-option-expiration-date",
                     "get-option-chain", "get-security-snapshot", "get-ticker", "get-order-book"})
SYMBOLS = frozenset({"SPY", "QQQ", "NVDA"})
MAX_REQUESTS = 30
MAX_RESPONSE = 8_000_000


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def local_host(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("LOOPBACK_HOST_REQUIRED")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("INVALID_HOST_PORT") from None
    if port is not None and not 1024 <= port <= 65535:
        raise ValueError("INVALID_HOST_PORT")
    return value


def schema_paths(value, prefix=""):
    """Record observed paths/types, never invent absent optional fields."""
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.setdefault(path, set()).add(type(child).__name__)
            for name, kinds in schema_paths(child, path).items():
                result.setdefault(name, set()).update(kinds)
    elif isinstance(value, list):
        for child in value:
            for name, kinds in schema_paths(child, prefix + "[]").items():
                result.setdefault(name, set()).update(kinds)
    return result


def safe_failure(text):
    """Keep only allowlisted reason classes and numeric protocol error codes."""
    value = str(text)
    code = "PROVIDER_REJECTED"
    for pattern, label in [
        (r"quota|rate.limit|频率|额度", "QUOTA_OR_RATE_LIMIT"),
        (r"app.?key|auth|permission|认证|鉴权|权限", "AUTH_OR_PERMISSION"),
        (r"unsupported|not.supported|不支持", "METHOD_UNSUPPORTED"),
        (r"subscribe|订阅", "SUBSCRIPTION_REQUIRED"),
        (r"connection refused|cannot reach|无法连接|连接失败", "LOCAL_SERVICE_UNAVAILABLE"),
    ]:
        if re.search(pattern, value, re.I):
            code = label
            break
    numeric = {}
    for name in ("ret_type", "err_code"):
        match = re.search(rf"\b{name}\s*[=:]\s*(-?\d{{1,10}})(?!\d)", value)
        numeric[name] = int(match[1]) if match else None
    return {"code": code, **numeric}


def quote_envelope(stdout, stderr, returncode):
    """Accept a quote object or a sanitized failure, including valid non-object JSON."""
    try:
        payload = json.loads(stdout.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        return None, safe_failure(stderr.decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        return None, {"code": "INVALID_RESPONSE_SHAPE", "ret_type": None, "err_code": None}
    if returncode or payload.get("ret_type") != 0:
        failure = safe_failure(str(payload.get("ret_msg", "")))
        for name in ("ret_type", "err_code"):
            if isinstance(payload.get(name), int) and not isinstance(payload[name], bool):
                failure[name] = payload[name]
        return None, failure
    if not isinstance(payload.get("s2c"), dict):
        return None, {"code": "INVALID_RESPONSE_SHAPE", "ret_type": 0, "err_code": None}
    return payload["s2c"], None


def numeric_presence(rows):
    """Presence/finite/zero counts are not independent validity verification."""
    from math import isfinite
    result = {}
    names = ("open_interest", "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
             "contract_size", "contract_multiplier")
    for name in names:
        values = [row.get("option_ex_data", {}).get(name) for row in rows]
        finite = [value for value in values if isinstance(value, (int, float))
                  and not isinstance(value, bool) and isfinite(value)]
        result[name] = {"present": sum(name in row.get("option_ex_data", {}) for row in rows),
                        "nonnull": sum(value is not None for value in values), "finite": len(finite),
                        "zero": sum(value == 0 for value in finite)}
    return {"rows": len(rows), "fields": result, "independent_validity_verified": False}


def vendor_flow_summary(rows):
    """An observed vendor aggressor proxy; no conversion to dealer side or inventory."""
    from math import isfinite
    counts, volumes = Counter(), Counter()
    unknown_size = 0
    for row in rows:
        direction = row.get("dir") if row.get("dir") in {"BUY", "SELL", "NEUTRAL"} else "UNKNOWN"
        counts[direction] += 1
        size = row.get("volume")
        if not isinstance(size, (int, float)) or isinstance(size, bool) or not isfinite(size) or size < 0:
            unknown_size += 1
        else:
            volumes[direction] += size
    return {"status": "VENDOR_AGGRESSOR_PROXY_ONLY", "direction_counts": dict(counts),
            "volume_native": dict(volumes), "unknown_size_rows": unknown_size,
            "signed_vendor_pressure_native": None if unknown_size else volumes["BUY"] - volumes["SELL"],
            "neutral_or_unknown_volume_excluded": volumes["NEUTRAL"] + volumes["UNKNOWN"],
            "volume_unit_independently_verified": False, "complete_tape_verified": False,
            "q": None, "mm_side_probability": None, "inventory_change_observed": None,
            "calibration_status": "NO_PARTICIPANT_LABELS"}


def clock_diagnostics(rows, received_at):
    """Flag vendor/local-clock disagreement; never shift or repair source times."""
    from math import isfinite
    local = datetime.fromisoformat(received_at).timestamp()
    differences = []
    missing = 0
    for row in rows:
        stamp = row.get("timestamp")
        # Installed CLI help documents this field as Unix seconds. Retain raw
        # values; unknown units or malformed clocks are not silently converted.
        if (not isinstance(stamp, (float, int)) or isinstance(stamp, bool)
                or not isfinite(stamp) or not 100_000_000 <= stamp < 100_000_000_000):
            missing += 1
        else:
            differences.append((stamp - local) * 1000)
    return {"vendor_timestamp_unit_used": "unix_seconds_from_installed_cli_contract",
            "missing_or_invalid_timestamp_rows": missing,
            "provider_later_than_local_receipt_rows": sum(delta > 0 for delta in differences),
            "max_provider_minus_receipt_ms": max(differences, default=None),
            "clock_alignment_verified": False, "timestamps_repaired": False}


def credential():
    supplied = os.environ.get("OPENAPI_HOST_APPKEY", "").strip()
    if supplied:
        return supplied
    folder = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not folder:
        raise ValueError("HOST_CREDENTIAL_NOT_CONFIGURED")
    protected = Path(folder) / "PcrMarketWatch" / "moomoo-appkey.dpapi"
    if not protected.is_file():
        raise ValueError("HOST_CREDENTIAL_NOT_CONFIGURED")
    command = ("$ErrorActionPreference='Stop'; $encoded=Get-Content -LiteralPath "
               "$env:ALPHA_PROTECTED_KEY_PATH -Raw; $value=ConvertTo-SecureString $encoded; "
               "$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($value); "
               "try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr))} "
               "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}")
    environment = dict(os.environ, ALPHA_PROTECTED_KEY_PATH=str(protected))
    environment["PSModulePath"] = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) /
                                        "System32/WindowsPowerShell/v1.0/Modules")
    try:
        reply = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                               env=environment, capture_output=True, timeout=10,
                               stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        key = reply.stdout.decode("utf-8-sig").strip() if reply.returncode == 0 else ""
        if not key:
            raise ValueError()
        return key
    except Exception:
        raise ValueError("PROTECTED_HOST_CREDENTIAL_UNAVAILABLE") from None


def choose_pairs(data, spot, *, per_expiry=2):
    """One nearby complete Call/Put pair; selection is explicitly partial."""
    candidates = []
    for chain in data.get("option_chain", []):
        for pair in chain.get("option", []):
            call, put = pair.get("call"), pair.get("put")
            if not isinstance(call, dict) or not isinstance(put, dict):
                continue
            call_code = call.get("basic", {}).get("security", {}).get("code")
            put_code = put.get("basic", {}).get("security", {}).get("code")
            strike = call.get("option_ex_data", {}).get("strike_price")
            if (not call_code or not put_code or not isinstance(strike, (int, float))
                    or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,40}", call_code)
                    or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,40}", put_code)):
                continue
            candidates.append((strike, "US." + call_code, "US." + put_code))
    if not candidates:
        return [], "NO_COMPLETE_PAIR"
    if isinstance(spot, (int, float)) and spot > 0:
        candidates.sort(key=lambda row: (abs(row[0] - spot), row[0]))
        method = "nearest_strike_to_observed_underlying_quote"
    else:
        candidates.sort()
        candidates = [candidates[len(candidates) // 2]]
        method = "middle_available_strike_spot_unavailable"
    return list(candidates[0][1:])[:per_expiry], method


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"])
    parser.add_argument("--probe", action="store_true", help="Check configuration; no market-data requests.")
    args = parser.parse_args(argv)
    if len(args.symbols) > 2 or len(set(args.symbols)) != len(args.symbols) or not set(args.symbols) <= SYMBOLS:
        parser.error("Choose one or two of SPY, QQQ, NVDA; this is a bounded field audit.")
    host = local_host(os.environ.get("OPENAPI_HOST_URL", "http://127.0.0.1:22222"))
    cli = Path(os.environ.get("ALPHA_MOOMOO_CLI", str(Path(os.environ.get("APPDATA", "")) /
                                                   "moomoo/2.0/OpenAPI/moomooapp-cli.exe")))
    try:
        key = credential()
    except ValueError as exc:
        print(json.dumps({"status": "NOT_CONFIGURED", "reason": str(exc), "read_only": True}))
        return 2
    if args.probe:
        print(json.dumps({"configured": bool(key), "cli_available": cli.is_file(), "read_only": True}))
        return 0
    if not cli.is_file():
        print(json.dumps({"status": "CLI_UNAVAILABLE", "read_only": True}))
        return 2
    started = utc_now()
    folder = ROOT / "state" / "dealer-inventory-audit" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, OPENAPI_HOST_URL=host, OPENAPI_HOST_APPKEY=key)
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    report = {"audit_version": 2, "started_at": started, "finished_at": None,
              "scope": "foreground desktop quotes only; no accounts, trades, uploads or background task",
              "underlyings": args.symbols, "read_only": True, "requests": [], "selection": [],
              "raw_redistribution": False, "oi_effective_at": None, "oi_publication_at": None,
              "inventory_status": "NOT_IDENTIFIABLE", "calibrated_probability": None,
              "historical_complete_chain_verified": False,
              "trade_quote_synchronization_verified": False,
              "zero_field_values_not_assumed_valid": True,
              "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    last_call = 0.0

    def request(label, command, flags):
        nonlocal last_call
        if command not in ALLOWED or len(report["requests"]) >= MAX_REQUESTS:
            raise ValueError("AUDIT_COMMAND_OR_BUDGET_REJECTED")
        time.sleep(max(0.0, .8 - (time.monotonic() - last_call)))
        last_call = time.monotonic()
        record = {"label": label, "command": command, "requested_at": utc_now(),
                  "received_at": None, "status": "FAILED"}
        report["requests"].append(record)
        try:
            response = subprocess.run([str(cli), "--raw", command, *flags], env=environment,
                                      capture_output=True, timeout=15, stdin=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            record["received_at"] = utc_now()
            if len(response.stdout) + len(response.stderr) > MAX_RESPONSE:
                raise ValueError("RESPONSE_TOO_LARGE")
            data, failure = quote_envelope(response.stdout, response.stderr, response.returncode)
            if failure:
                record.update(failure)
                return None
            expected_lists = {"get-option-expiration-date": ("date_list",),
                              "get-option-chain": ("option_chain",),
                              "get-basic-qot": ("basic_qot_list",),
                              "get-security-snapshot": ("snapshot_list",),
                              "get-ticker": ("ticker_list",),
                              "get-order-book": ("order_book_bid_list", "order_book_ask_list")}
            for field in expected_lists.get(command, ()):
                if not isinstance(data.get(field), list) or any(not isinstance(row, dict) for row in data[field]):
                    raise ValueError("INVALID_QUOTE_LIST_SHAPE")
            raw = json.dumps({"ret_type": 0, "s2c": data}, ensure_ascii=False).encode("utf-8")
            filename = label + ".json"
            (folder / filename).write_bytes(raw)
            record.update(status="OBSERVED", file=filename, bytes=len(raw),
                          sha256=hashlib.sha256(raw).hexdigest(), available_at=record["received_at"],
                          archive_format="reserialized_quote_s2c_json", original_stdout_preserved=False,
                          schema={name: sorted(kinds) for name, kinds in sorted(schema_paths(data).items())})
            # Preserve exact successful CLI bytes separately only for the
            # expected quote-only envelope with an empty message. Errors and
            # unknown top-level metadata are never written as raw output.
            original = json.loads(response.stdout.decode("utf-8-sig"))
            message = original.get("ret_msg")
            if set(original) <= {"ret_type", "ret_msg", "err_code", "s2c"} and (message is None or message == ""):
                raw_name = label + ".stdout.json"
                (folder / raw_name).write_bytes(response.stdout)
                record.update(original_stdout_preserved=True, original_stdout_file=raw_name,
                              original_stdout_sha256=hashlib.sha256(response.stdout).hexdigest())
            for name in ("date_list", "option_chain", "basic_qot_list", "snapshot_list", "ticker_list"):
                if isinstance(data.get(name), list):
                    record[name + "_count"] = len(data[name])
            if command == "get-basic-qot":
                record["option_numeric_presence"] = numeric_presence(data.get("basic_qot_list", []))
            if isinstance(data.get("ticker_list"), list):
                rows = data["ticker_list"]
                record["ticker_fields_present_counts"] = dict(Counter(k for row in rows for k in row))
                record["vendor_direction_counts"] = dict(Counter(str(row.get("dir")) for row in rows))
                record["provider_time_raw_min"] = min((r["time"] for r in rows if isinstance(r.get("time"), str)), default=None)
                record["provider_time_raw_max"] = max((r["time"] for r in rows if isinstance(r.get("time"), str)), default=None)
                sequences = [row.get("sequence") for row in rows if row.get("sequence") is not None]
                record["duplicate_sequences"] = len(sequences) - len(set(sequences))
                record["complete_tape_verified"] = False
                record["direction_is_not_participant_identity"] = True
                record["vendor_flow_proxy"] = vendor_flow_summary(rows)
                record["clock_diagnostics"] = clock_diagnostics(rows, record["received_at"])
            return data
        except subprocess.TimeoutExpired:
            record.update(status="FAILED", code="BOUNDED_REQUEST_TIMEOUT", received_at=utc_now())
            return None
        except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
            record.update(status="FAILED", code="AUDIT_RESPONSE_OR_TRANSPORT_FAILED", error_class=type(exc).__name__, received_at=utc_now())
            return None
        finally:
            (folder / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"label": label, "status": record["status"], "code": record.get("code")}), flush=True)

    underlying_codes = ["US." + symbol for symbol in args.symbols]
    subscription_flags = ["--sub-type-list", "basic", "--is-sub-or-un-sub", "--no-is-reg-or-un-reg-push",
                          "--no-extended-time", "--session", "rth"]
    request("underlying-subscribe", "subscribe", subscription_flags + underlying_codes)
    underlying = request("underlying-quotes", "get-basic-qot", underlying_codes) or {}
    spots = {r.get("security", {}).get("code"): r.get("cur_price") for r in underlying.get("basic_qot_list", [])}
    chosen = []
    ticker_contracts = []
    for symbol in args.symbols:
        expiries = request(symbol + "-expirations", "get-option-expiration-date", ["--owner", "US." + symbol]) or {}
        dates = sorted({r["strike_time"] for r in expiries.get("date_list", [])
                        if isinstance(r.get("strike_time"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["strike_time"])
                        and r["strike_time"] >= today})[:2]
        for index, expiry in enumerate(dates):
            data = request(f"{symbol}-chain-{expiry}", "get-option-chain",
                           ["--begin-time", expiry, "--end-time", expiry, "--owner", "US." + symbol])
            if data:
                codes, method = choose_pairs(data, spots.get(symbol))
                chosen.extend(codes)
                if index == 0:
                    ticker_contracts.extend(codes)
                report["selection"].append({"underlying": symbol, "expiry": expiry, "method": method,
                                            "dynamic_contract_count": len(codes), "complete_chain_sample": False})
    if chosen:
        request("option-subscribe", "subscribe", subscription_flags + chosen)
        request("option-quotes-before", "get-basic-qot", chosen)
        request("option-snapshot-small", "get-security-snapshot", chosen[:2])
    if ticker_contracts:
        types = subscription_flags.copy()
        types[1] = "ticker,order_book"
        request("option-ticker-book-subscribe", "subscribe", types + ticker_contracts)
        for index, contract in enumerate(ticker_contracts):
            request(f"contract-{index}-book-before", "get-order-book", ["--security", contract, "--num", "1"])
            request(f"contract-{index}-ticks", "get-ticker", ["--security", contract, "--max-ret-num", "100"])
            request(f"contract-{index}-book-after", "get-order-book", ["--security", contract, "--num", "1"])
    if chosen:
        request("option-quotes-after", "get-basic-qot", chosen)
    report.update(finished_at=utc_now(), dynamic_contracts_requested=len(chosen), ticker_contracts_requested=len(ticker_contracts))
    report["candidate_identity_or_open_close_paths"] = sorted({path for record in report["requests"]
        for path in record.get("schema", {}) if re.search(
            r"capacity|participant|is_?mm|origin|position_?effect|open_?close|complex_?exec|buy_?to_?open|sell_?to_?open", path, re.I)})
    report["candidate_identity_field_semantics_verified"] = False
    # Finding a similarly named field is not sufficient to enable inference.
    report["inventory_status"] = "NOT_IDENTIFIABLE"
    (folder / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit_relative_path": str(folder.relative_to(ROOT) / "audit.json"),
                      "requests": len(report["requests"]), "observed": sum(r["status"] == "OBSERVED" for r in report["requests"]),
                      "inventory_status": report["inventory_status"]}), flush=True)
    return 0 if any(r["status"] == "OBSERVED" and r["command"] != "subscribe" for r in report["requests"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
