"""Publish an explicitly prepared moomoo snapshot to one private dataset.

The public Space receives only a dataset-scoped read token. This local command
never publishes broker credentials, account records or the collector's raw files.
Default mode validates locally without connecting to Hugging Face.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
from io import StringIO
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys


DATASET = 'Rexymiao/alpha-trading-snapshots'
COLUMNS = ('timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume')
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50_000


class SnapshotPublishError(ValueError):
    pass


def _iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def build_payloads(contents, source_manifest, *, now=None):
    """Build only three allowlisted payloads, independent of files and tokens."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(contents, bytes) or not 0 < len(contents) <= MAX_BYTES:
        raise SnapshotPublishError('CSV_SIZE_INVALID')
    if (not isinstance(source_manifest, dict) or source_manifest.get('source') != 'moomoo'
            or source_manifest.get('status') != 'success'
            or source_manifest.get('interval') != '5m' or source_manifest.get('session') != 'RTH'
            or source_manifest.get('read_only') is not True):
        raise SnapshotPublishError('MOOMOO_PROVENANCE_REQUIRED')
    digest = hashlib.sha256(contents).hexdigest()
    original_csv = source_manifest.get('csv') or {}
    if original_csv.get('sha256') != digest or original_csv.get('bytes') != len(contents):
        raise SnapshotPublishError('COLLECTOR_CSV_HASH_MISMATCH')
    normalization = source_manifest.get('normalization') or original_csv.get('normalization') or {}
    label, conversion = normalization.get('provider_timestamp_label'), normalization.get('conversion')
    if (label, conversion) not in {('bar_start', 'none'), ('bar_end', 'subtract_5_minutes')}:
        raise SnapshotPublishError('VERIFIED_TIME_NORMALIZATION_REQUIRED')
    evidence = normalization.get('verification_source')
    if not isinstance(evidence, str) or not 1 <= len(evidence) <= 400:
        raise SnapshotPublishError('NORMALIZATION_EVIDENCE_REQUIRED')
    # This explanatory field is not a route for uploading local paths or keys.
    if re.search(r'(?i)([a-z]:[\\/]|https?://|appkey|token|password|secret|credential)', evidence):
        raise SnapshotPublishError('SENSITIVE_PROVENANCE_FIELD')
    try:
        reader = csv.DictReader(StringIO(contents.decode('utf-8-sig'), newline=''))
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise SnapshotPublishError('CSV_COLUMNS_INVALID')
        seen, symbols, row_count, last_end = set(), set(), 0, None
        for row in reader:
            row_count += 1
            if row_count > MAX_ROWS or set(row) != set(COLUMNS):
                raise SnapshotPublishError('CSV_ROW_LIMIT_OR_SHAPE')
            text, symbol = row['timestamp'], row['symbol']
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00(?:Z|\+00:00)', text):
                raise SnapshotPublishError('UTC_BAR_START_REQUIRED')
            stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
            end = stamp + timedelta(minutes=5)
            if stamp.minute % 5 or end > now:
                raise SnapshotPublishError('FUTURE_OR_OFF_GRID_BAR')
            if not re.fullmatch(r'[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,2})?', symbol):
                raise SnapshotPublishError('SYMBOL_INVALID')
            key = (stamp, symbol)
            if key in seen:
                raise SnapshotPublishError('DUPLICATE_BAR')
            seen.add(key)
            symbols.add(symbol)
            values = [float(row[name]) for name in COLUMNS[2:]]
            opening, high, low, close, volume = values
            if (not all(math.isfinite(value) for value in values) or min(values[:4]) <= 0
                    or volume < 0 or high < max(opening, low, close) or low > min(opening, high, close)):
                raise SnapshotPublishError('OHLCV_INVALID')
            last_end = max(last_end, end) if last_end else end
    except (UnicodeError, csv.Error, TypeError, ValueError, OverflowError) as error:
        if isinstance(error, SnapshotPublishError):
            raise
        raise SnapshotPublishError('CSV_PARSE_FAILED') from None
    if not row_count or not 2 <= len(symbols) <= 13 or 'SPY' not in symbols:
        raise SnapshotPublishError('SPY_AND_ONE_TO_TWELVE_STOCKS_REQUIRED')
    if original_csv.get('rows') != row_count:
        raise SnapshotPublishError('COLLECTOR_ROW_COUNT_MISMATCH')
    folder = 'snapshots/' + digest
    csv_path, manifest_path = folder + '/bars.csv', folder + '/manifest.json'
    manifest = {'schema_version': 1, 'source': 'moomoo', 'bar_minutes': 5,
        'timestamp_convention': 'UTC_bar_start', 'benchmark': 'SPY', 'created_at': _iso(now),
        'as_of': _iso(last_end), 'session': 'RTH', 'symbols': sorted(symbols),
        'normalization': {'provider_timestamp_label': label, 'conversion': conversion,
                          'verification_source': evidence},
        'csv': {'path': csv_path, 'sha256': digest, 'bytes': len(contents), 'rows': row_count}}
    latest = {'schema_version': 1, 'snapshot_id': digest, 'manifest_path': manifest_path, 'csv_path': csv_path}
    def encode(value):
        return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    return {csv_path: contents, manifest_path: encode(manifest), 'latest.json': encode(latest)}, manifest


