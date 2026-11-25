"""Orchestrate frozen-data experiments, decisions and auditable local reports."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import traceback
import numpy as np
import pandas as pd
from .data import load_snapshot, build_dataset, split_dataset, sha256_file


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    return value


def _json_write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix('.tmp')
    staging.write_text(json.dumps(_clean(document), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    staging.replace(path)


def write_unavailable(root, reason, *, status='data_unavailable'):
    config = json.loads((root / 'config.json').read_text(encoding='utf8'))
    errors = []
    manifest = root / 'data' / 'manifest.json'
    if manifest.exists():
        errors = json.loads(manifest.read_text(encoding='utf8')).get('errors', [])
    report = {'status': status, 'created_at': datetime.now(timezone.utc).isoformat(), 'config': config,
              'data': {'source': 'moomoo', 'symbols': config['universe'], 'errors': errors},
              'experiments': [], 'series': {'ic': [], 'equity': []}, 'predictions': [],
              'decision': {}, 'warnings': [reason]}
    _json_write(root / 'runs' / 'latest.json', report)
    return report


def _rank_ic(test):
    records = []
    for date, group in test.groupby('date'):
        usable = group[['score', 'target']].dropna()
        if len(usable) >= 3 and usable.score.nunique() > 1 and usable.target.nunique() > 1:
            value = usable.score.rank().corr(usable.target.rank())
            if np.isfinite(value):
                records.append({'date': date.strftime('%Y-%m-%d'), 'value': float(value), 'n_symbols': len(usable)})
    return records


def _buy_hold_equal_weight(prices, benchmark, start_date, config):
    """A separate initial-equal-weight buy/hold reference, not factor-selected."""
    capital, cost = float(config['capital']), float(config['cost_bps']) / 10000
    table = prices.pivot(index='date', columns='symbol', values='close').sort_index()
    opening = prices[prices.date.eq(pd.Timestamp(start_date))].set_index('symbol').open
    if opening.empty:
        return {'series': [], 'metrics': {}, 'trades': []}
    budget = capital / len(opening)
    quantities = (budget / (opening * (1 + cost))).apply(np.floor)
    spend = float((quantities * opening).sum())
    cash = capital - spend * (1 + cost)
    bench = benchmark.set_index('date')
    bench_units = capital / float(bench.loc[pd.Timestamp(start_date), 'open'])
    values, last_marks, high = [], opening.to_dict(), capital
    for date, row in table.loc[pd.Timestamp(start_date):].iterrows():
        for symbol in quantities.index:
            if pd.notna(row.get(symbol)):
                last_marks[symbol] = float(row[symbol])
        equity = cash + sum(float(quantities[symbol]) * last_marks[symbol] for symbol in quantities.index)
        high = max(high, equity)
        values.append({'date': date.strftime('%Y-%m-%d'), 'equity': equity,
                       'drawdown': equity / high - 1,
                       'benchmark_equity': float(bench.loc[date, 'close']) * bench_units,
                       'cash_weight': cash / equity, 'turnover': spend / capital if not values else 0.})
    equities = np.array([capital] + [row['equity'] for row in values])
    daily = equities[1:] / equities[:-1] - 1
    volatility = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.
    metrics = {'total_return': float(equities[-1] / capital - 1),
               'cagr': float((equities[-1]/capital)**(252/max(1, len(values)))-1),
               'sharpe': float(np.mean(daily)/volatility*np.sqrt(252)) if volatility > 0 else None,
               'max_drawdown': min((row['drawdown'] for row in values), default=0.),
               'total_cost': spend * cost, 'description': 'initial equal-weight integer-share buy-and-hold; initial buy cost included'}
    return {'series': values, 'metrics': metrics, 'trades': []}


def run_experiment(root: Path):
    from .models import fit_predict_models
    from .portfolio import PortfolioConfig, target_weights, make_order_drafts, backtest
    config = json.loads((root / 'config.json').read_text(encoding='utf8'))
    started = datetime.now(timezone.utc)
    run_id = started.strftime('%Y%m%dT%H%M%SZ') + '_' + sha256_file(root / 'config.json')[:8]
    run_dir = root / 'runs' / run_id
    computational_paths = ['run.py', 'research/data.py', 'research/coverage.py', 'research/models.py', 'research/portfolio.py', 'research/pipeline.py']
    source_hashes = {name: sha256_file(root/name) for name in computational_paths}
    try:
        prices, manifest, quality = load_snapshot(root)
        requested = set(config['universe']) | {config['benchmark']}
        missing = requested - set(prices.symbol)
        if missing:
            raise ValueError('missing_requested_symbols:' + ','.join(sorted(missing)))
        prices = prices[prices.symbol.isin(requested)].copy()
        dataset, features, benchmark = build_dataset(prices, config['benchmark'], horizon=config['horizon'], lookback=config['lookback'])
        train, validation, test, latest, boundaries = split_dataset(dataset,
            validation_days=config['validation_days'], test_days=config['test_days'], minimum_train_days=config['minimum_train_days'])
    except (OSError, ValueError, KeyError) as error:
        status = 'insufficient_data' if 'insufficient' in str(error) else 'data_unavailable'
        write_unavailable(root, str(error), status=status)
        print(json.dumps({'status': status, 'reason': str(error)}, ensure_ascii=False))
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    inputs = pd.concat([test, latest], ignore_index=True)
    print(json.dumps({'stage': 'training', 'train_rows': len(train), 'validation_rows': len(validation),
                      'test_rows': len(test), 'features': len(features), 'boundaries': boundaries}, ensure_ascii=False), flush=True)
    try:
        # All estimators and generators are fitted exclusively inside this call on train.
        import inspect
        kwargs = {'seed': config['seed'], 'config': config, 'train_dates': train.date}
        if 'artifacts_dir' in inspect.signature(fit_predict_models).parameters:
            kwargs['artifacts_dir'] = run_dir / 'models'
        outputs, metadata = fit_predict_models(train[features].to_numpy(), train.target.to_numpy(),
            validation[features].to_numpy(), validation.target.to_numpy(), inputs[features].to_numpy(), **kwargs)
        experiment_rows, ic_rows, equity_rows, prediction_rows, backtests = [], [], [], [], {}
        portfolio_config = PortfolioConfig(**config['portfolio'])
        stocks = prices[prices.symbol.isin(config['universe'])]
        for model, output in outputs.items():
            test_predictions = test[['date', 'symbol', 'target']].copy()
            test_predictions['score'] = np.asarray(output[:len(test)])
            daily_ic = _rank_ic(test_predictions)
            for row in daily_ic:
                ic_rows.append({'model': model, **row})
            signal_frame = test_predictions[['date', 'symbol', 'score']]
            result = backtest(stocks, signal_frame, benchmark, portfolio_config)
            backtests[model] = result
            for row in result['series']:
                equity_rows.append({'model': model, **row})
            ic_values = [row['value'] for row in daily_ic]
            metrics = {**result['metrics'], 'rank_ic_mean': float(np.mean(ic_values)) if ic_values else None,
                       'rank_ic_std': float(np.std(ic_values, ddof=1)) if len(ic_values) > 1 else None,
                       'n_ic_dates': len(ic_values), 'n_test_rows': len(test_predictions)}
            experiment_rows.append({'model': model, 'metrics': metrics, 'training': metadata[model]})
            for row in test_predictions.itertuples(index=False):
                prediction_rows.append({'date': row.date.strftime('%Y-%m-%d'), 'symbol': row.symbol,
                                        'model': model, 'score': row.score, 'realized_excess': row.target})
        if not outputs:
            raise ValueError('all_models_failed')
        for model, info in metadata.items():
            if info.get('status') != 'success':
                experiment_rows.append({'model': model, 'metrics': {}, 'training': info})
        first_result = next(iter(backtests.values()))
        if first_result.get('rebalances'):
            first_execution = first_result['rebalances'][0]['execution_date']
            reference = _buy_hold_equal_weight(stocks, benchmark, first_execution, config['portfolio'])
            experiment_rows.append({'model': 'equal_weight_buy_hold', 'metrics': reference['metrics'],
                                    'training': {'status': 'reference', 'kind': 'initial_equal_weight_buy_hold'}})
            equity_rows.extend({'model': 'equal_weight_buy_hold', **row} for row in reference['series'])
        decision_model = config['decision_model']
        decision = {'model': decision_model, 'capital': config['portfolio']['capital'], 'orders': [], 'weights': {}, 'gates': []}
        if decision_model in outputs:
            scores = pd.Series(outputs[decision_model][len(test):], index=latest.symbol, name='score')
            as_of = latest.date.max()
            history = stocks[stocks.date.le(as_of)].pivot(index='date', columns='symbol', values='close').sort_index().pct_change(fill_method=None)
            weights, diagnostics = target_weights(scores, history, portfolio_config)
            reference_prices = latest.set_index('symbol').reference_price.to_dict()
            orders = make_order_drafts(weights, reference_prices, config['portfolio']['capital'],
                                       current_quantities={}, as_of=as_of.strftime('%Y-%m-%d'), run_id=run_id, config=portfolio_config)
            decision.update({'as_of': as_of.strftime('%Y-%m-%d'), 'weights': weights, 'diagnostics': diagnostics,
                             'orders': orders, 'reference_prices': reference_prices,
                             'scores': scores.to_dict(), 'holdings_assumption': 'independent paper portfolio starts with cash; no real holdings read',
                             'requires_requote': True, 'can_submit': False})
            if not config.get('universe_confirmed'):
                decision['gates'].append('HOLDINGS_UNIVERSE_NOT_CONFIRMED')
            if (started.date() - as_of.date()).days > 7:
                decision['gates'].append('REFERENCE_DATA_STALE')
            decision['gates'].append('REFERENCE_PRICES_ONLY_NO_BROKER_SUBMISSION')
        else:
            decision['gates'].append('CONFIGURED_DECISION_MODEL_FAILED')
        package_versions = {name: importlib.metadata.version(name) for name in ('numpy', 'pandas', 'scipy', 'scikit-learn', 'plotly', 'streamlit', 'joblib', 'threadpoolctl')}
        report = {'status': 'completed', 'run_id': run_id, 'created_at': started.isoformat(), 'config': config,
                  'data': {'source': 'moomoo', 'symbols': sorted(stocks.symbol.unique().tolist()),
                           'start': str(prices.date.min().date()), 'end': str(prices.date.max().date()),
                           'n_dates': int(prices.date.nunique()), 'quality': quality, 'errors': manifest.get('errors', []),
                           'universe_confirmed': config.get('universe_confirmed', False), 'boundaries': boundaries},
                  'experiments': experiment_rows, 'series': {'ic': ic_rows, 'equity': equity_rows},
                  'predictions': prediction_rows, 'decision': decision,
                  'lineage': {'python': platform.python_version(), 'dependencies': package_versions,
                              'seed': config['seed'], 'features': features, 'data_files': quality['file_hashes'],
                              'config_sha256': sha256_file(root/'config.json'), 'source_hashes': source_hashes,
                              'preprocessing_fit_scope': 'training only', 'split': boundaries},
                  'warnings': ['Prototype fixed present-day universe: historical eligibility and survivorship bias are not resolved.',
                               'Adjusted OHLC is a return proxy; historical cash dividends, tradable raw prices and split-adjusted quantities require separate validation.',
                               'Only one historical test window and one random seed are run; overlapping 5-day labels are not independent observations.',
                               'No exact ADNN/DARL replication is claimed. Conditional DDPM samples labels, not joint market paths.',
                               'Decision capital and current holdings are independent paper assumptions, not the real brokerage account.',
                               'No transaction can be submitted by this software. Reference order prices require a new quote.']}
        if not config.get('universe_confirmed'):
            report['warnings'].append('The configured research universe is not a confirmed list of user holdings.')
        if quality.get('large_daily_moves_to_review'):
            report['warnings'].append('Daily price changes above 30% were flagged for source/corporate-action review; they were not silently removed.')
        _json_write(run_dir/'result.json', report)
        _json_write(run_dir/'config.json', config)
        _json_write(run_dir/'backtests.json', backtests)
        _json_write(root/'runs'/'latest.json', report)
        normalized = run_dir/'normalized_prices.csv'
        prices.to_csv(normalized, index=False, date_format='%Y-%m-%d')
        _json_write(run_dir/'snapshot_manifest.json', manifest)
        print(json.dumps({'status': 'completed', 'run_id': run_id, 'models': {name: info['status'] for name, info in metadata.items()},
                          'data_end': report['data']['end'], 'result': 'runs/latest.json',
                          'orders': len(decision['orders'])}, ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        _json_write(run_dir/'failure.json', {'type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc()})
        write_unavailable(root, f'{type(error).__name__}: {error}', status='failed')
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 1
