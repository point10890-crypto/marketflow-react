# TradingAgents 딥 검증 레이어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TradingAgents(TauricResearch, Apache-2.0) 다중 에이전트 방법론을 mirofish에 네이티브 이식하여, AI Brain TOP3 확정 전 딥 검증으로 **매수 유력 종목**을 검출한다 (SELL 제외·대체, STRONG_BUY 가점+배지, HOLD 감점).

**Architecture:** 신규 패키지 `app/services/mirofish/tradingagents/` (data_hub → analysts 4인 → bull/bear 토론+리서치매니저 → 트레이더+리스크3인+PM) + `workflow.py` 개입 지점 + admin 엔드포인트 4개. LLM은 기존 `llm_client` 폴백 체인, LLM 실패 시 결정론적 rule fallback (기존 agent_debate/cio_react 패턴).

**Tech Stack:** Python/Flask, llm_client(Gemini→DeepSeek→OpenAI), write_json_atomic, pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-tradingagents-deep-verification-design.md` (필독)

**절대 규칙 (CLAUDE.md):** Bash 경로는 MINGW(`/c/bitman_marketfloww`), Python은 `"$PYTHON"`=`.venv/Scripts/python.exe`, `PYTHONIOENCODING=utf-8` 필수. 테스트: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/<file> -v`.

---

## 공용 계약 (모든 태스크가 이 스키마를 따름 — 변경 금지)

```python
# data_hub.gather_bundle(target: str) -> dict
{
  'target': str, 'symbol': str|None, 'market': str|None, 'display_name': str,
  'price': dict,        # live_data context['price'] (found, price, change_pct, date, volume)
  'corpus': str,        # live_data context['corpus'] (뉴스/공시/시그널 텍스트)
  'technical': dict,    # technical_analysis.analyze_target_with_levels(target) 결과
  'rs': dict,           # sector_rs.get_rs_ratings() 중 symbol 엔트리 (없으면 {})
  'fundamentals': dict, # yfinance .KS/.KQ info 서브셋 + context 내 dart 스냅샷 (없으면 {})
  'errors': dict,       # {source_name: error_str} — 실패 소스 격리 기록
}

# analysts.run_analysts(bundle: dict, *, use_llm: bool = True) -> list[dict]  (항상 4개)
{
  'role': 'fundamentals'|'news'|'sentiment'|'technical',
  'title': str, 'summary': str,             # 리포트 본문 (한국어)
  'stance': 'bullish'|'bearish'|'neutral',
  'score': float,                            # -100..100 (rule 신호 강도)
  'evidence': list[str],                     # 인용 데이터 포인트
  'method': 'llm'|'rule',
}

# research_debate.run_research_debate(target, reports, *, rounds=2, use_llm=True) -> dict
{
  'rounds': [{'round': int,
              'bull': {'message': str}, 'bear': {'message': str}}],
  'bull_case': str, 'bear_case': str,        # 최종 요약 논거
  'manager': {'stance': 'bull'|'bear'|'neutral', 'thesis': str, 'confidence': float},  # 0~100
  'method': 'llm'|'rule'|'mixed',
}

# trader_risk.run_trader_and_risk(target, bundle, debate, *, use_llm=True) -> dict
{
  'trader_plan': {'action_hint': str, 'entry_note': str, 'risk_note': str},
  'risk_debate': [{'role': 'risky'|'safe'|'neutral', 'message': str,
                   'vote': 'approve'|'reject'|'neutral'}],
  'pm_decision': {'verdict': 'STRONG_BUY'|'BUY'|'HOLD'|'SELL',
                  'confidence': float,       # 0~100
                  'strong_buy': bool,        # verdict == STRONG_BUY
                  'reasoning': str},
  'method': 'llm'|'rule'|'mixed',
}

# engine.run_deep_analysis(target, *, symbol=None, rounds=None, use_llm=True) -> dict (런 레코드)
{
  'id': 'ta_<YYYYMMDD_HHMMSS>_<sha1(target)[:6]>',
  'target', 'symbol', 'market', 'created_at', 'completed_at', 'elapsed_ms',
  'bundle_meta': {'errors': dict, 'has_price': bool, 'has_technical': bool,
                  'has_rs': bool, 'has_fundamentals': bool, 'corpus_chars': int},
  'analyst_reports': list[dict], 'research_debate': dict, 'trader_risk': dict,
  'verdict': {  # pm_decision + 논거 플랫 병합 (workflow/텔레그램/FE 노출용)
     'verdict', 'confidence', 'strong_buy', 'reasoning',
     'bull_case', 'bear_case', 'risk_summary',   # risk_summary = risky/safe/neutral 1줄씩
  },
  'method': 'llm'|'rule'|'mixed',
}
```

