"""Fictional subprocesses only; never run moomoo or contact Hugging Face."""
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from threading import Event

import pytest

from scripts.run_snapshot_sync import (CHECKPOINT, CLI_VERSION, COLUMNS, DATASET,
    SnapshotSyncError, SnapshotSyncRunner, SyncConfig, completed_window)


NOW = datetime(2026, 11, 26, 16, tzinfo=timezone.utc)
FICTIONAL_TOKEN = "FICTIONAL_TEST_VALUE_NOT_A_REAL_TOKEN"


class Processes:
    def __init__(self, root, *, now=NOW):
        self.root, self.now = root, now
        self.calls = []
        self.version = CLI_VERSION
        self.collections = self.publications = self.preparations = 0
        self.fail_publish = False
        self.outside_manifest = None
        self.remove_last_bar = False
        self.collected_paths = []

    def __call__(self, argv, *, env, timeout):
        self.calls.append(argv)
        assert timeout > 0
        assert not any(word in argv for word in ("get-acc-list", "place-order", "accinfo-query"))
        if argv[-1] == "--version":
            raw = "openapi-cli "+self.version+"\n"
            return subprocess.CompletedProcess(argv, 0, raw.encode(), b"")
        if argv[0] == "node":
            self.collections += 1
            assert Path(argv[1]).name == "collect-moomoo-intraday.mjs"
            assert argv[argv.index("--timestamp-label")+1] == "bar-end"
            assert argv[argv.index("--rehab-type")+1] == "0"
            assert argv[argv.index("--end")+1] == self.now.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
            if self.outside_manifest:
                return subprocess.CompletedProcess(argv, 0, json.dumps({"status":"success", "manifest":str(self.outside_manifest)}).encode(), b"")
            symbols = argv[argv.index("--symbols")+1].split(",")
            start = argv[argv.index("--start")+1]
            all_sessions = completed_window(self.now, 10)["sessions"]
            sessions = [item for item in all_sessions if item["date"] >= start]
            folder = self.root / "data" / "intraday" / ("fictional-test-"+str(self.collections))
            folder.mkdir(parents=True)
            path = folder / "bars.csv"
            rows = []
            for session in sessions:
                stamp = datetime.fromisoformat(session["open"].replace("Z", "+00:00"))
                closing = datetime.fromisoformat(session["close"].replace("Z", "+00:00"))
                while stamp < closing:
                    for symbol in symbols:
                        rows.append([stamp.isoformat().replace("+00:00", "Z"), symbol, 100, 101, 99, 100.5, 123])
                    stamp += timedelta(minutes=5)
            if self.remove_last_bar:
                rows.pop()
            with path.open("w", newline="", encoding="utf8") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(COLUMNS)
                writer.writerows(rows)
            raw = path.read_bytes()
            source = {"status":"success", "source":"moomoo", "read_only":True, "interval":"5m", "session":"RTH",
                "cli_version":"openapi-cli "+CLI_VERSION,
                "csv":{"path":"bars.csv", "bytes":len(raw), "rows":len(rows), "sha256":hashlib.sha256(raw).hexdigest()},
                "normalization":{"provider_timestamp_label":"bar_end", "conversion":"subtract_5_minutes",
                                  "verification_source":"Fictional test evidence only"}}
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps(source), encoding="utf8")
            self.collected_paths.append(manifest)
            return subprocess.CompletedProcess(argv, 0,
                ("fictional progress line\n"+json.dumps({"status":"success", "manifest":str(manifest)})+"\n").encode(), b"")
        assert Path(argv[1]).name == "sync_moomoo_snapshot.py"
        path = Path(argv[argv.index("--csv")+1])
        rows = list(csv.DictReader(path.open(encoding="utf8")))
        end = max(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))+timedelta(minutes=5) for row in rows)
        result = {"status":"prepared_locally", "uploaded":False, "dataset":DATASET,
                  "rows":len(rows), "csv_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                  "as_of":end.isoformat().replace("+00:00", "Z")}
        if "--publish" in argv:
            assert "snapshot-sync-venv" in argv[0]
            self.publications += 1
            if self.fail_publish:
                return subprocess.CompletedProcess(argv, 1, b"", ("do not print "+FICTIONAL_TOKEN).encode())
            result.update(status="private_snapshot_uploaded", uploaded=True, revision="a"*40)
        else:
            self.preparations += 1
        return subprocess.CompletedProcess(argv, 0, json.dumps(result).encode(), b"")


def setup(tmp_path, *, publish=False, now=NOW, env=None, symbols=("SPY", "NVDA"), sessions=3, refresh=False):
    root = tmp_path / "fictional-project"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "collect-moomoo-intraday.mjs").write_text("// fictional test source, not executed\n")
    (root / "scripts" / "sync_moomoo_snapshot.py").write_text("# fictional test source, not executed\n")
    executable = root / "state" / "snapshot-sync-venv" / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"FICTIONAL FILE NEVER EXECUTED")
    config = SyncConfig(tmp_path / "local-runtime", symbols, sessions, publish, refresh)
    fake = Processes(root, now=now)
    obj = SnapshotSyncRunner(config, project_root=root, runner=fake, clock=lambda: fake.now,
                             env={} if env is None else env)
    return obj, fake


