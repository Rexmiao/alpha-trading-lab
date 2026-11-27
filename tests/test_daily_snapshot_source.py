"""Offline daily private input tests; these fixtures are not broker observations."""
from io import BytesIO
import hashlib
import json
from urllib.error import HTTPError

import pandas as pd
import pytest

from hf_space.daily_snapshot_source import (DATASET_ID, DailySnapshotError,
    fetch_moomoo_daily_snapshot, parse_daily_csv)
from scripts.sync_moomoo_daily_snapshot import build_payloads


NOW = pd.Timestamp("2026-11-26T12:00:00Z")
TOKEN = "offline_dataset_read_fixture"
REVISION = "a" * 40


def daily_csv():
    return ("date,symbol,open,high,low,close,volume\n"
            "2026-11-23,SPY,100,103,99,102,1000\n"
            "2026-11-23,NVDA,50,53,49,52,2000\n"
            "2026-11-24,SPY,102,104,101,103,1500\n"
            "2026-11-24,NVDA,52,54,51,53,2400\n").encode()


def source_manifest(contents=None):
    contents = daily_csv() if contents is None else contents
    return {"source": "moomoo", "status": "success", "interval": "1d", "session": "provider_daily",
        "read_only": True, "benchmark": "SPY", "date_convention": "exchange_session_date",
        "price_basis": "moomoo_forward_adjusted_ohlcv", "rehab_type": 1,
        "collected_at": "2026-11-25T22:00:00Z",
        "csv": {"sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents),
                "rows": contents.count(b"\n") - 1},
        "normalization": {"completed_session_verified": True, "calendar": "XNYS",
            "boundary_policy": "configured_symbol_start_dates_applied", "symbol_start_dates": {}}}


class Response(BytesIO):
    def __init__(self, value, url):
        super().__init__(value)
        self.url, self.headers, self.status = url, {}, 200

    def geturl(self):
        return self.url


class Hub:
    def __init__(self, contents=None):
        contents = daily_csv() if contents is None else contents
        self.payloads, self.manifest = build_payloads(contents, source_manifest(contents), now=NOW)
        self.latest = json.loads(self.payloads["daily/latest.json"])
        self.info = {"id": DATASET_ID, "private": True, "sha": REVISION}
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        assert request.get_header("Authorization") == "Bearer " + TOKEN
        assert 0 < timeout <= 15
        if "/api/datasets/" in request.full_url:
            value = json.dumps(self.info).encode()
        elif request.full_url.endswith("/daily/latest.json"):
            value = json.dumps(self.latest).encode()
        elif request.full_url.endswith("/manifest.json"):
            value = json.dumps(self.manifest).encode()
        else:
            value = self.payloads[self.latest["csv_path"]]
        return Response(value, request.full_url)


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("ALPHA_SNAPSHOT_DATASET", DATASET_ID)
    monkeypatch.setenv("ALPHA_SNAPSHOT_READ_TOKEN", TOKEN)
    return Hub()


def test_daily_private_revision_hash_and_sanitized_provenance(hub):
    hub.manifest["private_note"] = "LOCAL_ACCOUNT_SECRET_MUST_STAY_PRIVATE"
    prices, provenance = fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert len(prices) == 4 and set(prices.symbol) == {"NVDA", "SPY"}
    assert provenance["source"] == "moomoo_daily_snapshot"
    assert provenance["private_verified"] is True and provenance["revision"] == REVISION
    assert provenance["session"] == "provider_daily"
    assert provenance["price_basis"] == "moomoo_forward_adjusted_ohlcv"
    assert provenance["as_of"] == "2026-11-24T21:00:00Z"
    assert provenance["raw_download_available"] is False
    assert len(hub.requests) == 4
    assert all(f"/resolve/{REVISION}/daily/" in request.full_url for request in hub.requests[1:])
    encoded = json.dumps(provenance)
    assert TOKEN not in encoded and "LOCAL_ACCOUNT" not in encoded and "open" not in provenance


@pytest.mark.parametrize("name", ["ALPHA_SNAPSHOT_DATASET", "ALPHA_SNAPSHOT_READ_TOKEN"])
def test_missing_config_never_reuses_deployment_token(hub, monkeypatch, name):
    monkeypatch.delenv(name)
    monkeypatch.setenv("HF_TOKEN", "DEPLOYMENT_TOKEN_NOT_A_DATASET_CREDENTIAL")
    with pytest.raises(DailySnapshotError) as result:
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert result.value.code == "NOT_CONFIGURED" and not hub.requests


@pytest.mark.parametrize("dataset", ["Other/private", DATASET_ID + "/../secret", "http://127.0.0.1:22222"])
def test_fixed_dataset_not_arbitrary_url(hub, monkeypatch, dataset):
    monkeypatch.setenv("ALPHA_SNAPSHOT_DATASET", dataset)
    with pytest.raises(DailySnapshotError):
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert not hub.requests


@pytest.mark.parametrize("private", [False, 1, None, "true"])
def test_public_or_ambiguous_dataset_rejected_before_file_read(hub, private):
    hub.info["private"] = private
    with pytest.raises(DailySnapshotError) as result:
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert result.value.code == "NOT_PRIVATE" and len(hub.requests) == 1


