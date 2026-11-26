"""Read one immutable, private moomoo snapshot; no broker or local-file access.

The dedicated read token is used only for fixed Hugging Face HTTPS requests.
It is never returned, persisted, embedded in a URL, or forwarded to a CDN.
The caller keeps prices server-side and publishes only research results.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import pandas as pd

from hf_space.intraday import MAX_ROWS, MAX_UPLOAD_BYTES, parse_intraday_csv


DATASET_ID = "Rexymiao/alpha-trading-snapshots"
HUB_HOST = "huggingface.co"
# Exact official download hosts; no arbitrary URL, wildcard, or dynamic allowlist.
# https://huggingface.co/docs/hub/en/models-downloading
DOWNLOAD_HOSTS = frozenset({HUB_HOST, "cas-server.xethub.hf.co", "cas-server.xethub-eu.hf.co",
    "transfer.xethub.hf.co", "transfer.xethub-eu.hf.co", "us.aws.cdn.hf.co", "us.gcp.cdn.hf.co",
    "cdn-lfs-us-1.hf.co", "cdn-lfs-eu-1.hf.co"})
METADATA_LIMIT = 128 * 1024
REQUEST_TIMEOUT = 15.0
TOTAL_TIMEOUT = 60.0
_HEX64 = re.compile(r"[a-f0-9]{64}\Z")
_HEX40 = re.compile(r"[a-f0-9]{40}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)\Z")


class SnapshotError(ValueError):
    """A safe public error; provider bodies, URLs and credentials are omitted."""

    def __init__(self, message, *, code="INVALID_SNAPSHOT"):
        super().__init__(message)
        self.code = code


def _transport_url(url):
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == "https" and parts.hostname in DOWNLOAD_HOSTS
                 and parts.port in (None, 443) and parts.username is None
                 and parts.password is None and not parts.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise SnapshotError("The snapshot download redirect was refused.", code="REDIRECT_REFUSED")
    return parts


class _SnapshotRedirect(HTTPRedirectHandler):
    """Permit only known HF download hosts, never cross-host authorization."""

    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urljoin(req.full_url, newurl)
        target = _transport_url(destination)
        redirected = super().redirect_request(req, fp, code, msg, headers, destination)
        if redirected is not None:
            if target.hostname != urlsplit(req.full_url).hostname or target.hostname != HUB_HOST:
                redirected.remove_header("Authorization")
        return redirected


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SnapshotError("The private snapshot request timed out.", code="TIMEOUT")
    return min(REQUEST_TIMEOUT, remaining)


def _body(response, limit, deadline):
    headers = getattr(response, "headers", {})
    length = headers.get("Content-Length")
    if length is not None:
        try:
            size = int(length)
        except (ValueError, TypeError):
            raise SnapshotError("Invalid snapshot response length.") from None
        if size < 0 or size > limit:
            raise SnapshotError("The snapshot response exceeds its size limit.", code="SIZE_LIMIT")
    data = bytearray()
    read = getattr(response, "read1", response.read)
    while True:
        timeout = _remaining(deadline)
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(timeout)
        chunk = read(min(65536, limit + 1 - len(data)))
        _remaining(deadline)
        if not isinstance(chunk, bytes):
            raise SnapshotError("The snapshot response was not a byte stream.")
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > limit:
            raise SnapshotError("The snapshot response exceeds its size limit.", code="SIZE_LIMIT")


def _get(url, token, open_request, limit, deadline):
    # All initial URLs are constructed here on the Hub itself. Only the redirect
    # handler may reach a fixed CDN, with Authorization removed first.
    if _transport_url(url).hostname != HUB_HOST:
        raise SnapshotError("Invalid snapshot request destination.")
    request = Request(url, headers={"Authorization": "Bearer " + token,
        "User-Agent": "AlphaLab-PrivateSnapshot/1.0", "Accept-Encoding": "identity"})
    try:
        with open_request(request, timeout=_remaining(deadline)) as response:
            if hasattr(response, "geturl"):
                _transport_url(response.geturl())
            status = getattr(response, "status", 200)
            if status != 200:
                raise HTTPError(url, status, "", {}, None)
            return _body(response, limit, deadline)
    except SnapshotError:
        raise
    except HTTPError as error:
        status = error.code
        error.close()
        if status in (401, 403):
            raise SnapshotError("Private snapshot access was denied. Check the dedicated read-token configuration.", code="ACCESS_DENIED") from None
        if status == 404:
            raise SnapshotError("The configured private snapshot or file is unavailable.", code="NOT_AVAILABLE") from None
        raise SnapshotError("The snapshot provider returned an HTTP error.", code="HTTP_ERROR") from None
    except (TimeoutError, URLError, OSError):
        raise SnapshotError("The private snapshot service is unavailable or timed out.", code="SERVICE_UNAVAILABLE") from None


def _json(data):
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError):
        raise SnapshotError("Snapshot metadata is not valid UTF-8 JSON.") from None
    if not isinstance(value, dict):
        raise SnapshotError("Snapshot metadata must be a JSON object.")
    return value


def _integer(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise SnapshotError("Snapshot metadata contains an invalid size or row count.")
    return value


def _instant(value):
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise SnapshotError("Snapshot timestamps must be explicit UTC ISO instants.")
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError):
        raise SnapshotError("Snapshot metadata contains an invalid timestamp.") from None


def _iso(stamp):
    return stamp.isoformat().replace("+00:00", "Z")


def fetch_moomoo_snapshot(*, opener=None):
    """Return (prices, public-safe provenance), pinned to one private revision.

    No global cache or disk writes. ``opener`` is an offline-testing seam that
    accepts urllib Request + timeout and returns a context-managed byte response.
    No fallback to the publishing token, a broker, a public feed, or toy prices.
    """
    dataset = os.environ.get("ALPHA_SNAPSHOT_DATASET", "")
    token = os.environ.get("ALPHA_SNAPSHOT_READ_TOKEN", "")
    if not dataset or not token:
        raise SnapshotError("Private moomoo snapshots are not configured. Choose visitor CSV or teaching data, or ask the operator to configure the private snapshot source.", code="NOT_CONFIGURED")
    if dataset != DATASET_ID:
        raise SnapshotError("Only the fixed Rexymiao private snapshot dataset is permitted.", code="INVALID_CONFIGURATION")
    if not isinstance(token, str) or not 1 <= len(token) <= 2048 or any(not 33 <= ord(char) <= 126 for char in token):
        raise SnapshotError("The dedicated snapshot read-token configuration is invalid.", code="INVALID_CONFIGURATION")
    deadline = time.monotonic() + TOTAL_TIMEOUT
    open_request = opener if opener is not None else build_opener(ProxyHandler({}), _SnapshotRedirect()).open
    info = _json(_get(f"https://{HUB_HOST}/api/datasets/{dataset}/revision/main", token,
                      open_request, METADATA_LIMIT, deadline))
    if info.get("private") is not True:
        raise SnapshotError("The snapshot dataset must be private; public repositories are refused.", code="NOT_PRIVATE")
    revision = info.get("sha")
    if info.get("id") != DATASET_ID or not isinstance(revision, str) or _HEX40.fullmatch(revision) is None:
        raise SnapshotError("The private dataset identity or revision is invalid.")
    base = f"https://{HUB_HOST}/datasets/{dataset}/resolve/{revision}/"
    latest = _json(_get(base + "latest.json", token, open_request, METADATA_LIMIT, deadline))
    identifier = latest.get("snapshot_id")
    if type(latest.get("schema_version")) is not int or latest["schema_version"] != 1 or not isinstance(identifier, str) or _HEX64.fullmatch(identifier) is None:
        raise SnapshotError("Unsupported snapshot pointer schema or identifier.")
    manifest_path = f"snapshots/{identifier}/manifest.json"
    csv_path = f"snapshots/{identifier}/bars.csv"
    if latest.get("manifest_path") != manifest_path or latest.get("csv_path") != csv_path:
        raise SnapshotError("Snapshot paths must match the fixed content-addressed layout.", code="INVALID_PATH")
    manifest = _json(_get(base + manifest_path, token, open_request, METADATA_LIMIT, deadline))
    expected = {"schema_version": 1, "source": "moomoo", "bar_minutes": 5,
        "timestamp_convention": "UTC_bar_start", "benchmark": "SPY", "session": "RTH"}
    if any(manifest.get(key) != value or (isinstance(value, int) and type(manifest.get(key)) is not int)
           for key, value in expected.items()):
        raise SnapshotError("The snapshot manifest does not match the five-minute moomoo contract.")
    csv = manifest.get("csv")
    if not isinstance(csv, dict) or csv.get("path") != csv_path or csv.get("sha256") != identifier:
        raise SnapshotError("The CSV path or hash does not match its snapshot identifier.", code="INVALID_PATH")
    byte_count = _integer(csv.get("bytes"), 1, MAX_UPLOAD_BYTES)
    row_count = _integer(csv.get("rows"), 1, MAX_ROWS)
    symbols = manifest.get("symbols")
    if (not isinstance(symbols, list) or not all(isinstance(symbol, str) for symbol in symbols)
            or not 2 <= len(symbols) <= 13 or len(set(symbols)) != len(symbols) or "SPY" not in symbols):
        raise SnapshotError("The snapshot symbol list is invalid.")
    created_at, as_of = _instant(manifest.get("created_at")), _instant(manifest.get("as_of"))
    if as_of > created_at or created_at > pd.Timestamp.now(tz="UTC"):
        raise SnapshotError("The snapshot metadata has inconsistent or future timestamps.")
    normalization = manifest.get("normalization")
    if not isinstance(normalization, dict):
        raise SnapshotError("The snapshot must disclose its verified timestamp normalization.")
    label, conversion = normalization.get("provider_timestamp_label"), normalization.get("conversion")
    verification = normalization.get("verification_source")
    if (not isinstance(label, str) or not isinstance(conversion, str)
            or (label, conversion) not in {("bar_start", "none"), ("bar_end", "subtract_5_minutes")}
            or not isinstance(verification, str) or not 1 <= len(verification.strip()) <= 1000):
        raise SnapshotError("The snapshot timestamp normalization is not verified or supported.")
    contents = _get(base + csv_path, token, open_request, min(MAX_UPLOAD_BYTES, byte_count), deadline)
    if len(contents) != byte_count or hashlib.sha256(contents).hexdigest() != identifier:
        raise SnapshotError("The private snapshot CSV failed its byte-count or SHA256 check.", code="HASH_MISMATCH")
    try:
        prices = parse_intraday_csv(contents, benchmark="SPY")
    except (ValueError, TypeError):
        # Parser details can contain cell content; do not echo private OHLC.
        raise SnapshotError("The private snapshot failed five-minute OHLCV validation.", code="INVALID_PRICES") from None
    if len(prices) != row_count or set(prices.symbol) != set(symbols):
        raise SnapshotError("The CSV rows or symbols differ from its manifest.")
    if prices.timestamp.max() + pd.Timedelta(minutes=5) != as_of:
        raise SnapshotError("Snapshot as_of must identify the last CSV bar's end.")
    provenance = {"provider": "moomoo_private_snapshot", "source": "moomoo_snapshot",
        "dataset": DATASET_ID, "private_verified": True, "revision": revision,
        "snapshot_id": identifier, "created_at": _iso(created_at), "as_of": _iso(as_of),
        "retrieved_at": _iso(pd.Timestamp.now(tz="UTC")), "benchmark": "SPY",
        "symbols": sorted(symbols), "bar_minutes": 5, "session": "RTH",
        "timestamp_convention": "UTC_bar_start", "csv_sha256": identifier,
        "csv_bytes": byte_count, "csv_rows": row_count, "raw_download_available": False,
        "normalization": {"provider_timestamp_label": label, "conversion": conversion,
            "verification_source_sha256": hashlib.sha256(verification.encode("utf-8")).hexdigest()}}
    return prices, provenance
