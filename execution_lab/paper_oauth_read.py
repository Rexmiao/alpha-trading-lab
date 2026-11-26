"""Experimental, independent OAuth/US-paper read core; no login or I/O on import.

Only explicit register/exchange methods POST to OAuth protocol endpoints. The
business transport permits three GET resources in /sim-trade, never orders or
REAL routes. Nothing imports a write adapter, stores tokens, opens a callback
server or touches a runtime journal. Callers own private token lifecycle.

Official schemas: https://open.moomoo.com/zh-cn/api/overview/getting-started
and /api/sim-trade/{account-list,cash-info,position-list}. The docs omit scope
from the authorize parameter table; requesting trade:read in registration and
authorization is a constrained experiment, not proof the server honors it.
Registration metadata is never treated as a granted token scope.

This experiment pins the REST issuer/API origin to webapi.moomoo.com. The MCP
advertised issuer mcp.moomoo.com is not supported; shared endpoint hosts do not
prove issuer or callback compatibility. No flow has been activated or verified.
Position parsing distinguishes the HTML string-enum variant from the current
sim-trade schema in https://open.moomoo.com/openapi.yaml (integer enums/signed
short quantities). Neither variant imports live-trade schemas or order logic.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ISSUER = "https://webapi.moomoo.com"
ACCOUNTS_PATH = "/api/v1.0/sim-trade/accounts"
REQUESTED_SCOPE = "trade:read"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
AUTHORIZATION_ATTEMPT_TTL_SECONDS = 600
_ALLOWED_SCOPES = frozenset({"trade:read", "quote:read"})
_IDENTIFIER = re.compile(r"[0-9]{1,40}\Z")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")


class OAuthReadError(ValueError):
    """Only a static safe code: no raw response, URL, token or account ID."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise OAuthReadError(code) from None


def _now(clock):
    try:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            _fail("INVALID_CLOCK")
        return value.astimezone(timezone.utc)
    except OAuthReadError:
        raise
    except Exception:
        _fail("INVALID_CLOCK")


def _visible(value, code, maximum=4096):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or any(not 33 <= ord(char) <= 126 for char in value)):
        _fail(code)
    return value


def validate_callback_uri(uri):
    """Exactly http://127.0.0.1|localhost:<explicit port>/callback."""
    try:
        parts = urlsplit(uri)
        valid = (isinstance(uri, str) and parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
            and parts.port is not None and 1 <= parts.port <= 65535 and parts.port not in {11111, 22222}
            and parts.netloc == f"{parts.hostname}:{parts.port}" and parts.path == "/callback"
            and not parts.query and not parts.fragment and parts.username is None and parts.password is None)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        _fail("INVALID_CALLBACK_URI")
    return uri


def pkce_challenge(verifier):
    if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        _fail("INVALID_PKCE_VERIFIER")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


@dataclass(repr=False)
class OAuthAttempt:
    callback_uri: str
    state: str = field(repr=False)
    verifier: str = field(repr=False)
    created_at: datetime
    used: bool = False
    _lock: object = field(default_factory=threading.Lock, repr=False)

    def __repr__(self):
        return f"OAuthAttempt(used={self.used}; private state/verifier omitted)"


def new_pkce(callback_uri, *, clock=None):
    return OAuthAttempt(validate_callback_uri(callback_uri), secrets.token_urlsafe(32), secrets.token_urlsafe(48),
                        _now(clock or (lambda: datetime.now(timezone.utc))))


