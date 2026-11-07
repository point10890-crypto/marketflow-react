"""Read-only coverage evidence must not turn a newly written partial CSV green."""
import csv
from datetime import datetime
import json
import os

import pytest

from app.services import institutional_collection_status as service


NOW = datetime.fromisoformat('2026-11-08T12:05:00+09:00')


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def evidence(tmp_path, *, failed=1, source='2026-11-06', collected='2026-11-08T12:00:00'):
    codes = ['005930', '000660']
    successful = 2-failed
    outcomes = [{'ticker': code, 'status': 'success' if i < successful else 'failed',
                 'reason': 'current_source_history' if i < successful else 'invalid_or_empty_response',
                 **({'data_date': source, 'total_days': 60} if i < successful else {})}
                for i,code in enumerate(codes)]
    status = {'collected_at': collected, 'attempted': 2, 'successful': successful,
              'failed': failed, 'skipped': 0, 'usable_results': successful,
              'status': 'failed' if not successful else ('partial' if failed else 'completed'),
              'requested_codes': codes, 'failed_codes': codes[successful:], 'outcomes': outcomes}
    (tmp_path/'institutional_collection_status.json').write_text(json.dumps(status), encoding='utf8')
    metadata = {'collection_date': collected.replace('T', ' '), 'total_stocks': 2,
                'data_source': 'naver_finance_trend_api,naver_finance_enhanced',
                'latest_source_date': source, 'attempted_scrapes': 2,
                'successful_scrapes': successful, 'failed_scrapes': failed, 'skipped_scrapes': 0,
                'updated_stocks': successful, 'retained_stocks': failed,
                'requested_codes': json.dumps(codes), 'failed_codes': json.dumps(codes[successful:])}
    write_csv(tmp_path/'all_institutional_metadata.csv', [metadata])
    rows = [{'ticker': code, 'data_date': source if i < successful else '',
             'scrape_date': collected[:10] if i < successful else '2026-09-10',
             'data_source': 'naver_finance_trend_api' if i < successful else 'naver_finance_enhanced',
             'total_days': '60', 'foreign_net_buy_5d': '123', 'institutional_net_buy_5d': '-456'}
            for i,code in enumerate(codes)]
    path = tmp_path/'all_institutional_trend_data.csv'
    write_csv(path, rows)
    timestamp = datetime.fromisoformat(collected).replace(tzinfo=service.KST).timestamp()+1
    os.utime(path, (timestamp, timestamp))
    return status, metadata, rows


