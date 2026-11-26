"""VeighNa OMS projection and routing for one explicitly bound paper adapter.

The adapter/SQLite journal remain the only execution truth. This module never
authenticates, opens a broker connection, retries, matches a price, maintains a
cash ledger or submits during recovery. sync_from_state is called after commit.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import threading

from .veighna_bridge import BridgeError, _RUNTIME_LOCK, _at, _decimal, _integer, _load_vnpy, _symbol


_TERMINAL = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED"}
_STATUSES = {"SUBMITTING", "ACKNOWLEDGED", "SUBMISSION_UNKNOWN", "WAITING_SUBMIT", "SUBMITTED",
             "FILLED_PART", *_TERMINAL}
_CLIENT = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")


def _same(left, right):
    return type(left) is type(right) and left == right


class PaperGatewaySession:
    """Real MainEngine → BaseGateway → the same controlled paper adapter.

    Process-global VeighNa imports/cwd require an exclusive runtime session.
    Projection has its own short RLock; no such lock is held over a broker RPC.
    Account/position objects are deliberately omitted: adapter state does not
    contain the complete broker fields needed by those VeighNa object schemas.
    """

    order_path = "veighna_main_engine_paper_gateway"

    def __init__(self, runtime_dir, adapter, *, clock=None):
        self.adapter = adapter
        self.backend, self.account_id = getattr(adapter, "backend", None), getattr(adapter, "account_id", None)
        if (self.backend not in {"legacy_OpenD", "REST_sim_trade"}
                or getattr(adapter, "status", None) not in {"READY", "SUBMISSION_UNKNOWN"}
                or isinstance(self.account_id, bool) or not isinstance(self.account_id, (str, int))
                or not str(self.account_id) or not callable(getattr(adapter, "submit_limit", None))
                or not callable(getattr(adapter, "export_state", None))):
            raise BridgeError("A configured, explicitly selected BROKER_PAPER adapter is required; no SHADOW fallback.")
        if not _RUNTIME_LOCK.acquire(blocking=False):
            raise BridgeError("Another local VeighNa session owns the runtime.")
        self._previous_cwd, self.closed, self.main = Path.cwd(), False, None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._projection_lock = threading.RLock()
        self._orders, self._trades, self._state = {}, {}, None
        self.events = deque(maxlen=2000)
        self.route_count = self.cancel_route_count = 0
        self.projection_failed = False
        self.last_projection_error = None
        self._last_observed_at = None
        try:
            self.api = _load_vnpy(runtime_dir)
            self._build_engine()
            # Reconstructing OMS from restored adapter state cannot submit.
            self.sync_from_state(adapter.export_state())
        except Exception:
            self.close()
            raise

    def _build_engine(self):
        api, session = self.api, self

        class SynchronousEvents(api.EventEngine):
            def __init__(self):
                super().__init__()
                self.pending, self.dispatching = deque(), False

            def start(self):
                self._active = True

            def stop(self):
                self._active = False

            def put(self, event):
                self.pending.append(event)
                if self.dispatching:
                    return
                self.dispatching = True
                try:
                    while self.pending:
                        self._process(self.pending.popleft())
                finally:
                    self.dispatching = False

        class PaperMain(api.MainEngine):
            def init_engines(self):
                oms = self.add_engine(api.OmsEngine)
                for name in ("get_all_orders", "get_all_trades", "get_all_positions", "get_all_accounts",
                             "get_all_active_orders", "get_order", "get_tick"):
                    setattr(self, name, getattr(oms, name))

        class PaperGateway(api.BaseGateway):
            default_name = "ALPHA_BROKER_PAPER"
            default_setting = {"execution_environment": "BROKER_PAPER"}
            exchanges = [api.Exchange.SMART]

            def connect(self, setting):
                if setting != self.default_setting:
                    raise BridgeError("The local paper gateway cannot create or select another environment.")

            def subscribe(self, req):
                raise BridgeError("Quotes belong to the explicitly configured runtime provider.")

            def query_account(self):
                return None

            def query_position(self):
                return None

            def close(self):
                # Closing a view is not an instruction to cancel or flatten.
                return None

            def send_order(self, req):
                session._ready()
                if (req.exchange != api.Exchange.SMART or req.type != api.OrderType.LIMIT
                        or req.direction not in {api.Direction.LONG, api.Direction.SHORT}
                        or req.offset != api.Offset.NONE or not _CLIENT.fullmatch(req.reference or "")
                        or _integer(req.volume, "paper shares") != 1):
                    raise BridgeError("The paper gateway accepts explicit one-share US long/cash limit requests only.")
                context = getattr(req, "extra", None)
                if not isinstance(context, dict) or set(context) != {"quote_at", "as_of", "limit_price"}:
                    raise BridgeError("The runtime must attach explicit quote and submission timestamps.")
                if _decimal(req.price) != _decimal(context["limit_price"]):
                    raise BridgeError("OrderRequest and original limit economics differ.")
                session.route_count += 1
                try:
                    receipt = session.adapter.submit_limit(client_id=req.reference, symbol=_symbol(req.symbol),
                        side="BUY" if req.direction == api.Direction.LONG else "SELL", quantity=1,
                        price=context["limit_price"], quote_at=context["quote_at"], as_of=context["as_of"])
                except Exception:
                    session._sync_after_rpc()
                    raise
                session._sync_after_rpc()
                context["receipt"] = deepcopy(receipt)
                return f"{self.gateway_name}.{req.reference}"

            def cancel_order(self, req):
                session._ready()
                state = session.adapter.export_state()
                session._check_identity(state)
                intent = state.get("intents", {}).get(req.orderid)
                order_id = intent.get("order_id") if isinstance(intent, dict) else None
                owned = state.get("orders", {}).get(order_id)
                if (not owned or owned.get("client_id") != req.orderid or req.exchange != api.Exchange.SMART
                        or intent["payload"]["symbol"] != req.symbol):
                    raise BridgeError("Cancel only an adapter-owned matched order in this paper account.")
                session.cancel_route_count += 1
                try:
                    return session.adapter.cancel(order_id)
                finally:
                    session._sync_after_rpc()

        self.event_engine = SynchronousEvents()
        self.main = PaperMain(self.event_engine)
        self.event_engine.register_general(self._capture_event)
        self.gateway = self.main.add_gateway(PaperGateway)
        self.main.connect({"execution_environment": "BROKER_PAPER"}, self.gateway.gateway_name)

    def _capture_event(self, event):
        if event.type in {"eOrder.", "eTrade."}:
            self.events.append({"type": event.type, "data": deepcopy(vars(event.data))})

    def _ready(self):
        if self.closed or self.projection_failed:
            raise BridgeError("The paper OMS is closed or requires projection reconciliation.")
        if (self.adapter.backend != self.backend or not _same(self.adapter.account_id, self.account_id)
                or self.adapter.status not in {"READY", "SUBMISSION_UNKNOWN"}):
            raise BridgeError("The bound paper adapter identity or readiness changed.")

    def _check_identity(self, state):
        if (not isinstance(state, dict) or type(state.get("schema")) is not int or state["schema"] != 1
                or state.get("backend") != self.backend or not _same(state.get("account_id"), self.account_id)
                or state.get("execution_environment") != "BROKER_PAPER"):
            raise BridgeError("OMS state belongs to another backend/account/environment.")

    def __call__(self, **payload):
        return self.submit_limit(**payload)

    def submit_limit(self, *, client_id, symbol, side, quantity, price, quote_at=None, as_of=None):
        self._ready()
        if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id) or side not in {"BUY", "SELL"}:
            raise BridgeError("Use a stable client ID and an explicit BUY/SELL paper side.")
        if _integer(quantity, "paper shares") != 1:
            raise BridgeError("The controlled paper OMS accepts exactly one share.")
        limit = _decimal(price, "limit", minimum=Decimal("0.01"))
        req = self.api.OrderRequest(symbol=_symbol(symbol), exchange=self.api.Exchange.SMART,
            direction=self.api.Direction.LONG if side == "BUY" else self.api.Direction.SHORT,
            type=self.api.OrderType.LIMIT, volume=1, price=float(limit),
            reference=client_id)
        # Keep exact original decimal text through the float-typed VeighNa view;
        # durable client IDs must not acquire changed economics on retry.
        req.extra = {"quote_at": _at(quote_at), "as_of": _at(as_of), "limit_price": str(limit)}
        # The actual MainEngine method must route this OrderRequest to BaseGateway.
        vt_orderid = self.main.send_order(req, self.gateway.gateway_name)
        if vt_orderid != f"{self.gateway.gateway_name}.{client_id}" or "receipt" not in req.extra:
            raise BridgeError("The paper gateway did not return the same controlled adapter receipt.")
        return deepcopy(req.extra["receipt"])

    def _sync_after_rpc(self):
        # A failing durable sink must not turn uncommitted memory into OMS truth.
        if self.adapter.status == "PERSISTENCE_FAILED":
            self.projection_failed = True
            self.last_projection_error = "Uncommitted adapter memory was not projected."
            return
        try:
            self.sync_from_state(self.adapter.export_state())
        except Exception:
            self.projection_failed = True
            self.last_projection_error = "Paper OMS projection failed; durable broker truth remains unchanged."
            raise BridgeError(self.last_projection_error) from None

    def _projection_plan(self, state):
        self._check_identity(state)
        intents, orders, executions = state.get("intents"), state.get("orders"), state.get("executions")
        if not isinstance(intents, dict) or not isinstance(orders, dict) or not isinstance(executions, list):
            raise BridgeError("Paper state requires complete intent, order and execution collections.")
        if self._state is not None and (not set(self._state["intents"]) <= set(intents)
                                        or not set(self._state["orders"]) <= set(orders)):
            raise BridgeError("A projected paper intent/order cannot disappear.")
        plan = {}
        for client_id, intent in intents.items():
            if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id) or not isinstance(intent, dict):
                raise BridgeError("Invalid durable paper intent identity.")
            payload = intent.get("payload", {})
            if payload.get("side") not in {"BUY", "SELL"}:
                raise BridgeError("Only explicit long/cash paper sides can be projected.")
            normalized = {"symbol": _symbol(payload.get("symbol")), "side": payload["side"],
                "quantity": _integer(payload.get("quantity"), "durable shares"),
                "price": str(_decimal(payload.get("price"), "durable limit", minimum=Decimal("0.0001")))}
            order_id = intent.get("order_id")
            row = orders.get(order_id) if order_id is not None else None
            if order_id is not None and (not isinstance(row, dict) or row.get("client_id") != client_id):
                raise BridgeError("A durable broker order must map to its exact original intent.")
            if row is not None and (row.get("symbol") != normalized["symbol"] or row.get("side") != normalized["side"]
                    or _integer(row.get("quantity"), "broker quantity") != normalized["quantity"]):
                raise BridgeError("Durable broker order economics conflict with their intent.")
            status = row.get("status") if row is not None else intent.get("status")
            if status not in _STATUSES:
                raise BridgeError("Unsupported durable paper order status.")
            cumulative = _integer(row.get("cum_qty", 0), "cumulative shares", minimum=0) if row else 0
            if cumulative > normalized["quantity"]:
                raise BridgeError("Cumulative paper shares exceed the original order.")
            stamp = row.get("updated_at") if row else None
            if stamp is not None and not isinstance(stamp, str):
                raise BridgeError("A source order timestamp must preserve its documented textual basis.")
            entry = {"payload": normalized, "broker_order_id": order_id, "status": status,
                     "cumulative": cumulative, "source_updated_at": stamp}
            old = self._orders.get(client_id)
            if old and (old["payload"] != normalized or (old["broker_order_id"] is not None and old["broker_order_id"] != order_id)
                    or cumulative < old["cumulative"] or (old["status"] in _TERMINAL and status != old["status"])
                    or (old["source_updated_at"] and (not stamp or stamp < old["source_updated_at"]))):
                raise BridgeError("Paper OMS status, economics, quantity or source time cannot regress.")
            plan[client_id] = entry
        if len({row["client_id"] for row in orders.values()}) != len(orders) or any(row["client_id"] not in intents for row in orders.values()):
            raise BridgeError("Broker order identities must have one-to-one local ownership.")
        trades, by_order = {}, {}
        for row in executions:
            if not isinstance(row, dict) or row.get("source") != "derived_from_order_cumulative" or row.get("broker_deal_id") is not None:
                raise BridgeError("Only explicitly labelled cumulative-order-derived executions can be projected.")
            order_id = row.get("order_id")
            owner = orders.get(order_id)
            if (owner is None or row.get("client_id") != owner["client_id"] or row.get("symbol") != owner["symbol"]
                    or row.get("side") != owner["side"] or row.get("execution_environment") != "BROKER_PAPER"):
                raise BridgeError("An execution must belong to this exact durable paper order.")
            cumulative = _integer(row.get("cumulative_quantity"), "execution cumulative")
            quantity = _integer(row.get("quantity"), "execution increment")
            price = str(_decimal(row.get("price"), "execution price", minimum=Decimal("0.0001")))
            key = hashlib.sha256(json.dumps([self.backend, self.account_id, order_id, cumulative],
                                           separators=(",", ":")).encode()).hexdigest()
            item = {"client_id": owner["client_id"], "symbol": row["symbol"], "side": row["side"],
                    "broker_order_id": order_id, "cumulative": cumulative, "quantity": quantity, "price": price}
            if key in trades and trades[key] != item or key in self._trades and self._trades[key] != item:
                raise BridgeError("An existing derived execution cannot be changed or replaced.")
            if key not in trades:
                by_order.setdefault(order_id, []).append(item)
            trades[key] = item
        if not set(self._trades) <= set(trades):
            raise BridgeError("A durable execution cannot disappear from an OMS snapshot.")
        for order_id, row in orders.items():
            previous = 0
            for item in sorted(by_order.get(order_id, []), key=lambda item: item["cumulative"]):
                if item["cumulative"] - previous != item["quantity"]:
                    raise BridgeError("Derived paper execution increments do not match cumulative quantities.")
                previous = item["cumulative"]
            if previous != row["cum_qty"]:
                raise BridgeError("Durable cumulative fills require their corresponding execution records.")
        return plan, trades

    def sync_from_state(self, state):
        """Project a full committed state; never query, submit, cancel or persist."""
        if self.closed:
            raise BridgeError("The paper OMS session is closed.")
        with self._projection_lock:
            orders, trades = self._projection_plan(deepcopy(state))
            changes = [(key, row) for key, row in orders.items() if self._orders.get(key) != row]
            new_trades = [(key, row) for key, row in trades.items() if key not in self._trades]
            observed_at = _at(self._clock())
            if (changes or new_trades) and self._last_observed_at is not None and observed_at < self._last_observed_at:
                raise BridgeError("OMS observation time moved backward; reconcile before new orders.")
            status_map = {"SUBMITTED": self.api.Status.NOTTRADED, "FILLED_PART": self.api.Status.PARTTRADED,
                "FILLED_ALL": self.api.Status.ALLTRADED, "CANCELLED_ALL": self.api.Status.CANCELLED,
                "CANCELLED_PART": self.api.Status.CANCELLED, "FAILED": self.api.Status.REJECTED,
                "DISABLED": self.api.Status.REJECTED, "DELETED": self.api.Status.CANCELLED}
            for client_id, row in changes:
                payload = row["payload"]
                req = self.api.OrderRequest(symbol=payload["symbol"], exchange=self.api.Exchange.SMART,
                    direction=self.api.Direction.LONG if payload["side"] == "BUY" else self.api.Direction.SHORT,
                    type=self.api.OrderType.LIMIT, volume=payload["quantity"], price=float(payload["price"]), reference=client_id)
                item = req.create_order_data(client_id, self.gateway.gateway_name)
                item.status = status_map.get(row["status"], self.api.Status.SUBMITTING)
                item.traded, item.datetime = row["cumulative"], observed_at
                item.extra = self._extra(row, observed_at)
                self.gateway.on_order(item)
            for trade_id, row in new_trades:
                item = self.api.TradeData(symbol=row["symbol"], exchange=self.api.Exchange.SMART,
                    orderid=row["client_id"], tradeid="DERIVED_" + trade_id,
                    direction=self.api.Direction.LONG if row["side"] == "BUY" else self.api.Direction.SHORT,
                    price=float(row["price"]), volume=row["quantity"], datetime=observed_at,
                    gateway_name=self.gateway.gateway_name)
                item.extra = {**self._extra(row, observed_at), "source": "derived_from_order_cumulative",
                              "broker_deal_id": None, "cumulative_quantity": row["cumulative"]}
                self.gateway.on_trade(item)
            self._orders, self._trades, self._state = orders, trades, deepcopy(state)
            if changes or new_trades:
                self._last_observed_at = observed_at
            return {"order_updates": len(changes), "new_trades": len(new_trades), "broker_rpc": False}

    def _extra(self, row, at):
        return {"execution_environment": "BROKER_PAPER", "backend": self.backend, "account_id": self.account_id,
            "broker_order_id": row["broker_order_id"], "timestamp_basis": "projection_observed_at",
            "observed_at": at.isoformat(), "source_updated_at": row.get("source_updated_at"),
            "broker_order_status": row.get("status")}

    def report(self):
        return {"execution_environment": "BROKER_PAPER", "backend": self.backend, "account_id": self.account_id,
            "framework": "VeighNa MainEngine + OmsEngine + BaseGateway", "oms_order_count": len(self.main.get_all_orders()),
            "oms_trade_count": len(self.main.get_all_trades()), "route_count": self.route_count,
            "cancel_route_count": self.cancel_route_count, "projection_failed": self.projection_failed,
            "account_projection": "unavailable: complete broker balance/frozen fields are not present in adapter state",
            "position_projection": "unavailable: durable executions are not a complete broker position snapshot",
            "cash_ledger": "none; use the runtime journal and queried broker account",
            "trade_source": "derived_from_order_cumulative; not official broker deal records",
            "broker_connection_created": False, "recovery_submits": 0, "close_cancels": False}

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                if self.main is not None:
                    self.main.close()
            finally:
                import os
                os.chdir(self._previous_cwd)
                _RUNTIME_LOCK.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
