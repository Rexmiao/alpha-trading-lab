"""Synthetic offline fixtures for time semantics, never experiment results."""
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from research.data import (
    build_dataset,
    completed_session_cutoff,
    normalize_observation,
    split_dataset,
)


@pytest.fixture
def synthetic_prices():
    dates = pd.bdate_range("2024-01-02", periods=120)
    rows = []
    for i, day in enumerate(dates):
        for symbol, base, slope in (("A", 100.0, 1.0), ("B", 80.0, 0.7), ("SPY", 200.0, 0.4)):
            opening = base + slope * i + (i % 3) * 0.2
            closing = opening * (1 + 0.003 * np.sin(i + len(symbol)))
            rows.append({"date": day, "symbol": symbol, "open": opening,
                         "high": max(opening, closing) * 1.01,
                         "low": min(opening, closing) * 0.99,
                         "close": closing, "volume": 1000.0 + i * 10})
    return dates, pd.DataFrame(rows)


def _at(frame, day, symbol, field):
    return float(frame.loc[frame["date"].eq(day) & frame["symbol"].eq(symbol), field].iloc[0])


@pytest.mark.parametrize("horizon", [1, 5])
def test_label_is_next_open_to_h_plus_one_open_minus_same_benchmark(synthetic_prices, horizon):
    dates, prices = synthetic_prices
    dataset, _, _ = build_dataset(prices, "SPY", horizon=horizon, lookback=5)
    signal = dates[30]
    row = dataset.loc[dataset.date.eq(signal) & dataset.symbol.eq("A")].iloc[0]
    end = dates[30 + horizon + 1]
    entry = dates[31]
    expected = (_at(prices, end, "A", "open") / _at(prices, entry, "A", "open") - 1
                - (_at(prices, end, "SPY", "open") / _at(prices, entry, "SPY", "open") - 1))
    assert row.target == pytest.approx(expected)
    assert row.label_end == end
    old_close_formula = (_at(prices, dates[30 + horizon], "A", "close") / _at(prices, entry, "A", "open") - 1
                         - (_at(prices, dates[30 + horizon], "SPY", "close") / _at(prices, entry, "SPY", "open") - 1))
    assert abs(row.target - old_close_formula) > 1e-6


def test_future_truncation_preserves_every_past_feature(synthetic_prices):
    dates, prices = synthetic_prices
    full, feature_names, _ = build_dataset(prices, "SPY", horizon=5, lookback=10)
    cutoff = dates[60]
    truncated, truncated_names, _ = build_dataset(prices.loc[prices.date.le(cutoff)], "SPY", horizon=5, lookback=10)
    columns = ["date", "symbol", *feature_names, "reference_price"]
    assert feature_names == truncated_names
    pd.testing.assert_frame_equal(full.loc[full.date.le(cutoff), columns].reset_index(drop=True),
                                  truncated[columns].reset_index(drop=True), check_exact=True)
    last = truncated.loc[truncated.date.eq(cutoff)]
    assert not last.empty
    assert last.target.isna().all()  # Latest decisions exist without fabricated outcomes.


def test_future_mutation_cannot_change_features_at_or_before_signal(synthetic_prices):
    dates, prices = synthetic_prices
    full, columns, _ = build_dataset(prices, "SPY", horizon=5, lookback=10)
    mutated = prices.copy()
    future = mutated.date.gt(dates[60])
    mutated.loc[future, ["open", "high", "low", "close", "volume"]] *= 7
    changed, _, _ = build_dataset(mutated, "SPY", horizon=5, lookback=10)
    fields = ["date", "symbol", *columns]
    pd.testing.assert_frame_equal(full.loc[full.date.le(dates[60]), fields].reset_index(drop=True),
                                  changed.loc[changed.date.le(dates[60]), fields].reset_index(drop=True),
                                  check_exact=True)


def test_time_split_purges_labels_before_next_partition_for_all_stocks(synthetic_prices):
    dates, prices = synthetic_prices
    dataset, _, _ = build_dataset(prices, "SPY", horizon=5, lookback=10)
    train, validation, test, latest, metadata = split_dataset(dataset, validation_days=15,
                                                            test_days=15, minimum_train_days=30)
    validation_start = pd.Timestamp(metadata["validation_start"])
    test_start = pd.Timestamp(metadata["test_start"])
    assert train.date.max() < validation_start
    assert train.label_end.max() < validation_start
    assert validation.date.min() >= validation_start
    assert validation.date.max() < test_start
    assert validation.label_end.max() < test_start
    assert test.date.min() >= test_start
    assert not (set(train.date) & set(validation.date) or set(train.date) & set(test.date)
                or set(validation.date) & set(test.date))
    assert metadata["purged_train_rows"] == 12  # Six overlapping label dates, two symbols.
    assert metadata["purged_validation_rows"] == 12
    assert latest.date.unique().tolist() == [dates[-1]]
    assert latest.target.isna().all()
    for partition in (train, validation, test):
        assert partition.groupby("date").symbol.nunique().eq(2).all()


