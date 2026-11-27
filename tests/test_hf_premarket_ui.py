"""Cloud UI checks against the validated public derived research reference."""
import json

from streamlit.testing.v1 import AppTest


SCRIPT = '''
import streamlit as st
from hf_space.premarket_ui import render_premarket_page
st.radio("Language / 语言", ["English", "中文"], key="hf_language")
st.radio("Study", ["premarket", "other"], key="test_study")
def tr(zh, en):
    return zh if st.session_state["hf_language"] == "中文" else en
if st.session_state["test_study"] == "premarket":
    render_premarket_page(tr)
else:
    st.title("Other research")
'''


def app():
    result = AppTest.from_string(SCRIPT, default_timeout=30).run()
    assert not result.exception, [x.value for x in result.exception]
    return result


def test_default_three_etfs_and_explicit_run_without_raw_download(monkeypatch):
    from hf_space import premarket_ui
    loads, runs = [], []
    original_load, original_run = premarket_ui.load_reference, premarket_ui.analyze_reference
    def load():
        loads.append(1)
        return original_load()
    def analyze(reference, **kwargs):
        runs.append(kwargs)
        return original_run(reference, **kwargs)
    monkeypatch.setattr(premarket_ui, "load_reference", load)
    monkeypatch.setattr(premarket_ui, "analyze_reference", analyze)
    current = app()
    assert current.multiselect(key="premarket_symbols").value == ["QQQ", "SPY", "DIA"]
    assert current.number_input(key="premarket_threshold").value == 2.5
    assert current.selectbox(key="premarket_definition").value == "fixed_0925"
    assert not loads and not runs and "premarket_result" not in current.session_state
    current.button(key="premarket_run").click().run()
    assert not current.exception and len(loads) == 1 and len(runs) == 1
    report = current.session_state["premarket_result"]
    assert {s: x["events"]["n"] for s, x in report["results"].items()} == {"QQQ": 2, "SPY": 2, "DIA": 2}
    assert report["results"]["DIA"]["eligible_days"] == 236
    assert json.loads(current.session_state["premarket_result_json"]) == report
    assert len(current.get("download_button")) == 1
    assert len(current.get("plotly_chart")) == 1
    assert "kl_list" not in current.session_state["premarket_result_json"]


def test_custom_threshold_edits_language_and_navigation_preserve_last_run(monkeypatch):
    from hf_space import premarket_ui
    calls = []
    original = premarket_ui.analyze_reference
    def analyze(reference, **kwargs):
        calls.append(kwargs)
        return original(reference, **kwargs)
    monkeypatch.setattr(premarket_ui, "analyze_reference", analyze)
    current = app()
    current.button(key="premarket_run").click().run()
    saved = current.session_state["premarket_result_json"]
    current.number_input(key="premarket_threshold").set_value(1.25)
    assert not current.exception
    assert current.session_state["premarket_result_json"] == saved and len(calls) == 1
    assert current.session_state["premarket_result_context"]["threshold_pct"] == "2.5"
    current.button(key="premarket_run").click().run()
    assert not current.exception and len(calls) == 2
    result = current.session_state["premarket_result"]
    assert {s: x["events"]["n"] for s, x in result["results"].items()} == {"QQQ": 18, "SPY": 4, "DIA": 5}
    saved = current.session_state["premarket_result_json"]
    current.radio(key="hf_language").set_value("中文").run()
    assert not current.exception and current.number_input(key="premarket_threshold").value == 1.25
    assert current.title[0].value == "盘前涨幅与开盘半小时下探"
    assert current.session_state["premarket_result_json"] == saved and len(calls) == 2
    current.radio(key="test_study").set_value("other").run()
    current.radio(key="test_study").set_value("premarket").run()
    assert not current.exception
    assert current.number_input(key="premarket_threshold").value == 1.25
    assert current.session_state["premarket_result_json"] == saved and len(calls) == 2


def test_etf_selection_dia_no_events_and_unavailable_window_are_distinct():
    current = app()
    current.multiselect(key="premarket_symbols").set_value(["DIA"])
    current.number_input(key="premarket_threshold").set_value(3.)
    current.button(key="premarket_run").click().run()
    assert not current.exception
    report = current.session_state["premarket_result"]
    assert list(report["results"]) == ["DIA"]
    assert report["results"]["DIA"]["events"]["n"] == 0
    assert report["results"]["DIA"]["eligible_days"] == 236
    assert any("no qualifying events" in x.value for x in current.info)
    assert not current.get("plotly_chart")
    current.selectbox(key="premarket_definition").set_value("ever_before_open")
    current.number_input(key="premarket_threshold").set_value(2.5)
    current.button(key="premarket_run").click().run()
    assert not current.exception
    dia = current.session_state["premarket_result"]["results"]["DIA"]
    assert dia["eligible_days"] == 0 and dia["events"]["n"] == 0
    assert dia["events"]["max"] is None
    assert len(dia["partial_observed_hit_dates"]) == 3
    assert any("no eligible observations" in x.value for x in current.info)


def test_empty_etf_selection_and_load_failure_preserve_success(monkeypatch):
    from hf_space import premarket_ui
    current = app()
    current.button(key="premarket_run").click().run()
    saved = current.session_state["premarket_result_json"]
    current.multiselect(key="premarket_symbols").set_value([])
    current.button(key="premarket_run").click().run()
    assert not current.exception and current.error
    assert current.session_state["premarket_result_json"] == saved
    current.multiselect(key="premarket_symbols").set_value(["QQQ"])
    def fail():
        raise ValueError("PRIVATE_ERROR_MUST_NOT_RENDER")
    monkeypatch.setattr(premarket_ui, "load_reference", fail)
    current.button(key="premarket_run").click().run()
    assert not current.exception and current.error
    assert current.session_state["premarket_result_json"] == saved
    assert all("PRIVATE_ERROR" not in x.value for x in current.error)