**env 설정 (engine.py 에서만 읽고 함수 파라미터로 전달):**

| 변수 | 기본 | 의미 |
|------|------|------|
| `MIROFISH_TRADINGAGENTS_DISABLED` | false | 킬스위치 (workflow 단계 전체 스킵) |
| `MIROFISH_TA_MAX_CANDIDATES` | 5 | 딥 검증 대상 후보 수 |
| `MIROFISH_TA_DEBATE_ROUNDS` | 2 | Bull/Bear 라운드 (clamp 1~4) |
| `MIROFISH_TA_BOOST_STRONG` | 8.0 | STRONG_BUY 가점 |
| `MIROFISH_TA_BOOST_BUY` | 5.0 | BUY 최대 가점 (× confidence/100) |
| `MIROFISH_TA_PENALTY_HOLD` | 3.0 | HOLD 감점 |

**영속화:** `data/admin_mirofish/tradingagents_runs/<run_id>.json` + `latest.json` (`app.utils.atomic_json.write_json_atomic`). 목록은 디렉토리 glob mtime 역순.

**rule fallback 판정 산식 (결정론 — 테스트가 이 산식을 검증):**
- analyst rule score: technical(trend up=+40/down=-40, 이평 정배열 +20), rs(rs_rating≥80:+30, ≤20:-30), price(change_pct×3, clamp ±30), news(corpus 내 호재 키워드 [수주,계약,흑자,신고가,급등,무상증자,자사주] count×10 - 악재 키워드 [소송,횡령,적자,하한가,유상증자,감자] count×10, clamp ±40)
- stance: score ≥ 15 → bullish, ≤ -15 → bearish, else neutral
- manager rule: mean(analyst scores) → confidence = min(95, 50 + |mean|/2), stance bull/bear/neutral (±10 경계)
- PM rule verdict: mean ≥ 35 → STRONG_BUY(confidence ≥ 75 보장), ≥ 15 → BUY, ≤ -15 → SELL, else HOLD

**LLM 공통 패턴:** `llm_client.generate_text(prompt, system=..., json_mode=True, max_tokens=2048)` → `json.loads` 실패/None 시 해당 에이전트만 rule fallback, 전체 method는 'mixed'. 프롬프트는 한국어, 반드시 bundle 데이터 포인트 인용 지시 + 출력 JSON 스키마 명시.

---

### Task 1: data_hub.py — 종목 데이터 번들

**Files:**
- Create: `app/services/mirofish/tradingagents/__init__.py` (빈 파일 + docstring)
- Create: `app/services/mirofish/tradingagents/data_hub.py`
- Test: `tests/test_mirofish_tradingagents_data_hub.py`

- [ ] **Step 1: 실패 격리 테스트 작성** — `gather_bundle`이 개별 소스 예외에도 나머지 필드를 채우고 `errors`에 기록하는지, live_data/technical_analysis 를 monkeypatch 로 대체해 검증 (네트워크 금지)

```python
import app.services.mirofish.tradingagents.data_hub as data_hub

def test_gather_bundle_isolates_source_failures(monkeypatch):
    monkeypatch.setattr(data_hub.live_data, 'build_context', lambda t: {
        'resolved': {'symbol': '005930', 'market': 'KOSPI', 'display_name': '삼성전자'},
        'price': {'found': True, 'price': 70000, 'change_pct': 2.1, 'date': '2026-07-17'},
        'corpus': '삼성전자 수주 뉴스', 'dart': {},
    })
    monkeypatch.setattr(data_hub.technical_analysis, 'analyze_target_with_levels',
                        lambda t: (_ for _ in ()).throw(RuntimeError('boom')))
    monkeypatch.setattr(data_hub, '_load_rs_entry', lambda symbol: {'rs_rating': 85})
    monkeypatch.setattr(data_hub, '_load_fundamentals', lambda symbol, market, ctx: {})
    b = data_hub.gather_bundle('삼성전자')
    assert b['symbol'] == '005930' and b['price']['found']
    assert b['technical'] == {} and 'technical' in b['errors']
    assert b['rs'] == {'rs_rating': 85}
```

