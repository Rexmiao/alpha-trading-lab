"""Validate the exact static artifact published to GitHub Pages (stdlib only)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "web"
    expected = {
        "index.html", "style.css", "main.js",
        "assets/training-flow.gif", "assets/training-flow-en.gif",
        "assets/poster.png", "assets/poster-en.png",
    }
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise SystemExit("Symlinks are not allowed in the public artifact.")
    files = {path.relative_to(root).as_posix(): path for path in paths if path.is_file()}
    if set(files) != expected:
        raise SystemExit("Public artifact file list differs from the approved teaching files.")
    for name, path in files.items():
        if path.suffix not in {".html", ".css", ".js"}:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(
            r"127\.0\.0\.1|localhost|[A-Z]:\\|BEGIN [A-Z ]*PRIVATE KEY|"
            r"OPENAPI_HOST_APPKEY|\.dpapi|runs/|data/raw|Bearer\s+[A-Za-z0-9]",
            text, re.IGNORECASE,
        ):
            raise SystemExit(f"Local/private reference found in {name}.")
        if re.search(r"\bfetch\s*\(|XMLHttpRequest|new WebSocket\s*\(", text):
            raise SystemExit(f"Unexpected network operation in {name}.")
    html = files["index.html"].read_text(encoding="utf-8")
    if "viewport" not in html or "lang=" not in html:
        raise SystemExit("Missing language or responsive document metadata.")
    for reference in re.findall(r'(?:src|href)="([^"#]+)"', html):
        if "://" in reference or reference.startswith("#"):
            continue
        target = reference.split("?", 1)[0].split("#", 1)[0]
        if not (root / target).is_file():
            raise SystemExit(f"Missing static reference: {target}.")
    print(json.dumps({
        "public_files": len(files),
        "total_bytes": sum(path.stat().st_size for path in files.values()),
        "sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for name, path in sorted(files.items())},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
