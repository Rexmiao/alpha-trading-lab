"""A grouped soft-rank loss mechanism experiment, not a full ADNN reproduction.

Run ``python -m research.rank_experiment`` against the existing frozen snapshot.
No broker access or dependency on the four-model training code is required.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import time
import traceback

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .data import build_dataset, load_snapshot, sha256_file, split_dataset
from .pipeline import _clean, _json_write, _rank_ic
from .portfolio import PortfolioConfig, backtest


PAPER_URL = "https://arxiv.org/html/1912.11761"
MODEL_NAMES = ("rank_mse", "rank_softic")
LOSS_NAMES = {"rank_mse": "mse_standardized_target",
              "rank_softic": "negative_soft_rank_pearson"}


def _hash_arrays(*arrays):
    digest = hashlib.sha256()
    for values in arrays:
        values = np.ascontiguousarray(values, dtype="<f8")
        digest.update(str(values.shape).encode("ascii"))
        digest.update(values.tobytes())
    return digest.hexdigest()


def _soft_rank(values):
    values = np.asarray(values, dtype=float)
    centered = values - values.mean()
    scale = float(np.sqrt(np.mean(centered ** 2)))
    if scale <= 1e-12:
        return np.full_like(values, .5), centered, scale
    return expit(1.83 * centered / (2 * scale)), centered, scale


def soft_rank_loss_and_grad(predictions, targets):
    """Negative standard Pearson of paper-style soft ranks and its exact gradient.

    The standard deviation in g uses ddof=0. Equation 6's ambiguous printed
    denominator is interpreted as the usual product of centered L2 norms.
    Degenerate cross sections contribute zero and have zero gradient.
    """
    predictions = np.asarray(predictions, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if predictions.ndim != 1 or targets.shape != predictions.shape:
        raise ValueError("soft-rank predictions and targets must be aligned vectors")
    if len(predictions) < 3 or not np.isfinite(predictions).all() or not np.isfinite(targets).all():
        raise ValueError("soft-rank objective requires at least three finite observations")
    gp, centered_p, scale_p = _soft_rank(predictions)
    gt, _, scale_t = _soft_rank(targets)
    a, b = gp - gp.mean(), gt - gt.mean()
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    if min(scale_p, scale_t, norm_a, norm_b) <= 1e-12:
        return 0.0, np.zeros_like(predictions)
    correlation = float(np.dot(a, b) / (norm_a * norm_b))
    d_g = -b / (norm_a * norm_b) + correlation * a / norm_a ** 2
    d_u = d_g * gp * (1 - gp)
    standardized = centered_p / scale_p
    gradient = 1.83 / (2 * scale_p) * (
        d_u - d_u.mean() - standardized * np.mean(d_u * standardized))
    return -correlation, gradient


class GroupedTanhMLP:
    """Two-hidden-layer NumPy network with grouped loss and hand-coded Adam."""

    def __init__(self, n_features, *, hidden_sizes=(32, 16), seed=42):
        if len(hidden_sizes) != 2 or min(hidden_sizes) < 1 or n_features < 1:
            raise ValueError("two positive hidden sizes and a positive feature count are required")
        self.n_features_in_ = int(n_features)
        self.hidden_sizes = tuple(int(v) for v in hidden_sizes)
        self.seed = int(seed)
        rng = np.random.default_rng(seed)
        sizes = (n_features, *self.hidden_sizes, 1)
        self.params = {}
        for layer in range(1, 4):
            self.params[f"W{layer}"] = rng.normal(scale=np.sqrt(2 / (sizes[layer-1] + sizes[layer])),
                                                  size=(sizes[layer-1], sizes[layer]))
            self.params[f"b{layer}"] = np.zeros(sizes[layer])

    def _forward(self, X):
        h1 = np.tanh(X @ self.params["W1"] + self.params["b1"])
        h2 = np.tanh(h1 @ self.params["W2"] + self.params["b2"])
        output = (h2 @ self.params["W3"] + self.params["b3"])[:, 0]
        return output, (X, h1, h2)

    def predict(self, X):
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != self.n_features_in_ or not np.isfinite(X).all():
            raise ValueError("network prediction features are invalid")
        return self._forward(X)[0]

    def loss_and_grad(self, X, y, groups, *, objective):
        predictions, (X, h1, h2) = self._forward(X)
        output_gradient = np.zeros(len(predictions))
        objective_value = 0.0
        for group in groups:
            if objective == "rank":
                value, gradient = soft_rank_loss_and_grad(predictions[group], y[group])
            elif objective == "mse":
                residual = predictions[group] - y[group]
                value, gradient = float(np.mean(residual ** 2)), 2 * residual / len(group)
            else:
                raise ValueError("objective must be rank or mse")
            objective_value += value / len(groups)
            output_gradient[group] += gradient / len(groups)
        d3 = output_gradient[:, None]
        d2 = (d3 @ self.params["W3"].T) * (1 - h2 ** 2)
        d1 = (d2 @ self.params["W2"].T) * (1 - h1 ** 2)
        gradients = {"W3": h2.T @ d3, "b3": d3.sum(axis=0),
                     "W2": h1.T @ d2, "b2": d2.sum(axis=0),
                     "W1": X.T @ d1, "b1": d1.sum(axis=0)}
        return float(objective_value), gradients

    def fit(self, X, y, dates, *, objective, steps=600, batch_days=8, learning_rate=.002):
        X, y, dates = np.asarray(X, float), np.asarray(y, float), np.asarray(dates)
        if X.ndim != 2 or y.shape != (len(X),) or dates.shape != y.shape:
            raise ValueError("training rows, labels and dates must align")
        if not np.isfinite(X).all() or not np.isfinite(y).all():
            raise ValueError("training data must be finite")
        if steps < 1 or int(steps) != steps or batch_days < 1 or int(batch_days) != batch_days or learning_rate <= 0:
            raise ValueError("invalid optimizer settings")
        groups = [np.flatnonzero(dates == day) for day in np.unique(dates)]
        groups = [group for group in groups if len(group) >= 3 and np.std(y[group]) > 1e-12]
        if not groups:
            raise ValueError("no nondegenerate training cross sections with at least three symbols")
        batch_days = min(int(batch_days), len(groups))
        rng = np.random.default_rng(self.seed + 1000)
        first_moment = {key: np.zeros_like(value) for key, value in self.params.items()}
        second_moment = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.loss_history_ = []
        exposures = 0
        clipped_updates = 0
        selection_digest = hashlib.sha256()
        with threadpool_limits(limits=1):
            for step in range(1, int(steps) + 1):
                chosen = rng.choice(len(groups), size=batch_days, replace=False)
                selection_digest.update(chosen.astype("<i8").tobytes())
                chosen_groups = [groups[index] for index in chosen]
                rows = np.concatenate(chosen_groups)
                offsets = np.cumsum([0] + [len(group) for group in chosen_groups])
                local_groups = [np.arange(offsets[i], offsets[i+1]) for i in range(batch_days)]
                value, gradients = self.loss_and_grad(X[rows], y[rows], local_groups, objective=objective)
                norm = float(np.sqrt(sum(np.sum(gradient ** 2) for gradient in gradients.values())))
                if not np.isfinite(value) or not np.isfinite(norm):
                    raise ValueError("nonfinite grouped network objective or gradient")
                scale = min(1., 5. / norm) if norm else 1.
                clipped_updates += int(scale < 1)
                for key in self.params:
                    gradient = gradients[key] * scale
                    first_moment[key] = .9 * first_moment[key] + .1 * gradient
                    second_moment[key] = .999 * second_moment[key] + .001 * gradient ** 2
                    corrected_first = first_moment[key] / (1 - .9 ** step)
                    corrected_second = second_moment[key] / (1 - .999 ** step)
                    self.params[key] -= learning_rate * corrected_first / (np.sqrt(corrected_second) + 1e-8)
                exposures += len(rows)
                if step == 1 or step % 50 == 0 or step == steps:
                    self.loss_history_.append({"step": step, "loss": value})
            final_value, _ = self.loss_and_grad(X, y, groups, objective=objective)
        if not all(np.isfinite(value).all() for value in self.params.values()):
            raise ValueError("nonfinite fitted network weights")
        self.training_info_ = {"steps": int(steps), "optimizer_updates": int(steps),
            "batch_days": batch_days, "usable_training_days": len(groups),
            "training_sample_exposures": exposures, "group_selection_sha256": selection_digest.hexdigest(),
            "final_full_training_loss": final_value, "train_loss_history": self.loss_history_,
            "optimizer": "hand-coded Adam", "learning_rate": learning_rate,
            "adam_beta1": .9, "adam_beta2": .999, "adam_epsilon": 1e-8,
            "gradient_global_norm_cap": 5., "clipped_updates": clipped_updates,
            "hidden_sizes": list(self.hidden_sizes), "activation": "tanh", "weight_penalty": 0.,
            "early_stopping": False, "seed": self.seed}
        return self


@dataclass
class ScoreCalibrator:
    """Validation-only least squares with a nonnegative slope; no test selection."""
    intercept: float
    slope: float
    metadata: dict

    def predict(self, raw_score):
        return self.intercept + self.slope * np.asarray(raw_score, dtype=float)


def fit_score_calibrator(raw_validation_score, validation_target, dates):
    score, target = np.asarray(raw_validation_score, float), np.asarray(validation_target, float)
    dates = np.asarray(dates)
    if score.ndim != 1 or target.shape != score.shape or dates.shape != score.shape or len(score) < 3:
        raise ValueError("calibration needs aligned validation scores, targets and dates")
    if not np.isfinite(score).all() or not np.isfinite(target).all():
        raise ValueError("calibration values must be finite")
    centered = score - score.mean()
    denominator = float(np.dot(centered, centered))
    slope = max(0., float(np.dot(centered, target - target.mean()) / denominator)) if denominator > 1e-20 else 0.
    intercept = float(target.mean() - slope * score.mean())
    fitted = intercept + slope * score
    metadata = {"method": "validation-only nonnegative-slope affine least squares",
        "intercept": intercept, "slope": slope, "monotonic_nonnegative_slope": True,
        "fit_scope": "independent validation labels only; not test labels",
        "fit_rows": len(score), "fit_days": len(np.unique(dates)),
        "fit_start": str(pd.Timestamp(dates.min()).date()), "fit_end": str(pd.Timestamp(dates.max()).date()),
        "input_sha256": _hash_arrays(score, target),
        "rmse_decimal": float(np.sqrt(np.mean((fitted - target) ** 2))),
        "output_units": "decimal next-open holding-period excess return versus benchmark",
        "flat_calibration": slope == 0.,
        "note": "calibration fit quality is not held-out alpha evidence; zero slope gives constant forecasts"}
    return ScoreCalibrator(intercept, slope, metadata)


@dataclass
class RankModelArtifact:
    estimator: GroupedTanhMLP
    feature_scaler: StandardScaler
    target_scaler: StandardScaler
    calibrator: ScoreCalibrator
    features: list
    model_name: str

    def predict_raw(self, X):
        return self.estimator.predict(self.feature_scaler.transform(np.asarray(X, float)))

    def predict(self, X):
        return self.calibrator.predict(self.predict_raw(X))


def fit_rank_models(train, validation, test, features, *, seed=42, steps=600,
                    batch_days=8, hidden_sizes=(32, 16), artifacts_dir=None):
    """Fit both fixed objectives, calibrate on validation, and predict untouched test."""
    train_X, train_y = train[features].to_numpy(float), train.target.to_numpy(float)
    scaler = StandardScaler().fit(train_X)
    target_scaler = StandardScaler().fit(train_y[:, None])
    X = scaler.transform(train_X)
    y = target_scaler.transform(train_y[:, None])[:, 0]
    predictions, metadata = {}, {}
    common = {"fit_rows": len(train), "fit_days": int(train.date.nunique()),
        "fit_start": str(train.date.min().date()), "fit_end": str(train.date.max().date()),
        "train_input_sha256": _hash_arrays(train_X, train_y),
        "preprocessing": {"fit_scope": "training only", "X_mean": scaler.mean_.tolist(),
            "X_scale": scaler.scale_.tolist(), "y_mean": float(target_scaler.mean_[0]),
            "y_scale": float(target_scaler.scale_[0])},
        "raw_score_units": "dimensionless ranking score; never passed to return/cost thresholds",
        "feature_count": len(features)}
    for name in MODEL_NAMES:
        info = {**common, "status": "failed", "loss_name": LOSS_NAMES[name]}
        try:
            network = GroupedTanhMLP(len(features), hidden_sizes=hidden_sizes, seed=seed).fit(
                X, y, train.date.to_numpy(), objective="mse" if name == "rank_mse" else "rank",
                steps=steps, batch_days=batch_days)
            raw_validation = network.predict(scaler.transform(validation[features].to_numpy(float)))
            calibrator = fit_score_calibrator(raw_validation, validation.target.to_numpy(float),
                                               validation.date.to_numpy())
            raw_test = network.predict(scaler.transform(test[features].to_numpy(float)))
            calibrated_test = calibrator.predict(raw_test)
            if not np.isfinite(raw_test).all() or not np.isfinite(calibrated_test).all():
                raise ValueError("nonfinite held-out predictions")
            info.update(network.training_info_)
            info["calibration"] = calibrator.metadata
            info["calibration"]["fit_label_end"] = str(validation.label_end.max().date())
            if artifacts_dir is not None:
                destination = Path(artifacts_dir) / name / "model.joblib"
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".tmp")
                try:
                    joblib.dump(RankModelArtifact(network, scaler, target_scaler, calibrator,
                                                  list(features), name), temporary, compress=3)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
                info["artifact"] = {"file": f"{name}/model.joblib", "sha256": sha256_file(destination),
                                    "format": "joblib", "prediction_input": "unscaled features in lineage.features order"}
            info["status"] = "success"
            predictions[name] = {"raw_score": raw_test, "score": calibrated_test}
        except Exception as error:
            info.update(status="failed", error=f"{type(error).__name__}: {error}")
        metadata[name] = info
    return predictions, metadata


def _replication_description(config):
    horizon = config.get("horizon", 5)
    return {"paper_url": PAPER_URL, "section": "2.2 Alpha Discovery Neural Network",
        "scope": "core grouped soft-rank objective mechanism; not complete ADNN or paper-number reproduction",
        "formula_interpretation": "g(z)=sigmoid(1.83*(z-mean(z))/(2*population_std(z))); loss=-standard Pearson(g(pred),g(target)), averaged equally across dates",
        "deviations": [
            "Existing engineered daily features replace the paper's raw 30-day OHLCV tensor.",
            f"Label is stock open(t+{horizon+1})/open(t+1)-1 minus matching SPY return; the paper uses future close-to-close return.",
            "Current fixed 12-stock US example universe replaces the paper's A-share universe; historical eligibility is unresolved.",
            "Two-hidden-layer tanh NumPy network and fixed-step Adam replace the paper's various feature extractors.",
            "No GP, indicator pretraining, pruning, feature-diversity objective, factor pool, or downstream XGBoost selection is implemented.",
            "Equation 6's ambiguous printed denominator is implemented as standard Pearson correlation, not a literal malformed fraction.",
            "Independent validation fits a nonnegative affine score-to-return calibration for the shared portfolio cost threshold.",
            "One frozen train/validation/test split and seed; no tuning on test and no claim of reproducing the paper's reported IC or returns."]}


def run_rank_experiment(root, *, steps=600, batch_days=8, seed=None):
    """Write an independent real-snapshot run and rank_latest.json, never latest.json."""
    root = Path(root).resolve()
    started, start_clock = datetime.now(timezone.utc), time.perf_counter()
    config = json.loads((root / "config.json").read_text(encoding="utf8"))
    seed = int(config["seed"] if seed is None else seed)
    run_id = "rank_" + started.strftime("%Y%m%dT%H%M%S%fZ") + "_" + sha256_file(root / "config.json")[:8]
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {"status": "failed", "experiment_type": "adnn_soft_rank_mechanism", "run_id": run_id,
        "created_at": started.isoformat(), "config": config, "data": {"source": "moomoo"},
        "experiments": [], "series": {"ic": [], "equity": []}, "predictions": [],
        "training_curves": [], "decision": {}, "replication": _replication_description(config),
        "warnings": []}
    try:
        prices, manifest, quality = load_snapshot(root)
        requested = set(config["universe"]) | {config["benchmark"]}
        missing = requested - set(prices.symbol)
        if missing:
            raise ValueError("missing_requested_symbols:" + ",".join(sorted(missing)))
        prices = prices[prices.symbol.isin(requested)].copy()
        dataset, features, benchmark = build_dataset(prices, config["benchmark"],
            horizon=config["horizon"], lookback=config["lookback"])
        train, validation, test, _, boundaries = split_dataset(dataset,
            validation_days=config["validation_days"], test_days=config["test_days"],
            minimum_train_days=config["minimum_train_days"])
        print(json.dumps({"stage": "rank_training", "run_id": run_id, "features": len(features),
            "train_days": int(train.date.nunique()), "calibration_days": int(validation.date.nunique()),
            "test_days": int(test.date.nunique()), "steps": steps}, ensure_ascii=False), flush=True)
        outputs, metadata = fit_rank_models(train, validation, test, features, seed=seed,
            steps=steps, batch_days=batch_days, artifacts_dir=run_dir / "models")
        if not outputs:
            report["experiments"] = [{"model": name, "metrics": {}, "training": info}
                                     for name, info in metadata.items()]
            raise ValueError("all_rank_models_failed")
        stocks = prices[prices.symbol.isin(config["universe"])]
        cfg = PortfolioConfig(**config["portfolio"])
        backtests = {}
        for name, info in metadata.items():
            if name not in outputs:
                report["experiments"].append({"model": name, "metrics": {}, "training": info})
                continue
            predicted = test[["date", "symbol", "target"]].copy()
            predicted["raw_score"] = outputs[name]["raw_score"]
            predicted["score"] = outputs[name]["score"]
            raw_frame = predicted.copy()
            raw_frame["score"] = predicted["raw_score"]
            raw_ic, calibrated_ic = _rank_ic(raw_frame), _rank_ic(predicted)
            report["series"]["ic"].extend({"model": name, "score_basis": "raw_score", **row} for row in raw_ic)
            result = backtest(stocks, predicted[["date", "symbol", "score"]], benchmark, cfg)
            backtests[name] = result
            report["series"]["equity"].extend({"model": name, **row} for row in result["series"])
            ic_values = [row["value"] for row in raw_ic]
            metrics = {**result["metrics"],
                "rank_ic_mean": float(np.mean(ic_values)) if ic_values else None,
                "rank_ic_std": float(np.std(ic_values, ddof=1)) if len(ic_values) > 1 else None,
                "calibrated_rank_ic_mean": float(np.mean([row["value"] for row in calibrated_ic])) if calibrated_ic else None,
                "n_ic_dates": len(ic_values), "n_test_rows": len(test), "rank_ic_basis": "raw_score",
                "portfolio_score_basis": "validation-calibrated decimal expected excess return"}
            report["experiments"].append({"model": name, "metrics": metrics, "training": info})
            report["training_curves"].extend({"model": name, "loss_name": info["loss_name"], **row}
                                              for row in info["train_loss_history"])
            for row in predicted.itertuples(index=False):
                report["predictions"].append({"date": row.date.strftime("%Y-%m-%d"), "symbol": row.symbol,
                    "model": name, "raw_score": row.raw_score, "score": row.score,
                    "calibrated_score": row.score, "realized_excess": row.target})
        report.update(status="completed", elapsed_seconds=time.perf_counter()-start_clock,
            data={"source": "moomoo frozen daily-bar snapshot", "symbols": sorted(stocks.symbol.unique().tolist()),
                "start": str(prices.date.min().date()), "end": str(prices.date.max().date()),
                "n_dates": int(prices.date.nunique()), "quality": quality, "errors": manifest.get("errors", []),
                "boundaries": boundaries, "universe_confirmed": config.get("universe_confirmed", False)},
            lineage={"seed": seed, "features": features, "split": boundaries,
                "python": platform.python_version(), "data_files": quality["file_hashes"],
                "config_sha256": sha256_file(root / "config.json"),
                "dependencies": {name: importlib.metadata.version(name)
                                 for name in ("numpy", "pandas", "scipy", "scikit-learn", "joblib", "threadpoolctl")},
                "source_hashes": {f"research/{name}": sha256_file(root / "research" / name)
                                  for name in ("rank_experiment.py", "data.py", "portfolio.py", "pipeline.py")},
                "preprocessing_fit_scope": "train only; affine calibration on independent validation only",
                "experiment_settings": {"steps": steps, "batch_days": batch_days, "hidden_sizes": [32,16]}},
            warnings=["Core loss/grouping mechanism only, not complete ADNN or reproduction of paper numbers.",
                "Raw scores have no return units; only independently validation-calibrated scores enter the portfolio.",
                "Negative validation calibration slope is constrained to zero; flat calibration is disclosed and produces no ranking differentiation.",
                "One historical test window and seed; overlapping holding-period labels are not independent observations.",
                "Training loss and calibration fit diagnostics are not held-out alpha evidence.",
                "Present-day fixed example universe, adjusted OHLC, costs and historical eligibility remain prototype assumptions.",
                "Same portfolio execution and risk rules as the main experiment; offline only, no broker submissions."])
        _json_write(run_dir / "backtests.json", backtests)
        _json_write(run_dir / "config.json", config)
        _json_write(run_dir / "snapshot_manifest.json", manifest)
        prices.to_csv(run_dir / "normalized_prices.csv", index=False, date_format="%Y-%m-%d")
        code = 0
    except Exception as error:
        report["status"] = "data_unavailable" if isinstance(error, FileNotFoundError) else "failed"
        report["warnings"].append(f"{type(error).__name__}: {error}")
        _json_write(run_dir / "failure.json", {"error": str(error), "traceback": traceback.format_exc()})
        code = 1
    _json_write(run_dir / "result.json", report)
    _json_write(root / "runs" / "rank_latest.json", report)
    print(json.dumps({"status": report["status"], "run_id": run_id,
        "result": "runs/rank_latest.json", "elapsed_seconds": report.get("elapsed_seconds"),
        "models": {item["model"]: item["training"]["status"] for item in report["experiments"]}},
        ensure_ascii=False), flush=True)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--batch-days", type=int, default=8)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    return run_rank_experiment(args.root, steps=args.steps, batch_days=args.batch_days, seed=args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
