from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from requests.exceptions import Timeout

from app.services.kongming_disclosure import DisclosureVerifier


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 7, 20, tzinfo=KST)
ENTITY = {'symbol': '128940', 'name': '한미약품'}
CORP = '00904672'
ORIGINAL = '20261105800001'
CORRECTION = '20261107800002'


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('DART_API_KEY', 'marketflow-test-only')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/dart_corp_codes.json').write_text(
        json.dumps({ENTITY['symbol']: CORP}), encoding='utf-8'
    )
    return tmp_path


def _article(title='한미약품 3분기 영업이익 378억', **fields):
    return {
        'title': title, 'published_at': (NOW - timedelta(days=1)).isoformat(),
        'entities': [ENTITY], 'event': {'type': 'earnings', 'certainty': 'reported_unverified'},
        **fields,
    }


def _filing(receipt=ORIGINAL, **fields):
    return {
        'corp_name': ENTITY['name'], 'corp_code': CORP, 'stock_code': ENTITY['symbol'],
        'report_nm': '연결재무제표 기준 영업(잠정)실적(공정공시)',
        'rcept_no': receipt, 'rcept_dt': receipt[:8], **fields,
    }


def _zip(receipt, text):
    archive = BytesIO()
    with ZipFile(archive, 'w') as body:
        body.writestr(receipt + '.xml', text)
    return archive.getvalue()


def _report(receipt=ORIGINAL, *, operating='37,800', start='2026-07-01', unit='백만원'):
    rows = [
        '한미약품/연결재무제표기준영업(잠정)실적(공정공시)',
        '실적기간', '당기실적', start, '~', '2026-09-30',
        '전기실적', '2026-04-01', '~', '2026-06-30', '1. 연결실적내용',
        f'단위 : {unit}, %', '매출액', '당해실적', '500,000', '누계실적', '1,000,000',
        '영업이익', '당해실적', operating, '누계실적', '120,000',
        '당기순이익', '당해실적', '70,000', '누계실적', '615,661',
        '지배기업 소유주지분 순이익', '당해실적', '40,000', '누계실적', '595,657',
        '2. 정보제공내역',
    ]
    return _zip(receipt, '<DOCUMENT>' + ''.join(f'<TD>{row}</TD>' for row in rows) + '</DOCUMENT>')


class _Dart:
    def __init__(self, *, rows=None, status='000', total_page=1, documents=None):
        self.catalogue = {'status': status, 'total_page': total_page, 'list': rows or []}
        self.documents = documents or {}
        self.calls = []

    def __call__(self, url, params, *, limit, deadline):
        assert params['crtfc_key'] == 'marketflow-test-only'
        if url.endswith('/list.json'):
            self.calls.append(('list', params['corp_code'], params['bgn_de'], params['end_de']))
            return json.dumps(self.catalogue, ensure_ascii=False).encode('utf-8')
        assert url.endswith('/document.xml')
        self.calls.append(('document', params['rcept_no']))
        return self.documents[params['rcept_no']]


def test_matches_issuer_date_and_current_quarter_amount_and_reuses_receipts(project):
    dart = _Dart(rows=[_filing()], documents={ORIGINAL: _report()})
    provider = DisclosureVerifier(project, transport=dart)
    result = provider.verify(_article(), ENTITY, NOW)
    check, = result['checks']
    claim, = check['claims']
    assert result['status'] == check['status'] == 'verified_numeric_claims'
    assert result['source'] == 'OpenDART'
    assert result['checked_at'] == NOW.isoformat()
    assert len(result['catalogue_sha256']) == len(check['document_sha256']) == 64
    assert check['url'] == f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={ORIGINAL}'
    assert claim == {
        'metric': '영업이익', 'article_amount_krw': '37800000000',
        'official_amount_krw': '37800000000', 'verified': True,
        'period': '2026Q3', 'basis': '당기',
    }
    assert provider.verify(_article(), ENTITY, NOW) == result
    assert dart.calls == [('list', CORP, '20261103', '20261107'), ('document', ORIGINAL)]


def test_does_not_verify_superseded_amount_after_corrected_filing(project):
    correction = _filing(CORRECTION, report_nm='[기재정정]연결재무제표기준영업(잠정)실적(공정공시)')
    dart = _Dart(rows=[_filing(), correction], documents={CORRECTION: _report(CORRECTION, operating='0.037', unit='조원')})
    provider = DisclosureVerifier(project, transport=dart)
    result = provider.verify(_article(), ENTITY, NOW)
    latest, earlier = result['checks']
    assert result['status'] == 'related_filing_found'
    assert latest['filing_date_relation'] == 'later_correction'
    assert latest['claims'][0]['official_amount_krw'] == '37000000000.000'
    assert latest['claims'][0]['verified'] is False
    assert earlier['claims'] == []
    assert [call for call in dart.calls if call[0] == 'document'] == [('document', CORRECTION)]


