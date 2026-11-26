"""Cloud adapter contracts, using only fictional prices and no local snapshots."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import numpy as np
import pandas as pd
import pytest

from hf_space import engine


@pytest.fixture(scope="module")
def prices():
    return engine.make_synthetic_prices(seed=42)


def csv_bytes(frame):
    return frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8")


def test_synthetic_prices_are_repeatable_and_fictional(prices):
    pd.testing.assert_frame_equal(prices, engine.make_synthetic_prices(seed=42))
    assert set(prices.symbol) == {"BENCH", "TOY1", "TOY2", "TOY3", "TOY4", "TOY5", "TOY6"}
    parsed = engine.parse_csv(csv_bytes(prices), benchmark="BENCH")
    pd.testing.assert_frame_equal(parsed, prices)


@pytest.mark.parametrize("problem", ["duplicate", "ohlc", "future", "missing_benchmark", "nan"])
def test_invalid_uploads_fail_before_training(prices, problem):
    frame = prices.copy()
    if problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif problem == "ohlc":
        frame.loc[0, "high"] = 0.01
    elif problem == "future":
        frame.loc[0, "date"] = pd.Timestamp("2099-01-02")
    elif problem == "missing_benchmark":
        frame = frame[frame.symbol.ne("BENCH")]
    else:
        frame.loc[0, "volume"] = np.nan
    with pytest.raises(ValueError):
        engine.parse_csv(csv_bytes(frame), benchmark="BENCH")


def test_uploaded_input_is_bounded_bytes_not_a_url_or_pickle():
    with pytest.raises(TypeError):
        engine.parse_csv("https://example.com/prices.csv")
    with pytest.raises(ValueError, match="3 MiB"):
        engine.parse_csv(b"x" * (3 * 1024 * 1024 + 1))


def test_full_simulation_has_real_estimators_and_no_working_directory_writes(prices, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = engine.run_simulation(prices, benchmark="BENCH", source="synthetic")
    assert list(tmp_path.iterdir()) == []
    json.dumps(report, allow_nan=False)
    assert report["source"] == "synthetic"
    assert report["lineage"]["data"]["educational_only"] is True
    assert all(v["status"] == "success" for v in report["lineage"]["model_status"].values())
    assert {r["model"] for r in report["metrics"]} == set(engine.MODEL_NAMES)
    split = report["lineage"]["split"]
    assert split["train_label_end"] < split["validation_start"]
    assert split["validation_label_end"] < split["test_start"]
    budgets = [report["lineage"]["models"][m]["predictor_optimizer_updates"]
               for m in ("mlp", "mlp_resample", "mlp_diffusion")]
    assert len(set(budgets)) == 1
    for _, group in pd.DataFrame(report["weights"]).groupby("model"):
        assert group.weight.sum() == pytest.approx(1)
        assert (group.loc[group.kind.eq("asset"), "weight"] <= .2 + 1e-12).all()
        assert group.loc[group.kind.eq("cash"), "weight"].iloc[0] >= .2 - 1e-12


def test_cpu_row_limit_rejects_before_estimator_call(monkeypatch):
    def unexpected_fit(*args, **kwargs):
        pytest.fail("oversized input reached the estimator")
    monkeypatch.setattr(engine, "fit_predict_models", unexpected_fit)
    frame = engine.make_synthetic_prices(periods=600, n_assets=12)
    with pytest.raises(ValueError, match="training rows exceed"):
        engine.run_simulation(frame, benchmark="BENCH", source="synthetic")


def test_partial_model_failure_remains_visible(prices, monkeypatch):
    def failed_fit(train_x, train_y, val_x, val_y, test_x, **kwargs):
        statuses = {m: {"status": "failed", "error": "intentional test failure"}
                    for m in engine.MODEL_NAMES}
        statuses["ridge"] = {"status": "success"}
        return {"ridge": np.zeros(len(test_x))}, statuses
    monkeypatch.setattr(engine, "fit_predict_models", failed_fit)
    report = engine.run_simulation(prices, benchmark="BENCH", source="synthetic")
    assert report["lineage"]["model_status"]["mlp_diffusion"]["status"] == "failed"
    assert report["lineage"]["model_status"]["ridge"]["status"] == "success"
    assert set(row["model"] for row in report["equity"]) == {"ridge"}
    assert all(row["total_return"] is None for row in report["metrics"] if row["status"] == "failed")


def test_second_visitor_is_refused_while_training_instead_of_sharing_state(prices, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = engine.fit_predict_models
    def blocked_fit(*args, **kwargs):
        entered.set()
        if not release.wait(15):
            raise RuntimeError("test timed out")
        return original(*args, **kwargs)
    monkeypatch.setattr(engine, "fit_predict_models", blocked_fit)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(engine.run_simulation, prices, benchmark="BENCH", source="synthetic")
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError, match="another simulation"):
                engine.run_simulation(prices, benchmark="BENCH", source="synthetic")
        finally:
            release.set()
        assert first.result(timeout=20)["status"] == "success"
