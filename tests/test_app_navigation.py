"""Global navigation remains visible outside the collapsible parameter sidebar."""
from pathlib import Path
from types import SimpleNamespace
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_manual_language_is_restored_on_a_new_session_without_retraining(monkeypatch):
    browser = {"language": "zh"}
    writes = []

    def register_preference(name, **kwargs):
        def mount(**arguments):
            selected = arguments["data"]["save"]
            if selected in ("en", "zh"):
                browser["language"] = selected
                writes.append(selected)
            return SimpleNamespace(language=browser["language"])
        return mount

    monkeypatch.setattr(st.components.v2, "component", register_preference)
    first = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not first.exception
    assert first.radio(key="hf_language").value == "中文"
    assert writes == []
    first.radio(key="hf_language").set_value("English").run()
    assert not first.exception
    assert first.title[0].value == "Alpha Trading Research Lab"
    assert browser["language"] == "en"
    second = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not second.exception
    assert second.radio(key="hf_language").value == "English"
    second.radio(key="hf_language").set_value("中文").run()
    assert browser["language"] == "zh"
    third = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not third.exception
    assert third.radio(key="hf_language").value == "中文"
    for app in (first, second, third):
        assert "hf_result" not in app.session_state


def test_invalid_or_delayed_browser_preference_cannot_override_a_manual_choice(monkeypatch):
    stored = {"language": "invalid"}
    seen = []

    def register_preference(name, **kwargs):
        def mount(**arguments):
            seen.append(arguments["data"]["save"])
            return SimpleNamespace(language=stored["language"])
        return mount

    monkeypatch.setattr(st.components.v2, "component", register_preference)
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.radio(key="hf_language").value == "English"
    app.radio(key="hf_language").set_value("中文").run()
    stored["language"] = "en"
    app.run()
    assert not app.exception
    assert app.radio(key="hf_language").value == "中文"
    assert seen[-1] == "zh"
    assert "hf_result" not in app.session_state


def test_language_and_study_navigation_are_in_main_and_preserve_page():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    assert not any(item.key in {"hf_language", "hf_study"} for item in app.sidebar.radio)
    assert {"hf_language", "hf_study"} <= {item.key for item in app.main.radio}
    assert app.radio(key="hf_language").value == "English"
    assert app.title[0].value == "Alpha Trading Research Lab"
    assert len(app.radio(key="hf_study").options) == 7
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
    assert any(item.label == "Advanced Settings" for item in app.sidebar.expander)


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


def test_premarket_navigation_is_lazy_and_language_keeps_the_route(monkeypatch):
    from hf_space import premarket_ui
    def forbidden():
        raise AssertionError("Navigation must not load or calculate the research reference")
    monkeypatch.setattr(premarket_ui, "load_reference", forbidden)
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    app.radio(key="hf_study").set_value("premarket").run()
    assert not app.exception
    assert app.title[0].value == "Premarket Gains & Opening Downside"
    assert "premarket_result" not in app.session_state
    app.radio(key="hf_language").set_value("中文").run()
    assert not app.exception and app.radio(key="hf_study").value == "premarket"
    assert app.title[0].value == "盘前涨幅与开盘半小时下探"
    assert "premarket_result" not in app.session_state
    assert app.number_input(key="premarket_threshold").value == 2.5


def test_standalone_app_and_hugging_face_project_have_separate_entries():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    links = {item.proto.label: item.proto.url for item in app.get("link_button")}
    assert links["Launch Research Lab"] == "https://alphalab.levyquant.ai/"
    assert links["Hugging Face project"] == "https://huggingface.co/spaces/Rexymiao/alpha-trading-lab"
    assert links["Lévy Quant"] == "https://levyquant.ai/"
    app.radio(key="hf_language").set_value("中文").run()
    assert not app.exception
    links = {item.proto.label: item.proto.url for item in app.get("link_button")}
    assert links["进入研究平台"] == "https://alphalab.levyquant.ai/"
    assert links["Hugging Face项目页"] == "https://huggingface.co/spaces/Rexymiao/alpha-trading-lab"
    assert links["Lévy Quant 主站"] == "https://levyquant.ai/"


def test_day_night_toggle_is_client_side_and_bilingual():
    app = AppTest.from_file(str(ROOT / "hf_space/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    bodies = [item.proto.body for item in app.get("html")]
    toggle = next(body for body in bodies if "alpha-theme-toggle" in body)
    assert "Switch to night mode" in toggle and "Switch to day mode" in toggle
    assert "stMainMenuItem-theme-" in toggle
    assert "location.reload" not in toggle
    assert "alphaDefaultTheme-v1" in toggle  # one-time default to day; explicit choices kept
    assert "setItem(base" not in toggle and "setItem(k" not in toggle  # never writes Streamlit's key
    app.radio(key="hf_language").set_value("中文").run()
    toggle = next(item.proto.body for item in app.get("html") if "alpha-theme-toggle" in item.proto.body)
    assert "切换到夜间模式" in toggle and "切换到日间模式" in toggle
