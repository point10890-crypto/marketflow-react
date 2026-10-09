# 저장 보조 맥락과 전향 대조 코호트의 무쓰기·불변 계약을 검증한다.
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from app.services.mirofish.alpha_lab import opportunity_store, store

FIRST = '2026-10-07T09:46:02Z'
CAPTURE = '2026-10-09T11:00:00Z'


def module():
    name = 'app.services.mirofish.alpha_lab.catalyst_store'
    assert importlib.util.find_spec(name), 'catalyst sidecar store is not implemented'
    return importlib.import_module(name)


def board(clock=FIRST, identity='d', symbols=('000660',)):
    return dict(schema_version=1, policy_version='profit-opportunity-v1', decision_id=identity*64,
        input_fingerprint='a'*64, source_audit_hash='b'*64, generated_at=clock,
        candidates=[dict(symbol=symbol, name='SK하이닉스' if symbol == '000660' else symbol,
            opportunity_id=str(i)*64) for i,symbol in enumerate(symbols,1)])


def save_board(root, current=None):
    current = current or board()
    frozen = opportunity_store.register_board(root, current)
    store.publish(root, dict(schema_version=1, mode='research', opportunity_board=frozen), now=current['generated_at'])
    return frozen


def make_db(path, rows=None):
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE news_events (id INTEGER PRIMARY KEY, content_hash TEXT UNIQUE, title TEXT, '
            'summary TEXT, link TEXT, source TEXT, grade TEXT, published_ts TEXT, symbols TEXT, collected_at TEXT)')
        for row in rows or [dict(content_hash='e'*64, title='SK하이닉스 저평가 IBK 매수 의견',
            summary='', link='https://www.asiae.co.kr/article/202610070123', source='asiae_stock', grade='B',
            published_ts='2026-10-07T00:00:00Z', symbols=json.dumps(['000660']), collected_at='2026-10-07T01:00:00Z')]:
            keys = list(row)
            conn.execute('INSERT INTO news_events ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', list(row.values()))
    return path


def files(root):
    return {str(p.relative_to(root)):(p.read_bytes(), p.stat().st_mtime_ns) for p in Path(root).rglob('*') if p.is_file()}


def test_refresh_is_bound_to_frozen_decision_and_read_does_not_touch_db_or_write(tmp_path, monkeypatch):
    root = tmp_path/'alpha'; current = save_board(root); db = make_db(tmp_path/'omni.db')
    before = files(root)
    assert module().refresh_context(root, now=CAPTURE, db_path=db)['status'] == 'ready'
    assert all(files(root)[path] == value for path,value in before.items())
    saved = files(root)
    db_before = db.read_bytes(), db.stat().st_mtime_ns
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('GET opened SQLite')))
    public = module().read_context(root, current, now=CAPTURE)
    assert public['rows'][0]['first_detected_at'] == FIRST
    assert public['rows'][0]['events'][0]['timing'] == 'captured_before_first'
    assert files(root) == saved and (db.read_bytes(), db.stat().st_mtime_ns) == db_before
    assert public['validation']['enrolled_decisions'] == 0
    assert 'private_path' not in json.dumps(public)


def test_missing_store_get_creates_no_directory(tmp_path):
    root = tmp_path/'absent'
    assert module().read_context(root, board(), now=CAPTURE) is None
    assert not root.exists()


def test_missing_db_refresh_fails_sanitized_and_never_initializes_database(tmp_path):
    root = tmp_path/'alpha'; save_board(root); missing = tmp_path/'private-folder'/'omni.db'
    result = module().refresh_context(root, now=CAPTURE, db_path=missing)
    assert result == dict(status='failed', error='catalyst_news_unavailable')
    assert not missing.exists() and not missing.parent.exists()
    assert str(missing) not in json.dumps(result)


