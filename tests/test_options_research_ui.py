"""UI acceptance for source isolation and explicit fictional calculations."""
import ast
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


SCRIPT = '''
import streamlit as st
from hf_space.options_research_ui import render_options_research_page
st.radio("语言 / Language", ["中文", "English"], key="hf_language", horizontal=True)
st.radio("研究 / Study", ["options", "other"], key="test_study", horizontal=True)
def tr(zh, en):
    return en if st.session_state["hf_language"] == "English" else zh
if st.session_state["test_study"] == "options":
    render_options_research_page(tr)
else:
    st.title("Other research")
'''


def _app():
    result = AppTest.from_string(SCRIPT, default_timeout=50).run()
    assert not result.exception, [error.value for error in result.exception]
    return result


def _text(app):
    return " ".join(item.value for collection in
                    (app.caption, app.info, app.warning, app.error, app.markdown) for item in collection)


def test_first_render_only_static_audit_and_no_auto_calculation(monkeypatch):
    from hf_space import options_research_ui as ui

    def forbidden(**kwargs):
        pytest.fail("Calculations require an explicit teaching action")

    monkeypatch.setattr(ui, "run_demo_gex", forbidden)
    monkeypatch.setattr(ui, "run_demo_max_pain", forbidden)
    app = _app()
    assert len(app.tabs) == 5
    assert not app.error and len(app.get("plotly_chart")) == 0
    assert len(app.get("download_button")) == 0
    assert len(app.get("file_uploader")) == 0
    assert "NOT_ESTIMABLE" in _text(app) and "NOT_IDENTIFIABLE" in _text(app)
    assert len(app.latex) >= 5
    assert [row["contracts"] for row in ui.AUDIT["static_chains"]] == [438, 514]
    for row in ui.AUDIT["static_chains"]:
        assert row["source_updated_at"] is None
        assert row["oi_effective_date"] is None and row["oi_published_at"] is None
        assert row["available_at"] == row["retrieved_at"]
        assert len(row["sha256"]) == 64
    table = app.dataframe[0].value
    assert set(table["供方更新时间"]) == {"未知／未披露"}
    assert set(table["OI有效日"]) == {"未知／未披露"}
    assert "D:\\" not in _text(app) and "hf_" not in _text(app)