def checkpoint(obj):
    return json.loads((obj.runtime / CHECKPOINT).read_text())


def test_completed_window_excludes_current_date_even_after_close_and_handles_holiday_halfday_dst():
    assert [row["date"] for row in completed_window(NOW)["sessions"]] == ["2026-11-23", "2026-11-24", "2026-11-25"]
    # Nov 27 is a half day, and Nov 26 is a holiday. It enters only on Nov 28.
    half = completed_window(datetime(2026, 11, 28, 16, tzinfo=timezone.utc), 2)
    assert [row["date"] for row in half["sessions"]] == ["2026-11-25", "2026-11-27"]
    assert half["sessions"][-1]["close"] == "2026-11-27T18:00:00Z"
    dst = completed_window(datetime(2024, 3, 12, 22, tzinfo=timezone.utc), 2)
    assert [row["open"] for row in dst["sessions"]] == ["2024-03-08T14:30:00Z", "2024-03-11T13:30:00Z"]
    assert completed_window(datetime(2026, 11, 27, 23, tzinfo=timezone.utc), 1)["sessions"][0]["date"] == "2026-11-25"


def test_prepare_default_and_same_completed_window_skip_history_across_holiday(tmp_path):
    obj, fake = setup(tmp_path)
    first = obj.run_once()
    assert first["status"] == "COLLECTED_PREPARED" and first["rows"] == 468
    saved = (obj.runtime / CHECKPOINT).read_bytes()
    fake.now = datetime(2026, 11, 27, 20, tzinfo=timezone.utc)  # closed half day is still NY today
    second = obj.run_once()
    assert second["status"] == "ALREADY_SYNCED"
    assert fake.collections == fake.preparations == 1 and fake.publications == 0
    assert (obj.runtime / CHECKPOINT).read_bytes() == saved


def test_halfday_complete_prefix_is_42_bars_per_symbol(tmp_path):
    obj, _ = setup(tmp_path, now=datetime(2026, 11, 28, 16, tzinfo=timezone.utc), sessions=2)
    result = obj.run_once()
    assert result["rows"] == (78+42)*2 and result["as_of"] == "2026-11-27T18:00:00Z"


@pytest.mark.parametrize("env", [{}, {"ALPHA_SNAPSHOT_WRITE_TOKEN":" "},
                                   {"ALPHA_SNAPSHOT_TOKEN_DPAPI":"missing-fictional-file"}])
def test_no_publishing_token_prevents_even_cli_version_or_history_request(tmp_path, env):
    obj, fake = setup(tmp_path, publish=True, env=env)
    with pytest.raises(SnapshotSyncError, match="NOT_CONFIGURED"):
        obj.run_once()
    assert fake.calls == [] and not obj.checkpoint.exists()


def test_cli_version_change_requires_time_label_reverification_before_collection(tmp_path):
    obj, fake = setup(tmp_path)
    fake.version = "99.1.2.3"
    with pytest.raises(SnapshotSyncError, match="TIME_LABEL_REVERIFY"):
        obj.run_once()
    assert fake.collections == fake.publications == 0 and not obj.checkpoint.exists()


def test_prepared_snapshot_can_later_publish_without_collecting_again_and_deduplicates(tmp_path):
    obj, fake = setup(tmp_path)
    obj.run_once()
    published = SnapshotSyncRunner(SyncConfig(obj.runtime, publish=True), project_root=obj.root, runner=fake,
        clock=lambda: fake.now, env={"ALPHA_SNAPSHOT_WRITE_TOKEN":FICTIONAL_TOKEN})
    result = published.run_once()
    assert result["status"] == "PUBLISHED" and result["head"] == "a"*40
    assert fake.collections == fake.publications == 1
    assert published.run_once()["status"] == "ALREADY_SYNCED" and fake.publications == 1
    assert FICTIONAL_TOKEN not in published.checkpoint.read_text()


def test_refresh_preserves_old_snapshot_and_identical_payload_does_not_post_twice(tmp_path):
    obj, fake = setup(tmp_path, publish=True, env={"ALPHA_SNAPSHOT_WRITE_TOKEN":FICTIONAL_TOKEN})
    obj.run_once()
    original = fake.collected_paths[0].read_bytes()
    refreshed = SnapshotSyncRunner(SyncConfig(obj.runtime, publish=True, refresh=True), project_root=obj.root,
        runner=fake, clock=lambda: fake.now, env={"ALPHA_SNAPSHOT_WRITE_TOKEN":FICTIONAL_TOKEN})
    assert refreshed.run_once()["status"] == "UNCHANGED"
    assert fake.collections == 2 and fake.publications == 1
    assert fake.collected_paths[0].read_bytes() == original and len(checkpoint(obj)["records"]) == 2


