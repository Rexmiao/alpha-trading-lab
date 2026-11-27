"""Export an explicitly allowlisted public derived reference from a frozen run.

No network or broker access. The input minute data remains local. Only ratios,
quality flags, dates, dimensionless opening statistics and safe hashes leave it.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hf_space.premarket import DEFINITIONS, SCHEMA, SYMBOLS, validate_reference

DEFAULT_REPORT = ROOT / "state/premarket-365/20261127T200955569265Z"
OUTPUT = ROOT / "hf_space/assets/premarket_reference_365.json"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def leaf(folder, name):
    if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("source_leaf_required")
    path = (folder / name).resolve()
    if path.parent != folder:
        raise ValueError("source_outside_folder")
    return path


def build_reference(folder: Path) -> dict:
    folder = folder.resolve()
    if not folder.is_relative_to(ROOT / "state/premarket-365"):
        raise ValueError("frozen_report_scope")
    hashes = json.loads((folder / "artifact-hashes.json").read_bytes())
    if len(hashes) != 10:
        raise ValueError("expected_frozen_artifacts")
    for name, record in hashes.items():
        raw = leaf(folder, name).read_bytes()
        if digest(raw) != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("frozen_artifact_hash_or_length")
    raw_report = (folder / "report.json").read_bytes()
    report = json.loads(raw_report)
    for key, filename in (("engine_sha256", "engine-used.py"), ("runner_sha256", "runner-used.py")):
        if digest((folder / filename).read_bytes()) != report["code"][key]:
            raise ValueError("frozen_code_binding")
    config = report["config"]
    if (config["symbols"] != list(SYMBOLS) or config["start"] != "2025-11-27"
            or config["end_exclusive"] != "2026-11-27" or config["bar_label"] != "end"
            or config["price_adjustment"] != "raw_unadjusted" or config["execution_eligible"] is not False):
        raise ValueError("frozen_report_config")
    page_hashes, checkpoint_hashes = [], []
    total_rows = 0
    for capture in report["source"]["captures"]:
        source = Path(capture["capture_folder"]).resolve()
        if not source.is_relative_to(ROOT / "data/premarket-history"):
            raise ValueError("capture_scope")
        checkpoint = leaf((source / "progress").resolve(), capture["manifest_checkpoint"])
        if digest(checkpoint.read_bytes()) != capture["manifest_sha256"]:
            raise ValueError("source_checkpoint_binding")
        checkpoint_hashes.append(capture["manifest_sha256"])
        for page in capture["verification"]["pages"]:
            raw = leaf(source, page["file"]).read_bytes()
            if digest(raw) != page["sha256"] or len(raw) != page["bytes"]:
                raise ValueError("source_page_hash_or_length")
            page_hashes.append(page["sha256"])
            total_rows += page["rows"]
    reference = {"schema_version": SCHEMA, "reference_id": "moomoo-opening-365-2026-11-27-v1",
      "provenance": {"source": "moomoo_desktop_history", "start": config["start"], "end_exclusive": config["end_exclusive"],
        "natural_days": 365, "trading_sessions": 250, "timezone": "America/New_York", "bar_label": "end",
        "price_adjustment": "raw_unadjusted", "created_at_utc": report["created_at"],
        "report_sha256": digest(raw_report), "engine_sha256": report["code"]["engine_sha256"],
        "runner_sha256": report["code"]["runner_sha256"],
        "calendar_sha256": report["source"]["verification"]["calendar"]["sha256"],
        "checkpoint_sha256": checkpoint_hashes,
        "source_page_hashes_sha256": digest("\n".join(page_hashes).encode()),
        "source_pages": len(page_hashes), "source_rows": total_rows,
        "raw_minute_data_included": False, "historical_delivery_clocks_verified": False,
        "corporate_actions_audited": False, "publication_profile": "dimensionless_daily_statistics_only"},
      "symbols": {}}
    for symbol in SYMBOLS:
        reference["symbols"][symbol] = [{"date": d["date"], "base_eligible": d["base_eligible"],
          "first30_complete": d["quality"]["first30"]["complete"], "full_rth_complete": d["quality"]["full_rth"]["complete"],
          "previous_close_valid": d["quality"]["previous_close_valid"],
          "outcome": None if d["outcome"] is None else {
            "max_drop_ratio": d["outcome"]["exact_max_drop"], "return_30m_ratio": d["outcome"]["exact_return_30m"],
            "windows": [{k: w[k] for k in ("minutes", "max_drop_from_open", "return_at_window_end")} for w in d["outcome"]["windows"]]},
          "definitions": {name: {"eligible": d["definitions"][name]["analysis_eligible"],
            "condition_known": d["definitions"][name]["condition_known"],
            "window_complete": d["definitions"][name]["quality"]["complete"],
            "return_ratio": d["definitions"][name]["exact_premarket_return"]} for name in DEFINITIONS}}
          for d in report["results"][symbol]["daily"]]
    return validate_reference(reference)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    reference = build_reference(args.report)
    raw = (json.dumps(reference, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_bytes(raw)
    print(json.dumps({"file": "hf_space/assets/premarket_reference_365.json", "bytes": len(raw), "sha256": digest(raw),
                      "days": {s: len(v) for s, v in reference["symbols"].items()}, "raw_minute_data_included": False}))


if __name__ == "__main__":
    main()
