import sqlite3
from datetime import datetime

from app.services.control_center.llm_evidence import routing_evidence
from app.services.control_center.model import KST


def test_latest_real_call_beats_old_probe_and_cache(tmp_path):
    path = tmp_path / 'usage.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE provider_attempts(provider,model,operation,status,error_class,event_ts_utc,cache_hit)')
        conn.executemany('INSERT INTO provider_attempts VALUES (?,?,?,?,?,?,?)', [
            ('a','model','text','success',None,'2026-11-07T21:00:00+09:00',0),
            ('a','model','text','failed','numeric_mismatch','2026-11-07T22:00:00+09:00',0),
            ('a','model','text','success',None,'2026-11-07T23:00:00+09:00',1),
            ('a','model','text','skipped_breaker','breaker_open','2026-11-07T23:30:00+09:00',0)])
    cfg = {'id':'llm', 'label':'LLM', 'usage_path':str(path)}
    result = routing_evidence(cfg, datetime(2026,11,8,tzinfo=KST), ['a'])
    assert result.status == 'warn'
    assert result.value['providers'][0]['error_class'] == 'numeric_mismatch'
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO provider_attempts VALUES ('a','model','text','success',NULL,'2026-11-07T23:50:00+09:00',0)")
    assert routing_evidence(cfg, datetime(2026,11,8,tzinfo=KST), ['a']).status == 'ok'
    assert routing_evidence(cfg, datetime(2026,11,12,tzinfo=KST), ['a']).status == 'unknown'
    assert routing_evidence(cfg, datetime(2026,11,7,tzinfo=KST), ['a']).status == 'unknown'
    assert routing_evidence(cfg, datetime(2026,11,8,tzinfo=KST), ['missing']).status == 'unknown'


def test_missing_ledger_does_not_create_database(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    result = routing_evidence({'id':'llm','label':'LLM','usage_path':str(path)},
                              datetime(2026,11,8,tzinfo=KST), ['a'])
    assert result.status == 'unknown'
    assert not path.exists()
