"""Publish only a prepared moomoo daily research snapshot to a private Dataset.

Default mode validates locally, without reading tokens or contacting a service.
--publish is an explicit operator action; no background task is installed here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hf_space.daily_snapshot_source import (BOUNDARY_POLICY, DATASET_ID, DATE_CONVENTION,
    MAX_ROWS, MAX_UPLOAD_BYTES, PRICE_BASIS, SESSION, DailySnapshotError, daily_calendar,
    parse_daily_csv, validate_normalization, _instant, _iso, _now)
from scripts.sync_moomoo_snapshot import SnapshotPublishError, _write_token


DATASET = DATASET_ID
MAX_BYTES = MAX_UPLOAD_BYTES


def build_payloads(contents, source_manifest, *, now=None):
    """Return exactly CSV, sanitized manifest and daily/latest.json payloads."""
    stamp = _now(now)
    expected = {"source": "moomoo", "status": "success", "interval": "1d", "session": SESSION,
        "read_only": True, "benchmark": "SPY", "date_convention": DATE_CONVENTION,
        "price_basis": PRICE_BASIS, "rehab_type": 1}
    if (not isinstance(source_manifest, dict) or any(source_manifest.get(key) != value
            or isinstance(value, (int, bool)) and type(source_manifest.get(key)) is not type(value)
            for key, value in expected.items())):
        raise SnapshotPublishError("DAILY_MOOMOO_PROVENANCE_REQUIRED")
    if not isinstance(contents, bytes) or not 0 < len(contents) <= MAX_BYTES:
        raise SnapshotPublishError("DAILY_CSV_SIZE_INVALID")
    digest = hashlib.sha256(contents).hexdigest()
    supplied = source_manifest.get("csv")
    if (not isinstance(supplied, dict) or supplied.get("sha256") != digest
            or type(supplied.get("bytes")) is not int or supplied["bytes"] != len(contents)):
        raise SnapshotPublishError("DAILY_SOURCE_CSV_HASH_MISMATCH")
    try:
        prices = parse_daily_csv(contents, now=stamp)
        symbols = sorted(prices.symbol.unique())
        normalization = validate_normalization(source_manifest.get("normalization"), symbols)
        parse_daily_csv(contents, now=stamp, start_dates=normalization["symbol_start_dates"])
        collected = _instant(source_manifest.get("collected_at"))
        last_date = prices.date.max()
        as_of = daily_calendar(prices).session_close(last_date)
        if as_of > collected or collected > stamp:
            raise DailySnapshotError("Invalid daily collection time.")
    except (DailySnapshotError, ValueError, TypeError):
        raise SnapshotPublishError("DAILY_PRICE_OR_PROVENANCE_VALIDATION_FAILED") from None
    if type(supplied.get("rows")) is not int or supplied["rows"] != len(prices):
        raise SnapshotPublishError("DAILY_SOURCE_ROW_COUNT_MISMATCH")
    folder = "daily/snapshots/" + digest
    csv_path, manifest_path = folder + "/bars.csv", folder + "/manifest.json"
    manifest = {"schema_version": 1, "source": "moomoo", "frequency": "1d", "session": SESSION,
        "benchmark": "SPY", "date_convention": DATE_CONVENTION, "price_basis": PRICE_BASIS,
        "rehab_type": 1, "created_at": _iso(stamp), "collected_at": _iso(collected), "as_of": _iso(as_of),
        "first_session": str(prices.date.min().date()), "last_session": str(last_date.date()),
        "session_count": int(prices.date.nunique()), "symbols": symbols, "normalization": normalization,
        "csv": {"path": csv_path, "sha256": digest, "bytes": len(contents), "rows": len(prices)}}
    audit = source_manifest.get("source_audit")
    if audit is not None:
        if (not isinstance(audit, dict) or not isinstance(audit.get("manifest_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", audit["manifest_sha256"])
                or type(audit.get("source_files_count")) is not int or not 1 <= audit["source_files_count"] <= 61):
            raise SnapshotPublishError("DAILY_SOURCE_AUDIT_INVALID")
        manifest["source_audit"] = {"manifest_sha256": audit["manifest_sha256"],
            "source_files_count": audit["source_files_count"]}
    latest = {"schema_version": 1, "snapshot_id": digest, "csv_path": csv_path, "manifest_path": manifest_path}
    def encode(value):
        return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    return {csv_path: contents, manifest_path: encode(manifest), "daily/latest.json": encode(latest)}, manifest


def publish_payloads(payloads, *, api, operation_factory):
    """Only three fixed daily paths, private identity and expected-parent commit."""
    try:
        if not isinstance(payloads, dict) or len(payloads) != 3:
            raise ValueError
        latest = json.loads(payloads["daily/latest.json"])
        digest = latest["snapshot_id"]
        folder = "daily/snapshots/" + digest
        csv_path, manifest_path = folder + "/bars.csv", folder + "/manifest.json"
        if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or set(payloads) != {csv_path, manifest_path, "daily/latest.json"}
                or latest != {"schema_version": 1, "snapshot_id": digest, "csv_path": csv_path, "manifest_path": manifest_path}
                or hashlib.sha256(payloads[csv_path]).hexdigest() != digest):
            raise ValueError
        manifest = json.loads(payloads[manifest_path])
        csv = manifest["csv"]
        if (not isinstance(csv, dict) or csv.get("path") != csv_path or csv.get("sha256") != digest
                or csv.get("bytes") != len(payloads[csv_path]) or len(payloads[manifest_path]) > 128 * 1024):
            raise ValueError
        if _instant(manifest["created_at"]) > _now():
            raise ValueError
        # Rebuild the output allowlist instead of trusting caller-supplied extra
        # metadata, which could otherwise become a secret exfiltration route.
        reconstruction = {"source": manifest["source"], "status": "success", "interval": manifest["frequency"],
            "session": manifest["session"], "read_only": True, "benchmark": manifest["benchmark"],
            "date_convention": manifest["date_convention"], "price_basis": manifest["price_basis"],
            "rehab_type": manifest["rehab_type"], "collected_at": manifest["collected_at"],
            "normalization": manifest["normalization"], "csv": csv}
        if "source_audit" in manifest:
            reconstruction["source_audit"] = manifest["source_audit"]
        rebuilt, _ = build_payloads(payloads[csv_path], reconstruction, now=_instant(manifest["created_at"]))
        if payloads != rebuilt:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise SnapshotPublishError("DAILY_PAYLOAD_ALLOWLIST_OR_HASH_FAILED") from None
    info = api.repo_info(repo_id=DATASET, repo_type="dataset", revision="main")
    if getattr(info, "id", None) != DATASET or getattr(info, "private", None) is not True:
        raise SnapshotPublishError("TARGET_MUST_BE_THE_CONFIGURED_PRIVATE_DATASET")
    head = getattr(info, "sha", None)
    if not isinstance(head, str) or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise SnapshotPublishError("DATASET_REVISION_UNAVAILABLE")
    existing = api.list_repo_files(repo_id=DATASET, repo_type="dataset", revision=head)
    if csv_path in existing or manifest_path in existing:
        raise SnapshotPublishError("SNAPSHOT_ALREADY_EXISTS_NO_OVERWRITE")
    operations = [operation_factory(path_in_repo=path, path_or_fileobj=raw) for path, raw in sorted(payloads.items())]
    commit = api.create_commit(repo_id=DATASET, repo_type="dataset", revision="main", parent_commit=head,
        operations=operations, commit_message="Publish completed moomoo daily research snapshot")
    oid = getattr(commit, "oid", None)
    if not isinstance(oid, str) or not re.fullmatch(r"[a-f0-9]{40}", oid):
        raise SnapshotPublishError("UPLOAD_RESPONSE_UNCONFIRMED_CHECK_REMOTE_BEFORE_RETRY")
    return oid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.csv.stat().st_size > MAX_BYTES or args.source_manifest.stat().st_size > 1024 * 1024:
            raise SnapshotPublishError("DAILY_INPUT_FILE_TOO_LARGE")
        source = json.loads(args.source_manifest.read_text(encoding="utf-8-sig"))
        payloads, manifest = build_payloads(args.csv.read_bytes(), source)
        report = {"status": "daily_prepared_locally", "uploaded": False, "dataset": DATASET,
            "csv_sha256": manifest["csv"]["sha256"], "rows": manifest["csv"]["rows"],
            "as_of": manifest["as_of"], "files": sorted(payloads)}
        if args.publish:
            token = _write_token()
            try:
                from huggingface_hub import HfApi, CommitOperationAdd
            except ImportError:
                raise SnapshotPublishError("INSTALL_REQUIREMENTS_SNAPSHOT_TXT") from None
            api = HfApi(endpoint="https://huggingface.co", token=token)
            oid = publish_payloads(payloads, api=api, operation_factory=CommitOperationAdd)
            report.update(status="private_daily_snapshot_uploaded", uploaded=True, revision=oid)
        print(json.dumps(report, ensure_ascii=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, SnapshotPublishError) else "DAILY_PREPARATION_OR_UPLOAD_FAILED"
        print(json.dumps({"status": "failed", "uploaded": None if args.publish else False, "code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
