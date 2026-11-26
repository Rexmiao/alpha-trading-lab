"""Offline HTTP/schema tests; fixtures are synthetic, never broker observations."""
import hashlib
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pandas as pd
import pytest

from hf_space.intraday import make_synthetic_intraday_prices, run_intraday_comparison
from hf_space.snapshot_source import (
    DATASET_ID, METADATA_LIMIT, SnapshotError, _SnapshotRedirect, fetch_moomoo_snapshot,
)


TOKEN = "hf_offline_mock_read_token"
REVISION = "a" * 40


class Response(BytesIO):
    def __init__(self, body, url, headers=None, status=200):
        super().__init__(body)
        self.url, self.headers, self.status = url, headers or {}, status

    def geturl(self):
        return self.url


class MockHub:
    """Serve a mutable local fixture through the real request/validation path."""

    def __init__(self, prices):
        self.requests = []
        self.info = {"id": DATASET_ID, "private": True, "sha": REVISION}
        self.contents = prices.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode("utf-8")
        identifier = hashlib.sha256(self.contents).hexdigest()
        base = f"snapshots/{identifier}/"
        self.latest = {"schema_version": 1, "snapshot_id": identifier,
            "manifest_path": base + "manifest.json", "csv_path": base + "bars.csv"}
        as_of = prices.timestamp.max() + pd.Timedelta(minutes=5)
        self.manifest = {"schema_version": 1, "source": "moomoo", "bar_minutes": 5,
            "timestamp_convention": "UTC_bar_start", "benchmark": "SPY", "session": "RTH",
            "created_at": (as_of + pd.Timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "as_of": as_of.isoformat().replace("+00:00", "Z"), "symbols": sorted(prices.symbol.unique()),
            "csv": {"path": base + "bars.csv", "sha256": identifier, "bytes": len(self.contents), "rows": len(prices)},
            "normalization": {"provider_timestamp_label": "bar_start", "conversion": "none",
                "verification_source": "Offline schema fixture; not observed moomoo data."}}

    def __call__(self, request, timeout):
        self.requests.append(request)
        assert 0 < timeout <= 15
        assert request.get_header("Authorization") == "Bearer " + TOKEN
        url = request.full_url
        if "/api/datasets/" in url:
            body = json.dumps(self.info).encode()
        elif url.endswith("/latest.json"):
            body = json.dumps(self.latest).encode()
        elif url.endswith("/manifest.json"):
            body = json.dumps(self.manifest).encode()
        elif url.endswith("/bars.csv"):
            body = self.contents
        else:
            raise AssertionError("Unexpected fixed-repository URL")
        return Response(body, url)


@pytest.fixture(scope="module")
def prices():
    frame = make_synthetic_intraday_prices(days=2)
    frame.loc[frame.symbol.eq("BENCH"), "symbol"] = "SPY"
    return frame


@pytest.fixture
def hub(prices, monkeypatch):
    monkeypatch.setenv("ALPHA_SNAPSHOT_DATASET", DATASET_ID)
    monkeypatch.setenv("ALPHA_SNAPSHOT_READ_TOKEN", TOKEN)
    return MockHub(prices)


def test_private_fixed_revision_byte_hash_schema_and_public_provenance(hub, prices):
    # Deliberately include extra private metadata. It must not enter provenance.
    hub.manifest["private_note"] = "private-local-path-or-credential-must-not-be-published"
    frame, provenance = fetch_moomoo_snapshot(opener=hub)
    assert len(frame) == len(prices)
    assert set(frame.columns) == set(prices.columns)
    assert provenance["private_verified"] is True
    assert provenance["source"] == "moomoo_snapshot"
    assert provenance["revision"] == REVISION
    assert provenance["snapshot_id"] == hashlib.sha256(hub.contents).hexdigest()
    assert provenance["raw_download_available"] is False
    assert len(hub.requests) == 4
    assert all(f"/resolve/{REVISION}/" in item.full_url for item in hub.requests[1:])
    exported = json.dumps(provenance)
    assert TOKEN not in exported and "private-local-path" not in exported
    assert "Offline schema fixture" not in exported
    assert "verification_source_sha256" in provenance["normalization"]


@pytest.mark.parametrize("missing", ["ALPHA_SNAPSHOT_DATASET", "ALPHA_SNAPSHOT_READ_TOKEN"])
def test_missing_dedicated_configuration_does_not_request_or_use_publishing_token(hub, monkeypatch, missing):
    monkeypatch.delenv(missing)
    monkeypatch.setenv("HF_TOKEN", "publishing-token-must-not-be-used")
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=hub)
    assert error.value.code == "NOT_CONFIGURED"
    assert not hub.requests