def test_publish_failure_does_not_checkpoint_and_watch_never_retries_post(tmp_path):
    obj, fake = setup(tmp_path, publish=True, env={"ALPHA_SNAPSHOT_WRITE_TOKEN":FICTIONAL_TOKEN})
    fake.fail_publish = True
    slept, emitted = [], []
    with pytest.raises(SnapshotSyncError, match="PUBLISH_FAILED_CHECK_REMOTE_BEFORE_RETRY"):
        obj.watch(max_cycles=3, sleeper=slept.append, emit=emitted.append)
    assert fake.publications == 1 and slept == emitted == [] and not obj.checkpoint.exists()


def test_failed_refresh_keeps_previous_checkpoint_bytes(tmp_path):
    obj, fake = setup(tmp_path)
    obj.run_once()
    saved = obj.checkpoint.read_bytes()
    fake.remove_last_bar = True
    refreshed = SnapshotSyncRunner(SyncConfig(obj.runtime, refresh=True), project_root=obj.root,
        runner=fake, clock=lambda: fake.now, env={})
    with pytest.raises(SnapshotSyncError, match="INCOMPLETE_COMPLETED_SESSION_WINDOW"):
        refreshed.run_once()
    assert obj.checkpoint.read_bytes() == saved


def test_collector_output_manifest_path_cannot_escape_project_intraday_root(tmp_path):
    obj, fake = setup(tmp_path)
    fake.outside_manifest = tmp_path / "outside.json"
    fake.outside_manifest.write_text("{}")
    with pytest.raises(SnapshotSyncError, match="COLLECTOR_PATH_OUTSIDE_INTRADAY_ROOT"):
        obj.run_once()
    assert fake.preparations == 0 and not obj.checkpoint.exists()


def test_watch_is_explicit_bounded_and_sleeps_in_at_most_thirty_second_blocks(tmp_path):
    obj, fake = setup(tmp_path)
    slept, emitted = [], []
    obj.watch(max_cycles=2, poll_seconds=65, sleeper=slept.append, emit=emitted.append)
    assert slept == [30, 30, 5] and len(emitted) == 2 and fake.collections == 1
    assert all(set(json.loads(line)) <= {"status", "head", "csv_sha256", "rows", "as_of"} for line in emitted)
    assert FICTIONAL_TOKEN not in "".join(emitted)
    stopped = Event()
    stopped.set()
    assert obj.watch(max_cycles=1, stop_event=stopped) is None


@pytest.mark.parametrize("path", ["relative", "Dropbox/local-runtime"])
def test_runtime_requires_explicit_non_dropbox_location(tmp_path, path):
    raw = Path(path) if path == "relative" else tmp_path / path
    with pytest.raises(SnapshotSyncError, match="ABSOLUTE|NON_DROPBOX"):
        SnapshotSyncRunner(SyncConfig(raw))


def test_checkpoint_local_hash_is_verified_before_deduplicated_success(tmp_path):
    obj, fake = setup(tmp_path)
    obj.run_once()
    csv_path = fake.collected_paths[0].parent / "bars.csv"
    csv_path.write_bytes(csv_path.read_bytes()+b"corrupt")
    with pytest.raises(SnapshotSyncError, match="COLLECTOR_SNAPSHOT_INVALID"):
        obj.run_once()
    assert fake.collections == 1


def test_modified_source_manifest_cannot_be_silently_accepted_on_checkpoint_hit(tmp_path):
    obj, fake = setup(tmp_path)
    obj.run_once()
    manifest = fake.collected_paths[0]
    source = json.loads(manifest.read_bytes())
    source["normalization"]["verification_source"] = "Changed fictional evidence"
    manifest.write_text(json.dumps(source))
    with pytest.raises(SnapshotSyncError, match="CHECKPOINT_SNAPSHOT_MISMATCH"):
        obj.run_once()
    assert fake.collections == 1


def test_collector_source_digest_is_part_of_window_key(tmp_path):
    obj, fake = setup(tmp_path)
    obj.run_once()
    obj.collector.write_text("// changed fictional parser source, never executed\n")
    assert obj.run_once()["status"] == "COLLECTED_PREPARED"
    assert fake.collections == 2 and len(checkpoint(obj)["records"]) == 2


def test_one_to_twelve_stocks_plus_spy_contract_has_thirteen_total_symbols(tmp_path):
    symbols = tuple(["SPY"]+["T"+str(index) for index in range(12)])
    obj, fake = setup(tmp_path, symbols=symbols)
    assert obj.run_once()["rows"] == 78*3*13 and fake.collections == 1
