"""Offline protocol/signature/durability tests; no login, sockets or account data."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import base64
import hashlib
import json
from urllib.error import HTTPError

import pytest

from execution_lab.rest_paper import API_BASE, PREFIX, RestPaperAdapter, SimOnlyRestTransport
from execution_lab.rest_transport import (ApiKeyAuth, BearerAuth, RestHttpClient, RestTransportError,
    _NoRedirect, build_rest_paper_adapter, canonical_request)
from execution_lab.veighna_bridge import BridgeError


AT = datetime(2024, 3, 11, 14, 0, tzinfo=timezone.utc)
ACCOUNT = "000123"
META = {"account_id": ACCOUNT, "market_id": 100, "broker_id": 0, "account_type": 1}
BASE = PREFIX + ACCOUNT + "/"


def order(**changes):
    row = {"order_id": "0099", "side": 1, "market": 2, "symbol": "NVDA", "order_type": 1,
        "status": 2, "qty": "1", "cum_qty": "0", "price": "100.0", "avg_fill_price": "0",
        "update_time": "1710165600000000", "text": "buy_1"}
    row.update(changes)
    return row


def body(**changes):
    data = {"market": 100, "symbol": "US.NVDA", "order_type": 1, "order_side": 1,
        "qty": "1", "price": "100.0", "text": "buy_1", "order_trade_time_type": 1}
    data.update(changes)
    return data


class FakeRest:
    def __init__(self):
        self.calls, self.orders, self.positions = [], [], []
        self.funds = {"balance": "10000", "hold": "100", "total_asset": "10500", "max_power_long": "999999"}
        self.timeout_submit = False
        self.before_post = None

    def __call__(self, method, url, *, params, json, timeout):
        self.calls.append((method, url, deepcopy(params), deepcopy(json)))
        if method == "POST" and self.before_post:
            self.before_post()
        if method == "GET" and url.endswith("/accounts"):
            data = {"accounts": [META]}
        elif method == "GET" and url.endswith("/cash-info"):
            data = self.funds
        elif method == "GET" and url.endswith("/positions"):
            data = {"positions": self.positions}
        elif method == "GET" and url.endswith("/orders"):
            data = {"orders": self.orders}
        elif method == "POST" and url.endswith("/orders"):
            if self.timeout_submit:
                raise TimeoutError("not a real broker message")
            data = {"order_id": "0099"}
        elif method == "POST" and url.endswith("/cancel"):
            data = {"order_id": "0099"}
        else:
            raise AssertionError("Unexpected test request")
        return {"ret_code": 0, "data": deepcopy(data)}


def adapter(fake=None, *, states=None, **kwargs):
    fake = fake or FakeRest()
    states = states if states is not None else []
    item = RestPaperAdapter(fake, account_id=ACCOUNT, account_metadata=META, auth_confirmed=True,
                            persist_state=lambda state: states.append(deepcopy(state)), **kwargs)
    return item, fake, states


def submit(item, **changes):
    args = dict(client_id="buy_1", symbol="NVDA", side="BUY", quantity=1, price=100,
                quote_at=AT, as_of=AT)
    args.update(changes)
    return item.submit_limit(**args)


def test_missing_configuration_never_discovers_or_falls_back():
    fake = FakeRest()
    item = RestPaperAdapter(fake, account_id=ACCOUNT, account_metadata=META)
    assert item.status == "NOT_CONFIGURED" and not fake.calls
    with pytest.raises(BridgeError):
        submit(item)
    assert not fake.calls


@pytest.mark.parametrize("change", [{"account_id": 123}, {"market_id": 10}, {"broker_id": 1},
                                  {"account_type": 2}, {"market_id": True}])
def test_account_namespace_requires_exact_personal_us_paper_metadata(change):
    fake = FakeRest()
    with pytest.raises(BridgeError):
        RestPaperAdapter(fake, account_id=ACCOUNT, account_metadata={**META, **change}, auth_confirmed=True)
    assert not fake.calls


def test_reconciliation_maps_usd_equity_and_cash_and_preserves_string_id():
    item, fake, _ = adapter()
    with pytest.raises(BridgeError, match="Reconcile"):
        submit(item)
    assert not fake.calls
    report = item.reconcile()
    assert report["funds"][0]["us_cash"] == "9900"
    assert report["funds"][0]["total_assets"] == "10500"
    assert item.account_id == ACCOUNT and not item.requires_reconciliation
    assert all(url.startswith(API_BASE + BASE) for _, url, _, _ in fake.calls)
    assert item.export_state()["backend"] == "REST_sim_trade"


def test_no_equity_or_no_cash_stays_unavailable_and_blocks_order():
    for missing in ("balance", "hold", "total_asset"):
        item, fake, _ = adapter()
        fake.funds.pop(missing)
        result = item.reconcile()
        expected = "total_assets" if missing == "total_asset" else "us_cash"
        assert result["funds"][0][expected] is None
        with pytest.raises(BridgeError):
            submit(item)
        assert not any(call[0] == "POST" for call in fake.calls)


@pytest.mark.parametrize("change", [{"quantity": 2}, {"quantity": True}, {"side": "SELL"},
                                  {"symbol": "HK.00700"}, {"price": 100.001}])
def test_controlled_prototype_rejects_unsafe_order_before_post(change):
    item, fake, _ = adapter()
    item.reconcile()
    with pytest.raises(BridgeError):
        submit(item, **change)
    assert not any(call[0] == "POST" for call in fake.calls)


def test_manual_paper_share_is_never_sold_or_added_to():
    item, fake, _ = adapter()
    fake.positions = [{"symbol": "NVDA", "market": "US_STOCK", "pstn_type": "LONG", "qty": "1", "qty_avbl": "1"}]
    item.reconcile()
    for side in ("BUY", "SELL"):
        with pytest.raises(BridgeError, match="inventory"):
            submit(item, side=side)
    assert not any(call[0] == "POST" for call in fake.calls)


def test_intent_is_durable_before_post_and_idempotent_after_ack():
    item, fake, states = adapter()
    item.reconcile()
    fake.before_post = lambda: (states[-1]["intents"]["buy_1"]["status"] == "SUBMITTING") or pytest.fail("not durable")
    result = submit(item)
    assert result["order_id"] == "0099" and result["status"] == "WAITING_SUBMIT"
    assert not item.executions
    assert submit(item) == result
    assert sum(call[0] == "POST" for call in fake.calls) == 1
    sent = next(call for call in fake.calls if call[0] == "POST")
    assert sent[3] == body()
    with pytest.raises(BridgeError, match="economics"):
        submit(item, price=101)


def test_failed_durable_sink_prevents_any_post():
    item, fake, _ = adapter()
    item.reconcile()
    def fail(_):
        raise OSError("private path should never appear")
    item.persist_state = fail
    with pytest.raises(BridgeError, match="persistence failed"):
        submit(item)
    assert item.status == "PERSISTENCE_FAILED"
    assert not any(call[0] == "POST" for call in fake.calls)


def test_post_timeout_never_retries_and_unique_economic_match_recovers():
    item, fake, states = adapter()
    item.reconcile()
    fake.timeout_submit = True
    with pytest.raises(BridgeError, match="unknown"):
        submit(item)
    assert states[-1]["intents"]["buy_1"]["status"] == "SUBMISSION_UNKNOWN"
    with pytest.raises(BridgeError):
        submit(item)
    assert sum(call[0] == "POST" for call in fake.calls) == 1
    fake.orders = [order(status=4, cum_qty="1", avg_fill_price="99.9")]
    fake.positions = [{"symbol": "NVDA", "market": "US_STOCK", "pstn_type": "LONG", "qty": "1", "qty_avbl": "1"}]
    report = item.reconcile()
    assert report["status"] == "matched" and not item.requires_reconciliation
    assert len(report["new_executions"]) == 1
    fill = report["new_executions"][0]
    assert (fill["symbol"], fill["side"], fill["quantity"], fill["cumulative_quantity"]) == ("NVDA", "BUY", 1, 1)
    assert fill["broker_deal_id"] is None and fill["source"] == "derived_from_order_cumulative"
    assert item.reconcile()["new_executions"] == []
    assert len(item.executions) == 1 and sum(call[0] == "POST" for call in fake.calls) == 1


@pytest.mark.parametrize("rows", [[], [order(price="101")], [order(order_type=3)],
                                 [order(), order(order_id="0100")]])
def test_unknown_submission_without_unique_matching_limit_stays_blocked(rows):
    item, fake, _ = adapter()
    item.reconcile()
    fake.timeout_submit = True
    with pytest.raises(BridgeError):
        submit(item)
    fake.orders = rows
    result = item.reconcile()
    assert result["status"] == "submission_unknown" and item.requires_reconciliation
    assert not item.executions and not item.orders
    assert sum(call[0] == "POST" for call in fake.calls) == 1


def test_cancel_ack_is_not_fill_finality_and_cumulative_fill_deduplicates():
    item, fake, _ = adapter()
    item.reconcile()
    submit(item)
    assert item.cancel("0099")["status"] == "CANCEL_PENDING"
    assert item.cancel("0099")["status"] == "CANCEL_PENDING"
    assert sum(url.endswith("/cancel") for _, url, _, _ in fake.calls) == 1
    assert not item.executions and item.orders["0099"]["status"] == "WAITING_SUBMIT"
    # A fill that happened before cancellation can be reported with terminal status.
    row = order(status=7, cum_qty="1", avg_fill_price="100")
    item.process_rest_order_snapshot(row)
    item.process_rest_order_snapshot(row)
    assert len(item.executions) == 1
    assert item.orders["0099"]["status"] == "CANCELLED_PART"
    state = item.export_state()
    restored, _, _ = adapter(state=state)
    restored.process_rest_order_snapshot(row)
    assert len(restored.executions) == 1 and restored.requires_reconciliation
    for change in ({"backend": "legacy_OpenD"}, {"account_id": 123}, {"account_id": "123"}):
        with pytest.raises(BridgeError, match="another"):
            adapter(state={**state, **change})


@pytest.mark.parametrize("change", [{"side": 2}, {"qty": "2"}, {"price": "101"}, {"order_type": 3}])
def test_known_order_economics_cannot_change_before_deriving_fill(change):
    item, _, _ = adapter()
    item.reconcile()
    submit(item)
    with pytest.raises(BridgeError, match="economics"):
        item.process_rest_order_snapshot(order(status=4, cum_qty="1", avg_fill_price="100", **change))
    assert not item.executions and item.requires_reconciliation


def test_documented_null_market_is_bound_to_selected_us_account_not_default_hk():
    item, fake, _ = adapter()
    item.reconcile()
    submit(item)
    fake.orders = [order(market=None)]
    assert item.reconcile()["orders"][0]["code"] == "US.NVDA"
    fake.orders = [order(market=1)]
    with pytest.raises(BridgeError):
        item.reconcile()
    assert item.requires_reconciliation


@pytest.mark.parametrize("method,path,params,payload", [
    ("GET", "/api/v1.0/trade/accounts", {}, None),
    ("GET", PREFIX + "123/orders", {"market": 100}, None),
    ("GET", BASE + "orders", {}, None),
    ("GET", BASE + "orders", {"market": 10}, None),
    ("POST", BASE + "orders", {}, body(qty="2")),
    ("POST", BASE + "orders", {}, body(market=10)),
    ("POST", BASE + "orders", {}, body(order_side=3)),
    ("POST", BASE + "orders", {}, body(symbol="HK.00700")),
    ("POST", BASE + "orders", {}, body(order_type=3)),
    ("POST", BASE + "orders", {}, body(order_trade_time_type=2)),
    ("POST", BASE + "orders/0099/modify", {}, {"market": 100}),
])
def test_sim_transport_route_and_economic_whitelist(method, path, params, payload):
    fake = FakeRest()
    transport = SimOnlyRestTransport(fake, account_id=ACCOUNT, auth_confirmed=True)
    with pytest.raises(BridgeError):
        transport.request(method, path, params=params, json=payload)
    assert not fake.calls


class Response(BytesIO):
    def __init__(self, data=None, *, url=None, headers=None, status=200):
        super().__init__(json.dumps(data if data is not None else {"ret_code": 0, "data": {}}).encode())
        self._url, self.headers, self.status = url, headers or {}, status

    def geturl(self):
        return self._url


def test_canonical_get_keeps_empty_fields_and_post_hashes_exact_utf8_bytes():
    assert canonical_request("123", "GET", BASE + "orders", "market=100", b"") == (
        "123\nGET\n" + BASE + "orders\nmarket=100\n").encode()
    raw = '{"text":"教学"}'.encode()
    assert canonical_request("123", "POST", BASE + "orders", "", raw).split(b"\n")[-1] == hashlib.sha256(raw).hexdigest().encode()


@pytest.mark.parametrize("algorithm", ["Ed25519", "RSA-SHA256"])
def test_real_signature_verifies_exact_request_transmitted_by_http(algorithm):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
    private = ed25519.Ed25519PrivateKey.generate() if algorithm == "Ed25519" else rsa.generate_private_key(65537, 2048)
    observed = []
    def open_once(request, timeout):
        observed.append(request)
        timestamp = request.get_header("X-timestamp")
        assert timestamp == str(int(AT.timestamp() * 1000))
        assert request.get_header("X-nonce") == "offline_nonce"
        # Independent construction, including transmitted body and empty query.
        expected = (timestamp + "\nPOST\n" + BASE + "orders\n\n"
                    + hashlib.sha256(request.data).hexdigest()).encode()
        signature = base64.b64decode(request.get_header("Authorization"))
        if algorithm == "Ed25519":
            private.public_key().verify(signature, expected)
        else:
            private.public_key().verify(signature, expected, padding.PKCS1v15(), hashes.SHA256())
        assert json.loads(request.data) == body()
        return Response(url=request.full_url)
    auth = ApiKeyAuth("offline_app", private, algorithm=algorithm, clock=lambda: AT,
                      nonce_provider=lambda: "offline_nonce")
    RestHttpClient(auth, account_id=ACCOUNT, opener=open_once)("POST", API_BASE + BASE + "orders", json=body())
    assert len(observed) == 1


@pytest.mark.parametrize("url", ["http://webapi.moomoo.com" + BASE + "orders",
    "https://webapi.moomoo.com.evil.invalid" + BASE + "orders",
    API_BASE + BASE + "orders?market=100", API_BASE + "/api/v1.0/trade/accounts"])
def test_destination_rejection_precedes_reading_any_token(url):
    calls = []
    http = RestHttpClient(BearerAuth(lambda: calls.append("token")), account_id=ACCOUNT,
                          opener=lambda *a, **k: calls.append("network"))
    with pytest.raises(BridgeError):
        http("GET", url, params={"market": 100})
    assert calls == []


def test_http_get_signature_query_and_no_default_body():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    def open_once(request, timeout):
        assert request.full_url == API_BASE + BASE + "orders?market=100" and request.data is None
        expected = (str(int(AT.timestamp()*1000)) + "\nGET\n" + BASE + "orders\nmarket=100\n").encode()
        key.public_key().verify(base64.b64decode(request.get_header("Authorization")), expected)
        return Response(url=request.full_url)
    http = RestHttpClient(ApiKeyAuth("offline", key, algorithm="Ed25519", clock=lambda: AT),
                          account_id=ACCOUNT, opener=open_once)
    assert http("GET", API_BASE + BASE + "orders", params={"market": 100})["ret_code"] == 0


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_errors_are_sanitized_and_never_retried(status):
    calls = []
    def open_once(request, timeout):
        calls.append(1)
        raise HTTPError(request.full_url, status, "SENSITIVE_TOKEN", {}, BytesIO(b"SENSITIVE_BODY"))
    http = RestHttpClient(BearerAuth(lambda: "offline_token"), account_id=ACCOUNT, opener=open_once)
    with pytest.raises(RestTransportError) as caught:
        http("POST", API_BASE + BASE + "orders", json=body())
    assert len(calls) == 1 and caught.value.http_status == status
    assert "SENSITIVE" not in str(caught.value) and "offline_token" not in str(caught.value)


def test_redirects_timeouts_business_errors_and_oversize_are_fail_closed():
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid") is None
    cases = [
        (lambda req, **kw: Response(url="https://other.invalid"), "REDIRECT_REFUSED"),
        (lambda req, **kw: Response({"ret_code": 77, "ret_msg": "PRIVATE"}, url=req.full_url), "BUSINESS_ERROR"),
        (lambda req, **kw: Response(url=req.full_url, headers={"Content-Length": "999999999"}), "SIZE_LIMIT"),
    ]
    def timeout(*args, **kwargs):
        raise TimeoutError("PRIVATE")
    cases.append((timeout, "OUTCOME_UNKNOWN"))
    for opener, code in cases:
        calls = []
        def counted(request, **kwargs):
            calls.append(1)
            return opener(request, **kwargs)
        http = RestHttpClient(BearerAuth(lambda: "offline_token"), account_id=ACCOUNT, opener=counted)
        with pytest.raises(RestTransportError) as caught:
            http("POST", API_BASE + BASE + "orders", json=body())
        assert caught.value.code == code and len(calls) == 1
        assert "PRIVATE" not in str(caught.value)


def private_config(tmp_path, **changes):
    config = {"schema_version": 1, "backend": "REST_sim_trade", "account_id": ACCOUNT,
              "authorization_confirmed": True, "auth": {"type": "bearer"}}
    config.update(changes)
    path = tmp_path / "private_paper.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_factory_backend_and_fresh_quote_gates_precede_credentials(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Configuration or credential access was not authorized")
    monkeypatch.setattr("execution_lab.rest_transport._private_bytes", forbidden)
    assert build_rest_paper_adapter(backend="legacy_OpenD", config_path="unused").status == "NOT_CONFIGURED"
    assert build_rest_paper_adapter(backend="REST_sim_trade", config_path="unused").status == "NOT_CONFIGURED"


def test_factory_missing_auth_or_synced_config_does_not_access_network(tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing setup must not perform network access")
    kwargs = dict(backend="REST_sim_trade", quote_provider=lambda *a: {}, opener=forbidden)
    item = build_rest_paper_adapter(config_path=private_config(tmp_path), **kwargs)
    assert item.status == "NOT_CONFIGURED"
    item = build_rest_paper_adapter(config_path=r"D:\Dropbox\private.json", token_provider=lambda: "offline", **kwargs)
    assert item.status == "NOT_CONFIGURED"


def test_factory_discovers_only_selected_string_paper_account_and_no_write(tmp_path):
    calls = []
    provider = lambda *args: {}
    def opener(request, timeout):
        calls.append(request)
        assert request.method == "GET" and request.full_url == API_BASE + PREFIX + "accounts"
        return Response({"ret_code": 0, "data": {"accounts": [
            {**META, "account_id": "123"}, META]}}, url=request.full_url)
    item = build_rest_paper_adapter(backend="REST_sim_trade", config_path=private_config(tmp_path),
        account_id=ACCOUNT, quote_provider=provider, token_provider=lambda: "offline_token", opener=opener)
    assert item.status == "READY" and item.account_id == ACCOUNT and item.quote_provider is provider
    assert item.requires_reconciliation and item.persist_state is None
    assert item.auth_policy["upstream_paper_only_scope_verified"] is False
    assert len(calls) == 1 and not item.intents
    # No conversion from legacy numeric IDs or dropping leading zeros.
    other = build_rest_paper_adapter(backend="REST_sim_trade", config_path=private_config(tmp_path),
        account_id="123", quote_provider=provider, token_provider=lambda: "offline", opener=opener)
    assert other.status == "NOT_CONFIGURED" and len(calls) == 1


def test_factory_api_key_reads_only_explicit_key_and_signs_discovery(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "explicit-test-key.pem"
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    config = private_config(tmp_path, auth={"type": "api_key", "app_key": "offline_key",
        "algorithm": "Ed25519", "private_key_file": str(key_path)})
    def opener(request, timeout):
        expected = (str(int(AT.timestamp()*1000)) + "\nGET\n" + PREFIX + "accounts\n\n").encode()
        key.public_key().verify(base64.b64decode(request.get_header("Authorization")), expected)
        return Response({"ret_code": 0, "data": {"accounts": [META]}}, url=request.full_url)
    item = build_rest_paper_adapter(backend="REST_sim_trade", config_path=config,
        quote_provider=lambda *a: {}, clock=lambda: AT, opener=opener)
    assert item.status == "READY" and item.account_id == ACCOUNT