def publish_payloads(payloads, *, api, operation_factory):
    """Private-repository and expected-parent checks precede the only commit."""
    info = api.repo_info(repo_id=DATASET, repo_type='dataset', revision='main')
    if getattr(info, 'id', None) != DATASET or getattr(info, 'private', None) is not True:
        raise SnapshotPublishError('TARGET_MUST_BE_THE_CONFIGURED_PRIVATE_DATASET')
    head = getattr(info, 'sha', None)
    if not isinstance(head, str) or not re.fullmatch('[0-9a-f]{40}', head):
        raise SnapshotPublishError('DATASET_REVISION_UNAVAILABLE')
    latest = json.loads(payloads['latest.json'])
    # An identical snapshot is immutable and requires no replacement commit.
    existing = api.list_repo_files(repo_id=DATASET, repo_type='dataset', revision=head)
    if latest['manifest_path'] in existing or latest['csv_path'] in existing:
        raise SnapshotPublishError('SNAPSHOT_ALREADY_EXISTS_NO_OVERWRITE')
    operations = [operation_factory(path_in_repo=path, path_or_fileobj=raw)
                  for path, raw in sorted(payloads.items())]
    commit = api.create_commit(repo_id=DATASET, repo_type='dataset', revision='main', parent_commit=head,
        operations=operations, commit_message='Publish completed moomoo five-minute research snapshot')
    oid = getattr(commit, 'oid', None)
    if not isinstance(oid, str) or not re.fullmatch('[0-9a-f]{40}', oid):
        raise SnapshotPublishError('UPLOAD_RESPONSE_UNCONFIRMED_CHECK_REMOTE_BEFORE_RETRY')
    return oid


def _write_token():
    value = os.environ.get('ALPHA_SNAPSHOT_WRITE_TOKEN', '').strip()
    if value:
        return value
    protected = os.environ.get('ALPHA_SNAPSHOT_TOKEN_DPAPI')
    if not protected:
        raise SnapshotPublishError('LOCAL_DATASET_WRITE_TOKEN_NOT_CONFIGURED')
    if os.name != 'nt' or not Path(protected).is_file():
        raise SnapshotPublishError('LOCAL_PROTECTED_TOKEN_UNAVAILABLE')
    command = ('$ErrorActionPreference="Stop"; $s=ConvertTo-SecureString '
        '(Get-Content -LiteralPath $env:ALPHA_SNAPSHOT_TOKEN_DPAPI -Raw); '
        '$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); '
        'try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))} '
        'finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, timeout=10, check=False, text=True, env=os.environ,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not result.stdout.strip():
            raise SnapshotPublishError('LOCAL_PROTECTED_TOKEN_UNAVAILABLE')
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        raise SnapshotPublishError('LOCAL_PROTECTED_TOKEN_UNAVAILABLE') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', required=True, type=Path)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--publish', action='store_true', help='Upload only to the configured private dataset')
    args = parser.parse_args(argv)
    try:
        if args.csv.stat().st_size > MAX_BYTES or args.source_manifest.stat().st_size > 1024 * 1024:
            raise SnapshotPublishError('INPUT_FILE_TOO_LARGE')
        source = json.loads(args.source_manifest.read_text(encoding='utf-8-sig'))
        payloads, manifest = build_payloads(args.csv.read_bytes(), source)
        report = {'status': 'prepared_locally', 'uploaded': False, 'dataset': DATASET,
                  'csv_sha256': manifest['csv']['sha256'], 'rows': manifest['csv']['rows'],
                  'as_of': manifest['as_of'], 'files': sorted(payloads)}
        if args.publish:
            token = _write_token()
            try:
                from huggingface_hub import HfApi, CommitOperationAdd
            except ImportError:
                raise SnapshotPublishError('INSTALL_REQUIREMENTS_SNAPSHOT_TXT') from None
            api = HfApi(endpoint='https://huggingface.co', token=token)
            oid = publish_payloads(payloads, api=api, operation_factory=CommitOperationAdd)
            report.update(status='private_snapshot_uploaded', uploaded=True, revision=oid)
        print(json.dumps(report, ensure_ascii=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, SnapshotPublishError) else 'SNAPSHOT_PREPARATION_OR_UPLOAD_FAILED'
        print(json.dumps({'status':'failed', 'uploaded':None if args.publish else False, 'code':code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