def _check_attempt_time(attempt, clock):
    if (not isinstance(attempt.created_at, datetime) or attempt.created_at.tzinfo is None
            or attempt.created_at.utcoffset() is None):
        _fail("INVALID_AUTHORIZATION_TIME")
    age = (_now(clock) - attempt.created_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= AUTHORIZATION_ATTEMPT_TTL_SECONDS:
        _fail("AUTHORIZATION_ATTEMPT_EXPIRED_OR_FUTURE")


def authorization_url(client_id, attempt, *, clock=None):
    _visible(client_id, "INVALID_CLIENT_ID", 256)
    if not isinstance(attempt, OAuthAttempt) or attempt.used:
        _fail("INVALID_AUTHORIZATION_ATTEMPT")
    _check_attempt_time(attempt, clock or (lambda: datetime.now(timezone.utc)))
    validate_callback_uri(attempt.callback_uri)
    _visible(attempt.state, "INVALID_AUTHORIZATION_ATTEMPT", 128)
    return ISSUER + "/oauth2/authorize/confirm?" + urlencode({"client_id": client_id,
        "code_challenge": pkce_challenge(attempt.verifier), "code_challenge_method": "S256",
        "redirect_uri": attempt.callback_uri, "response_type": "code", "state": attempt.state,
        "scope": REQUESTED_SCOPE})


def _scopes(value):
    if not isinstance(value, str) or not value or len(value) > 256 or re.search(r"[^\x21-\x7e ]", value):
        _fail("SCOPE_MISSING_OR_INVALID")
    scopes = value.split(" ")
    if (any(not scope for scope in scopes) or len(set(scopes)) != len(scopes)
            or REQUESTED_SCOPE not in scopes or not set(scopes) <= _ALLOWED_SCOPES):
        _fail("SCOPE_REJECTED")
    return tuple(sorted(scopes))


@dataclass(frozen=True)
class ReadToken:
    access_token: str = field(repr=False)
    scopes: tuple[str, ...]
    expires_at: datetime

    def __post_init__(self):
        _visible(self.access_token, "INVALID_ACCESS_TOKEN")
        if not isinstance(self.scopes, tuple) or any(not isinstance(value, str) for value in self.scopes):
            _fail("SCOPE_REJECTED")
        _scopes(" ".join(self.scopes))
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            _fail("INVALID_TOKEN_EXPIRY")


def validate_token_response(response, *, clock=None):
    if (not isinstance(response, dict) or not isinstance(response.get("token_type"), str)
            or response["token_type"].casefold() != "bearer"):
        _fail("INVALID_TOKEN_RESPONSE")
    scopes = _scopes(response.get("scope"))
    expiry = response.get("expires_in")
    if type(expiry) is not int or not 0 < expiry <= 31 * 86400:
        _fail("INVALID_TOKEN_EXPIRY")
    return ReadToken(_visible(response.get("access_token"), "INVALID_ACCESS_TOKEN"), scopes,
                     _now(clock or (lambda: datetime.now(timezone.utc))) + timedelta(seconds=expiry))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("INVALID_RESPONSE")
        result[key] = value
    return result


class _JsonHttp:
    def __init__(self, *, opener=None, timeout=15):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 15:
            _fail("INVALID_TIMEOUT")
        self.timeout = timeout
        self._open = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect()).open
        if not callable(self._open):
            _fail("INVALID_OPENER")

    def send(self, method, path, *, query=None, body=None, content_type=None, token=None):
        oauth = method == "POST" and path in {"/oauth2/register", "/oauth2/token"} and not query and token is None
        business = method == "GET" and body is None and token is not None and (
            path == ACCOUNTS_PATH or isinstance(path, str) and re.fullmatch(
                r"/api/v1\.0/sim-trade/[0-9]{1,40}/(?:cash-info|positions)", path))
        if not oauth and not business:
            _fail("HTTP_ROUTE_REFUSED")
        target = ISSUER + path + ("?" + urlencode(query) if query else "")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "AlphaLab-Paper-Read/1"}
        if token is not None:
            headers["Authorization"] = "Bearer " + _visible(token, "INVALID_ACCESS_TOKEN")
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(target, data=body, method=method, headers=headers)
        deadline = time.monotonic() + self.timeout
        try:
            with self._open(request, timeout=self.timeout) as response:
                if getattr(response, "geturl", lambda: target)() != target:
                    _fail("REDIRECT_REFUSED")
                status = getattr(response, "status", 200)
                if status != 200:
                    raise HTTPError(target, status, "", {}, None)
                length = getattr(response, "headers", {}).get("Content-Length")
                if length is not None:
                    try:
                        valid_length = 0 <= int(length) <= MAX_RESPONSE_BYTES
                    except (ValueError, TypeError):
                        _fail("INVALID_RESPONSE")
                    if not valid_length:
                        _fail("RESPONSE_SIZE_LIMIT")
                raw = bytearray()
                read = getattr(response, "read1", response.read)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _fail("REQUEST_TIMEOUT_NO_RETRY")
                    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    chunk = read(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
                    if not isinstance(chunk, bytes):
                        _fail("INVALID_RESPONSE")
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        _fail("RESPONSE_SIZE_LIMIT")
        except OAuthReadError:
            raise
        except HTTPError as error:
            code = "AUTH_REQUIRED" if error.code in {401, 403, 439} else "REDIRECT_REFUSED" if 300 <= error.code < 400 else "HTTP_ERROR_NO_RETRY"
            error.close()
            _fail(code)
        except (TimeoutError, URLError, OSError):
            _fail("REQUEST_FAILED_NO_RETRY")
        except Exception:
            _fail("INVALID_RESPONSE")
        try:
            result = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_unique_object,
                                parse_constant=lambda value: _fail("INVALID_RESPONSE"))
        except OAuthReadError:
            raise
        except (ValueError, UnicodeError, RecursionError):
            _fail("INVALID_RESPONSE")
        if not isinstance(result, dict):
            _fail("INVALID_RESPONSE")
        return result


