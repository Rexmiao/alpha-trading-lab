"""Train-only alpha predictors and a small conditional DDPM research experiment.

These are method experiments, not exact implementations of ADNN or DARL.  Every
MLP predictor sees the same number of examples and optimizer updates.  Generating
extra training labels has its own separately reported computational budget.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


MODEL_NAMES = ("ridge", "mlp", "mlp_resample", "mlp_diffusion")


def _array_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        normalized = np.ascontiguousarray(array, dtype="<f8")
        digest.update(str(normalized.shape).encode("ascii"))
        digest.update(normalized.tobytes())
    return digest.hexdigest()


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or int(value) != value or int(value) < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _hidden_sizes(value: Any, *, exactly_two: bool = False) -> tuple[int, ...]:
    sizes = tuple(_positive_int(item, "hidden layer size") for item in value)
    if not sizes or (exactly_two and len(sizes) != 2):
        raise ValueError("predictor must have exactly two hidden layers" if exactly_two
                         else "at least one hidden layer is required")
    return sizes


def _matrix(value: Any, name: str, n_features: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape[1] < 1:
        raise ValueError(f"{name} must be a two-dimensional feature matrix")
    if n_features is not None and array.shape[1] != n_features:
        raise ValueError(f"{name} has the wrong number of features")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def _target(value: Any, name: str, n_rows: int) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim == 2 and array.shape[1] == 1:
        array = array[:, 0]
    if array.ndim != 1 or len(array) != n_rows:
        raise ValueError(f"{name} must contain one target per feature row")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def _cosine_schedule(steps: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Discrete DDPM cosine schedule, with a nearly pure-noise final state."""
    if steps < 2:
        raise ValueError("diffusion_steps must be at least two")
    time = np.arange(steps + 1, dtype=float) / steps
    cumulative = np.cos((time + 0.008) / 1.008 * np.pi / 2) ** 2
    cumulative /= cumulative[0]
    betas = np.clip(1.0 - cumulative[1:] / cumulative[:-1], 1e-8, 0.999)
    alphas = 1.0 - betas
    return betas, alphas, np.cumprod(alphas)


