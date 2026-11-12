import csv
import importlib.util
from pathlib import Path

from app.services.forecast_league import bars

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'audit_league_price_sources.py'
spec = importlib.util.spec_from_file_location('audit_league_price_sources', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_preclose_share_counts_rows_captured_before_the_close(tmp_path):
    path = tmp_path / 'daily_prices.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['ticker', 'date', 'name', 'current_price', 'change', 'change_rate', 'high', 'low',
                         'open', 'volume', 'update_time'])
        writer.writerow(['005930', '2026-07-30', 'x', 1, 0, 0, 1, 1, 1, 1, '2026-07-30 14:52:15'])
        writer.writerow(['005930', '2026-07-31', 'x', 1, 0, 0, 1, 1, 1, 1, '2026-07-31 16:10:00'])
        writer.writerow(['005930', '2026-06-30', 'x', 1, 0, 0, 1, 1, 1, 1, '2026-07-02 20:00:00'])
    assert audit.preclose_share(str(path)) == {
        '2026-06': {'rows': 1, 'pre_close': 0}, '2026-07': {'rows': 2, 'pre_close': 1}}


def test_compare_bases_counts_field_mismatches(league_conn):
    def put(code, basis, **over):
        values = dict(open=100.0, high=110.0, low=95.0, close=105.0)
        values.update(over)
        bars.put_bar(league_conn, stock_code=code, session_date='2026-11-12', basis=basis, captured_at='t', **values)

    put('005930', bars.BASIS_REGULAR)
    put('005930', bars.BASIS_UNIVERSE, close=104.0, low=94.0)
    put('000660', bars.BASIS_REGULAR)
    put('000660', bars.BASIS_UNIVERSE)
    put('035420', bars.BASIS_REGULAR)                    # 한쪽에만 있음 → 비교하지 않음
    assert audit.compare_bases(league_conn, '2026-11-12') == {
        'session': '2026-11-12', 'compared': 2, 'mismatch': {'open': 0, 'high': 0, 'low': 1, 'close': 1}}
