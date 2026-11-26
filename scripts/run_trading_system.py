"""Explicit foreground commands for the local/private coordinator."""
from __future__ import annotations

import argparse
from dataclasses import replace
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_lab.runtime import RuntimeConfig, TradingRuntime, resolve_runtime_dir


def parser():
    result = argparse.ArgumentParser(description="Local capture/strategy/paper pilot; LIVE unavailable.")
    result.add_argument("--runtime-dir", default=None, help="Explicit non-synced absolute directory, or ALPHA_RUNTIME_DIR")
    result.add_argument("--symbols", default="NVDA", help="Comma-separated stocks; benchmark is separate")
    result.add_argument("--benchmark", default="SPY")
    result.add_argument("--mode", choices=["ALERT_ONLY", "CONFIRM_BEFORE_SEND", "AUTO_EXECUTE"])
    result.add_argument("--environment", choices=["NONE", "SHADOW", "BROKER_PAPER"])
    result.add_argument("--account-scope", default=None, help="Retain saved scope unless explicitly changed")
    result.add_argument("--paper-account-id", help="Opaque REST paper ID is preserved as text; no implicit SDK-ID conversion")
    result.add_argument("--backend", choices=["REST_sim_trade"], help="Explicit paper-only backend; default loads no authentication")
    result.add_argument("--paper-config", help="Explicit private REST paper configuration; no login/keyring discovery")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("capture-once")
    commands.add_parser("status")
    commands.add_parser("reconcile", help="Read/recover owned paper order state; never dispatch old proposals")
    watch = commands.add_parser("watch", help="Foreground loop only; no service or scheduled task is installed")
    watch.add_argument("--max-cycles", type=int)
    confirmation = commands.add_parser("confirm")
    confirmation.add_argument("proposal_id")
    pause = commands.add_parser("pause", help="Stop new submissions; does not cancel or flatten")
    pause.add_argument("--reason", default="operator pause")
    commands.add_parser("resume", help="Resume new signals only; never dispatch old alerts")
    replay = commands.add_parser("shadow-replay", help="Separate nonpersistent local VeighNa replay")
    replay.add_argument("--source", choices=["moomoo", "synthetic"], required=True)
    replay.add_argument("--csv", help="Explicit real CSV path; required with --source moomoo")
    replay.add_argument("--output", help="Explicit local JSON output path; never uploaded")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    config = RuntimeConfig(runtime_dir=args.runtime_dir, symbols=tuple(args.symbols.split(",")),
        benchmark=args.benchmark, automation_mode=args.mode, execution_environment=args.environment,
        account_scope=args.account_scope, paper_account_id=args.paper_account_id)
    try:
        if args.command == "shadow-replay":
            # REPLAY never opens the active journal or reads its saved mode.
            # It cannot bootstrap a paper adapter even if policy was AUTO.
            value = _shadow_replay(args)
            print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        with ExitStack() as stack:
            runtime = stack.enter_context(TradingRuntime(config))
            can_configure = args.command in {"capture-once", "watch", "confirm", "reconcile"}
            if can_configure and args.paper_config and not args.backend:
                raise ValueError("--paper-config requires an explicit --backend REST_sim_trade.")
            if can_configure and args.backend:
                if runtime.policy()["environment"] != "BROKER_PAPER":
                    raise ValueError("An explicit BROKER_PAPER environment is required before configuring a backend.")
                for stored in runtime.db.execute("SELECT payload FROM broker_states"):
                    saved = json.loads(stored["payload"])
                    if saved.get("backend") != args.backend:
                        raise ValueError("Saved backend differs; no implicit SDK/REST account migration is permitted.")
                from execution_lab.marketdata import make_quote_provider
                from execution_lab.rest_transport import build_rest_paper_adapter
                provider = make_quote_provider(runtime_dir=runtime.runtime_dir)
                adapter = build_rest_paper_adapter(backend=args.backend, config_path=args.paper_config,
                    quote_provider=provider, persist_state=None)
                if getattr(adapter, "status", "NOT_CONFIGURED") in {"READY", "SUBMISSION_UNKNOWN"}:
                    if args.paper_account_id is not None and args.paper_account_id != adapter.account_id:
                        raise ValueError("CLI paper ID does not match the explicitly configured REST account string.")
                    runtime.config = replace(runtime.config, paper_account_id=adapter.account_id)
                    runtime.bind_paper_adapter(adapter, provider)
                    from execution_lab.paper_gateway import PaperGatewaySession
                    session = stack.enter_context(PaperGatewaySession(runtime_dir=runtime.runtime_dir / "veighna-paper", adapter=adapter))
                    runtime.order_dispatcher = session
                else:
                    runtime.paper_adapter = adapter
            if args.command == "capture-once":
                value = runtime.capture_once()
            elif args.command == "status":
                value = runtime.status()
            elif args.command == "reconcile":
                value = runtime.reconcile()
            elif args.command == "watch":
                value = runtime.watch(max_cycles=args.max_cycles)
            elif args.command == "confirm":
                value = runtime.confirm(args.proposal_id)
            elif args.command == "pause":
                value = runtime.pause(args.reason)
            elif args.command == "resume":
                value = runtime.resume()
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "STOPPED", "cancelled": False, "flattened": False}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__, "reason": str(error)[:240]}))
        return 1


def _shadow_replay(args):
    from hf_space.intraday import make_synthetic_intraday_prices, parse_intraday_csv
    from execution_lab.veighna_bridge import run_shadow_replay
    directory = resolve_runtime_dir(args.runtime_dir)
    if args.source == "moomoo":
        if not args.csv:
            raise ValueError("--source moomoo requires an explicit --csv; no synthetic fallback.")
        path = Path(args.csv)
        if path.stat().st_size > 8*1024*1024:
            raise ValueError("Intraday CSV exceeds 8 MiB.")
        bars = parse_intraday_csv(path.read_bytes(), benchmark=args.benchmark)
        benchmark = args.benchmark
    else:
        if args.csv:
            raise ValueError("Synthetic replay must not label a supplied CSV as generated data.")
        bars = make_synthetic_intraday_prices()
        benchmark = "BENCH"
    value = run_shadow_replay(bars, runtime_dir=directory / "veighna-replay", benchmark=benchmark, source=args.source)
    if args.output:
        output = Path(args.output).resolve()
        if any("dropbox" in part.casefold() for part in output.parts):
            raise ValueError("Execution reports belong in the non-synced runtime directory.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        value = {"status": value["status"], "source": value["source"], "execution_environment": "SHADOW",
                 "orders": len(value["orders"]), "trades": len(value["trades"]), "reconciliation": value["reconciliation"]}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