@dataclass(frozen=True)
class Registration:
    client_id: str = field(repr=False)
    public_summary: dict


class OAuthReadClient:
    def __init__(self, *, opener=None, clock=None, timeout=15):
        self._http = _JsonHttp(opener=opener, timeout=timeout)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def register(self, callback_uri, client_name="alpha_trading_lab_paper_read"):
        callback_uri = validate_callback_uri(callback_uri)
        if not isinstance(client_name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", client_name):
            _fail("INVALID_CLIENT_NAME")
        body = {"redirect_uris": [callback_uri], "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code"], "response_types": ["code"],
                "client_name": client_name, "scope": REQUESTED_SCOPE}
        result = self._http.send("POST", "/oauth2/register", body=json.dumps(body, separators=(",", ":")).encode(),
                                 content_type="application/json")
        client_id = _visible(result.get("client_id"), "INVALID_REGISTRATION_RESPONSE", 256)
        # Drop registration_access_token and all metadata carrying credentials.
        return Registration(client_id, {"status": "CLIENT_REGISTERED_NOT_AUTHORIZED", "requested_scope": REQUESTED_SCOPE,
            "registration_scope_is_grant": False, "server_minimal_scope_support_verified": False})

    def exchange(self, client_id, attempt, callback_url):
        _visible(client_id, "INVALID_CLIENT_ID", 256)
        if not isinstance(attempt, OAuthAttempt):
            _fail("INVALID_AUTHORIZATION_ATTEMPT")
        _check_attempt_time(attempt, self._clock)
        expected = urlsplit(validate_callback_uri(attempt.callback_uri))
        try:
            actual = urlsplit(callback_url)
            if ((actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path)
                    or actual.fragment or re.search(r"%(?![0-9A-Fa-f]{2})", actual.query)):
                _fail("CALLBACK_MISMATCH")
            pairs = parse_qsl(actual.query, keep_blank_values=True, strict_parsing=True, max_num_fields=10)
            params = dict(pairs)
            if len(params) != len(pairs) or not set(params) <= {"state", "code", "error", "error_description", "error_uri", "iss"}:
                _fail("INVALID_CALLBACK_PARAMETERS")
        except OAuthReadError:
            raise
        except (TypeError, ValueError):
            _fail("INVALID_CALLBACK_PARAMETERS")
        supplied = params.get("state")
        if (not isinstance(supplied, str) or not 1 <= len(supplied) <= 128 or not supplied.isascii()
                or not isinstance(attempt.state, str) or not attempt.state.isascii()
                or not secrets.compare_digest(supplied, attempt.state)):
            _fail("STATE_MISMATCH")
        if "iss" in params and params["iss"] != ISSUER:
            _fail("ISSUER_MISMATCH")
        if "error" in params and "code" in params:
            _fail("INVALID_CALLBACK_PARAMETERS")
        with attempt._lock:
            if attempt.used:
                _fail("AUTHORIZATION_ATTEMPT_USED")
            attempt.used = True  # One attempt even if the exchange times out.
        if "error" in params:
            _fail("AUTHORIZATION_DENIED")
        code = _visible(params.get("code"), "INVALID_AUTHORIZATION_CODE", 4096)
        pkce_challenge(attempt.verifier)
        body = urlencode({"grant_type": "authorization_code", "code": code, "client_id": client_id,
            "redirect_uri": attempt.callback_uri, "code_verifier": attempt.verifier}).encode("ascii")
        result = self._http.send("POST", "/oauth2/token", body=body, content_type="application/x-www-form-urlencoded")
        return validate_token_response(result, clock=self._clock)


