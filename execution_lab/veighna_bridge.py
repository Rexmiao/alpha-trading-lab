"""Local VeighNa event/OMS experiment and an explicitly configured paper backend.

Importing this module opens no socket, imports no broker SDK and reads no account.
SHADOW fills are local model outputs. BROKER_PAPER never falls back to SHADOW.
The old vnpy_futu gateway is deliberately not imported: it unlocks and queries
implicit accounts. A legacy paper adapter only accepts a caller-created context.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import threading
from types import SimpleNamespace


class BridgeError(ValueError):
    """Invalid input, unsafe configuration or unresolved execution state."""


_RUNTIME_LOCK = threading.Lock()
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?\Z")
_TERMINAL = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED"}


def _decimal(value, name="value", *, minimum=Decimal("0")):
    if isinstance(value, bool):
        raise BridgeError(f"{name} cannot be boolean.")
    try:
        number = Decimal(str(value))
    except Exception:
        raise BridgeError(f"{name} must be finite numeric.") from None
    if not number.is_finite() or number < minimum:
        raise BridgeError(f"{name} must be finite and >= {minimum}.")
    return number


def _integer(value, name, minimum=1):
    number = _decimal(value, name)
    if number != number.to_integral_value() or number < minimum:
        raise BridgeError(f"{name} must be an integer >= {minimum}.")
    return int(number)


def _symbol(value):
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise BridgeError("Only uppercase US stock/ETF ticker symbols are accepted.")
    return value


def _at(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise BridgeError("Use a timezone-aware UTC timestamp.") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BridgeError("Use a timezone-aware UTC timestamp.")
    return value.astimezone(timezone.utc)


def _json(value):
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.name
    return value


def _label(value):
    return value.name if isinstance(value, Enum) else str(value)


def _load_vnpy(runtime_dir):
    """Import only after an isolated .vntrader exists; never read home settings."""
    runtime_dir = Path(runtime_dir).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / ".vntrader").mkdir(exist_ok=True)
    if version("vnpy") != "4.5.0":
        raise BridgeError("Use the isolated requirements-veighna.txt environment (vnpy==4.5.0).")
    os.chdir(runtime_dir)
    from vnpy.event import Event, EventEngine
    from vnpy.trader import engine as trader_engine
    from vnpy.trader import utility
    from vnpy.trader.constant import Direction, Exchange, Offset, OrderType, Product, Status
    from vnpy.trader.gateway import BaseGateway
    from vnpy.trader.object import AccountData, ContractData, OrderRequest, PositionData, TickData, TradeData
    from vnpy.trader.setting import SETTINGS
    utility.TRADER_DIR = trader_engine.TRADER_DIR = runtime_dir
    utility.TEMP_DIR = runtime_dir / ".vntrader"
    SETTINGS["log.active"] = False
    return SimpleNamespace(**{key: value for key, value in locals().items() if key[0].isupper()},
                           MainEngine=trader_engine.MainEngine, OmsEngine=trader_engine.OmsEngine)


class ShadowSession:
    """Actual VeighNa MainEngine/OMS with a synchronous, replay-only gateway.

    The deterministic event driver subclasses EventEngine and uses its official
    dispatch method. It intentionally has no timer/network threads or live mode.
    Runtime imports/cwd are process-global in VeighNa, so sessions are exclusive.
    """

    def __init__(self, *, runtime_dir, initial_cash=100000, max_weight=.2, cash_floor=.2,
                 fee_bps=10, max_quote_age_seconds=5):
        if not _RUNTIME_LOCK.acquire(blocking=False):
            raise BridgeError("Another local VeighNa session owns the runtime.")
        self._previous_cwd = Path.cwd()
        self.closed = False
        self.main = None
        try:
            self.initial_cash = self.cash = _decimal(initial_cash, "initial_cash", minimum=Decimal("100"))
            self.max_weight = _decimal(max_weight, "max_weight", minimum=Decimal("0.01"))
            self.cash_floor = _decimal(cash_floor, "cash_floor")
            self.fee_rate = _decimal(fee_bps, "fee_bps") / 10000
            self.max_quote_age_seconds = _integer(max_quote_age_seconds, "max_quote_age_seconds")
            if self.max_weight > 1 or self.cash_floor >= 1 or self.fee_rate > Decimal("0.01"):
                raise BridgeError("Require max_weight<=1, cash_floor<1 and fee_bps<=100.")
            self.api = _load_vnpy(runtime_dir)
            self.holdings, self.quotes = {}, {}
            self.orders, self.trades, self.events = [], [], []
            self.signals, self.targets, self.risk_checks = [], [], []
            self.accounts, self.positions = [], []
            self._signal_hashes, self._quote_versions = {}, {}
            self.clock = None
            self._build_engine()
            self.gateway.publish_account()
        except Exception:
            self.close()
            raise

    def _build_engine(self):
        api, session = self.api, self

        class ReplayEvents(api.EventEngine):
            def __init__(self):
                super().__init__()
                self.pending = deque()
                self.dispatching = False

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

        class LocalMain(api.MainEngine):
            def init_engines(self):
                oms = self.add_engine(api.OmsEngine)
                for name in ("get_all_orders", "get_all_trades", "get_all_positions", "get_all_accounts",
                             "get_all_active_orders", "get_order", "get_tick"):
                    setattr(self, name, getattr(oms, name))

        class LocalGateway(api.BaseGateway):
            default_name = "ALPHA_SHADOW"
            default_setting = {"execution_environment": "SHADOW"}
            exchanges = [api.Exchange.SMART]

            def __init__(self, event_engine, gateway_name):
                super().__init__(event_engine, gateway_name)
                self.active = {}
                self.sequence = 0

            def connect(self, setting):
                if setting != {"execution_environment": "SHADOW"}:
                    raise BridgeError("This gateway only supports a local SHADOW account.")

            def subscribe(self, req):
                _symbol(req.symbol)

            def query_account(self):
                self.publish_account()

            def query_position(self):
                self.publish_account()

            def close(self):
                self.cancel_all()

            def publish_account(self):
                equity = session.equity()
                self.on_account(api.AccountData(accountid="SHADOW", balance=float(equity),
                    frozen=float(equity-session.cash), gateway_name=self.gateway_name))
                session.accounts.append({"as_of": session.clock, "cash": session.cash,
                    "equity": equity, "execution_environment": "SHADOW"})
                for symbol, quantity in session.holdings.items():
                    self.on_position(api.PositionData(symbol=symbol, exchange=api.Exchange.SMART,
                        direction=api.Direction.NET, volume=quantity, gateway_name=self.gateway_name))

            def send_order(self, req):
                if req.type != api.OrderType.MARKET or req.exchange != api.Exchange.SMART:
                    raise BridgeError("The local gateway accepts US market-proxy orders only.")
                self.sequence += 1
                order = req.create_order_data(f"S{self.sequence:06d}", self.gateway_name)
                order.datetime = session.clock
                order.status = api.Status.NOTTRADED
                self.active[order.orderid] = (order, session._quote_versions[req.symbol])
                session.orders.append({"order_id": order.vt_orderid, "symbol": req.symbol,
                    "side": "BUY" if req.direction == api.Direction.LONG else "SELL",
                    "quantity": int(req.volume), "as_of": session.clock, "status": "NOTTRADED",
                    "execution_environment": "SHADOW", "fill_source": "local_price_proxy"})
                self.on_order(deepcopy(order))
                return order.vt_orderid

            def cancel_order(self, req):
                entry = self.active.pop(req.orderid, None)
                if entry:
                    order, _ = entry
                    order.status = api.Status.CANCELLED
                    self._update(order)

            def cancel_all(self):
                for order, _ in list(self.active.values()):
                    self.cancel_order(order.create_cancel_request())

            def _update(self, order):
                row = next(row for row in session.orders if row["order_id"] == order.vt_orderid)
                row.update(status=order.status.name, filled_quantity=int(order.traded))
                self.on_order(deepcopy(order))

            def match(self, symbol, *, scheduled=False):
                quote = session.quotes[symbol]
                for order, created_version in list(self.active.values()):
                    if order.symbol != symbol or (not scheduled and session._quote_versions[symbol] <= created_version):
                        continue
                    price, held = quote["price"], session.holdings.get(symbol, 0)
                    buy = order.direction == api.Direction.LONG
                    quantity = int(order.volume-order.traded)
                    if buy:
                        equity = session.equity()
                        cash_qty = ((session.cash-session.cash_floor*equity) /
                            (price*(1+session.fee_rate*(1-session.cash_floor))))
                        cap_qty = ((session.max_weight*equity-held*price) /
                            (price*(1+session.max_weight*session.fee_rate)))
                        quantity = min(quantity, max(0, int(min(cash_qty, cap_qty).to_integral_value(rounding=ROUND_FLOOR))))
                    else:
                        quantity = min(quantity, held)
                    if quantity:
                        notional = quantity*price
                        fee = notional*session.fee_rate
                        session.cash += (-notional if buy else notional)-fee
                        session.holdings[symbol] = held+(quantity if buy else -quantity)
                        if session.cash < 0 or session.holdings[symbol] < 0:
                            raise BridgeError("SHADOW cash/long-only invariant failed.")
                        order.traded += quantity
                        trade = api.TradeData(symbol=symbol, exchange=api.Exchange.SMART,
                            orderid=order.orderid, tradeid=f"LOCAL{len(session.trades)+1:06d}",
                            direction=order.direction, price=float(price), volume=quantity,
                            datetime=session.clock, gateway_name=self.gateway_name)
                        session.trades.append({"trade_id": trade.vt_tradeid, "order_id": order.vt_orderid,
                            "symbol": symbol, "side": "BUY" if buy else "SELL", "quantity": quantity,
                            "price": price, "fee": fee, "as_of": session.clock, "cash_after": session.cash,
                            "position_after": session.holdings[symbol], "execution_environment": "SHADOW",
                            "fill_source": "local_price_proxy", "broker_deal_id": None})
                        self.on_trade(trade)
                    # A model market order gets one snapshot opportunity. An
                    # unaffordable remainder is cancelled, never silently retried.
                    order.status = api.Status.ALLTRADED if order.traded == order.volume else api.Status.CANCELLED
                    self.active.pop(order.orderid)
                    self._update(order)
                    self.publish_account()

        self.event_engine = ReplayEvents()
        self.main = LocalMain(self.event_engine)
        self.event_engine.register_general(self._capture_event)
        self.gateway = self.main.add_gateway(LocalGateway)
        self.main.connect({"execution_environment": "SHADOW"}, self.gateway.gateway_name)

    def _capture_event(self, event):
        # BaseGateway emits generic and per-symbol events; one generic copy is
        # enough to audit each OMS transition without duplicating ledger entries.
        if event.type in {"eTick.", "eOrder.", "eTrade.", "eAccount.", "ePosition.",
                          "eAlphaSignal", "eAlphaTarget", "eAlphaRisk"}:
            data = event.data if isinstance(event.data, dict) else vars(event.data)
            self.events.append({"sequence": len(self.events)+1, "type": event.type,
                                "data": _json(deepcopy(data))})

    def equity(self):
        return self.cash+sum(quantity*self.quotes[symbol]["price"] for symbol, quantity in self.holdings.items())

    def publish_quote(self, symbol, price, at, *, as_of=None, source="explicit_shadow_input"):
        symbol, price, at = _symbol(symbol), _decimal(price, "price", minimum=Decimal("0.000001")), _at(at)
        as_of = at if as_of is None else _at(as_of)
        age = (as_of-at).total_seconds()
        if age < 0 or age > self.max_quote_age_seconds:
            raise BridgeError("Quote is future-dated or stale; no local fill is permitted.")
        if self.clock is not None and as_of < self.clock:
            raise BridgeError("Market event clock must not move backwards.")
        if symbol in self.quotes and at < self.quotes[symbol]["at"]:
            raise BridgeError("Out-of-order quote rejected.")
        self.clock = as_of
        self.quotes[symbol] = {"price": price, "at": at, "source": str(source)}
        self._quote_versions[symbol] = self._quote_versions.get(symbol, 0)+1
        tick = self.api.TickData(symbol=symbol, exchange=self.api.Exchange.SMART,
            datetime=at, last_price=float(price), gateway_name=self.gateway.gateway_name)
        self.gateway.on_tick(tick)
        self.gateway.match(symbol)

    def submit_targets(self, weights, *, as_of, signal_id, scores=None, reason="strategy_target"):
        as_of = _at(as_of)
        if not isinstance(signal_id, str) or not signal_id or len(signal_id) > 128:
            raise BridgeError("A bounded, stable signal_id is required.")
        if not isinstance(weights, dict) or not weights:
            raise BridgeError("Provide an explicit target for each managed symbol.")
        targets = {_symbol(symbol): _decimal(weight, "target_weight") for symbol, weight in weights.items()}
        payload_hash = hashlib.sha256(json.dumps(_json({"weights": targets, "as_of": as_of}), sort_keys=True).encode()).hexdigest()
        if signal_id in self._signal_hashes:
            if self._signal_hashes[signal_id] != payload_hash:
                raise BridgeError("A signal_id cannot be reused for changed targets.")
            return []
        self._signal_hashes[signal_id] = payload_hash
        signal = {"signal_id": signal_id, "as_of": as_of, "scores": scores or {}, "reason": reason}
        self.signals.append(signal)
        self.event_engine.put(self.api.Event("eAlphaSignal", signal))
        target_row = {"signal_id": signal_id, "as_of": as_of, "weights": targets,
                      "cash_target": 1-sum(targets.values()), "execution_environment": "SHADOW"}
        self.targets.append(target_row)
        self.event_engine.put(self.api.Event("eAlphaTarget", target_row))
        rejection = None
        if any(weight > self.max_weight for weight in targets.values()) or sum(targets.values()) > 1-self.cash_floor:
            rejection = "position_cap_or_cash_floor"
        elif set(self.holdings)-set(targets):
            rejection = "missing_existing_position_target"
        elif any(symbol not in self.quotes for symbol in targets):
            rejection = "missing_quote"
        elif self.clock is None or as_of < self.clock:
            rejection = "stale_signal"
        elif any(not 0 <= (as_of-self.quotes[symbol]["at"]).total_seconds() <= self.max_quote_age_seconds for symbol in targets):
            rejection = "stale_quote"
        risk = {"signal_id": signal_id, "as_of": as_of, "accepted": rejection is None,
                "reason": rejection or "passed", "execution_environment": "SHADOW"}
        self.risk_checks.append(risk)
        self.event_engine.put(self.api.Event("eAlphaRisk", risk))
        if rejection:
            return []
        self.clock = as_of
        self.gateway.cancel_all()
        equity = self.equity()
        reserve = self.fee_rate*((equity-self.cash)+sum(targets.values())*equity)
        capital = max(Decimal(0), equity-reserve)
        deltas = {symbol: int((weight*capital/self.quotes[symbol]["price"]).to_integral_value(rounding=ROUND_FLOOR))
                         - self.holdings.get(symbol, 0) for symbol, weight in targets.items()}
        ids = []
        for side in (-1, 1):
            for symbol, delta in deltas.items():
                if delta*side <= 0:
                    continue
                req = self.api.OrderRequest(symbol=symbol, exchange=self.api.Exchange.SMART,
                    direction=self.api.Direction.LONG if delta > 0 else self.api.Direction.SHORT,
                    type=self.api.OrderType.MARKET, volume=abs(delta), reference=signal_id)
                ids.append(self.main.send_order(req, self.gateway.gateway_name))
        return ids

    def flatten_at_scheduled_open(self, *, at, signal_id):
        """Only for a predetermined replay session end, never a stop-on-data-error."""
        self.gateway.cancel_all()
        self.submit_targets({symbol: 0 for symbol in self.quotes}, as_of=at, signal_id=signal_id,
                            reason="scheduled_last_bar_open_flatten")
        for symbol in self.quotes:
            self.gateway.match(symbol, scheduled=True)

    def report(self, source="explicit_shadow_input"):
        oms_orders = {item.vt_orderid: item for item in self.main.get_all_orders()}
        oms_trade_count = len(self.main.get_all_trades())
        cash = self.initial_cash
        rebuilt = {}
        for trade in self.trades:
            direction = 1 if trade["side"] == "BUY" else -1
            cash -= direction*trade["quantity"]*trade["price"]+trade["fee"]
            rebuilt[trade["symbol"]] = rebuilt.get(trade["symbol"], 0)+direction*trade["quantity"]
        consistent = (cash == self.cash and rebuilt == self.holdings and oms_trade_count == len(self.trades)
                      and len(oms_orders) == len(self.orders))
        return _json({"status": "success" if consistent else "reconciliation_failed",
            "execution_environment": "SHADOW", "broker_status": "NOT_CONFIGURED", "source": source,
            "signals": self.signals, "targets": self.targets, "risk_checks": self.risk_checks,
            "orders": self.orders, "trades": self.trades, "accounts": self.accounts,
            "positions": [{"symbol": key, "quantity": value} for key, value in sorted(self.holdings.items())],
            "reconciliation": {"status": "matched" if consistent else "mismatch", "cash": self.cash,
                "equity": self.equity(), "rebuilt_cash": cash, "oms_order_count": len(oms_orders),
                "oms_trade_count": oms_trade_count, "active_orders": len(self.main.get_all_active_orders()),
                "broker_reconciled": False},
            "events": self.events, "lineage": {"framework": "VeighNa MainEngine + OmsEngine + BaseGateway",
                "event_driver": "synchronous subclass of official EventEngine; deterministic local replay",
                "dependencies": {name: version(name) for name in ("vnpy", "futu-api", "numpy", "pandas", "TA-Lib", "PySide6", "protobuf")},
                "code_sha256": _CODE_SHA256,
                "costs": "fee_bps per actual buy/sell reference-price notional, charged once",
                "fills": "local next-price market proxy; not a broker execution, bid/ask or queue reconstruction",
                "risk": {"max_weight": self.max_weight, "cash_floor": self.cash_floor,
                         "fee_bps": self.fee_rate*10000}, "account_scope": "independent_local_shadow_account"},
            "warnings": ["All SHADOW trades are local simulation outputs; no broker was connected or reconciled.",
                         "This laboratory is not a durable production order manager or a live-trading implementation."]})

    def close(self):
        if getattr(self, "closed", True):
            return
        try:
            if self.main is not None:
                self.main.close()
        finally:
            self.closed = True
            os.chdir(self._previous_cwd)
            _RUNTIME_LOCK.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run_shadow_replay(bars, *, runtime_dir, benchmark="SPY", source="synthetic", initial_cash=100000,
                      lookback_bars=6, max_weight=.2, cash_floor=.2, fee_bps=10):
    """One within-RTH momentum rule through actual VeighNa OMS events, not a benchmark claim."""
    # Reuse the already-audited five-minute input/calendar contract, not its
    # simulated account or daily-date parser. This does not import cloud UI.
    from hf_space.intraday import _validate, _complete_sessions, BAR_DURATION
    frame = _validate(bars, benchmark)
    sessions, coverage = _complete_sessions(frame)
    length = _integer(lookback_bars, "lookback_bars")
    if length > 60:
        raise BridgeError("lookback_bars must be <=60.")
    sessions = [session for session in sessions if len(session["timestamps"]) > length+2]
    with ShadowSession(runtime_dir=runtime_dir, initial_cash=initial_cash, max_weight=max_weight,
                       cash_floor=cash_floor, fee_bps=fee_bps) as session:
        symbols = sorted(set(frame.symbol)-{benchmark})
        for day in sessions:
            stamps = day["timestamps"]
            subset = frame.loc[frame.timestamp.isin(stamps) & frame.symbol.isin(symbols)]
            tables = {key: subset.pivot(index="timestamp", columns="symbol", values=key).reindex(stamps)
                      for key in ("open", "close")}
            for index, stamp in enumerate(stamps):
                terminal = index == len(stamps)-1
                if terminal:
                    session.gateway.cancel_all()
                for symbol in symbols:
                    session.publish_quote(symbol, tables["open"].at[stamp, symbol], stamp.to_pydatetime(), source=source)
                if terminal:
                    session.flatten_at_scheduled_open(at=stamp.to_pydatetime(), signal_id=f'{day["session"]}:EXIT')
                    continue
                available = (stamp+BAR_DURATION).to_pydatetime()
                for symbol in symbols:
                    session.publish_quote(symbol, tables["close"].at[stamp, symbol], available, source=source)
                if index < length or index+1 >= len(stamps)-1:
                    continue
                scores = {symbol: float(tables["close"].iloc[index][symbol]/tables["close"].iloc[index-length][symbol]-1)
                          for symbol in symbols}
                selected = [symbol for symbol in symbols if scores[symbol] > 0]
                weight = min((1-float(cash_floor))/len(selected), float(max_weight)) if selected else 0
                session.submit_targets({symbol: weight if symbol in selected else 0 for symbol in symbols},
                    as_of=available, signal_id=f'{day["session"]}:{index}', scores=scores)
        result = session.report(source)
        result["lineage"]["coverage"] = coverage
        result["lineage"]["strategy"] = {"name": "within_RTH_positive_momentum", "lookback_bars": length,
            "score_unit": "historical_return_not_expected_return", "execution": "next_bar_open_zero_latency_proxy",
            "end_of_day": "last_bar_open_flatten_no_overnight", "benchmark_excluded_from_trading": benchmark}
        if not sessions:
            result["status"] = "insufficient_history"
        return result


class FutuPaperAdapter:
    """Explicit US simulated-account facade; constructor never opens a context.

    root/caller owns context creation, masked account discovery, SDK log path and
    external state durability. No unlock, account discovery, REAL, default account
    index, DealPush, deal query, fee query, or automatic submit retry exists here.
    """

    backend = "legacy_OpenD"

    def __init__(self, context=None, *, sdk=None, account_id=None, account_metadata=None,
                 context_security_firm=None, expected_security_firm=None, state=None,
                 max_order_notional=1000, max_quote_age_seconds=5, persist_state=None):
        self.context, self.sdk = context, sdk
        self.account_id = None
        self.status, self.reason = "NOT_CONFIGURED", "An explicitly selected US paper context/account is required."
        self.orders, self.intents, self.executions, self.corrections = {}, {}, [], []
        self._pending_pushes = {}
        self.cancel_intents = {}
        self.persist_state = persist_state
        if persist_state is not None and not callable(persist_state):
            raise BridgeError("persist_state must be an explicit durable state callback.")
        self._lock = threading.RLock()
        self.requires_reconciliation = True
        self.max_order_notional = _decimal(max_order_notional, "max_order_notional", minimum=Decimal("1"))
        self.max_quote_age_seconds = _integer(max_quote_age_seconds, "max_quote_age_seconds")
        self._funds, self._positions = [], []
        self.security_firm = None
        if context is None:
            return
        if sdk is None or account_metadata is None:
            raise BridgeError("SDK constants and selected account metadata must be explicit.")
        account_id = _integer(account_id, "paper account_id")
        row = dict(account_metadata)
        auth = row.get("trdmarket_auth")
        if (_integer(row.get("acc_id"), "metadata acc_id") != account_id
                or _label(row.get("trd_env")) != "SIMULATE" or _label(row.get("acc_status")) != "ACTIVE"
                or _label(row.get("sim_acc_type")) != "STOCK_AND_OPTION"
                or not isinstance(auth, (list, tuple)) or "US" not in {_label(item) for item in auth}):
            raise BridgeError("Require the exact ACTIVE US STOCK_AND_OPTION SIMULATE account; never fall back.")
        actual_firm, expected = _label(context_security_firm), _label(expected_security_firm)
        if not context_security_firm or not expected_security_firm or actual_firm != expected or actual_firm in {"REAL", "None"}:
            raise BridgeError("Confirm the caller-created context security_firm explicitly.")
        account_firm = _label(row.get("security_firm", "N/A"))
        if account_firm not in {"N/A", "NONE", "None", "", actual_firm}:
            raise BridgeError("Available account security_firm conflicts with the confirmed context.")
        self.account_id, self.security_firm = account_id, {"context": actual_firm, "account": account_firm}
        self.status, self.reason = "READY", "Selected paper account verified; explicit reconciliation is required before submission."
        if state is not None:
            self.restore_state(state)

    def _ready(self):
        if self.status not in {"READY", "SUBMISSION_UNKNOWN"}:
            raise BridgeError(f"Paper backend is {self.status}; there is no SHADOW fallback.")

    def _kwargs(self):
        return {"trd_env": self.sdk.TrdEnv.SIMULATE, "acc_id": self.account_id}

    def _persist(self, *, required=False):
        """The caller must atomically persist/fsync before returning from this sink."""
        if self.persist_state is None:
            if required:
                raise BridgeError("Configure a durable persist_state sink before any paper submission/cancel.")
            return
        try:
            self.persist_state(self.export_state())
        except Exception:
            self.status, self.requires_reconciliation = "PERSISTENCE_FAILED", True
            raise BridgeError("Paper state persistence failed; no further broker submission is permitted.") from None

    def _rows(self, response, operation):
        if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.sdk.RET_OK:
            self.requires_reconciliation = True
            raise BridgeError(f"Paper {operation} failed; no retry or fallback was attempted.")
        table = response[1]
        return table.to_dict("records") if hasattr(table, "to_dict") else list(table)

    def reconcile(self):
        self._ready()
        execution_start = len(self.executions)
        funds = self._rows(self.context.accinfo_query(currency=self.sdk.Currency.USD, refresh_cache=True, **self._kwargs()), "funds")
        positions = self._rows(self.context.position_list_query(refresh_cache=True, **self._kwargs()), "positions")
        orders = self._rows(self.context.order_list_query(refresh_cache=True, **self._kwargs()), "orders")
        self._funds, self._positions = deepcopy(funds), deepcopy(positions)
        resolutions = self._resolve_unknown_intents(orders)
        for row in orders:
            if str(row.get("order_id")) in self.orders:
                self.process_order_snapshot(row, trusted_query=True)
        # A successful query does not resolve an unknown submission without a
        # broker order ID. Human/caller must match its explicit remark first.
        unresolved = any(intent["status"] == "SUBMISSION_UNKNOWN" for intent in self.intents.values())
        self.requires_reconciliation = unresolved or any(order.get("correction_pending") for order in self.orders.values())
        if not unresolved and self.status == "SUBMISSION_UNKNOWN":
            self.status = "READY"
            self._persist()
        return _json({"execution_environment": "BROKER_PAPER", "backend": self.backend,
            "status": "submission_unknown" if unresolved else "queried", "funds": funds,
            "positions": positions, "orders": orders, "new_executions": self.executions[execution_start:],
            "unknown_resolution": resolutions,
            "cash_field": "us_cash; missing stays unavailable; buying power is not cash",
            "durability": "caller must persist export_state before emitting downstream events"})

    def _resolve_unknown_intents(self, rows):
        """A remark is evidence only when unique and all original economics match."""
        resolutions = []
        for client_id, intent in self.intents.items():
            if intent["status"] not in {"SUBMITTING", "SUBMISSION_UNKNOWN"} or intent.get("order_id"):
                continue
            candidates = [row for row in rows if str(row.get("remark", "")) == client_id]
            resolution = {"client_id": client_id, "status": "not_found_still_unknown"}
            if len(candidates) > 1:
                resolution["status"] = "ambiguous_manual_reconciliation_required"
            elif len(candidates) == 1:
                row, payload = candidates[0], intent["payload"]
                try:
                    matches = (bool(row.get("order_id")) and row.get("code") == f'US.{payload["symbol"]}'
                        and _label(row.get("trd_side")) == payload["side"]
                        and _integer(row.get("qty"), "queried qty") == payload["quantity"]
                        and _decimal(row.get("price"), "queried limit") == Decimal(payload["price"])
                        and (row.get("acc_id") is None or str(row["acc_id"]) == str(self.account_id))
                        and (row.get("trd_env") is None or _label(row["trd_env"]) == "SIMULATE"))
                except (BridgeError, KeyError):
                    matches = False
                if not matches:
                    resolution["status"] = "economics_or_account_mismatch_manual_reconciliation_required"
                elif self.persist_state is None:
                    resolution["status"] = "durable_sink_required_still_unknown"
                else:
                    order_id = str(row["order_id"])
                    if order_id in self.orders and self.orders[order_id]["client_id"] != client_id:
                        resolution["status"] = "order_identity_conflict_manual_reconciliation_required"
                    else:
                        self.orders[order_id] = {"client_id": client_id, "quantity": payload["quantity"],
                            "symbol": payload["symbol"], "side": payload["side"], "cum_qty": 0,
                            "cum_notional": "0", "status": "SUBMITTING", "updated_at": None}
                        intent.update(status="ACKNOWLEDGED", order_id=order_id)
                        self._persist(required=True)
                        resolution.update(status="bound_exact_unique_remark_and_economics", order_id=order_id)
            resolutions.append(resolution)
        return resolutions

    def submit_limit(self, *, client_id, symbol, side, quantity, price, quote_at=None, as_of=None):
        with self._lock:
            self._ready()
            if self.requires_reconciliation or self.status == "SUBMISSION_UNKNOWN":
                raise BridgeError("Reconcile the paper account before a new submission.")
            if self.persist_state is None:
                raise BridgeError("Configure a durable persist_state sink before a paper submission.")
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", client_id):
                raise BridgeError("A stable bounded client_id is required.")
            symbol, quantity, price = _symbol(symbol), _integer(quantity, "quantity"), _decimal(price, "limit price", minimum=Decimal("0.01"))
            if side not in {"BUY", "SELL"}:
                raise BridgeError("Paper side must be BUY or SELL; short selling is not supported.")
            payload = {"symbol": symbol, "side": side, "quantity": quantity, "price": str(price)}
            if client_id in self.intents:
                if self.intents[client_id]["payload"] != payload:
                    raise BridgeError("A client_id cannot represent changed order economics.")
                return deepcopy(self.intents[client_id])
            if quote_at is None or as_of is None:
                raise BridgeError("A fresh timestamped quote is required for a paper order.")
            age = (_at(as_of)-_at(quote_at)).total_seconds()
            if not 0 <= age <= self.max_quote_age_seconds:
                raise BridgeError("Paper quote is stale or future-dated; no submission occurred.")
            if quantity*price > self.max_order_notional:
                raise BridgeError("Paper order exceeds the explicit per-order notional budget.")
            if any(order["status"] not in _TERMINAL for order in self.orders.values()):
                raise BridgeError("Reconcile/finish the existing paper order before another submission.")
            if side == "BUY":
                if len(self._funds) != 1 or self._funds[0].get("us_cash") in (None, "N/A", ""):
                    raise BridgeError("USD cash is unavailable; do not substitute buying power or withdrawal cash.")
                if quantity*price > _decimal(self._funds[0]["us_cash"], "USD cash"):
                    raise BridgeError("Paper purchase exceeds queried USD cash.")
            else:
                position = [row for row in self._positions if row.get("code") == f"US.{symbol}"]
                if len(position) != 1 or position[0].get("can_sell_qty") in (None, "N/A", ""):
                    raise BridgeError("Available paper long position is unknown; no short sale is permitted.")
                if quantity > _integer(position[0]["can_sell_qty"], "sellable quantity", minimum=0):
                    raise BridgeError("Paper sell exceeds queried sellable long shares.")
            self.intents[client_id] = {"client_id": client_id, "payload": payload,
                                       "status": "SUBMITTING", "order_id": None}
            self._persist(required=True)
            try:
                response = self.context.place_order(price=float(price), qty=quantity, code=f"US.{symbol}",
                    trd_side=self.sdk.TrdSide.BUY if side == "BUY" else self.sdk.TrdSide.SELL,
                    order_type=self.sdk.OrderType.NORMAL, time_in_force=self.sdk.TimeInForce.DAY,
                    adjust_limit=0, fill_outside_rth=False, session=self.sdk.Session.RTH,
                    remark=client_id, **self._kwargs())
            except Exception:
                self._unknown(client_id)
                raise BridgeError("Paper submission outcome is unknown; query before any further submission.") from None
            # Non-OK does not prove that no order reached a broker. Conservatively
            # treat it as unknown rather than resubmit a possibly accepted intent.
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.sdk.RET_OK:
                self._unknown(client_id)
                raise BridgeError("Paper submission was not confirmed; reconciliation is required.")
            rows = self._rows(response, "submit")
            if len(rows) != 1 or not rows[0].get("order_id"):
                self._unknown(client_id)
                raise BridgeError("Paper response had no unique order identity; do not resubmit.")
            order_id = str(rows[0]["order_id"])
            self.intents[client_id].update(order_id=order_id, status="ACKNOWLEDGED")
            self.orders[order_id] = {"client_id": client_id, "quantity": quantity, "symbol": symbol,
                "side": side, "cum_qty": 0, "cum_notional": "0", "status": "SUBMITTING", "updated_at": None}
            self._persist(required=True)
            for row in [rows[0], *self._pending_pushes.pop(order_id, [])]:
                self.process_order_snapshot(row, trusted_query=True)
            return deepcopy(self.intents[client_id])

    def _unknown(self, client_id):
        self.intents[client_id]["status"] = "SUBMISSION_UNKNOWN"
        self.status, self.requires_reconciliation = "SUBMISSION_UNKNOWN", True
        self._persist(required=True)

    def process_order_snapshot(self, row, *, trusted_query=False):
        """Upsert a matched order only; SDK callbacks have no blanket account trust."""
        with self._lock:
            order_id = str(row.get("order_id", ""))
            if row.get("acc_id") is not None and str(row["acc_id"]) != str(self.account_id):
                return {"status": "ignored_wrong_account"}
            if row.get("trd_env") is not None and _label(row["trd_env"]) != "SIMULATE":
                return {"status": "ignored_wrong_environment"}
            if order_id not in self.orders:
                # A callback can arrive before place_order returns. Buffer only
                # an exact outstanding remark, never an arbitrary account push.
                remark = str(row.get("remark", ""))
                if remark in self.intents and self.intents[remark]["status"] == "SUBMITTING" and order_id:
                    self._pending_pushes.setdefault(order_id, []).append(deepcopy(row))
                    return {"status": "buffered_before_submit_response"}
                return {"status": "ignored_unmatched_order"}
            previous = self.orders[order_id]
            if row.get("code") not in {None, f'US.{previous["symbol"]}'}:
                raise BridgeError("Paper order symbol conflicts with its matched intent.")
            stamp = row.get("updated_time", row.get("update_time"))
            # OpenD US order times are ET local strings; lexicographic order is
            # sufficient within this one order. It is not treated as UTC.
            if stamp and previous["updated_at"] and str(stamp) < previous["updated_at"]:
                return {"status": "ignored_older_snapshot"}
            quantity = _integer(row.get("dealt_qty", 0), "cumulative dealt_qty", minimum=0)
            if quantity > previous["quantity"] or quantity < previous["cum_qty"]:
                self.requires_reconciliation = True
                raise BridgeError("Inconsistent cumulative paper quantity; reconcile before further orders.")
            average = _decimal(row.get("dealt_avg_price", 0), "cumulative average")
            notional = quantity*average
            old_notional = Decimal(previous["cum_notional"])
            execution = None
            if quantity > previous["cum_qty"]:
                delta_qty, delta_notional = quantity-previous["cum_qty"], notional-old_notional
                if average <= 0 or delta_notional <= 0:
                    self.requires_reconciliation = True
                    raise BridgeError("Invalid cumulative paper notional; no invented fill is emitted.")
                if previous.get("correction_pending"):
                    raise BridgeError("Resolve the previous notional correction before deriving another execution.")
                execution = {"order_id": order_id, "client_id": previous["client_id"],
                    "symbol": previous["symbol"], "side": previous["side"], "quantity": delta_qty,
                    "price": str(delta_notional/delta_qty), "notional": str(delta_notional),
                    "cumulative_quantity": quantity, "source": "derived_from_order_cumulative",
                    "execution_environment": "BROKER_PAPER", "broker_deal_id": None}
                previous.update(cum_qty=quantity, cum_notional=str(notional))
                self.executions.append(execution)
                self.requires_reconciliation = True
            elif quantity and notional != old_notional:
                self.corrections.append({"order_id": order_id, "quantity": quantity,
                    "old_notional": str(old_notional), "new_notional": str(notional),
                    "reason": "same_quantity_average_correction_requires_reconciliation"})
                self.requires_reconciliation = True
                previous["correction_pending"] = True
            status = _label(row.get("order_status", previous["status"]))
            if previous["status"] not in _TERMINAL or status in _TERMINAL:
                previous["status"] = status
            if stamp:
                previous["updated_at"] = str(stamp)
            self.intents[previous["client_id"]]["status"] = previous["status"]
            self._persist()
            return {"status": "updated", "execution": deepcopy(execution)}

    def cancel(self, order_id):
        self._ready()
        order_id = str(order_id)
        if order_id not in self.orders:
            raise BridgeError("Only a matched order in the selected paper account can be cancelled.")
        if self.orders[order_id]["status"] in _TERMINAL:
            return {"status": self.orders[order_id]["status"]}
        if order_id in self.cancel_intents:
            return {"status": "CANCEL_PENDING", "order_id": order_id}
        if self.persist_state is None:
            raise BridgeError("Configure a durable persist_state sink before a paper cancellation.")
        self.cancel_intents[order_id] = {"status": "SUBMITTING"}
        self._persist(required=True)
        try:
            response = self.context.modify_order(modify_order_op=self.sdk.ModifyOrderOp.CANCEL,
                order_id=order_id, qty=0, price=0, adjust_limit=0, **self._kwargs())
            self._rows(response, "cancel")
        except Exception:
            self.cancel_intents[order_id]["status"] = "SUBMISSION_UNKNOWN"
            self.requires_reconciliation = True
            self._persist(required=True)
            raise BridgeError("Paper cancel outcome is unknown; query rather than cancel again.") from None
        self.cancel_intents[order_id]["status"] = "ACKNOWLEDGED"
        self._persist(required=True)
        self.requires_reconciliation = True
        # A successful cancel RPC is an acknowledgement, not a final fill state.
        return {"status": "CANCEL_PENDING", "order_id": order_id}

    def export_state(self):
        return deepcopy({"schema": 1, "backend": self.backend, "execution_environment": "BROKER_PAPER",
            "account_id": self.account_id, "orders": self.orders, "intents": self.intents,
            "executions": self.executions, "corrections": self.corrections,
            "cancel_intents": self.cancel_intents})

    def restore_state(self, state):
        if (state.get("schema") != 1 or state.get("backend") != self.backend
                or state.get("execution_environment") != "BROKER_PAPER"
                or state.get("account_id") != self.account_id):
            raise BridgeError("Paper state belongs to another environment/backend/account.")
        self.orders, self.intents = deepcopy(state["orders"]), deepcopy(state["intents"])
        self.executions, self.corrections = deepcopy(state["executions"]), deepcopy(state["corrections"])
        self.cancel_intents = deepcopy(state.get("cancel_intents", {}))
        for intent in self.intents.values():
            if intent["status"] == "SUBMITTING":
                intent["status"] = "SUBMISSION_UNKNOWN"
        if any(intent["status"] == "SUBMISSION_UNKNOWN" for intent in self.intents.values()):
            self.status = "SUBMISSION_UNKNOWN"
        self.requires_reconciliation = True
        self._persist()


def paper_backend_status(backend="legacy_OpenD"):
    if backend not in {"legacy_OpenD", "REST_sim_trade"}:
        raise BridgeError("Unknown paper backend.")
    return {"execution_environment": "BROKER_PAPER", "backend": backend, "status": "NOT_CONFIGURED",
        "reason": "An explicitly verified account/context is required; REST OAuth and legacy SDK account IDs are separate.",
        "shadow_fallback": False, "real_trading_supported": False}