- [ ] **Step 2: 테스트 실패 확인** — `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_data_hub.py -v` → ModuleNotFoundError
- [ ] **Step 3: 구현** — `gather_bundle(target)`: `live_data.build_context(target)` 1회 호출로 resolved/price/corpus/dart 확보(이미 내부 실패 격리됨), 이어서 각각 try/except로 `technical_analysis.analyze_target_with_levels(target)`, `_load_rs_entry(symbol)` (sector_rs.get_rs_ratings(data_root=DATA_ROOT, allow_compute=False) → ratings.get(symbol)), `_load_fundamentals(symbol, market, context)` (yfinance Ticker(f"{symbol}.KS"|".KQ").info 서브셋: marketCap, trailingPE, forwardPE, priceToBook, returnOnEquity, revenueGrowth, debtToEquity — ImportError/네트워크 실패 시 dart 스냅샷만). 각 실패는 `errors[source]=str(exc)` 기록 후 빈 dict
- [ ] **Step 4: 테스트 통과 확인** — 동일 명령 PASS
- [ ] **Step 5: Commit** — `feat(tradingagents): add KR-native data hub for deep analysis`

### Task 2: analysts.py — 분석가 4인

**Files:**
- Create: `app/services/mirofish/tradingagents/analysts.py`
- Test: `tests/test_mirofish_tradingagents_analysts.py`

- [ ] **Step 1: rule 경로 테스트 작성** — use_llm=False 로 4개 리포트/stance/score 산식 검증

```python
from app.services.mirofish.tradingagents import analysts

BUNDLE = {
    'target': '삼성전자', 'symbol': '005930', 'market': 'KOSPI', 'display_name': '삼성전자',
    'price': {'found': True, 'price': 70000, 'change_pct': 4.0, 'date': '2026-07-17'},
    'corpus': '삼성전자 대규모 수주 계약 체결. 신고가 경신.',
    'technical': {'trend': 'up', 'ma_aligned': True},
    'rs': {'rs_rating': 90}, 'fundamentals': {'trailingPE': 12.0}, 'errors': {},
}

def test_rule_analysts_produce_four_reports():
    reports = analysts.run_analysts(BUNDLE, use_llm=False)
    assert [r['role'] for r in reports] == ['fundamentals', 'news', 'sentiment', 'technical']
    assert all(r['method'] == 'rule' for r in reports)
    tech = next(r for r in reports if r['role'] == 'technical')
    assert tech['stance'] == 'bullish' and tech['score'] > 0  # trend up + 정배열 + RS 90

def test_rule_news_keyword_scoring():
    bearish = dict(BUNDLE, corpus='소송 제기, 대규모 적자 전환, 유상증자 결정')
    reports = analysts.run_analysts(bearish, use_llm=False)
    news = next(r for r in reports if r['role'] == 'news')
    assert news['stance'] == 'bearish'
```

- [ ] **Step 2: 실패 확인** (모듈 없음)
- [ ] **Step 3: 구현** — 역할별 `_rule_report(role, bundle)` (공용 계약의 산식: technical 은 trend/ma_aligned/rs, news·sentiment 는 키워드 스코어 — sentiment 는 news 점수에 change_pct 가중 합성, fundamentals 는 PE/ROE 존재 시 간단 밸류에이션 점수, 데이터 없으면 neutral/score 0 + evidence 에 '데이터 부족' 명기). `_llm_report(role, bundle)`: 역할별 system 프롬프트(TradingAgents Analyst Team 이식 — 각자 관점·데이터만 사용, 근거 인용 강제) + json_mode, 출력 {title, summary, stance, score, evidence}. use_llm=True 면 역할별 LLM 시도→개별 실패 시 rule
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** — `feat(tradingagents): add four-analyst report layer`