@pytest.mark.parametrize(
    ('article', 'document', 'expected'),
    [
        (_article('한미약품 3분기 누적 순이익 5957억'), _report(), '615661000000'),
        (_article('한미약품 3분기 영업이익 378억 달러'), _report(), None),
        (_article('한미약품 3분기 영업이익 378억원 감소'), _report(), None),
        (_article('한미약품 3분기 별도 영업이익 378억'), _report(), None),
        (_article('한미약품 작년 3분기 영업이익 378억'), _report(), None),
        (_article(event={'type': 'earnings', 'certainty': 'forecast'}), _report(), None),
        (_article(entities=[ENTITY, {'symbol': '005930', 'name': '삼성전자'}]), _report(), None),
        (_article(), _report(start='2026-04-01'), None),
    ],
)
def test_avoids_nearby_but_incompatible_amounts(project, article, document, expected):
    dart = _Dart(rows=[_filing()], documents={ORIGINAL: document})
    result = DisclosureVerifier(project, transport=dart).verify(article, ENTITY, NOW)
    assert result['status'] == 'related_filing_found'
    claims = result['checks'][0]['claims']
    if expected is None:
        assert claims == []
    else:
        claim, = claims
        assert claim['official_amount_krw'] == expected
        assert claim['verified'] is False


def test_excludes_subsidiary_unrelated_and_lookahead_filing(project):
    rows = [
        _filing(report_nm='자회사의 주요경영사항 영업(잠정)실적'),
        _filing(receipt='20261107800001'),
        _filing(receipt='20261031800001'),
        _filing(report_nm='주주총회소집공고'),
    ]
    result = DisclosureVerifier(project, transport=_Dart(rows=rows)).verify(_article(), ENTITY, NOW)
    assert result['status'] == 'no_matching_filing'
    assert result['checks'] == []


@pytest.mark.parametrize('fields', [{'corp_name': '다른 회사'}, {'stock_code': '000660'}, {'corp_code': '00000000'}])
def test_does_not_open_document_for_mismatched_issuer(project, fields):
    dart = _Dart(rows=[_filing(**fields)])
    result = DisclosureVerifier(project, transport=dart).verify(_article(), ENTITY, NOW)
    assert result['status'] == 'issuer_name_conflict'
    assert len(dart.calls) == 1


def test_empty_result_is_distinct_from_quota_and_partial_catalogue(project):
    empty = DisclosureVerifier(project, transport=_Dart(status='013')).verify(_article(), ENTITY, NOW)
    assert empty['status'] == 'no_matching_filing'
    quota = _Dart(status='020')
    provider = DisclosureVerifier(project, transport=quota)
    for _ in range(2):
        unavailable = provider.verify(_article(), ENTITY, NOW)
        assert unavailable['status'] == 'source_unavailable'
        assert unavailable['error_code'] == 'dart_status_020'
    assert len(quota.calls) == 1
    pages = DisclosureVerifier(project, transport=_Dart(rows=[_filing()], total_page=2))
    assert pages.verify(_article(), ENTITY, NOW)['error_code'] == 'catalogue_page_limit'


def test_budget_preserves_filing_metadata_for_later_document_verification(project):
    dart = _Dart(rows=[_filing()])
    result = DisclosureVerifier(project, max_requests=1, transport=dart).verify(_article(), ENTITY, NOW)
    assert result['status'] == 'pending'
    assert result['checks'][0]['filing']['rcept_no'] == ORIGINAL
    assert len(dart.calls) == 1


def test_unsafe_document_does_not_turn_filing_into_confirmation(project):
    xml = '<!DOCTYPE DOCUMENT [<!ENTITY sample SYSTEM "file:///private">]><DOCUMENT>&sample;</DOCUMENT>'
    dart = _Dart(rows=[_filing()], documents={ORIGINAL: _zip(ORIGINAL, xml)})
    result = DisclosureVerifier(project, transport=dart).verify(_article(), ENTITY, NOW)
    assert result['status'] == 'document_unavailable'
    assert result['checks'][0]['claims'] == []


def test_request_errors_hide_provider_credentials(project):
    def failed(*args, **kwargs):
        raise Timeout('https://opendart.fss.or.kr/api/list.json?crtfc_key=marketflow-test-only')

    result = DisclosureVerifier(project, transport=failed).verify(_article(), ENTITY, NOW)
    assert result['status'] == 'source_unavailable'
    assert result['error_code'] == 'request_failed'
    assert 'marketflow-test-only' not in json.dumps(result)


NEW_ENTITY = {'symbol': '0162D0', 'name': '동원파츠'}
NEW_CORP = '00784184'


