"""Exercise explicit-run, real intraday results and bilingual session state."""
import copy
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def _app():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=90).run()
    assert not app.exception
    app.radio(key="hf_study").set_value("intraday").run()
    assert not app.exception, [error.value for error in app.exception]
    return app


def test_intraday_real_engine_run_keeps_bytes_settings_and_source_on_language_and_page_changes(monkeypatch):
    from hf_space import intraday_ui

    calls = []
    original = intraday_ui.run_intraday_comparison

    def observed_run(prices, **kwargs):
        calls.append(kwargs.copy())
        return original(prices, **kwargs)

    monkeypatch.setattr(intraday_ui, "run_intraday_comparison", observed_run)
    app = _app()
    assert app.radio(key="intraday_source").value == "uploaded_csv"
    assert "intraday_result" not in app.session_state
    app.radio(key="intraday_source").set_value("synthetic").run()
    app.number_input(key="intraday_momentum_lookback").set_value(7).run()
    app.number_input(key="intraday_fast_window").set_value(2).run()
    app.number_input(key="intraday_slow_window").set_value(8).run()
    app.number_input(key="intraday_opening_range").set_value(4).run()
    app.selectbox(key="intraday_execution_delay").set_value(1).run()
    assert not calls
    app.button(key="intraday_run").click().run(timeout=90)
    assert not app.exception, [error.value for error in app.exception]
    assert not app.error, [error.value for error in app.error]
    report = app.session_state["intraday_result"]
    assert report["source"] == "synthetic"
    assert report["status"] == "success"
    assert len(report["metrics"]) == 3
    assert all(row["status"] == "success" for row in report["metrics"])
    assert report["equity"] and report["signals"] and report["session_metrics"]
    assert all(row["sharpe"] is None for row in report["metrics"])
    assert calls == [app.session_state["intraday_result_context"]]
    assert calls[0]["lookback_bars"] == 7 and calls[0]["execution_delay_bars"] == 1
    saved = app.session_state["intraday_result_json"]
    assert isinstance(saved, bytes)
    assert json.loads(saved) == report
    assert all(report["lineage"]["dependencies"][name] == version(name)
               for name in ("streamlit", "plotly", "pyarrow"))
    assert len(app.dataframe) >= 4

    for language in ("English", "中文", "English"):
        app.radio(key="hf_language").set_value(language).run()
        assert not app.exception
        assert app.radio(key="hf_study").value == "intraday"
        assert app.radio(key="intraday_source").value == "synthetic"
        assert app.number_input(key="intraday_momentum_lookback").value == 7
        assert app.number_input(key="intraday_fast_window").value == 2
        assert app.number_input(key="intraday_slow_window").value == 8
        assert app.number_input(key="intraday_opening_range").value == 4
        assert app.selectbox(key="intraday_execution_delay").value == 1
        assert app.session_state["intraday_result_json"] == saved
        assert len(calls) == 1
    assert app.title[0].value == "5-minute Momentum & Trend Lab"
    assert any(tab.label == "Mathematical derivation" for tab in app.tabs)

    app.number_input(key="intraday_momentum_lookback").set_value(9).run()
    app.radio(key="intraday_source").set_value("uploaded_csv").run()
    assert app.session_state["intraday_result_context"]["lookback_bars"] == 7
    assert app.session_state["intraday_result"]["source"] == "synthetic"
    assert any("last run used synthetic" in warning.value for warning in app.warning)
    assert app.session_state["intraday_result_json"] == saved
    app.radio(key="hf_study").set_value("ai").run()
    app.radio(key="hf_study").set_value("intraday").run()
    assert not app.exception
    assert app.number_input(key="intraday_momentum_lookback").value == 9
    assert app.radio(key="intraday_source").value == "uploaded_csv"
    assert app.session_state["intraday_result_json"] == saved
    assert len(calls) == 1


