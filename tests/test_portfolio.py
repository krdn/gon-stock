from datetime import date, timedelta
from random import Random

import pytest


def fixture():
    dates = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(61)]
    candidates = [
        {'symbol': s, 'name': s, 'group': g, 'exchange': 'XNAS', 'currency': 'USD'}
        for s, g in [('AAA', 'tech'), ('BBB', 'tech'), ('CCC', 'bank')]
    ]
    series = {}
    for n, s in enumerate(['AAA', 'BBB', 'CCC']):
        rng = Random(n)
        price = 100.0
        rows = []
        for day in dates:
            price *= 1 + rng.uniform(-0.005, 0.005)
            rows.append(
                {
                    'date': day,
                    'open': str(price),
                    'high': str(price + 1),
                    'low': str(price - 1),
                    'close': str(price),
                    'volume': str(100000 // (n + 1)),
                }
            )
        series[s] = rows
    return candidates, series, dates


def api():
    import importlib.util

    assert importlib.util.find_spec('gon_stock.portfolio') is not None, (
        'portfolio screening missing'
    )
    from gon_stock.portfolio import screen_market

    return screen_market


def test_liquidity_rank_and_group_constraint():
    candidates, series, dates = fixture()
    result = api()(candidates, series, series, dates, dates[-1])
    assert result['selected'] == ['AAA', 'CCC']
    assert result['statistics'][0]['symbol'] == 'AAA'
    assert result['selection_reasons']['BBB'] == 'same_group'
    assert result['statistics'][0]['return_observations'] == 60
    assert abs(result['correlations']['AAA|CCC']) < 0.8


def test_future_rows_cannot_change_selection_or_statistics():
    from copy import deepcopy

    candidates, series, dates = fixture()
    expected = api()(candidates, series, series, dates, dates[-1])
    changed = deepcopy(series)
    changed['CCC'].append(
        {**changed['CCC'][-1], 'date': '2027-01-01', 'close': '1000000', 'high': '1000000'}
    )
    assert api()(candidates, changed, changed, dates + ['2027-01-01'], dates[-1]) == expected


def test_missing_invalid_or_duplicate_rows_are_excluded():
    from copy import deepcopy

    for case in ['missing', 'ohlc', 'duplicate']:
        candidates, series, dates = fixture()
        changed = deepcopy(series)
        if case == 'missing':
            changed['AAA'].pop(10)
        elif case == 'ohlc':
            changed['AAA'][10]['high'] = '1'
        else:
            changed['AAA'].append(changed['AAA'][10])
        result = api()(candidates, changed, series, dates, dates[-1])
        assert 'AAA' not in result['selected']
        assert 'AAA' in result['excluded']
        assert len(result['selected']) <= 2


def test_high_correlation_stays_in_cash_slot_instead_of_forcing_pair():
    from copy import deepcopy

    candidates, series, dates = fixture()
    changed = deepcopy(series)
    changed['CCC'] = deepcopy(series['AAA'])
    for row in changed['CCC']:
        row['volume'] = '1000'
    result = api()(candidates, changed, changed, dates, dates[-1])
    assert result['selected'] == ['AAA']
    assert result['selection_reasons']['CCC'] == 'high_correlation'


def test_short_reference_window_fails():
    candidates, series, dates = fixture()
    with pytest.raises(ValueError, match='insufficient_reference_sessions'):
        api()(candidates, series, series, dates[:60], dates[-1])
