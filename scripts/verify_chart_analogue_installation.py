"""Read-only installed forecast smoke check using real local market data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from app.services.mirofish import chart_analogue


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None, 'Evidence timestamp must include its timezone'
    return parsed.astimezone(timezone.utc)


def verify(symbol: str) -> dict:
    started=time.perf_counter()
    prediction=chart_analogue.predict(symbol)
    elapsed=time.perf_counter()-started
    assert prediction['status']=='ready', f"Forecast not ready: {prediction['status']}"
    json.dumps(prediction,allow_nan=False)
    neighbours=prediction['neighbors']
    assert prediction['sample_count']==len(neighbours)>=5
    assert len({(item['symbol'],item['end_date']) for item in neighbours})==len(neighbours)
    cutoff=prediction['as_of'][:10]
    decision_at = _utc(prediction['as_of'])
    for item in neighbours:
        assert item['start_date']<item['end_date']<=item['outcome_end_date']<=cutoff
        assert _utc(item['captured_at']) <= decision_at
    history=prediction['history']
    assert history and len({row['date'] for row in history})==len(history)
    assert all(float(row['close'])>0 for row in history)
    assert history[-1]['date']<=cutoff
    close=float(history[-1]['close'])
    for horizon in prediction['horizons']:
        returns=np.asarray([float(item['returns'][str(horizon['sessions'])]) for item in neighbours])
        assert np.isfinite(returns).all()
        assert abs(float(horizon['median_return_pct'])-float(np.median(returns)))<0.02
        assert abs(float(horizon['p10_return_pct'])-float(np.quantile(returns,0.1)))<0.02
        assert abs(float(horizon['p90_return_pct'])-float(np.quantile(returns,0.9)))<0.02
        assert abs(float(horizon['up_frequency_pct'])-float(np.mean(returns>0)*100))<0.02
        assert abs(float(horizon['median_price'])-close*(1+float(horizon['median_return_pct'])/100))<0.1
        assert horizon['lower_price']<=horizon['median_price']<=horizon['upper_price']
    assert prediction['fan'] and all(row['p10_price']<=row['median_price']<=row['p90_price'] for row in prediction['fan'])
    warm_started=time.perf_counter()
    second=chart_analogue.predict(symbol)
    warm_elapsed=time.perf_counter()-warm_started
    assert second['horizons']==prediction['horizons']
    from app.services.mirofish.alpha_scanner import _attach_chart_analogue_shadow
    rows = [{'symbol':symbol,'name':prediction['target'],'ranking_score':80.0,
             'alpha_score':75.0,'rank':1,'evidence':[]}]
    summary = _attach_chart_analogue_shadow(rows, generated_at=prediction['as_of'])
    assert summary['ready_count']==1 and summary['ranking_effect']=='none'
    assert (rows[0]['ranking_score'],rows[0]['alpha_score'],rows[0]['rank'])==(80.0,75.0,1)
    assert rows[0]['evidence'][-1]['applied_to_scoring'] is False
    return {'status':'verified','symbol':symbol,'sample_count':len(neighbours),'latest_session':history[-1]['date'],'cold_seconds':round(elapsed,3),'warm_seconds':round(warm_elapsed,3),'checks':['finite_json','unique_history','completed_labels_before_cutoff','independent_return_recalculation','band_ordering','repeatability'],'prediction':prediction}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',default='003690')
    parser.add_argument('--output')
    args=parser.parse_args()
    result=verify(args.symbol)
    if args.output:
        target=Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key!='prediction'},ensure_ascii=True))