@pytest.mark.parametrize("change", [{"sha": "main"}, {"id": "Other/private"}])
def test_exact_identity_and_commit_required(hub, change):
    hub.info.update(change)
    with pytest.raises(DailySnapshotError):
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert len(hub.requests) == 1


@pytest.mark.parametrize("field,value", [("csv_path", "../bars.csv"), ("csv_path", "snapshots/old/bars.csv"),
    ("manifest_path", "https://example.invalid/manifest.json"), ("schema_version", True)])
def test_daily_pointer_cannot_escape_or_read_old_intraday_namespace(hub, field, value):
    hub.latest[field] = value
    with pytest.raises(DailySnapshotError):
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert len(hub.requests) == 2


@pytest.mark.parametrize("field,value", [("source", "synthetic"), ("session", "RTH"), ("rehab_type", True),
    ("frequency", "5m"), ("date_convention", "UTC_bar_start"), ("price_basis", "raw_unknown"),
    ("created_at", "2027-01-01T00:00:00Z"), ("symbols", ["SPY"])])
def test_daily_contract_and_timestamps_checked_before_csv(hub, field, value):
    hub.manifest[field] = value
    with pytest.raises(DailySnapshotError):
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert len(hub.requests) == 3


def test_payload_tampering_rejected_by_hash(hub):
    path = hub.latest["csv_path"]
    hub.payloads[path] = hub.payloads[path].replace(b"NVDA", b"AMD ")
    with pytest.raises(DailySnapshotError) as result:
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert result.value.code == "HASH_MISMATCH"


@pytest.mark.parametrize("field,value", [("bytes", 12 * 1024 * 1024 + 1), ("bytes", True),
    ("rows", 80_001), ("rows", 0), ("sha256", "b" * 64), ("path", "../private.csv")])
def test_declared_daily_size_rows_and_content_path_are_bounded_before_csv(hub, field, value):
    hub.manifest["csv"][field] = value
    with pytest.raises(DailySnapshotError):
        fetch_moomoo_daily_snapshot(opener=hub, now=NOW)
    assert len(hub.requests) == 3


@pytest.mark.parametrize("bad", [
    lambda raw: raw.replace(b"2026-11-23", b"2026-11-22"),
    lambda raw: raw.replace(b"2026-11-24", b"2026-11-26"),
    lambda raw: raw.replace(b"2026-11-24", b"2027-11-24"),
    lambda raw: raw.replace(b",NVDA,", b",SPY,"),
    lambda raw: raw.replace(b",102,1000", b",nan,1000"),
    lambda raw: raw.replace(b",2000", b",-1"),
    lambda raw: raw.replace(b"date,symbol", b"timestamp,symbol"),
])
def test_daily_parser_rejects_invalid_sessions_future_duplicate_or_ohlcv(bad):
    with pytest.raises(DailySnapshotError):
        parse_daily_csv(bad(daily_csv()), now=NOW)


def test_completed_day_uses_exchange_close_and_twenty_minute_buffer():
    with pytest.raises(DailySnapshotError):
        parse_daily_csv(daily_csv(), now=pd.Timestamp("2026-11-24T21:19:59Z"))
    assert len(parse_daily_csv(daily_csv(), now=pd.Timestamp("2026-11-24T21:20:00Z"))) == 4


def test_half_day_calendar_completion_and_missing_rows_are_not_filled():
    contents = daily_csv().replace(b"2026-11-23", b"2026-11-27").replace(b"2026-11-24", b"2026-11-30")
    with pytest.raises(DailySnapshotError):
        parse_daily_csv(contents, now=pd.Timestamp("2026-11-27T18:20:00Z"))
    half = b"\n".join(contents.splitlines()[:3]) + b"\n"
    frame = parse_daily_csv(half, now=pd.Timestamp("2026-11-27T18:20:00Z"))
    assert len(frame) == 2
    incomplete = b"\n".join(daily_csv().splitlines()[:-1]) + b"\n"
    assert len(parse_daily_csv(incomplete, now=NOW)) == 3


def test_identity_boundary_rejects_old_reused_ticker():
    old = daily_csv().replace(b"NVDA", b"SNDK").replace(b"2026-11-23", b"2024-11-25").replace(b"2026-11-24", b"2024-11-26")
    with pytest.raises(DailySnapshotError):
        parse_daily_csv(old, now=NOW, start_dates={"SNDK": "2025-02-24"})


def test_http_error_never_exposes_provider_body_or_token(hub):
    def denied(request, timeout):
        raise HTTPError(request.full_url + "?secret=" + TOKEN, 403, TOKEN, {}, BytesIO(b"PRIVATE_CSV"))
    with pytest.raises(DailySnapshotError) as result:
        fetch_moomoo_daily_snapshot(opener=denied, now=NOW)
    assert result.value.code == "ACCESS_DENIED"
    assert TOKEN not in str(result.value) and "PRIVATE_CSV" not in str(result.value)
