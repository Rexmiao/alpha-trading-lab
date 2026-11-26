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


@pytest.mark.parametrize("horizon", [7, 20])
def test_custom_horizon_uses_matching_labels_purge_and_actual_rebalances(prices, monkeypatch, horizon):
    """Exercise nonpreset and upper-bound horizons through all real estimators."""
    original_backtest = engine.backtest
    actual_simulations = []

    def capture_real_backtest(*args, **kwargs):
        simulation = original_backtest(*args, **kwargs)
        actual_simulations.append(simulation)
        return simulation

    monkeypatch.setattr(engine, "backtest", capture_real_backtest)
    report = engine.run_simulation(prices, benchmark="BENCH", source="synthetic", horizon=horizon)
    assert report["status"] == "success"
    assert all(status["status"] == "success" for status in report["lineage"]["model_status"].values())
    assert len(actual_simulations) == len(engine.MODEL_NAMES)
    assert {row["model"] for row in report["predictions"]} == set(engine.MODEL_NAMES)
    json.dumps(report, allow_nan=False)

    split = report["lineage"]["split"]
    sessions = pd.DatetimeIndex(sorted(prices.loc[prices.symbol.eq("BENCH"), "date"]))
    for segment, next_segment in (("train", "validation"), ("validation", "test")):
        last_signal = pd.Timestamp(split[f"{segment}_end"])
        last_label_end = pd.Timestamp(split[f"{segment}_label_end"])
        assert last_label_end == sessions[sessions.get_loc(last_signal) + horizon + 1]
        assert last_label_end < pd.Timestamp(split[f"{next_segment}_start"])
    assert split["purged_train_rows"] > 0
    assert split["purged_validation_rows"] > 0

    # Check exported realized answers against actual next-open and exit-open
    # prices, independently of build_dataset and its generated target column.
    opens = prices.pivot(index="date", columns="symbol", values="open")
    predictions = pd.DataFrame(report["predictions"])
    for _, model_predictions in predictions.groupby("model"):
        for row in model_predictions.iloc[[0, len(model_predictions) // 2, -1]].itertuples(index=False):
            position = sessions.get_loc(pd.Timestamp(row.date))
            entry, exit_ = sessions[position + 1], sessions[position + horizon + 1]
            stock_return = opens.at[exit_, row.symbol] / opens.at[entry, row.symbol] - 1
            market_return = opens.at[exit_, "BENCH"] / opens.at[entry, "BENCH"] - 1
            assert row.realized_excess == pytest.approx(stock_return - market_return, abs=1e-12)

    first_test = pd.Timestamp(predictions.date.min())
    for simulation in actual_simulations:
        rebalances = simulation["rebalances"]
        assert len(rebalances) >= 2
        signal_positions = [sessions.get_loc(pd.Timestamp(row["signal_date"])) for row in rebalances]
        execution_positions = [sessions.get_loc(pd.Timestamp(row["execution_date"])) for row in rebalances]
        assert sessions[signal_positions[0]] == first_test
        assert np.all(np.diff(signal_positions) == horizon)
        assert np.array_equal(np.asarray(execution_positions), np.asarray(signal_positions) + 1)
        assert simulation["metrics"]["rebalance_days"] == horizon
        assert simulation["metrics"]["rebalance_count"] == len(rebalances)


@pytest.mark.parametrize("horizon", [0, 21, 7.5, True, False])
def test_invalid_horizon_is_refused_before_training(prices, monkeypatch, horizon):
    def unexpected_fit(*args, **kwargs):
        pytest.fail("invalid horizon reached the estimator")

    monkeypatch.setattr(engine, "fit_predict_models", unexpected_fit)
    with pytest.raises(ValueError, match="horizon"):
        engine.run_simulation(prices, benchmark="BENCH", source="synthetic", horizon=horizon)


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
