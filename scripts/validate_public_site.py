"""Validate the exact static artifact published to GitHub Pages (stdlib only)."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


class EnglishFallback(HTMLParser):
    """Check initial HTML independently of JavaScript or browser preferences."""

    def __init__(self):
        super().__init__()
        self.language = None
        self.elements = {}
        self.description = None
        self.in_language_button = False
        self.unexpected_chinese_text = False

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "html":
            self.language = attributes.get("lang")
        if "id" in attributes:
            self.elements[attributes["id"]] = attributes
        if tag == "meta" and attributes.get("name") == "description":
            self.description = attributes.get("content", "")
        if tag == "button" and attributes.get("id") == "language":
            self.in_language_button = True

    def handle_endtag(self, tag):
        if tag == "button":
            self.in_language_button = False

    def handle_data(self, data):
        if not self.in_language_button and re.search(r"[\u4e00-\u9fff]", data):
            self.unexpected_chinese_text = True


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
    fallback = EnglishFallback()
    fallback.feed(html)
    if (fallback.language != "en" or fallback.unexpected_chinese_text
            or not fallback.description or re.search(r"[\u4e00-\u9fff]", fallback.description)
            or "<title>Alpha Training Lab · From data to decisions</title>" not in html):
        raise SystemExit("Fresh static HTML must display English before JavaScript runs.")
    if (fallback.elements.get("flowImage", {}).get("src") != "assets/poster-en.png"
            or fallback.elements.get("downloadGif", {}).get("href") != "assets/training-flow-en.gif"
            or "docs/media/en/alpha-training-flow.gif" not in html):
        raise SystemExit("English fallback poster, GIF download and README media are required.")
    for reference in re.findall(r'(?:src|href)="([^"#]+)"', html):
        if "://" in reference or reference.startswith("#"):
            continue
        target = reference.split("?", 1)[0].split("#", 1)[0]
        if not (root / target).is_file():
            raise SystemExit(f"Missing static reference: {target}.")
    print(json.dumps({
        "public_files": len(files),
        "default_language": "en",
        "english_fallback_checked": True,
        "total_bytes": sum(path.stat().st_size for path in files.values()),
        "sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for name, path in sorted(files.items())},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