### Task 3: research_debate.py — Bull/Bear 토론 + 리서치 매니저

**Files:**
- Create: `app/services/mirofish/tradingagents/research_debate.py`
- Test: `tests/test_mirofish_tradingagents_debate.py`

- [ ] **Step 1: 테스트 작성**

```python
from app.services.mirofish.tradingagents import research_debate

REPORTS = [
    {'role': 'fundamentals', 'stance': 'bullish', 'score': 30, 'summary': 'PER 저평가', 'evidence': []},
    {'role': 'news', 'stance': 'bullish', 'score': 40, 'summary': '수주 계약', 'evidence': []},
    {'role': 'sentiment', 'stance': 'neutral', 'score': 5, 'summary': '중립', 'evidence': []},
    {'role': 'technical', 'stance': 'bullish', 'score': 50, 'summary': '정배열 신고가', 'evidence': []},
]

def test_rule_debate_structure_and_bull_win():
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=2, use_llm=False)
    assert len(result['rounds']) == 2
    assert result['manager']['stance'] == 'bull'          # mean=31.25 > 10
    assert 50 <= result['manager']['confidence'] <= 95    # 50+31.25/2 ≈ 65.6
    assert result['bull_case'] and result['bear_case']

def test_rounds_clamped():
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=99, use_llm=False)
    assert len(result['rounds']) == 4
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — rule: 라운드마다 bull 은 bullish 리포트 요약 조합, bear 는 bearish/neutral 리스크 조합 메시지 생성(라운드 번호 명시, 결정론). manager rule 산식은 공용 계약. LLM: 라운드별 bull→bear 순차 호출(상대 직전 발언을 프롬프트에 포함 — TradingAgents 구조화 토론 이식), 마지막에 manager 가 전체 트랜스크립트 심판 {stance, thesis, confidence}. 부분 실패 시 method='mixed'
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** — `feat(tradingagents): add bull/bear research debate with manager verdict`

### Task 4: trader_risk.py — 트레이더 + 리스크 3인 + PM

**Files:**
- Create: `app/services/mirofish/tradingagents/trader_risk.py`
- Test: `tests/test_mirofish_tradingagents_trader_risk.py`

- [ ] **Step 1: 테스트 작성**

```python
from app.services.mirofish.tradingagents import trader_risk

BUNDLE = {'target': '삼성전자', 'price': {'found': True, 'price': 70000, 'change_pct': 4.0},
          'technical': {'trend': 'up'}, 'rs': {'rs_rating': 90}, 'corpus': '수주', 'errors': {}}

def _debate(mean_hint):
    return {'manager': {'stance': 'bull' if mean_hint > 0 else 'bear',
                        'thesis': 't', 'confidence': 80},
            'bull_case': 'b', 'bear_case': 'r',
            '_analyst_mean': mean_hint}  # rule 경로 입력

def test_pm_strong_buy_thresholds():
    out = trader_risk.run_trader_and_risk('삼성전자', BUNDLE, _debate(40), use_llm=False)
    pm = out['pm_decision']
    assert pm['verdict'] == 'STRONG_BUY' and pm['strong_buy'] and pm['confidence'] >= 75
    assert len(out['risk_debate']) == 3

def test_pm_sell_and_hold():
    assert trader_risk.run_trader_and_risk('t', BUNDLE, _debate(-30), use_llm=False)['pm_decision']['verdict'] == 'SELL'
    assert trader_risk.run_trader_and_risk('t', BUNDLE, _debate(5), use_llm=False)['pm_decision']['verdict'] == 'HOLD'
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — debate 결과에 `_analyst_mean`(analyst score 평균)을 engine 이 주입(rule 경로 입력). rule: trader_plan 은 technical levels/trend 기반 문장, risk 3인은 결정론 vote(risky=approve if mean>0, safe=reject if 변동성·악재 키워드, neutral=중재), PM verdict 산식은 공용 계약(STRONG_BUY 시 confidence=max(75, manager.confidence)). LLM: TradingAgents Trader/Risk Team/Portfolio Manager 프롬프트 이식(한국어) — trader 1회, risk 3역할 각 1회, PM 1회(전체 컨텍스트 심판). 부분 실패 mixed
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** — `feat(tradingagents): add trader, risk team, and PM final decision`