class _ConditionalDDPM:
    """Conditional scalar-return DDPM, using a numerically stable v parameterization.

    q(y_t|y_0) = sqrt(abar_t)y_0 + sqrt(1-abar_t)epsilon.
    v = sqrt(abar_t)epsilon - sqrt(1-abar_t)y_0 is the regression target.
    This reconstructs epsilon_hat = sqrt(1-abar_t)y_t + sqrt(abar_t)v_hat
    and y0_hat = sqrt(abar_t)y_t - sqrt(1-abar_t)v_hat.  Sampling then
    uses the actual DDPM Gaussian posterior at every reverse timestep.
    """

    def __init__(self, *, steps: int = 32, train_steps: int = 450,
                 batch_size: int = 128, components: int = 8,
                 hidden_sizes: tuple[int, ...] = (48, 24), seed: int = 42):
        self.steps = _positive_int(steps, "diffusion_steps")
        self.train_steps = _positive_int(train_steps, "diffusion_train_steps")
        self.batch_size = _positive_int(batch_size, "diffusion_batch_size")
        self.components = _positive_int(components, "diffusion_components")
        self.hidden_sizes = _hidden_sizes(hidden_sizes)
        self.seed = int(seed)
        self.betas_, self.alphas_, self.alpha_bar_ = _cosine_schedule(self.steps)

    def _input(self, noisy_y: np.ndarray, condition: np.ndarray,
               timesteps: np.ndarray) -> np.ndarray:
        fraction = (timesteps + 0.5) / self.steps
        phase = 2 * np.pi * fraction[:, None] * np.array([1., 2., 4., 8.])
        time_features = np.column_stack((fraction,
            np.sqrt(self.alpha_bar_[timesteps]),
            np.sqrt(1 - self.alpha_bar_[timesteps]), np.sin(phase), np.cos(phase)))
        return np.column_stack((noisy_y, condition, time_features))

    def fit(self, X_train: np.ndarray, y_train_standardized: np.ndarray):
        X_train = _matrix(X_train, "generator X_train")
        y_train_standardized = _target(y_train_standardized, "generator y_train", len(X_train))
        if len(X_train) < 2:
            raise ValueError("conditional diffusion requires at least two training rows")
        self.n_features_in_ = X_train.shape[1]
        components = min(self.components, X_train.shape[1], len(X_train) - 1)
        self.pca_ = PCA(n_components=components, svd_solver="full")
        # Constant features are valid; explained_variance_ratio is not used.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            condition = self.pca_.fit_transform(X_train)
        self.condition_scaler_ = StandardScaler().fit(condition)
        condition = self.condition_scaler_.transform(condition)
        self.clip_bound_ = float(max(4.0, np.quantile(np.abs(y_train_standardized), .995)))
        self.denoiser_ = MLPRegressor(hidden_layer_sizes=self.hidden_sizes,
            activation="tanh", solver="adam", learning_rate_init=0.001,
            alpha=0.0001, batch_size=self.batch_size, max_iter=1,
            random_state=self.seed, shuffle=False, early_stopping=False)
        rng = np.random.default_rng(self.seed)
        with warnings.catch_warnings(), threadpool_limits(limits=1):
            warnings.simplefilter("ignore", ConvergenceWarning)
            for _ in range(self.train_steps):
                rows = rng.integers(0, len(X_train), size=self.batch_size)
                timesteps = rng.integers(0, self.steps, size=self.batch_size)
                epsilon = rng.standard_normal(self.batch_size)
                a = np.sqrt(self.alpha_bar_[timesteps])
                b = np.sqrt(1 - self.alpha_bar_[timesteps])
                clean_y = y_train_standardized[rows]
                noisy_y = a * clean_y + b * epsilon
                velocity = a * epsilon - b * clean_y
                model_input = self._input(noisy_y, condition[rows], timesteps)
                self.denoiser_.partial_fit(model_input, velocity)
            last_velocity_mse = float(np.mean((self.denoiser_.predict(model_input) - velocity) ** 2))
        loss = float(self.denoiser_.loss_)
        if not math.isfinite(loss):
            raise ValueError("DDPM denoiser training produced a non-finite loss")
        self.metadata_ = {
            "kind": "conditional_ddpm", "condition": "train-only PCA of standardized X",
            "generated_variable": "standardized future excess-return label y conditional on X",
            "prediction_parameterization": "v; epsilon_hat = sqrt(1-alpha_bar)*y_t + sqrt(alpha_bar)*v_hat",
            "training_objective": "mean squared velocity denoising error",
            "reverse_sampler": "DDPM posterior with predicted clean label",
            "schedule": "cosine", "steps": self.steps,
            "terminal_alpha_bar": float(self.alpha_bar_[-1]),
            "train_steps": self.train_steps, "batch_size": self.batch_size,
            "fit_rows": len(X_train), "fit_input_sha256": _array_hash(X_train, y_train_standardized),
            "condition_components": components, "hidden_sizes": list(self.hidden_sizes),
            "seed": self.seed, "fit_scope": "training rows only; no validation or test fitting",
            "diagnostics": {"last_batch_velocity_mse": last_velocity_mse,
                            "last_training_objective": loss,
                            "objective_definition": "scikit-learn half squared error plus L2 penalty",
                            "interpretation": "generator training diagnostic, not alpha evidence"},
            "clip": {"method": "clip predicted clean standardized label at every reverse step",
                     "absolute_bound": self.clip_bound_,
                     "bound_source": "max(4, training-only 99.5th percentile of abs standardized y)"},
        }
        return self

    def sample(self, X_condition: np.ndarray, *, seed: int | None = None) -> np.ndarray:
        if not hasattr(self, "denoiser_"):
            raise ValueError("DDPM must be fitted before sampling")
        X_condition = _matrix(X_condition, "X_condition", self.n_features_in_)
        if len(X_condition) == 0:
            return np.empty(0, dtype=float)
        condition = self.condition_scaler_.transform(self.pca_.transform(X_condition))
        rng = np.random.default_rng(self.seed + 1 if seed is None else seed)
        current = rng.standard_normal(len(X_condition))
        clipped_count = 0
        with threadpool_limits(limits=1):
            for timestep in range(self.steps - 1, -1, -1):
                t = np.full(len(current), timestep, dtype=int)
                velocity = self.denoiser_.predict(self._input(current, condition, t))
                abar = self.alpha_bar_[timestep]
                previous_abar = self.alpha_bar_[timestep - 1] if timestep else 1.0
                predicted_clean = np.sqrt(abar) * current - np.sqrt(1 - abar) * velocity
                clipped_count += int(np.count_nonzero(np.abs(predicted_clean) > self.clip_bound_))
                predicted_clean = np.clip(predicted_clean, -self.clip_bound_, self.clip_bound_)
                denominator = 1 - abar
                mean = (np.sqrt(previous_abar) * self.betas_[timestep] / denominator * predicted_clean
                        + np.sqrt(self.alphas_[timestep]) * (1 - previous_abar) / denominator * current)
                variance = self.betas_[timestep] * (1 - previous_abar) / denominator
                current = mean + (np.sqrt(max(variance, 0.0)) * rng.standard_normal(len(current))
                                  if timestep else 0.0)
        if not np.all(np.isfinite(current)):
            raise ValueError("DDPM reverse sampling produced non-finite labels")
        self.last_sampling_diagnostics_ = {
            "generated_rows": len(current), "reverse_steps": self.steps,
            "clipped_proposals_fraction": clipped_count / (len(current) * self.steps),
            "standardized_label_mean": float(np.mean(current)),
            "standardized_label_std": float(np.std(current)),
        }
        return current


