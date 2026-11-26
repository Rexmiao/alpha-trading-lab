"""Independent timestamp, causality, calendar and ledger checks for RTH rules."""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

from hf_space import intraday as engine


def prices(sessions=None, *, flat=False):
    """Explicit UTC test oracles: two normal days straddling US DST."""
    sessions = sessions or [
        ("2024-03-08", "14:30", 78), ("2024-03-11", "13:30", 78)]
    rows = []
    for day_number, (day, opening, count) in enumerate(sessions):
        for index, stamp in enumerate(pd.date_range(f"{day}T{opening}:00Z", periods=count, freq="5min")):
            for asset_number, symbol in enumerate(("AAA", "BBB", "SPY")):
                base = 100 + asset_number * 10 + day_number
                op = base if flat else base + index * .12
                close = op if flat else op + .08
                rows.append([stamp, symbol, op, max(op, close) + .02,
                             min(op, close) - .02, close, 1000 + index])
    return pd.DataFrame(rows, columns=engine.COLUMNS)


def csv_bytes(frame):
    return frame.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ", lineterminator="\n").encode()


@pytest.fixture(scope="module")
def two_days():
    return prices()


@pytest.fixture(scope="module")
def result(two_days):
    return engine.run_intraday_comparison(two_days)


def test_schema_json_and_reproducible_lineage(two_days, result):
    assert result["status"] == "success"
    assert set(result) == {"source", "status", "metrics", "equity", "signals", "weights", "trades",
                           "session_metrics", "lineage", "warnings"}
    json.dumps(result, allow_nan=False)
    assert {row["strategy"] for row in result["metrics"]} == set(engine.STRATEGY_IDS)
    lineage = result["lineage"]
    normalized = two_days.astype({column: float for column in engine.COLUMNS[2:]})
    assert lineage["data"]["sha256"] == hashlib.sha256(csv_bytes(normalized)).hexdigest()
    assert lineage["code_sha256"]["hf_space/intraday.py"] == hashlib.sha256(
        __import__("pathlib").Path(engine.__file__).read_bytes()).hexdigest()
    assert lineage["calendar"]["version"] == "4.11.2"
    for dependency in ("numpy", "pandas", "exchange-calendars", "tzdata", "python-dateutil", "pytz", "six"):
        assert lineage["dependencies"][dependency]


def test_csv_roundtrip_utc_and_no_daily_conversion(two_days):
    restored = engine.parse_intraday_csv(csv_bytes(two_days))
    pd.testing.assert_frame_equal(restored, engine._validate(two_days, "SPY"))
    assert restored.timestamp.dt.tz is not None
    assert restored.timestamp.nunique() == 156
    assert restored.timestamp.dt.date.nunique() == 2


@pytest.mark.parametrize("bad", ["a.csv", "https://example.org/prices.csv", bytearray(b"x"), None])
def test_csv_bytes_only(bad):
    with pytest.raises(TypeError):
        engine.parse_intraday_csv(bad)


def test_csv_size_and_row_bounds(two_days):
    with pytest.raises(engine.IntradayError, match="8 MiB"):
        engine.parse_intraday_csv(b"x" * (engine.MAX_UPLOAD_BYTES + 1))
    with pytest.raises(engine.IntradayError, match="50000"):
        engine._validate(pd.concat([two_days] * 108, ignore_index=True), "SPY")


@pytest.mark.parametrize("change,match", [
    ("naive", "UTC ISO"), ("local", "UTC ISO"), ("off_grid", "five-minute"),
    ("nan", "Missing"), ("partial", "finite"), ("ohlc", "Invalid OHLC"),
    ("negative_volume", "nonnegative"), ("infinity", "finite"),
    ("duplicate", "Duplicate"), ("url_symbol", "uppercase"), ("lowercase", "uppercase"),
    ("boolean", "Boolean"), ("extra_column", "exactly"), ("duplicate_column", "exactly")])
