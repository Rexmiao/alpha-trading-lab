"""Local checkpoint and resume checks; no broker or credential access."""
import json

import pytest

from scripts import collect_premarket_history as capture


def test_checkpoint_latest_preserves_initial_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    capture.save(manifest, {"complete": False, "rows": 0})
    initial = manifest.read_bytes()
    capture.save(manifest, {"complete": True, "rows": 5000})
    assert manifest.read_bytes() == initial
    assert capture.load_capture_manifest(tmp_path) == {"complete": True, "rows": 5000}
    assert len(list((tmp_path / "progress").glob("*.json"))) == 2


def test_legacy_initial_manifest_is_read_without_journal(tmp_path):
    (tmp_path / "manifest.json").write_text('{"complete": false}', encoding="utf-8")
    assert capture.load_capture_manifest(tmp_path) == {"complete": False}


def test_resume_corruption_fails_before_credentials_or_network(tmp_path, monkeypatch):
    root = tmp_path / "captures"
    folder = root / "one"
    folder.mkdir(parents=True)
    (folder / "QQQ-0001.json").write_bytes(b"changed bytes")
    manifest = {
        "symbols": list(capture.SYMBOLS), "begin": capture.BEGIN,
        "end_exclusive": capture.END, "session": "ALL", "rehab_type": 0,
        "streams": {"QQQ": {"pages": [{"file": "QQQ-0001.json", "sha256": "bad"}]},
                    "SPY": {"pages": []}},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(capture, "OUTPUT", root)
    monkeypatch.setattr(capture, "credential", lambda: pytest.fail("credential accessed"))
    monkeypatch.setattr(capture.subprocess, "run", lambda *a, **k: pytest.fail("network requested"))
    with pytest.raises(ValueError, match="stored_page_hash"):
        capture.main(["--resume", str(folder)])


def test_resume_outside_capture_root_fails_before_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "OUTPUT", tmp_path / "allowed")
    monkeypatch.setattr(capture, "credential", lambda: pytest.fail("credential accessed"))
    with pytest.raises(ValueError, match="output_scope"):
        capture.main(["--resume", str(tmp_path / "elsewhere")])


def test_only_explicit_etf_subsets_are_accepted():
    assert capture.validate_symbols(["DIA"]) == ("DIA",)
    assert capture.validate_symbols(["QQQ", "SPY", "DIA"]) == ("QQQ", "SPY", "DIA")
    for bad in ([], ["DIA", "DIA"], ["AMD"], "DIA", [None]):
        with pytest.raises(ValueError, match="capture_symbol_scope"):
            capture.validate_symbols(bad)


def test_resume_does_not_expand_saved_symbols(tmp_path, monkeypatch):
    root = tmp_path / "captures"
    folder = root / "dia"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"symbols": ["DIA"]}), encoding="utf-8")
    monkeypatch.setattr(capture, "OUTPUT", root)
    monkeypatch.setattr(capture, "credential", lambda: pytest.fail("credential accessed"))
    with pytest.raises(ValueError, match="resume_symbol_scope"):
        capture.main(["--resume", str(folder), "--symbols", "QQQ", "SPY", "DIA"])
