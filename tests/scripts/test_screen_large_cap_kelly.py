import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/screen_large_cap_kelly.py'


def cli():
    spec = importlib.util.spec_from_file_location('large_cap_cli_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def account(name, amount, *, fs='CFS', added=None, receipt='20260814003699', symbol='005930', currency='KRW'):
    row = dict(stock_code=symbol, fs_div=fs, rcept_no=receipt, account_nm=name,
               sj_div='BS' if name in ('자본총계', '부채총계') else 'IS',
               thstrm_amount=str(amount), currency=currency)
    if added is not None:
        row['thstrm_add_amount'] = str(added)
    return row


def test_dart_cumulative_income_and_statement_scope_never_mix():
    module = cli()
    rows = [account('자본총계', '1,000'), account('부채총계', 500),
            account('영업이익', -10, added=80), account('당기순이익', 20, added=60),
            account('자본총계', 9999, fs='OFS'), account('부채총계', 1, fs='OFS')]
    values = module.normalize_dart(rows, period_end='2026-06-30', fetched_at='2026-10-03T00:00:00Z')
    assert len(values) == 1
    assert values[0]['equity'] == 1000
    assert values[0]['net_income'] == 60 and values[0]['operating_profit'] == 80
    assert values[0]['fs_div'] == 'CFS'
    assert values[0]['available_date'] == '2026-08-15'


def test_incomplete_cfs_does_not_borrow_ofs_values():
    module = cli()
    rows = [account('자본총계', 1000), account('부채총계', 500),
            account('영업이익', 80, fs='OFS'), account('당기순이익', 60, fs='OFS')]
    result = module.normalize_dart(rows, period_end='2026-06-30', fetched_at='2026-10-03T00:00:00Z')
    assert result[0]['net_income'] is None and result[0]['operating_profit'] is None


@pytest.mark.parametrize('currency', ['USD', ''])
def test_unverified_currency_is_not_a_krw_financial(currency):
    module = cli()
    rows = [account('자본총계', 1000, currency=currency)]
    assert module.normalize_dart(rows, period_end='2026-06-30', fetched_at='2026-10-03T00:00:00Z') == []


def test_conflicting_same_receipt_accounts_fail_closed():
    module = cli()
    rows = [account('자본총계', 1000), account('자본총계', 2000)]
    with pytest.raises(ValueError, match='Conflicting'):
        module.normalize_dart(rows, period_end='2026-06-30', fetched_at='2026-10-03T00:00:00Z')


def test_quarter_income_without_cumulative_value_is_missing_not_mislabeled():
    module = cli()
    values = module.normalize_dart([account('자본총계', 1000), account('영업이익', 80),
                                   account('당기순이익', 60)],
                                  period_end='2026-06-30', fetched_at='2026-10-03T00:00:00Z')
    assert values[0]['operating_profit'] is None and values[0]['net_income'] is None


def test_listing_rules_exclude_preferred_funds_and_spac(tmp_path):
    module = cli()
    path = tmp_path / 'listing.csv'
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['Code', 'Name', 'Market', 'Marcap', 'Volume'])
        writer.writeheader()
        for code, name in [('005930', '삼성전자'), ('005935', '삼성전자우'),
                           ('069500', 'KODEX 200'), ('000020', '테스트스팩')]:
            writer.writerow(dict(Code=code, Name=name, Market='KOSPI', Marcap=1000, Volume=100))
    rows, evidence = module.load_listing(path, '2026-10-01')
    assert [row['share_type'] for row in rows] == ['common', 'preferred', 'fund', 'spac']
    assert evidence['share_type_method'] == 'code_and_name_rule'
    assert evidence['official_share_type_verified'] is False


def test_rank_before_price_read_and_do_not_backfill_current_caps(tmp_path, monkeypatch):
    module = cli()
    listing = tmp_path / 'listing.csv'
    listing.write_text('Code,Name,Market,Marcap,Volume\n005930,삼성전자,KOSPI,1000,100\n000660,SK하이닉스,KOSPI,500,100\n', encoding='utf-8')
    financials = tmp_path / 'financials.json'
    financials.write_text(json.dumps([dict(symbol='005930', equity=1000, liabilities=500,
        operating_profit=80, net_income=60, available_date='2026-08-15', period_end='2026-06-30',
        fs_div='CFS', source='DART', fetched_at='2026-10-03T00:00:00Z')]), encoding='utf-8')
    observed = []
    def price_reader(path, symbols):
        observed.append(symbols)
        # No prior prices: this is held rather than an invented signal.
        return [dict(symbol='005930', name='삼성전자', date='2026-10-01', close=100)], {'sha256': 'test'}
    monkeypatch.setattr(module, 'load_prices', price_reader)
    out = tmp_path / 'out'
    assert module.main(['--listing', str(listing), '--financials', str(financials),
                        '--prices', 'unused.csv', '--as-of', '2026-10-01', '--top-n', '1', '--out', str(out)]) == 0
    assert observed == [{'005930'}]
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['scope']['ranked_count'] == 1
    assert report['qualified_60pct_symbols'] == []
    assert report['historical_validation']['status'] == 'not_verified'
    assert '당일 가격 후보' in (out / 'report.html').read_text(encoding='utf-8')


def test_no_live_fetch_is_implicitly_enabled(tmp_path, capsys):
    module = cli()
    assert module.main(['--prices', str(tmp_path / 'no.csv'), '--as-of', '2026-10-01']) == 2
    assert 'listing' in capsys.readouterr().err.lower()


def test_cached_dart_retains_its_actual_fetch_time(tmp_path, monkeypatch):
    module = cli()
    codes = tmp_path / 'codes.json'
    codes.write_text(json.dumps({'005930': '00126380'}), encoding='utf-8')
    env = tmp_path / '.env'
    env.write_text('DART_API_KEY=test-only-value\n', encoding='utf-8')
    identity = module.hashlib.sha256(b'00126380').hexdigest()[:16]
    source = tmp_path / 'sources' / f'dart_2026_11012_{identity}.json'
    source.parent.mkdir()
    captured = (module.datetime.now(module.timezone.utc) - module.timedelta(hours=1)).isoformat()
    source.write_text(json.dumps(dict(fetched_at=captured, source=module.DART_API,
        payload=dict(status='000', list=[account('자본총계', 1000)]))), encoding='utf-8')
    def forbidden_network(*args, **kwargs):
        raise AssertionError('Fresh captured stage must be reused')
    monkeypatch.setattr(module, '_get_bytes', forbidden_network)
    rows, evidence = module.fetch_financials({'005930'}, mapping_path=codes, env_file=env,
        year=2026, report_code='11012', out=tmp_path)
    assert rows[0]['fetched_at'] == captured
    assert evidence['calls_this_run'] == 0


def test_absent_new_large_cap_price_is_held_not_replaced_by_lower_rank(tmp_path):
    module = cli()
    prices = tmp_path / 'prices.csv'
    prices.write_text('symbol,date,close\n005930,2026-10-01,100\n', encoding='utf-8')
    rows, evidence = module.load_prices(prices, {'005930', '000660'})
    assert {row['symbol'] for row in rows} == {'005930'}
    assert evidence['missing_symbols'] == ['000660']


def test_original_backtest_price_reader_still_requires_complete_requested_cohort(tmp_path):
    module = cli()
    prices = tmp_path / 'prices.csv'
    prices.write_text('symbol,date,close\n005930,2026-10-01,100\n', encoding='utf-8')
    with pytest.raises(ValueError, match='absent'):
        module.load_price_csv(prices, {'005930', '000660'})