def test_rejects_invalid_uploads(two_days, change, match):
    frame = two_days.copy()
    if change in {"naive", "local", "off_grid"}:
        frame["timestamp"] = frame.timestamp.map(lambda value: value.isoformat().replace("+00:00", "Z"))
        frame.loc[0, "timestamp"] = {
            "naive": "2024-03-08T14:30:00", "local": "2024-03-08T09:30:00-05:00",
            "off_grid": "2024-03-08T14:31:00Z"}[change]
    elif change == "nan": frame.loc[0, "close"] = np.nan
    elif change == "partial": frame.loc[0, "close"] = ""
    elif change == "ohlc": frame.loc[0, "low"] = 999
    elif change == "negative_volume": frame.loc[0, "volume"] = -1
    elif change == "infinity": frame.loc[0, "close"] = np.inf
    elif change == "duplicate": frame = pd.concat([frame, frame.iloc[[0]]])
    elif change == "url_symbol": frame.loc[0, "symbol"] = "https://localhost"
    elif change == "lowercase": frame.loc[0, "symbol"] = "aaa"
    elif change == "boolean":
        frame["volume"] = frame.volume.astype(object)
        frame.loc[0, "volume"] = True
    elif change == "extra_column": frame["date"] = "2024-03-08"
    elif change == "duplicate_column": frame = pd.concat([frame, frame[["close"]]], axis=1)
    with pytest.raises(engine.IntradayError, match=match):
        engine._validate(frame, "SPY")


def test_symbol_and_benchmark_limits(two_days):
    with pytest.raises(engine.IntradayError, match="separate benchmark"):
        engine._validate(two_days[two_days.symbol != "SPY"], "SPY")
    pieces = [two_days[two_days.symbol == "SPY"]]
    for index in range(13):
        pieces.append(two_days[two_days.symbol == "AAA"].assign(symbol=f"ASSET{index}"))
    with pytest.raises(engine.IntradayError, match="1 to 12"):
        engine._validate(pd.concat(pieces), "SPY")


def test_calendar_dst_and_explicit_half_day(result):
    complete = result["lineage"]["coverage"]["complete_sessions"]
    assert [(r["open"], r["expected_bars"]) for r in complete] == [
        ("2024-03-08T14:30:00Z", 78), ("2024-03-11T13:30:00Z", 78)]
    frame = prices([("2024-07-03", "13:30", 42), ("2024-07-05", "13:30", 78)])
    output = engine.run_intraday_comparison(frame)
    complete = output["lineage"]["coverage"]["complete_sessions"]
    assert [(r["session"], r["close"], r["expected_bars"]) for r in complete] == [
        ("2024-07-03", "2024-07-03T17:00:00Z", 42),
        ("2024-07-05", "2024-07-05T20:00:00Z", 78)]
    assert not any(r["session"] == "2024-07-04" for r in output["session_metrics"])
    july3 = [row for row in output["trades"] if row["session"] == "2024-07-03"]
    assert all(row["execution_at"] <= "2024-07-03T16:55:00Z" for row in july3)
    assert any(row["reason"] == "scheduled_last_bar_open_flatten" and
               row["execution_at"] == "2024-07-03T16:55:00Z" for row in july3)


def test_one_session_returns_insufficient_history_without_calendar_error(two_days):
    output = engine.run_intraday_comparison(two_days[two_days.timestamp.dt.day == 8])
    assert output["status"] == "insufficient_history"
    assert not output["metrics"] and not output["trades"]
    assert output["lineage"]["coverage"]["usable_session_count"] == 1


def test_no_execution_window_half_days_are_not_successful_cash_experiments():
    frame = prices([("2024-11-29", "14:30", 42), ("2024-12-24", "14:30", 42)])
    output = engine.run_intraday_comparison(frame, slow_bars=60)
    assert output["status"] == "insufficient_history"
    assert not output["metrics"] and not output["equity"] and not output["trades"]
    coverage = output["lineage"]["coverage"]
    assert coverage["complete_session_count"] == 2
    assert coverage["usable_session_count"] == 0
    reasons = {row["reason"] for row in coverage["excluded_sessions"]
               if row["session"] in {"2024-11-29", "2024-12-24"}}
    assert reasons == {"insufficient_intraday_window"}


