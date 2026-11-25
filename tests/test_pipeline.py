from pathlib import Path
import numpy as np
import pandas as pd
from research.pipeline import _buy_hold_equal_weight, _rank_ic


def test_equal_weight_reference_cannot_buy_at_signal_open():
    dates = pd.bdate_range('2024-01-02', periods=3)
    prices = pd.DataFrame({'date': dates, 'symbol': ['A']*3,
                           'open': [1., 10., 10.], 'close': [10., 10., 10.]})
    benchmark = pd.DataFrame({'date': dates, 'open': [1., 10., 10.], 'close': [10., 10., 10.]})
    result = _buy_hold_equal_weight(prices, benchmark, dates[1], {'capital': 100., 'cost_bps': 0.})
    assert [row['date'] for row in result['series']] == ['2024-01-03', '2024-01-04']
    assert result['metrics']['total_return'] == 0.


def test_equal_weight_fees_are_charged_once():
    dates = pd.bdate_range('2024-01-02', periods=3)
    prices = pd.DataFrame({'date': dates, 'symbol': ['A']*3, 'open': [10.]*3, 'close': [10.]*3})
    benchmark = prices[['date','open','close']]
    result = _buy_hold_equal_weight(prices, benchmark, dates[0], {'capital': 100., 'cost_bps': 100.})
    assert np.isclose(result['metrics']['total_cost'], .9)
    assert all(np.isclose(row['equity'], 99.1) for row in result['series'])


def test_rank_ic_computed_within_date_not_pooled():
    dates = [pd.Timestamp('2024-01-02')]*3 + [pd.Timestamp('2024-01-03')]*3
    data = pd.DataFrame({'date': dates, 'score': [1,2,3,100,200,300], 'target': [1,2,3,-1,-2,-3]})
    values = _rank_ic(data)
    assert np.isclose(values[0]['value'], 1.)
    assert np.isclose(values[1]['value'], -1.)
