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


def test_dedicated_write_token_never_invokes_powershell_or_uses_deployment_token(monkeypatch):
    from scripts import sync_moomoo_snapshot as publisher
    monkeypatch.setenv('ALPHA_SNAPSHOT_WRITE_TOKEN', 'dedicated-dataset-only-fixture')
    monkeypatch.setenv('HF_TOKEN', 'deployment-fixture-must-not-be-used')
    monkeypatch.setattr(publisher.subprocess, 'run', lambda *a, **k: pytest.fail('No child process for explicit token'))
    assert publisher._write_token() == 'dedicated-dataset-only-fixture'


def _protected_fixture(tmp_path, monkeypatch):
    from scripts import sync_moomoo_snapshot as publisher
    protected = tmp_path / 'credential.dpapi'
    protected.write_text('offline-encrypted-fixture', encoding='utf-8')
    system_root = tmp_path / 'Windows'
    base = system_root / 'System32/WindowsPowerShell/v1.0'
    (base / 'Modules').mkdir(parents=True)
    (base / 'powershell.exe').touch()
    environment = {'ALPHA_SNAPSHOT_TOKEN_DPAPI': str(protected), 'SystemRoot': str(system_root),
        'PSModulePath': 'incompatible-powershell7-modules', 'PSModuleAnalysisCachePath': 'parent-cache',
        'HF_TOKEN': 'deployment-fixture-must-not-be-used'}
    monkeypatch.setattr(publisher, 'os', SimpleNamespace(name='nt', environ=environment))
    return publisher, base, environment


def test_dpapi_reader_uses_windows_powershell_system_modules_and_no_plaintext_arguments(tmp_path, monkeypatch, capsys):
    publisher, base, environment = _protected_fixture(tmp_path, monkeypatch)
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv[0] == str(base / 'powershell.exe')
        assert kwargs['env']['PSModulePath'] == str(base / 'Modules')
        assert 'PSModuleAnalysisCachePath' not in kwargs['env']
        assert kwargs['capture_output'] is True
        return SimpleNamespace(returncode=0, stdout='private-dataset-fixture', stderr='')
    monkeypatch.setattr(publisher.subprocess, 'run', execute)
    assert publisher._write_token() == 'private-dataset-fixture'
    assert len(calls) == 1 and environment['PSModulePath'] == 'incompatible-powershell7-modules'
    assert 'private-dataset-fixture' not in str(calls[0][0])
    assert not capsys.readouterr().out


def test_dpapi_failure_does_not_expose_child_output_or_reuse_hf_token(tmp_path, monkeypatch, capsys):
    publisher, _, _ = _protected_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(publisher.subprocess, 'run', lambda *a, **k:
        SimpleNamespace(returncode=1, stdout='sensitive-fixture', stderr='sensitive-fixture'))
    with pytest.raises(SnapshotPublishError, match='^LOCAL_PROTECTED_TOKEN_UNAVAILABLE$'):
        publisher._write_token()
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