def test_delay_and_rebalance_anchor_determine_usable_common_days():
    frame = prices([("2024-07-02", "13:30", 78), ("2024-07-03", "13:30", 42),
                    ("2024-07-05", "13:30", 78)])
    # SMA40 first exists at index39; halfday index39 can reach index40 only at delay0.
    output = engine.run_intraday_comparison(frame, slow_bars=40, execution_delay_bars=1)
    assert output["status"] == "success"
    coverage = output["lineage"]["coverage"]
    assert coverage["complete_session_count"] == 3 and coverage["usable_session_count"] == 2
    assert {row["session"] for row in output["session_metrics"]} == {"2024-07-02", "2024-07-05"}
    assert next(row for row in coverage["excluded_sessions"] if row["session"] == "2024-07-03")["reason"] == "insufficient_intraday_window"
    no_delay = engine.run_intraday_comparison(frame, slow_bars=40, execution_delay_bars=0)
    assert no_delay["lineage"]["coverage"]["usable_session_count"] == 3
    anchored = engine.run_intraday_comparison(frame, slow_bars=40, rebalance_bars=10)
    assert anchored["lineage"]["coverage"]["usable_session_count"] == 2


def test_missing_bar_excludes_whole_common_day_without_fill():
    frame = prices([("2024-03-08", "14:30", 78), ("2024-03-11", "13:30", 78),
                    ("2024-03-12", "13:30", 78)])
    missing = (frame.symbol == "AAA") & (frame.timestamp == pd.Timestamp("2024-03-11T14:00:00Z"))
    output = engine.run_intraday_comparison(frame.loc[~missing])
    coverage = output["lineage"]["coverage"]
    assert coverage["complete_session_count"] == 2 and coverage["no_gap_filling"]
    excluded = next(row for row in coverage["excluded_sessions"] if row["session"] == "2024-03-11")
    assert excluded["reason"] == "missing_common_RTH_bars"
    assert excluded["by_symbol"] == {"AAA": {"missing_bars": 1, "sample_utc": ["2024-03-11T14:00:00Z"]}}
    for collection in ("equity", "trades", "signals", "session_metrics"):
        assert not any(row["session"] == "2024-03-11" for row in output[collection])


def test_pre_and_post_market_are_reported_not_traded(two_days):
    before = two_days.iloc[:3].copy()
    before["timestamp"] = pd.Timestamp("2024-03-08T14:25:00Z")
    output = engine.run_intraday_comparison(pd.concat([two_days, before]))
    assert output["lineage"]["coverage"]["excluded_non_RTH_rows"] == 3
    assert not any(row["timestamp"] == "2024-03-08T14:25:00Z" for row in output["signals"])


def test_incomplete_current_session_excluded_and_future_bars_rejected(two_days, monkeypatch):
    monkeypatch.setattr(engine, "_now_utc", lambda: pd.Timestamp("2024-03-11T15:00:00Z"))
    with pytest.raises(engine.IntradayError, match="Future or not-yet-completed"):
        engine.run_intraday_comparison(two_days)
    past_only = two_days[two_days.timestamp + engine.BAR_DURATION <= engine._now_utc()]
    output = engine.run_intraday_comparison(past_only)
    assert output["status"] == "insufficient_history"
    excluded = output["lineage"]["coverage"]["excluded_sessions"]
    assert next(row for row in excluded if row["session"] == "2024-03-11")["reason"] == "session_not_completed"
    monkeypatch.setattr(engine, "_now_utc", lambda: pd.Timestamp("2024-03-08T14:33:00Z"))
    with pytest.raises(engine.IntradayError, match="not-yet-completed"):
        engine.parse_intraday_csv(csv_bytes(two_days.iloc[:3]))


def test_shared_warmup_and_signal_close_to_execution_open(result):
    warmup = result["lineage"]["config"]["common_warmup_bars"]
    assert warmup == 11
    for strategy in engine.STRATEGY_IDS:
        rows = [r for r in result["signals"] if r["strategy"] == strategy and r["symbol"] == "AAA"
                and r["session"] == "2024-03-08"]
        assert all(r["status"] == "common_warmup" and not r["eligible"] and r["execution_at"] is None for r in rows[:warmup])
        first_trade = next(r for r in result["trades"] if r["strategy"] == strategy)
        assert first_trade["signal_available_at"] == "2024-03-08T15:30:00Z"
        assert first_trade["execution_at"] == first_trade["signal_available_at"]
    for trade in result["trades"]:
        if trade["reason"] == "rule_rebalance":
            assert trade["execution_at"] == trade["signal_available_at"]


