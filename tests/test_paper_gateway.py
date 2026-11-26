"""Actual VeighNa MainEngine/OMS with a fake, explicitly bound paper adapter."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import threading

import pytest

from execution_lab.paper_gateway import PaperGatewaySession
from execution_lab.veighna_bridge import BridgeError


AT = datetime(2024, 3, 11, 14, 0, tzinfo=timezone.utc)


class FakePaper:
    backend, account_id, status = "REST_sim_trade", "000123", "READY"

    def __init__(self, state=None):
        self.state = deepcopy(state) if state is not None else {"schema": 1, "backend": self.backend,
            "account_id": self.account_id, "execution_environment": "BROKER_PAPER", "orders": {},
            "intents": {}, "executions": [], "corrections": [], "cancel_intents": {}}
        self.calls, self.cancel_calls, self.committed = [], [], []
        self.observer = None
        self.timeout_submit = self.threaded_callback = False

    def export_state(self):
        return deepcopy(self.state)

    def persist(self):
        self.committed.append(self.export_state())
        if self.observer:
            if self.threaded_callback:
                errors = []
                def publish():
                    try:
                        self.observer(self.export_state())
                    except Exception as error:
                        errors.append(error)
                thread = threading.Thread(target=publish, daemon=True)
                thread.start()
                thread.join(2)
                assert not thread.is_alive(), "Projection lock was held across adapter RPC"
                if errors:
                    raise errors[0]
            else:
                self.observer(self.export_state())

    def submit_limit(self, **args):
        if self.status == "SUBMISSION_UNKNOWN":
            raise BridgeError("Unknown submission remains blocked")
        self.calls.append(deepcopy(args))
        key = args["client_id"]
        payload = {name: args[name] for name in ("symbol", "side", "quantity")}
        payload["price"] = str(args["price"])
        self.state["intents"][key] = {"client_id": key, "payload": payload,
                                       "status": "SUBMITTING", "order_id": None}
        self.persist()
        if self.timeout_submit:
            self.status = self.state["intents"][key]["status"] = "SUBMISSION_UNKNOWN"
            self.persist()
            raise BridgeError("Unknown fake submission; no retry")
        self.state["intents"][key].update(status="SUBMITTED", order_id="0099")
        self.state["orders"]["0099"] = {"client_id": key, "symbol": args["symbol"], "side": args["side"],
            "quantity": args["quantity"], "cum_qty": 0, "cum_notional": "0", "status": "SUBMITTED",
            "updated_at": "00001710165600000000"}
        self.persist()
        return deepcopy(self.state["intents"][key])

    def fill(self):
        row = self.state["orders"]["0099"]
        row.update(cum_qty=1, cum_notional="99.9", status="FILLED_ALL", updated_at="00001710165610000000")
        self.state["intents"][row["client_id"]]["status"] = "FILLED_ALL"
        self.state["executions"].append({"order_id": "0099", "client_id": row["client_id"],
            "symbol": row["symbol"], "side": row["side"], "quantity": 1, "price": "99.9", "notional": "99.9",
            "cumulative_quantity": 1, "source": "derived_from_order_cumulative",
            "execution_environment": "BROKER_PAPER", "broker_deal_id": None})
        self.persist()

    def cancel(self, order_id):
        self.cancel_calls.append(order_id)
        self.state["cancel_intents"][order_id] = {"status": "ACKNOWLEDGED"}
        self.persist()
        return {"status": "CANCEL_PENDING", "order_id": order_id}


def submit(session):
    return session(client_id="stable_intent_1", symbol="NVDA", side="BUY", quantity=1,
                   price=100, quote_at=AT, as_of=AT)


def test_true_mainengine_gateway_orderrequest_routes_to_same_adapter(tmp_path, monkeypatch):
    fake, cwd = FakePaper(), Path.cwd()
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        from vnpy.trader.engine import MainEngine, OmsEngine
        from vnpy.trader.gateway import BaseGateway
        from vnpy.trader.object import OrderRequest
        assert isinstance(session.main, MainEngine) and isinstance(session.main.engines["oms"], OmsEngine)
        assert isinstance(session.gateway, BaseGateway) and set(session.main.engines) == {"oms"}
        seen, original = [], session.main.send_order
        def observed(req, gateway_name):
            assert isinstance(req, OrderRequest) and req.reference == "stable_intent_1"
            seen.append(req)
            return original(req, gateway_name)
        monkeypatch.setattr(session.main, "send_order", observed)
        fake.observer = session.sync_from_state
        receipt = submit(session)
        assert len(seen) == len(fake.calls) == 1
        assert receipt["order_id"] == "0099" and session.route_count == 1
        item = session.main.get_all_orders()[0]
        assert item.orderid == "stable_intent_1" and item.extra["broker_order_id"] == "0099"
        assert item.status == session.api.Status.NOTTRADED and item.traded == 0
        assert not session.main.get_all_trades()
        assert session.order_path == "veighna_main_engine_paper_gateway"
        assert not session.main.get_all_accounts() and not session.main.get_all_positions()
        assert "unavailable" in session.report()["account_projection"]
    assert Path.cwd() == cwd and not fake.cancel_calls


def test_cumulative_fill_projects_once_with_derived_id_and_observation_time(tmp_path):
    fake = FakePaper()
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        fake.observer = session.sync_from_state
        submit(session)
        fake.fill()
        assert session.sync_from_state(fake.export_state()) == {"order_updates": 0, "new_trades": 0, "broker_rpc": False}
        assert len(session.main.get_all_trades()) == 1
        item = session.main.get_all_trades()[0]
        assert item.tradeid.startswith("DERIVED_") and item.extra["broker_deal_id"] is None
        assert item.extra["source"] == "derived_from_order_cumulative"
        assert item.extra["timestamp_basis"] == "projection_observed_at" and item.datetime == AT
        assert item.orderid == "stable_intent_1" and item.volume == 1 and item.price == 99.9
        assert session.main.get_all_orders()[0].status == session.api.Status.ALLTRADED
        assert not session.main.get_all_active_orders()
        assert sum(event["type"] == "eTrade." for event in session.events) == 1


def test_recovery_reconstructs_same_oms_trade_without_rpc_or_cancel_on_close(tmp_path):
    fake = FakePaper()
    with PaperGatewaySession(tmp_path / "one", fake, clock=lambda: AT) as session:
        submit(session)
        fake.fill()
        session.sync_from_state(fake.export_state())
        trade_id = session.main.get_all_trades()[0].vt_tradeid
    restored = FakePaper(fake.export_state())
    with PaperGatewaySession(tmp_path / "two", restored, clock=lambda: AT) as session:
        assert session.main.get_all_trades()[0].vt_tradeid == trade_id
        assert session.report()["oms_order_count"] == session.report()["oms_trade_count"] == 1
        assert not restored.calls and not restored.cancel_calls
        session.sync_from_state(restored.export_state())
        assert len(session.main.get_all_trades()) == 1
    assert not restored.cancel_calls


@pytest.mark.parametrize("change", [{"backend": "legacy_OpenD"}, {"account_id": "123"},
    {"account_id": 123}, {"execution_environment": "SHADOW"}, {"schema": True}])
def test_wrong_namespace_rejected_before_any_oms_projection(tmp_path, change):
    fake = FakePaper()
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        with pytest.raises(BridgeError, match="another"):
            session.sync_from_state({**fake.export_state(), **change})
        assert not session.main.get_all_orders() and not fake.calls


@pytest.mark.parametrize("change", ["quantity", "terminal", "time", "execution", "intent"])
def test_durable_terminal_quantity_time_or_execution_never_regresses(tmp_path, change):
    fake = FakePaper()
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        submit(session)
        fake.fill()
        state = fake.export_state()
        session.sync_from_state(state)
        bad = deepcopy(state)
        if change == "quantity":
            bad["orders"]["0099"]["cum_qty"] = 0
        elif change == "terminal":
            bad["orders"]["0099"]["status"] = "SUBMITTED"
        elif change == "time":
            bad["orders"]["0099"]["updated_at"] = "00001710165000000000"
        elif change == "execution":
            bad["executions"] = []
        else:
            bad["intents"] = {}
        before = len(session.events)
        with pytest.raises(BridgeError):
            session.sync_from_state(bad)
        assert len(session.events) == before
        assert len(session.main.get_all_trades()) == 1
        assert session.main.get_all_orders()[0].status == session.api.Status.ALLTRADED


def test_cancel_only_owned_order_uses_mainengine_and_close_has_no_side_effect(tmp_path):
    fake = FakePaper()
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        submit(session)
        item = session.main.get_all_orders()[0]
        request = item.create_cancel_request()
        session.main.cancel_order(request, session.gateway.gateway_name)
        assert fake.cancel_calls == ["0099"] and session.cancel_route_count == 1
        request.orderid = "not_owned"
        with pytest.raises(BridgeError, match="owned"):
            session.main.cancel_order(request, session.gateway.gateway_name)
    assert fake.cancel_calls == ["0099"]


def test_no_session_projection_lock_across_adapter_rpc_callback(tmp_path):
    fake = FakePaper()
    fake.threaded_callback = True
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        fake.observer = session.sync_from_state
        submit(session)
        assert session.report()["oms_order_count"] == 1
        assert len(fake.committed) == 2


def test_mainengine_float_view_preserves_original_decimal_order_economics(tmp_path):
    fake = FakePaper()
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        session(client_id="precise_limit", symbol="NVDA", side="BUY", quantity=1,
                price="100.00", quote_at=AT, as_of=AT)
        assert fake.calls[0]["price"] == "100.00"
        assert fake.export_state()["intents"]["precise_limit"]["payload"]["price"] == "100.00"


def test_unknown_submission_persists_order_without_inventing_fill_or_retry(tmp_path):
    fake = FakePaper()
    fake.timeout_submit = True
    with PaperGatewaySession(tmp_path / "vnpy", fake, clock=lambda: AT) as session:
        fake.observer = session.sync_from_state
        with pytest.raises(BridgeError, match="Unknown"):
            submit(session)
        item = session.main.get_all_orders()[0]
        assert item.status == session.api.Status.SUBMITTING
        assert item.extra["broker_order_id"] is None and item.extra["broker_order_status"] == "SUBMISSION_UNKNOWN"
        with pytest.raises(BridgeError):
            submit(session)
        assert len(fake.calls) == 1 and not session.main.get_all_trades()


def test_unconfigured_adapter_does_not_initialize_vnpy_or_fallback(tmp_path):
    fake = FakePaper()
    fake.status = "NOT_CONFIGURED"
    runtime = tmp_path / "must_not_exist"
    with pytest.raises(BridgeError, match="no SHADOW fallback"):
        PaperGatewaySession(runtime, fake)
    assert not runtime.exists() and not fake.calls and not fake.cancel_calls
