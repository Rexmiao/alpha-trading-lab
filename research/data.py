"""Point-in-time market-data normalization and chronological dataset construction."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def completed_session_cutoff(now=None):
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    # A conservative buffer excludes a possibly unfinished current daily candle.
    return (current.date() if current.time() >= time(16, 20)
            else (pd.Timestamp(current.date()) - pd.Timedelta(days=1)).date())


def normalize_observation(observation, *, cutoff=None):
    symbol = str(observation['symbol']).removeprefix('US.')
    rows, rejected = [], []
    for item in observation.get('data', {}).get('kl_list', []):
        raw_date = item.get('time', item.get('time_key', item.get('timestamp')))
        try:
            if isinstance(raw_date, (int, float)):
                day = pd.to_datetime(raw_date, unit='s', utc=True).tz_convert('America/New_York').date()
            else:
                day = pd.Timestamp(str(raw_date)[:10]).date()
            if cutoff is not None and day > cutoff:
                continue
            values = {key: float(item[key] if key in item else item[key + '_price'])
                      for key in ('open', 'high', 'low', 'close')}
            values['volume'] = float(item['volume'])
            if not all(np.isfinite(v) for v in values.values()):
                raise ValueError('nonfinite')
            if item.get('is_blank', False):
                raise ValueError('blank_candle')
            if min(values[k] for k in ('open', 'high', 'low', 'close')) <= 0 or values['volume'] < 0:
                raise ValueError('invalid_price_or_volume')
            if values['low'] > min(values['open'], values['close']) or values['high'] < max(values['open'], values['close']) or values['high'] < values['low']:
                raise ValueError('inconsistent_ohlc')
            rows.append({'date': pd.Timestamp(day), 'symbol': symbol, **values})
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            rejected.append({'symbol': symbol, 'date': str(raw_date), 'reason': str(error)[:80]})
    frame = pd.DataFrame(rows, columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
    if frame.duplicated(['date', 'symbol']).any():
        raise ValueError(f'duplicate_daily_bar:{symbol}')
    return frame.sort_values(['date', 'symbol']).reset_index(drop=True), rejected


def load_snapshot(root: Path):
    manifest_path = root / 'data' / 'manifest.json'
    if not manifest_path.exists():
        raise FileNotFoundError('No moomoo snapshot. Run python run.py collect.')
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    frames, rejected, hashes = [], [], []
    cutoff = completed_session_cutoff()
    for record in manifest.get('files', []):
        path = (root / record['path']).resolve()
        if not path.is_relative_to((root / 'data' / 'raw').resolve()):
            raise ValueError('snapshot_path_outside_raw_directory')
        actual_hash = sha256_file(path)
        if actual_hash != record['sha256']:
            raise ValueError('snapshot_hash_mismatch:' + record['symbol'])
        observation = json.loads(path.read_text(encoding='utf8'))
        normalized, errors = normalize_observation(observation, cutoff=cutoff)
        frames.append(normalized)
        rejected.extend(errors)
        hashes.append({'symbol': record['symbol'], 'sha256': actual_hash})
    if not frames:
        raise ValueError('No usable moomoo market observations in snapshot.')
    data = pd.concat(frames, ignore_index=True).sort_values(['date', 'symbol'])
    raw_counts = data.groupby('symbol').size().astype(int).to_dict()
    coverage, boundary_audit = {}, []
    config_path = root / 'config.json'
    if config_path.exists():
        # Import only when called: coverage uses build_dataset from this module.
        from .coverage import apply_history_boundaries, assess_coverage
        config = json.loads(config_path.read_text(encoding='utf8'))
        coverage = assess_coverage(data, config)
        data, boundary_audit = apply_history_boundaries(data, config)
    changes = data.sort_values(['symbol', 'date']).copy()
    changes['return_1d'] = changes.groupby('symbol').close.pct_change(fill_method=None)
    large_moves = changes.loc[changes.return_1d.abs().gt(.30), ['date','symbol','return_1d']].copy()
    large_moves['date'] = large_moves.date.dt.strftime('%Y-%m-%d')
    quality = {'rejected_rows': rejected, 'completed_session_cutoff': str(cutoff), 'file_hashes': hashes,
               'bars_by_symbol': data.groupby('symbol').size().astype(int).to_dict(),
               'raw_bars_by_symbol': raw_counts, 'coverage': coverage,
               'history_boundary_audit': boundary_audit,
               'large_daily_moves_to_review': large_moves.to_dict('records'),
               'large_move_policy': 'flag absolute close-to-close changes above 30%; never silently delete or repair'}
    return data, manifest, quality


def build_dataset(prices, benchmark_symbol, *, horizon=5, lookback=30):
    if horizon < 1 or lookback < 5:
        raise ValueError('invalid_horizon_or_lookback')
    data = prices.copy()
    data['date'] = pd.to_datetime(data['date'])
    if data.duplicated(['date', 'symbol']).any():
        raise ValueError('duplicate_daily_bar')
    benchmark = data[data.symbol.eq(benchmark_symbol)].sort_values('date').copy()
    if benchmark.empty:
        raise ValueError('benchmark_missing')
    # Reindex on actual benchmark sessions, so a missing bar never becomes a shortened horizon.
    sessions = pd.DatetimeIndex(benchmark.date)
    bench = benchmark.set_index('date').reindex(sessions)
    bench_target = bench.open.shift(-(horizon+1)) / bench.open.shift(-1) - 1
    market_return = bench.close.pct_change(fill_method=None)
    rows, feature_columns = [], []
    for symbol, original in data[~data.symbol.eq(benchmark_symbol)].groupby('symbol'):
        frame = original.set_index('date').sort_index().reindex(sessions)
        returns = frame.close.pct_change(fill_method=None)
        features = pd.DataFrame(index=sessions)
        for lag in range(lookback):
            features[f'return_lag_{lag}'] = returns.shift(lag)
        for period in (5, 10, 20):
            features[f'momentum_{period}'] = frame.close / frame.close.shift(period) - 1
            features[f'vol_{period}'] = returns.rolling(period, min_periods=period).std()
        features['intraday_return'] = frame.close / frame.open - 1
        features['high_low_range'] = frame.high / frame.low - 1
        features['volume_ratio'] = frame.volume / frame.volume.rolling(20, min_periods=20).mean() - 1
        features['market_return'] = market_return
        features['relative_momentum_5'] = features['momentum_5'] - (bench.close / bench.close.shift(5) - 1)
        feature_columns = list(features.columns)
        features['target'] = frame.open.shift(-(horizon+1)) / frame.open.shift(-1) - 1 - bench_target
        features['label_end'] = pd.Series(sessions, index=sessions).shift(-(horizon+1))
        features['date'] = sessions
        features['symbol'] = symbol
        features['reference_price'] = frame.close
        features = features.replace([np.inf, -np.inf], np.nan)
        rows.append(features.dropna(subset=feature_columns + ['reference_price']).reset_index(drop=True))
    if not rows:
        raise ValueError('stock_universe_empty')
    dataset = pd.concat(rows, ignore_index=True).sort_values(['date', 'symbol']).reset_index(drop=True)
    return dataset, feature_columns, benchmark


def split_dataset(dataset, *, validation_days=50, test_days=100, minimum_train_days=120):
    eligible = dataset.dropna(subset=['target', 'label_end'])
    dates = pd.DatetimeIndex(sorted(eligible.date.unique()))
    required = validation_days + test_days + minimum_train_days
    if len(dates) < required:
        raise ValueError(f'insufficient_history:{len(dates)}_eligible_days_need_{required}')
    validation_start, test_start = dates[-(validation_days+test_days)], dates[-test_days]
    train = eligible[(eligible.date < validation_start) & (eligible.label_end < validation_start)].copy()
    validation = eligible[(eligible.date >= validation_start) & (eligible.date < test_start) & (eligible.label_end < test_start)].copy()
    test = eligible[eligible.date >= test_start].copy()
    if train.date.nunique() < minimum_train_days or validation.empty or test.empty:
        raise ValueError('insufficient_history_after_label_purging')
    latest_date = dataset.date.max()
    latest = dataset[dataset.date.eq(latest_date)].copy()
    return train, validation, test, latest, {
        'train_start': str(train.date.min().date()), 'train_end': str(train.date.max().date()),
        'train_label_end': str(train.label_end.max().date()),
        'validation_start': str(validation_start.date()), 'validation_end': str(validation.date.max().date()),
        'validation_label_end': str(validation.label_end.max().date()), 'test_start': str(test_start.date()),
        'test_end': str(test.date.max().date()), 'purged_train_rows': int(((eligible.date < validation_start) & (eligible.label_end >= validation_start)).sum()),
        'purged_validation_rows': int(((eligible.date >= validation_start) & (eligible.date < test_start) & (eligible.label_end >= test_start)).sum())}
