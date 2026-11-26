"""Explicit foreground daily-window moomoo snapshot sync; no trading methods.

This is delayed completed-session history, not an intraday quote feed. A normal
invocation collects/prepares once. --publish additionally calls the existing
private-dataset publisher; --watch only loops while this process is running.
No task/service is registered. Process output is captured and never forwarded.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
from io import StringIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CLI_VERSION = "16.40.27608.11182326"
CALENDAR_VERSION = "4.11.2"
VERIFICATION_SOURCE = ("Observed 78 of 78 five-minute OHLC groups matched one-minute right-end aggregates; "
                       "native volume differences retained")
CHECKPOINT = "snapshot-sync.checkpoint.json"
DATASET = "Rexymiao/alpha-trading-snapshots"
NY = ZoneInfo("America/New_York")
COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


class SnapshotSyncError(ValueError):
    """Only fixed non-sensitive codes are emitted to the console."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SnapshotSyncError("TIMEZONE_AWARE_CLOCK_REQUIRED")
    return value.astimezone(timezone.utc)


def _iso(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()


def completed_window(as_of, sessions=3):
    """XNYS sessions strictly before NY today, including half days and DST."""
    if isinstance(sessions, bool) or not isinstance(sessions, int) or not 1 <= sessions <= 10:
        raise SnapshotSyncError("SESSIONS_MUST_BE_ONE_TO_TEN")
    try:
        if version("exchange-calendars") != CALENDAR_VERSION:
            raise SnapshotSyncError("PINNED_CALENDAR_VERSION_REQUIRED")
        import exchange_calendars as xcals
        today = _utc(as_of).astimezone(NY).date()
        calendar = xcals.get_calendar("XNYS", start=str(today-timedelta(days=90)), end=str(today+timedelta(days=3)))
        # The calendar can trim a weekend start to its first valid session;
        # do not query a pre-boundary weekend through sessions_in_range.
        selected = [item for item in calendar.sessions if item.date() < today][-sessions:]
        if len(selected) != sessions:
            raise SnapshotSyncError("CALENDAR_WINDOW_UNAVAILABLE")
        records = [{"date": str(item.date()), "open": _iso(calendar.session_open(item).to_pydatetime()),
                    "close": _iso(calendar.session_close(item).to_pydatetime())} for item in selected]
        return {"sessions": records, "start": records[0]["date"], "end_exclusive": str(today)}
    except SnapshotSyncError:
        raise
    except Exception:
        raise SnapshotSyncError("CALENDAR_WINDOW_UNAVAILABLE") from None


def _run(argv, *, env, timeout):
    return subprocess.run(argv, env=env, timeout=timeout, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _last_document(result, code):
    try:
        raw = result.stdout.encode() if isinstance(result.stdout, str) else result.stdout
        if not raw or len(raw) > 2*1024*1024:
            raise ValueError()
        document = json.loads(raw.decode("utf-8-sig").strip().splitlines()[-1])
        if not isinstance(document, dict):
            raise ValueError()
        return document
    except Exception:
        raise SnapshotSyncError(code) from None


def _inside(path, root):
    try:
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_file() or not resolved.is_relative_to(root.resolve()):
            raise ValueError()
        return resolved
    except (OSError, ValueError, TypeError):
        raise SnapshotSyncError("COLLECTOR_PATH_OUTSIDE_INTRADAY_ROOT") from None


def _atomic_checkpoint(path, value):
    temporary = path.with_name(path.name+"."+uuid4().hex+".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Windows cannot generally fsync a directory handle using os.open;
        # file data is fsynced and replacement is atomic on this local volume.
        if os.name != "nt":
            handle = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class SyncConfig:
    runtime_dir: str | Path
    symbols: tuple[str, ...] = ("SPY", "NVDA")
    sessions: int = 3
    publish: bool = False
    refresh: bool = False


class SnapshotSyncRunner:
    def __init__(self, config, *, runner=None, clock=None, env=None, project_root=None):
        self.config, self.runner = config, runner or _run
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.env = dict(os.environ if env is None else env)
        self.root = Path(project_root or ROOT).resolve()
        raw = Path(config.runtime_dir).expanduser()
        if not raw.is_absolute():
            raise SnapshotSyncError("EXPLICIT_ABSOLUTE_RUNTIME_DIR_REQUIRED")
        self.runtime = raw.resolve()
        if any("dropbox" in part.casefold() for part in (*raw.parts, *self.runtime.parts)):
            raise SnapshotSyncError("NON_DROPBOX_RUNTIME_REQUIRED")
        self.symbols = tuple(sorted(config.symbols))
        if (not 2 <= len(self.symbols) <= 13 or len(set(self.symbols)) != len(self.symbols) or "SPY" not in self.symbols
                or any(not isinstance(item, str) or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", item) for item in self.symbols)):
            raise SnapshotSyncError("SPY_AND_ONE_TO_TWELVE_STOCKS_REQUIRED")
        self.collector = self.root / "scripts" / "collect-moomoo-intraday.mjs"
        self.publisher = self.root / "scripts" / "sync_moomoo_snapshot.py"
        self.publish_python = self.root / "state" / "snapshot-sync-venv" / "Scripts" / "python.exe"
        self.cli = self.env.get("ALPHA_MOOMOO_CLI") or str(Path(self.env.get("APPDATA", "")) / "moomoo" / "2.0" / "OpenAPI" / "moomooapp-cli.exe")
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self.runtime / CHECKPOINT
        if self.checkpoint.is_symlink():
            raise SnapshotSyncError("REGULAR_CHECKPOINT_REQUIRED")

    @contextmanager
    def _lock(self):
        path = self.runtime / "snapshot-sync.lock"
        if path.is_symlink():
            raise SnapshotSyncError("REGULAR_LOCK_REQUIRED")
        with path.open("a+b") as stream:
            try:
                if os.name == "nt":
                    import msvcrt
                    if stream.tell() == 0:
                        stream.write(b"0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, IOError):
                raise SnapshotSyncError("SYNC_ALREADY_RUNNING") from None
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _invoke(self, argv, timeout, code):
        try:
            response = self.runner([str(item) for item in argv], env=self.env, timeout=timeout)
        except Exception:
            raise SnapshotSyncError(code) from None
        if response.returncode:
            raise SnapshotSyncError(code)
        return response

    def _preflight(self):
        # Configuration presence only: protected plaintext is handled solely
        # inside the existing publisher, and never enters this runner's state.
        if self.config.publish:
            configured = bool(self.env.get("ALPHA_SNAPSHOT_WRITE_TOKEN", "").strip())
            protected = self.env.get("ALPHA_SNAPSHOT_TOKEN_DPAPI", "")
            if not configured:
                configured = bool(protected and Path(protected).is_file() and Path(protected).stat().st_size)
            if not configured or not self.publish_python.is_file():
                raise SnapshotSyncError("NOT_CONFIGURED")
        if not self.collector.is_file() or not self.publisher.is_file():
            raise SnapshotSyncError("LOCAL_SOURCE_NOT_CONFIGURED")
        response = self._invoke([self.cli, "--version"], 10, "CLI_VERSION_UNAVAILABLE")
        text = response.stdout.decode("utf-8-sig") if isinstance(response.stdout, bytes) else response.stdout
        if not isinstance(text, str) or text.strip() != "openapi-cli "+CLI_VERSION:
            raise SnapshotSyncError("TIME_LABEL_REVERIFY")
        return _digest(_json({"collector_sha256": _digest(self.collector.read_bytes()), "cli_version": CLI_VERSION,
                              "timestamp_label": "bar-end", "verification_source": VERIFICATION_SOURCE}))

    def _load(self):
        if not self.checkpoint.exists():
            return {"schema_version": 1, "records": []}
        try:
            state = json.loads(self.checkpoint.read_bytes())
            if state.get("schema_version") != 1 or not isinstance(state.get("records"), list):
                raise ValueError()
            return state
        except Exception:
            raise SnapshotSyncError("CHECKPOINT_INVALID") from None

    def _validate_snapshot(self, manifest_path, window):
        root = self.root / "data" / "intraday"
        manifest_path = _inside(manifest_path, root)
        try:
            if manifest_path.stat().st_size > 4*1024*1024:
                raise ValueError()
            manifest = json.loads(manifest_path.read_bytes())
            if manifest.get("status") != "success" or manifest.get("source") != "moomoo":
                raise ValueError()
            if manifest.get("cli_version") != "openapi-cli "+CLI_VERSION:
                raise SnapshotSyncError("TIME_LABEL_REVERIFY")
            csv_path = _inside(manifest_path.parent / manifest["csv"]["path"], root)
            contents = csv_path.read_bytes()
            digest = _digest(contents)
            if len(contents) > 8*1024*1024 or digest != manifest["csv"]["sha256"] or len(contents) != manifest["csv"]["bytes"]:
                raise ValueError()
            reader = csv.DictReader(StringIO(contents.decode("utf-8-sig")))
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise ValueError()
            expected = set()
            for session in window["sessions"]:
                stamp = datetime.fromisoformat(session["open"].replace("Z", "+00:00"))
                closing = datetime.fromisoformat(session["close"].replace("Z", "+00:00"))
                while stamp < closing:
                    expected.update((_iso(stamp), symbol) for symbol in self.symbols)
                    stamp += timedelta(minutes=5)
            observed = set()
            for row in reader:
                stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                key = (_iso(stamp), row["symbol"])
                if key in observed:
                    raise ValueError()
                observed.add(key)
            if observed != expected or len(observed) != manifest["csv"]["rows"]:
                raise SnapshotSyncError("INCOMPLETE_COMPLETED_SESSION_WINDOW")
            as_of = window["sessions"][-1]["close"]
            return manifest_path, csv_path, {"csv_sha256": digest, "rows": len(observed), "as_of": as_of}
        except SnapshotSyncError:
            raise
        except Exception:
            raise SnapshotSyncError("COLLECTOR_SNAPSHOT_INVALID") from None

    def run_once(self):
        with self._lock():
            source_version = self._preflight()
            window = completed_window(self.clock(), self.config.sessions)
            key = _digest(_json({"sessions": window["sessions"], "symbols": self.symbols, "source_version": source_version}))
            state = self._load()
            previous = next((row for row in reversed(state["records"]) if row["key"] == key), None)
            if previous and not self.config.refresh and (not self.config.publish or previous.get("revision")):
                saved_manifest, _, verified = self._validate_snapshot(previous["manifest_path"], window)
                if (any(previous.get(name) != value for name, value in verified.items())
                        or previous.get("manifest_sha256") != _digest(saved_manifest.read_bytes())):
                    raise SnapshotSyncError("CHECKPOINT_SNAPSHOT_MISMATCH")
                return {"status": "ALREADY_SYNCED", "head": previous.get("revision"),
                        **{name: previous[name] for name in ("csv_sha256", "rows", "as_of")}}
            if previous and not self.config.refresh:
                manifest_path = previous["manifest_path"]
            else:
                response = self._invoke(["node", self.collector, "--symbols", ",".join(self.symbols),
                    "--start", window["start"], "--end", window["end_exclusive"], "--rehab-type", "0",
                    "--page-size", "100", "--max-pages", "10", "--timestamp-label", "bar-end",
                    "--verification-source", VERIFICATION_SOURCE], 1800, "COLLECTION_FAILED")
                report = _last_document(response, "COLLECTOR_OUTPUT_INVALID")
                if report.get("status") != "success":
                    raise SnapshotSyncError("COLLECTION_FAILED")
                manifest_path = report.get("manifest")
            manifest_path, csv_path, summary = self._validate_snapshot(manifest_path, window)
            manifest_sha256 = _digest(manifest_path.read_bytes())
            if previous and not self.config.refresh and previous.get("manifest_sha256") != manifest_sha256:
                raise SnapshotSyncError("CHECKPOINT_SNAPSHOT_MISMATCH")
            args = [self.publisher, "--csv", csv_path, "--source-manifest", manifest_path]
            prepared = _last_document(self._invoke([sys.executable, *args], 60, "PREPARATION_FAILED"), "PREPARATION_FAILED")
            if (prepared.get("status") != "prepared_locally" or prepared.get("dataset") != DATASET
                    or prepared.get("csv_sha256") != summary["csv_sha256"]
                    or prepared.get("rows") != summary["rows"] or prepared.get("as_of") != summary["as_of"]):
                raise SnapshotSyncError("PREPARATION_FAILED")
            revision, status = None, "COLLECTED_PREPARED"
            if self.config.publish:
                identical = next((row for row in reversed(state["records"])
                                  if row.get("revision") and row.get("csv_sha256") == summary["csv_sha256"]), None)
                if identical:
                    revision, status = identical["revision"], "UNCHANGED"
                else:
                    published = _last_document(self._invoke([self.publish_python, *args, "--publish"], 120,
                                               "PUBLISH_FAILED_CHECK_REMOTE_BEFORE_RETRY"), "PUBLISH_RESPONSE_UNCONFIRMED")
                    revision = published.get("revision")
                    if (published.get("status") != "private_snapshot_uploaded" or published.get("dataset") != DATASET
                            or published.get("uploaded") is not True
                            or published.get("csv_sha256") != summary["csv_sha256"] or not isinstance(revision, str)
                            or not re.fullmatch("[0-9a-f]{40}", revision)):
                        raise SnapshotSyncError("PUBLISH_RESPONSE_UNCONFIRMED")
                    status = "PUBLISHED"
            record = {"key": key, "source_version": source_version, "window": window, "symbols": self.symbols,
                "manifest_path": str(manifest_path), "manifest_sha256": manifest_sha256, "csv_path": str(csv_path), **summary,
                "revision": revision, "completed_at": _iso(self.clock()), "status": status}
            state["records"].append(record)
            try:
                _atomic_checkpoint(self.checkpoint, state)
            except Exception:
                raise SnapshotSyncError("CHECKPOINT_WRITE_FAILED_CHECK_REMOTE_BEFORE_RETRY" if revision else "CHECKPOINT_WRITE_FAILED") from None
            return {"status": status, "head": revision, **summary}

    def watch(self, *, max_cycles=None, poll_seconds=300, sleeper=time.sleep, emit=print, stop_event=None):
        if (max_cycles is not None and (isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 1)
                or isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or not 1 <= poll_seconds <= 86400):
            raise SnapshotSyncError("INVALID_WATCH_LIMIT")
        cycle, result = 0, None
        while max_cycles is None or cycle < max_cycles:
            if stop_event is not None and stop_event.is_set():
                break
            # Any failure exits the watcher. In particular, an uncertain POST
            # is never retried automatically in this process.
            result = self.run_once()
            emit(json.dumps(result, sort_keys=True))
            cycle += 1
            if max_cycles is not None and cycle >= max_cycles:
                break
            remaining = poll_seconds
            while remaining > 0:
                if stop_event is not None and stop_event.is_set():
                    return result
                delay = min(30, remaining)
                sleeper(delay)
                remaining -= delay
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--symbols", default="SPY,NVDA")
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--poll-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        if args.max_cycles is not None and not args.watch:
            raise SnapshotSyncError("MAX_CYCLES_REQUIRES_WATCH")
        config = SyncConfig(args.runtime_dir, tuple(item.strip().upper() for item in args.symbols.split(",")),
                            args.sessions, args.publish, args.refresh)
        runner = SnapshotSyncRunner(config)
        if args.watch:
            runner.watch(max_cycles=args.max_cycles, poll_seconds=args.poll_seconds)
        else:
            print(json.dumps(runner.run_once(), sort_keys=True))
        return 0
    except Exception as error:
        code = error.code if isinstance(error, SnapshotSyncError) else "SNAPSHOT_SYNC_FAILED"
        print(json.dumps({"status": "NOT_CONFIGURED" if code == "NOT_CONFIGURED" else "FAILED", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
