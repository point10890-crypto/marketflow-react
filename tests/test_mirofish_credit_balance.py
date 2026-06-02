import json

from app.services.mirofish import credit_balance


def test_credit_balance_parser_computes_ratio_from_shares():
    payload = '\n'.join([
        'ticker,date,balance_shares,listed_shares',
        '000001,2026-05-24,5000000,100000000',
    ])

    entries = credit_balance._parse_credit_payload(payload)

    assert entries['000001']['credit_ratio_pct'] == 5.0
    assert entries['000001']['lookahead_safe'] is not False if 'lookahead_safe' in entries['000001'] else True


def test_credit_balance_cache_lookup(tmp_path):
    path = tmp_path / credit_balance.CACHE_FILENAME
    path.write_text(json.dumps({
        'schema_version': 'mirofish.credit_balance.v1',
        'status': 'fresh',
        'fetched_at': '2026-05-24T00:00:00+00:00',
        'entries': {
            '000001': {'symbol': '000001', 'credit_ratio_pct': 4.5},
        },
    }), encoding='utf-8')

    entry = credit_balance.get_credit_entry('000001', data_root=str(tmp_path))

    assert entry['credit_ratio_pct'] == 4.5


def test_credit_balance_missing_fails_open(tmp_path):
    snapshot = credit_balance.get_credit_balance_snapshot(data_root=str(tmp_path))

    assert snapshot['status'] == 'missing'
    assert snapshot['entries'] == {}