def test_extra_bar_delay_never_crosses_session(two_days):
    output = engine.run_intraday_comparison(two_days, execution_delay_bars=1)
    assert output["trades"]
    for trade in output["trades"]:
        executed = pd.Timestamp(trade["execution_at"])
        if trade["reason"] == "rule_rebalance":
            assert executed - pd.Timestamp(trade["signal_available_at"]) == engine.BAR_DURATION
        assert executed.tz_convert("America/New_York").strftime("%Y-%m-%d") == trade["session"]
    for signal in output["signals"]:
        if signal["execution_at"] is not None:
            assert pd.Timestamp(signal["execution_at"]) < pd.Timestamp(f'{signal["session"]}T20:55:00Z')


def test_opening_range_frozen_state_has_no_rolling_or_future_dependency():
    close = np.array([100] * 6 + [106, 104, 100, 94, 100, 107], float).reshape(-1, 1)
    high = close + 1
    low = close - 1
    high[:6] = 105
    low[:6] = 95
    cfg = dict(lookback_bars=2, fast_bars=2, slow_bars=3, opening_range_bars=6)
    scores, held, _ = engine._rules(close, high, low, cfg)["opening_range_breakout"]
    assert held.ravel().tolist() == [False] * 6 + [True, True, True, False, False, True]
    np.testing.assert_allclose(scores[6:, 0], close[6:, 0] / 105 - 1)
    truncated = engine._rules(close[:10], high[:10], low[:10], cfg)["opening_range_breakout"]
    np.testing.assert_allclose(scores[:10], truncated[0], equal_nan=True)
    np.testing.assert_array_equal(held[:10], truncated[1])


def test_append_future_sessions_does_not_change_past_outputs():
    earlier = engine.make_synthetic_intraday_prices(days=3)
    later = engine.make_synthetic_intraday_prices(days=5)
    first = engine.run_intraday_comparison(earlier, benchmark="BENCH", source="synthetic")
    appended = engine.run_intraday_comparison(later, benchmark="BENCH", source="synthetic")
    last_session = "2024-03-12"
    for key in ("equity", "signals", "trades", "session_metrics"):
        assert first[key] == [row for row in appended[key] if row["session"] <= last_session]
    assert first["lineage"]["benchmark"]["trades"] == [
        row for row in appended["lineage"]["benchmark"]["trades"] if row["session"] <= last_session]


def test_cost_components_integer_cash_and_independent_ledger(two_days, result):
    price_map = {(row.timestamp.isoformat().replace("+00:00", "Z"), row.symbol): row.open
                 for row in two_days.itertuples()}
    for strategy in engine.STRATEGY_IDS:
        cash, quantities, total_cost = 100000., {"AAA": 0, "BBB": 0}, 0.
        trades = [row for row in result["trades"] if row["strategy"] == strategy]
        for trade in trades:
            assert isinstance(trade["quantity"], int) and trade["quantity"] > 0
            assert trade["reference_price"] == price_map[trade["execution_at"], trade["symbol"]]
            notional = trade["quantity"] * trade["reference_price"]
            assert trade["notional"] == pytest.approx(notional)
            assert trade["fee"] == pytest.approx(notional * .001)
            assert trade["spread_cost"] == pytest.approx(notional * .0001)
            assert trade["slippage_cost"] == pytest.approx(notional * .0001)
            assert trade["total_cost"] == pytest.approx(notional * .0012)
            cash -= trade["quantity_delta"] * trade["reference_price"] + trade["total_cost"]
            quantities[trade["symbol"]] += trade["quantity_delta"]
            total_cost += trade["total_cost"]
            assert cash >= -1e-7 and quantities[trade["symbol"]] >= 0
            assert trade["cash_after"] == pytest.approx(cash)
            assert trade["position_after"] == quantities[trade["symbol"]]
        assert set(quantities.values()) == {0}
        metric = next(row for row in result["metrics"] if row["strategy"] == strategy)
        assert metric["total_return"] == pytest.approx(cash / 100000 - 1)
        assert metric["total_cost"] == pytest.approx(total_cost)
        assert metric["trade_count"] == len(trades)
        assert metric["sharpe"] is None and metric["annualized_volatility"] is None