@pytest.mark.parametrize("dataset", ["Other/alpha-trading-snapshots", DATASET_ID + "-other",
    "https://huggingface.co/" + DATASET_ID, "Rexymiao/../private", "http://127.0.0.1:22222"])
def test_dataset_destination_is_fixed_and_never_used_as_arbitrary_url(hub, monkeypatch, dataset):
    monkeypatch.setenv("ALPHA_SNAPSHOT_DATASET", dataset)
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=hub)
    assert error.value.code == "INVALID_CONFIGURATION"
    assert not hub.requests


@pytest.mark.parametrize("private", [False, None, 1, "true"])
def test_public_or_ambiguous_repository_is_refused_before_any_file_read(hub, private):
    hub.info["private"] = private
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=hub)
    assert error.value.code == "NOT_PRIVATE"
    assert len(hub.requests) == 1


@pytest.mark.parametrize("field,value", [("sha", "main"), ("sha", "a" * 64), ("id", "Other/data")])
def test_repository_identity_and_commit_must_match(hub, field, value):
    hub.info[field] = value
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=hub)
    assert len(hub.requests) == 1


@pytest.mark.parametrize("field,value", [("manifest_path", "../manifest.json"),
    ("csv_path", "https://example.com/bars.csv"), ("csv_path", "snapshots/other/bars.csv"),
    ("snapshot_id", "a/../../secret"), ("schema_version", True)])
def test_snapshot_pointer_cannot_escape_content_addressed_paths(hub, field, value):
    hub.latest[field] = value
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=hub)
    assert len(hub.requests) == 2


@pytest.mark.parametrize("field,value", [("source", "synthetic"), ("bar_minutes", 15),
    ("schema_version", True), ("benchmark", "QQQ"), ("session", "ALL"),
    ("timestamp_convention", "UTC_bar_end"), ("symbols", ["SPY"]),
    ("normalization", {"provider_timestamp_label": "bar_end", "conversion": "none", "verification_source": "x"}),
    ("normalization", {"provider_timestamp_label": [], "conversion": "none", "verification_source": "x"})])
def test_manifest_contract_is_strict(hub, field, value):
    hub.manifest[field] = value
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=hub)
    assert len(hub.requests) == 3


@pytest.mark.parametrize("field,value", [("bytes", 8 * 1024 * 1024 + 1), ("bytes", True),
    ("rows", 50_001), ("rows", 0), ("path", "../bars.csv"), ("sha256", "b" * 64)])
def test_manifest_csv_bounds_and_path_are_checked_before_download(hub, field, value):
    hub.manifest["csv"][field] = value
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=hub)
    assert len(hub.requests) == 3


def test_tampered_csv_and_manifest_rows_cannot_be_silently_accepted(hub):
    hub.contents = hub.contents.replace(b"TOY1", b"TOYX")
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=hub)
    assert error.value.code == "HASH_MISMATCH"


def test_declared_rows_and_last_bar_end_must_match_validated_csv(hub):
    hub.manifest["csv"]["rows"] -= 1
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=hub)
    hub.manifest["csv"]["rows"] += 1
    hub.manifest["as_of"] = "2024-01-01T00:00:00Z"
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=hub)