def _registry_xml(*entries):
    rows = ''.join(
        '<list><corp_code>{}</corp_code><corp_name>{}</corp_name>'
        '<corp_eng_name>EXAMPLE CO LTD</corp_eng_name><stock_code>{}</stock_code>'
        '<modify_date>20261110</modify_date></list>'.format(corp, name, symbol)
        for symbol, corp, name in entries
    )
    return _zip('CORPCODE', '<?xml version="1.0" encoding="UTF-8"?><result>' + rows + '</result>')


class _RegistryDart(_Dart):
    def __init__(self, registry=None, **kwargs):
        super().__init__(**kwargs)
        self.registry = registry if registry is not None else _registry_xml(
            (NEW_ENTITY['symbol'], NEW_CORP, NEW_ENTITY['name']),
            (ENTITY['symbol'], CORP, ENTITY['name']),
        )

    def __call__(self, url, params, **kwargs):
        if url.endswith('/corpCode.xml'):
            self.calls.append(('registry',))
            if isinstance(self.registry, Exception):
                raise self.registry
            return self.registry
        return super().__call__(url, params, **kwargs)


def _new_article(entity=NEW_ENTITY):
    return _article(entity['name'] + ' 지분 공시', entities=[entity], event={'type': 'capital_policy'})


def test_missing_alphanumeric_symbol_refreshes_official_registry_and_survives_restart(project):
    original_map = (project / 'data/dart_corp_codes.json').read_bytes()
    filing = _filing(corp_name=NEW_ENTITY['name'], corp_code=NEW_CORP,
                     stock_code=NEW_ENTITY['symbol'], report_nm='임원ㆍ주요주주특정증권등소유상황보고서')
    dart = _RegistryDart(rows=[filing])
    result = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)
    assert result['status'] == 'related_filing_found'
    mapping = result['issuer_mapping']
    assert mapping['corp_code'] == NEW_CORP
    assert mapping['stock_code'] == '0162D0'
    assert mapping['corp_name'] == '동원파츠'
    assert mapping['source'] == 'https://opendart.fss.or.kr/api/corpCode.xml'
    assert mapping['fetched_at'] == NOW.isoformat()
    assert len(mapping['sha256']) == 64
    restarted = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)
    assert restarted['status'] == 'related_filing_found'
    assert [call for call in dart.calls if call[0] == 'registry'] == [('registry',)]
    assert (project / 'data/dart_corp_codes.json').read_bytes() == original_map


def test_missing_registry_file_can_recover_without_replacing_shared_map(project):
    (project / 'data/dart_corp_codes.json').unlink()
    result = DisclosureVerifier(project, transport=_RegistryDart(status='013')).verify(_new_article(), NEW_ENTITY, NOW)
    assert result['status'] == 'no_matching_filing'
    assert not (project / 'data/dart_corp_codes.json').exists()


def test_unlisted_symbol_does_not_download_corpus_each_worker_run(project):
    entity = {'symbol': '9999Z0', 'name': '미등록회사'}
    dart = _RegistryDart(status='013')
    for minutes in (0, 1, 10, 60):
        result = DisclosureVerifier(project, transport=dart).verify(_new_article(entity), entity, NOW + timedelta(minutes=minutes))
        assert result['error_code'] == 'issuer_mapping_unavailable'
    assert dart.calls == [('registry',)]
    assert result['issuer_mapping']['retry_at'] == (NOW + timedelta(days=1)).isoformat()


def test_failed_refresh_retries_after_cooldown_without_losing_valid_mapping(project):
    good = _RegistryDart(status='013')
    assert DisclosureVerifier(project, transport=good).verify(_new_article(), NEW_ENTITY, NOW)['status'] == 'no_matching_filing'
    entity = {'symbol': '9999Z0', 'name': '미등록회사'}
    future = NOW + timedelta(days=2)
    failed = _RegistryDart(registry=Timeout('secret-key-in-provider-url'), status='013')
    first = DisclosureVerifier(project, transport=failed).verify(_new_article(entity), entity, future)
    assert first['status'] == 'source_unavailable'
    again = DisclosureVerifier(project, transport=failed).verify(_new_article(entity), entity, future + timedelta(minutes=1))
    assert again['status'] == 'source_unavailable'
    assert failed.calls == [('registry',)]
    kept = DisclosureVerifier(project, transport=failed).verify(_new_article(), NEW_ENTITY, future)
    assert kept['status'] == 'no_matching_filing'
    assert kept['issuer_mapping']['fetched_at'] == NOW.isoformat()
    assert kept['issuer_mapping']['stale'] is True
    DisclosureVerifier(project, transport=failed).verify(_new_article(entity), entity, future + timedelta(minutes=16))
    assert len([call for call in failed.calls if call[0] == 'registry']) == 2
    assert 'secret-key' not in json.dumps(first)
    assert 'secret-key' not in (project / 'data/kongming/dart_issuer_registry.json').read_text(encoding='utf-8')