def test_intraday_upload_required_and_invalid_csv_never_falls_back_or_runs_engine(monkeypatch):
    from hf_space import intraday_ui

    def forbidden_run(*args, **kwargs):
        raise AssertionError("Invalid uploads must not reach the backtest")

    monkeypatch.setattr(intraday_ui, "run_intraday_comparison", forbidden_run)
    app = _app()
    assert app.button(key="intraday_run").disabled
    assert not app.error
    assert "intraday_result" not in app.session_state
    assert any("CSV" in item.value for item in app.info)
    # File-upload widgets have no upload setter in AppTest. Exercise the same
    # session bytes produced by its callback, through the real CSV validator.
    invalid = b"date,symbol,close\n2025-01-02,SPY,100\n"
    app.session_state["intraday_upload_bytes"] = invalid
    app.session_state["intraday_upload_name"] = "bad.csv"
    app.run()
    assert not app.button(key="intraday_run").disabled
    app.button(key="intraday_run").click().run()
    assert not app.exception
    assert app.error
    assert app.session_state["intraday_result"] is None
    assert app.session_state["intraday_result_json"] is None
    assert app.session_state["intraday_upload_bytes"] == invalid
    app.radio(key="hf_language").set_value("English").run()
    app.radio(key="hf_study").set_value("ai").run()
    app.radio(key="hf_study").set_value("intraday").run()
    assert not app.exception
    assert app.session_state["intraday_upload_bytes"] == invalid
    assert app.radio(key="intraday_source").value == "uploaded_csv"
    assert app.session_state["intraday_result"] is None


def test_intraday_parameter_error_is_visible_and_does_not_leave_an_old_success():
    app = _app()
    app.radio(key="intraday_source").set_value("synthetic").run()
    app.button(key="intraday_run").click().run(timeout=90)
    assert not app.exception
    assert app.session_state["intraday_result"]["status"] == "success"
    app.number_input(key="intraday_fast_window").set_value(12).run()
    assert app.session_state["intraday_result"] is not None
    app.button(key="intraday_run").click().run(timeout=90)
    assert not app.exception
    assert app.error
    assert app.session_state["intraday_result"] is None
    assert app.session_state["intraday_result_json"] is None
    assert app.session_state["intraday_result_context"] is None


def test_intraday_insufficient_history_status_survives_export_without_a_curve(monkeypatch):
    from hf_space import intraday_ui

    prices = intraday_ui.make_synthetic_intraday_prices(days=2)
    first_date = prices.timestamp.dt.date.min()
    one_session = prices.loc[prices.timestamp.dt.date.eq(first_date)].copy()
    monkeypatch.setattr(intraday_ui, "make_synthetic_intraday_prices", lambda **kwargs: one_session)
    app = _app()
    app.radio(key="intraday_source").set_value("synthetic").run()
    app.button(key="intraday_run").click().run(timeout=90)
    assert not app.exception
    report = app.session_state["intraday_result"]
    assert report["status"] == "insufficient_history"
    assert not report["equity"] and not report["metrics"] and not report["trades"]
    assert json.loads(app.session_state["intraday_result_json"])["status"] == "insufficient_history"
    assert len(app.get("plotly_chart")) == 0


def _published_fixture():
    """Synthetic UI fixture only; never represents a live private-dataset test."""
    from hf_space.intraday import make_synthetic_intraday_prices
    prices = make_synthetic_intraday_prices(days=2)
    prices.loc[prices.symbol.eq("BENCH"), "symbol"] = "SPY"
    digest = hashlib.sha256(prices.to_csv(index=False).encode()).hexdigest()
    provenance = {"provider": "moomoo_private_snapshot", "source": "moomoo_snapshot",
        "dataset": "Rexymiao/alpha-trading-snapshots", "private_verified": True,
        "revision": "a" * 40, "snapshot_id": digest,
        "as_of": (prices.timestamp.max() + pd.Timedelta(minutes=5)).isoformat(),
        "raw_download_available": False, "csv_sha256": digest}
    return prices, provenance