### Task 5: engine.py — 오케스트레이션 + 영속화

**Files:**
- Create: `app/services/mirofish/tradingagents/engine.py` (docstring 에 Apache-2.0 출처 명기: "Pipeline architecture ported from TauricResearch/TradingAgents (Apache-2.0)")
- Test: `tests/test_mirofish_tradingagents_engine.py`

- [ ] **Step 1: 테스트 작성** — tmp_path 로 RUNS_ROOT monkeypatch, use_llm=False 전체 파이프라인 결정론 + 영속화 + list/get/status 검증

```python
import app.services.mirofish.tradingagents.engine as engine

def _patch_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.data_hub, 'gather_bundle', lambda t: {
        'target': t, 'symbol': '005930', 'market': 'KOSPI', 'display_name': t,
        'price': {'found': True, 'price': 70000, 'change_pct': 4.0, 'date': '2026-07-17'},
        'corpus': '수주 계약 신고가', 'technical': {'trend': 'up', 'ma_aligned': True},
        'rs': {'rs_rating': 90}, 'fundamentals': {}, 'errors': {}})

def test_run_deep_analysis_rule_end_to_end(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    assert run['verdict']['verdict'] in ('STRONG_BUY', 'BUY', 'HOLD', 'SELL')
    assert run['method'] == 'rule' and run['id'].startswith('ta_')
    assert len(run['analyst_reports']) == 4
    assert engine.get_run(run['id'])['id'] == run['id']
    assert engine.list_runs(limit=5)[0]['id'] == run['id']
    st = engine.get_status()
    assert st['enabled'] is True and st['last_run_id'] == run['id']

def test_kill_switch_status(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setenv('MIROFISH_TRADINGAGENTS_DISABLED', 'true')
    assert engine.get_status()['enabled'] is False
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — `run_deep_analysis`: gather_bundle → run_analysts → run_research_debate(rounds=env clamp 1~4) → debate 에 `_analyst_mean` 주입 → run_trader_and_risk → verdict 플랫 병합(bull_case/bear_case/risk_summary 포함) → 레코드 조립 → `write_json_atomic(<RUNS_ROOT>/<id>.json)` + `latest.json`. method 집계: 전 단계 rule→'rule', 전 llm→'llm', 혼합→'mixed'. `is_disabled()`, `get_status()` (enabled, config env 값들, last_run_id/at, runs_count), `list_runs(limit)` (파일 glob mtime 역순, 요약 필드만), `get_run(run_id)` (path traversal 방지: run_id 는 `^ta_[0-9_]+_[0-9a-f]{6}$` regex 검증)
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** — `feat(tradingagents): add deep analysis engine with persistence`

### Task 6: workflow.py 개입 — TOP3 재선정

**Files:**
- Modify: `app/services/mirofish/workflow.py` (`_complete_workflow` 내 `ranked = sorted(...)` 직후 ~L798, `build_workflow_top3_telegram_message` ~L460)
- Test: `tests/test_mirofish_tradingagents_workflow.py`

- [ ] **Step 1: 개입 규칙 테스트 작성** — engine.run_deep_analysis monkeypatch 로 결정론 검증

```python
from app.services.mirofish import workflow

def _ranked():
    return [
        {'candidate': {'symbol': f'00{i}'}, 'run_id': f'r{i}', 'final_score': 90 - i * 10,
         'verdict': {'action': 'BUY'}} for i in range(4)  # 90,80,70,60
    ]

def _fake_engine(verdict_map):
    def fake(target, **kw):
        v = verdict_map.get(target, ('HOLD', 50))
        return {'id': f'ta_{target}', 'method': 'rule',
                'verdict': {'verdict': v[0], 'confidence': v[1], 'strong_buy': v[0] == 'STRONG_BUY',
                            'bull_case': 'b', 'bear_case': 'r', 'risk_summary': 's', 'reasoning': 'x'}}
    return fake

