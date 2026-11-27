"""Offline UI fixtures only; no real private-source or strategy acceptance claim."""
import copy
import json

import pandas as pd
from streamlit.testing.v1 import AppTest


SCRIPT = '''
import streamlit as st
from hf_space.beta_ui import render_beta_page
st.radio("语言 / Language", ["中文", "English"], key="hf_language")
st.radio("研究 / Study", ["beta", "other"], key="test_study")
def tr(zh, en):
    return en if st.session_state["hf_language"] == "English" else zh
if st.session_state["test_study"] == "beta":
    render_beta_page(tr)
else:
    st.title("Other research")
'''


def _fixture():
    prices = pd.DataFrame({"date": ["2020-01-02"], "symbol": ["SPY"],
                           "open": [100.], "high": [101.], "low": [99.], "close": [100.5], "volume": [1000.]})
    provenance = {"source": "moomoo_daily_snapshot", "provider": "moomoo_private_daily_snapshot",
                  "dataset": "Rexymiao/alpha-trading-snapshots", "revision": "a" * 40,
                  "snapshot_id": "a" * 64, "as_of": "2020-01-02T21:00:00Z",
                  "csv_rows": 1, "raw_download_available": False}
    return prices, provenance


def _result(status="success"):
    ids = ("high_beta", "low_beta", "equal_weight", "spy_80", "spy_100")
    result = {"source": "moomoo_daily_snapshot", "status": status,
              "metrics": [{"strategy": name, "status": "success", "total_return": .02,
                           "annual_return": .03, "annual_vol": .1, "sharpe": .3,
                           "max_drawdown": -.01, "realized_beta": .8, "realized_r_squared": .6,
                           "total_costs": 120., "trade_count": 3, "turnover": 1.2} for name in ids],
              "equity": [{"strategy": name, "date": day, "equity": equity,
                          "drawdown": drawdown, "predicted_beta": .8} for name in ids
                         for day, equity, drawdown in (("2020-01-02", 100000., 0.), ("2020-01-03", 99000., -.01))],
              "estimates": [{"symbol": "TEST", "date": "2020-01-03", "beta": 1.2,
                             "correlation": .6, "r_squared": .36, "standard_error": .2,
                             "nobs": 126, "annual_vol": .3, "residual_vol": .2, "status": "ok"}],
              "beta_history": [], "weights": [{"strategy": "high_beta", "symbol": "TEST", "weight": .2,
                                                "quantity": 100, "kind": "asset", "as_of": "2020-01-03"}],
              "latest_targets": [{"strategy": "high_beta", "symbol": "TEST", "weight": .2,
                                  "as_of": "2020-01-02"}],
              "rebalances": [], "trades": [], "coverage": {"eligible_stocks": 20},
              "config": {"return_basis": "raw_return_market_model"}, "lineage": {}, "warnings": [],
              "raw_csv": "MUST_NOT_BE_DOWNLOADED", "prices": [{"close": 100.5}]}
    if status != "success":
        result.update(metrics=[], equity=[], estimates=[], weights=[], latest_targets=[])
    return result


def _app():
    app = AppTest.from_string(SCRIPT, default_timeout=30).run()
    assert not app.exception, [item.value for item in app.exception]
    return app


def test_default_snapshot_requires_explicit_action_and_result_is_allowlisted(monkeypatch):
    from hf_space import beta_ui
    fetched, runs = [], []

    def fetch():
        fetched.append(1)
        return _fixture()

    def run(prices, **params):
        runs.append(params)
        return _result()

    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", fetch)
    monkeypatch.setattr(beta_ui, "run_beta_comparison", run)
    app = _app()
    assert app.radio(key="beta_source").value == "moomoo_daily_snapshot"
    assert not fetched and not runs and "beta_result" not in app.session_state
    app.button(key="beta_run").click().run()
    assert not app.exception and not app.error
    assert fetched == [1] and len(runs) == 1
    report = app.session_state["beta_result"]
    assert len(report["metrics"]) == 5 and report["source"] == "moomoo_daily_snapshot"
    assert report["lineage"]["external_data"]["revision"] == "a" * 40
    assert "raw_csv" not in report and "prices" not in report
    assert json.loads(app.session_state["beta_result_json"]) == report
    assert len(app.get("download_button")) == 2  # Blank template and safe research JSON only.
    assert len(app.get("plotly_chart")) == 4
    assert runs[0] == app.session_state["beta_result_context"]
    assert runs[0]["beta_window"] == 126 and runs[0]["test_sessions"] == 252