def test_registry_refresh_consumes_the_existing_request_budget(project):
    dart = _RegistryDart(status='013')
    zero = DisclosureVerifier(project, transport=dart, max_requests=0).verify(_new_article(), NEW_ENTITY, NOW)
    assert zero['status'] == 'pending'
    assert dart.calls == []
    one = DisclosureVerifier(project, transport=dart, max_requests=1).verify(_new_article(), NEW_ENTITY, NOW)
    assert one['status'] == 'pending'
    assert dart.calls == [('registry',)]
    assert DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)['status'] == 'no_matching_filing'


def test_official_mapping_name_conflict_never_queries_another_issuer(project):
    dart = _RegistryDart(registry=_registry_xml(('0162D0', NEW_CORP, '동원산업')), status='013')
    result = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)
    assert result['status'] == 'issuer_name_conflict'
    assert dart.calls == [('registry',)]


@pytest.mark.parametrize('archive', [
    b'not a zip file',
    _zip('CORPCODE', '<!DOCTYPE result [<!ENTITY x "unsafe">]><result>&x;</result>'),
    _zip('CORPCODE', '<result><list>'),
    _registry_xml(('0162D0', 'invalid', '동원파츠')),
    _registry_xml(('0162D0', NEW_CORP, '동원파츠'), ('0162D0', CORP, '한미약품')),
], ids=['not_zip', 'entity_declaration', 'truncated_xml', 'bad_corp_code', 'duplicate_symbol'])
def test_invalid_registry_is_not_accepted_or_refetched_every_minute(project, archive):
    dart = _RegistryDart(registry=archive, status='013')
    first = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)
    assert first['status'] == 'source_unavailable'
    assert first['error_code'] == 'issuer_registry_invalid'
    assert DisclosureVerifier(project, transport=dart).verify(_article(), ENTITY, NOW)['status'] == 'no_matching_filing'
    DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW + timedelta(minutes=1))
    assert len([call for call in dart.calls if call[0] == 'registry']) == 1


def test_registry_refresh_lock_defers_other_worker_without_duplicate_download(project):
    from filelock import FileLock

    cache = project / 'data/kongming/dart_issuer_registry.json'
    cache.parent.mkdir(parents=True)
    dart = _RegistryDart(status='013')
    with FileLock(str(cache) + '.lock', timeout=0):
        result = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)
    assert result['status'] == 'pending'
    assert dart.calls == []
    assert DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)['status'] == 'no_matching_filing'


def test_registry_quota_error_is_preserved_and_stops_later_requests(project):
    dart = _RegistryDart(registry=b'<?xml version="1.0"?><result><status>020</status><message>quota</message></result>')
    provider = DisclosureVerifier(project, transport=dart)
    result = provider.verify(_new_article(), NEW_ENTITY, NOW)
    assert result['error_code'] == 'dart_status_020'
    assert result['issuer_mapping']['retry_at'] == (NOW + timedelta(minutes=15)).isoformat()
    assert provider.verify(_article(), ENTITY, NOW)['error_code'] == 'dart_status_020'
    assert dart.calls == [('registry',)]
    again = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW + timedelta(minutes=1))
    assert again['error_code'] == 'dart_status_020'


def test_missing_symbol_is_recovered_when_next_daily_registry_includes_it(project):
    old = _RegistryDart(registry=_registry_xml((ENTITY['symbol'], CORP, ENTITY['name'])))
    assert DisclosureVerifier(project, transport=old).verify(_new_article(), NEW_ENTITY, NOW)['error_code'] == 'issuer_mapping_unavailable'
    updated = _RegistryDart(status='013')
    result = DisclosureVerifier(project, transport=updated).verify(_new_article(), NEW_ENTITY, NOW + timedelta(days=1))
    assert result['status'] == 'no_matching_filing'
    assert result['issuer_mapping']['fetched_at'] == (NOW + timedelta(days=1)).isoformat()


def test_oversized_registry_is_rejected_before_extracting_xml(project, monkeypatch):
    from app.services import kongming_dart_registry

    monkeypatch.setattr(kongming_dart_registry, 'XML_LIMIT', 100)
    result = DisclosureVerifier(project, transport=_RegistryDart()).verify(_new_article(), NEW_ENTITY, NOW)
    assert result['error_code'] == 'issuer_registry_invalid'


def test_registry_cache_write_failure_does_not_trigger_uncached_download(project, monkeypatch):
    from app.services import kongming_dart_registry

    def full_disk(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(kongming_dart_registry, 'write_json_atomic', full_disk)
    dart = _RegistryDart()
    result = DisclosureVerifier(project, transport=dart).verify(_new_article(), NEW_ENTITY, NOW)
    assert result['error_code'] == 'issuer_registry_cache_unavailable'
    assert dart.calls == []