def _account_id(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) or int(value) <= 0:
        _fail("INVALID_PAPER_ACCOUNT_ID")
    return value


def _rows(data, key):
    rows = data.get(key)
    if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        _fail("INVALID_PAPER_RESPONSE")
    return rows


def _number(value, *, nonnegative=False):
    if value in (None, "", "N/A"):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        _fail("INVALID_PAPER_NUMBER")
    try:
        text = str(value)
        if len(text) > 128:
            _fail("INVALID_PAPER_NUMBER")
        number = Decimal(text)
        if (not number.is_finite() or number.adjusted() > 18 or number.as_tuple().exponent < -18
                or abs(number) > Decimal("1e18") or nonnegative and number < 0):
            _fail("INVALID_PAPER_NUMBER")
        return format(number, "f")
    except (InvalidOperation, ValueError):
        _fail("INVALID_PAPER_NUMBER")


@dataclass(frozen=True)
class PaperSelection:
    public_summary: dict
    selected_account_id: str = field(repr=False)
    _token_binding: str = field(repr=False)


@dataclass(frozen=True)
class PaperReadResult:
    public_summary: dict
    private_data: dict = field(repr=False)


class PaperReadTransport:
    """Explicit provider must return ReadToken; no files/env/keyring/token store."""

    def __init__(self, token_provider, *, opener=None, clock=None, timeout=15):
        if not callable(token_provider):
            _fail("TOKEN_PROVIDER_REQUIRED")
        self._provider, self._http = token_provider, _JsonHttp(opener=opener, timeout=timeout)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._selected_id = self._binding = None
        self._last_get_binding = None
        self._last_granted_scopes = ()
        self._discovered_count = None

    def _token(self):
        try:
            token = self._provider()
        except OAuthReadError:
            raise
        except Exception:
            _fail("TOKEN_UNAVAILABLE")
        if type(token) is not ReadToken:
            _fail("VALIDATED_TOKEN_REQUIRED")
        _scopes(" ".join(token.scopes))
        _visible(token.access_token, "INVALID_ACCESS_TOKEN")
        if _now(self._clock) >= token.expires_at:
            _fail("TOKEN_EXPIRED")
        return token

    def request(self, method, url, *, params=None):
        # Reject destination/method before reading the caller's token.
        try:
            parsed = urlsplit(url)
            origin_ok = (parsed.scheme == "https" and parsed.netloc == "webapi.moomoo.com"
                         and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment)
        except (TypeError, ValueError):
            origin_ok = False
        if not origin_ok or method != "GET":
            _fail("BUSINESS_ROUTE_REFUSED")
        params = {} if params is None else params
        if not isinstance(params, dict):
            _fail("BUSINESS_ROUTE_REFUSED")
        selected = self._selected_id is not None and parsed.path.startswith("/api/v1.0/sim-trade/" + self._selected_id + "/")
        allowed = (parsed.path == ACCOUNTS_PATH and params == {} or selected and (
            parsed.path == f"/api/v1.0/sim-trade/{self._selected_id}/cash-info" and params == {}
            or parsed.path == f"/api/v1.0/sim-trade/{self._selected_id}/positions" and params == {"market": 100}
            and type(params.get("market")) is int))
        if not allowed:
            _fail("BUSINESS_ROUTE_REFUSED")
        token = self._token()
        binding = hashlib.sha256(token.access_token.encode()).hexdigest()
        if parsed.path != ACCOUNTS_PATH and binding != self._binding:
            _fail("REDISCOVERY_REQUIRED")
        result = self._http.send("GET", parsed.path, query=params, token=token.access_token)
        if type(result.get("ret_code")) is not int or result["ret_code"] != 0 or not isinstance(result.get("data"), dict):
            _fail("PAPER_BUSINESS_ERROR")
        self._last_get_binding = binding
        self._last_granted_scopes = token.scopes
        return result["data"]  # Private raw body; use high-level safe summaries.

    def discover(self):
        self._selected_id = self._binding = None
        rows = _rows(self.request("GET", ISSUER + ACCOUNTS_PATH), "accounts")
        matches = [row for row in rows if type(row.get("broker_id")) is int and row["broker_id"] == 0
                   and type(row.get("account_type")) is int and row["account_type"] == 1
                   and type(row.get("market_id")) is int and row["market_id"] == 100]
        if not matches:
            _fail("NO_US_PAPER_ACCOUNT")
        if len(matches) != 1:
            _fail("AMBIGUOUS_US_PAPER_ACCOUNT")
        row = matches[0]
        if "trd_env" in row and row["trd_env"] != "SIMULATE":
            _fail("PAPER_IDENTITY_REJECTED")
        self._selected_id, self._binding = _account_id(row.get("account_id")), self._last_get_binding
        self._discovered_count = len(rows)
        return PaperSelection(self._selection_summary(), self._selected_id, self._binding)

    def _selection_summary(self):
        return {"status": "US_PAPER_SELECTED_READ_ONLY", "paper_accounts_returned": self._discovered_count,
            "matching_us_personal_accounts": 1, "broker_id": 0, "account_type": 1, "market_id": 100,
            "server_paper_only_binding_verified": False, "business_writes_supported": False,
            "actual_scopes": list(self._last_granted_scopes)}

    def read_selected(self, selection):
        if (type(selection) is not PaperSelection or selection.selected_account_id != self._selected_id
                or selection._token_binding != self._binding):
            _fail("PAPER_SELECTION_REQUIRED")
        base = f"/api/v1.0/sim-trade/{self._selected_id}/"
        raw_cash = self.request("GET", ISSUER + base + "cash-info")
        cash = {key: _number(raw_cash.get(key), nonnegative=key in {"hold", "max_power_long"})
                for key in ("balance", "hold", "total_asset", "max_power_long")}
        cash["available_cash"] = (str(max(Decimal(0), Decimal(cash["balance"]) - Decimal(cash["hold"])))
                                  if cash["balance"] is not None and cash["hold"] is not None else None)
        raw_positions = _rows(self.request("GET", ISSUER + base + "positions", params={"market": 100}), "positions")
        positions = []
        for row in raw_positions:
            symbol = row.get("symbol")
            source_direction, market = row.get("pstn_type"), row.get("market")
            numeric = type(market) is int and market in {2, 3} and type(source_direction) is int and source_direction in {0, 1}
            textual = market == "US_STOCK" and isinstance(source_direction, str) and source_direction in {"LONG", "SHORT"}
            if not numeric and not textual:
                _fail("UNSUPPORTED_POSITION_SCHEMA")
            direction = ("LONG" if source_direction == 0 else "SHORT") if numeric else source_direction
            kind = "US_OPTION" if numeric and market == 3 else "US_STOCK"
            symbol_valid = (_SYMBOL.fullmatch(symbol) if kind == "US_STOCK" else
                            re.fullmatch(r"[A-Z][A-Z0-9.]{0,63}", symbol)) if isinstance(symbol, str) else None
            if symbol_valid is None:
                _fail("UNSUPPORTED_POSITION_SCHEMA")
            quantity, available = _number(row.get("qty")), _number(row.get("qty_avbl"))
            if (quantity is None or Decimal(quantity) != Decimal(quantity).to_integral_value()
                    or direction == "LONG" and Decimal(quantity) < 0
                    or numeric and direction == "SHORT" and Decimal(quantity) > 0
                    or available is not None and (Decimal(available) != Decimal(available).to_integral_value()
                        or abs(Decimal(available)) > abs(Decimal(quantity))
                        or direction == "LONG" and Decimal(available) < 0)):
                _fail("INVALID_POSITION_QUANTITY")
            positions.append({"symbol": symbol, "direction": direction, "quantity": quantity, "available_quantity": available,
                "instrument_kind": kind, "schema_variant": "openapi_integer_signed" if numeric else "html_string_enum",
                "quantity_policy": "provider sign preserved; not an order-ready sellable quantity"})
        summary = {**self._selection_summary(), "status": "PAPER_READ_ONLY_CONNECTED", "cash_read": True,
            "cash_fields_available": {key: value is not None for key, value in cash.items()},
            "positions_read": True, "position_rows": len(positions), "orders_read": False,
            "position_schema_variants": sorted({row["schema_variant"] for row in positions}),
            "actual_order_submissions": 0, "scope_requested": REQUESTED_SCOPE}
        return PaperReadResult(summary, {"funds": cash, "positions": positions})