@dataclass
class AlphaModelArtifact:
    """Reusable fitted model bundle. Load only artifacts from a trusted source.

    ``predict`` accepts original, unscaled feature rows.  The optional generator
    is a research training-label sampler, not the alpha predictor itself.
    """

    model_name: str
    estimator: Any
    x_scaler: StandardScaler
    y_scaler: StandardScaler
    generator: _ConditionalDDPM | None
    training_metadata: dict
    format_version: int = 1

    def predict(self, X) -> np.ndarray:
        X = _matrix(X, "artifact prediction X", int(self.x_scaler.n_features_in_))
        if not len(X):
            return np.empty(0, dtype=float)
        with threadpool_limits(limits=1):
            scaled_prediction = self.estimator.predict(self.x_scaler.transform(X))
        prediction = self.y_scaler.inverse_transform(scaled_prediction[:, None])[:, 0]
        if not np.all(np.isfinite(prediction)):
            raise ValueError("artifact produced non-finite predictions")
        return prediction

    def generate_labels(self, X, *, seed: int | None = None) -> np.ndarray:
        if self.generator is None:
            raise ValueError("this artifact does not contain a conditional DDPM")
        X = _matrix(X, "artifact label condition X", int(self.x_scaler.n_features_in_))
        if not len(X):
            return np.empty(0, dtype=float)
        labels = self.generator.sample(self.x_scaler.transform(X), seed=seed)
        return self.y_scaler.inverse_transform(labels[:, None])[:, 0]


def _save_artifact(bundle: AlphaModelArtifact, artifacts_dir) -> dict:
    directory = Path(artifacts_dir) / bundle.model_name
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "model.joblib"
    # A failed serialization must not expose a partial model.joblib as usable.
    with tempfile.NamedTemporaryFile(dir=directory, prefix="model.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        joblib.dump(bundle, temporary, compress=3)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"file": f"{bundle.model_name}/model.joblib", "sha256": digest,
            "format": "joblib", "bundle_class": "research.models.AlphaModelArtifact",
            "prediction_input": "original unscaled feature rows"}


