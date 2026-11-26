"""Offline-only OAuth protocol and sim-trade reads; never register/login live."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import base64
import hashlib
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from execution_lab.paper_oauth_read import (ACCOUNTS_PATH, ISSUER, OAuthReadClient, OAuthReadError,
    PaperReadTransport, ReadToken, _NoRedirect, _number, authorization_url, new_pkce,
    pkce_challenge, validate_callback_uri, validate_token_response)


AT = datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc)
CALLBACK = "http://127.0.0.1:8765/callback"
ACCOUNT = "00013579"
SECRET = "OFFLINE_TEST_TOKEN_ONLY"
US = {"account_id": ACCOUNT, "broker_id": 0, "account_type": 1, "market_id": 100}


class Response(BytesIO):
    def __init__(self, value=None, *, url=None, raw=None, headers=None):
        super().__init__(raw if raw is not None else json.dumps(value).encode())
        self.url, self.headers, self.status = url, headers or {}, 200

    def geturl(self):
        return self.url


def token_response(**changes):
    return {"access_token": SECRET, "token_type": "Bearer", "expires_in": 7200, "scope": "trade:read", **changes}


def token(**changes):
    return validate_token_response(token_response(**changes), clock=lambda: AT)


def callback(attempt, **changes):
    return CALLBACK + "?" + urlencode({"state": attempt.state, "code": "OFFLINE_CODE", **changes})


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.accounts = [US]
        self.cash = {"balance": "92345.12", "hold": "345.12", "total_asset": "95678.9", "max_power_long": "199999"}
        self.positions = []
        self.registration = {"client_id": "offline_client", "registration_access_token": "DROP_PRIVATE_REGISTRATION_TOKEN",
            "scope": "quote:read quote:write trade:read trade:write accid:*"}
        self.token = token_response()
        self.failure = None

    def __call__(self, request, timeout):
        self.calls.append(request)
        assert 0 < timeout <= 15
        if self.failure:
            raise self.failure
        path = urlsplit(request.full_url).path
        if path == "/oauth2/register":
            value = self.registration
        elif path == "/oauth2/token":
            value = self.token
        elif path == ACCOUNTS_PATH:
            value = {"ret_code": 0, "data": {"accounts": self.accounts}}
        elif path.endswith("/cash-info"):
            value = {"ret_code": 0, "data": self.cash}
        elif path.endswith("/positions"):
            value = {"ret_code": 0, "data": {"positions": self.positions}}
        else:
            raise AssertionError("Unexpected offline test route")
        return Response(value, url=request.full_url)


def transport(api=None, provider=None, **kwargs):
    api = api or FakeAPI()
    return PaperReadTransport(provider or (lambda: token()), opener=api, clock=lambda: AT, **kwargs), api


def test_actual_pkce_s256_randomness_and_known_hash():
    attempts = [new_pkce(CALLBACK, clock=lambda: AT) for _ in range(3)]
    assert len({a.state for a in attempts}) == len({a.verifier for a in attempts}) == 3
    for attempt in attempts:
        expected = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
        query = parse_qs(urlsplit(authorization_url("offline_client", attempt, clock=lambda: AT)).query)
        assert query["code_challenge"] == [expected] and query["code_challenge_method"] == ["S256"]
        assert query["scope"] == ["trade:read"] and not any("accid" in x for xs in query.values() for x in xs)
        assert attempt.state not in repr(attempt) and attempt.verifier not in repr(attempt)
    assert pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.parametrize("uri", ["http://localhost/callback", "https://127.0.0.1:8765/callback",
    "http://127.0.0.1.evil.invalid:8765/callback", "http://0.0.0.0:8765/callback",
    "http://user@localhost:8765/callback", "http://localhost:8765/other", "http://localhost:22222/callback",
    "http://localhost:8765/callback?state=bad", "http://localhost:8765/callback#bad"])
def test_callback_is_fixed_loopback_explicit_port_and_path(uri):
    with pytest.raises(OAuthReadError):
        validate_callback_uri(uri)


def test_registration_requests_minimum_scope_and_metadata_is_not_a_grant():
    api = FakeAPI()
    registered = OAuthReadClient(opener=api, clock=lambda: AT).register(CALLBACK)
    request = api.calls[0]
    body = json.loads(request.data)
    assert request.method == "POST" and request.full_url == ISSUER + "/oauth2/register"
    assert body["scope"] == "trade:read" and body["redirect_uris"] == [CALLBACK]
    assert body["client_name"] == "alpha_trading_lab_paper_read" and "-" not in body["client_name"]
    assert request.get_header("Authorization") is None
    assert registered.public_summary["registration_scope_is_grant"] is False
    assert registered.public_summary["server_minimal_scope_support_verified"] is False
    assert "DROP_PRIVATE_REGISTRATION_TOKEN" not in repr(registered)
    read = PaperReadTransport(lambda: registered, opener=api, clock=lambda: AT)
    with pytest.raises(OAuthReadError, match="VALIDATED_TOKEN_REQUIRED"):
        read.discover()
    assert len(api.calls) == 1


@pytest.mark.parametrize("problem", ["state", "host", "port", "path", "fragment", "duplicate_state", "issuer", "unicode_state"])
def test_exact_state_callback_and_issuer_validation_precede_token_exchange(problem):
    api, attempt = FakeAPI(), new_pkce(CALLBACK, clock=lambda: AT)
    target = callback(attempt)
    if problem == "state": target = callback(attempt, state="wrong")
    elif problem == "unicode_state": target = callback(attempt, state="非匹配")
    elif problem == "host": target = target.replace("127.0.0.1", "localhost")
    elif problem == "port": target = target.replace(":8765/", ":8766/")
    elif problem == "path": target = target.replace("/callback?", "/other?")
    elif problem == "fragment": target += "#sensitive"
    elif problem == "duplicate_state": target += "&state=wrong"
    else: target += "&iss=https%3A%2F%2Fmcp.moomoo.com"
    with pytest.raises(OAuthReadError):
        OAuthReadClient(opener=api, clock=lambda: AT).exchange("offline_client", attempt, target)
    assert not api.calls


@pytest.mark.parametrize("seconds", [-1, 601])
def test_expired_or_future_attempt_never_authorizes_or_exchanges(seconds):
    api, attempt = FakeAPI(), new_pkce(CALLBACK, clock=lambda: AT)
    clock = lambda: AT + timedelta(seconds=seconds)
    with pytest.raises(OAuthReadError, match="EXPIRED_OR_FUTURE"):
        authorization_url("offline_client", attempt, clock=clock)
    with pytest.raises(OAuthReadError, match="EXPIRED_OR_FUTURE"):
        OAuthReadClient(opener=api, clock=clock).exchange("offline_client", attempt, callback(attempt))
    assert not api.calls


def test_valid_token_exchange_is_once_and_transmits_original_verifier():
    api, attempt = FakeAPI(), new_pkce(CALLBACK, clock=lambda: AT)
    client = OAuthReadClient(opener=api, clock=lambda: AT)
    result = client.exchange("offline_client", attempt, callback(attempt))
    sent = parse_qs(api.calls[0].data.decode())
    assert sent["code_verifier"] == [attempt.verifier] and sent["redirect_uri"] == [CALLBACK]
    assert api.calls[0].full_url == ISSUER + "/oauth2/token"
    assert result.scopes == ("trade:read",) and SECRET not in repr(result)
    with pytest.raises(OAuthReadError, match="ATTEMPT_USED"):
        client.exchange("offline_client", attempt, callback(attempt))
    assert len(api.calls) == 1


@pytest.mark.parametrize("scope", [None, "", "quote:read", "trade:read trade:write", "trade:read quote:write",
    "trade:read accid:*", "trade:read accid:123456", "trade:read unknown:read", "trade:read\nquote:read"])
def test_missing_broad_or_unknown_actual_grant_never_reaches_account_rpc(scope):
    api, attempt = FakeAPI(), new_pkce(CALLBACK, clock=lambda: AT)
    api.token = token_response(scope=scope)
    with pytest.raises(OAuthReadError):
        OAuthReadClient(opener=api, clock=lambda: AT).exchange("offline_client", attempt, callback(attempt))
    assert len(api.calls) == 1 and urlsplit(api.calls[0].full_url).path == "/oauth2/token"


@pytest.mark.parametrize("token_type", [None, 1, {}, []])
def test_malformed_token_type_is_a_static_safe_error(token_type):
    with pytest.raises(OAuthReadError, match="INVALID_TOKEN_RESPONSE"):
        token(token_type=token_type)


def test_denied_callback_does_not_exchange_or_echo_private_description():
    api, attempt = FakeAPI(), new_pkce(CALLBACK, clock=lambda: AT)
    target = CALLBACK + "?" + urlencode({"state": attempt.state, "error": "access_denied", "error_description": SECRET})
    with pytest.raises(OAuthReadError) as caught:
        OAuthReadClient(opener=api, clock=lambda: AT).exchange("offline_client", attempt, target)
    assert caught.value.code == "AUTHORIZATION_DENIED" and SECRET not in str(caught.value)
    assert not api.calls


@pytest.mark.parametrize("method,url,params", [
    ("GET", ISSUER + "/api/v1.0/accounts/123/funds", None),
    ("GET", "https://evil.invalid" + ACCOUNTS_PATH, None),
    ("POST", ISSUER + ACCOUNTS_PATH, None),
    ("GET", ISSUER + f"/api/v1.0/sim-trade/{ACCOUNT}/orders", {"market": 100}),
    ("GET", ISSUER + f"/api/v1.0/sim-trade/{ACCOUNT}/cash-info", None),
    ("GET", ISSUER + ACCOUNTS_PATH + "?market=100", None),
    ("GET", ISSUER + ACCOUNTS_PATH, []),
])
def test_real_order_or_unselected_routes_rejected_before_reading_token(method, url, params):
    calls, api = [], FakeAPI()
    read = PaperReadTransport(lambda: calls.append("token"), opener=api, clock=lambda: AT)
    with pytest.raises(OAuthReadError, match="ROUTE_REFUSED"):
        read.request(method, url, params=params)
    assert not api.calls and not calls


def test_selects_unique_us_personal_account_not_first_and_public_output_has_no_identity_or_amounts():
    read, api = transport()
    api.accounts = [{**US, "account_id": "55555", "market_id": 1}, US]
    selection = read.discover()
    assert selection.selected_account_id == ACCOUNT
    assert ACCOUNT not in repr(selection)
    # Public summary cannot be contaminated through a mutated caller copy.
    selection.public_summary["leaked_account"] = ACCOUNT
    result = read.read_selected(selection)
    encoded = json.dumps(result.public_summary)
    assert ACCOUNT not in encoded and "92345.12" not in encoded and SECRET not in repr(result)
    assert result.private_data["funds"]["available_cash"] == "92000.00"
    assert result.public_summary["actual_order_submissions"] == 0 and result.public_summary["position_rows"] == 0
    assert [urlsplit(request.full_url).path for request in api.calls] == [ACCOUNTS_PATH,
        f"/api/v1.0/sim-trade/{ACCOUNT}/cash-info", f"/api/v1.0/sim-trade/{ACCOUNT}/positions"]
    assert api.calls[-1].full_url.endswith("positions?market=100")
    assert all(request.method == "GET" for request in api.calls)


@pytest.mark.parametrize("rows,code", [([], "NO_US_PAPER_ACCOUNT"), ([{**US, "market_id": 1}], "NO_US_PAPER_ACCOUNT"),
    ([US, {**US, "account_id": "99999"}], "AMBIGUOUS_US_PAPER_ACCOUNT"),
    ([{**US, "account_id": 123}], "INVALID_PAPER_ACCOUNT_ID"),
    ([{**US, "trd_env": "REAL"}], "PAPER_IDENTITY_REJECTED")])
def test_no_unique_verified_us_paper_identity_never_reads_funds(rows, code):
    read, api = transport()
    api.accounts = rows
    with pytest.raises(OAuthReadError, match=code):
        read.discover()
    assert len(api.calls) == 1


@pytest.mark.parametrize("position,variant,quantity,kind", [
    ({"market": "US_STOCK", "pstn_type": "LONG", "symbol": "NVDA", "qty": 2, "qty_avbl": 1}, "html_string_enum", "2", "US_STOCK"),
    ({"market": "US_STOCK", "pstn_type": "SHORT", "symbol": "NVDA", "qty": 2, "qty_avbl": 1}, "html_string_enum", "2", "US_STOCK"),
    ({"market": 2, "pstn_type": 0, "symbol": "NVDA", "qty": "2", "qty_avbl": "1"}, "openapi_integer_signed", "2", "US_STOCK"),
    ({"market": 2, "pstn_type": 1, "symbol": "NVDA", "qty": "-2", "qty_avbl": "-1"}, "openapi_integer_signed", "-2", "US_STOCK"),
    ({"market": 3, "pstn_type": 1, "symbol": "AAPL261120C275000", "qty": "-2", "qty_avbl": "1"}, "openapi_integer_signed", "-2", "US_OPTION"),
])
def test_nonempty_official_html_and_openapi_sim_variants_preserve_signs(position, variant, quantity, kind):
    read, api = transport()
    api.positions = [position]
    result = read.read_selected(read.discover())
    row = result.private_data["positions"][0]
    assert row["schema_variant"] == variant and row["quantity"] == quantity and row["instrument_kind"] == kind
    assert result.public_summary["position_rows"] == 1


@pytest.mark.parametrize("value", ["1e999999999", "1e-999999999", "1e19", "1e-19", "9" * 129, "NaN", "Infinity", True])
def test_extreme_numeric_inputs_are_rejected_before_decimal_fixed_format(value):
    with pytest.raises(OAuthReadError, match="INVALID_PAPER_NUMBER"):
        _number(value)


def test_expired_or_changed_grant_requires_no_get_or_rediscovery():
    api = FakeAPI()
    expired = PaperReadTransport(lambda: token(expires_in=1), opener=api, clock=lambda: AT + timedelta(seconds=2))
    with pytest.raises(OAuthReadError, match="TOKEN_EXPIRED"):
        expired.discover()
    assert not api.calls
    current = [token(scope="trade:read quote:read")]
    read, api = transport(provider=lambda: current[0])
    selection = read.discover()
    current[0] = validate_token_response(token_response(access_token="OFFLINE_OTHER_TOKEN"), clock=lambda: AT)
    with pytest.raises(OAuthReadError, match="REDISCOVERY_REQUIRED"):
        read.read_selected(selection)
    assert len(api.calls) == 1


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_http_errors_never_retry_or_echo_url_headers_or_body(status):
    api = FakeAPI()
    api.failure = HTTPError("https://private.invalid/" + SECRET, status, SECRET, {}, BytesIO(SECRET.encode()))
    read, _ = transport(api)
    with pytest.raises(OAuthReadError) as caught:
        read.discover()
    assert len(api.calls) == 1 and SECRET not in str(caught.value) and "private.invalid" not in str(caught.value)


def test_redirects_timeout_business_failures_and_size_limit_fail_without_retry():
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid") is None
    failures = [lambda req, **kw: Response({}, url="https://elsewhere.invalid"),
        lambda req, **kw: Response({"ret_code": -9, "ret_msg": SECRET}, url=req.full_url),
        lambda req, **kw: Response({}, url=req.full_url, headers={"Content-Length": "999999999"}),
        lambda req, **kw: Response(url=req.full_url, raw=b'{"ret_code":0,"ret_code":-9}')]
    def timeout(*args, **kwargs):
        raise TimeoutError(SECRET)
    failures.append(timeout)
    for fail in failures:
        calls = []
        def opener(request, **kwargs):
            calls.append(1)
            return fail(request, **kwargs)
        read = PaperReadTransport(lambda: token(), opener=opener, clock=lambda: AT)
        with pytest.raises(OAuthReadError) as caught:
            read.discover()
        assert len(calls) == 1 and SECRET not in str(caught.value)


def test_token_exchange_timeout_consumes_attempt_and_never_retries():
    api, attempt = FakeAPI(), new_pkce(CALLBACK, clock=lambda: AT)
    api.failure = TimeoutError(SECRET)
    client = OAuthReadClient(opener=api, clock=lambda: AT)
    with pytest.raises(OAuthReadError, match="NO_RETRY"):
        client.exchange("offline_client", attempt, callback(attempt))
    with pytest.raises(OAuthReadError, match="ATTEMPT_USED"):
        client.exchange("offline_client", attempt, callback(attempt))
    assert len(api.calls) == 1


@pytest.mark.parametrize("timeout", [0, 16, True, float("nan")])
def test_unbounded_or_invalid_timeout_is_rejected_without_network(timeout):
    api = FakeAPI()
    with pytest.raises(OAuthReadError, match="INVALID_TIMEOUT"):
        PaperReadTransport(lambda: token(), opener=api, timeout=timeout)
    assert not api.calls
