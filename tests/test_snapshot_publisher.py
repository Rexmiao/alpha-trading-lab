"""Private-only upload boundary and provenance checks, without any network."""
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.sync_moomoo_snapshot import build_payloads, publish_payloads, SnapshotPublishError, DATASET


CSV = (b'timestamp,symbol,open,high,low,close,volume\n'
       b'2026-11-24T14:30:00Z,SPY,100,101,99,100.5,1000\n'
       b'2026-11-24T14:30:00Z,NVDA,100,101,99,100.5,1000\n')
NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


def provenance(contents=CSV):
    return {'source':'moomoo','status':'success','interval':'5m','session':'RTH','read_only':True,
        'csv':{'sha256':hashlib.sha256(contents).hexdigest(),'bytes':len(contents),'rows':2},
        'normalization':{'provider_timestamp_label':'bar_end','conversion':'subtract_5_minutes',
            'verification_source':'Observed OHLC right-end aggregation matched; native volume retained'},
        'account_id':'must-not-leave-local-provenance','local_path':'must-not-leave-local-provenance'}


def test_allowlisted_snapshot_contains_no_local_account_or_provenance_fields():
    payloads, manifest = build_payloads(CSV, provenance(), now=NOW)
    assert len(payloads) == 3 and payloads[manifest['csv']['path']] == CSV
    latest = json.loads(payloads['latest.json'])
    assert latest['snapshot_id'] == manifest['csv']['sha256']
    assert manifest['as_of'] == '2026-11-24T14:35:00Z'
    assert manifest['symbols'] == ['NVDA', 'SPY']
    assert not any(b'must-not-leave' in value for value in payloads.values())


@pytest.mark.parametrize('change', [
    {'csv':{'sha256':'0'*64,'bytes':len(CSV),'rows':2}},
    {'status':'failed'}, {'session':'ALL'}, {'read_only':False},
    {'normalization':{'provider_timestamp_label':'unverified','conversion':'none','verification_source':'not confirmed'}},
    {'normalization':{'provider_timestamp_label':'bar_end','conversion':'subtract_5_minutes','verification_source':'C:\\private\\source.json'}},
])
def test_failed_capture_wrong_hash_or_unverified_label_never_becomes_a_snapshot(change):
    source = provenance()
    source.update(change)
    with pytest.raises(SnapshotPublishError):
        build_payloads(CSV, source, now=NOW)


@pytest.mark.parametrize('bad', [
    CSV.replace(b'100.5,1000', b'nan,1000'),
    CSV.replace(b'T14:30:00Z',b'T14:31:00Z'),
    CSV.replace(b'2026-11-24',b'2027-11-24'),
    CSV.replace(b',NVDA,',b',SPY,'),
])
def test_invalid_or_future_csv_cannot_be_uploaded_even_with_matching_manifest_hash(bad):
    with pytest.raises(SnapshotPublishError):
        build_payloads(bad, provenance(bad), now=NOW)


class API:
    def __init__(self, private=True):
        self.private = private
        self.commits = []
        self.existing = []

    def repo_info(self, **kwargs):
        assert kwargs == {'repo_id':DATASET,'repo_type':'dataset','revision':'main'}
        return SimpleNamespace(id=DATASET, private=self.private, sha='a'*40)

    def list_repo_files(self, **kwargs):
        assert kwargs['revision'] == 'a'*40
        return self.existing

    def create_commit(self, **kwargs):
        self.commits.append(kwargs)
        return SimpleNamespace(oid='b'*40)


def test_public_dataset_is_rejected_before_any_upload():
    payloads, _ = build_payloads(CSV, provenance(), now=NOW)
    api = API(private=False)
    with pytest.raises(SnapshotPublishError, match='PRIVATE_DATASET'):
        publish_payloads(payloads, api=api, operation_factory=lambda **kwargs:kwargs)
    assert not api.commits


def test_three_files_are_atomic_expected_parent_commit_and_old_snapshots_not_overwritten():
    payloads, manifest = build_payloads(CSV, provenance(), now=NOW)
    api = API()
    assert publish_payloads(payloads, api=api, operation_factory=lambda **kwargs:kwargs) == 'b'*40
    call = api.commits[0]
    assert call['parent_commit'] == 'a'*40 and len(call['operations']) == 3
    assert {item['path_in_repo'] for item in call['operations']} == set(payloads)
    api.existing.append(manifest['csv']['path'])
    with pytest.raises(SnapshotPublishError, match='NO_OVERWRITE'):
        publish_payloads(payloads, api=api, operation_factory=lambda **kwargs:kwargs)
    assert len(api.commits) == 1