def test_partial_counts_dates_and_kst_acquisition_time_are_explicit(tmp_path):
    evidence(tmp_path)
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir()}
    result = service.read_institutional_collection(tmp_path, NOW)
    assert result['status'] == 'partial'
    assert (result['requested'],result['successful'],result['failed'],result['skipped']) == (2,1,1,0)
    assert result['source_date'] == '2026-11-06'
    assert result['collected_at'] == '2026-11-08T12:00:00+09:00'
    assert before == {p.name:p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('missing', ['institutional_collection_status.json', 'all_institutional_metadata.csv'])
def test_legacy_or_missing_evidence_never_becomes_ok_from_new_mtime(tmp_path, missing):
    evidence(tmp_path, failed=0)
    (tmp_path/missing).unlink()
    assert service.read_institutional_collection(tmp_path,NOW)['status'] == 'unknown'


@pytest.mark.parametrize('kind', ['count_mismatch','duplicate_outcome','false_completed','future_collection',
                                 'metadata_count','metadata_time','csv_old','csv_missing_success','csv_bad_flow'])
def test_inconsistent_evidence_is_unknown(tmp_path, kind):
    status,metadata,rows = evidence(tmp_path)
    if kind == 'count_mismatch': status['successful'] = 2
    elif kind == 'duplicate_outcome': status['outcomes'][1] = status['outcomes'][0]
    elif kind == 'false_completed': status['status'] = 'completed'
    elif kind == 'future_collection': status['collected_at'] = '2026-11-09T12:00:00'
    elif kind == 'metadata_count': metadata['successful_scrapes'] = 2
    elif kind == 'metadata_time': metadata['collection_date'] = '2026-09-10 12:00:00'
    elif kind == 'csv_old': rows[0]['data_date'] = '2026-09-10'
    elif kind == 'csv_missing_success': rows = rows[1:]
    elif kind == 'csv_bad_flow': rows[0]['foreign_net_buy_5d'] = 'NaN'
    (tmp_path/'institutional_collection_status.json').write_text(json.dumps(status))
    write_csv(tmp_path/'all_institutional_metadata.csv',[metadata])
    write_csv(tmp_path/'all_institutional_trend_data.csv',rows)
    assert service.read_institutional_collection(tmp_path,NOW)['status'] == 'unknown'


def test_all_failed_attempt_is_failure_even_when_no_new_csv_metadata_was_written(tmp_path):
    evidence(tmp_path,failed=2)
    (tmp_path/'all_institutional_metadata.csv').unlink()
    result = service.read_institutional_collection(tmp_path,NOW)
    assert result['status'] == 'failed' and result['failed'] == 2 and result['successful'] == 0


@pytest.mark.parametrize('now,source,collected,expected', [
    ('2026-11-08T23:00:00+09:00','2026-11-06','2026-11-07T08:00:00','ok'),
    ('2026-11-09T17:29:00+09:00','2026-11-06','2026-11-07T08:00:00','ok'),
    ('2026-11-09T17:30:00+09:00','2026-11-06','2026-11-07T08:00:00','stale'),
    ('2026-11-08T12:05:00+09:00','2026-11-05','2026-11-08T12:00:00','stale'),
    ('2026-05-04T10:00:00+09:00','2026-04-30','2026-05-01T08:00:00','ok'),
    ('2026-03-02T20:00:00+09:00','2026-02-27','2026-02-28T08:00:00','ok'),
    ('2026-11-08T12:05:00+09:00','2026-11-09','2026-11-08T12:00:00','unknown'),
])
def test_source_session_freshness_weekends_holidays_and_after_close_deadline(tmp_path,now,source,collected,expected):
    evidence(tmp_path,failed=0,source=source,collected=collected)
    assert service.read_institutional_collection(tmp_path,datetime.fromisoformat(now))['status'] == expected


def test_status_read_is_bounded(tmp_path,monkeypatch):
    evidence(tmp_path)
    monkeypatch.setattr(service,'MAX_STATUS_BYTES',10)
    assert service.read_institutional_collection(tmp_path,NOW)['status'] == 'unknown'


@pytest.mark.parametrize('mode,expected', [('partial','warn'),('failed','fail'),('stale','fail'),('unknown','unknown'),('ok','ok')])
def test_control_center_has_an_independent_source_check(tmp_path,mode,expected):
    from app.services.control_center import contracts,local_checks
    if mode != 'unknown':
        evidence(tmp_path,failed=2 if mode=='failed' else (1 if mode=='partial' else 0),
                 source='2026-11-05' if mode=='stale' else '2026-11-06')
    contract = next(item for item in contracts.load()['data'] if item['id']=='kr_institutional')
    item = dict(contract,path=str(tmp_path/'institutional_collection_status.json'))
    result = local_checks.check_data([item],NOW)[0]
    assert result.id == 'data:kr_institutional' and result.status == expected
    assert result.data['freshness_basis'] == 'source_session'
    assert result.data['collection']['status'] == mode


@pytest.mark.parametrize('has_evidence', [True,False])
def test_data_status_response_includes_verified_collection_and_keeps_other_rows_compatible(tmp_path,monkeypatch,has_evidence):
    from flask import Flask
    from app.routes import common
    if has_evidence:
        evidence(tmp_path)
    else:
        (tmp_path/'all_institutional_trend_data.csv').write_text('ticker\n005930\n')
    actual = service.read_institutional_collection
    monkeypatch.setattr(service,'read_institutional_collection',lambda directory:actual(directory,NOW))
    for key in ('DATA_DIR','BASE_DIR','US_OUTPUT_DIR','CRYPTO_OUTPUT_DIR'):
        monkeypatch.setattr(common,key,str(tmp_path))
    app = Flask(__name__)
    # Auth is unchanged; isolate this existing handler's returned data contract.
    with app.test_request_context('/api/system/data-status'):
        response = common.get_data_status.__wrapped__().get_json()
    institutional = next(row for row in response['files'] if row['name']=='Institutional Trend')
    assert institutional['exists'] and institutional['rowCount'] == (2 if has_evidence else 1)
    assert institutional['collection']['status'] == ('partial' if has_evidence else 'unknown')
    assert set(institutional['collection']) == {'status','requested','successful','failed','skipped','source_date','collected_at','detail'}
    assert all('collection' not in row for row in response['files'] if row['name']!='Institutional Trend')
