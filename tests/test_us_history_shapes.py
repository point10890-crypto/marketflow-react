"""Historical collection must normalize provider shape, even for one new ticker."""
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from us_market.data_fetcher import USStockDataFetcher


def _fetcher(frame):
    calls = []
    client = USStockDataFetcher.__new__(USStockDataFetcher)
    client.yf_available = True
    client.yf_session = None
    client.finnhub_available = False
    client.yf = SimpleNamespace(download=lambda *args, **kwargs: calls.append((args, kwargs)) or frame.copy())
    return client, calls


@pytest.mark.parametrize('multi_index', [True, False])
def test_one_new_symbol_retains_dates_ohlcv_and_adjusted_column(multi_index):
    frame = pd.DataFrame({
        'Open': [99.0, 101.0], 'High': [102.0, 104.0], 'Low': [98.0, 100.0],
        'Close': [100.0, 103.0], 'Adj Close': [95.0, 97.85], 'Volume': [1000, 1500],
    }, index=pd.DatetimeIndex(['2026-11-05', '2026-11-06'], name='Date'))
    if multi_index:
        frame.columns = pd.MultiIndex.from_tuples([(column, 'OKTA') for column in frame.columns],
                                                 names=['Price', 'Ticker'])
    client, calls = _fetcher(frame)
    result = client.download_history(['OKTA'], datetime(2020, 1, 1), datetime(2026, 11, 6),
                                     delay_between_batches=0)
    assert not isinstance(result.columns, pd.MultiIndex)
    assert result['Ticker'].tolist() == ['OKTA', 'OKTA']
    assert result['Date'].dt.strftime('%Y-%m-%d').tolist() == ['2026-11-05', '2026-11-06']
    assert result['Close'].tolist() == [100.0, 103.0]
    assert result['Adj Close'].tolist() == [95.0, 97.85]
    assert result['Volume'].tolist() == [1000, 1500]
    assert calls[0][1]['end'] == datetime(2026, 11, 7)
    assert 'auto_adjust' not in calls[0][1]  # Preserve the existing provider adjustment policy.


def test_multiple_symbols_remain_distinct_and_keep_all_ohlcv_values():
    fields = ['Open', 'High', 'Low', 'Close', 'Volume']
    columns = pd.MultiIndex.from_product([fields, ['OKTA', 'AAPL']], names=['Price', 'Ticker'])
    frame = pd.DataFrame([[99, 199, 102, 202, 98, 198, 100, 200, 1000, 2000]],
                         index=pd.DatetimeIndex(['2026-11-06'], name='Date'), columns=columns)
    client, _ = _fetcher(frame)
    result = client.download_history(['OKTA', 'AAPL'], datetime(2026, 11, 6), datetime(2026, 11, 6),
                                     delay_between_batches=0)
    assert not isinstance(result.columns, pd.MultiIndex)
    by_symbol = result.set_index('Ticker')
    assert by_symbol.loc['OKTA', fields].tolist() == [99, 102, 98, 100, 1000]
    assert by_symbol.loc['AAPL', fields].tolist() == [199, 202, 198, 200, 2000]
    assert not result.duplicated(['Date', 'Ticker']).any()