def test_sell_excluded_and_replaced(monkeypatch):
    ranked = _ranked()
    for i, item in enumerate(ranked):
        item['candidate']['display_name'] = f'종목{i}'
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis',
                        _fake_engine({'종목0': ('SELL', 80), '종목1': ('BUY', 80),
                                      '종목2': ('STRONG_BUY', 85), '종목3': ('HOLD', 50)}))
    adjusted, summary = workflow._apply_tradingagents_layer(ranked, top_n=3, require_buy=True)
    top = adjusted[:3]
    symbols = [t['candidate']['symbol'] for t in top]
    assert '000' not in symbols                                # SELL 제외
    assert top[0]['candidate']['symbol'] == '002'              # 70+8(STRONG) > 80+5*0.8=84 → 002=78? 아님
    # 산식 검증: 001 BUY→80+5*0.8=84, 002 STRONG→70+8=78, 003 HOLD→60-3=57
    assert top[0]['candidate']['symbol'] == '001' and top[0]['ta_adjusted_score'] == 84.0
    assert top[1]['tradingagents']['strong_buy'] is True
    assert summary['excluded'] == ['000']

def test_kill_switch_no_change(monkeypatch):
    monkeypatch.setenv('MIROFISH_TRADINGAGENTS_DISABLED', 'true')
    ranked = _ranked()
    adjusted, summary = workflow._apply_tradingagents_layer(ranked, top_n=3, require_buy=True)
    assert adjusted == ranked and summary['status'] == 'disabled'

def test_engine_failure_falls_back(monkeypatch):
    def boom(target, **kw):
        raise RuntimeError('llm down')
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis', boom)
    ranked = _ranked()
    adjusted, summary = workflow._apply_tradingagents_layer(ranked, top_n=3, require_buy=True)
    assert [r['final_score'] for r in adjusted[:3]] == [90, 80, 70]  # 무보정
    assert summary['analyzed'] == 0
```

(첫 테스트의 기대값 산식: BUY 84.0 > STRONG_BUY 78.0 > HOLD 57.0 — 원점수가 지배하되 판정이 재조정)

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — workflow.py 상단 `from app.services.mirofish.tradingagents import engine as ta_engine`. 신규 함수:

```python
def _apply_tradingagents_layer(ranked, *, top_n, require_buy):
    """TradingAgents 딥 검증: BUY 후보 상위 N 분석 → SELL 제외, 점수 재조정.
    실패 시 ranked 원본 그대로 반환 (무손상 폴백)."""
    if ta_engine.is_disabled():
        return ranked, {'status': 'disabled', 'analyzed': 0, 'excluded': []}
    cfg = ta_engine.get_status()['config']  # max_candidates, boost_strong, boost_buy, penalty_hold
    eligible = [r for r in ranked if _verdict_is_buy(r)] if require_buy else list(ranked)
    targets = eligible[:cfg['max_candidates']]
    excluded, analyzed = [], 0
    for item in targets:
        cand = item.get('candidate') or {}
        name = cand.get('display_name') or cand.get('name') or cand.get('symbol')
        try:
            run = ta_engine.run_deep_analysis(name, symbol=cand.get('symbol'))
        except Exception as exc:
            item['tradingagents'] = {'status': 'failed', 'error': str(exc)}
            continue
        analyzed += 1
        v = run.get('verdict') or {}
        base = float(item.get('final_score') or 0.0)
        verdict = v.get('verdict')
        if verdict == 'SELL':
            item['ta_excluded'] = True
            excluded.append(cand.get('symbol'))
        elif verdict == 'STRONG_BUY':
            item['ta_adjusted_score'] = base + cfg['boost_strong']
        elif verdict == 'BUY':
            item['ta_adjusted_score'] = base + cfg['boost_buy'] * (float(v.get('confidence') or 0) / 100.0)
        elif verdict == 'HOLD':
            item['ta_adjusted_score'] = base - cfg['penalty_hold']
        item['tradingagents'] = {
            'run_id': run.get('id'), 'verdict': verdict,
            'confidence': v.get('confidence'), 'strong_buy': bool(v.get('strong_buy')),
            'bull_case': v.get('bull_case'), 'bear_case': v.get('bear_case'),
            'risk_summary': v.get('risk_summary'), 'method': run.get('method'),
        }
    def sort_key(r):
        return r.get('ta_adjusted_score', r.get('final_score') or -999)
    adjusted = sorted([r for r in ranked if not r.get('ta_excluded')], key=sort_key, reverse=True)
    adjusted += [r for r in ranked if r.get('ta_excluded')]   # 제외 종목은 꼬리에 보존(기록용)
    return adjusted, {'status': 'applied', 'analyzed': analyzed, 'excluded': excluded,
                      'config': cfg}
