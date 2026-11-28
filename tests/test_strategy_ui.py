"""Exercise the real rule page and explicit-run/session boundaries."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def _run_button(app):
    # The header also has buttons (Training Guide), so find the form submit by label.
    return next(b for b in app.button if b.label in ("运行四种策略", "Run four strategies"))


def test_rule_page_runs_four_strategies_without_training_and_keeps_result(monkeypatch):
    def forbidden_training(*args, **kwargs):
        raise AssertionError("The rule page must not train AI models")

    monkeypatch.setattr("hf_space.engine.fit_predict_models", forbidden_training)
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=60).run()
    assert not app.exception
    app.radio(key="hf_study").set_value("strategies").run()
    assert not app.exception
    assert "strategy_result" not in app.session_state
    app.radio(key="strategy_source").set_value("synthetic").run()
    assert not app.exception
    _run_button(app).click().run(timeout=60)
    assert not app.exception, [item.value for item in app.exception]
    report = app.session_state["strategy_result"]
    assert report["source"] == "synthetic"
    assert len(report["metrics"]) == 4
    assert all(row["status"] == "success" for row in report["metrics"])
    assert len(app.dataframe) >= 3
    saved = app.session_state["strategy_result_json"]
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception
    assert app.title[0].value == "Momentum & Trend Lab"
    assert app.session_state["strategy_result_json"] == saved
    app.radio(key="hf_language").set_value("中文").run()
    assert not app.exception
    assert app.title[0].value == "动量与趋势实验室"
    assert app.radio(key="hf_study").value == "strategies"
    assert app.radio(key="strategy_source").value == "synthetic"
    assert app.session_state["strategy_result_json"] == saved
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception
    assert app.radio(key="hf_study").value == "strategies"
    app.number_input(key="strategy_lookback").set_value(80).run()
    assert app.session_state["strategy_result_context"]["lookback"] == 60
    assert app.session_state["strategy_result_json"] == saved
    app.radio(key="hf_study").set_value("ai").run()
    assert not app.exception
    assert "hf_result" not in app.session_state
    app.radio(key="hf_study").set_value("strategies").run()
    assert app.session_state["strategy_result_json"] == saved


def test_missing_csv_shows_error_without_running_or_exposing_a_result():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    app.radio(key="hf_study").set_value("strategies").run()
    _run_button(app).click().run()
    assert not app.exception
    assert app.session_state["strategy_result"] is None
    assert any("CSV" in item.value for item in app.error)