@pytest.mark.parametrize("missing_offset", [1, 6])
def test_missing_label_endpoint_stays_missing_not_shifted_to_another_session(synthetic_prices, missing_offset):
    dates, prices = synthetic_prices
    missing = (prices.symbol.eq("A") & prices.date.eq(dates[30 + missing_offset]))
    dataset, _, _ = build_dataset(prices.loc[~missing], "SPY", horizon=5, lookback=5)
    row = dataset.loc[dataset.date.eq(dates[30]) & dataset.symbol.eq("A")].iloc[0]
    assert pd.isna(row.target)
    assert row.label_end == dates[36]


def test_missing_interior_stock_bar_does_not_shorten_trading_horizon(synthetic_prices):
    dates, prices = synthetic_prices
    missing = prices.symbol.eq("A") & prices.date.eq(dates[33])
    dataset, _, _ = build_dataset(prices.loc[~missing], "SPY", horizon=5, lookback=5)
    row = dataset.loc[dataset.date.eq(dates[30]) & dataset.symbol.eq("A")].iloc[0]
    expected = (_at(prices, dates[36], "A", "open") / _at(prices, dates[31], "A", "open")
                - _at(prices, dates[36], "SPY", "open") / _at(prices, dates[31], "SPY", "open"))
    assert row.target == pytest.approx(expected)
    assert row.label_end == dates[36]


def test_duplicate_dataset_daily_bar_is_rejected(synthetic_prices):
    _, prices = synthetic_prices
    with pytest.raises(ValueError, match="duplicate_daily_bar"):
        build_dataset(pd.concat([prices, prices.iloc[[30]]], ignore_index=True), "SPY")


def _observation(*bars):
    return {"symbol": "US.A", "data": {"kl_list": list(bars)}}


def test_moomoo_real_ohlc_field_names_are_normalized():
    observation = _observation({"time": "2024-01-02 00:00:00", "open_price": 100,
                                "high_price": 103, "low_price": 99,
                                "close_price": 102, "volume": 5000})
    normalized, rejected = normalize_observation(observation, cutoff=date(2024, 1, 3))
    assert rejected == []
    assert len(normalized) == 1
    row = normalized.iloc[0]
    assert (row.symbol, row.date, row.open, row.high, row.low, row.close, row.volume) == (
        "A", pd.Timestamp("2024-01-02"), 100, 103, 99, 102, 5000)


def test_normalization_excludes_incomplete_future_day_and_records_invalid_ohlc():
    valid = {"time": "2024-01-02", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 5000}
    invalid = {**valid, "time": "2024-01-03", "high": 90}
    future = {**valid, "time": "2024-01-05"}
    normalized, rejected = normalize_observation(_observation(valid, invalid, future), cutoff=date(2024, 1, 4))
    assert normalized.date.tolist() == [pd.Timestamp("2024-01-02")]
    assert len(rejected) == 1
    assert "inconsistent_ohlc" in rejected[0]["reason"]


def test_duplicate_normalized_daily_bar_is_rejected():
    bar = {"time": "2024-01-02", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 5000}
    with pytest.raises(ValueError, match="duplicate_daily_bar"):
        normalize_observation(_observation(bar, dict(bar)))


def test_completed_cutoff_uses_new_york_time_and_conservative_close_buffer():
    # January 16:00 New York is 21:00 UTC; fixture is independent of host timezone.
    assert completed_session_cutoff(datetime(2024, 1, 23, 21, 0, tzinfo=timezone.utc)) == date(2024, 1, 22)
    assert completed_session_cutoff(datetime(2024, 1, 23, 21, 21, tzinfo=timezone.utc)) == date(2024, 1, 23)


def test_short_history_cannot_silently_reduce_required_training_days(synthetic_prices):
    _, prices = synthetic_prices
    dataset, _, _ = build_dataset(prices, "SPY", horizon=5, lookback=10)
    with pytest.raises(ValueError, match="insufficient_history"):
        split_dataset(dataset, validation_days=15, test_days=15, minimum_train_days=100)
