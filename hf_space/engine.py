"""Bounded in-memory simulations for the public teaching app.

This adapter never loads local snapshots, credentials, configs, runs or models.
Uploaded CSV is parsed as data only. Synthetic prices are explicitly teaching
data, with no claim that their performance represents an investable strategy.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
from importlib.metadata import version
from io import BytesIO
import math
from pathlib import Path
import re
import threading
import time

import numpy as np
import pandas as pd

from research.data import build_dataset, completed_session_cutoff, split_dataset
from research.models import MODEL_NAMES, fit_predict_models
from research.portfolio import PortfolioConfig, backtest, target_weights


COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume")
MAX_UPLOAD_BYTES = 3 * 1024 * 1024
MAX_ROWS = 8000
MAX_DATES = 600
MAX_TRAIN_ROWS = 3000
_SIMULATION_LOCK = threading.BoundedSemaphore(1)
MODEL_SETTINGS = {
    "ridge_alpha": 10.0,
    "mlp_max_iter": 20,
    "mlp_batch_size": 128,
    "mlp_hidden_sizes": (24, 12),
    "mlp_learning_rate": .001,
    "mlp_alpha": .001,
    "synthetic_ratio": .25,
    "diffusion_steps": 8,
    "diffusion_train_steps": 40,
    "diffusion_batch_size": 128,
    "diffusion_components": 8,
    "diffusion_hidden_sizes": (24, 12),
}

# Fingerprint only this adapter and the three public computational sources.
# No snapshot, configuration, model, credential or result paths are inspected.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CODE_SHA256 = {name: hashlib.sha256((_PROJECT_ROOT / name).read_bytes()).hexdigest()
                for name in ("hf_space/engine.py", "research/data.py",
                             "research/models.py", "research/portfolio.py")}
_DEPENDENCIES = {name: version(name) for name in
                 ("numpy", "pandas", "scipy", "scikit-learn", "joblib", "threadpoolctl",
                  "pyarrow", "streamlit", "plotly")}


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}].")
    return int(value)


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} must be numeric.")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and in [{low}, {high}].")
    return value


def _symbol(value):
    value = str(value).strip().upper()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,19}", value) is None:
        raise ValueError("Symbols must contain 1 to 20 letters, digits, dots, underscores or hyphens.")
    return value


def _validate_prices(prices, benchmark):
    """Return a fresh normalized frame; validation is repeated at the API boundary."""
    benchmark = _symbol(benchmark)
    if not isinstance(prices, pd.DataFrame) or set(prices.columns) != set(COLUMNS):
        raise ValueError("CSV must contain exactly: date,symbol,open,high,low,close,volume.")
    if prices.empty or len(prices) > MAX_ROWS:
        raise ValueError(f"Provide 1 to {MAX_ROWS} daily rows.")
    frame = prices.loc[:, list(COLUMNS)].copy()
    if frame.isna().any().any():
        raise ValueError("Missing values are not accepted; do not fill unavailable market history.")
    if pd.api.types.is_datetime64_any_dtype(frame.date.dtype):
        parsed = pd.to_datetime(frame.date, errors="raise")
        if parsed.dt.tz is not None or not parsed.eq(parsed.dt.normalize()).all():
            raise ValueError("Dates must be timezone-free daily dates (YYYY-MM-DD).")
    else:
        values = frame.date.astype(str)
        if not values.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
            raise ValueError("Dates must use YYYY-MM-DD, without time or timezone.")
        parsed = pd.to_datetime(values, format="%Y-%m-%d", errors="raise")
    cutoff = pd.Timestamp(completed_session_cutoff())
    if parsed.isna().any() or (parsed > cutoff).any():
        raise ValueError("Future or not-yet-completed US daily bars are not accepted.")
    if (parsed.dt.dayofweek > 4).any():
        raise ValueError("US stock daily bars must use weekday sessions.")
    frame["date"] = parsed
    frame["symbol"] = frame.symbol.map(_symbol)
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("Duplicate date/symbol daily bars are not accepted.")
    for column in COLUMNS[2:]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    numeric = frame[list(COLUMNS[2:])].to_numpy(float)
    if not np.isfinite(numeric).all():
        raise ValueError("OHLCV values must be finite numbers.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError("Prices must be positive; volume must be nonnegative.")
    if ((frame.high < frame[["open", "low", "close"]].max(axis=1)) |
            (frame.low > frame[["open", "high", "close"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC: low <= open/close <= high is required.")
    symbols = set(frame.symbol)
    if benchmark not in symbols:
        raise ValueError(f"Benchmark {benchmark} is missing from the CSV.")
    if not 3 <= len(symbols - {benchmark}) <= 12:
        raise ValueError("Provide 3 to 12 stock symbols plus a separate benchmark.")
    sessions = pd.DatetimeIndex(frame.loc[frame.symbol.eq(benchmark), "date"])
    if len(sessions) > MAX_DATES or frame.date.nunique() > MAX_DATES:
        raise ValueError(f"The public demo accepts at most {MAX_DATES} distinct dates.")
    if not frame.date.isin(sessions).all():
        raise ValueError("Every stock date must have a benchmark bar; benchmark defines the session calendar.")
    return frame.sort_values(["date", "symbol"]).reset_index(drop=True)


def parse_csv(contents: bytes, benchmark="SPY"):
    """Parse a bounded UTF-8 CSV; accepts bytes, never a path, URL or pickle."""
    if not isinstance(contents, bytes):
        raise TypeError("CSV contents must be bytes, not a filename or URL.")
    if not contents or len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload a nonempty CSV no larger than 3 MiB.")
    try:
        frame = pd.read_csv(BytesIO(contents), encoding="utf-8-sig", dtype={"date": str, "symbol": str},
                            keep_default_na=False, nrows=MAX_ROWS + 1, on_bad_lines="error")
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise ValueError("CSV could not be parsed as a UTF-8 daily OHLCV table.") from exc
    return _validate_prices(frame, benchmark)


def make_synthetic_prices(seed=42, periods=400, n_assets=6):
    """Make correlated fictional OHLCV, not historical quotes or an alpha claim.

    BENCH and TOY1..TOYn use a weekday teaching calendar starting in 2020.
    It intentionally does not claim to reproduce an exchange holiday calendar.
    """
    seed = _integer(seed, "seed", 0, 2**32 - 1)
    periods = _integer(periods, "periods", 200, MAX_DATES)
    n_assets = _integer(n_assets, "n_assets", 3, 12)
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2020-01-02", periods=periods)
    market_overnight = rng.normal(0.0, .003, periods)
    market_intraday = rng.normal(.00015, .006, periods)
    rows = []
    for index, symbol in enumerate(["BENCH"] + [f"TOY{i+1}" for i in range(n_assets)]):
        if index == 0:
            overnight, intraday = market_overnight, market_intraday
        else:
            beta = .7 + .1 * index
            overnight = beta * market_overnight + rng.normal(0.0, .004, periods)
            intraday = beta * market_intraday + rng.normal(0.0, .01, periods)
        previous_close = 100.0 + 5 * index
        for offset, session in enumerate(sessions):
            opening = previous_close * math.exp(float(overnight[offset]))
            close = opening * math.exp(float(intraday[offset]))
            spread = abs(float(rng.normal(.004, .002)))
            rows.append({"date": session, "symbol": symbol, "open": opening,
                         "high": max(opening, close) * (1 + spread),
                         "low": min(opening, close) / (1 + spread), "close": close,
                         "volume": float(rng.integers(100_000, 3_000_000))})
            previous_close = close
    return _validate_prices(pd.DataFrame(rows, columns=COLUMNS), "BENCH")


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _rank_ic(predictions, model):
    records = []
    for day, group in predictions.groupby("date"):
        if len(group) >= 3 and group.score.nunique() > 1 and group.target.nunique() > 1:
            value = group.score.rank().corr(group.target.rank())
            if np.isfinite(value):
                records.append({"date": day.strftime("%Y-%m-%d"), "model": model,
                                "value": float(value), "n_symbols": len(group)})
    return records


def run_simulation(prices, *, benchmark, source, seed=42, horizon=5,
                   cost_bps=10, max_weight=.2, target_vol=.15):
    """Run one bounded simulation; refuse parallel training instead of queuing data."""
    if not _SIMULATION_LOCK.acquire(blocking=False):
        raise ValueError("The shared CPU is running another simulation. Please try again shortly.")
    try:
        return _run_simulation(prices, benchmark=benchmark, source=source, seed=seed,
            horizon=horizon, cost_bps=cost_bps, max_weight=max_weight, target_vol=target_vol)
    finally:
        _SIMULATION_LOCK.release()


def _run_simulation(prices, *, benchmark, source, seed=42, horizon=5,
                    cost_bps=10, max_weight=.2, target_vol=.15):
    """Run the four real estimators in memory and return JSON-safe result tables.

    The synthetic source marker is a caller declaration, never an inference from
    profitability. Predictions, IC and equity retain that marker in lineage.
    No files are written; no estimator objects or filesystem paths are returned.
    Fixed public source fingerprints are captured once when this module loads.
    """
    if source not in {"synthetic", "uploaded_csv"}:
        raise ValueError("source must be 'synthetic' or 'uploaded_csv'.")
    seed = _integer(seed, "seed", 0, 2**32 - 1)
    horizon = _integer(horizon, "horizon", 1, 20)
    cost_bps = _number(cost_bps, "cost_bps", 0, 100)
    max_weight = _number(max_weight, "max_weight", .05, .5)
    target_vol = _number(target_vol, "target_vol", 0, .5)
    benchmark = _symbol(benchmark)
    prices = _validate_prices(prices, benchmark)
    started = time.perf_counter()
    dataset, features, benchmark_prices = build_dataset(prices, benchmark, horizon=horizon, lookback=30)
    train, validation, test, latest, boundaries = split_dataset(
        dataset, validation_days=30, test_days=60, minimum_train_days=90)
    if len(train) > MAX_TRAIN_ROWS:
        raise ValueError(f"{len(train)} training rows exceed the public CPU budget of {MAX_TRAIN_ROWS}; "
                         "reduce stock count or history length. No rows were silently sampled away.")
    cfg = PortfolioConfig(capital=100_000.0, top_k=4, max_weight=max_weight,
        min_cash_weight=.2, target_annual_vol=target_vol, cost_bps=cost_bps,
        rebalance_days=horizon, min_expected_excess=2 * cost_bps / 10000)
    inputs = pd.concat([test, latest], ignore_index=True)
    outputs, training = fit_predict_models(
        train[features].to_numpy(float), train.target.to_numpy(float),
        validation[features].to_numpy(float), validation.target.to_numpy(float),
        inputs[features].to_numpy(float), seed=seed, config=MODEL_SETTINGS,
        train_dates=train.date, artifacts_dir=None)
    stocks = prices.loc[~prices.symbol.eq(benchmark)]
    historical_returns = stocks.pivot(index="date", columns="symbol", values="close").reindex(
        pd.DatetimeIndex(benchmark_prices.date)).pct_change(fill_method=None)
    warnings = [
        "Research simulation only. No broker, account, current quote or order submission is connected.",
        "Only training rows fit scalers, predictors and the conditional generator; validation is diagnostic only.",
        "Short holdout periods and overlapping multi-day labels do not establish stable alpha or independent IC samples.",
        "Changing settings after inspecting test results is exploratory, not a fresh out-of-sample test.",
    ]
    if source == "synthetic":
        warnings.insert(0, "ILLUSTRATIVE SYNTHETIC DATA ONLY: fictional assets and weekday calendar; "
                        "all resulting returns and IC describe this teaching simulation, not market evidence.")
    else:
        warnings.append("Uploaded prices are visitor-supplied and unverified. Use consistently adjusted OHLC; "
                        "corporate actions, delistings and historical universe membership are not reconstructed.")
    expected_rows = len(benchmark_prices) * prices.symbol.nunique()
    if len(prices) < expected_rows:
        warnings.append("Some stock sessions are missing. No prices or IPO history are filled; "
                        "features/labels may be unavailable and a held-position missing price can fail evaluation.")
    changes = prices.groupby("symbol").close.pct_change(fill_method=None)
    large_move_count = int(changes.abs().gt(.30).sum())
    if large_move_count:
        warnings.append(f"{large_move_count} daily close moves exceed 30%; flagged for review, never silently repaired.")
    result = {"source": source, "status": "failed", "metrics": [], "ic": [], "equity": [],
              "predictions": [], "weights": [], "warnings": warnings, "lineage": {}}
    model_status, latest_risk = {}, {}
    for model in MODEL_NAMES:
        info = training.get(model, {"status": "failed", "error": "No training metadata returned."})
        if info.get("status") != "success" or model not in outputs:
            error = info.get("error", "Model did not return predictions.")
            model_status[model] = {"status": "failed", "stage": "training", "error": error}
            result["metrics"].append({"model": model, "status": "failed", "total_return": None,
                "sharpe": None, "max_drawdown": None, "rank_ic_mean": None})
            continue
        try:
            values = np.asarray(outputs[model], dtype=float)
            if values.shape != (len(inputs),) or not np.isfinite(values).all():
                raise ValueError("Model prediction shape or finiteness is invalid.")
            heldout = test[["date", "symbol", "target"]].copy()
            heldout["score"] = values[:len(test)]
            daily_ic = _rank_ic(heldout, model)
            simulation = backtest(stocks, heldout[["date", "symbol", "score"]], benchmark_prices, cfg)
            latest_scores = pd.Series(values[len(test):], index=latest.symbol)
            allocation, risk = target_weights(latest_scores,
                historical_returns.loc[:latest.date.max()], cfg)
            ic_values = [row["value"] for row in daily_ic]
            result["metrics"].append({"model": model, "status": "success", **simulation["metrics"],
                "rank_ic_mean": float(np.mean(ic_values)) if ic_values else None,
                "rank_ic_std": float(np.std(ic_values, ddof=1)) if len(ic_values) > 1 else None,
                "n_ic_dates": len(ic_values), "n_test_rows": len(test)})
            result["ic"].extend(daily_ic)
            result["equity"].extend({"model": model, **row} for row in simulation["series"])
            result["predictions"].extend({"model": model, "date": row.date.strftime("%Y-%m-%d"),
                "symbol": row.symbol, "score": row.score, "realized_excess": row.target}
                for row in heldout.itertuples(index=False))
            result["weights"].extend({"model": model, "symbol": symbol, "weight": weight, "kind": "asset"}
                                     for symbol, weight in sorted(allocation.items()))
            result["weights"].append({"model": model, "symbol": "__CASH__", "weight": 1 - sum(allocation.values()), "kind": "cash"})
            latest_risk[model] = risk
            result["warnings"].extend(simulation.get("warnings", []))
            model_status[model] = {"status": "success", "stage": "evaluated", "error": None}
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            model_status[model] = {"status": "failed", "stage": "evaluation", "error": error}
            result["metrics"].append({"model": model, "status": "failed", "total_return": None,
                "sharpe": None, "max_drawdown": None, "rank_ic_mean": None})
    canonical_bytes = prices.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.17g").encode("utf8")
    result["status"] = "success" if any(v["status"] == "success" for v in model_status.values()) else "failed"
    result["lineage"] = {
        "engine": "public_in_memory_v1", "data": {"source": source,
            "educational_only": source == "synthetic", "sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            "rows": len(prices), "symbols": sorted(prices.symbol.unique()), "benchmark": benchmark,
            "start": prices.date.min().strftime("%Y-%m-%d"), "end": prices.date.max().strftime("%Y-%m-%d"),
            "completed_session_cutoff": str(completed_session_cutoff()), "large_move_count": large_move_count,
            "calendar": "synthetic weekdays, not exchange holidays" if source == "synthetic" else "uploaded benchmark sessions"},
        "config": {"seed": seed, "horizon": horizon, "lookback": 30,
            "validation_days": 30, "test_days": 60, "minimum_train_days": 90,
            "models": dict(MODEL_SETTINGS), "portfolio": vars(cfg)},
        "split": {**boundaries, "train_rows": len(train), "validation_rows": len(validation),
                  "test_rows": len(test), "train_days": train.date.nunique(),
                  "validation_days": validation.date.nunique(), "test_days": test.date.nunique()},
        "features": features, "models": training, "model_status": model_status,
        "latest_weights_as_of": latest.date.max().strftime("%Y-%m-%d"),
        "latest_weights_scope": "hypothetical target allocation after the final completed uploaded/synthetic bar; not an order",
        "latest_risk": latest_risk, "elapsed_seconds": time.perf_counter() - started,
        "limits": {"upload_bytes": MAX_UPLOAD_BYTES, "rows": MAX_ROWS, "dates": MAX_DATES,
                   "stock_symbols": 12, "train_rows": MAX_TRAIN_ROWS},
        "method_scope": "Small-budget method illustration; not full ADNN or DARL replication.",
        "label": "next-session open to horizon+1 session open stock return minus benchmark return",
        "code_sha256": dict(_CODE_SHA256), "dependencies": dict(_DEPENDENCIES),
        "storage": "Only fixed public Python source files are read for fingerprints; no market/config/model reads or writes. Upload/session retention is managed by the UI.",
    }
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    return _json_safe(result)
