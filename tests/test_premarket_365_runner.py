"""Offline runner guards; synthetic fixtures are not market observations."""
from datetime import date, timedelta
import json

import pytest

from scripts import run_premarket_365 as runner


def capture(tmp_path, symbols=None):
    symbols = list(symbols or runner.SYMBOLS)
    manifest = {"source": "moomoo_desktop_history", "target_start": runner.START,
                "target_end_exclusive": runner.END, "end_exclusive": runner.END,
                "interval": "1m", "session": "ALL", "rehab_type": 0, "read_only": True,
                "account_requests": 0, "orders": 0, "today_excluded": True,
                "target_calendar_days": 365, "symbols": symbols,
                "complete": True, "finished_at": "2026-11-27T20:00:00Z", "streams": {}}
    for symbol in symbols:
        raw = json.dumps({"ret_type": 0, "s2c": {"security": {"code": symbol, "market": "US"},
                         "kl_list": [{"time": "2025-11-28 09:31:00"}], "next_req_key": None}}).encode()
        filename = f"{symbol}-0001.json"
        (tmp_path / filename).write_bytes(raw)
        manifest["streams"][symbol] = {"complete_pagination": True, "rows": 1,
            "pages": [{"page": 1, "file": filename, "sha256": runner.sha256(raw), "bytes": len(raw),
                       "rows": 1, "next_req_key": None}]}
    days = [date(2025, 11, 28) + timedelta(days=i) for i in range(249)] + [date(2026, 11, 25)]
    # Runner tests validate archival contracts, not exchange-calendar generation.
    sessions = {d.isoformat(): {"open": f"{d}T14:30:00Z", "close": f"{d}T21:00:00Z"} for d in days}
    sessions["2025-11-26"] = {"open": "2025-11-26T14:30:00Z", "close": "2025-11-26T21:00:00Z"}
    (tmp_path / "calendar.json").write_text(json.dumps({"calendar": "XNYS", "target_start": runner.START,
         "target_end_exclusive": runner.END, "sessions": sessions}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def save_manifest(folder, manifest):
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_validates_every_page_and_prefers_latest_progress(tmp_path):
    manifest = capture(tmp_path)
    old = dict(manifest, complete=False)
    save_manifest(tmp_path, old)
    (tmp_path / "progress").mkdir()
    (tmp_path / "progress" / "0001.json").write_text(json.dumps(manifest), encoding="utf-8")
    verified, calendar, proof = runner.validate_capture(tmp_path)
    assert verified["complete"] is True
    assert proof["calendar"]["target_sessions"] == 250
    assert len(proof["pages"]) == 2
    assert list(runner.iter_symbol_rows(tmp_path, verified, "SPY"))[0]["time"] == "2025-11-28 09:31:00"


def test_incomplete_capture_never_starts_analysis(tmp_path, monkeypatch):
    manifest = capture(tmp_path)
    manifest["complete"] = False
    save_manifest(tmp_path, manifest)
    monkeypatch.setattr(runner, "analyze_symbol", lambda *args, **kwargs: pytest.fail("analysis started"))
    with pytest.raises(runner.ReportError, match="pagination_not_complete"):
        runner.run(tmp_path)


def test_tampered_last_symbol_page_rejected_before_analysis(tmp_path, monkeypatch):
    capture(tmp_path)
    (tmp_path / "SPY-0001.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "analyze_symbol", lambda *args, **kwargs: pytest.fail("analysis started"))
    with pytest.raises(runner.ReportError, match="hash_or_length"):
        runner.run(tmp_path)


def test_terminal_cursor_and_symbol_substitution_rejected(tmp_path):
    manifest = capture(tmp_path)
    page = tmp_path / "SPY-0001.json"
    envelope = json.loads(page.read_bytes())
    envelope["s2c"]["next_req_key"] = "still-more"
    raw = json.dumps(envelope).encode()
    page.write_bytes(raw)
    record = manifest["streams"]["SPY"]["pages"][0]
    record.update(sha256=runner.sha256(raw), bytes=len(raw), next_req_key="still-more")
    save_manifest(tmp_path, manifest)
    with pytest.raises(runner.ReportError, match="terminal_page_has_cursor"):
        runner.validate_capture(tmp_path)
    envelope["s2c"]["security"]["code"] = "AMD"
    raw = json.dumps(envelope).encode()
    page.write_bytes(raw)
    record.update(sha256=runner.sha256(raw), bytes=len(raw))
    save_manifest(tmp_path, manifest)
    with pytest.raises(runner.ReportError, match="page_symbol_or_status"):
        runner.validate_capture(tmp_path)


def test_archive_path_escape_rejected(tmp_path):
    with pytest.raises(runner.ReportError, match="leaf_name"):
        runner._local_file(tmp_path, "../not-an-archive.json")


def test_no_event_values_remain_unavailable():
    def outcome(n):
        return {"n": n, "drop_distribution": {"n": n, "mean": None, "median": None, "p90": None, "max": None},
                "thresholds": [{"drop_threshold": t, "k": 0, "n": n, "proportion": None,
                                 "lower": None, "upper": None} for t in (.005, .01, .02)],
                "negative_30m_close": {"k": 0, "n": n, "proportion": None, "lower": None, "upper": None}}
    html = runner._probability_table({"events": outcome(0), "baseline_same_eligible_days": outcome(0)})
    assert "0/0" in html and "—" in html
    assert "0.00% [0.00%" not in html
    assert runner.pct(None) == "—"


def test_disjoint_capture_merge_preserves_sources_and_adds_dia(tmp_path):
    first, second = tmp_path / "old", tmp_path / "dia"
    first.mkdir(); second.mkdir()
    capture(first)
    capture(second, ["DIA"])
    records, sources, calendar = runner.validate_captures([first, second])
    assert set(sources) == {"QQQ", "SPY", "DIA"}
    assert len(records) == 2 and sources["DIA"][0] == second.resolve()


def test_duplicate_symbol_capture_is_not_silently_overwritten(tmp_path):
    capture(tmp_path)
    with pytest.raises(runner.ReportError, match="duplicate_symbol"):
        runner.validate_captures([tmp_path, tmp_path])


def test_source_calendars_must_match(tmp_path):
    first, second = tmp_path / "old", tmp_path / "dia"
    first.mkdir(); second.mkdir()
    capture(first); capture(second, ["DIA"])
    calendar = json.loads((second / "calendar.json").read_text())
    calendar["sessions"]["2025-11-26"]["close"] = "2025-11-26T18:00:00Z"
    (second / "calendar.json").write_text(json.dumps(calendar))
    with pytest.raises(runner.ReportError, match="calendars_do_not_match"):
        runner.validate_captures([first, second])


@pytest.mark.parametrize("value", [True, 0, -1, 11, "NaN", "Infinity", "0.0000001"])
def test_invalid_gain_cutoff_fails_before_source_reads(value, monkeypatch):
    monkeypatch.setattr(runner, "validate_captures", lambda *_: pytest.fail("source read"))
    with pytest.raises(runner.ReportError):
        runner.run([], premarket_threshold_pct=value)


def test_custom_fractional_percent_and_duplicate_grid_validation():
    assert runner.decimal_text(runner.threshold_pct("1.25") / 100) == "0.0125"
    assert tuple(str(v) for v in runner.threshold_grid_pct("2.5,1.25,0.5")) == ("0.5", "1.25", "2.5")
    with pytest.raises(runner.ReportError, match="duplicate_threshold"):
        runner.threshold_grid_pct("2.5,2.50")


def test_interactive_html_labels_chosen_threshold_and_embeds_no_minute_rows(monkeypatch):
    monkeypatch.setattr(runner, "_render_reference_html", lambda _: '<html><head><title>QQQ / SPY gain >2.50%</title><style></style></head><body><header>QQQ / SPY gain >2.50%</header><section id="QQQ"></section><section id="audit"></section><script>function setLanguage(){}</script></body></html>')
    report = {"config": {"premarket_threshold_pct": "1.25", "threshold_grid_pct": ["0.5", "2.5"]},
              "code": {"engine_sha256": "audit"}, "source": {"captures": []},
              "results": {"QQQ": {"daily": []}, "SPY": {"daily": []}, "DIA": {"daily": []}}}
    html = runner.render_html(report)
    assert 'value="1.25"' in html and 'step="any"' in html
    assert '<title>Premarket gains and opening 30-minute downside</title>' in html
    h1 = html.split('<h1>')[1].split('</h1>')[0]
    assert '1.25' not in h1 and '2.5' not in h1
    assert 'Frozen Python reference · gain &gt; 1.25%' in html
    assert 'getExplorerSummary' in html and 'BigInt(a.numerator)' in html
    assert set(runner._explorer_payload(report)) == {"default_pct", "grid_pct", "fingerprints", "definitions", "symbols"}
    assert 'kl_list' not in json.dumps(runner._explorer_payload(report))
    assert 'download-custom' in html and 'No eligible days for this definition' in html
