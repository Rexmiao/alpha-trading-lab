"""Offline UI checks; fixtures are not acceptance of real moomoo performance."""
import json

import pandas as pd
from streamlit.testing.v1 import AppTest


SCRIPT = '''
import streamlit as st
from hf_space.support_resistance_ui import render_sr_page
st.radio("语言 / Language", ["中文", "English"], key="hf_language", horizontal=True)
st.radio("研究 / Study", ["sr", "other"], key="test_study", horizontal=True)
def tr(zh, en):
    return en if st.session_state["hf_language"] == "English" else zh
if st.session_state["test_study"] == "sr":
    render_sr_page(tr)
else:
    st.title("Other research")
'''


def _fixture():
    prices = pd.DataFrame([
        ["2020-01-03T14:30:00Z", "SPY", 100., 102., 99., 101., 1000.],
        ["2020-01-03T14:30:00Z", "TEST", 100., 102., 99., 101., 1000.],
        ["2020-01-03T14:35:00Z", "TEST", 101., 103., 100., 102., 1200.],
    ], columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    provenance = {"source": "moomoo_snapshot", "revision": "a" * 40, "snapshot_id": "a" * 64,
                  "as_of": "2020-01-03T21:00:00Z", "csv_rows": 3, "raw_download_available": False}
    return prices, provenance


def _report(status="success"):
    ids = ("support_bounce", "resistance_breakout", "breakout_retest", "benchmark_rth")
    report = {
        "source": "moomoo_snapshot", "status": status,
        "metrics": [{"strategy": strategy, "status": "success", "total_return": 0., "max_drawdown": 0.,
                     "sharpe": None, "annualized_volatility": None, "total_cost": 0., "trade_count": 0,
                     "n_sessions": 2, "final_equity": 100000.} for strategy in ids],
        "equity": [{"strategy": strategy, "timestamp": timestamp, "session": "2020-01-03", "equity": 100000.,
                    "drawdown": 0., "cash": 100000.} for strategy in ids
                   for timestamp in ("2020-01-03T14:35:00Z", "2020-01-03T14:40:00Z")],
        "drawdown": [], "signals": [],
        "levels": [{"symbol": "TEST", "session": "2020-01-03", "level_id": kind + "-version-1",
                    "type": kind, "source_session": "2020-01-02", "center": center,
                    "lower": center * .999, "upper": center * 1.001}
                   for kind, center in (("support", 99.), ("resistance", 101.))],
        "events": [{"strategy": "resistance_breakout", "symbol": "TEST", "session": "2020-01-03",
                    "event": "entry_confirmed", "available_at": "2020-01-03T14:40:00Z", "signal_close": 102.}],
        "trades": [{"strategy": "resistance_breakout", "symbol": "TEST", "session": "2020-01-03",
                    "execution_at": "2020-01-03T14:40:00Z", "reference_price": 102., "quantity": 1, "side": "BUY"}],
        "weights": [{"strategy": strategy, "symbol": "__CASH__", "weight": 1., "kind": "actual", "asset_kind": "cash"}
                    for strategy in ids],
        "session_metrics": [], "coverage": {"evaluated_session_count": 2}, "config": {},
        "lineage": {"raw_OHLCV_in_report": False}, "warnings": [],
        "raw_csv": "NEVER_DOWNLOAD_FULL_OHLCV", "prices": [{"high": 103., "volume": 1200.}],
    }
    if status != "success":
        report.update(metrics=[], equity=[], levels=[], events=[], trades=[], weights=[])
    return report


def _app():
    app = AppTest.from_string(SCRIPT, default_timeout=40).run()
    assert not app.exception, [item.value for item in app.exception]
    return app


def test_default_private_source_needs_explicit_run_and_download_excludes_raw_prices(monkeypatch):
    from hf_space import support_resistance_ui as ui
    fetched, runs = [], []

    def fetch():
        fetched.append(1)
        return _fixture()

    def run(prices, **params):
        runs.append(params)
        return _report()

    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", fetch)
    monkeypatch.setattr(ui, "run_sr_comparison", run)
    app = _app()
    assert app.radio(key="sr_source").value == "moomoo_snapshot"
    assert not fetched and not runs
    assert len(app.get("plotly_chart")) == 0
    assert len(app.latex) >= 7  # The primer is available without data/network.
    app.button(key="sr_run").click().run()
    assert not app.exception and not app.error
    assert fetched == [1] and len(runs) == 1
    report = app.session_state["sr_result"]
    assert len(report["metrics"]) == 4
    assert report["source"] == "moomoo_snapshot"
    assert report["lineage"]["external_data"]["revision"] == "a" * 40
    assert "raw_csv" not in report and "prices" not in report and "close_path" not in report
    assert json.loads(app.session_state["sr_result_json"]) == report
    assert len(app.get("download_button")) == 2  # Header template and derived report only.
    assert len(app.get("plotly_chart")) == 3
    assert runs[0] == app.session_state["sr_result_context"]
    assert runs[0]["band_bps"] == 10 and runs[0]["confirmation_bars"] == 12
    assert runs[0]["initial_cash"] == 100000.
    text = " ".join(item.value for item in app.caption)
    assert "最多20%" in text and "现金至少80%" in text
    # A close is plotted only at its completed endpoint; no OHLC table is exported.
    assert app.session_state["sr_executed_close_path"].timestamp.iloc[0] == pd.Timestamp("2020-01-03T14:35:00Z")
    assert set(app.session_state["sr_executed_close_path"].columns) == {"timestamp", "symbol", "close", "session"}


def test_language_navigation_settings_and_refresh_preserve_executed_result(monkeypatch):
    from hf_space import support_resistance_ui as ui
    fetched, runs = [], []

    def fetch():
        fetched.append(1)
        prices, provenance = _fixture()
        provenance["revision"] = ("a" if len(fetched) == 1 else "b") * 40
        provenance["snapshot_id"] = ("a" if len(fetched) == 1 else "b") * 64
        return prices, provenance

    def run(prices, **params):
        runs.append(params)
        return _report()

    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", fetch)
    monkeypatch.setattr(ui, "run_sr_comparison", run)
    app = _app()
    app.button(key="sr_snapshot_refresh").click().run()
    assert len(fetched) == 1 and not runs
    app.button(key="sr_run").click().run()
    saved = app.session_state["sr_result_json"]
    for language in ("English", "中文"):
        app.radio(key="hf_language").set_value(language).run()
        assert not app.exception and app.session_state["sr_result_json"] == saved
        assert app.radio(key="sr_source").value == "moomoo_snapshot"
    app.number_input(key="sr_band").set_value(15).run()
    app.number_input(key="sr_confirmation").set_value(6).run()
    app.slider(key="sr_cost").set_value(15).run()
    app.radio(key="test_study").set_value("other").run()
    app.radio(key="test_study").set_value("sr").run()
    assert not app.exception and app.number_input(key="sr_band").value == 15
    assert app.slider(key="sr_cost").value == 15
    assert app.session_state["sr_result_context"]["band_bps"] == 10
    assert app.session_state["sr_result_json"] == saved and len(runs) == 1
    app.button(key="sr_snapshot_refresh").click().run()
    assert len(fetched) == 2 and len(runs) == 1 and app.session_state["sr_result_json"] == saved
    assert app.session_state["sr_snapshot_cache"]["provenance"]["revision"] == "b" * 40
    assert app.session_state["sr_result"]["lineage"]["external_data"]["revision"] == "a" * 40
    assert any("尚未用于" in item.value for item in app.caption)
    app.button(key="sr_run").click().run()
    assert not app.exception and len(runs) == 2 and len(fetched) == 2
    assert app.session_state["sr_result_context"]["band_bps"] == 15
    assert app.session_state["sr_result"]["lineage"]["external_data"]["revision"] == "b" * 40


def test_private_source_failure_is_redacted_and_never_falls_back(monkeypatch):
    from hf_space import support_resistance_ui as ui

    class Failure(ValueError):
        code = "NOT_CONFIGURED"

    def fail():
        raise Failure("SECRET_AND_PROVIDER_RESPONSE")

    def forbidden(*args, **kwargs):
        raise AssertionError("No substitute or computation on source failure")

    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", fail)
    monkeypatch.setattr(ui, "run_sr_comparison", forbidden)
    monkeypatch.setattr(ui, "make_synthetic_intraday_prices", forbidden)
    monkeypatch.setattr(ui, "parse_intraday_csv", forbidden)
    app = _app()
    app.button(key="sr_run").click().run()
    assert not app.exception and app.session_state["sr_result"] is None
    assert app.session_state["sr_error"] == "NOT_CONFIGURED"
    assert len(app.get("plotly_chart")) == 0
    text = " ".join(item.value for collection in (app.info, app.error, app.caption) for item in collection)
    assert "SECRET_AND" not in text and "尚未连接" in text
    app.radio(key="hf_language").set_value("English").run()
    assert any("not connected yet" in item.value for item in app.info)


def test_guest_csv_does_not_load_private_source_and_retains_upload(monkeypatch):
    from hf_space import support_resistance_ui as ui
    parsed, runs = [], []

    def forbidden(*args, **kwargs):
        raise AssertionError("CSV visitors do not fetch private or synthetic prices")

    def parse(payload, **params):
        parsed.append((payload, params))
        return _fixture()[0]

    def run(prices, **params):
        runs.append(params)
        return _report()

    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", forbidden)
    monkeypatch.setattr(ui, "make_synthetic_intraday_prices", forbidden)
    monkeypatch.setattr(ui, "parse_intraday_csv", parse)
    monkeypatch.setattr(ui, "run_sr_comparison", run)
    app = _app()
    app.radio(key="sr_source").set_value("uploaded_csv").run()
    assert app.button(key="sr_run").disabled and not parsed and not runs
    app.session_state["sr_upload_bytes"] = b"OFFLINE_FIXTURE_CSV_ONLY"
    app.session_state["sr_upload_name"] = "offline.csv"
    app.run()
    app.button(key="sr_run").click().run()
    assert not app.exception and not app.error
    assert parsed == [(b"OFFLINE_FIXTURE_CSV_ONLY", {"benchmark": "SPY"})]
    assert runs[0]["source"] == "uploaded_csv"
    assert "external_data" not in app.session_state["sr_result"]["lineage"]
    saved = app.session_state["sr_result_json"]
    app.radio(key="hf_language").set_value("English").run()
    assert app.session_state["sr_result_json"] == saved
    assert app.session_state["sr_upload_bytes"] == b"OFFLINE_FIXTURE_CSV_ONLY"


def test_insufficient_history_has_no_fake_equity_and_failed_rerun_clears_result(monkeypatch):
    from hf_space import support_resistance_ui as ui
    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", _fixture)
    monkeypatch.setattr(ui, "run_sr_comparison", lambda *a, **k: _report("insufficient_history"))
    app = _app()
    app.button(key="sr_run").click().run()
    assert not app.exception and not app.error
    assert app.session_state["sr_result"]["status"] == "insufficient_history"
    assert len(app.get("plotly_chart")) == 0
    monkeypatch.setattr(ui, "run_sr_comparison", lambda *a, **k: _report())
    app.button(key="sr_run").click().run()
    assert app.session_state["sr_result"]["metrics"]

    def fail(*args, **kwargs):
        raise ValueError("PRIVATE_ROW_AND_TOKEN")

    monkeypatch.setattr(ui, "run_sr_comparison", fail)
    app.button(key="sr_run").click().run()
    assert not app.exception and app.error
    for key in ("sr_result", "sr_result_json", "sr_result_context", "sr_executed_close_path"):
        assert app.session_state[key] is None
    assert "PRIVATE_ROW" not in " ".join(item.value for item in app.error)


def test_explicit_teaching_selection_runs_real_core_without_source_calls(monkeypatch):
    from hf_space import support_resistance_ui as ui

    def forbidden(*args, **kwargs):
        raise AssertionError("Teaching source must be explicitly separate from observed data")

    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", forbidden)
    monkeypatch.setattr(ui, "parse_intraday_csv", forbidden)
    app = _app()
    app.radio(key="sr_source").set_value("synthetic").run()
    assert "sr_result" not in app.session_state
    app.button(key="sr_run").click().run()
    assert not app.exception and not app.error
    report = app.session_state["sr_result"]
    assert report["status"] == "success" and report["source"] == "synthetic"
    assert {row["strategy"] for row in report["metrics"]} == set(ui.LABELS)
    assert report["config"]["benchmark"] == "BENCH"
    assert report["lineage"]["raw_OHLCV_in_report"] is False
    assert report["lineage"]["orders_submitted"] is False
    assert report["coverage"]["evaluated_session_count"] == 4
    assert len(app.get("plotly_chart")) == 3
    assert all(row["sharpe"] is None for row in report["metrics"])
    assert "prices" not in report and "close_path" not in report
    assert report["signals"] and all("signal_close" not in row for row in report["signals"])
    assert any(row.get("signal_close") is not None for row in report["events"])
    saved = app.session_state["sr_result_json"]
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception and app.session_state["sr_result_json"] == saved
    assert any("synthetic teaching" in item.value for item in app.warning)


def test_native_export_cannot_reconstruct_entire_close_path_but_keeps_sparse_audit_prices(monkeypatch):
    from hf_space import support_resistance_ui as ui
    report = _report()
    # Mirror the native engine's dense per-bar signal contract: each strategy
    # repeats the full observed stock-close path. These values must not escape.
    private_closes = [143.123456 + index / 1000 for index in range(12)]
    report["signals"] = [{"strategy": strategy, "symbol": "TEST", "session": "2020-01-03",
                          "timestamp": f"2020-01-03T{14 + (30 + 5 * index) // 60:02}:{(30 + 5 * index) % 60:02}:00Z",
                          "signal_close": close, "state": "flat", "selected": False,
                          "reason": "waiting_setup"}
                         for strategy in tuple(ui.LABELS)[:3] for index, close in enumerate(private_closes)]
    monkeypatch.setattr(ui, "fetch_moomoo_snapshot", _fixture)
    monkeypatch.setattr(ui, "run_sr_comparison", lambda *a, **k: report)
    app = _app()
    app.button(key="sr_run").click().run()
    assert not app.exception and not app.error
    exported_bytes = app.session_state["sr_result_json"]
    exported = json.loads(exported_bytes)
    assert len(exported["signals"]) == 36
    assert all("signal_close" not in row for row in exported["signals"])
    assert all(row["reason"] == "waiting_setup" for row in exported["signals"])
    assert all(str(close).encode() not in exported_bytes for close in private_closes)
    # Preserve genuine sparse confirmation and execution references for audit.
    assert exported["events"][0]["signal_close"] == 102.
    assert exported["trades"][0]["reference_price"] == 102.
    assert all("signal_close" in row for row in report["signals"])  # No mutation of engine output.
    assert "prices" not in exported and "close_path" not in exported
    assert len(app.get("download_button")) == 2