def test_missing_bars_are_preserved_and_screened_by_the_actual_intraday_engine(hub, prices):
    incomplete = prices.drop(prices.loc[prices.symbol.eq("TOY1")].index[0])
    source = MockHub(incomplete)
    frame, metadata = fetch_moomoo_snapshot(opener=source)
    assert len(frame) == len(prices) - 1
    report = run_intraday_comparison(frame, benchmark="SPY", source="uploaded_csv")
    assert report["status"] == "insufficient_history"
    assert not report["equity"]
    assert report["lineage"]["coverage"]["complete_session_count"] == 1


def test_future_csv_bars_are_rejected_by_the_real_parser_without_echoing_prices(hub, prices):
    future = prices.copy()
    future.loc[future.index[-1], "timestamp"] += pd.DateOffset(years=10)
    source = MockHub(future)
    source.manifest["as_of"] = hub.manifest["as_of"]
    source.manifest["created_at"] = hub.manifest["created_at"]
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=source)
    assert error.value.code == "INVALID_PRICES"


@pytest.mark.parametrize("headers,body", [({"Content-Length": str(METADATA_LIMIT + 1)}, b"{}"),
    ({}, b" " * (METADATA_LIMIT + 1)), ({"Content-Length": "not-a-size"}, b"{}")],
    ids=["declared-size", "actual-size", "invalid-header"])
def test_metadata_reader_limits_both_claimed_and_actual_stream_size(hub, headers, body):
    def oversized(request, timeout):
        return Response(body, request.full_url, headers=headers)
    with pytest.raises(SnapshotError):
        fetch_moomoo_snapshot(opener=oversized)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_http_failure_messages_never_expose_token_provider_body_or_signed_url(hub, status):
    def denied(request, timeout):
        raise HTTPError(request.full_url + "?secret=" + TOKEN, status,
                        TOKEN, {"Authorization": TOKEN}, BytesIO(b"raw-private-price"))
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=denied)
    assert TOKEN not in str(error.value) and "raw-private-price" not in str(error.value)
    assert "secret=" not in str(error.value)
    assert error.value.code in {"ACCESS_DENIED", "NOT_AVAILABLE", "HTTP_ERROR"}


def test_network_failures_are_sanitized(hub):
    def unavailable(request, timeout):
        raise URLError(TOKEN + " raw-private-price")
    with pytest.raises(SnapshotError) as error:
        fetch_moomoo_snapshot(opener=unavailable)
    assert error.value.code == "SERVICE_UNAVAILABLE"
    assert TOKEN not in str(error.value) and "raw-private-price" not in str(error.value)


def test_cross_host_redirect_drops_authorization_and_same_hub_redirect_keeps_it():
    handler = _SnapshotRedirect()
    original = Request("https://huggingface.co/datasets/" + DATASET_ID + "/resolve/commit/file",
                       headers={"Authorization": "Bearer " + TOKEN})
    cdn = handler.redirect_request(original, None, 302, "", {}, "https://us.aws.cdn.hf.co/file?signature=x")
    assert cdn.get_header("Authorization") is None
    assert not any(key.lower() == "authorization" for key, value in cdn.header_items())
    same = handler.redirect_request(original, None, 302, "", {}, "/api/resolve-cache/datasets/fixed")
    assert same.get_header("Authorization") == "Bearer " + TOKEN


@pytest.mark.parametrize("url", ["https://example.com/file", "http://huggingface.co/file",
    "https://huggingface.co.evil.example/file", "https://user@huggingface.co/file",
    "https://huggingface.co:8443/file", "file:///private", "https://127.0.0.1/file"])
def test_redirects_to_nonfixed_domains_or_nonhttps_are_refused(url):
    original = Request("https://huggingface.co/file", headers={"Authorization": "Bearer " + TOKEN})
    with pytest.raises(SnapshotError) as error:
        _SnapshotRedirect().redirect_request(original, None, 302, "", {}, url)
    assert error.value.code == "REDIRECT_REFUSED"
    assert TOKEN not in str(error.value)