```

`_complete_workflow` 에서 `ranked = sorted(...)` 직후:

```python
    try:
        ranked, ta_summary = _apply_tradingagents_layer(ranked, top_n=top_n, require_buy=_require_buy(workflow))
    except Exception as exc:
        ta_summary = {'status': 'error', 'error': str(exc)}
    workflow['tradingagents_summary'] = ta_summary
```

(`_select_top3` 는 그대로 — 재정렬·제외가 이미 반영된 ranked 를 받음. `ta_excluded` 항목은 `_verdict_is_buy` 여부와 무관하게 TOP 진입 불가해야 하므로 `_select_top3` 의 eligible 필터에 `and not r.get('ta_excluded')` 1줄 추가.)

`build_workflow_top3_telegram_message` 항목 루프에 (기존 포맷 유지, 항목당 1줄 추가):

```python
        ta = item.get('tradingagents') or {}
        if ta.get('verdict'):
            badge = ' 🔥매수유력' if ta.get('strong_buy') else ''
            lines.append(f"  🤝 TradingAgents: {ta['verdict']} {round(float(ta.get('confidence') or 0))}%{badge}")
```

- [ ] **Step 4: 신규 + 기존 워크플로우 테스트 통과 확인** — `pytest tests/test_mirofish_tradingagents_workflow.py tests/test_admin_mirofish_workflow.py -v`
- [ ] **Step 5: Commit** — `feat(tradingagents): intervene in TOP3 selection with deep verification`

### Task 7: admin 엔드포인트 4개

**Files:**
- Create: `app/routes/admin_mirofish_tradingagents.py`
- Modify: `app/routes/__init__.py` (기존 admin_mirofish_analysis_bp 등록 라인 옆에 동일 prefix `/api/admin/mirofish` 로 등록)
- Test: `tests/test_admin_mirofish_tradingagents_routes.py`

- [ ] **Step 1: 라우트 테스트 작성** — 기존 `tests/test_admin_mirofish_agent_status.py` 의 앱/인증 fixture 패턴을 그대로 복사(conftest 의 admin 클라이언트 사용, 없으면 해당 파일 패턴대로 monkeypatch). engine 함수들을 monkeypatch:

```python
def test_analyze_endpoint(admin_client, monkeypatch):
    import app.routes.admin_mirofish_tradingagents as mod
    monkeypatch.setattr(mod.engine, 'run_deep_analysis',
                        lambda target, **kw: {'id': 'ta_x', 'verdict': {'verdict': 'BUY'}})
    resp = admin_client.post('/api/admin/mirofish/tradingagents/analyze', json={'symbol': '005930', 'name': '삼성전자'})
    assert resp.status_code == 200 and resp.get_json()['verdict']['verdict'] == 'BUY'

def test_analyze_requires_target(admin_client):
    assert admin_client.post('/api/admin/mirofish/tradingagents/analyze', json={}).status_code == 400

def test_runs_and_status(admin_client, monkeypatch):
    import app.routes.admin_mirofish_tradingagents as mod
    monkeypatch.setattr(mod.engine, 'list_runs', lambda limit=20: [{'id': 'ta_x'}])
    monkeypatch.setattr(mod.engine, 'get_run', lambda rid: {'id': rid} if rid == 'ta_x' else None)
    monkeypatch.setattr(mod.engine, 'get_status', lambda: {'enabled': True})
    assert admin_client.get('/api/admin/mirofish/tradingagents/runs').get_json()['runs'][0]['id'] == 'ta_x'
    assert admin_client.get('/api/admin/mirofish/tradingagents/runs/ta_x').status_code == 200
    assert admin_client.get('/api/admin/mirofish/tradingagents/runs/nope').status_code == 404
    assert admin_client.get('/api/admin/mirofish/tradingagents/status').get_json()['enabled'] is True
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — admin_mirofish_analysis.py 스타일 그대로 (`admin_or_aibain_required`… 단, 실행형 POST 는 `admin_required` 가 있으면 그걸로 — `app.auth.decorators` 확인 후 기존 실행형 엔드포인트가 쓰는 데코레이터와 동일하게):

