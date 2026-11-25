"""Offline test fixtures only; these are not simulated market performance claims."""
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from research.rank_experiment import (GroupedTanhMLP, fit_rank_models,
    fit_score_calibrator, run_rank_experiment, soft_rank_loss_and_grad)


def test_soft_rank_gradient_matches_finite_differences():
    scores = np.array([-.9, .2, 1.4, -.1, .7])
    target = np.array([.01, -.02, .03, .005, -.008])
    _, analytical = soft_rank_loss_and_grad(scores, target)
    numerical = np.zeros_like(scores)
    epsilon = 1e-6
    for i in range(len(scores)):
        high, low = scores.copy(), scores.copy()
        high[i] += epsilon
        low[i] -= epsilon
        numerical[i] = (soft_rank_loss_and_grad(high, target)[0] -
                        soft_rank_loss_and_grad(low, target)[0]) / (2 * epsilon)
    np.testing.assert_allclose(analytical, numerical, rtol=2e-5, atol=2e-7)
    assert abs(analytical.sum()) < 1e-10


@pytest.mark.parametrize("objective", ["rank", "mse"])
def test_complete_network_gradient_matches_finite_differences(objective):
    rng = np.random.default_rng(18)
    X, y = rng.normal(size=(8, 2)), rng.normal(size=8)
    groups = [np.arange(4), np.arange(4, 8)]
    network = GroupedTanhMLP(2, hidden_sizes=(3, 2), seed=8)
    _, analytical = network.loss_and_grad(X, y, groups, objective=objective)
    epsilon = 1e-6
    for key, parameter in network.params.items():
        for index in np.ndindex(parameter.shape):
            original = parameter[index]
            parameter[index] = original + epsilon
            high = network.loss_and_grad(X, y, groups, objective=objective)[0]
            parameter[index] = original - epsilon
            low = network.loss_and_grad(X, y, groups, objective=objective)[0]
            parameter[index] = original
            np.testing.assert_allclose(analytical[key][index], (high-low)/(2*epsilon),
                                       rtol=3e-4, atol=3e-6)


def test_soft_rank_affine_invariance_and_constant_groups():
    scores, target = np.array([-1., .3, .9, 2]), np.array([.2, -.1, .6, .1])
    original = soft_rank_loss_and_grad(scores, target)[0]
    transformed = soft_rank_loss_and_grad(scores * 3 + 9, target * 100 + 5)[0]
    assert original == pytest.approx(transformed)
    loss, gradient = soft_rank_loss_and_grad(np.ones(4), target)
    assert loss == 0
    np.testing.assert_array_equal(gradient, np.zeros(4))


@pytest.fixture
def frames():
    rng = np.random.default_rng(2026)
    dates = pd.bdate_range("2020-01-01", periods=24)
    rows = []
    for day in dates:
        for stock in range(4):
            f1, f2 = rng.normal(size=2)
            rows.append({"date": day, "label_end": day+pd.Timedelta(days=2),
                "symbol": f"TEST{stock}", "f1": f1, "f2": f2,
                "target": .002*f1-.001*f2+rng.normal(scale=.0002)})
    frame = pd.DataFrame(rows)
    return frame.iloc[:64].copy(), frame.iloc[64:80].copy(), frame.iloc[80:].copy()


def test_grouped_models_budget_reproducibility_and_calibration_separation(frames):
    train, validation, test = frames
    output, info = fit_rank_models(*frames, ["f1", "f2"], seed=4, steps=40, batch_days=3)
    repeated, repeated_info = fit_rank_models(*frames, ["f1", "f2"], seed=4, steps=40, batch_days=3)
    assert set(output) == {"rank_mse", "rank_softic"}
    assert info["rank_mse"]["group_selection_sha256"] == info["rank_softic"]["group_selection_sha256"]
    for name in output:
        np.testing.assert_array_equal(output[name]["raw_score"], repeated[name]["raw_score"])
        assert info[name]["status"] == "success"
        assert info[name]["optimizer_updates"] == 40
        assert info[name]["training_sample_exposures"] == 40*3*4
        assert info[name]["calibration"]["fit_rows"] == len(validation)
        assert np.isfinite(output[name]["score"]).all()
        np.testing.assert_allclose(info[name]["preprocessing"]["X_mean"], train[["f1","f2"]].mean())
    assert info == repeated_info
    changed_validation = validation.copy()
    changed_validation["target"] += .1
    changed, changed_info = fit_rank_models(train, changed_validation, test, ["f1","f2"],
                                           seed=4, steps=40, batch_days=3)
    for name in output:
        np.testing.assert_array_equal(output[name]["raw_score"], changed[name]["raw_score"])
        np.testing.assert_allclose(changed[name]["score"]-output[name]["score"], .1, atol=1e-12)
        assert info[name]["train_input_sha256"] == changed_info[name]["train_input_sha256"]
    changed_test = test.copy()
    changed_test["target"] += 300
    _, test_info = fit_rank_models(train, validation, changed_test, ["f1","f2"],
                                  seed=4, steps=40, batch_days=3)
    assert info == test_info
    json.dumps(info, allow_nan=False)


def test_validation_calibrator_never_inverts_rank_direction():
    score = np.array([-2., -1., 0., 1., 2.])
    dates = pd.bdate_range("2020-01-01", periods=5)
    positive = fit_score_calibrator(score, .01+.002*score, dates)
    assert positive.slope == pytest.approx(.002)
    assert positive.intercept == pytest.approx(.01)
    negative = fit_score_calibrator(score, .01-.002*score, dates)
    assert negative.slope == 0
    assert negative.metadata["flat_calibration"]


def test_saved_rank_weights_reproduce_both_scores(frames, tmp_path):
    output, metadata = fit_rank_models(*frames, ["f1","f2"], steps=20,
                                      batch_days=3, artifacts_dir=tmp_path)
    test_X = frames[-1][["f1","f2"]].to_numpy()
    for name in output:
        path = tmp_path / metadata[name]["artifact"]["file"]
        artifact = joblib.load(path)  # Own test-created artifact only.
        np.testing.assert_array_equal(artifact.predict_raw(test_X), output[name]["raw_score"])
        np.testing.assert_array_equal(artifact.predict(test_X), output[name]["score"])


def test_missing_snapshot_cannot_overwrite_main_latest(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"seed":42,"horizon":5}), encoding="utf8")
    (tmp_path / "runs").mkdir()
    main_latest = tmp_path / "runs" / "latest.json"
    main_latest.write_text('{"sentinel":"main experiment"}', encoding="utf8")
    before = main_latest.read_bytes()
    assert run_rank_experiment(tmp_path, steps=1) == 1
    assert main_latest.read_bytes() == before
    rank = json.loads((tmp_path / "runs" / "rank_latest.json").read_text(encoding="utf8"))
    assert rank["status"] == "data_unavailable"
    assert rank["predictions"] == []
