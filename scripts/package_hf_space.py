"""Create an allowlisted, local-only Hugging Face Docker deployment bundle.

No imports of application code, market data reads, authentication or networking.
Existing output directories must contain only the known package files. This
script never recursively deletes a directory.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "MANIFEST.json"
ARTIFACT = "alpha-lab-huggingface-docker"
# Source -> path at the root of the uploaded Space. No recursive source copy.
SOURCES = (
    ("deploy/huggingface/Dockerfile", "Dockerfile"),
    ("deploy/huggingface/README.md", "README.md"),
    ("deploy/huggingface/requirements.txt", "requirements.txt"),
    ("deploy/huggingface/.dockerignore", ".dockerignore"),
    ("LICENSE", "LICENSE"),
    ("hf_space/__init__.py", "hf_space/__init__.py"),
    ("hf_space/engine.py", "hf_space/engine.py"),
    ("hf_space/history.py", "hf_space/history.py"),
    ("hf_space/strategies.py", "hf_space/strategies.py"),
    ("hf_space/strategy_ui.py", "hf_space/strategy_ui.py"),
    ("hf_space/streamlit_app.py", "hf_space/streamlit_app.py"),
    ("research/__init__.py", "research/__init__.py"),
    ("research/data.py", "research/data.py"),
    ("research/models.py", "research/models.py"),
    ("research/portfolio.py", "research/portfolio.py"),
)
ALLOWED_FILES = frozenset(destination for _, destination in SOURCES) | {MANIFEST_NAME}
ALLOWED_DIRECTORIES = frozenset(
    str(parent) for name in ALLOWED_FILES for parent in PurePosixPath(name).parents
    if str(parent) != "."
)


class PackagingError(RuntimeError):
    """An explicit boundary or stable-source check failed."""


def sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _reject_link(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise PackagingError("Symbolic links and directory junctions are not allowed.")


def _check_chain(path: Path, boundary: Path) -> None:
    """Check lexical containment before resolving, so links cannot disappear."""
    try:
        path.relative_to(boundary)
    except ValueError:
        raise PackagingError("A package path is outside its intended directory.") from None
    current = path
    while True:
        _reject_link(current)
        if current == boundary:
            break
        current = current.parent


def _fingerprint(info) -> tuple:
    # Windows path.stat and os.fstat can expose different ctime semantics.
    # Compare ctime only within each API, not across path and handle results.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_stable(root: Path, relative: str) -> bytes:
    path = root / relative
    _check_chain(path, root)
    try:
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise PackagingError(f"Required source is not a regular file: {relative}")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            contents = stream.read()
            finished = os.fstat(stream.fileno())
        after = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        raise PackagingError(f"Missing required source: {relative}") from None
    except OSError as error:
        raise PackagingError(f"Cannot read required source: {relative} ({type(error).__name__})") from None
    _check_chain(path, root)
    if (len({_fingerprint(item) for item in (before, opened, finished, after)}) != 1
            or before.st_ctime_ns != after.st_ctime_ns
            or opened.st_ctime_ns != finished.st_ctime_ns):
        raise PackagingError(f"Source changed while reading: {relative}")
    return contents


def _validate_text(relative: str, contents: bytes) -> None:
    try:
        text = contents.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise PackagingError(f"Source must be UTF-8 text: {relative}") from None
    if re.search(r"\bhf_[A-Za-z0-9]{20,}\b", text):
        raise PackagingError(f"Possible authentication material in source: {relative}")
    if relative.endswith(".py"):
        try:
            ast.parse(text, filename=relative)
        except SyntaxError:
            raise PackagingError(f"Python source is incomplete or invalid: {relative}") from None
    if relative == "deploy/huggingface/README.md":
        if not text.startswith("---\n") or not re.search(r"(?m)^sdk:\s*docker\s*$", text) or not re.search(r"(?m)^app_port:\s*7860\s*$", text):
            raise PackagingError("The Space README must declare Docker and app_port 7860.")


def snapshots(root: Path) -> dict[str, bytes]:
    result = {}
    for source, destination in SOURCES:
        contents = _read_stable(root, source)
        _validate_text(source, contents)
        result[destination] = contents
    verify_sources(root, result)
    return result


def verify_sources(root: Path, payloads: dict[str, bytes]) -> None:
    for source, destination in SOURCES:
        if _read_stable(root, source) != payloads[destination]:
            raise PackagingError(f"Source changed during packaging: {source}; retry after editing finishes.")


def check_output_directory(folder: Path) -> None:
    _reject_link(folder)
    if not folder.exists():
        return
    if not folder.is_dir():
        raise PackagingError("The bundle destination already exists as a non-directory.")
    for directory, names, files in os.walk(folder, followlinks=False):
        current = Path(directory)
        _check_chain(current, folder)
        for name in names:
            path = current / name
            _check_chain(path, folder)
            if path.relative_to(folder).as_posix() not in ALLOWED_DIRECTORIES:
                raise PackagingError("Existing bundle has an unexpected directory; nothing was deleted.")
        for name in files:
            path = current / name
            _check_chain(path, folder)
            if path.relative_to(folder).as_posix() not in ALLOWED_FILES:
                raise PackagingError("Existing bundle has an unexpected file; nothing was deleted.")
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise PackagingError("Existing bundle contains a non-regular file.")


def _atomic_write(path: Path, contents: bytes, boundary: Path) -> None:
    _check_chain(path, boundary)
    path.parent.mkdir(parents=True, exist_ok=True)
    _check_chain(path.parent, boundary)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".hf-package-", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        _check_chain(path, boundary)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            _check_chain(temporary, boundary)
            temporary.unlink()


def package(root: Path = ROOT, *, name: str = "hf-space-bundle") -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name) or name in {".", ".."}:
        raise PackagingError("Bundle name must be a simple filename, without path separators.")
    root = Path(root).absolute()
    _reject_link(root)
    payloads = snapshots(root)  # Missing or changing source fails before output writes.
    output_root = root.parent / "outputs"
    _check_chain(output_root, root.parent)
    output_root.mkdir(exist_ok=True)
    folder, archive = output_root / name, output_root / (name + ".zip")
    _check_chain(folder, output_root)
    _check_chain(archive, output_root)
    check_output_directory(folder)
    if archive.exists() and not archive.is_file():
        raise PackagingError("Archive destination is not a regular file.")
    manifest = {
        "schema_version": 1,
        "artifact": ARTIFACT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "entrypoint": "hf_space/streamlit_app.py",
        "deployment_performed": False,
        "files": [{"path": destination, "bytes": len(payloads[destination]),
                   "sha256": sha256(payloads[destination])} for _, destination in SOURCES],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    all_payloads = {**payloads, MANIFEST_NAME: manifest_bytes}
    folder.mkdir(exist_ok=True)
    for relative, contents in all_payloads.items():
        _atomic_write(folder / relative, contents, folder)
    check_output_directory(folder)
    for relative, expected in all_payloads.items():
        if _read_stable(folder, relative) != expected:
            raise PackagingError("Bundle verification failed; do not upload this output.")
    verify_sources(root, payloads)
    temporary_zip = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".hf-package-", suffix=".zip.tmp", dir=output_root, delete=False) as stream:
            temporary_zip = Path(stream.name)
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for relative, contents in all_payloads.items():
                bundle.writestr(relative, contents)
        with zipfile.ZipFile(temporary_zip) as bundle:
            if bundle.testzip() is not None or set(bundle.namelist()) != ALLOWED_FILES:
                raise PackagingError("Archive integrity verification failed.")
            if any(bundle.read(relative) != expected for relative, expected in all_payloads.items()):
                raise PackagingError("Archive contents differ from the frozen source snapshot.")
        verify_sources(root, payloads)
        _check_chain(archive, output_root)
        os.replace(temporary_zip, archive)
    finally:
        if temporary_zip is not None and temporary_zip.exists():
            _check_chain(temporary_zip, output_root)
            temporary_zip.unlink()
    return {"artifact": ARTIFACT, "bundle": "outputs/" + name,
            "archive": "outputs/" + name + ".zip", "files": len(all_payloads),
            "archive_sha256": sha256(archive.read_bytes()), "deployment_performed": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="hf-space-bundle", help="Folder/archive name under the parent outputs directory.")
    arguments = parser.parse_args(argv)
    try:
        result = package(name=arguments.name)
    except (PackagingError, OSError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, PackagingError) else type(error).__name__
        print("Packaging failed: " + message, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
