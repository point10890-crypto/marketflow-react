from datetime import datetime, timedelta, timezone

from app.services.catalyst_outcomes import analytics as a

NOW = datetime(2026, 11, 11, 2, tzinfo=timezone.utc)


def series(count=100):
    start = datetime(2026, 6, 1)
    days = [(start+timedelta(days=i)).date().isoformat() for i in range(200)
            if (start+timedelta(days=i)).weekday()<5][:count]
    return [dict(date=d, close=100+i, fetched_at=NOW.isoformat(), source='naver_closed_daily',
                 price_basis='provider_adjusted') for i,d in enumerate(days)]


def event(day, basis='received', identity='one'):
    return dict(id=identity,symbol='005930',name='삼성전자',title='삼성전자 공급 계약',
                url='https://example.com/news',source='omni',event_type='contract',
                published_at=day+'T08:00:00+09:00',first_seen_at=day+'T10:00:00+09:00',
                anchor_at=day+'T10:00:00+09:00',analysis_basis=basis,verification='reported_unverified')


def test_returns_use_next_close_and_complete_horizon_with_costs():
    rows=series();e=event(rows[61]['date'])
    case=a.evaluate_case(e,rows,[r['date'] for r in rows],NOW)
    h=case['horizons']['10']
    assert h['entry_date']==rows[62]['date'] and h['exit_date']==rows[72]['date']
    assert abs(h['net_return']-(172*.997/(162*1.001)-1))<1e-12
    assert h['status']=='completed'


def test_missing_first_or_intermediate_session_does_not_shift_trade():
    rows=series();e=event(rows[61]['date']);calendar=[r['date'] for r in rows]
    for missing in [62,67]:
        case=a.evaluate_case(e,rows[:missing]+rows[missing+1:],calendar,NOW)
        assert case['horizons']['10']['status']=='missing'
        assert case['horizons']['10']['net_return'] is None


def test_insufficient_horizon_is_pending_and_old_history_missing():
    rows=series();calendar=[r['date'] for r in rows]
    assert a.evaluate_case(event(rows[-3]['date']),rows,calendar,NOW)['horizons']['10']['status']=='pending'
    assert a.evaluate_case(event('2020-01-01'),rows,calendar,NOW)['horizons']['10']['status']=='missing'


def test_closed_outcome_is_preserved_and_excluded_after_revision():
    rows=series();e=event(rows[61]['date']);calendar=[r['date'] for r in rows]
    first=a.evaluate_case(e,rows,calendar,NOW)
    changed=[dict(r) for r in rows];changed[66]['close']+=10
    again=a.evaluate_case(e,changed,calendar,NOW,previous=first)
    assert again['horizons']['10']['net_return']==first['horizons']['10']['net_return']
    assert again['horizons']['10']['status']=='revised'
    restored=a.evaluate_case(e,rows,calendar,NOW,previous=again)
    assert restored['horizons']['10']['status']=='revised'


def test_temporarily_missing_source_recovers_without_permanent_revision():
    rows=series();e=event(rows[61]['date']);calendar=[r['date'] for r in rows]
    first=a.evaluate_case(e,rows,calendar,NOW)
    missing=a.evaluate_case(e,[],calendar,NOW,previous=first)
    assert missing['horizons']['10']['status']=='blocked'
    assert missing['horizons']['10']['net_return']==first['horizons']['10']['net_return']
    restored=a.evaluate_case(e,rows,calendar,NOW,previous=missing)
    assert restored['horizons']['10']==first['horizons']['10']


def test_intraday_today_and_future_rows_do_not_mature():
    rows=series();rows.append(dict(rows[-1],date='2026-11-11',close=999))
    case=a.evaluate_case(event('2026-11-10'),rows,[r['date'] for r in rows],NOW)
    assert case['horizons']['5']['status']=='pending'


def test_candidate_requires_positive_case_current_trend_and_no_import():
    rows=series();now=datetime.fromisoformat(rows[-1]['date']+'T23:00:00+00:00')+timedelta(days=1)
    rows=[dict(r,fetched_at=now.isoformat()) for r in rows]
    old=a.evaluate_case(event(rows[-20]['date']),rows,[r['date'] for r in rows],now)
    prices={'005930':dict(captured_at=now.isoformat(),symbol='005930',bars=[dict(r,open=r['close']-.5,high=r['close']+1,low=r['close']-1,volume=10000000,traded_value=2000000000,quality_flags=[]) for r in rows])}
    selected=a.rank_candidates([old],prices,now,[r['date'] for r in rows])
    assert selected and selected[0]['symbol']=='005930'
    assert selected[0]['plan']['stop_price']<selected[0]['price']<selected[0]['plan']['target_price']
    assert not a.rank_candidates([dict(old,analysis_basis='retrospective')],prices,now,[r['date'] for r in rows])
    prices['005930']['bars'][-1]['quality_flags']=[{'code':'provider_price_event_unverified'}]
    assert not a.rank_candidates([old],prices,now,[r['date'] for r in rows])


def test_same_stock_same_receipt_day_is_one_support_not_multiple_wins():
    rows=series();now=datetime.fromisoformat(rows[-1]['date']+'T23:00:00+00:00')+timedelta(days=1)
    rows=[dict(r,fetched_at=now.isoformat()) for r in rows]
    cases=[a.evaluate_case(event(rows[-20]['date'],identity=str(i)),rows,[r['date'] for r in rows],now) for i in range(3)]
    assert a.support(cases,now)['005930']['matured']==1


def test_no_positive_cases_means_no_research_candidate():
    rows=series();case=a.evaluate_case(event(rows[-2]['date']),rows,[r['date'] for r in rows],NOW)
    assert a.shortlist([case],{'005930':rows},NOW)==[]