def test_failed_refresh_retains_previous_snapshot_and_immutable_runs(tmp_path):
    root = tmp_path/'alpha'; current = save_board(root); db = make_db(tmp_path/'omni.db')
    first = module().refresh_context(root, now=CAPTURE, db_path=db)
    public = module().read_context(root, current, now=CAPTURE)
    saved = files(root/'catalyst-context')
    result = module().refresh_context(root, now='2026-10-09T12:00:00Z', db_path=tmp_path/'missing.db')
    assert result['status'] == 'failed' and result['error'] == 'catalyst_news_unavailable'
    assert files(root/'catalyst-context') == saved
    assert module().read_context(root, current, now='2026-10-09T12:00:00Z') == public
    assert first['snapshot_id'] == public['snapshot_id']


def test_pre_detection_capture_survives_more_than_256_later_cached_reports(tmp_path):
    root = tmp_path/'alpha'; current = save_board(root)
    pre = dict(content_hash='e'*64, title='SK하이닉스 저평가', summary='',
        link='https://www.asiae.co.kr/article/pre', source='asiae_stock', grade='B',
        published_ts='2026-10-07T08:00:00Z', symbols=json.dumps(['000660']), collected_at='2026-10-07T09:45:00Z')
    rows = [pre]
    for i in range(300):
        clock = (datetime(2026,10,8,tzinfo=timezone.utc)+timedelta(minutes=i)).isoformat()
        rows.append(dict(pre, content_hash=format(i+1000, '064x'), title='SK하이닉스 신규 보도 '+str(i),
            link='https://www.asiae.co.kr/article/after-'+str(i), published_ts=clock, collected_at=clock))
    db = make_db(tmp_path/'omni.db', rows)
    assert module().refresh_context(root, now=CAPTURE, db_path=db)['status'] == 'ready'
    events = module().read_context(root, current, now=CAPTURE)['rows'][0]['events']
    assert len(events) == 8
    assert events[0]['url'] == 'https://www.asiae.co.kr/article/pre'
    assert events[0]['collected_at'] == '2026-10-07T09:45:00Z'
    assert events[0]['timing'] == 'captured_before_first'
    assert [row['url'] for row in events[1:]] == [
        'https://www.asiae.co.kr/article/after-'+str(i) for i in range(293,300)]


def test_read_omits_corrupted_snapshot_or_other_binding_without_repair(tmp_path):
    root = tmp_path/'alpha'; current = save_board(root); db = make_db(tmp_path/'omni.db')
    result = module().refresh_context(root, now=CAPTURE, db_path=db)
    other = deepcopy(current); other['source_audit_hash'] = 'c'*64
    assert module().read_context(root, other, now=CAPTURE) is None
    target = root/'catalyst-context'/'runs'/(result['snapshot_id']+'.json')
    target.write_text('{broken', encoding='utf-8')
    before = files(root)
    assert module().read_context(root, current, now=CAPTURE) is None
    assert files(root) == before


def test_protocol_is_fixed_on_first_refresh_and_old_decisions_never_enroll(tmp_path):
    root = tmp_path/'alpha'; current = save_board(root); db = make_db(tmp_path/'omni.db')
    assert module().register_cohort(root, current, {'000660':'SK하이닉스','005930':'삼성전자'}, now=CAPTURE)['status'] == 'not_started'
    module().refresh_context(root, now=CAPTURE, db_path=db)
    protocol = (root/'catalyst-context'/'protocol.json').read_bytes()
    assert module().register_cohort(root, current, {'000660':'SK하이닉스','005930':'삼성전자'}, now=CAPTURE)['status'] == 'historical'
    module().refresh_context(root, now='2026-10-09T12:00:00Z', db_path=db)
    assert (root/'catalyst-context'/'protocol.json').read_bytes() == protocol
    public = module().read_context(root, current, now='2026-10-09T12:00:00Z')
    assert public['validation']['started_at'] == CAPTURE and public['validation']['enrolled_decisions'] == 0