def test_page_has_no_network_private_file_or_broker_imports():
    from hf_space import options_research_ui as ui
    tree = ast.parse(Path(ui.__file__).read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(name.name for name in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith(("requests", "urllib", "socket", "subprocess", "os", "pathlib", "sqlite3",
                                   "hf_space.snapshot_source", "execution_lab")) for name in imports)


def test_max_pain_calls_real_core_and_keeps_entire_flat_interval():
    app = _app()
    app.button(key="options_mp_run").click().run()
    assert not app.exception and not app.error
    report = app.session_state["options_mp_report"]
    assert report["underlying"] == "TOY" and report["source_kind"] == "synthetic_demo"
    assert float(report["result"]["minimizer"]["lower"]) == 100.
    assert float(report["result"]["minimizer"]["upper"]) == 110.
    assert float(report["result"]["minimum_loss"]) == 10000.
    assert report["claims"]["market_observation"] is False
    assert json.loads(app.session_state["options_mp_json"]) == report
    assert len(app.get("plotly_chart")) == 1
    assert len(app.get("download_button")) == 1


def test_spot_changes_distance_inputs_but_not_fixed_oi_max_pain():
    app = _app()
    app.button(key="options_mp_run").click().run()
    first = app.session_state["options_mp_report"]
    before = app.session_state["options_mp_json"]
    app.number_input(key="options_mp_spot").set_value(125.).run()
    assert app.session_state["options_mp_json"] == before
    app.button(key="options_mp_run").click().run()
    second = app.session_state["options_mp_report"]
    assert first["result"]["minimizer"] == second["result"]["minimizer"]
    assert first["result"]["minimum_loss"] == second["result"]["minimum_loss"]
    assert second["inputs"]["spot"] == 125.
    assert float(first["distance_to_minimizer"]) == 0.
    assert float(second["distance_to_minimizer"]) == 15.


def test_language_navigation_and_unsubmitted_inputs_preserve_calculation():
    app = _app()
    app.button(key="options_mp_run").click().run()
    saved = app.session_state["options_mp_json"]
    app.number_input(key="options_mp_call_oi").set_value(23).run()
    for lang in ("English", "中文"):
        app.radio(key="hf_language").set_value(lang).run()
        assert not app.exception and app.session_state["options_mp_json"] == saved
        assert app.number_input(key="options_mp_call_oi").value == 23
    app.radio(key="test_study").set_value("other").run()
    app.radio(key="test_study").set_value("options").run()
    assert not app.exception and app.session_state["options_mp_json"] == saved
    assert app.number_input(key="options_mp_call_oi").value == 23
    assert app.session_state["options_mp_report"]["inputs"]["call_oi"] == 10


def test_gex_explicit_run_uses_toy_core_and_never_produces_fake_performance():
    app = _app()
    app.button(key="options_gex_run").click().run()
    assert not app.exception and not app.error
    report = app.session_state["options_gex_report"]
    models = report["result"]["models"]
    assert set(models) == {"fixed_call_put", "prior_inventory", "unsigned_concentration",
                           "all_dealer_long", "all_dealer_short"}
    assert len(models["fixed_call_put"]["curve"]) == 61
    assert models["all_dealer_long"]["current_gex"] > 0
    assert models["all_dealer_short"]["current_gex"] < 0
    assert report["underlying"] == "TOY" and report["source_kind"] == "synthetic_demo"
    assert report["claims"]["confidence_interval"] is False
    assert report["claims"]["orders_submitted"] is False
    assert not {"equity", "sharpe", "win_rate", "accuracy"} & set(report["result"])
    assert json.loads(app.session_state["options_gex_json"]) == report
    assert len(app.get("plotly_chart")) == 1
    assert "NOT_ESTIMABLE" in _text(app)


def test_gex_inputs_language_and_reference_level_do_not_auto_rerun():
    app = _app()
    app.button(key="options_gex_run").click().run()
    saved = app.session_state["options_gex_json"]
    app.number_input(key="options_gex_reference_level").set_value(95.).run()
    app.slider(key="options_gex_pc").set_value(.4).run()
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception
    assert app.session_state["options_gex_json"] == saved
    assert app.slider(key="options_gex_pc").value == .4
    assert "level below spot" in _text(app)
    assert app.session_state["options_gex_report"]["inputs"]["prior_long_call"] == .6


def test_failures_are_redacted_and_do_not_turn_into_market_results(monkeypatch):
    from hf_space import options_research_ui as ui

    def fail(**kwargs):
        raise ValueError("SECRET_OR_RAW_PROVIDER_BODY")

    monkeypatch.setattr(ui, "run_demo_gex", fail)
    app = _app()
    app.button(key="options_gex_run").click().run()
    assert not app.exception and app.error
    assert len(app.get("plotly_chart")) == 0
    assert "SECRET_OR_RAW" not in _text(app)
    assert "NOT_ESTIMABLE" in _text(app)


def test_zero_oi_teaching_does_not_claim_a_unique_target():
    app = _app()
    app.number_input(key="options_mp_call_oi").set_value(0).run()
    app.number_input(key="options_mp_put_oi").set_value(0).run()
    app.button(key="options_mp_run").click().run()
    assert not app.exception and not app.error
    core = app.session_state["options_mp_report"]["result"]
    assert core["status"] != "success"
    assert core.get("minimizer") is None


def test_inventory_methods_require_action_and_keep_prior_uncertainty():
    app = _app()
    assert "q0" not in app.session_state
    app.button(key="options_inventory_run").click().run()
    assert not app.exception and not app.error
    report = app.session_state["options_inventory_report"]
    assert report["source_kind"] == "synthetic_demo"
    assert report["result"]["q"] is None
    saved = app.session_state["options_inventory_json"]
    app.number_input(key="options_inventory_delta").set_value(100.).run()
    app.radio(key="hf_language").set_value("English").run()
    assert not app.exception and app.session_state["options_inventory_json"] == saved
    assert "local computer" in _text(app)
    assert not app.get("file_uploader")


def test_inventory_reversed_bounds_fail_without_losing_last_good_report():
    app = _app()
    app.button(key="options_inventory_run").click().run()
    saved = app.session_state["options_inventory_json"]
    app.number_input(key="options_inventory_q0_low").set_value(300.).run()
    app.button(key="options_inventory_run").click().run()
    assert not app.exception and app.error
    assert app.session_state["options_inventory_json"] == saved