def _train_mlp(X_pool: np.ndarray, y_pool: np.ndarray, *, n_real: int,
               seed: int, settings: dict) -> tuple[MLPRegressor, dict]:
    epochs = _positive_int(settings.get("mlp_max_iter", 160), "mlp_max_iter")
    batch_size = min(n_real, _positive_int(settings.get("mlp_batch_size", 128), "mlp_batch_size"))
    hidden = _hidden_sizes(settings.get("mlp_hidden_sizes", (48, 24)), exactly_two=True)
    estimator = MLPRegressor(hidden_layer_sizes=hidden, activation="relu", solver="adam",
        learning_rate_init=float(settings.get("mlp_learning_rate", .001)),
        alpha=float(settings.get("mlp_alpha", .001)), batch_size=batch_size,
        max_iter=1, random_state=seed, shuffle=False, early_stopping=False)
    rng = np.random.default_rng(seed)
    with warnings.catch_warnings(), threadpool_limits(limits=1):
        warnings.simplefilter("ignore", ConvergenceWarning)
        for _ in range(epochs):
            # Exactly n_real examples and ceil(n_real/batch_size) updates per epoch
            # for all three predictor groups, irrespective of augmented pool size.
            rows = rng.permutation(len(X_pool))[:n_real]
            estimator.partial_fit(X_pool[rows], y_pool[rows])
        training_mse = float(np.mean((estimator.predict(X_pool[rows]) - y_pool[rows]) ** 2))
    loss = float(estimator.loss_)
    if not math.isfinite(loss):
        raise ValueError("MLP training produced a non-finite loss")
    return estimator, {"hidden_sizes": list(hidden), "activation": "relu", "solver": "adam",
        "epochs": epochs, "batch_size": batch_size, "pool_rows": len(X_pool),
        "predictor_examples_per_epoch": n_real, "predictor_examples_seen": epochs * n_real,
        "predictor_optimizer_updates": epochs * math.ceil(n_real / batch_size),
        "last_training_mse_standardized": training_mse,
        "last_training_objective": loss,
        "objective_definition": "scikit-learn half squared error plus L2 penalty",
        "early_stopping": False,
        "budget_note": "same predictor updates/examples across MLP groups; generator compute is extra"}