def test_language_page_parameters_and_refresh_keep_previous_executed_result(monkeypatch):
    from hf_space import beta_ui
    fetched, runs = [], []

    def fetch():
        fetched.append(1)
        prices, provenance = _fixture()
        provenance["revision"] = ("a" if len(fetched) == 1 else "b") * 40
        provenance["snapshot_id"] = ("a" if len(fetched) == 1 else "b") * 64
        return prices, provenance

    def run(prices, **params):
        runs.append(params)
        return _result()

    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", fetch)
    monkeypatch.setattr(beta_ui, "run_beta_comparison", run)
    app = _app()
    app.button(key="beta_snapshot_refresh").click().run()
    assert len(fetched) == 1 and not runs
    app.button(key="beta_run").click().run()
    saved = app.session_state["beta_result_json"]
    for language in ("English", "中文"):
        app.radio(key="hf_language").set_value(language).run()
        assert not app.exception
        assert app.session_state["beta_result_json"] == saved
        assert app.radio(key="beta_source").value == "moomoo_daily_snapshot"
    app.selectbox(key="beta_window").set_value(252).run()
    app.number_input(key="beta_test_sessions").set_value(126).run()
    app.slider(key="beta_cost").set_value(12).run()
    assert app.session_state["beta_result_context"]["beta_window"] == 126
    assert app.session_state["beta_result_json"] == saved and len(runs) == 1
    app.radio(key="test_study").set_value("other").run()
    app.radio(key="test_study").set_value("beta").run()
    assert not app.exception and app.selectbox(key="beta_window").value == 252
    assert app.session_state["beta_result_json"] == saved
    app.button(key="beta_snapshot_refresh").click().run()
    assert len(fetched) == 2 and len(runs) == 1
    assert app.session_state["beta_result_json"] == saved
    assert app.session_state["beta_snapshot_cache"]["provenance"]["revision"] == "b" * 40
    assert app.session_state["beta_result"]["lineage"]["external_data"]["revision"] == "a" * 40
    assert any("尚未用于" in item.value for item in app.caption)
    app.button(key="beta_run").click().run()
    assert not app.exception and len(fetched) == 2 and len(runs) == 2
    assert app.session_state["beta_result_context"]["beta_window"] == 252
    assert app.session_state["beta_result"]["lineage"]["external_data"]["revision"] == "b" * 40


def test_snapshot_failure_is_safe_and_has_no_fallback(monkeypatch):
    from hf_space import beta_ui

    class Failure(ValueError):
        code = "NOT_CONFIGURED"

    def fail():
        raise Failure("PRIVATE_TOKEN_AND_PROVIDER_BODY")

    def forbidden(*args, **kwargs):
        raise AssertionError("No CSV or substitute strategy on private-source failure")

    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", fail)
    monkeypatch.setattr(beta_ui, "run_beta_comparison", forbidden)
    monkeypatch.setattr(beta_ui, "parse_beta_csv", forbidden)
    app = _app()
    app.button(key="beta_run").click().run()
    assert not app.exception and app.session_state["beta_result"] is None
    assert app.session_state["beta_error"] == "NOT_CONFIGURED"
    text = " ".join(item.value for collection in (app.info, app.error, app.caption) for item in collection)
    assert "PRIVATE_TOKEN" not in text and "尚未连接" in text
    assert len(app.get("plotly_chart")) == 0
    app.radio(key="hf_language").set_value("English").run()
    assert any("not connected yet" in item.value for item in app.info)


