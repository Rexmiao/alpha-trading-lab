"""Normalize the existing hashed moomoo daily snapshot for private publication.

No collection, authentication, networking, model training or account access.
Outputs stay in the ignored data/daily directory; source audit stays local.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def prepare():
    from research.data import load_snapshot
    from hf_space.daily_snapshot_source import parse_daily_csv

    prices, collected, quality = load_snapshot(ROOT)
    if collected.get("source") != "moomoo" or collected.get("read_only") is not True or collected.get("errors"):
        raise ValueError("DAILY_COLLECTION_NOT_COMPLETE")
    if collected.get("rehab_type") != 1:
        raise ValueError("DAILY_FORWARD_ADJUSTMENT_REQUIRED")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if config.get("benchmark") != "SPY":
        raise ValueError("DAILY_SPY_BENCHMARK_REQUIRED")
    expected = set(config["universe"]) | {"SPY"}
    if set(prices.symbol.unique()) != expected:
        raise ValueError("DAILY_COLLECTION_SYMBOLS_INCOMPLETE")
    normalized = prices.loc[:, ["date", "symbol", "open", "high", "low", "close", "volume"]].copy()
    normalized["date"] = normalized.date.dt.strftime("%Y-%m-%d")
    normalized = normalized.sort_values(["date", "symbol"], kind="stable")
    raw = normalized.to_csv(index=False, lineterminator="\n").encode("utf-8")
    now = datetime.now(timezone.utc)
    parsed = parse_daily_csv(raw, now=now)
    if len(parsed) != len(normalized):
        raise ValueError("DAILY_PARSER_ROW_COUNT_CHANGED")
    digest = hashlib.sha256(raw).hexdigest()
    source_manifest = {
        "source": "moomoo", "status": "success", "interval": "1d", "session": "provider_daily",
        "read_only": True, "benchmark": "SPY", "date_convention": "exchange_session_date",
        "price_basis": "moomoo_forward_adjusted_ohlcv", "rehab_type": 1,
        "collected_at": collected["collected_at"],
        "csv": {"sha256": digest, "bytes": len(raw), "rows": len(normalized)},
        "normalization": {"completed_session_verified": True, "calendar": "XNYS",
            "boundary_policy": "configured_symbol_start_dates_applied",
            "symbol_start_dates": {name: day for name, day in config.get("symbol_start_dates", {}).items()
                                   if name in expected}},
        "source_audit": {"manifest_sha256": hashlib.sha256((ROOT / "data/manifest.json").read_bytes()).hexdigest(),
                         "source_files_count": len(collected["files"])},
    }
    parent = ROOT / "data" / "daily"
    if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
        raise ValueError("DAILY_OUTPUT_LINK_REFUSED")
    folder = parent / (now.strftime("%Y%m%dT%H%M%SZ") + "_" + digest[:12])
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "bars.csv").write_bytes(raw)
    (folder / "source-manifest.json").write_text(json.dumps(source_manifest, ensure_ascii=False,
        allow_nan=False, indent=2) + "\n", encoding="utf-8")
    (folder / "source-audit-private.json").write_text(json.dumps({"quality": quality,
        "collector_manifest": collected, "normalized_csv_sha256": digest}, ensure_ascii=False,
        allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "csv": (folder / "bars.csv").relative_to(ROOT).as_posix(),
        "source_manifest": (folder / "source-manifest.json").relative_to(ROOT).as_posix(),
        "sha256": digest, "bytes": len(raw), "rows": len(normalized), "symbols": len(expected),
        "start": normalized.date.min(), "end": normalized.date.max(),
        "large_moves_flagged_not_repaired": len(quality["large_daily_moves_to_review"]),
        "published": False}


if __name__ == "__main__":
    try:
        print(json.dumps(prepare(), ensure_ascii=False, allow_nan=False, indent=2))
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__,
                          "reason": "Daily preparation failed; no publication was performed."}))
        raise SystemExit(1)