def test_new_cohort_freezes_all_same_quality_controls_and_cannot_be_reselected(tmp_path):
    root = tmp_path/'alpha'; save_board(root); db = make_db(tmp_path/'omni.db')
    module().refresh_context(root, now=CAPTURE, db_path=db)
    current = save_board(root, board('2026-10-09T12:00:00Z', 'c'))
    universe = {'000660':'SK하이닉스','005930':'삼성전자','035420':'NAVER'}
    result = module().register_cohort(root, current, universe, now='2026-10-09T12:01:00Z')
    assert result['status'] == 'enrolled'
    cohort_path = root/'catalyst-context'/'cohorts'/(current['decision_id']+'.json')
    cohort = json.loads(cohort_path.read_text(encoding='utf-8'))['data']
    assert cohort['selected_symbols'] == ['000660']
    assert cohort['control_symbols'] == ['005930','035420']
    assert cohort['decision_at'] == '2026-10-09T12:00:00Z'
    assert cohort['horizon_until'] == '2026-10-12T12:00:00Z'
    assert cohort['input_fingerprint'] == 'a'*64
    before = files(root/'catalyst-context')
    assert module().register_cohort(root, current, universe, now='2026-10-09T12:02:00Z')['status'] == 'existing'
    assert module().register_cohort(root, current, ['000660','005930'], now='2026-10-09T12:02:00Z')['status'] == 'failed'
    assert files(root/'catalyst-context') == before
    module().refresh_context(root, now='2026-10-09T12:03:00Z', db_path=db)
    public = module().read_context(root, current, now='2026-10-09T12:03:00Z')
    assert public['validation']['enrolled_decisions'] == 1
    assert public['validation']['matured_decisions'] == 0 and public['validation']['coincidence_rejected'] is False


def test_expired_window_cannot_be_enrolled_after_its_news_outcome_is_already_known(tmp_path):
    root = tmp_path/'alpha'; save_board(root); db = make_db(tmp_path/'omni.db')
    module().refresh_context(root, now=CAPTURE, db_path=db)
    current = save_board(root, board('2026-10-09T12:00:00Z', 'c'))
    before = files(root/'catalyst-context')
    result = module().register_cohort(root, current, ['000660','005930'], now='2026-10-12T12:00:00Z')
    assert result == dict(status='failed', error='catalyst_cohort_registration_late')
    assert files(root/'catalyst-context') == before


def test_refresh_requires_hash_valid_issued_clock_and_never_changes_status(tmp_path):
    root = tmp_path/'alpha'; current = save_board(root); db = make_db(tmp_path/'omni.db')
    module().refresh_context(root, now=CAPTURE, db_path=db)
    source = root/'decision_engine'/'issued.json'
    document = json.loads(source.read_text(encoding='utf-8'))
    document['data']['issued'][0]['board']['generated_at'] = '2026-01-01T00:00:00Z'
    source.write_text(json.dumps(document), encoding='utf-8')
    saved_status = (root/'status.json').read_bytes()
    previous = module().read_context(root, current, now=CAPTURE)
    result = module().refresh_context(root, now='2026-10-09T12:00:00Z', db_path=db)
    assert result == dict(status='failed', error='catalyst_journal_unavailable')
    assert (root/'status.json').read_bytes() == saved_status
    assert module().read_context(root, current, now='2026-10-09T12:00:00Z') == previous


def test_cli_only_refreshes_cached_sources_and_sanitizes_missing_data(tmp_path, capsys):
    name = 'scripts.run_alpha_lab_catalysts'
    assert importlib.util.find_spec(name), 'cached catalyst CLI is not implemented'
    cli = importlib.import_module(name)
    root = tmp_path/'alpha'; save_board(root); db = make_db(tmp_path/'omni.db')
    assert cli.main(['--root',str(root),'--db-path',str(db)], now=CAPTURE) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'ready' and 'rows' not in output
    assert cli.main(['--root',str(root),'--db-path',str(tmp_path/'missing.db')], now=CAPTURE) == 2
    output = json.loads(capsys.readouterr().out)
    assert output == dict(status='failed', error='catalyst_news_unavailable')
