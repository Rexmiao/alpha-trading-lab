"""Persistent coordinator acceptance with fixed clocks and no external service."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from execution_lab.runtime import RuntimeConfig, RuntimeError, TradingRuntime


class Clock:
    def __init__(self, value="2024-03-11T14:05:10Z"):
        self.value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    def __call__(self):
        return self.value


def market_state(now):
    opening = now.replace(hour=13, minute=30, second=0, microsecond=0)
    closing = now.replace(hour=20, minute=0, second=0, microsecond=0)
    if now.date().isoformat() == "2026-11-26":
        return {"status": "MARKET_CLOSED", "expected_bar_end": None}
    end = pd.Timestamp(now-timedelta(seconds=10)).floor("5min").to_pydatetime()
    end = min(end, closing)
    return {"status": "READY" if end > opening else "WAITING_FOR_COMPLETED_BAR",
            "session_open": opening, "session_close": closing, "expected_bar_end": end}


class Source:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.revise = False
        self.partial = False
        self.descending = False

    def read_completed(self, symbols, as_of, runtime_dir):
        self.calls += 1
        if self.fail:
            raise OSError("fake source unavailable")
        state = market_state(as_of)
        rows = []
        for number, stamp in enumerate(pd.date_range(state["session_open"], state["expected_bar_end"], freq="5min", inclusive="left")):
            for symbol in symbols:
                op = 100-number if self.descending else 100+number
                close = op-.5 if self.descending else op+.5
                if self.revise and number == 0:
                    close += .1
                rows.append([stamp, symbol, op, op+1, op-1, close, 1000])
        frame = pd.DataFrame(rows, columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        if self.partial:
            frame = frame.iloc[:-1]
        return frame, {"source": "mock_moomoo", "synthetic_test_fixture": True}


class Adapter:
    backend = "fake_paper"
    account_id = 101
    status = "READY"

    def __init__(self):
        self.calls = []
        self.requires_reconciliation = True
        self.persist_state = None
        self.timeout = False
        self.observe_before_rpc = None
        self.funds = [{"us_cash": 10000, "total_assets": 10000}]
        self.positions = []
        self.state = dict(schema=1, backend="fake_paper", execution_environment="BROKER_PAPER",
                          account_id=101, orders={}, intents={}, executions=[], corrections=[], cancel_intents={})

    def restore_state(self, state):
        self.state = deepcopy(state)
        self.requires_reconciliation = True

    def export_state(self):
        return deepcopy(self.state)

    def reconcile(self):
        self.requires_reconciliation = False
        return {"status": "queried", "funds": deepcopy(self.funds), "positions": deepcopy(self.positions), "orders": []}

    def submit_limit(self, **payload):
        client_id = payload["client_id"]
        assert payload["quantity"] == 1
        self.state["intents"][client_id] = dict(client_id=client_id, status="SUBMITTING", order_id=None,
                                              payload={"symbol": payload["symbol"], "quantity": 1})
        self.persist_state(self.state)
        if self.observe_before_rpc:
            self.observe_before_rpc(client_id)
        self.calls.append(payload)
        if self.timeout:
            self.state["intents"][client_id]["status"] = "SUBMISSION_UNKNOWN"
            self.persist_state(self.state)
            raise TimeoutError("fake broker outcome unknown")
        receipt = {"status": "ACKNOWLEDGED", "order_id": "O1", "client_id": client_id}
        self.state["intents"][client_id].update(receipt)
        self.state["orders"]["O1"] = {"cum_qty": 0, "status": "SUBMITTED"}
        self.persist_state(self.state)
        return receipt


def build(tmp_path, *, clock=None, source=None, adapter=None, quote_provider=None,
          mode=None, environment=None, symbols=("NVDA",), scope=None):
    clock = clock or Clock()
    source = source or Source()
    config = RuntimeConfig(runtime_dir=tmp_path / "local-runtime", symbols=symbols, automation_mode=mode,
                           execution_environment=environment, paper_account_id=101 if adapter else None,
                           account_scope=scope)
    return TradingRuntime(config, market_source=source, clock=clock, market_state=market_state,
        next_capture_at=lambda now: now+timedelta(minutes=5), paper_adapter=adapter, quote_provider=quote_provider)


def quotes(symbols, now):
    return {symbol: {"price": 100., "timestamp": now} for symbol in symbols}


def test_explicit_non_synced_runtime_required(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHA_RUNTIME_DIR", raising=False)
    for path in (None, "relative", tmp_path / "Dropbox" / "runtime"):
        with pytest.raises(RuntimeError, match="explicit|Dropbox"):
            TradingRuntime(RuntimeConfig(runtime_dir=path), market_state=market_state, next_capture_at=lambda x: x)
    with pytest.raises(RuntimeError, match="LIVE"):
        build(tmp_path, environment="LIVE")


def test_holiday_is_journalled_without_market_or_broker_rpc(tmp_path):
    source, adapter = Source(), Adapter()
    with build(tmp_path, clock=Clock("2026-11-26T16:00:00Z"), source=source, adapter=adapter,
               mode="AUTO_EXECUTE", environment="BROKER_PAPER", quote_provider=quotes) as runtime:
        result = runtime.capture_once()
        assert result["status"] == "MARKET_CLOSED"
        assert source.calls == 0 and not adapter.calls
        assert runtime.status()["counts"]["snapshots"] == 0
        assert runtime.db.execute("SELECT kind FROM audit ORDER BY id DESC").fetchone()[0] == "MARKET_CLOSED"


def test_capture_persistent_signal_and_restart_before_rpc_dedup(tmp_path):
    source = Source()
    with build(tmp_path, source=source) as runtime:
        first = runtime.capture_once()
        assert first["status"] == "CAPTURED" and first["proposal_status"] == "ALERT"
        assert runtime.capture_once()["status"] == "ALREADY_CAPTURED"
        signal = json.loads(runtime.db.execute("SELECT payload FROM signals").fetchone()[0])
        assert signal["scores"]["NVDA"] == pytest.approx(106.5/100.5-1)
        assert signal["target_weights"] == {"NVDA": .2}
        assert runtime.status()["counts"]["intents"] == 0
    with build(tmp_path, source=source) as runtime:
        assert runtime.capture_once()["status"] == "ALREADY_CAPTURED"
        assert runtime.status()["counts"]["signals"] == 1
    assert source.calls == 1


def test_immutable_snapshot_bars_and_signal(tmp_path):
    with build(tmp_path) as runtime:
        runtime.capture_once()
        for table in ("snapshots", "bars", "signals"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                runtime.db.execute(f"UPDATE {table} SET { {'snapshots':'sha256','bars':'payload','signals':'payload'}[table]}='changed'")
        blob = runtime.db.execute("SELECT csv,sha256 FROM snapshots").fetchone()
        import hashlib
        assert hashlib.sha256(blob["csv"]).hexdigest() == blob["sha256"]


@pytest.mark.parametrize("failure", ["fail", "partial"])
def test_source_failure_or_missing_bar_does_not_emit_zero_signal_or_order(tmp_path, failure):
    source, adapter = Source(), Adapter()
    setattr(source, failure, True)
    with build(tmp_path, source=source, adapter=adapter, mode="AUTO_EXECUTE", environment="BROKER_PAPER", quote_provider=quotes) as runtime:
        result = runtime.capture_once()
        assert result["status"] == "CAPTURE_FAILED"
        assert not adapter.calls
        assert runtime.status()["counts"]["signals"] == 0
        assert runtime.status()["counts"]["intents"] == 0


def test_warmup_does_not_create_cash_liquidation_target(tmp_path):
    with build(tmp_path, clock=Clock("2024-03-11T13:45:10Z"), mode="AUTO_EXECUTE", environment="BROKER_PAPER") as runtime:
        result = runtime.capture_once()
        assert result["proposal_status"] == "WARMUP"
        payload = json.loads(runtime.db.execute("SELECT payload FROM signals").fetchone()[0])
        assert payload["scores"]["NVDA"] is None and payload["target_weights"] is None
        assert runtime.status()["counts"]["intents"] == 0


def test_revision_is_blocked_without_rewriting_prior_capture(tmp_path):
    clock, source = Clock(), Source()
    with build(tmp_path, clock=clock, source=source) as runtime:
        runtime.capture_once()
        source.revise = True
        clock.value += timedelta(minutes=5)
        assert runtime.capture_once()["status"] == "DATA_REVISION_BLOCKED"
        assert runtime.status()["counts"]["snapshots"] == 1
        assert runtime.status()["counts"]["signals"] == 1


def test_mode_switch_never_executes_old_alert_and_status_retains_policy(tmp_path):
    adapter, source = Adapter(), Source()
    with build(tmp_path, source=source) as runtime:
        proposal_id = runtime.capture_once()["proposal_id"]
    with build(tmp_path, source=source, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["status"] == "ALREADY_CAPTURED"
        assert runtime.confirm(proposal_id)["status"] == "CONFIRMATION_REJECTED"
        assert not adapter.calls
    with build(tmp_path, source=source) as runtime:
        assert runtime.policy()["mode"] == "AUTO_EXECUTE" and runtime.policy()["environment"] == "BROKER_PAPER"


def test_changed_stock_pool_has_a_distinct_stable_strategy_instance(tmp_path):
    with build(tmp_path, symbols=("NVDA",)) as runtime:
        first = runtime.capture_once()
        original_version = runtime.strategy_version
    with build(tmp_path, symbols=("AMD",)) as runtime:
        second = runtime.capture_once()
        assert second["status"] == "CAPTURED" and first["proposal_id"] != second["proposal_id"]
        assert runtime.strategy_version != original_version
        assert runtime.status()["counts"]["signals"] == 2
    with build(tmp_path, symbols=("NVDA",)) as runtime:
        assert runtime.strategy_version == original_version
        assert runtime.capture_once()["status"] == "ALREADY_CAPTURED"


@pytest.mark.parametrize("environment", ["NONE", "SHADOW", "BROKER_PAPER"])
def test_unconfigured_execution_is_explicit_without_local_fake_fill(tmp_path, environment):
    with build(tmp_path, mode="AUTO_EXECUTE", environment=environment) as runtime:
        result = runtime.capture_once()
        assert result["proposal_status"] == "NOT_CONFIGURED"
        assert runtime.status()["counts"]["intents"] == 0
        assert runtime.status()["counts"]["executions"] == 0


def test_paper_network_boundary_has_committed_intent_and_durable_adapter_state(tmp_path):
    adapter = Adapter()
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        def observe(client_id):
            # Independent SQLite reader proves COMMIT precedes the external RPC.
            with sqlite3.connect(runtime.runtime_dir / "journal.sqlite3") as reader:
                assert reader.execute("SELECT status FROM intents WHERE id=?", (client_id,)).fetchone()[0] == "SUBMITTING"
                state = json.loads(reader.execute("SELECT payload FROM broker_states").fetchone()[0])
                assert state["intents"][client_id]["status"] == "SUBMITTING"
        adapter.observe_before_rpc = observe
        result = runtime.capture_once()
        assert result["proposal_status"] == "DISPATCHED"
        assert len(adapter.calls) == 1 and adapter.calls[0]["quantity"] == 1
        assert runtime.db.execute("SELECT status FROM intents").fetchone()[0] == "ACKNOWLEDGED"
        assert runtime.status()["counts"]["executions"] == 0  # ACK is not a fill.


def test_existing_manual_one_share_is_never_adopted_or_sold(tmp_path):
    adapter, source = Adapter(), Source()
    source.descending = True
    adapter.positions = [{"code": "US.NVDA", "qty": 1, "can_sell_qty": 1}]
    with build(tmp_path, source=source, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "RISK_BLOCKED"
        signal = json.loads(runtime.db.execute("SELECT payload FROM signals").fetchone()[0])
        assert signal["target_weights"] == {"NVDA": 0}
        assert not adapter.calls and runtime.status()["counts"]["intents"] == 0


def test_only_persisted_owned_one_share_can_follow_a_valid_exit(tmp_path):
    adapter, source = Adapter(), Source()
    source.descending = True
    adapter.positions = [{"code": "US.NVDA", "qty": 1, "can_sell_qty": 1}]
    with build(tmp_path, source=source, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        state = deepcopy(adapter.state)
        state["orders"]["OLD"] = {"cum_qty": 1, "status": "FILLED_ALL"}
        state["executions"] = [{"order_id": "OLD", "cumulative_quantity": 1, "quantity": 1,
            "symbol": "NVDA", "side": "BUY", "source": "derived_from_order_cumulative", "broker_deal_id": None}]
        runtime.persist_adapter_state(state)
        assert runtime.capture_once()["proposal_status"] == "DISPATCHED"
        assert len(adapter.calls) == 1 and adapter.calls[0]["side"] == "SELL" and adapter.calls[0]["quantity"] == 1


@pytest.mark.parametrize("funds", [[{"us_cash": 10000}], [{"us_cash": 100, "power": 999999}],
                                   [{"us_cash": 100, "total_assets": 100}],
                                   [{"us_cash": 210, "total_assets": 1000}]])
def test_missing_equity_weight_cap_and_cash_floor_reject_one_share(tmp_path, funds):
    adapter = Adapter()
    adapter.funds = funds
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "RISK_BLOCKED"
        assert not adapter.calls and runtime.status()["counts"]["intents"] == 0


def test_unknown_submit_blocks_new_signal_and_restart(tmp_path):
    clock, adapter = Clock(), Adapter()
    adapter.timeout = True
    with build(tmp_path, clock=clock, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "SUBMISSION_UNKNOWN"
    clock.value += timedelta(minutes=5)
    with build(tmp_path, clock=clock, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "BLOCKED_UNKNOWN"
        assert runtime.status()["unresolved_intents"] == 1
    assert len(adapter.calls) == 1


def test_crash_left_submitting_becomes_unknown_without_replay(tmp_path):
    clock = Clock()
    with build(tmp_path, clock=clock) as runtime:
        proposal_id = runtime.capture_once()["proposal_id"]
        runtime.db.execute("INSERT INTO intents VALUES('lost',?,?,?,'SUBMITTING','{}',NULL)",
                           (proposal_id, clock().isoformat(), "dead-process"))
    clock.value += timedelta(minutes=5)
    with build(tmp_path, clock=clock, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=Adapter(), quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "BLOCKED_UNKNOWN"
        assert runtime.db.execute("SELECT status FROM intents WHERE id='lost'").fetchone()[0] == "SUBMISSION_UNKNOWN"


def test_confirmation_is_explicit_fresh_and_not_repeated(tmp_path):
    adapter = Adapter()
    with build(tmp_path, mode="CONFIRM_BEFORE_SEND", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        proposal_id = runtime.capture_once()["proposal_id"]
        assert not adapter.calls
        assert runtime.confirm(proposal_id)["proposal_status"] == "DISPATCHED"
        runtime.confirm(proposal_id)
        assert len(adapter.calls) == 1


@pytest.mark.parametrize("problem", ["stale_quote", "high_price", "expired_signal"])
def test_paper_prechecks_never_turn_bar_close_or_old_proposal_into_order(tmp_path, problem):
    clock, adapter = Clock(), Adapter()
    def provider(symbols, now):
        return {symbol: {"price": 1001 if problem == "high_price" else 100,
                         "timestamp": now-timedelta(seconds=6) if problem == "stale_quote" else now} for symbol in symbols}
    with build(tmp_path, clock=clock, mode="CONFIRM_BEFORE_SEND", environment="BROKER_PAPER", adapter=adapter, quote_provider=provider) as runtime:
        proposal_id = runtime.capture_once()["proposal_id"]
        if problem == "expired_signal": clock.value += timedelta(minutes=2)
        status = runtime.confirm(proposal_id)["proposal_status"]
        assert status in {"RISK_BLOCKED", "EXPIRED"} and not adapter.calls
        assert runtime.status()["counts"]["intents"] == 0


def test_pause_during_quote_check_stops_new_intent_and_is_not_cancel_flatten(tmp_path):
    adapter = Adapter()
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter) as runtime:
        def provider(symbols, now):
            runtime.pause("test operator pause")
            return quotes(symbols, now)
        runtime.quote_provider = provider
        assert runtime.capture_once()["proposal_status"] == "SUPERSEDED_POLICY"
        assert not adapter.calls and runtime.status()["counts"]["intents"] == 0
        paused = runtime.pause()
        assert paused["cancelled"] is False and paused["flattened"] is False
        assert runtime.capture_once()["status"] == "PAUSED"
        assert runtime.resume()["old_proposals_dispatched"] is False


def test_two_coordinators_cannot_claim_one_capture(tmp_path):
    with build(tmp_path) as one, build(tmp_path) as two:
        with one._lease():
            with pytest.raises(RuntimeError, match="owns the unexpired"):
                two.capture_once()
        assert two.capture_once()["status"] == "CAPTURED"


def test_order_reported_executions_persist_dedup_and_regression_is_blocked(tmp_path):
    with build(tmp_path, adapter=Adapter()) as runtime:
        state = deepcopy(Adapter().state)
        state["orders"]["O1"] = {"cum_qty": 1}
        state["executions"] = [{"order_id": "O1", "cumulative_quantity": 1, "quantity": 1,
                                "source": "derived_from_order_cumulative", "broker_deal_id": None}]
        runtime.persist_adapter_state(state)
        runtime.persist_adapter_state(state)
        assert runtime.status()["counts"]["executions"] == 1
        state["orders"]["O1"]["cum_qty"] = 2
        state["executions"].append({"order_id": "O1", "cumulative_quantity": 2, "quantity": 1,
                                    "source": "derived_from_order_cumulative", "broker_deal_id": None})
        runtime.persist_adapter_state(state)
        assert runtime.status()["counts"]["executions"] == 2
        state["orders"]["O1"]["cum_qty"] = 1
        with pytest.raises(RuntimeError, match="cannot regress"):
            runtime.persist_adapter_state(state)
        assert runtime.status()["counts"]["executions"] == 2


def test_watch_is_explicit_bounded_sleep_and_stops_after_requested_cycles(tmp_path):
    clock = Clock("2026-11-26T16:00:00Z")
    sleeps = []
    with build(tmp_path, clock=clock) as runtime:
        def sleep(seconds):
            assert 0 < seconds <= 30
            sleeps.append(seconds)
            clock.value += timedelta(seconds=seconds)
        outcomes = runtime.watch(max_cycles=2, sleeper=sleep)
        assert [row["status"] for row in outcomes] == ["MARKET_CLOSED", "MARKET_CLOSED"]
        assert sleeps and runtime.status()["counts"]["snapshots"] == 0


def test_durable_order_terminal_timestamp_and_cancel_state_cannot_regress(tmp_path):
    with build(tmp_path, adapter=Adapter()) as runtime:
        state = deepcopy(Adapter().state)
        state["orders"]["O1"] = {"cum_qty": 0, "status": "CANCELLED_ALL", "updated_at": "2024-03-11 10:00:02"}
        state["cancel_intents"]["O1"] = {"status": "ACKNOWLEDGED"}
        runtime.persist_adapter_state(state)
        stale = deepcopy(state)
        stale["orders"]["O1"].update(status="SUBMITTED", updated_at="2024-03-11 10:00:01")
        with pytest.raises(RuntimeError, match="terminal status|timestamp"):
            runtime.persist_adapter_state(stale)
        stale = deepcopy(state)
        stale["cancel_intents"]["O1"]["status"] = "SUBMITTING"
        with pytest.raises(RuntimeError, match="cancel intent"):
            runtime.persist_adapter_state(stale)
        saved = json.loads(runtime.db.execute("SELECT payload FROM broker_states").fetchone()[0])
        assert saved["orders"]["O1"]["status"] == "CANCELLED_ALL"
        assert saved["cancel_intents"]["O1"]["status"] == "ACKNOWLEDGED"


def test_slow_commit_rechecks_actual_quote_age_before_rpc(tmp_path):
    clock, adapter = Clock(), Adapter()
    with build(tmp_path, clock=clock, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        original = runtime._audit
        def delayed_commit(kind, payload):
            original(kind, payload)
            if kind == "INTENT_COMMITTED_BEFORE_RPC":
                clock.value += timedelta(seconds=6)
        runtime._audit = delayed_commit
        assert runtime.capture_once()["proposal_status"] == "RISK_BLOCKED"
        assert not adapter.calls
        assert runtime.db.execute("SELECT status FROM intents").fetchone()[0] == "CANCELLED_BEFORE_RPC"
        assert runtime.status()["unresolved_intents"] == 0


def test_inflight_account_switch_rejected_but_mode_change_allowed(tmp_path):
    adapter = Adapter()
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "DISPATCHED"
    with pytest.raises(RuntimeError, match="in-flight"):
        build(tmp_path, scope="another-account")
    with build(tmp_path, mode="ALERT_ONLY") as runtime:
        assert runtime.policy()["mode"] == "ALERT_ONLY"
        assert runtime.policy()["environment"] == "BROKER_PAPER"


def test_callback_physical_namespace_does_not_follow_changed_policy_label(tmp_path):
    with build(tmp_path, adapter=Adapter()) as runtime:
        namespace = runtime.bind_paper_adapter(runtime.paper_adapter)
        callback = runtime.paper_adapter.persist_state
        state = runtime.paper_adapter.export_state()
        callback(state)
        runtime.db.execute("UPDATE policy SET account='different-logical-label',epoch=epoch+1")
        callback(state)
        keys = [row[0] for row in runtime.db.execute("SELECT account FROM broker_states")]
        assert keys == [namespace]
        assert json.loads(namespace) == ["fake_paper", "int", 101]
        assert "different-logical-label" not in namespace


def test_unknown_recovery_cli_flow_and_paused_closed_monitor_do_not_submit(tmp_path):
    # Reuse the established fake SDK/context around the actual paper adapter;
    # no duplicated recovery algorithm and no network endpoint exists here.
    import runpy
    helpers = runpy.run_path(str(Path(__file__).with_name("test_veighna_bridge.py")))
    adapter, context = helpers["configured"]()
    context.funds = [{"us_cash": 10000, "total_assets": 10000}]
    context.positions = []
    context.submit_error = True
    clock = Clock()
    with build(tmp_path, clock=clock, symbols=("AAA",), mode="AUTO_EXECUTE", environment="BROKER_PAPER",
               adapter=adapter, quote_provider=quotes) as runtime:
        assert runtime.capture_once()["proposal_status"] == "SUBMISSION_UNKNOWN"
        client_id = runtime.db.execute("SELECT id FROM intents").fetchone()[0]
        runtime.pause("keep watching the outstanding order")
        runtime.db.execute("UPDATE policy SET mode='ALERT_ONLY',epoch=epoch+1")
        context.order_rows = [{"order_id": "O1", "code": "US.AAA", "remark": client_id,
            "qty": 1, "price": 100, "trd_side": "BUY", "dealt_qty": 0, "dealt_avg_price": 0,
            "order_status": "SUBMITTED", "updated_time": "2024-03-11 10:00:01"}]
        assert runtime.reconcile()["status"] == "RECONCILED"
        assert adapter.status == "READY" and runtime.status()["unresolved_intents"] == 0
        assert runtime.db.execute("SELECT status FROM intents").fetchone()[0] == "SUBMITTED"
        clock.value = datetime(2026, 11, 26, 16, tzinfo=timezone.utc)
        before = len(context.calls)
        assert runtime.monitor_once()["status"] == "RECONCILED"
        assert len(context.calls) == before+3  # funds, positions, orders, no submit.
        assert runtime.monitor_once()["status"] == "MONITOR_NOT_DUE"
        assert len(context.calls) == before+3
        context.order_rows[0].update(dealt_qty=1, dealt_avg_price=100, order_status="FILLED_ALL", updated_time="2024-03-11 10:00:02")
        clock.value += timedelta(seconds=31)
        assert runtime.monitor_once()["status"] == "RECONCILED"
        assert runtime.status()["counts"]["executions"] == 1
        assert runtime.db.execute("SELECT status FROM intents").fetchone()[0] == "FILLED_ALL"
        assert sum(name == "place_order" for name, _ in context.calls) == 1
        assert runtime.policy()["paused"] and runtime.policy()["mode"] == "ALERT_ONLY"


def _cli_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("execution_runtime_cli_test", Path(__file__).parents[1] / "scripts" / "run_trading_system.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shadow_replay_never_opens_active_runtime_or_configures_paper(tmp_path, monkeypatch):
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER") as runtime:
        original = runtime.policy()
        directory = runtime.runtime_dir
    cli = _cli_module()
    import execution_lab.veighna_bridge as bridge
    import execution_lab.rest_transport as transport
    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not construct runtime or bootstrap authentication")
    monkeypatch.setattr(cli, "TradingRuntime", forbidden)
    monkeypatch.setattr(transport, "build_rest_paper_adapter", forbidden)
    monkeypatch.setattr(bridge, "run_shadow_replay", lambda *args, **kwargs: {"status": "success", "execution_environment": "SHADOW"})
    assert cli.main(["--runtime-dir", str(directory), "--backend", "REST_sim_trade", "--paper-config", str(tmp_path / "never-read.json"),
                     "shadow-replay", "--source", "synthetic"]) == 0
    with build(tmp_path) as runtime:
        assert runtime.policy() == original
        assert runtime.status()["counts"]["audit"] == 1


@pytest.mark.parametrize("command", ["status", "pause", "resume"])
def test_inspection_policy_commands_never_bootstrap_private_paper_auth(tmp_path, monkeypatch, command):
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER") as runtime:
        directory = runtime.runtime_dir
    cli = _cli_module()
    import execution_lab.rest_transport as transport
    def forbidden(*args, **kwargs):
        raise AssertionError("This command must not read authentication or query paper accounts")
    monkeypatch.setattr(transport, "build_rest_paper_adapter", forbidden)
    assert cli.main(["--runtime-dir", str(directory), "--backend", "REST_sim_trade", "--paper-config", str(tmp_path / "never-read.json"), command]) == 0


def test_optional_dispatcher_is_the_only_submit_entrypoint(tmp_path):
    adapter, seen = Adapter(), []
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        def dispatcher(**payload):
            seen.append(payload)
            return adapter.submit_limit(**payload)
        runtime.order_dispatcher = dispatcher
        assert runtime.capture_once()["proposal_status"] == "DISPATCHED"
        assert len(seen) == len(adapter.calls) == 1
        assert runtime.status()["order_path"] == "injected_gateway_dispatcher"


def test_oms_observer_sees_committed_state_copy_without_changing_the_journal(tmp_path):
    with build(tmp_path, adapter=Adapter()) as runtime:
        state = runtime.paper_adapter.export_state()
        state["orders"]["O1"] = {"cum_qty": 1, "status": "FILLED_ALL"}
        class Observer:
            def __call__(self, **kwargs):
                raise AssertionError("Projection must not submit")
            def sync_from_state(self, observed):
                with sqlite3.connect(runtime.runtime_dir / "journal.sqlite3") as reader:
                    durable = json.loads(reader.execute("SELECT payload FROM broker_states").fetchone()[0])
                    assert durable["orders"]["O1"]["cum_qty"] == 1
                observed["orders"]["O1"]["cum_qty"] = 999  # Must be an isolated copy.
        runtime.order_dispatcher = Observer()
        runtime.persist_adapter_state(state)
        assert state["orders"]["O1"]["cum_qty"] == 1
        saved = json.loads(runtime.db.execute("SELECT payload FROM broker_states").fetchone()[0])
        assert saved["orders"]["O1"]["cum_qty"] == 1
        assert runtime.status()["oms_projection_healthy"]


def test_oms_failure_keeps_sql_committed_blocks_new_intents_and_can_reconcile(tmp_path):
    adapter = Adapter()
    class Observer:
        fail = True
        def __call__(self, **kwargs):
            return adapter.submit_limit(**kwargs)
        def sync_from_state(self, observed):
            if self.fail:
                raise ValueError("fake OMS unavailable")
    observer = Observer()
    with build(tmp_path, mode="AUTO_EXECUTE", environment="BROKER_PAPER", adapter=adapter, quote_provider=quotes) as runtime:
        runtime.order_dispatcher = observer
        runtime.persist_adapter_state(adapter.export_state())  # Does not misreport SQL rollback.
        assert runtime.db.execute("SELECT COUNT(*) FROM broker_states").fetchone()[0] == 1
        failed = runtime.db.execute("SELECT payload FROM audit WHERE kind='OMS_SYNC_FAILED'").fetchone()
        assert json.loads(failed[0])["state_committed"] is True
        assert not runtime.status()["oms_projection_healthy"]
        assert runtime.capture_once()["proposal_status"] == "BLOCKED_OMS_SYNC"
        assert not adapter.calls
    with build(tmp_path, adapter=adapter, quote_provider=quotes) as runtime:
        assert not runtime.status()["oms_projection_healthy"]
        observer.fail = False
        runtime.order_dispatcher = observer
        assert runtime.reconcile()["status"] == "RECONCILED"
        assert runtime.status()["oms_projection_healthy"]
        assert not adapter.calls  # Recovery never executes an old proposal.


def test_runtime_routes_through_real_veighna_paper_gateway_and_projects_committed_fills(tmp_path):
    import runpy
    from execution_lab.paper_gateway import PaperGatewaySession
    helpers = runpy.run_path(str(Path(__file__).with_name("test_veighna_bridge.py")))
    adapter, context = helpers["configured"]()
    context.funds = [{"us_cash": 10000, "total_assets": 10000}]
    context.positions = []
    clock = Clock()
    with build(tmp_path, clock=clock, symbols=("AAA",), mode="AUTO_EXECUTE", environment="BROKER_PAPER",
               adapter=adapter, quote_provider=quotes) as runtime:
        with PaperGatewaySession(runtime_dir=tmp_path / "real-veighna-paper", adapter=adapter, clock=clock) as gateway:
            runtime.order_dispatcher = gateway
            result = runtime.capture_once()
            assert result["proposal_status"] == "DISPATCHED" and result["oms_projection_healthy"]
            assert runtime.status()["order_path"] == "veighna_main_engine_paper_gateway"
            assert gateway.route_count == 1
            assert len(gateway.main.get_all_orders()) == 1 and len(gateway.main.get_all_trades()) == 0
            client_id = runtime.db.execute("SELECT id FROM intents").fetchone()[0]
            context.order_rows = [{"order_id": "O1", "code": "US.AAA", "remark": client_id,
                "qty": 1, "price": 100, "trd_side": "BUY", "dealt_qty": 1, "dealt_avg_price": 100,
                "order_status": "FILLED_ALL", "updated_time": "2024-03-11 10:05:12"}]
            context.positions = [{"code": "US.AAA", "qty": 1, "can_sell_qty": 1}]
            clock.value += timedelta(seconds=2)
            assert runtime.reconcile()["status"] == "RECONCILED"
            assert runtime.status()["counts"]["executions"] == 1
            assert len(gateway.main.get_all_trades()) == 1
            trade = gateway.main.get_all_trades()[0]
            assert trade.extra["source"] == "derived_from_order_cumulative" and trade.extra["broker_deal_id"] is None
            assert gateway.main.get_all_orders()[0].status.name == "ALLTRADED"
            runtime.reconcile()
            assert len(gateway.main.get_all_trades()) == 1  # Re-query cannot duplicate the projection.
            report = gateway.report()
            assert report["broker_connection_created"] is False
            assert report["account_projection"].startswith("unavailable")
            calls_before_close = len(context.calls)
        assert len(context.calls) == calls_before_close
        assert not any(name == "modify_order" for name, _ in context.calls)
        assert sum(name == "place_order" for name, _ in context.calls) == 1
