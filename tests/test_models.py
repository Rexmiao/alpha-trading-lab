"""Offline unit tests; synthetic fixtures are not trading experiment results."""

import json
import hashlib

import joblib
import numpy as np
import pytest

from research.models import MODEL_NAMES, _ConditionalDDPM, _cosine_schedule, fit_predict_models


@pytest.fixture
def fixture_data():
    rng = np.random.default_rng(123)
    X = rng.normal(size=(120, 5))
    y = .0002 + .002 * X[:, 0] - .001 * X[:, 1] + rng.normal(scale=.0003, size=120)
    return X[:80], y[:80], X[80:100], y[80:100], X[100:]


@pytest.fixture
def small_config():
    return {"models": {"mlp_max_iter": 12, "mlp_hidden_sizes": [12, 6],
        "mlp_batch_size": 20, "diffusion_steps": 8, "diffusion_train_steps": 35,
        "diffusion_batch_size": 24, "diffusion_hidden_sizes": [12, 6],
        "diffusion_components": 3, "synthetic_ratio": .25}}


def test_all_models_finite_reproducible_and_predictors_budget_matched(fixture_data, small_config):
    first, metadata = fit_predict_models(*fixture_data, seed=17, config=small_config)
    repeated, second_metadata = fit_predict_models(*fixture_data, seed=17, config=small_config)
    assert set(first) == set(MODEL_NAMES)
    for name in MODEL_NAMES:
        assert metadata[name]["status"] == "success", metadata[name]
        assert first[name].shape == (20,)
        assert np.isfinite(first[name]).all()
        np.testing.assert_array_equal(first[name], repeated[name])
    assert metadata == second_metadata
    json.dumps(metadata, allow_nan=False)
    neural_metadata = [metadata[name] for name in MODEL_NAMES if name != "ridge"]
    assert {item["predictor_optimizer_updates"] for item in neural_metadata} == {48}
    assert {item["predictor_examples_seen"] for item in neural_metadata} == {960}
    generator = metadata["mlp_diffusion"]["generator"]
    assert generator["fit_rows"] == 80
    assert generator["terminal_alpha_bar"] < .001
    assert generator["kind"] == "conditional_ddpm"
    assert generator["sampling"]["reverse_steps"] == 8


def test_validation_and_test_cannot_change_fitted_generator(fixture_data, small_config):
    X_train, y_train, X_val, y_val, X_test = fixture_data
    original, original_meta = fit_predict_models(*fixture_data, seed=19, config=small_config)
    shifted, shifted_meta = fit_predict_models(X_train, y_train, X_val * 100 + 500,
        y_val + 999, X_test, seed=19, config=small_config)
    for name in MODEL_NAMES:
        np.testing.assert_array_equal(original[name], shifted[name])
        assert original_meta[name]["preprocessing"] == shifted_meta[name]["preprocessing"]
    assert original_meta["mlp_diffusion"]["generator"] == shifted_meta["mlp_diffusion"]["generator"]
    _, shifted_test_meta = fit_predict_models(X_train, y_train, X_val, y_val,
        X_test * 10 + 75, seed=19, config=small_config)
    assert original_meta["mlp_diffusion"]["generator"] == shifted_test_meta["mlp_diffusion"]["generator"]
    np.testing.assert_allclose(original_meta["ridge"]["preprocessing"]["X_mean"], X_train.mean(axis=0))


def test_small_decimal_target_scaling_and_training_lineage(fixture_data, small_config):
    X_train, y_train, X_val, y_val, X_test = fixture_data
    predictions, metadata = fit_predict_models(X_train, y_train * 1e-5, X_val,
        y_val * 1e-5, X_test, config=small_config,
        train_dates=[f"2020-01-{(i % 20) + 1:02d}" for i in range(len(X_train))])
    assert set(predictions) == set(MODEL_NAMES)
    scale = metadata["mlp"]["preprocessing"]["y_scale"]
    assert 0 < scale < 1e-6
    assert max(abs(predictions["mlp"])) < 1e-5
    assert metadata["ridge"]["train_start"] == "2020-01-01"
    assert metadata["ridge"]["train_end"] == "2020-01-20"
    _, changed_metadata = fit_predict_models(X_train, y_train * 2e-5, X_val,
        y_val * 1e-5, X_test, config=small_config)
    assert metadata["ridge"]["train_input_sha256"] != changed_metadata["ridge"]["train_input_sha256"]