def test_scheduled_last_open_flatten_and_benchmark_costs(result):
    ends = {"2024-03-08": "2024-03-08T20:55:00Z", "2024-03-11": "2024-03-11T19:55:00Z"}
    for strategy in engine.STRATEGY_IDS:
        for day, terminal in ends.items():
            trades = [row for row in result["trades"] if row["strategy"] == strategy and row["session"] == day]
            assert any(r["reason"] == "scheduled_last_bar_open_flatten" for r in trades)
            assert all(r["execution_at"] <= terminal for r in trades)
            assert all(r["side"] == "SELL" for r in trades if r["execution_at"] == terminal)
    assert all(row["end_positions"] == 0 for row in result["session_metrics"])
    bench = result["lineage"]["benchmark"]
    assert bench["trade_count"] == 4
    assert bench["total_cost"] == pytest.approx(sum(row["notional"] * .0012 for row in bench["trades"]))
    assert all(r["price"] == pytest.approx(r["reference_price"] * (1.0002 if r["side"] == "BUY" else .9998))
               for r in bench["trades"])
    for day in ends:
        trades = [row for row in bench["trades"] if row["session"] == day]
        assert [r["side"] for r in trades] == ["BUY", "SELL"]
        assert sum(row["quantity_delta"] for row in trades) == 0


def test_targets_are_historical_references_separate_from_actual_cash(result):
    for strategy in engine.STRATEGY_IDS:
        target = [r for r in result["weights"] if r["strategy"] == strategy and r["kind"] == "target"]
        actual = [r for r in result["weights"] if r["strategy"] == strategy and r["kind"] == "actual"]
        assert {r["symbol"] for r in target} == {"AAA", "BBB", "__CASH__"}
        assert sum(r["weight"] for r in target) == pytest.approx(1)
        assert all(r["weight"] <= .2 for r in target if r["asset_kind"] == "asset")
        assert next(r["weight"] for r in target if r["symbol"] == "__CASH__") >= .2
        assert len({r["as_of"] for r in target}) == 1
        assert all(r["as_of"] == r["execution_at"] for r in target)
        assert len(actual) == 1 and actual[0]["symbol"] == "__CASH__" and actual[0]["weight"] == 1
        assert actual[0]["as_of"] > target[0]["execution_at"]


def test_constant_prices_have_no_trades_and_truthful_zero_target():
    output = engine.run_intraday_comparison(prices(flat=True))
    assert output["status"] == "success" and not output["trades"]
    assert all(r["equity"] == 100000 and r["cash"] == 100000 for r in output["equity"])
    for target in [r for r in output["weights"] if r["kind"] == "target"]:
        assert target["weight"] == (1 if target["asset_kind"] == "cash" else 0)
    assert all(r["trade_count"] == 0 and r["total_return"] == 0 for r in output["metrics"])


def test_annualization_uses_daily_portfolio_returns_only():
    output = engine.run_intraday_comparison(engine.make_synthetic_intraday_prices(days=20),
                                           benchmark="BENCH", source="synthetic")
    for metric in output["metrics"]:
        returns = np.array([r["return"] for r in output["session_metrics"] if r["strategy"] == metric["strategy"]])
        assert len(returns) == 20 and metric["n_sessions"] == 20
        assert metric["annualized_volatility"] == pytest.approx(returns.std(ddof=1) * math.sqrt(252))
        assert metric["sharpe"] == pytest.approx(returns.mean() / returns.std(ddof=1) * math.sqrt(252))


@pytest.mark.parametrize("kwargs", [dict(lookback_bars=True), dict(fast_bars=12),
    dict(cost_bps=-1), dict(half_spread_bps=float("nan")), dict(source="online_history"),
    dict(execution_delay_bars=.5), dict(cash_floor=1), dict(initial_cash=99)])
def test_parameter_rejection_releases_worker(two_days, kwargs):
    with pytest.raises(engine.IntradayError):
        engine.run_intraday_comparison(two_days, **kwargs)
    assert engine._BUSY.acquire(blocking=False)
    engine._BUSY.release()


def test_busy_worker_is_explicit(two_days):
    engine._BUSY.acquire()
    try:
        with pytest.raises(engine.IntradayError, match="busy"):
            engine.run_intraday_comparison(two_days)
    finally:
        engine._BUSY.release()


def test_research_never_writes_market_data_or_state(two_days, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = engine.run_intraday_comparison(two_days)
    assert output["status"] == "success"
    assert list(tmp_path.iterdir()) == []