def test_snapshot_not_configured_is_friendly_and_cannot_train_or_fall_back(monkeypatch):
    from hf_space import intraday_ui
    monkeypatch.delenv("ALPHA_SNAPSHOT_DATASET", raising=False)
    monkeypatch.delenv("ALPHA_SNAPSHOT_READ_TOKEN", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unconfigured snapshots must not simulate or substitute toy data")

    monkeypatch.setattr(intraday_ui, "run_intraday_comparison", forbidden)
    monkeypatch.setattr(intraday_ui, "make_synthetic_intraday_prices", forbidden)
    app = _app()
    app.radio(key="intraday_source").set_value("moomoo_snapshot").run()
    assert "intraday_result" not in app.session_state
    app.button(key="intraday_run").click().run()
    assert not app.exception
    assert app.session_state["intraday_result"] is None
    assert app.session_state["intraday_error"] == "NOT_CONFIGURED"
    assert any("尚未连接" in item.value for item in app.info)
    text = " ".join(item.value for kind in (app.info, app.error, app.caption) for item in kind)
    assert "ALPHA_SNAPSHOT" not in text and "READ_TOKEN" not in text
    app.radio(key="hf_language").set_value("English").run()
    assert any("not connected yet" in item.value for item in app.info)
    assert app.session_state["intraday_result"] is None


def test_snapshot_fetch_cache_refresh_source_and_language_preserve_a_fixed_report(monkeypatch):
    from hf_space import intraday_ui
    prices, metadata = _published_fixture()
    requests, simulations = [], []
    real_run = intraday_ui.run_intraday_comparison

    def fetch():
        requests.append(1)
        value = copy.deepcopy(metadata)
        value["revision"] = ("a" if len(requests) == 1 else "b") * 40
        value["snapshot_id"] = ("a" if len(requests) == 1 else "b") * 64
        return prices.copy(), value

    def run(frame, **kwargs):
        simulations.append(kwargs)
        return real_run(frame, **kwargs)

    monkeypatch.setattr(intraday_ui, "fetch_moomoo_snapshot", fetch)
    monkeypatch.setattr(intraday_ui, "run_intraday_comparison", run)
    app = _app()
    app.radio(key="intraday_source").set_value("moomoo_snapshot").run()
    assert not requests and not simulations
    app.button(key="intraday_snapshot_refresh").click().run()
    assert not app.exception and len(requests) == 1 and not simulations
    assert "intraday_result" not in app.session_state
    app.button(key="intraday_run").click().run(timeout=90)
    assert not app.exception and not app.error
    report = app.session_state["intraday_result"]
    assert report["source"] == "moomoo_snapshot"
    assert report["status"] == "success"
    assert simulations[0]["source"] == "uploaded_csv" and simulations[0]["benchmark"] == "SPY"
    assert report["lineage"]["external_data"]["revision"] == "a" * 40
    assert report["lineage"]["external_data"]["raw_download_available"] is False
    assert len(app.get("download_button")) == 2  # Blank template + research JSON, never raw snapshot CSV.
    saved = app.session_state["intraday_result_json"]
    assert "prices" not in report and "raw_csv" not in report
    for language in ("English", "中文"):
        app.radio(key="hf_language").set_value(language).run()
        assert not app.exception
        assert app.session_state["intraday_result_json"] == saved
    app.number_input(key="intraday_momentum_lookback").set_value(7).run()
    assert len(requests) == 1 and len(simulations) == 1
    app.button(key="intraday_snapshot_refresh").click().run()
    assert not app.exception and len(requests) == 2 and len(simulations) == 1
    assert app.session_state["intraday_snapshot_cache"]["provenance"]["revision"] == "b" * 40
    assert app.session_state["intraday_result"]["lineage"]["external_data"]["revision"] == "a" * 40
    assert app.session_state["intraday_result_json"] == saved
    app.radio(key="intraday_source").set_value("uploaded_csv").run()
    assert app.session_state["intraday_result"]["source"] == "moomoo_snapshot"
    assert any("上次运行使用本机发布" in item.value for item in app.info)
    app.radio(key="hf_study").set_value("ai").run()
    app.radio(key="hf_study").set_value("intraday").run()
    assert not app.exception and app.session_state["intraday_result_json"] == saved
    app.radio(key="intraday_source").set_value("moomoo_snapshot").run()
    app.button(key="intraday_run").click().run(timeout=90)
    assert not app.exception
    assert len(requests) == 2 and len(simulations) == 2
    assert app.session_state["intraday_result"]["lineage"]["external_data"]["revision"] == "b" * 40


def test_snapshot_refresh_failure_keeps_old_report_but_cannot_reuse_old_cache_as_fresh(monkeypatch):
    from hf_space import intraday_ui
    from hf_space.snapshot_source import SnapshotError
    prices, provenance = _published_fixture()
    monkeypatch.setattr(intraday_ui, "fetch_moomoo_snapshot", lambda: (prices, provenance))
    app = _app()
    app.radio(key="intraday_source").set_value("moomoo_snapshot").run()
    app.button(key="intraday_run").click().run(timeout=90)
    saved = app.session_state["intraday_result_json"]
    assert app.session_state["intraday_result"]["source"] == "moomoo_snapshot"

    def denied():
        raise SnapshotError("private-secret-provider-body-must-not-be-rendered", code="ACCESS_DENIED")

    monkeypatch.setattr(intraday_ui, "fetch_moomoo_snapshot", denied)
    app.button(key="intraday_snapshot_refresh").click().run()
    assert not app.exception
    assert app.session_state["intraday_snapshot_cache"] is None
    assert app.session_state["intraday_result_json"] == saved
    assert all("private-secret" not in item.value for item in app.error)
    app.button(key="intraday_run").click().run()
    assert not app.exception
    assert app.session_state["intraday_result"] is None
    assert app.session_state["intraday_result_json"] is None
    assert all("private-secret" not in item.value for item in app.error)
