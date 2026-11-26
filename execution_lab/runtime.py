"""First local persistent capture/decision coordinator, with LIVE unavailable.

Public research apps never import this module. The active SQLite file must be in
an explicit non-Dropbox directory. No constructor opens a broker connection.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .veighna_bridge import BridgeError, _at, _json, _symbol


STRATEGY_VERSION = "rth_momentum6_v1"
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MODES = {"ALERT_ONLY", "CONFIRM_BEFORE_SEND", "AUTO_EXECUTE"}
ENVIRONMENTS = {"NONE", "SHADOW", "BROKER_PAPER"}
UNKNOWN = {"SUBMITTING", "SUBMISSION_UNKNOWN", "PERSISTENCE_FAILED"}
TERMINAL = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED", "REJECTED", "CANCELLED_BEFORE_RPC"}


class RuntimeError(BridgeError):
    pass


def _dump(value):
    return json.dumps(_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stamp(value):
    return _at(value).isoformat().replace("+00:00", "Z")


def _broker_key(backend, account_id):
    if not backend or account_id is None or isinstance(account_id, bool):
        raise RuntimeError("An explicit backend and exact physical paper account ID are required.")
    return _dump([str(backend), type(account_id).__name__, account_id])


def resolve_runtime_dir(raw_path=None):
    raw_path = raw_path or os.environ.get("ALPHA_RUNTIME_DIR")
    if not raw_path or not Path(raw_path).is_absolute():
        raise RuntimeError("Set an explicit absolute non-synced ALPHA_RUNTIME_DIR or --runtime-dir.")
    directory = Path(raw_path).resolve()
    if any("dropbox" in part.casefold() for part in directory.parts):
        raise RuntimeError("The active runtime directory must be outside Dropbox.")
    return directory


@dataclass(frozen=True)
class RuntimeConfig:
    runtime_dir: str | Path | None = None
    symbols: tuple[str, ...] = ("NVDA",)
    benchmark: str = "SPY"
    # None retains the saved policy. A new database starts ALERT_ONLY + NONE.
    automation_mode: str | None = None
    execution_environment: str | None = None
    account_scope: str | None = None
    # Legacy SDK integers and REST opaque strings are different namespaces.
    paper_account_id: int | str | None = None
    max_weight: float = .2
    cash_floor: float = .2
    max_order_notional: float = 1000
    lease_seconds: int = 900


class TradingRuntime:
    def __init__(self, config: RuntimeConfig, *, market_source=None, quote_provider=None,
                 paper_adapter=None, clock=None, market_state=None, next_capture_at=None, order_dispatcher=None):
        self.config = config
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.owner = uuid.uuid4().hex
        self._last_monitor_at = None
        self.runtime_dir = resolve_runtime_dir(config.runtime_dir)
        self.symbols = tuple(sorted({_symbol(symbol) for symbol in config.symbols}))
        self.benchmark = _symbol(config.benchmark)
        if not self.symbols or len(self.symbols) > 12 or self.benchmark in self.symbols:
            raise RuntimeError("Configure 1 to 12 stocks and a separate benchmark.")
        if (config.account_scope is not None and (not config.account_scope or len(config.account_scope) > 80
                or any(character in config.account_scope for character in "\\/\r\n"))):
            raise RuntimeError("Use a bounded logical account_scope, not a filesystem path.")
        for value, name, low, high in ((config.max_weight, "max_weight", .01, 1),
                (config.cash_floor, "cash_floor", 0, .95),
                (config.max_order_notional, "max_order_notional", 1, 1000)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise RuntimeError(f"Invalid {name}.")
        if not isinstance(config.lease_seconds, int) or not 30 <= config.lease_seconds <= 3600:
            raise RuntimeError("lease_seconds must be 30..3600.")
        self._validate_policy(config.automation_mode, config.execution_environment)
        if market_state is None or next_capture_at is None:
            from . import marketdata
            market_state = market_state or marketdata.market_state
            next_capture_at = next_capture_at or marketdata.next_capture_at
        self.market_state, self.next_capture_at = market_state, next_capture_at
        self.market_source, self.quote_provider, self.paper_adapter = market_source, quote_provider, paper_adapter
        if order_dispatcher is not None and not callable(order_dispatcher):
            raise RuntimeError("order_dispatcher must be a callable paper gateway entrypoint.")
        self.order_dispatcher = order_dispatcher
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        database = self.runtime_dir / "journal.sqlite3"
        if database.is_symlink() or database.resolve().parent != self.runtime_dir:
            raise RuntimeError("The active database must be a regular file in the selected local runtime.")
        self._db_lock = threading.RLock()
        self.db = sqlite3.connect(database, timeout=5, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            self._schema()
            self._configure_policy()
            health = self.db.execute("SELECT kind FROM audit WHERE kind IN ('OMS_SYNC_FAILED','OMS_SYNC_RECOVERED') ORDER BY id DESC LIMIT 1").fetchone()
            self._oms_sync_failed = bool(health and health["kind"] == "OMS_SYNC_FAILED")
        except Exception:
            self.db.close()
            raise
        self.pool_key = hashlib.sha256(_dump({"symbols": self.symbols, "benchmark": self.benchmark,
                                              "source": "moomoo_desktop"}).encode()).hexdigest()
        self.strategy_version = STRATEGY_VERSION+"_"+hashlib.sha256(_dump({
            "pool_key": self.pool_key, "max_weight": config.max_weight, "cash_floor": config.cash_floor}).encode()).hexdigest()[:16]

    @staticmethod
    def _validate_policy(mode, environment):
        if mode is not None and mode not in MODES:
            raise RuntimeError("Unknown automation_mode.")
        if environment is not None and environment not in ENVIRONMENTS:
            raise RuntimeError("LIVE is unavailable; use NONE, SHADOW or BROKER_PAPER.")

    def _schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1),mode TEXT NOT NULL,
          environment TEXT NOT NULL,account TEXT NOT NULL,epoch INTEGER NOT NULL,paused INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY,owner TEXT NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,pool_key TEXT NOT NULL,bar_end TEXT NOT NULL,
          captured_at TEXT NOT NULL,sha256 TEXT NOT NULL,csv BLOB NOT NULL,provenance TEXT NOT NULL,
          UNIQUE(pool_key,bar_end));
        CREATE TABLE IF NOT EXISTS bars(pool_key TEXT NOT NULL,symbol TEXT NOT NULL,bar_start TEXT NOT NULL,
          payload TEXT NOT NULL,PRIMARY KEY(pool_key,symbol,bar_start));
        CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
          strategy_version TEXT NOT NULL,bar_end TEXT NOT NULL,environment TEXT NOT NULL,account TEXT NOT NULL,
          status TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(strategy_version,bar_end,environment,account));
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,signal_id TEXT NOT NULL UNIQUE REFERENCES signals(id),
          created_at TEXT NOT NULL,mode TEXT NOT NULL,environment TEXT NOT NULL,account TEXT NOT NULL,
          epoch INTEGER NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL REFERENCES proposals(id),
          created_at TEXT NOT NULL,owner TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,
          receipt TEXT,UNIQUE(proposal_id,id));
        CREATE TABLE IF NOT EXISTS broker_states(account TEXT PRIMARY KEY,updated_at TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY,account TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS immutable_snapshot_update BEFORE UPDATE ON snapshots BEGIN
          SELECT RAISE(ABORT,'immutable snapshot'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_snapshot_delete BEFORE DELETE ON snapshots BEGIN
          SELECT RAISE(ABORT,'immutable snapshot'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_bar_update BEFORE UPDATE ON bars BEGIN
          SELECT RAISE(ABORT,'immutable bar'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_bar_delete BEFORE DELETE ON bars BEGIN
          SELECT RAISE(ABORT,'immutable bar'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_signal_update BEFORE UPDATE ON signals BEGIN
          SELECT RAISE(ABORT,'immutable signal'); END;
        """)

    @contextmanager
    def _transaction(self):
        with self._db_lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            else:
                self.db.execute("COMMIT")

    def _audit(self, kind, payload):
        with self._db_lock:
            self.db.execute("INSERT INTO audit(at,kind,payload) VALUES(?,?,?)", (_stamp(self.clock()), kind, _dump(payload)))

    def _configure_policy(self):
        with self._transaction():
            old = self.db.execute("SELECT * FROM policy WHERE id=1").fetchone()
            mode = self.config.automation_mode or (old["mode"] if old else "ALERT_ONLY")
            environment = self.config.execution_environment or (old["environment"] if old else "NONE")
            account = self.config.account_scope or (old["account"] if old else "local_research")
            working = self._working_intents()
            if working and old and (environment, account) != (old["environment"], old["account"]):
                raise RuntimeError("Finish/reconcile in-flight paper orders before changing environment/account scope; mode may change.")
            if working and self.config.paper_account_id is not None:
                for intent in working:
                    namespace = json.loads(intent["payload"]).get("broker_namespace")
                    if namespace and json.loads(namespace)[2] != self.config.paper_account_id:
                        raise RuntimeError("Cannot change the physical paper account while orders remain in flight.")
            if old is None:
                self.db.execute("INSERT INTO policy VALUES(1,?,?,?,?,0)", (mode, environment, account, 1))
                self._audit("POLICY_CREATED", {"mode": mode, "environment": environment, "account": account, "epoch": 1})
            elif (mode, environment, account) != (old["mode"], old["environment"], old["account"]):
                self.db.execute("UPDATE policy SET mode=?,environment=?,account=?,epoch=epoch+1 WHERE id=1", (mode, environment, account))
                self._audit("POLICY_CHANGED_NO_OLD_DISPATCH", {"mode": mode, "environment": environment, "account": account})

    def policy(self):
        return dict(self.db.execute("SELECT * FROM policy WHERE id=1").fetchone())

    def _working_intents(self):
        return [dict(row) for row in self.db.execute("SELECT intents.* FROM intents JOIN proposals ON proposals.id=intents.proposal_id WHERE proposals.environment='BROKER_PAPER'")
                if row["status"] not in TERMINAL]

    def _adapter_namespace(self, adapter=None):
        adapter = self.paper_adapter if adapter is None else adapter
        if adapter is None:
            raise RuntimeError("No configured paper backend.")
        return _broker_key(getattr(adapter, "backend", None) or adapter.export_state().get("backend"), adapter.account_id)

    def bind_paper_adapter(self, adapter, quote_provider=None):
        namespace = self._adapter_namespace(adapter)
        if self.config.paper_account_id != adapter.account_id:
            raise RuntimeError("Configured account ID and adapter account ID must match exactly, including namespace/type.")
        if any(row["account"] != namespace for row in self.db.execute("SELECT account FROM broker_states")):
            raise RuntimeError("This runtime is bound to one physical backend/account; use a separate runtime directory, never migrate a ledger.")
        for intent in self._working_intents():
            old = json.loads(intent["payload"]).get("broker_namespace")
            if old and old != namespace:
                raise RuntimeError("Cannot switch backend/account with in-flight paper orders.")
        self.paper_adapter = adapter
        if quote_provider is not None:
            self.quote_provider = quote_provider
        adapter.persist_state = lambda state: self.persist_adapter_state(state, broker_namespace=namespace)
        return namespace

    @contextmanager
    def _lease(self):
        now = _at(self.clock())
        with self._transaction():
            old = self.db.execute("SELECT * FROM leases WHERE name='coordinator'").fetchone()
            if old and old["owner"] != self.owner and old["expires"] > _stamp(now):
                raise RuntimeError("Another coordinator owns the unexpired runtime lease.")
            self.db.execute("INSERT INTO leases VALUES('coordinator',?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires=excluded.expires",
                            (self.owner, _stamp(now+timedelta(seconds=self.config.lease_seconds))))
            abandoned = self.db.execute("SELECT id FROM intents WHERE status='SUBMITTING' AND owner<>?", (self.owner,)).fetchall()
            for row in abandoned:
                self.db.execute("UPDATE intents SET status='SUBMISSION_UNKNOWN' WHERE id=?", (row["id"],))
                self._audit("RECOVERY_SUBMISSION_UNKNOWN", {"intent_id": row["id"]})
        try:
            yield
        finally:
            self.db.execute("DELETE FROM leases WHERE name='coordinator' AND owner=?", (self.owner,))

    def _assert_lease(self):
        lease = self.db.execute("SELECT * FROM leases WHERE name='coordinator'").fetchone()
        if not lease or lease["owner"] != self.owner or lease["expires"] <= _stamp(self.clock()):
            raise RuntimeError("Runtime ownership expired; no publication or submission is permitted.")

    def capture_once(self):
        with self._lease():
            policy, as_of = self.policy(), _at(self.clock())
            if policy["paused"]:
                return self._outcome("PAUSED", {"new_orders_stopped": True, "cancelled": False, "flattened": False})
            state = self.market_state(as_of)
            if state["status"] != "READY":
                return self._outcome(state["status"], {"market": state, "broker_rpc": False})
            bar_end = _stamp(state["expected_bar_end"])
            if self.db.execute("SELECT 1 FROM snapshots WHERE pool_key=? AND bar_end=?", (self.pool_key, bar_end)).fetchone():
                return self._outcome("ALREADY_CAPTURED", {"bar_end": bar_end, "source_rpc": False})
            if self.market_source is None:
                from .marketdata import MoomooDesktopSource
                self.market_source = MoomooDesktopSource()
            try:
                frame, provenance = self.market_source.read_completed(
                    [*self.symbols, self.benchmark], as_of, self.runtime_dir)
                frame, canonical = self._validated_snapshot(frame, state, as_of)
            except Exception as error:
                return self._outcome("CAPTURE_FAILED", {"error_type": type(error).__name__,
                    "error_code": getattr(error, "code", "SOURCE_OR_DATA_CONTRACT"),
                    "signals_created": False, "orders_submitted": False, "positions_liquidated": False})
            sha = hashlib.sha256(canonical).hexdigest()
            snapshot_id = hashlib.sha256((self.pool_key+bar_end+sha).encode()).hexdigest()
            try:
                with self._transaction():
                    self._assert_lease()
                    # A correction to an earlier observed bar is evidence, not
                    # permission to rewrite a previously published signal.
                    for row in frame.itertuples(index=False):
                        payload = _dump({key: getattr(row, key) for key in ("open", "high", "low", "close", "volume")})
                        previous = self.db.execute("SELECT payload FROM bars WHERE pool_key=? AND symbol=? AND bar_start=?",
                            (self.pool_key, row.symbol, _stamp(row.timestamp))).fetchone()
                        if previous and previous["payload"] != payload:
                            raise RuntimeError("DATA_REVISION_BLOCKED")
                        self.db.execute("INSERT OR IGNORE INTO bars VALUES(?,?,?,?)", (self.pool_key, row.symbol, _stamp(row.timestamp), payload))
                    self.db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?)", (snapshot_id, self.pool_key, bar_end,
                        _stamp(as_of), sha, canonical, _dump(provenance)))
                    proposal_id = self._publish(frame, snapshot_id, bar_end, as_of, policy)
                    self._audit("CAPTURE_COMMITTED", {"snapshot_id": snapshot_id, "bar_end": bar_end, "sha256": sha})
            except RuntimeError as error:
                if str(error) == "DATA_REVISION_BLOCKED":
                    return self._outcome("DATA_REVISION_BLOCKED", {"bar_end": bar_end, "signals_created": False, "orders_submitted": False})
                raise
            if policy["mode"] == "AUTO_EXECUTE":
                self._dispatch(proposal_id, confirmed=False)
            proposal = self._proposal(proposal_id)
            return self._outcome("CAPTURED", {"snapshot_id": snapshot_id, "bar_end": bar_end,
                "proposal_id": proposal_id, "proposal_status": proposal["status"], "reason": proposal["reason"]})

    def _validated_snapshot(self, frame, state, as_of):
        import pandas as pd
        from hf_space.intraday import _validate
        frame = _validate(frame, self.benchmark, as_of=as_of)
        expected = pd.date_range(state["session_open"], state["expected_bar_end"], freq="5min", inclusive="left")
        required = set(self.symbols)|{self.benchmark}
        if set(frame.symbol) != required or any(set(group.timestamp) != set(expected) for _, group in frame.groupby("symbol")):
            raise RuntimeError("Expected a complete common within-session five-minute grid; no filling or stale snapshot.")
        canonical = frame.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode()
        return frame, canonical

    def _publish(self, frame, snapshot_id, bar_end, as_of, policy):
        closes = frame.pivot(index="timestamp", columns="symbol", values="close").sort_index()
        scores = {symbol: float(closes[symbol].iloc[-1]/closes[symbol].iloc[-7]-1) if len(closes) >= 7 else None for symbol in self.symbols}
        valid = all(value is not None for value in scores.values())
        selected = [symbol for symbol, score in scores.items() if score is not None and score > 0]
        weight = min((1-self.config.cash_floor)/len(selected), self.config.max_weight) if selected else 0
        targets = {symbol: weight if symbol in selected else 0 for symbol in self.symbols} if valid else None
        business = _dump([self.strategy_version, bar_end, policy["environment"], policy["account"]])
        signal_id = hashlib.sha256(business.encode()).hexdigest()
        signal = {"scores": scores, "score_unit": "within_session_historical_return_not_forecast",
            "lookback_bars": 6, "target_weights": targets,
            "data_sha256": self.db.execute("SELECT sha256 FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()[0],
            "bar_end": bar_end, "created_at": _stamp(as_of), "pool_key": self.pool_key}
        self.db.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?,?)", (signal_id, snapshot_id, self.strategy_version,
            bar_end, policy["environment"], policy["account"], "READY" if valid else "WARMUP", _dump(signal)))
        proposal_id = "P"+signal_id[:30]
        if not valid:
            status, reason = "WARMUP", "Seven completed within-session bars are required; no target is inferred."
        elif policy["mode"] == "ALERT_ONLY":
            status, reason = "ALERT", "Only an alert was requested; no order intent exists."
        elif policy["mode"] == "CONFIRM_BEFORE_SEND":
            status, reason = "AWAITING_CONFIRMATION", "This policy epoch requires explicit confirmation."
        else:
            status, reason = "READY", "Automatic dispatch still requires a configured paper backend, fresh quote and risk checks."
        self.db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?)", (proposal_id, signal_id, _stamp(as_of),
            policy["mode"], policy["environment"], policy["account"], policy["epoch"], status, _dump(signal), reason))
        return proposal_id

    def _proposal(self, proposal_id):
        row = self.db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise RuntimeError("Unknown proposal_id.")
        return dict(row)

    def _set_proposal(self, proposal_id, status, reason):
        self.db.execute("UPDATE proposals SET status=?,reason=? WHERE id=?", (status, reason, proposal_id))
        self._audit("PROPOSAL_STATUS", {"proposal_id": proposal_id, "status": status, "reason": reason})

    def _outcome(self, status, payload):
        self._audit(status, payload)
        return _json({"status": status, **payload, "policy": self.policy(),
                      "oms_projection_healthy": not self._oms_sync_failed, "at": _at(self.clock())})

    def _dispatch(self, proposal_id, *, confirmed):
        self._assert_lease()
        row, policy, now = self._proposal(proposal_id), self.policy(), _at(self.clock())
        if row["status"] not in {"READY", "AWAITING_CONFIRMATION", "NOT_CONFIGURED"}:
            return
        if self._oms_sync_failed:
            self._set_proposal(proposal_id, "BLOCKED_OMS_SYNC", "OMS projection failed; new orders require a successful reconciliation/projection.")
            return
        if (row["epoch"] != policy["epoch"] or row["mode"] != policy["mode"]
                or row["environment"] != policy["environment"] or row["account"] != policy["account"]):
            self._set_proposal(proposal_id, "SUPERSEDED_POLICY", "Mode/environment/account changed; old alerts are never dispatched.")
            return
        if policy["paused"]:
            self._set_proposal(proposal_id, "PAUSED", "New submissions are paused; existing orders were not cancelled.")
            return
        if row["mode"] == "ALERT_ONLY" or (row["mode"] == "CONFIRM_BEFORE_SEND" and not confirmed):
            return
        if row["environment"] != "BROKER_PAPER":
            self._set_proposal(proposal_id, "NOT_CONFIGURED", "Persistent SHADOW execution is not implemented; NONE never submits. Use separate shadow-replay.")
            return
        if self.db.execute("SELECT 1 FROM intents WHERE status IN ('SUBMITTING','SUBMISSION_UNKNOWN','PERSISTENCE_FAILED') LIMIT 1").fetchone():
            self._set_proposal(proposal_id, "BLOCKED_UNKNOWN", "An unresolved intent blocks all new submissions until trusted reconciliation.")
            return
        adapter = self.paper_adapter
        if (adapter is None or self.quote_provider is None or self.config.paper_account_id is None
                or getattr(adapter, "account_id", None) != self.config.paper_account_id
                or getattr(adapter, "status", "NOT_CONFIGURED") != "READY"):
            self._set_proposal(proposal_id, "NOT_CONFIGURED", "Explicit verified US paper account, adapter and fresh quote provider are required.")
            return
        market = self.market_state(now)
        if market["status"] != "READY" or not (market["session_open"] <= now < market["session_close"]):
            self._set_proposal(proposal_id, "RISK_BLOCKED", "Paper dispatch is RTH only.")
            return
        payload = json.loads(row["payload"])
        # This pilot never executes a delayed signal on confirmation/restart.
        if not 0 <= (now-_at(payload["bar_end"])).total_seconds() <= 60:
            self._set_proposal(proposal_id, "EXPIRED", "Proposal is no longer within its one-minute dispatch window.")
            return
        try:
            namespace = self.bind_paper_adapter(adapter)
            stored = self.db.execute("SELECT payload FROM broker_states WHERE account=?", (namespace,)).fetchone()
            if stored:
                adapter.restore_state(json.loads(stored["payload"]))
            reconciliation = adapter.reconcile()
            if reconciliation.get("status") not in {"queried", "matched"} or getattr(adapter, "requires_reconciliation", True):
                raise RuntimeError("Paper account has unresolved reconciliation state.")
            if any(str(order.get("order_status", "")) not in TERMINAL for order in reconciliation.get("orders", [])):
                raise RuntimeError("A working paper order must finish/reconcile before another target is submitted.")
            positions = {str(position["code"]): position for position in reconciliation.get("positions", [])}
            funds = reconciliation.get("funds", [])
            if len(funds) != 1:
                raise RuntimeError("A unique USD equity/cash observation is required.")
            equity, usd_cash = float(funds[0]["total_assets"]), float(funds[0]["us_cash"])
            if not math.isfinite(equity) or equity <= 0 or not math.isfinite(usd_cash) or usd_cash < 0:
                raise RuntimeError("USD equity/cash is unavailable; buying power is not a substitute.")
            owned = {symbol: 0. for symbol in self.symbols}
            for execution_row in self.db.execute("SELECT payload FROM executions WHERE account=?", (namespace,)):
                execution = json.loads(execution_row["payload"])
                symbol = execution.get("symbol")
                if symbol not in owned:
                    continue
                if execution.get("side") not in {"BUY", "SELL"}:
                    raise RuntimeError("Persisted execution side is unknown; ownership cannot be inferred.")
                owned[symbol] += float(execution["quantity"])*(1 if execution["side"] == "BUY" else -1)
            quotes = self.quote_provider(list(self.symbols), _at(self.clock()))
            now = _at(self.clock())
            if not isinstance(quotes, dict) or set(quotes) != set(self.symbols):
                raise RuntimeError("Quote provider must return every configured stock.")
            if not 0 <= (now-_at(payload["bar_end"])).total_seconds() <= 60:
                raise RuntimeError("Proposal expired during broker/quote checks.")
            planned = []
            for symbol in self.symbols:
                quote = quotes[symbol]
                price, quote_at = float(quote["price"]), _at(quote["timestamp"])
                if not math.isfinite(price) or price <= 0 or not 0 <= (now-quote_at).total_seconds() <= 5:
                    raise RuntimeError("A fresh quote (age <=5s) is required; bar-close references cannot submit.")
                position = positions.get(f"US.{symbol}", {})
                held = float(position.get("qty", 0))
                sellable = float(position["can_sell_qty"]) if held else 0
                if held not in (0, 1) or sellable not in (0, 1) or owned[symbol] != held:
                    raise RuntimeError("Pilot only manages known 0/1-share long positions; no account migration.")
                target = 1 if payload["target_weights"][symbol] > 0 else 0
                delta = target-int(held)
                if delta:
                    price = float(quote.get("buy_price" if delta > 0 else "sell_price", quote["price"]))
                    if not math.isfinite(price) or price <= 0:
                        raise RuntimeError("Invalid side-specific limit reference.")
                    if abs(delta) != 1 or price > self.config.max_order_notional or delta < 0 and sellable < 1:
                        raise RuntimeError("One-share/max-notional/sellable-share risk check failed.")
                    # A declared conservative fee reserve is a pilot budget,
                    # not a broker fee quote. Reconcile actual cash before the
                    # next intent; never use margin power as cash or equity.
                    fee_reserve = max(1., price*.01)
                    after_equity = equity-fee_reserve
                    after_cash = usd_cash-price*delta-fee_reserve
                    if (after_equity <= 0 or target*price > self.config.max_weight*after_equity
                            or after_cash < self.config.cash_floor*after_equity):
                        raise RuntimeError("One-share target violates the USD equity cap or cash floor after fee reserve.")
                    planned.append({"symbol": symbol, "side": "BUY" if delta > 0 else "SELL", "quantity": 1,
                                    "price": price, "quote_at": _stamp(quote_at), "fee_reserve": fee_reserve,
                                    "usd_equity": equity, "usd_cash": usd_cash, "owned_quantity": owned[symbol],
                                    "broker_namespace": namespace})
            planned.sort(key=lambda item: (item["side"] != "SELL", item["symbol"]))
        except Exception as error:
            self._set_proposal(proposal_id, "RISK_BLOCKED", f"Pre-submission checks failed ({type(error).__name__}); no new order.")
            return
        if not planned:
            self._set_proposal(proposal_id, "NO_ACTION", "Queried paper positions already match 0/1-share pilot targets.")
            return
        for number, economics in enumerate(planned):
            intent_id = "I"+hashlib.sha256((proposal_id+economics["symbol"]+economics["side"]).encode()).hexdigest()[:40]
            with self._transaction():
                self._assert_lease()
                current_policy = self.policy()
                if current_policy["paused"] or current_policy["epoch"] != policy["epoch"]:
                    self._set_proposal(proposal_id, "SUPERSEDED_POLICY", "Policy changed during risk checks; no new intent.")
                    return
                if self.db.execute("SELECT 1 FROM intents WHERE id=?", (intent_id,)).fetchone():
                    self._set_proposal(proposal_id, "BLOCKED_EXISTING_INTENT", "An existing intent is never resent from a proposal.")
                    return
                self.db.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,NULL)", (intent_id, proposal_id, _stamp(now),
                    self.owner, "SUBMITTING", _dump(economics)))
                self._audit("INTENT_COMMITTED_BEFORE_RPC", {"intent_id": intent_id, "proposal_id": proposal_id})
            try:
                # Repeat immediately before crossing the actual RPC boundary;
                # slow queries, SQLite commits or policy changes do not grant
                # permission to use an old quote/expired proposal.
                send_at = _at(self.clock())
                send_market, send_policy = self.market_state(send_at), self.policy()
                self._assert_lease()
                if (send_policy["paused"] or send_policy["epoch"] != policy["epoch"]
                        or send_market["status"] != "READY"
                        or not send_market["session_open"] <= send_at < send_market["session_close"]
                        or not 0 <= (send_at-_at(economics["quote_at"])).total_seconds() <= 5
                        or not 0 <= (send_at-_at(payload["bar_end"])).total_seconds() <= 60):
                    with self._transaction():
                        self.db.execute("UPDATE intents SET status='CANCELLED_BEFORE_RPC' WHERE id=?", (intent_id,))
                        self._set_proposal(proposal_id, "RISK_BLOCKED", "Market/policy/quote/proposal changed before RPC; committed intent was not sent.")
                    return
                submit = self.order_dispatcher or adapter.submit_limit
                receipt = submit(client_id=intent_id, symbol=economics["symbol"], side=economics["side"],
                    quantity=1, price=economics["price"], quote_at=economics["quote_at"], as_of=send_at)
                with self._transaction():
                    # Durable callback state may already contain a later fill;
                    # a delayed submit response must not regress that truth.
                    self.db.execute("UPDATE intents SET status=CASE WHEN status='SUBMITTING' THEN ? ELSE status END,receipt=? WHERE id=?",
                                    (receipt["status"], _dump(receipt), intent_id))
                    self._audit("PAPER_SUBMISSION_RETURNED", {"intent_id": intent_id, "status": receipt["status"]})
            except Exception as error:
                with self._transaction():
                    self.db.execute("UPDATE intents SET status='SUBMISSION_UNKNOWN' WHERE id=?", (intent_id,))
                    self._set_proposal(proposal_id, "SUBMISSION_UNKNOWN", f"Submission requires reconciliation ({type(error).__name__}); no retry.")
                return
            # One submit per capture/confirmation. Further targets wait for a
            # genuinely new signal after fills/reconciliation, never rapid loops.
            self._set_proposal(proposal_id, "DISPATCHED", "One-share paper intent submitted; broker fills remain external evidence.")
            if len(planned) > 1:
                self._audit("ADDITIONAL_TARGETS_NOT_DISPATCHED", {"proposal_id": proposal_id, "count": len(planned)-1})
            return

    def persist_adapter_state(self, state, *, broker_namespace=None):
        """Bridge sink: SQLite FULL transaction commits before RPC/event return."""
        if (state.get("execution_environment") != "BROKER_PAPER"
                or state.get("account_id") != self.config.paper_account_id or self.config.paper_account_id is None):
            raise RuntimeError("Adapter state does not belong to the selected paper account.")
        account = _broker_key(state.get("backend"), state["account_id"])
        if broker_namespace is not None and broker_namespace != account:
            raise RuntimeError("An old callback cannot migrate into another physical broker/account namespace.")
        with self._transaction():
            previous = self.db.execute("SELECT payload FROM broker_states WHERE account=?", (account,)).fetchone()
            if previous:
                old = json.loads(previous["payload"])
                if old.get("backend") != state.get("backend") or old.get("account_id") != state.get("account_id"):
                    raise RuntimeError("Never mix backend/account identities in persisted broker state.")
                for order_id, order in old.get("orders", {}).items():
                    new = state.get("orders", {}).get(order_id, {})
                    if new.get("cum_qty", -1) < order.get("cum_qty", 0):
                        raise RuntimeError("Broker-state cumulative quantity cannot regress.")
                    if (order.get("status") in TERMINAL and new.get("status") != order["status"]
                            or order.get("updated_at") and (not new.get("updated_at") or new["updated_at"] < order["updated_at"])):
                        raise RuntimeError("Broker-state terminal status or update timestamp cannot regress.")
                progress = {"SUBMITTING": 0, "ACKNOWLEDGED": 1, "SUBMISSION_UNKNOWN": 2}
                for order_id, cancel in old.get("cancel_intents", {}).items():
                    new = state.get("cancel_intents", {}).get(order_id, {})
                    if progress.get(new.get("status"), -1) < progress.get(cancel.get("status"), 0):
                        raise RuntimeError("A durable cancel intent cannot regress or disappear.")
                for client_id, intent in old.get("intents", {}).items():
                    new = state.get("intents", {}).get(client_id, {})
                    if intent.get("status") in TERMINAL and new.get("status") != intent["status"]:
                        raise RuntimeError("A durable terminal intent cannot regress.")
            self.db.execute("INSERT INTO broker_states VALUES(?,?,?) ON CONFLICT(account) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                            (account, _stamp(self.clock()), _dump(state)))
            for client_id, intent in state.get("intents", {}).items():
                current = self.db.execute("SELECT payload FROM intents WHERE id=?", (client_id,)).fetchone()
                if current and json.loads(current["payload"]).get("broker_namespace") == account:
                    self.db.execute("UPDATE intents SET status=?,receipt=? WHERE id=?", (intent["status"], _dump(intent), client_id))
            for execution in state.get("executions", []):
                key = hashlib.sha256(_dump([state["backend"], state["account_id"], execution["order_id"], execution["cumulative_quantity"]]).encode()).hexdigest()
                self.db.execute("INSERT OR IGNORE INTO executions VALUES(?,?,?)", (key, account, _dump(execution)))
            self._audit("BROKER_STATE_DURABLE", {"account": account, "order_count": len(state.get("orders", {}))})
        # SQLite has committed. An OMS observer is a projection of that truth,
        # not a second journal, broker operation or reason to roll SQL back.
        self._sync_oms(state)

    def _sync_oms(self, state, *, recovery=False):
        observer = getattr(self.order_dispatcher, "sync_from_state", None)
        if not callable(observer):
            return not self._oms_sync_failed
        try:
            observer(json.loads(_dump(state)))
        except Exception as error:
            self._oms_sync_failed = True
            self._audit("OMS_SYNC_FAILED", {"state_committed": True, "error_type": type(error).__name__,
                "broker_namespace": _broker_key(state.get("backend"), state.get("account_id")),
                "new_orders_blocked": True})
            return False
        if recovery and self._oms_sync_failed:
            self._oms_sync_failed = False
            self._audit("OMS_SYNC_RECOVERED", {"state_committed": True, "full_state_projected": True})
        return not self._oms_sync_failed

    def reconcile(self, *, only_working=False):
        """Read/recover owned paper orders even while paused or in alert mode.

        It never dispatches a proposal. Unknown intents only become known through
        the adapter's exact unique remark/economics/account query matching.
        """
        with self._lease():
            if self.policy()["environment"] != "BROKER_PAPER" or self.paper_adapter is None:
                return self._outcome("NOT_CONFIGURED", {"operation": "reconcile", "orders_submitted": False})
            adapter = self.paper_adapter
            if getattr(adapter, "account_id", None) != self.config.paper_account_id or getattr(adapter, "status", "NOT_CONFIGURED") not in {"READY", "SUBMISSION_UNKNOWN"}:
                return self._outcome("NOT_CONFIGURED", {"operation": "reconcile", "orders_submitted": False})
            namespace = self.bind_paper_adapter(adapter)
            owned = [intent for intent in self._working_intents() if json.loads(intent["payload"]).get("broker_namespace") == namespace]
            if only_working and not owned:
                return {"status": "NO_WORKING_ORDERS", "orders_submitted": False}
            try:
                stored = self.db.execute("SELECT payload FROM broker_states WHERE account=?", (namespace,)).fetchone()
                state = json.loads(stored["payload"]) if stored else adapter.export_state()
                for intent in owned:
                    if intent["status"] not in UNKNOWN or intent["id"] in state["intents"]:
                        continue
                    economics = json.loads(intent["payload"])
                    state["intents"][intent["id"]] = {"client_id": intent["id"], "order_id": None,
                        "status": "SUBMISSION_UNKNOWN", "payload": {"symbol": economics["symbol"], "side": economics["side"],
                            "quantity": economics["quantity"], "price": str(economics["price"])}}
                adapter.restore_state(state)
                report = adapter.reconcile()
                self._sync_oms(adapter.export_state(), recovery=True)
                remaining = any(intent["status"] in UNKNOWN and json.loads(intent["payload"]).get("broker_namespace") == namespace
                                for intent in self._working_intents())
                return self._outcome("RECONCILED" if report.get("status") in {"queried", "matched"} and not remaining else "RECONCILIATION_PENDING",
                    {"operation": "reconcile", "broker_namespace": namespace, "broker_status": report.get("status"),
                     "unknown_resolution": report.get("unknown_resolution", []), "orders_submitted": False})
            except Exception as error:
                return self._outcome("RECONCILIATION_FAILED", {"error_type": type(error).__name__, "orders_submitted": False})

    def monitor_once(self):
        now = _at(self.clock())
        if self._last_monitor_at is not None and (now-self._last_monitor_at).total_seconds() < 30:
            return {"status": "MONITOR_NOT_DUE", "orders_submitted": False}
        result = self.reconcile(only_working=True)
        if result["status"] not in {"NOT_CONFIGURED", "NO_WORKING_ORDERS"}:
            self._last_monitor_at = now
        return result

    def confirm(self, proposal_id):
        with self._lease():
            proposal = self._proposal(proposal_id)
            if proposal["mode"] != "CONFIRM_BEFORE_SEND":
                return self._outcome("CONFIRMATION_REJECTED", {"proposal_id": proposal_id, "reason": "Only proposals created in confirmation mode can be confirmed."})
            self._audit("CONFIRMATION_REQUESTED", {"proposal_id": proposal_id})
            self._dispatch(proposal_id, confirmed=True)
            return self._outcome("CONFIRMATION_PROCESSED", {"proposal_id": proposal_id, "proposal_status": self._proposal(proposal_id)["status"]})

    def pause(self, reason="operator pause"):
        with self._transaction():
            self.db.execute("UPDATE policy SET paused=1,epoch=epoch+1 WHERE id=1")
            self._audit("PAUSED_NO_CANCEL_NO_FLATTEN", {"reason": str(reason)[:240]})
        return {"status": "PAUSED", "cancelled": False, "flattened": False, "policy": self.policy()}

    def resume(self):
        with self._transaction():
            self.db.execute("UPDATE policy SET paused=0,epoch=epoch+1 WHERE id=1")
            self._audit("RESUMED_NEW_SIGNALS_ONLY", {})
        return {"status": "RESUMED", "old_proposals_dispatched": False, "policy": self.policy()}

    def status(self):
        counts = {table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("snapshots", "signals", "proposals", "intents", "executions", "audit")}
        proposals = [dict(row) for row in self.db.execute("SELECT id,created_at,status,reason,mode,environment,epoch FROM proposals ORDER BY created_at DESC LIMIT 10")]
        unknown = self.db.execute("SELECT COUNT(*) FROM intents WHERE status IN ('SUBMITTING','SUBMISSION_UNKNOWN','PERSISTENCE_FAILED')").fetchone()[0]
        return {"status": "READY", "policy": self.policy(), "counts": counts, "recent_proposals": proposals,
            "strategy_version": self.strategy_version, "code_sha256": _CODE_SHA256,
            "unresolved_intents": unknown, "paper_backend": getattr(self.paper_adapter, "status", "NOT_CONFIGURED"),
            "order_path": getattr(self.order_dispatcher, "order_path", "injected_gateway_dispatcher") if self.order_dispatcher else "direct_adapter_pilot_not_vnpy_gateway",
            "oms_projection_healthy": not self._oms_sync_failed,
            "live_supported": False, "persistent_shadow_supported": False,
            "scope": "first runnable increment; full M1 and actual broker-paper loop are not yet accepted"}

    def watch(self, *, max_cycles=None, sleeper=time.sleep, stop_event=None):
        if max_cycles is not None and (not isinstance(max_cycles, int) or max_cycles < 1):
            raise RuntimeError("max_cycles must be positive or None.")
        outcomes, cycles = [], 0
        while max_cycles is None or cycles < max_cycles:
            if stop_event is not None and stop_event.is_set():
                break
            outcome = self.capture_once()
            outcomes.append(outcome)
            outcomes = outcomes[-20:]
            cycles += 1
            if self.paper_adapter is not None and self._working_intents():
                self.monitor_once()
            if max_cycles is not None and cycles >= max_cycles:
                break
            wake = _at(self.next_capture_at(_at(self.clock())))
            while _at(self.clock()) < wake:
                if stop_event is not None and stop_event.is_set():
                    return outcomes
                sleeper(min(30, max(.1, (wake-_at(self.clock())).total_seconds())))
                if self.paper_adapter is not None and self._working_intents():
                    self.monitor_once()
        return outcomes

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
