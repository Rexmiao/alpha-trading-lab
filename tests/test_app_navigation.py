"""Global navigation remains visible outside the collapsible parameter sidebar."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_language_and_study_navigation_are_in_main_and_preserve_page():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    assert not any(item.key in {"hf_language", "hf_study"} for item in app.sidebar.radio)
    assert {"hf_language", "hf_study"} <= {item.key for item in app.main.radio}
    assert app.radio(key="hf_language").value == "English"
    assert app.title[0].value == "Alpha Trading Research Lab"
    assert len(app.radio(key="hf_study").options) == 6
    app.radio(key="hf_language").set_value("中文").run()
    assert "支撑与阻力策略" in app.radio(key="hf_study").options
    app.radio(key="hf_study").set_value("beta").run()
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception
    assert app.radio(key="hf_study").value == "beta"
    assert app.title[0].value == "Beta Measurements & Strategy Comparison"
    assert not any(item.key in {"hf_language", "hf_study"} for item in app.sidebar.radio)
    app.radio(key="hf_study").set_value("ai").run()
    assert app.radio(key="hf_language").value == "English"
    assert "hf_result" not in app.session_state
    assert any(item.label == "Advanced settings" for item in app.sidebar.expander)


def test_sr_real_navigation_is_lazy_and_keeps_language_outside_sidebar(monkeypatch):
    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("Navigation and language changes must not fetch private prices")
    monkeypatch.setattr("hf_space.support_resistance_ui.fetch_moomoo_snapshot", forbidden_fetch)
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    app.radio(key="hf_study").set_value("sr").run()
    assert not app.exception
    assert app.radio(key="sr_source").value == "moomoo_snapshot"
    assert "sr_result" not in app.session_state
    assert not app.get("plotly_chart")
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception
    assert app.radio(key="hf_study").value == "sr"
    assert not any(item.key in {"hf_language", "hf_study"} for item in app.sidebar.radio)
    app.radio(key="sr_source").set_value("uploaded_csv").run()
    assert app.button(key="sr_run").disabled
    app.radio(key="hf_study").set_value("beta").run()
    app.radio(key="hf_study").set_value("sr").run()
    assert not app.exception
    assert app.radio(key="sr_source").value == "uploaded_csv"
    assert app.radio(key="hf_language").value == "English"


def test_options_research_route_starts_with_audit_without_auto_calculation():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    app.radio(key="hf_study").set_value("options").run()
    assert not app.exception
    assert not app.get("plotly_chart")
    assert app.radio(key="hf_language").value == "English"
    assert any("Options Structure" in item.value for item in app.title)
    app.radio(key="hf_language").set_value("中文").run()
    assert any("期权" in item.value for item in app.title)
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception
    assert app.radio(key="hf_study").value == "options"
    assert not any(item.key in {"hf_language", "hf_study"} for item in app.sidebar.radio)


def test_initial_screen_and_options_navigation_do_not_load_training_or_express(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def without_training(name, *args, **kwargs):
        if name in {"hf_space.engine", "hf_space.history", "plotly.express"}:
            raise AssertionError("Unused training and chart dependencies must stay deferred")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_training)
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    app.radio(key="hf_study").set_value("options").run()
    assert not app.exception
    assert not app.get("plotly_chart")
