"""Offline private daily publication and payload boundary checks."""
from types import SimpleNamespace
import hashlib
import json

import pandas as pd
import pytest

from scripts.sync_moomoo_daily_snapshot import DATASET, SnapshotPublishError, build_payloads, publish_payloads


NOW = pd.Timestamp("2026-11-26T12:00:00Z")
CSV = (b"date,symbol,open,high,low,close,volume\n"
       b"2026-11-24,SPY,100,103,99,102,1000\n"
       b"2026-11-24,NVDA,50,53,49,52,2000\n")


def provenance(contents=CSV):
    return {"source": "moomoo", "status": "success", "interval": "1d", "session": "provider_daily",
        "read_only": True, "benchmark": "SPY", "date_convention": "exchange_session_date",
        "price_basis": "moomoo_forward_adjusted_ohlcv", "rehab_type": 1,
        "collected_at": "2026-11-25T22:00:00Z",
        "csv": {"sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents), "rows": 2},
        "normalization": {"completed_session_verified": True, "calendar": "XNYS",
            "boundary_policy": "configured_symbol_start_dates_applied", "symbol_start_dates": {}},
        "source_audit": {"manifest_sha256": "1" * 64, "source_files_count": 2},
        "account": "DO_NOT_UPLOAD", "local_path": "DO_NOT_UPLOAD", "token": "DO_NOT_UPLOAD"}


def test_exact_three_daily_files_and_sanitized_manifest():
    payloads, manifest = build_payloads(CSV, provenance(), now=NOW)
    digest = hashlib.sha256(CSV).hexdigest()
    assert set(payloads) == {"daily/latest.json", f"daily/snapshots/{digest}/bars.csv", f"daily/snapshots/{digest}/manifest.json"}
    assert manifest["session"] == "provider_daily" and manifest["as_of"] == "2026-11-24T21:00:00Z"
    assert all(b"DO_NOT_UPLOAD" not in raw for raw in payloads.values())
    assert manifest["source_audit"] == {"manifest_sha256": "1" * 64, "source_files_count": 2}


@pytest.mark.parametrize("change", [{"read_only": False}, {"rehab_type": True}, {"source": "yahoo"},
    {"session": "RTH"}, {"collected_at": "2027-01-01T00:00:00Z"},
    {"normalization": {"completed_session_verified": False}},
    {"csv": {"sha256": "0" * 64, "bytes": len(CSV), "rows": 2}},
    {"source_audit": {"manifest_sha256": "PRIVATE_PATH", "source_files_count": 2}}])
def test_failed_or_unverified_source_never_builds_publishable_payloads(change):
    source = provenance()
    source.update(change)
    with pytest.raises(SnapshotPublishError):
        build_payloads(CSV, source, now=NOW)


def test_current_symbol_identity_requires_exact_known_start_date_and_rejects_old_history():
    contents = CSV.replace(b"NVDA", b"SNDK")
    source = provenance(contents)
    with pytest.raises(SnapshotPublishError):
        build_payloads(contents, source, now=NOW)
    source["normalization"]["symbol_start_dates"] = {"SNDK": "2025-02-24"}
    assert build_payloads(contents, source, now=NOW)[1]["symbols"] == ["SNDK", "SPY"]
    old = contents.replace(b"2026-11-24", b"2024-11-26")
    source = provenance(old)
    source["normalization"]["symbol_start_dates"] = {"SNDK": "2025-02-24"}
    with pytest.raises(SnapshotPublishError):
        build_payloads(old, source, now=NOW)


class API:
    def __init__(self, private=True):
        self.private, self.commits, self.existing, self.reads = private, [], [], []

    def repo_info(self, **kwargs):
        self.reads.append(kwargs)
        assert kwargs == {"repo_id": DATASET, "repo_type": "dataset", "revision": "main"}
        return SimpleNamespace(id=DATASET, private=self.private, sha="a" * 40)

    def list_repo_files(self, **kwargs):
        assert kwargs["revision"] == "a" * 40
        return self.existing

    def create_commit(self, **kwargs):
        self.commits.append(kwargs)
        return SimpleNamespace(oid="b" * 40)


def test_atomic_three_file_parent_guard_and_intraday_pointer_untouched():
    payloads, manifest = build_payloads(CSV, provenance(), now=NOW)
    api = API()
    api.existing = ["latest.json", "snapshots/" + "c" * 64 + "/bars.csv"]
    assert publish_payloads(payloads, api=api, operation_factory=lambda **x: x) == "b" * 40
    commit = api.commits[0]
    assert commit["parent_commit"] == "a" * 40
    assert {entry["path_in_repo"] for entry in commit["operations"]} == set(payloads)
    assert all(entry["path_in_repo"].startswith("daily/") for entry in commit["operations"])
    api.existing.append(manifest["csv"]["path"])
    with pytest.raises(SnapshotPublishError, match="NO_OVERWRITE"):
        publish_payloads(payloads, api=api, operation_factory=lambda **x: x)
    assert len(api.commits) == 1


def test_public_target_is_refused_before_mutation():
    payloads, _ = build_payloads(CSV, provenance(), now=NOW)
    api = API(False)
    with pytest.raises(SnapshotPublishError, match="PRIVATE_DATASET"):
        publish_payloads(payloads, api=api, operation_factory=lambda **x: x)
    assert not api.commits


@pytest.mark.parametrize("mutation", ["extra_file", "extra_private_manifest_field", "csv_tamper", "pointer_escape", "future_created", "malformed_csv_metadata"])
def test_publish_entry_revalidates_allowlist_before_even_reading_hub(mutation):
    payloads, manifest = build_payloads(CSV, provenance(), now=NOW)
    if mutation == "extra_file":
        payloads["credentials.txt"] = b"PRIVATE"
    elif mutation == "extra_private_manifest_field":
        changed = dict(manifest, local_path="PRIVATE")
        payloads[manifest["csv"]["path"].replace("bars.csv", "manifest.json")] = json.dumps(changed).encode()
    elif mutation == "csv_tamper":
        payloads[manifest["csv"]["path"]] = CSV.replace(b"NVDA", b"AMD ")
    elif mutation in {"future_created", "malformed_csv_metadata"}:
        changed = dict(manifest)
        changed["created_at" if mutation == "future_created" else "csv"] = "2099-01-01T00:00:00Z" if mutation == "future_created" else "PRIVATE"
        payloads[manifest["csv"]["path"].replace("bars.csv", "manifest.json")] = json.dumps(changed).encode()
    else:
        pointer = json.loads(payloads["daily/latest.json"])
        pointer["csv_path"] = "../bars.csv"
        payloads["daily/latest.json"] = json.dumps(pointer).encode()
    api = API()
    with pytest.raises(SnapshotPublishError):
        publish_payloads(payloads, api=api, operation_factory=lambda **x: x)
    assert not api.reads and not api.commits