def test_csv_is_optional_guest_route_without_snapshot_calls(monkeypatch):
    from hf_space import beta_ui
    parsed, runs = [], []

    def forbidden():
        raise AssertionError("CSV visitors must not load private snapshots")

    def parse(payload, **kwargs):
        parsed.append((payload, kwargs))
        return _fixture()[0]

    def run(prices, **params):
        runs.append(params)
        return _result()

    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", forbidden)
    monkeypatch.setattr(beta_ui, "parse_beta_csv", parse)
    monkeypatch.setattr(beta_ui, "run_beta_comparison", run)
    app = _app()
    app.radio(key="beta_source").set_value("uploaded_csv").run()
    assert app.button(key="beta_run").disabled and not parsed and not runs
    app.session_state["beta_upload_bytes"] = b"OFFLINE_TEST_CSV_ONLY"
    app.session_state["beta_upload_name"] = "offline.csv"
    app.run()
    app.button(key="beta_run").click().run()
    assert not app.exception and not app.error
    assert parsed == [(b"OFFLINE_TEST_CSV_ONLY", {"benchmark": "SPY"})]
    assert runs[0]["source"] == "uploaded_csv"
    assert app.session_state["beta_result"]["source"] == "uploaded_csv"
    assert "external_data" not in app.session_state["beta_result"]["lineage"]
    saved = app.session_state["beta_result_json"]
    app.radio(key="hf_language").set_value("English").run()
    assert app.session_state["beta_result_json"] == saved
    assert app.session_state["beta_upload_bytes"] == b"OFFLINE_TEST_CSV_ONLY"


def test_insufficient_history_does_not_show_fake_curves(monkeypatch):
    from hf_space import beta_ui
    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", _fixture)
    monkeypatch.setattr(beta_ui, "run_beta_comparison", lambda *a, **k: _result("insufficient_history"))
    app = _app()
    app.button(key="beta_run").click().run()
    assert not app.exception and not app.error
    assert app.session_state["beta_result"]["status"] == "insufficient_history"
    assert not app.session_state["beta_result"]["equity"]
    assert len(app.get("plotly_chart")) == 0


def test_failed_rerun_clears_prior_result_and_redacts_exception(monkeypatch):
    from hf_space import beta_ui
    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", _fixture)
    monkeypatch.setattr(beta_ui, "run_beta_comparison", lambda *a, **k: _result())
    app = _app()
    app.button(key="beta_run").click().run()
    assert app.session_state["beta_result"]

    def fail(*args, **kwargs):
        raise ValueError("PRIVATE_PRICE_ROW_AND_TOKEN")

    monkeypatch.setattr(beta_ui, "run_beta_comparison", fail)
    app.button(key="beta_run").click().run()
    assert not app.exception and app.error
    assert app.session_state["beta_result"] is None
    assert app.session_state["beta_result_json"] is None
    assert app.session_state["beta_result_context"] is None
    assert "PRIVATE_PRICE" not in " ".join(item.value for item in app.error)


def test_page_renders_real_beta_engine_schema_without_training_or_network(monkeypatch):
    """Generated offline prices exercise the real computational/UI boundary."""
    import exchange_calendars as xcals
    import numpy as np
    from hf_space import beta_ui

    dates = xcals.get_calendar("XNYS").sessions_in_range("2023-01-03", "2023-10-31")[:160].tz_localize(None)
    rng = np.random.default_rng(681)
    market = rng.normal(.0002, .009, len(dates))
    rows = []
    for index in range(21):
        symbol = "SPY" if index == 20 else f"T{index:02d}"
        returns = market if symbol == "SPY" else (.4 + index * .07) * market + rng.normal(0., .003, len(dates))
        closes = 100 * np.cumprod(1 + returns)
        for day, close in zip(dates, closes):
            rows.append({"date": day, "symbol": symbol, "open": close * .999,
                         "high": close * 1.003, "low": close * .996, "close": close, "volume": 100000.})
    prices = pd.DataFrame(rows)
    provenance = _fixture()[1]

    def forbidden(*args, **kwargs):
        raise AssertionError("Beta comparison must not train models")

    monkeypatch.setattr("hf_space.engine.fit_predict_models", forbidden)
    monkeypatch.setattr(beta_ui, "fetch_moomoo_daily_snapshot", lambda: (prices, provenance))
    app = _app()
    app.number_input(key="beta_test_sessions").set_value(20).run()
    app.button(key="beta_run").click().run(timeout=90)
    assert not app.exception, [item.value for item in app.exception]
    assert not app.error, [item.value for item in app.error]
    report = app.session_state["beta_result"]
    assert report["status"] == "success" and len(report["metrics"]) == 5
    assert len(report["equity"]) == len(report["drawdown"]) == 100
    assert len(report["estimates"]) == 20
    assert report["latest_targets"] and report["weights"]
    assert all(item["status"] == "success" for item in report["metrics"])
    assert report["lineage"]["orders_submitted"] is False
    assert len(app.get("plotly_chart")) == 4
    saved = app.session_state["beta_result_json"]
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception and app.session_state["beta_result_json"] == saved