def test_bad_generator_setting_is_not_silently_replaced(fixture_data, small_config, tmp_path):
    small_config["models"]["diffusion_steps"] = 1
    predictions, metadata = fit_predict_models(*fixture_data, config=small_config,
                                               artifacts_dir=tmp_path)
    assert set(predictions) == {"ridge", "mlp", "mlp_resample"}
    assert metadata["mlp_diffusion"]["status"] == "failed"
    assert "diffusion_steps" in metadata["mlp_diffusion"]["error"]
    assert "artifact" not in metadata["mlp_diffusion"]
    assert not (tmp_path / "mlp_diffusion" / "model.joblib").exists()


def test_generator_reverse_sampling_reproducible_and_condition_preserved():
    rng = np.random.default_rng(55)
    X = rng.normal(size=(40, 3))
    y = .4 * X[:, 0] + rng.normal(scale=.5, size=40)
    generator = _ConditionalDDPM(steps=6, train_steps=15, batch_size=20,
        components=2, hidden_sizes=(8, 4), seed=31).fit(X, y)
    condition = X[:7].copy()
    first = generator.sample(condition, seed=90)
    repeated = generator.sample(condition, seed=90)
    assert first.shape == (7,)
    assert np.isfinite(first).all()
    np.testing.assert_array_equal(first, repeated)
    np.testing.assert_array_equal(condition, X[:7])
    changed = generator.sample(condition, seed=91)
    assert not np.array_equal(first, changed)
    changed_condition = generator.sample(condition + 2.0, seed=90)
    assert not np.array_equal(first, changed_condition)
    assert np.max(np.abs(first)) <= generator.clip_bound_ + 1e-12


def test_schedule_is_monotonic_and_terminal_noise_dominates():
    betas, alphas, alpha_bar = _cosine_schedule(32)
    assert np.all((betas > 0) & (betas < 1))
    assert np.all((alphas > 0) & (alphas < 1))
    assert np.all(np.diff(alpha_bar) < 0)
    assert alpha_bar[-1] < .00001


def test_invalid_nonfinite_input_rejected(fixture_data, small_config):
    invalid = list(fixture_data)
    invalid[0] = invalid[0].copy()
    invalid[0][0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        fit_predict_models(*invalid, config=small_config)


def test_saved_artifacts_reproduce_original_scale_predictions(fixture_data, small_config, tmp_path):
    predictions, metadata = fit_predict_models(*fixture_data, seed=72,
        config=small_config, artifacts_dir=tmp_path)
    assert set(predictions) == set(MODEL_NAMES)
    for name in MODEL_NAMES:
        descriptor = metadata[name]["artifact"]
        artifact_path = tmp_path / descriptor["file"]
        assert artifact_path.is_file()
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == descriptor["sha256"]
        # This test loads only the artifact just written by this test invocation.
        bundle = joblib.load(artifact_path)
        assert bundle.model_name == name
        np.testing.assert_array_equal(bundle.predict(fixture_data[-1]), predictions[name])
        np.testing.assert_allclose(bundle.x_scaler.mean_, fixture_data[0].mean(axis=0))
        assert bundle.generator is not None if name == "mlp_diffusion" else bundle.generator is None
        if bundle.generator is not None:
            labels = bundle.generate_labels(fixture_data[0][:5], seed=4)
            assert labels.shape == (5,)
            assert np.isfinite(labels).all()
    assert not list(tmp_path.rglob("*.tmp"))


def test_artifact_write_failure_is_reported_without_partial_models(fixture_data, small_config,
                                                                tmp_path, monkeypatch):
    def fail_serialization(*args, **kwargs):
        raise OSError("test serialization failure")

    monkeypatch.setattr("research.models.joblib.dump", fail_serialization)
    predictions, metadata = fit_predict_models(*fixture_data, config=small_config,
                                               artifacts_dir=tmp_path)
    assert predictions == {}
    assert all(item["status"] == "failed" for item in metadata.values())
    assert all("serialization failure" in item["error"] for item in metadata.values())
    assert not list(tmp_path.rglob("model.joblib"))
    assert not list(tmp_path.rglob("*.tmp"))
