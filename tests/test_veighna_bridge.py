"""No sockets/accounts: real VeighNa OMS and injected, fake SDK paper behavior."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from execution_lab.veighna_bridge import (BridgeError, FutuPaperAdapter, ShadowSession,
                                         paper_backend_status, run_shadow_replay)


AT = datetime(2024, 3, 11, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def runtime(tmp_path):
    return tmp_path / "private-runtime"


def test_actual_mainengine_oms_event_chain_and_no_broker(runtime):
    previous_cwd = Path.cwd()
    with ShadowSession(runtime_dir=runtime) as session:
        session.publish_quote("AAA", 100, AT)
        ids = session.submit_targets({"AAA": .2}, as_of=AT, signal_id="known-1", scores={"AAA": .1})
        assert len(ids) == 1 and not session.trades
        session.publish_quote("AAA", 101, AT+timedelta(seconds=1))
        report = session.report()
        assert report["execution_environment"] == "SHADOW"
        assert report["broker_status"] == "NOT_CONFIGURED"
        assert report["reconciliation"]["status"] == "matched"
        assert report["reconciliation"]["oms_order_count"] == 1
        assert report["reconciliation"]["oms_trade_count"] == 1
        assert report["trades"][0]["price"] == 101
        assert report["trades"][0]["fill_source"] == "local_price_proxy"
        assert report["trades"][0]["broker_deal_id"] is None
        types = [row["type"] for row in report["events"]]
        for name in ("eTick.", "eAlphaSignal", "eAlphaTarget", "eAlphaRisk", "eOrder.", "eTrade.", "eAccount.", "ePosition."):
            assert name in types
        assert types.index("eAlphaSignal") < types.index("eAlphaTarget") < types.index("eAlphaRisk") < types.index("eOrder.") < types.index("eTrade.")
        assert set(session.main.engines) == {"oms"}
        assert set(session.main.gateways) == {"ALPHA_SHADOW"}
        assert report["lineage"]["dependencies"]["vnpy"] == "4.5.0"
        json.dumps(report, allow_nan=False)
    assert Path.cwd() == previous_cwd
    assert (runtime / ".vntrader").is_dir()


def test_shadow_price_jump_rechecks_budget_caps_and_integer_quantity(runtime):
    with ShadowSession(runtime_dir=runtime, initial_cash=1000, max_weight=.2, cash_floor=.2) as session:
        session.publish_quote("AAA", 10, AT)
        session.submit_targets({"AAA": .2}, as_of=AT, signal_id="jump")
        session.publish_quote("AAA", 500, AT+timedelta(seconds=1))
        assert not session.trades
        assert session.orders[0]["status"] == "CANCELLED"
        assert session.cash == Decimal(1000)
        assert session.report()["reconciliation"]["status"] == "matched"


def test_shadow_partial_budget_fill_and_local_cancelled_remainder(runtime):
    with ShadowSession(runtime_dir=runtime, initial_cash=1000, max_weight=.2, cash_floor=.2) as session:
        session.publish_quote("AAA", 10, AT)
        session.submit_targets({"AAA": .2}, as_of=AT, signal_id="partial")
        session.publish_quote("AAA", 20, AT+timedelta(seconds=1))
        assert len(session.trades) == 1 and session.trades[0]["quantity"] == 9
        assert session.orders[0]["quantity"] == 19 and session.orders[0]["status"] == "CANCELLED"
        assert session.cash >= session.cash_floor*session.equity()
        assert session.holdings["AAA"]*Decimal(20) <= session.max_weight*session.equity()
        assert session.trades[0]["fee"] == Decimal(".18")


@pytest.mark.parametrize("weights,reason", [({"AAA": .21}, "position_cap_or_cash_floor"),
                                          ({"AAA": .2, "BBB": .1}, "missing_quote")])
def test_shadow_risk_rejects_without_order(runtime, weights, reason):
    with ShadowSession(runtime_dir=runtime) as session:
        session.publish_quote("AAA", 100, AT)
        assert session.submit_targets(weights, as_of=AT, signal_id="risk") == []
        assert session.risk_checks[-1]["reason"] == reason
        assert not session.orders and not session.trades


def test_shadow_signal_idempotency_and_stale_quotes(runtime):
    with ShadowSession(runtime_dir=runtime) as session:
        session.publish_quote("AAA", 100, AT)
        session.submit_targets({"AAA": .2}, as_of=AT, signal_id="one")
        assert session.submit_targets({"AAA": .2}, as_of=AT, signal_id="one") == []
        assert len(session.orders) == 1
        with pytest.raises(BridgeError, match="changed targets"):
            session.submit_targets({"AAA": .1}, as_of=AT, signal_id="one")
        with pytest.raises(BridgeError, match="stale"):
            session.publish_quote("AAA", 99, AT, as_of=AT+timedelta(minutes=1))
        assert session.submit_targets({"AAA": 0}, as_of=AT+timedelta(minutes=1), signal_id="stale") == []
        assert session.risk_checks[-1]["reason"] == "stale_quote"


def test_exclusive_runtime_released_after_error(runtime):
    with ShadowSession(runtime_dir=runtime) as session:
        with pytest.raises(BridgeError, match="owns the runtime"):
            ShadowSession(runtime_dir=runtime)
    with pytest.raises(BridgeError):
        ShadowSession(runtime_dir=runtime, max_weight=2)
    with ShadowSession(runtime_dir=runtime):
        pass


def teaching_bars(days=2):
    from hf_space.intraday import make_synthetic_intraday_prices
    return make_synthetic_intraday_prices(days=days)


def test_replay_causal_next_open_end_flat_and_true_framework(runtime):
    bars = teaching_bars()
    report = run_shadow_replay(bars, runtime_dir=runtime, benchmark="BENCH")
    assert report["status"] == "success" and report["trades"]
    assert report["reconciliation"]["status"] == "matched"
    assert report["reconciliation"]["active_orders"] == 0
    assert all(row["quantity"] == 0 for row in report["positions"])
    assert all(row["symbol"] != "BENCH" for row in report["orders"])
    # Every local trade uses an actual next-open input, never the signal close.
    opens = {(row.timestamp.isoformat().replace("+00:00", "Z"), row.symbol): row.open for row in bars.itertuples()}
    for trade in report["trades"]:
        assert trade["price"] == opens[trade["as_of"], trade["symbol"]]
        assert trade["fee"] == pytest.approx(trade["quantity"]*trade["price"]*.001)
    assert report["lineage"]["coverage"]["complete_session_count"] == 2


def test_append_future_day_preserves_shadow_history(runtime):
    a = run_shadow_replay(teaching_bars(2), runtime_dir=runtime, benchmark="BENCH")
    b = run_shadow_replay(teaching_bars(3), runtime_dir=runtime, benchmark="BENCH")
    cutoff = "2024-03-12T00:00:00Z"
    for key in ("orders", "trades", "targets", "risk_checks", "signals"):
        assert a[key] == [row for row in b[key] if row["as_of"] < cutoff]


SDK = SimpleNamespace(RET_OK=0, TrdEnv=SimpleNamespace(SIMULATE="SIMULATE"),
    Currency=SimpleNamespace(USD="USD"), TrdSide=SimpleNamespace(BUY="BUY", SELL="SELL"),
    OrderType=SimpleNamespace(NORMAL="NORMAL"), TimeInForce=SimpleNamespace(DAY="DAY"),
    ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"), Session=SimpleNamespace(RTH="RTH"))
ACCOUNT = dict(acc_id=101, trd_env="SIMULATE", acc_status="ACTIVE", sim_acc_type="STOCK_AND_OPTION",
               trdmarket_auth=["US"], security_firm="N/A")


class FakeContext:
    def __init__(self):
        self.calls = []
        self.before_return = None
        self.submit_error = False
        self.funds = [{"us_cash": 5000}]
        self.positions = [{"code": "US.AAA", "qty": 20, "can_sell_qty": 20}]
        self.order_rows = []

    def _record(self, name, kwargs):
        assert kwargs["trd_env"] == "SIMULATE" and kwargs["acc_id"] == 101
        self.calls.append((name, kwargs))

    def accinfo_query(self, **kwargs):
        self._record("funds", kwargs)
        assert kwargs["currency"] == "USD" and kwargs["refresh_cache"] is True
        return 0, deepcopy(self.funds)

    def position_list_query(self, **kwargs):
        self._record("positions", kwargs)
        assert kwargs["refresh_cache"] is True
        return 0, deepcopy(self.positions)

    def order_list_query(self, **kwargs):
        self._record("orders", kwargs)
        assert kwargs["refresh_cache"] is True
        return 0, deepcopy(self.order_rows)

    def place_order(self, **kwargs):
        self._record("place_order", kwargs)
        assert kwargs["order_type"] == "NORMAL" and kwargs["time_in_force"] == "DAY"
        assert kwargs["session"] == "RTH" and kwargs["fill_outside_rth"] is False and kwargs["adjust_limit"] == 0
        if self.submit_error:
            raise TimeoutError("response body must never be printed")
        if self.before_return:
            self.before_return()
        return 0, [{"order_id": "O1", "code": "US.AAA", "dealt_qty": 0,
                    "dealt_avg_price": 0, "order_status": "SUBMITTED"}]

    def modify_order(self, **kwargs):
        self._record("modify_order", kwargs)
        assert kwargs["modify_order_op"] == "CANCEL"
        return 0, [{"order_id": "O1"}]


def configured(context=None, **kwargs):
    context = FakeContext() if context is None else context
    kwargs.setdefault("persist_state", lambda state: None)  # Pure mock; production runner must persist durably.
    adapter = FutuPaperAdapter(context, sdk=SDK, account_id=101,
        account_metadata=ACCOUNT, context_security_firm="FUTUINC", expected_security_firm="FUTUINC", **kwargs)
    return adapter, context


def submit(adapter, **changes):
    kwargs = dict(client_id="intent-1", symbol="AAA", side="BUY", quantity=10, price=10,
                  quote_at=AT, as_of=AT)
    kwargs.update(changes)
    return adapter.submit_limit(**kwargs)


def snapshot(cumulative_qty, avg, status="FILLED_PART", stamp="2024-03-11 10:00:01", **changes):
    row = dict(order_id="O1", code="US.AAA", dealt_qty=cumulative_qty, dealt_avg_price=avg,
               order_status=status, updated_time=stamp)
    row.update(changes)
    return row


def test_unconfigured_backends_never_open_sdk_or_fallback():
    assert FutuPaperAdapter().status == "NOT_CONFIGURED"
    for backend in ("legacy_OpenD", "REST_sim_trade"):
        status = paper_backend_status(backend)
        assert status["status"] == "NOT_CONFIGURED" and not status["shadow_fallback"]
        assert not status["real_trading_supported"]


@pytest.mark.parametrize("change", [dict(acc_id=0), dict(acc_id=102), dict(trd_env="REAL"),
    dict(acc_status="DISABLED"), dict(sim_acc_type="OPTION"), dict(sim_acc_type="STOCK"),
    dict(trdmarket_auth=["HK"]), dict(security_firm="OTHER")])
def test_invalid_paper_account_fails_before_any_context_call(change):
    context = FakeContext()
    metadata = {**ACCOUNT, **change}
    with pytest.raises(BridgeError):
        FutuPaperAdapter(context, sdk=SDK, account_id=101, account_metadata=metadata,
                         context_security_firm="FUTUINC", expected_security_firm="FUTUINC")
    assert not context.calls


def test_paper_security_firm_confirmation_and_na_not_live_account():
    context = FakeContext()
    with pytest.raises(BridgeError, match="security_firm"):
        FutuPaperAdapter(context, sdk=SDK, account_id=101, account_metadata=ACCOUNT,
                         context_security_firm="FUTUINC", expected_security_firm="FUTUSECURITIES")
    adapter, _ = configured(context)
    assert adapter.security_firm == {"context": "FUTUINC", "account": "N/A"}
    assert not context.calls


def test_explicit_security_firm_none_is_accepted_but_implicit_none_is_not():
    context = FakeContext()
    adapter = FutuPaperAdapter(context, sdk=SDK, account_id=101, account_metadata=ACCOUNT,
                              context_security_firm="N/A", expected_security_firm="N/A")
    assert adapter.status == "READY"
    for config in ({}, {"context_security_firm": "N/A"}):
        with pytest.raises(BridgeError, match="security_firm"):
            FutuPaperAdapter(context, sdk=SDK, account_id=101, account_metadata=ACCOUNT, **config)
    assert not context.calls


def test_explicit_env_account_currency_and_no_unlock_deal_calls():
    adapter, context = configured()
    with pytest.raises(BridgeError, match="Reconcile"):
        submit(adapter)
    adapter.reconcile()
    receipt = submit(adapter)
    assert receipt["order_id"] == "O1"
    assert submit(adapter)["order_id"] == "O1"  # No second place_order.
    assert sum(name == "place_order" for name, _ in context.calls) == 1
    assert {name for name, _ in context.calls} == {"funds", "positions", "orders", "place_order"}
    assert context.calls[-1][1]["code"] == "US.AAA"


@pytest.mark.parametrize("change", [dict(quote_at=None), dict(as_of=AT+timedelta(minutes=1)),
    dict(quote_at=AT+timedelta(seconds=1)), dict(quantity=1000), dict(quantity=.5),
    dict(symbol="HK.00700"), dict(side="SELL_SHORT"), dict(price=0)])
def test_paper_quote_and_risk_rejection_never_calls_place(change):
    adapter, context = configured()
    adapter.reconcile()
    with pytest.raises(BridgeError):
        submit(adapter, **change)
    assert not any(name == "place_order" for name, _ in context.calls)


def test_paper_cash_and_long_share_limits_are_real_fields_not_buying_power():
    adapter, context = configured()
    context.funds = [{"power": 999999, "avl_withdrawal_cash": 999999}]
    adapter.reconcile()
    with pytest.raises(BridgeError, match="cash is unavailable"):
        submit(adapter)
    context.funds = [{"us_cash": 50}]
    adapter.reconcile()
    with pytest.raises(BridgeError, match="exceeds queried USD cash"):
        submit(adapter)
    with pytest.raises(BridgeError, match="sellable long"):
        submit(adapter, side="SELL", quantity=21)
    assert not any(name == "place_order" for name, _ in context.calls)


def test_timeout_is_unknown_and_never_retried_or_shadow_filled():
    adapter, context = configured()
    adapter.reconcile()
    context.submit_error = True
    with pytest.raises(BridgeError, match="outcome is unknown"):
        submit(adapter)
    assert adapter.status == "SUBMISSION_UNKNOWN" and not adapter.executions
    with pytest.raises(BridgeError, match="Reconcile"):
        submit(adapter)
    adapter.reconcile()
    with pytest.raises(BridgeError):
        submit(adapter, client_id="intent-2")
    assert sum(name == "place_order" for name, _ in context.calls) == 1


def test_cumulative_notional_partial_cancel_and_duplicate_is_not_a_deal_push():
    adapter, context = configured()
    adapter.reconcile()
    submit(adapter)
    adapter.process_order_snapshot(snapshot(4, 10))
    adapter.process_order_snapshot(snapshot(10, 11, status="CANCELLED_PART", stamp="2024-03-11 10:00:02"))
    assert [row["quantity"] for row in adapter.executions] == [4, 6]
    assert [Decimal(row["price"]) for row in adapter.executions] == [Decimal(10), Decimal(70)/6]
    assert all(row["broker_deal_id"] is None and row["source"] == "derived_from_order_cumulative" for row in adapter.executions)
    adapter.process_order_snapshot(snapshot(10, 11, status="CANCELLED_PART", stamp="2024-03-11 10:00:02"))
    assert len(adapter.executions) == 2
    assert adapter.orders["O1"]["status"] == "CANCELLED_PART"
    assert adapter.orders["O1"]["cum_qty"] == 10


def test_callback_before_submit_response_and_wrong_account_are_isolated():
    adapter, context = configured()
    adapter.reconcile()
    context.before_return = lambda: adapter.process_order_snapshot(snapshot(4, 10, remark="intent-1"))
    submit(adapter)
    assert len(adapter.executions) == 1 and adapter.executions[0]["quantity"] == 4
    assert adapter.process_order_snapshot(snapshot(10, 10, acc_id=202))["status"] == "ignored_wrong_account"
    assert adapter.process_order_snapshot(snapshot(10, 10, trd_env="REAL"))["status"] == "ignored_wrong_environment"
    assert adapter.process_order_snapshot(snapshot(10, 10, order_id="STRANGER"))["status"] == "ignored_unmatched_order"
    assert len(adapter.executions) == 1


def test_out_of_order_snapshot_and_terminal_state_do_not_regress():
    adapter, _ = configured()
    adapter.reconcile()
    submit(adapter)
    adapter.process_order_snapshot(snapshot(4, 10, "CANCELLED_PART", "2024-03-11 10:00:03"))
    assert adapter.process_order_snapshot(snapshot(0, 0, "SUBMITTED", "2024-03-11 10:00:01"))["status"] == "ignored_older_snapshot"
    adapter.process_order_snapshot(snapshot(4, 10, "SUBMITTED", "2024-03-11 10:00:04"))
    assert adapter.orders["O1"]["status"] == "CANCELLED_PART"
    with pytest.raises(BridgeError, match="cumulative paper quantity"):
        adapter.process_order_snapshot(snapshot(3, 10, stamp="2024-03-11 10:00:05"))
    assert adapter.requires_reconciliation and len(adapter.executions) == 1


def test_average_correction_blocks_deriving_fictitious_increment():
    adapter, _ = configured()
    adapter.reconcile()
    submit(adapter)
    adapter.process_order_snapshot(snapshot(4, 10))
    adapter.process_order_snapshot(snapshot(4, 11, stamp="2024-03-11 10:00:02"))
    assert len(adapter.executions) == 1 and len(adapter.corrections) == 1
    with pytest.raises(BridgeError, match="correction"):
        adapter.process_order_snapshot(snapshot(5, 11, stamp="2024-03-11 10:00:03"))


def test_cancel_acknowledgement_is_not_final_and_fills_survive():
    adapter, context = configured()
    adapter.reconcile()
    submit(adapter)
    adapter.process_order_snapshot(snapshot(4, 10))
    assert adapter.cancel("O1")["status"] == "CANCEL_PENDING"
    assert adapter.orders["O1"]["status"] == "FILLED_PART"
    assert adapter.requires_reconciliation
    context.order_rows = [snapshot(4, 10, "CANCELLED_PART", "2024-03-11 10:00:02")]
    adapter.reconcile()
    assert adapter.orders["O1"]["status"] == "CANCELLED_PART"
    assert len(adapter.executions) == 1
    with pytest.raises(BridgeError, match="matched order"):
        adapter.cancel("OTHER")


def test_state_restore_requeries_and_never_duplicates_cumulative_execution():
    adapter, _ = configured()
    adapter.reconcile()
    submit(adapter)
    adapter.process_order_snapshot(snapshot(4, 10))
    state = adapter.export_state()
    restored, context = configured(state=state)
    assert restored.requires_reconciliation
    context.order_rows = [snapshot(4, 10)]
    restored.reconcile()
    assert len(restored.executions) == 1
    restored.process_order_snapshot(snapshot(10, 11, "FILLED_ALL", "2024-03-11 10:00:02"))
    assert [row["quantity"] for row in restored.executions] == [4, 6]
    with pytest.raises(BridgeError, match="another environment"):
        configured(state={**state, "account_id": 202})


def test_missing_durable_sink_allows_queries_but_no_order_or_cancel():
    adapter, context = configured(persist_state=None)
    assert adapter.reconcile()["status"] == "queried"
    with pytest.raises(BridgeError, match="persist_state"):
        submit(adapter)
    assert not any(name == "place_order" for name, _ in context.calls)


def test_persist_submitting_precedes_rpc_and_ack_and_execution_are_saved():
    saved, chronology = [], []
    context = FakeContext()

    def persist(state):
        saved.append(deepcopy(state))
        chronology.append(("persist", deepcopy(state["intents"])))

    adapter, _ = configured(context, persist_state=persist)
    adapter.reconcile()
    context.before_return = lambda: chronology.append(("broker_rpc", None))
    submit(adapter)
    assert chronology[0][0] == "persist" and chronology[0][1]["intent-1"]["status"] == "SUBMITTING"
    assert chronology[1][0] == "broker_rpc"
    assert any(row["intents"]["intent-1"]["status"] == "ACKNOWLEDGED" for row in saved)
    adapter.process_order_snapshot(snapshot(4, 10))
    assert saved[-1]["orders"]["O1"]["cum_qty"] == 4
    assert len(saved[-1]["executions"]) == 1
    adapter.cancel("O1")
    assert any(row["cancel_intents"].get("O1", {}).get("status") == "SUBMITTING" for row in saved)
    assert saved[-1]["cancel_intents"]["O1"]["status"] == "ACKNOWLEDGED"
    adapter.cancel("O1")
    assert sum(name == "modify_order" for name, _ in context.calls) == 1


def test_persist_failure_stops_before_any_broker_submission():
    def failed_sink(state):
        raise OSError("fake disk unavailable")

    adapter, context = configured(persist_state=failed_sink)
    adapter.reconcile()
    with pytest.raises(BridgeError, match="persistence failed"):
        submit(adapter)
    assert adapter.status == "PERSISTENCE_FAILED"
    assert not any(name == "place_order" for name, _ in context.calls)


def test_restart_during_submit_stays_unknown_after_queries_and_never_retries():
    saved = []
    adapter, context = configured(persist_state=lambda state: saved.append(deepcopy(state)))
    adapter.reconcile()
    context.submit_error = True
    with pytest.raises(BridgeError):
        submit(adapter)
    submitting = next(row for row in saved if row["intents"]["intent-1"]["status"] == "SUBMITTING")
    restored, new_context = configured(state=submitting)
    assert restored.intents["intent-1"]["status"] == "SUBMISSION_UNKNOWN"
    assert restored.status == "SUBMISSION_UNKNOWN"
    assert restored.reconcile()["status"] == "submission_unknown"
    with pytest.raises(BridgeError, match="Reconcile"):
        submit(restored)
    assert not any(name == "place_order" for name, _ in new_context.calls)


def test_unknown_response_is_recovered_only_by_exact_unique_query_economics():
    adapter, context = configured()
    adapter.reconcile()
    context.submit_error = True
    with pytest.raises(BridgeError):
        submit(adapter)
    context.order_rows = [snapshot(4, 10, remark="intent-1", qty=10, price=10, trd_side="BUY")]
    report = adapter.reconcile()
    assert report["status"] == "queried" and adapter.status == "READY"
    assert report["unknown_resolution"][0]["status"] == "bound_exact_unique_remark_and_economics"
    assert adapter.intents["intent-1"]["order_id"] == "O1"
    assert adapter.orders["O1"]["cum_qty"] == 4
    assert len(adapter.executions) == 1 and adapter.executions[0]["quantity"] == 4
    adapter.reconcile()
    assert len(adapter.executions) == 1
    assert sum(name == "place_order" for name, _ in context.calls) == 1


@pytest.mark.parametrize("problem", ["duplicate_remark", "different_price", "different_account"])
def test_unknown_ambiguous_or_mismatched_query_never_adopts_or_retries(problem):
    adapter, context = configured()
    adapter.reconcile()
    context.submit_error = True
    with pytest.raises(BridgeError):
        submit(adapter)
    row = snapshot(0, 0, "SUBMITTED", remark="intent-1", qty=10, price=10, trd_side="BUY")
    if problem == "different_price": row["price"] = 11
    if problem == "different_account": row["acc_id"] = 202
    context.order_rows = [row, {**row, "order_id": "O2"}] if problem == "duplicate_remark" else [row]
    assert adapter.reconcile()["status"] == "submission_unknown"
    assert adapter.status == "SUBMISSION_UNKNOWN" and not adapter.orders and not adapter.executions
    assert sum(name == "place_order" for name, _ in context.calls) == 1
