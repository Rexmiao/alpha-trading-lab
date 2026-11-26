"""US paper-only REST facade with an injected, single-attempt transport.

There is deliberately no OAuth login, credential loading, HTTP client, CLI,
reporter, retry loop, broker discovery, or SHADOW fallback in this module.
The operator must separately review authorization and inject a function that
sends one request. Official paper-only OAuth/account scoping remains unverified;
``auth_confirmed`` is a caller assertion, not proof of narrower server scopes.

REST paper IDs remain strings and have their own REST_sim_trade state namespace.
The existing cumulative-order state machine is reused through a strict mapping;
its order-derived executions never become fictitious broker deal IDs.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re
from types import SimpleNamespace

from .veighna_bridge import BridgeError, FutuPaperAdapter, _decimal, _integer, _symbol


API_BASE = "https://webapi.moomoo.com"
PREFIX = "/api/v1.0/sim-trade/"
_ID = re.compile(r"[0-9]{1,40}\Z")
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_ORDER_STATUS = {1: "WAITING_SUBMIT", 2: "SUBMITTED", 3: "FILLED_PART", 4: "FILLED_ALL",
                 5: "CANCELLED_ALL", 6: "FAILED", 7: "CANCELLED_PART"}
_TERMINAL = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED"}
_CONSTANTS = SimpleNamespace(RET_OK=0, TrdEnv=SimpleNamespace(SIMULATE="SIMULATE"),
    Currency=SimpleNamespace(USD="USD"), TrdSide=SimpleNamespace(BUY="BUY", SELL="SELL"),
    OrderType=SimpleNamespace(NORMAL="LIMIT"), TimeInForce=SimpleNamespace(DAY="DAY"),
    Session=SimpleNamespace(RTH="RTH"), ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"))


def _identifier(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise BridgeError(f"REST paper {name} must be an explicit decimal string, never an implicit SDK ID.")
    return value


def _price(value):
    number = _decimal(value, "limit price", minimum=Decimal("0.0001"))
    tick = Decimal("0.01") if number >= 1 else Decimal("0.0001")
    if number % tick:
        raise BridgeError("The US limit price must match its tick size; automatic adjustment is disabled.")
    return format(number, "f")


def _list(data, key):
    rows = data.get(key)
    if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        raise BridgeError("REST paper response has an invalid or excessive row list.")
    return rows


class SimOnlyRestTransport:
    """Namespace guard around an explicitly injected request-once callable.

    Callable signature: (method, fixed_https_url, *, params, json, timeout).
    It must return the decoded official {ret_code:0,data:{...}} envelope and
    must not retry internally, invoke login, follow cross-origin redirects,
    report payloads elsewhere, or fall back to another origin or account.
    Authentication/secret storage belongs to a separately reviewed caller.
    """

    def __init__(self, request_once=None, *, account_id=None, auth_confirmed=False):
        self._request_once = request_once
        self.account_id = _identifier(account_id, "account_id") if account_id is not None else None
        self.configured = callable(request_once) and auth_confirmed is True

    def _validated_args(self, method, path, params=None, body=None):
        params, body = deepcopy(params or {}), deepcopy(body)
        if method == "GET" and path == PREFIX + "accounts":
            allowed = params == {} and body is None
        else:
            if self.account_id is None:
                raise BridgeError("Select an explicit REST paper account before any account request.")
            base = PREFIX + self.account_id + "/"
            allowed = False
            if method == "GET" and path == base + "cash-info":
                allowed = params == {} and body is None
            elif method == "GET" and path in {base + "positions", base + "orders"}:
                allowed = params == {"market": 100} and type(params.get("market")) is int and body is None
            elif method == "POST" and path == base + "orders":
                keys = {"market", "symbol", "order_type", "order_side", "qty", "price", "text", "order_trade_time_type"}
                if isinstance(body, dict) and set(body) == keys and params == {}:
                    symbol = body.get("symbol")
                    allowed = (type(body.get("market")) is int and body["market"] == 100
                        and type(body.get("order_type")) is int and body["order_type"] == 1
                        and type(body.get("order_side")) is int and body["order_side"] in (1, 2)
                        and body.get("qty") == "1" and type(body.get("order_trade_time_type")) is int
                        and body["order_trade_time_type"] == 1 and isinstance(symbol, str) and symbol.startswith("US.")
                        and isinstance(body.get("text"), str) and _CLIENT_ID.fullmatch(body["text"]) is not None)
                    if allowed:
                        _symbol(symbol[3:])
                        allowed = isinstance(body.get("price"), str) and _price(body["price"]) == body["price"]
            elif method == "POST" and path.startswith(base + "orders/") and path.endswith("/cancel"):
                order_id = path[len(base + "orders/"):-len("/cancel")]
                allowed = (_ID.fullmatch(order_id) is not None and params == {}
                           and body == {"market": 100} and type(body.get("market")) is int)
        if not allowed:
            raise BridgeError("Only fixed US sim-trade reads and one-share RTH limit/cancel requests are permitted.")
        return params, body

    def request(self, method, path, *, params=None, json=None):
        if not self.configured:
            raise BridgeError("REST paper backend is NOT_CONFIGURED; no authentication or fallback was attempted.")
        params, body = self._validated_args(method, path, params, json)
        try:
            # Exactly one invocation. POST outcomes are never retried here.
            response = self._request_once(method, API_BASE + path, params=params, json=body, timeout=15.0)
        except Exception:
            raise BridgeError("REST paper request failed or its outcome is unknown; no retry was attempted.") from None
        if (not isinstance(response, dict) or type(response.get("ret_code")) is not int
                or response["ret_code"] != 0 or not isinstance(response.get("data"), dict)):
            # HTTP 200 does not mean success. Do not echo provider bodies/tokens.
            raise BridgeError("REST paper request was not confirmed by a successful response envelope.")
        return deepcopy(response["data"])

    def accounts(self):
        """Explicit discovery, never invoked by adapter construction."""
        return deepcopy(_list(self.request("GET", PREFIX + "accounts"), "accounts"))


class _RestContext:
    """Translate the reviewed REST schema to the shared order-state interface."""

    def __init__(self, transport, account_id):
        self.transport, self.account_id = transport, account_id
        self.base = PREFIX + account_id + "/"

    def _identity(self, kwargs):
        if kwargs.get("trd_env") != "SIMULATE" or kwargs.get("acc_id") != self.account_id:
            raise BridgeError("Every REST paper call requires the selected simulated account explicitly.")

    def accinfo_query(self, **kwargs):
        self._identity(kwargs)
        if kwargs.get("currency") != "USD":
            raise BridgeError("The US paper facade requires USD funds.")
        data = self.transport.request("GET", self.base + "cash-info")
        balance, hold, assets = data.get("balance"), data.get("hold"), data.get("total_asset")
        available = None
        if balance not in (None, "N/A", "") and hold not in (None, "N/A", ""):
            available = str(max(Decimal(0), _decimal(balance, "cash balance") - _decimal(hold, "cash hold")))
        assets = str(_decimal(assets, "USD equity")) if assets not in (None, "N/A", "") else None
        return 0, [{"us_cash": available, "total_assets": assets,
                    "rest_cash_balance": balance, "rest_cash_hold": hold,
                    "cash_source": "max(0,balance-hold); buying power is not cash"}]

    def position_list_query(self, **kwargs):
        self._identity(kwargs)
        data = self.transport.request("GET", self.base + "positions", params={"market": 100})
        rows = []
        for row in _list(data, "positions"):
            symbol = str(row.get("symbol", ""))
            symbol = symbol[3:] if symbol.startswith("US.") else symbol
            _symbol(symbol)
            if row.get("market") not in ("US_STOCK", "US", 2, "2") or row.get("pstn_type") not in ("LONG", 0):
                raise BridgeError("The paper prototype only normalizes confirmed US long-stock positions.")
            quantity = _integer(row.get("qty"), "paper position quantity", minimum=0)
            available = row.get("qty_avbl")
            sellable = (_integer(available, "sellable shares", minimum=0)
                        if available not in (None, "N/A", "") else None)
            if sellable is not None and sellable > quantity:
                raise BridgeError("REST paper sellable shares exceed the position.")
            rows.append({"code": "US." + symbol, "qty": quantity, "can_sell_qty": sellable})
        if len({row["code"] for row in rows}) != len(rows):
            raise BridgeError("Ambiguous duplicate REST paper positions require reconciliation.")
        return 0, rows

    def order_row(self, row):
        for key in ("acc_id", "account_id"):
            if key in row and row[key] != self.account_id:
                raise BridgeError("REST paper order belongs to another account.")
        order_id = _identifier(row.get("order_id"), "order_id")
        symbol = str(row.get("symbol", ""))
        symbol = symbol[3:] if symbol.startswith("US.") else symbol
        _symbol(symbol)
        status, side = row.get("status"), row.get("side")
        if (type(status) is not int or status not in _ORDER_STATUS or type(side) is not int
                or side not in (1, 2)
                or (row.get("market") is not None and (type(row["market"]) is not int or row["market"] != 2))
                or type(row.get("order_type")) is not int or row["order_type"] not in (1, 3)):
            raise BridgeError("REST paper order has an unsupported market, side or status.")
        stamp = row.get("update_time")
        if not isinstance(stamp, str) or not re.fullmatch(r"[0-9]{1,20}", stamp):
            raise BridgeError("REST paper order update_time must be Unix microseconds as text.")
        return {"order_id": order_id, "acc_id": self.account_id, "trd_env": "SIMULATE",
            "code": "US." + symbol, "trd_side": "BUY" if side == 1 else "SELL",
            "order_type": "LIMIT" if row.get("order_type") == 1 else "MARKET",
            "qty": _integer(row.get("qty"), "order quantity"),
            "price": str(_decimal(row.get("price"), "order price")),
            "dealt_qty": _integer(row.get("cum_qty"), "cumulative quantity", minimum=0),
            "dealt_avg_price": str(_decimal(row.get("avg_fill_price"), "cumulative average")),
            "order_status": _ORDER_STATUS[status], "updated_time": stamp.zfill(20),
            "remark": str(row.get("text", ""))}

    def order_list_query(self, **kwargs):
        self._identity(kwargs)
        data = self.transport.request("GET", self.base + "orders", params={"market": 100})
        rows = [self.order_row(row) for row in _list(data, "orders")]
        if len({row["order_id"] for row in rows}) != len(rows):
            raise BridgeError("Ambiguous duplicate REST paper order identities were returned.")
        return 0, rows

    def place_order(self, **kwargs):
        self._identity(kwargs)
        if (kwargs.get("order_type") != "LIMIT" or kwargs.get("time_in_force") != "DAY"
                or kwargs.get("session") != "RTH" or kwargs.get("adjust_limit") != 0
                or kwargs.get("fill_outside_rth") is not False):
            raise BridgeError("Only fixed DAY/RTH paper limits with no automatic price adjustment are supported.")
        side = kwargs.get("trd_side")
        body = {"market": 100, "symbol": kwargs.get("code"), "qty": str(kwargs.get("qty")),
            "order_type": 1, "order_side": 1 if side == "BUY" else 2 if side == "SELL" else 0,
            "price": _price(kwargs.get("price")), "text": kwargs.get("remark"), "order_trade_time_type": 1}
        data = self.transport.request("POST", self.base + "orders", json=body)
        order_id = _identifier(data.get("order_id"), "order_id")
        # An ID acknowledges creation; it is not proof of exchange acceptance or fill.
        return 0, [{"order_id": order_id, "code": kwargs["code"], "order_status": "WAITING_SUBMIT",
                    "dealt_qty": 0, "dealt_avg_price": 0}]

    def modify_order(self, **kwargs):
        self._identity(kwargs)
        if kwargs.get("modify_order_op") != "CANCEL" or kwargs.get("qty") != 0 or kwargs.get("price") != 0:
            raise BridgeError("This REST paper facade supports cancellation only, never generic modification.")
        order_id = _identifier(kwargs.get("order_id"), "order_id")
        data = self.transport.request("POST", self.base + "orders/" + order_id + "/cancel", json={"market": 100})
        if str(data.get("order_id")) != order_id:
            raise BridgeError("The REST cancel acknowledgement has a different order identity.")
        return 0, [{"order_id": order_id, "trd_env": "SIMULATE"}]


class RestPaperAdapter(FutuPaperAdapter):
    """Shared durable order state, separate REST identity, one-share long/cash API."""

    backend = "REST_sim_trade"

    def __init__(self, transport=None, *, account_id=None, account_metadata=None, auth_confirmed=False,
                 state=None, max_order_notional=1000, max_quote_age_seconds=5, persist_state=None):
        super().__init__(context=None, max_order_notional=max_order_notional,
                         max_quote_age_seconds=max_quote_age_seconds, persist_state=persist_state)
        self.reason = "An explicitly reviewed REST transport and selected US paper account are required."
        if transport is None or auth_confirmed is not True or account_id is None or account_metadata is None:
            return
        account_id = _identifier(account_id, "account_id")
        row = dict(account_metadata)
        if (row.get("account_id") != account_id or type(row.get("market_id")) is not int or row["market_id"] != 100
                or type(row.get("broker_id")) is not int or row["broker_id"] != 0
                or type(row.get("account_type")) is not int or row["account_type"] != 1):
            raise BridgeError("Select the exact personal US margin-paper account from sim-trade/accounts; no default or SDK account is allowed.")
        if self.max_order_notional > 1000:
            raise BridgeError("The paper prototype's per-order notional budget cannot exceed 1000 USD.")
        if isinstance(transport, SimOnlyRestTransport):
            if not transport.configured or transport.account_id != account_id:
                raise BridgeError("The REST transport must be bound to the same explicitly selected paper account.")
        elif callable(transport):
            transport = SimOnlyRestTransport(transport, account_id=account_id, auth_confirmed=True)
        else:
            raise BridgeError("Inject a reviewed, single-attempt REST transport callable.")
        self.account_id, self.sdk = account_id, _CONSTANTS
        self.context = _RestContext(transport, account_id)
        self.status, self.reason = "READY", "REST paper account selected; explicit reconciliation is required before submission."
        if state is not None:
            self.restore_state(state)

    def reconcile(self):
        self.requires_reconciliation = True
        try:
            return self._reconcile_rest()
        except Exception:
            self.requires_reconciliation = True
            raise

    def _reconcile_rest(self):
        execution_start = len(self.executions)
        result = super().reconcile()
        matched = any(row.get("status") == "bound_exact_unique_remark_and_economics"
                      for row in result.get("unknown_resolution", []))
        # Read assets again after order snapshots, rather than return the earlier
        # asset view alongside a newly discovered execution. They are still not
        # an atomic broker snapshot: the runtime must compare owned inventory.
        funds = self._rows(self.context.accinfo_query(currency="USD", refresh_cache=True, **self._kwargs()), "funds")
        positions = self._rows(self.context.position_list_query(refresh_cache=True, **self._kwargs()), "positions")
        self._funds, self._positions = deepcopy(funds), deepcopy(positions)
        unresolved = any(intent["status"] == "SUBMISSION_UNKNOWN" for intent in self.intents.values())
        self.requires_reconciliation = unresolved or any(order.get("correction_pending") for order in self.orders.values())
        self.status = "SUBMISSION_UNKNOWN" if unresolved else "READY"
        result.update(status="submission_unknown" if unresolved else "matched" if matched else "queried",
                      funds=funds, positions=positions,
                      new_executions=deepcopy(self.executions[execution_start:]),
                      cash_field="available USD cash=max(0,balance-hold); total_assets=total_asset; missing remains unavailable")
        self._persist()
        return result

    def _resolve_unknown_intents(self, rows):
        # A matching remark on a market order cannot prove our original limit.
        # Do not filter individual rows and accidentally make an ambiguous
        # remark unique: block the entire remark if any type is inconsistent.
        blocked = {row.get("remark") for row in rows if row.get("order_type") != "LIMIT"
                   and row.get("remark") in self.intents
                   and self.intents[row["remark"]].get("order_id") is None}
        resolutions = super()._resolve_unknown_intents([row for row in rows if row.get("remark") not in blocked])
        for row in resolutions:
            if row["client_id"] in blocked:
                row["status"] = "order_type_mismatch_manual_reconciliation_required"
        return resolutions

    def submit_limit(self, *, client_id, symbol, side, quantity, price, quote_at=None, as_of=None):
        self._ready()
        if self.requires_reconciliation or self.status == "SUBMISSION_UNKNOWN":
            raise BridgeError("Reconcile the paper account before a new submission.")
        if _integer(quantity, "paper quantity") != 1:
            raise BridgeError("The controlled REST paper prototype accepts exactly one share.")
        _price(price)
        symbol = _symbol(symbol)
        if client_id in self.intents:
            return super().submit_limit(client_id=client_id, symbol=symbol, side=side, quantity=quantity,
                                        price=price, quote_at=quote_at, as_of=as_of)
        # Never sell a manually held paper share, and never add a second test share.
        owned = sum(row["quantity"] * (1 if row["side"] == "BUY" else -1)
                    for row in self.executions if row["symbol"] == symbol)
        positions = [row for row in self._positions if row["code"] == "US." + symbol]
        held = positions[0]["qty"] if len(positions) == 1 else 0 if not positions else None
        if held != owned or (side == "BUY" and owned != 0) or (side == "SELL" and owned != 1):
            raise BridgeError("Paper inventory differs from the owned one-share test ledger; no manual position is traded.")
        if not self._funds or self._funds[0].get("total_assets") in (None, "N/A", ""):
            raise BridgeError("Verified USD equity is unavailable; buying power is not a substitute.")
        return super().submit_limit(client_id=client_id, symbol=symbol, side=side, quantity=quantity,
                                    price=price, quote_at=quote_at, as_of=as_of)

    def process_rest_order_snapshot(self, row):
        self._ready()
        return self.process_order_snapshot(self.context.order_row(row), trusted_query=True)

    def process_order_snapshot(self, row, *, trusted_query=False):
        previous = self.orders.get(str(row.get("order_id", "")))
        if previous is not None:
            payload = self.intents[previous["client_id"]]["payload"]
            if (("trd_side" in row and row["trd_side"] != payload["side"])
                    or ("qty" in row and row["qty"] != payload["quantity"])
                    or ("order_type" in row and row["order_type"] != "LIMIT")
                    or ("price" in row and _decimal(row["price"]) != _decimal(payload["price"]))):
                self.requires_reconciliation = True
                raise BridgeError("REST paper order economics conflict with the original matched limit intent.")
        return super().process_order_snapshot(row, trusted_query=trusted_query)
