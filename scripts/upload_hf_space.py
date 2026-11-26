"""Sync a validated package to an existing, personal, public CPU Basic Space.

No Space creation, deletion, hardware changes, login or credential persistence.
The deployment token is accepted only through HF_TOKEN in the process environment.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys

if __package__:
    from . import package_hf_space as package_tools
else:
    import package_hf_space as package_tools


DEFAULT_BUNDLE = Path(__file__).resolve().parents[2] / "outputs" / "hf-space-bundle"
HUB_ENDPOINT = "https://huggingface.co"
COMMIT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class SyncGuardError(RuntimeError):
    pass


class MissingTokenError(SyncGuardError):
    pass


class InvalidSpaceIdError(SyncGuardError):
    pass


class InvalidArgumentsError(SyncGuardError):
    pass


class BundleValidationError(SyncGuardError):
    pass


class PersonalOwnerMismatchError(SyncGuardError):
    pass


class SpaceVisibilityError(SyncGuardError):
    pass


class SpaceSDKError(SyncGuardError):
    pass


class HardwarePolicyError(SyncGuardError):
    pass


class RemoteContentError(SyncGuardError):
    pass


class RemoteRevisionError(SyncGuardError):
    pass


class CommitAttemptError(SyncGuardError):
    def __init__(self, cause):
        # Keep sanitized diagnostics only; a lost response may follow an accepted commit.
        self.error_type = type(cause).__name__
        self.http_status = _http_status(cause)


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def validate_space_id(value: str) -> str:
    value = str(value or "").strip()
    if value.count("/") != 1:
        raise InvalidSpaceIdError()
    owner, name = value.split("/")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", owner)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", name)
            or name.endswith((".", "-", ".git")) or ".." in name or "--" in name):
        raise InvalidSpaceIdError()
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleValidationError()
        result[key] = value
    return result


def load_bundle(folder: Path) -> dict[str, bytes]:
    """Return frozen bytes only after exact-file, manifest, hash and link checks."""
    folder = Path(folder).absolute()
    try:
        for ancestor in (folder, *folder.parents):
            package_tools._reject_link(ancestor)
        if not folder.is_dir():
            raise BundleValidationError()
        package_tools.check_output_directory(folder)
        actual = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
        if actual != package_tools.ALLOWED_FILES:
            raise BundleValidationError()
        payloads = {name: package_tools._read_stable(folder, name) for name in sorted(actual)}
        manifest = json.loads(payloads[package_tools.MANIFEST_NAME].decode("utf-8-sig"), object_pairs_hook=_unique_object)
        if (not isinstance(manifest, dict)
                or set(manifest) != {"schema_version", "artifact", "created_at", "entrypoint", "deployment_performed", "files"}
                or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
                or manifest["artifact"] != package_tools.ARTIFACT
                or manifest["entrypoint"] != "hf_space/streamlit_app.py"
                or manifest["deployment_performed"] is not False
                or not isinstance(manifest["created_at"], str)
                or not isinstance(manifest["files"], list)):
            raise BundleValidationError()
        entries = manifest["files"]
        expected_names = package_tools.ALLOWED_FILES - {package_tools.MANIFEST_NAME}
        if len(entries) != len(expected_names):
            raise BundleValidationError()
        checked = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
                raise BundleValidationError()
            name = entry["path"]
            if not isinstance(name, str) or name not in expected_names or name in checked:
                raise BundleValidationError()
            if type(entry["bytes"]) is not int or entry["bytes"] != len(payloads[name]):
                raise BundleValidationError()
            digest = entry["sha256"]
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise BundleValidationError()
            if hashlib.sha256(payloads[name]).hexdigest() != digest:
                raise BundleValidationError()
            checked.add(name)
        if checked != expected_names:
            raise BundleValidationError()
        for source, destination in package_tools.SOURCES:
            package_tools._validate_text(source, payloads[destination])
        if any(package_tools._read_stable(folder, name) != contents for name, contents in payloads.items()):
            raise BundleValidationError()
        return payloads
    except SyncGuardError:
        raise
    except (OSError, ValueError, TypeError, KeyError, package_tools.PackagingError):
        raise BundleValidationError() from None


def _hardware_values(runtime) -> tuple:
    hardware = _field(runtime, "hardware")
    if isinstance(hardware, Mapping):
        return hardware.get("current"), hardware.get("requested")
    return hardware, _field(runtime, "requested_hardware")


def validate_hardware(*runtimes) -> None:
    """Unknown is allowed only alongside an explicit CPU Basic observation."""
    observed = []
    for runtime in runtimes:
        for value in _hardware_values(runtime):
            if value is None:
                continue
            value = getattr(value, "value", value)
            if not isinstance(value, str) or value != "cpu-basic":
                raise HardwarePolicyError()
            observed.append(value)
    if not observed:
        raise HardwarePolicyError()


def _safe_stage(runtime) -> str | None:
    stage = _field(runtime, "stage")
    stage = getattr(stage, "value", stage)
    return stage if isinstance(stage, str) and re.fullmatch(r"[A-Z_]{1,48}", stage) else None


def _http_status(error) -> int | None:
    status = _field(_field(error, "response"), "status_code")
    return status if type(status) is int and 100 <= status <= 599 else None


def safe_error(error: Exception) -> dict:
    """Do not serialize exception messages, requests, responses or credentials."""
    if isinstance(error, CommitAttemptError):
        return {"error_type": error.error_type, "http_status": error.http_status}
    return {"error_type": type(error).__name__, "http_status": _http_status(error)}


def upload_bundle(folder: Path, space_id: str, *, api=None, operation_factory=None) -> dict:
    """Inject API/factory for offline boundary tests; no SDK import is required then."""
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise MissingTokenError()
    space_id = validate_space_id(space_id)
    payloads = load_bundle(folder)
    if api is None or operation_factory is None:
        from huggingface_hub import CommitOperationAdd, HfApi
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
        logging.getLogger("huggingface_hub").setLevel(logging.CRITICAL)
        logging.getLogger("httpx").setLevel(logging.CRITICAL)
        if api is None:
            # Explicit endpoint and token prevent endpoint/cache authentication fallback.
            api = HfApi(endpoint=HUB_ENDPOINT, token=token, library_name="alpha-lab-allowlist-sync")
        if operation_factory is None:
            operation_factory = CommitOperationAdd

    account = api.whoami(token=token)
    owner = space_id.split("/", 1)[0]
    if (_field(account, "type") != "user" or not isinstance(_field(account, "name"), str)
            or owner.casefold() != _field(account, "name").casefold()):
        raise PersonalOwnerMismatchError()
    info = api.space_info(repo_id=space_id)
    remote_id = _field(info, "id")
    if not isinstance(remote_id, str) or remote_id.casefold() != space_id.casefold():
        raise PersonalOwnerMismatchError()
    if (_field(info, "private") is not False or _field(info, "protected", False) is True
            or _field(info, "visibility") not in {None, "public"}):
        raise SpaceVisibilityError()
    if _field(info, "sdk") != "docker":
        raise SpaceSDKError()
    head = _field(info, "sha")
    if not isinstance(head, str) or COMMIT_PATTERN.fullmatch(head) is None:
        raise RemoteRevisionError()
    # Never request hardware, create a repo, change visibility or set billing.
    runtime = api.get_space_runtime(repo_id=space_id)
    validate_hardware(_field(info, "runtime"), runtime)
    remote_files = api.list_repo_files(repo_id=space_id, repo_type="space", revision=head)
    if (not isinstance(remote_files, list)
            or any(not isinstance(name, str) or name not in package_tools.ALLOWED_FILES | {".gitattributes"}
                   for name in remote_files)):
        raise RemoteContentError()
    operations = [operation_factory(path_in_repo=name, path_or_fileobj=payloads[name]) for name in sorted(payloads)]
    try:
        commit = api.create_commit(
            repo_id=space_id,
            repo_type="space",
            revision="main",
            parent_commit=head,
            operations=operations,
            commit_message="Sync allowlisted Alpha Lab simulator source",
        )
    except Exception as error:
        raise CommitAttemptError(error) from None
    oid = _field(commit, "oid")
    commit_verified = isinstance(oid, str) and COMMIT_PATTERN.fullmatch(oid) is not None
    result = {
        "status": "code_uploaded" if commit_verified else "upload_response_unconfirmed",
        "code_uploaded": True if commit_verified else None,
        "space_url": HUB_ENDPOINT + "/spaces/" + remote_id,
        "commit": oid if commit_verified else None,
        "files": len(operations),
        "app_running_verified": False,
    }
    # A runtime-read failure after an accepted commit must not be reported as no upload.
    try:
        result["runtime_stage_observed"] = _safe_stage(api.get_space_runtime(repo_id=space_id))
    except Exception as error:
        result["runtime_stage_observed"] = None
        result["runtime_check_error"] = safe_error(error)
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidArgumentsError()


def main(argv=None, *, api=None, operation_factory=None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--space-id", default=os.environ.get("HF_SPACE_ID", ""))
    try:
        arguments = parser.parse_args(argv)
        result = upload_bundle(arguments.bundle, arguments.space_id, api=api, operation_factory=operation_factory)
    except Exception as error:
        print(json.dumps({"status": "failed", "code_uploaded": None if isinstance(error, CommitAttemptError) else False, **safe_error(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["commit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