```python
"""TradingAgents deep-verification endpoints. URL prefix: /api/admin/mirofish"""
from flask import Blueprint, jsonify, request
from app.auth.decorators import admin_or_aibain_required
from app.services.mirofish.tradingagents import engine

admin_mirofish_tradingagents_bp = Blueprint('admin_mirofish_tradingagents', __name__)

@admin_mirofish_tradingagents_bp.route('/tradingagents/analyze', methods=['POST'])
@admin_or_aibain_required
def analyze():
    payload = request.get_json(silent=True) or {}
    target = (payload.get('name') or payload.get('symbol') or '').strip()
    if not target:
        return jsonify({'error': 'symbol or name required'}), 400
    try:
        rounds = payload.get('rounds')
        run = engine.run_deep_analysis(target, symbol=payload.get('symbol'),
                                       rounds=int(rounds) if rounds else None)
        return jsonify(run), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'service': 'mirofish-tradingagents'}), 500
# + GET /tradingagents/runs, /tradingagents/runs/<run_id> (404 처리), /tradingagents/status
```

- [ ] **Step 4: 통과 확인 + 스킬 4 전체 검증 (엔진 임포트/라우트 카운트)**
- [ ] **Step 5: Commit** — `feat(tradingagents): add admin endpoints for deep analysis`

### Task 8: 통합 검증

- [ ] **Step 1: 전체 pytest** — `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -x -q` → 기존 회귀 0
- [ ] **Step 2: 로컬 스모크 (LLM 실사용 1종목)** — `PYTHONIOENCODING=utf-8 "$PYTHON" -c "from app.services.mirofish.tradingagents.engine import run_deep_analysis; import json; r=run_deep_analysis('삼성전자'); print(r['method'], r['verdict']['verdict'], r['verdict']['confidence'])"` → 판정 출력 확인 (LLM 키 없으면 rule 로도 성공해야 함)
- [ ] **Step 3: Commit (잔여 변경)** — `test(tradingagents): full-suite verification`

### Task 9: 배포 + miniPC 최종 검증 (메인 세션이 직접 수행 — 서브에이전트 금지)

- [ ] **Step 1: push** — `git push origin main`
- [ ] **Step 2: miniPC pull** — `ssh 192.168.55.103 'powershell -Command "cd C:\bitman_marketfloww; git -c rebase.autoStash=true pull --rebase origin main"'`
- [ ] **Step 3: 백엔드 반영 = miniPC 재부팅** (Flask SSH 재시작 금지 — phantom socket boot-loop 이력): `ssh 192.168.55.103 'powershell -Command "Restart-Computer -Force"'` → 90초 대기
- [ ] **Step 4: 프로덕션 검증** — health 200 확인 후 admin 토큰으로 `/api/admin/mirofish/tradingagents/status` 200 + `enabled:true` 확인, 온디맨드 analyze 1종목 실행해 verdict 확인
- [ ] **Step 5: 프론트 배포 없음 확인** — frontend-react 변경 0 이므로 npm run deploy 불필요 (배지 UI 는 후속)

---

## Self-Review 결과
- 스펙 §2 파이프라인(4인/토론/매니저/트레이더/리스크/PM) → Task 2~5. §4 개입규칙/킬스위치/폴백/텔레그램 → Task 6. §5 엔드포인트 4개 → Task 7. §8 테스트 4종 → Task 1~7 각 스텝 + Task 8. 커버리지 공백 없음.
- 타입 일관성: verdict 스키마·env 명·함수 시그니처 공용 계약 절에 단일 정의, 각 태스크가 참조.
- Task 6 테스트 기대값 산식 재검산: 001 BUY = 80 + 5×0.8 = 84.0 / 002 STRONG = 70+8 = 78.0 / 003 HOLD = 60−3 = 57.0 → 정렬 [001, 002, 003]. 일치.