def fit_predict_models(X_train, y_train, X_val, y_val, X_test, *, seed=42,
                       config=None, train_dates=None, artifacts_dir=None):
    """Return test-aligned predictions and per-model JSON-serializable metadata.

    Validation labels only produce an RMSE diagnostic after fitting.  Failed
    models are omitted from predictions and explicitly marked failed in metadata;
    another model's scores are never substituted. If artifacts_dir is provided,
    each successful model is saved beneath it as <model>/model.joblib together
    with its fitted preprocessors and optional DDPM. No artifacts are read here.
    """
    X_train = _matrix(X_train, "X_train")
    if len(X_train) < 2:
        raise ValueError("at least two training rows are required")
    n_features = X_train.shape[1]
    X_val = _matrix(X_val, "X_val", n_features)
    X_test = _matrix(X_test, "X_test", n_features)
    y_train = _target(y_train, "y_train", len(X_train))
    y_val = _target(y_val, "y_val", len(X_val))
    if train_dates is not None and len(train_dates) != len(X_train):
        raise ValueError("train_dates must align with training rows")
    settings = dict((config or {}).get("models", config or {}))
    scaler = StandardScaler().fit(X_train)
    target_scaler = StandardScaler().fit(y_train[:, None])
    train_x = scaler.transform(X_train)
    val_x = scaler.transform(X_val) if len(X_val) else np.empty((0, n_features))
    test_x = scaler.transform(X_test) if len(X_test) else np.empty((0, n_features))
    train_y = target_scaler.transform(y_train[:, None])[:, 0]
    date_values = [str(value) for value in train_dates] if train_dates is not None else []
    common = {"seed": int(seed), "fit_rows": len(X_train), "feature_count": n_features,
        "train_input_sha256": _array_hash(X_train, y_train),
        "train_start": min(date_values) if date_values else None,
        "train_end": max(date_values) if date_values else None,
        "preprocessing": {"fit_scope": "training rows only",
            "X_mean": scaler.mean_.tolist(), "X_scale": scaler.scale_.tolist(),
            "y_mean": float(target_scaler.mean_[0]), "y_scale": float(target_scaler.scale_[0])},
        "validation_usage": "post-fit RMSE diagnostic only; no fitting, selection or early stopping",
        "paper_replication": "research design; not an exact ADNN or DARL reproduction"}
    predictions, metadata = {}, {}
    for name in MODEL_NAMES:
        info = {**common, "status": "failed", "model": name}
        generator = None
        try:
            if name == "ridge":
                alpha = float(settings.get("ridge_alpha", 10.0))
                estimator = Ridge(alpha=alpha, solver="lsqr", tol=1e-8).fit(train_x, train_y)
                info.update({"kind": "ridge_regression", "alpha": alpha})
            else:
                pool_x, pool_y = train_x, train_y
                if name != "mlp":
                    ratio = float(settings.get("synthetic_ratio", .25))
                    if not math.isfinite(ratio) or ratio <= 0 or ratio > 10:
                        raise ValueError("synthetic_ratio must be finite and in (0, 10]")
                    count = max(1, round(len(train_x) * ratio))
                    rows = np.random.default_rng(int(seed) + 17).integers(0, len(train_x), size=count)
                    if name == "mlp_resample":
                        extra_y = train_y[rows]
                        info["augmentation"] = {"kind": "bootstrap paired training rows", "rows": count}
                    else:
                        generator = _ConditionalDDPM(
                            steps=settings.get("diffusion_steps", 32),
                            train_steps=settings.get("diffusion_train_steps", 450),
                            batch_size=settings.get("diffusion_batch_size", 128),
                            components=settings.get("diffusion_components", 8),
                            hidden_sizes=settings.get("diffusion_hidden_sizes", (48, 24)),
                            seed=int(seed) + 101).fit(train_x, train_y)
                        extra_y = generator.sample(train_x[rows], seed=int(seed) + 102)
                        generated_decimal = target_scaler.inverse_transform(extra_y[:, None])[:, 0]
                        info["generator"] = {**generator.metadata_,
                            "raw_training_input_sha256": common["train_input_sha256"],
                            "sampling": generator.last_sampling_diagnostics_,
                            "generated_label_decimal": {"mean": float(np.mean(generated_decimal)),
                                "std": float(np.std(generated_decimal)),
                                "min": float(np.min(generated_decimal)), "max": float(np.max(generated_decimal))},
                            "alpha_effect": "not established by generator diagnostics; evaluate real held-out predictions"}
                        info["augmentation"] = {"kind": "conditional_ddpm_labels", "rows": count,
                            "pairing": "retain selected real training X and generate its conditional y; no independent input-label shuffle",
                            "condition_rows_sha256": _array_hash(train_x[rows])}
                    pool_x = np.concatenate((train_x, train_x[rows]))
                    pool_y = np.concatenate((train_y, extra_y))
                estimator, training_info = _train_mlp(pool_x, pool_y, n_real=len(train_x),
                                                     seed=int(seed), settings=settings)
                info.update({"kind": "two_hidden_layer_mlp", **training_info})
            with threadpool_limits(limits=1):
                scaled_prediction = estimator.predict(test_x) if len(test_x) else np.empty(0)
                values = target_scaler.inverse_transform(scaled_prediction[:, None])[:, 0] if len(test_x) else np.empty(0)
                if not np.all(np.isfinite(values)):
                    raise ValueError("model produced non-finite test predictions")
                if len(val_x):
                    validation_prediction = target_scaler.inverse_transform(estimator.predict(val_x)[:, None])[:, 0]
                    rmse = float(np.sqrt(np.mean((validation_prediction - y_val) ** 2)))
                    info["validation_rmse_decimal"] = rmse if math.isfinite(rmse) else None
            info["status"] = "success"
            if artifacts_dir is not None:
                bundle = AlphaModelArtifact(model_name=name, estimator=estimator,
                    x_scaler=scaler, y_scaler=target_scaler, generator=generator,
                    training_metadata=info.copy())
                info["artifact"] = _save_artifact(bundle, artifacts_dir)
            predictions[name] = values
        except Exception as exc:
            info["status"] = "failed"
            info["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        metadata[name] = info
    return predictions, metadata
