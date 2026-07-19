# Brain 13D → TradingAgents 라이브 링크 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라이브 run 의 Brain 13D 레짐 스냅샷을 TradingAgents 딥 검증에 주입하는 온디맨드 run-스코프 엔드포인트 + 최소 대시보드 버튼을 추가해 매수 유력 검출력을 강화한다.

**Architecture:** 신규 `regime.py` 가 Brain 13D → {direction, adjustment, 한줄컨텍스트} 로 정규화. 엔진이 이를 계산해 LLM 경로(프롬프트 1줄)와 rule fallback(PM 밴드 유계 보정, rule일 때만)에 주입. 신규 엔드포인트가 run 의 brain_summary 를 읽어 엔진을 호출하고 결과를 run.json 에 원자적으로 부착. 기존 호출은 `brain=None` 기본값으로 무변경.

**Tech Stack:** Python 3 / Flask (backend), pytest, React + TypeScript (frontend), `write_json_atomic`.

**환경 (고정):**
```bash
PROJECT="/c/bitman_marketfloww"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
```
모든 pytest 실행은 `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest ...` 형태.

**참조 스펙:** `docs/superpowers/specs/2026-07-19-brain13d-tradingagents-live-link-design.md`

---

## Task 1: regime.py — Brain 13D 정규화 모듈

**Files:**
- Create: `app/services/mirofish/tradingagents/regime.py`
- Test: `tests/test_mirofish_tradingagents_regime.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_mirofish_tradingagents_regime.py
import importlib
from app.services.mirofish.tradingagents import regime


def test_none_or_empty_brain_is_neutral_noop():
    rc = regime.regime_context(None)
    assert rc['direction'] == 'neutral'
    assert rc['adjustment'] == 0.0
    assert rc['line'] == ''            # 브레인 없으면 프롬프트 주입 금지
    assert regime.regime_context({})['line'] == ''


def test_bull_regime_with_high_alignment_boosts(monkeypatch):
    monkeypatch.delenv('MIROFISH_TA_REGIME_BOOST', raising=False)
    monkeypatch.delenv('MIROFISH_TA_REGIME_ALIGN_MIN', raising=False)
    rc = regime.regime_context({'regime': 'constructive_accumulation', 'alignment_score': 0.62})
    assert rc['direction'] == 'bull'
    assert rc['adjustment'] == 5.0     # 기본 boost
    assert '완만 강세' in rc['line'] and '0.62' in rc['line']


def test_bull_regime_below_alignment_min_no_boost():
    rc = regime.regime_context({'regime': 'constructive_bullish', 'alignment_score': 0.40})
    assert rc['direction'] == 'bull'
    assert rc['adjustment'] == 0.0     # 정렬 미달 → 무보정


def test_bear_regime_penalizes():
    rc = regime.regime_context({'regime': 'risk_off', 'alignment_score': 0.20})
    assert rc['direction'] == 'bear'
    assert rc['adjustment'] == -5.0


def test_neutral_and_unknown_noop():
    for label in ('neutral_balanced', 'unknown', 'data_unavailable'):
        rc = regime.regime_context({'regime': label, 'alignment_score': 0.9})
        assert rc['direction'] == 'neutral'
        assert rc['adjustment'] == 0.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv('MIROFISH_TA_REGIME_BOOST', '8')
    monkeypatch.setenv('MIROFISH_TA_REGIME_PENALTY', '9')
    monkeypatch.setenv('MIROFISH_TA_REGIME_ALIGN_MIN', '0.50')
    importlib.reload(regime)
    assert regime.regime_context({'regime': 'constructive_bullish', 'alignment_score': 0.55})['adjustment'] == 8.0
    assert regime.regime_context({'regime': 'defensive_caution', 'alignment_score': 0.1})['adjustment'] == -9.0
    importlib.reload(regime)  # restore defaults for other tests
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_regime.py -q`
Expected: FAIL (ModuleNotFoundError: regime).

- [ ] **Step 3: 최소 구현**

```python
# app/services/mirofish/tradingagents/regime.py
"""Brain 13D → TradingAgents 레짐 컨텍스트 정규화.

`regime_context(brain)` 는 Brain 13D 스냅샷을 다음으로 축약한다:
    {regime, alignment, direction('bull'|'bear'|'neutral'), adjustment(float),
     line(str, 프롬프트 주입용 1줄 — 브레인 없으면 '')}
env 는 호출 시점이 아니라 import 시점에 읽어 상수화(테스트는 reload 로 검증).
"""
from __future__ import annotations

import os
from typing import Any

_BULL = {'constructive_bullish', 'constructive_accumulation'}
_BEAR = {'defensive_caution', 'risk_off'}
_LABEL_KO = {
    'constructive_bullish': '강세',
    'constructive_accumulation': '완만 강세(매집)',
    'neutral_balanced': '중립',
    'defensive_caution': '방어',
    'risk_off': '위험회피',
    'unknown': '불명',
    'data_unavailable': '데이터없음',
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


_BOOST = _env_float('MIROFISH_TA_REGIME_BOOST', 5.0)
_PENALTY = _env_float('MIROFISH_TA_REGIME_PENALTY', 5.0)
_ALIGN_MIN = _env_float('MIROFISH_TA_REGIME_ALIGN_MIN', 0.55)


def regime_context(brain: dict[str, Any] | None) -> dict[str, Any]:
    if not brain:
        return {'regime': 'unknown', 'alignment': None, 'direction': 'neutral',
                'adjustment': 0.0, 'line': ''}
    regime = str(brain.get('regime') or 'unknown')
    alignment = _safe_float(brain.get('alignment_score'))
    if regime in _BULL:
        direction = 'bull'
    elif regime in _BEAR:
        direction = 'bear'
    else:
        direction = 'neutral'

    if direction == 'bull' and alignment is not None and alignment >= _ALIGN_MIN:
        adjustment = _BOOST
    elif direction == 'bear':
        adjustment = -_PENALTY
    else:
        adjustment = 0.0

    return {'regime': regime, 'alignment': alignment, 'direction': direction,
            'adjustment': float(adjustment), 'line': _line(regime, alignment)}


def _line(regime: str, alignment: float | None) -> str:
    ko = _LABEL_KO.get(regime, regime)
    al = f'{alignment:.2f}' if alignment is not None else 'N/A'
    return f'시장 레짐: {ko}({regime}, 정렬 {al}). 종목 근거를 우선하되 레짐을 감안하라.'


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_regime.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/tradingagents/regime.py tests/test_mirofish_tradingagents_regime.py
git commit -m "feat(tradingagents): add Brain 13D regime normalization"
```

---

## Task 2: data_hub — brain pass-through

**Files:**
- Modify: `app/services/mirofish/tradingagents/data_hub.py` (`gather_bundle` 시그니처 + 반환 dict)
- Test: `tests/test_mirofish_tradingagents_data_hub.py` (기존 파일에 추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_mirofish_tradingagents_data_hub.py 하단에 추가
def test_gather_bundle_carries_injected_brain(monkeypatch):
    from app.services.mirofish.tradingagents import data_hub
    # live_data / technical 등 외부 소스는 실패해도 됨(각 소스 격리) — brain 주입만 검증
    brain = {'regime': 'constructive_bullish', 'alignment_score': 0.71}
    bundle = data_hub.gather_bundle('삼성전자', brain=brain)
    assert bundle['brain'] == brain


def test_gather_bundle_brain_defaults_empty():
    from app.services.mirofish.tradingagents import data_hub
    bundle = data_hub.gather_bundle('삼성전자')
    assert bundle['brain'] == {}
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_data_hub.py -q -k brain`
Expected: FAIL (`gather_bundle() got an unexpected keyword argument 'brain'`).

- [ ] **Step 3: 구현**

`gather_bundle` 시그니처를 변경하고 반환 dict 에 `brain` 추가:

```python
def gather_bundle(target: str, *, brain: dict[str, Any] | None = None) -> dict[str, Any]:
```
반환 dict(현재 `return {...}`)에 마지막 필드로 추가:
```python
        'errors': errors,
        'brain': brain or {},   # 외부(엔진) 주입 Brain 13D 스냅샷 pass-through
    }
```
그리고 파일 상단 Contract docstring 의 스키마 블록에 `'brain': dict,  # 엔진 주입 Brain 13D, 기본 {}` 한 줄 추가.

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_data_hub.py -q`
Expected: PASS (기존 + 신규 2건).

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/tradingagents/data_hub.py tests/test_mirofish_tradingagents_data_hub.py
git commit -m "feat(tradingagents): pass-through Brain 13D in data bundle"
```

---

## Task 3: analysts — 프롬프트에 레짐 1줄 주입

**Files:**
- Modify: `app/services/mirofish/tradingagents/analysts.py` (`_build_prompt`)
- Test: `tests/test_mirofish_tradingagents_analysts.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_mirofish_tradingagents_analysts.py 하단에 추가
def test_build_prompt_includes_regime_line_when_brain_present():
    from app.services.mirofish.tradingagents import analysts
    bundle = {
        'display_name': '삼성전자', 'symbol': '005930',
        'technical': {}, 'rs': {}, 'corpus': '', 'price': {}, 'fundamentals': {},
        'brain': {'regime': 'constructive_bullish', 'alignment_score': 0.7},
    }
    prompt = analysts._build_prompt('technical', bundle)
    assert '시장 레짐' in prompt


def test_build_prompt_no_regime_line_without_brain():
    from app.services.mirofish.tradingagents import analysts
    bundle = {'display_name': '삼성전자', 'symbol': '005930', 'technical': {}, 'rs': {}}
    assert '시장 레짐' not in analysts._build_prompt('technical', bundle)
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_analysts.py -q -k regime`
Expected: FAIL (`'시장 레짐' not in prompt`).

- [ ] **Step 3: 구현**

`analysts.py` 상단 import 에 추가:
```python
from app.services.mirofish.tradingagents import regime as regime_mod
```
`_build_prompt` 를 수정 (기존 함수 전체 교체):
```python
def _build_prompt(role: str, bundle: dict[str, Any]) -> str:
    name = str(bundle.get('display_name') or bundle.get('target') or '대상')
    symbol = str(bundle.get('symbol') or '')
    header = f'분석 대상: {name} ({symbol})'
    regime_line = regime_mod.regime_context(bundle.get('brain')).get('line') or ''
    regime_block = f'\n[시장 레짐]\n{regime_line}\n' if regime_line else ''
    slice_text = _role_data_slice(role, bundle)
    return f'{header}{regime_block}\n[데이터]\n{slice_text}\n\n{_JSON_INSTRUCTION}'
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_analysts.py -q`
Expected: PASS (기존 + 신규).

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/tradingagents/analysts.py tests/test_mirofish_tradingagents_analysts.py
git commit -m "feat(tradingagents): inject regime line into analyst prompts"
```

---

## Task 4: research_debate — regime_line 파라미터

**Files:**
- Modify: `app/services/mirofish/tradingagents/research_debate.py` (`run_research_debate`, `_llm_side`, `_llm_manager`)
- Test: `tests/test_mirofish_tradingagents_debate.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_mirofish_tradingagents_debate.py 하단에 추가
def test_run_research_debate_accepts_regime_line_rule_path():
    from app.services.mirofish.tradingagents import research_debate
    reports = [{'role': 'technical', 'stance': 'bullish', 'score': 40, 'summary': 's'}]
    # use_llm=False → rule 경로. regime_line 은 무해하게 수용되어야 함(시그니처/회귀).
    out = research_debate.run_research_debate('삼성전자', reports, rounds=1,
                                              use_llm=False, regime_line='시장 레짐: 강세')
    assert out['manager']['stance'] in ('bull', 'bear', 'neutral')
    assert out['method'] == 'rule'
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_debate.py -q -k regime_line`
Expected: FAIL (`unexpected keyword argument 'regime_line'`).

- [ ] **Step 3: 구현**

`run_research_debate` 시그니처에 `regime_line: str = ''` 추가하고 LLM 조각 호출에 전달:
```python
def run_research_debate(
    target: str,
    reports: list[dict[str, Any]],
    *,
    rounds: int = 2,
    use_llm: bool = True,
    regime_line: str = '',
) -> dict[str, Any]:
```
루프 내 `_bull_message`/`_bear_message` 호출과 `_manager_verdict` 호출에 `regime_line` 을 전달하려면,
각 헬퍼의 LLM 서브함수(`_llm_side`, `_llm_manager`)에 `regime_line` 을 프롬프트 앞에 붙인다.
간결하게 하기 위해 `_bull_message`/`_bear_message`/`_manager_verdict` 에 `regime_line` 인자를 추가하고
그대로 `_llm_side`/`_llm_manager` 로 넘긴다. `_llm_side` 프롬프트 조립부를:
```python
def _llm_side(system, json_hint, target, reports, opponent_prev, round_num, *,
              opponent_label, regime_line=''):
    regime_block = f'[시장 레짐]\n{regime_line}\n\n' if regime_line else ''
    prompt = (
        f'분석 대상: {target}\n라운드: {round_num}\n\n{regime_block}'
        f'[애널리스트 리포트]\n{_reports_digest(reports)}\n\n'
        f'[{opponent_label}의 직전 주장]\n{opponent_prev or "(없음)"}\n\n{json_hint}'
    )
    ...
```
`_llm_manager` 도 동일하게 `regime_line` 인자 + `[시장 레짐]` 블록을 transcript 앞에 삽입.
호출 체인(`_bull_message`→`_llm_side`, `_bear_message`→`_llm_side`, `_manager_verdict`→`_llm_manager`)에
`regime_line=regime_line` 를 스레딩. rule 경로는 regime_line 무시(무해).

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_debate.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/tradingagents/research_debate.py tests/test_mirofish_tradingagents_debate.py
git commit -m "feat(tradingagents): thread regime_line into research debate prompts"
```

---

## Task 5: trader_risk — regime_line + rule 유계 보정

**Files:**
- Modify: `app/services/mirofish/tradingagents/trader_risk.py` (`run_trader_and_risk`, `_pm_decision`, `_pm_decision_rule`, `_llm_pm`)
- Test: `tests/test_mirofish_tradingagents_trader_risk.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_mirofish_tradingagents_trader_risk.py 하단에 추가
def _debate(mean):
    return {'_analyst_mean': mean, 'manager': {'confidence': 60}, 'bull_case': '', 'bear_case': ''}


def test_regime_boost_lifts_rule_verdict_band():
    from app.services.mirofish.tradingagents import trader_risk
    # mean 12 → 기본 HOLD(<15). +5 보정 → 17 → BUY.
    out = trader_risk.run_trader_and_risk('삼성전자', {}, _debate(12),
                                          use_llm=False, regime_adjustment=5.0)
    assert out['pm_decision']['verdict'] == 'BUY'


def test_regime_penalty_lowers_rule_verdict_band():
    from app.services.mirofish.tradingagents import trader_risk
    # mean -12 → 기본 HOLD(>-15). -5 보정 → -17 → SELL.
    out = trader_risk.run_trader_and_risk('삼성전자', {}, _debate(-12),
                                          use_llm=False, regime_adjustment=-5.0)
    assert out['pm_decision']['verdict'] == 'SELL'


def test_no_adjustment_matches_baseline():
    from app.services.mirofish.tradingagents import trader_risk
    out = trader_risk.run_trader_and_risk('삼성전자', {}, _debate(12), use_llm=False)
    assert out['pm_decision']['verdict'] == 'HOLD'   # 무보정 회귀
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_trader_risk.py -q -k regime`
Expected: FAIL (`unexpected keyword argument 'regime_adjustment'`).

- [ ] **Step 3: 구현**

`run_trader_and_risk` 시그니처:
```python
def run_trader_and_risk(
    target: str,
    bundle: dict[str, Any],
    debate: dict[str, Any],
    *,
    use_llm: bool = True,
    regime_line: str = '',
    regime_adjustment: float = 0.0,
) -> dict[str, Any]:
```
- 트레이더/리스크 LLM 프롬프트에 regime_line 을 붙이려면 `_trader_plan`/`_risk_entry`/`_pm_decision`
  호출에 `regime_line` 전달 → 각 `_llm_*` 프롬프트 앞에 `[시장 레짐]\n{regime_line}\n\n`(regime_line 있을 때만).
- `_pm_decision` 호출을 `_pm_decision(target, debate, trader_plan, risk_debate, use_llm, regime_line, regime_adjustment)` 로 변경.

`_pm_decision` 수정:
```python
def _pm_decision(target, debate, trader_plan, risk_debate, use_llm,
                 regime_line='', regime_adjustment=0.0):
    rule = _pm_decision_rule(debate, regime_adjustment)
    if use_llm:
        try:
            llm = _llm_pm(target, debate, trader_plan, risk_debate, rule, regime_line)
            if llm:
                return llm, True
        except Exception as exc:  # noqa: BLE001
            logger.warning('[trader_risk] PM LLM failed: %s', exc)
    return rule, False
```

`_pm_decision_rule` 수정 (regime_adjustment 를 밴드 계산에만 반영, 원본 mean 트레이스 보존):
```python
def _pm_decision_rule(debate, regime_adjustment: float = 0.0):
    base_mean = _analyst_mean(debate)
    mean = base_mean + float(regime_adjustment or 0.0)
    manager_conf = _safe_float((debate.get('manager') or {}).get('confidence')) or 50.0

    if mean >= _STRONG_BUY_CUTOFF:
        verdict = 'STRONG_BUY'; confidence = max(_STRONG_BUY_CONF_FLOOR, manager_conf)
    elif mean >= _BUY_CUTOFF:
        verdict = 'BUY'; confidence = manager_conf
    elif mean <= _SELL_CUTOFF:
        verdict = 'SELL'; confidence = manager_conf
    else:
        verdict = 'HOLD'; confidence = manager_conf

    confidence = round(_clamp(confidence, 0.0, 100.0), 2)
    adj_note = (f' (레짐 보정 {regime_adjustment:+.1f} → {mean:+.1f})'
                if regime_adjustment else '')
    reasoning = (f'애널리스트 평균 {base_mean:+.1f}{adj_note}, 리서치 매니저 확신 '
                 f'{manager_conf:.0f} 기준 {verdict} 판정.')
    return {'verdict': verdict, 'confidence': confidence,
            'strong_buy': verdict == 'STRONG_BUY', 'reasoning': reasoning}
```

`_llm_pm` 시그니처에 `regime_line=''` 추가 + 프롬프트 앞 `[시장 레짐]` 블록(있을 때만) 삽입.
`_llm_trader`/`_llm_risk` 도 동일하게 `regime_line=''` 인자 + 블록 삽입, 호출부에서 전달.

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_trader_risk.py -q`
Expected: PASS (기존 + 신규 3).

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/tradingagents/trader_risk.py tests/test_mirofish_tradingagents_trader_risk.py
git commit -m "feat(tradingagents): regime-aware PM (prompt + bounded rule adjustment)"
```

---

## Task 6: engine — run_deep_analysis(brain=...) 배선

**Files:**
- Modify: `app/services/mirofish/tradingagents/engine.py` (`run_deep_analysis`, `_flat_verdict`)
- Test: `tests/test_mirofish_tradingagents_engine.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_mirofish_tradingagents_engine.py 하단에 추가
def test_run_deep_analysis_threads_brain_and_regime(monkeypatch, tmp_path):
    from app.services.mirofish.tradingagents import engine
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    brain = {'regime': 'constructive_bullish', 'alignment_score': 0.8}
    run = engine.run_deep_analysis('삼성전자', symbol='005930', use_llm=False, brain=brain)
    assert run['verdict']['regime'] == 'constructive_bullish'
    assert run['verdict']['regime_adjustment']['direction'] == 'bull'
    assert run['regime_context']['adjustment'] == 5.0


def test_run_deep_analysis_without_brain_is_neutral(monkeypatch, tmp_path):
    from app.services.mirofish.tradingagents import engine
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    run = engine.run_deep_analysis('삼성전자', symbol='005930', use_llm=False)
    assert run['verdict']['regime'] == 'unknown'
    assert run['regime_context']['adjustment'] == 0.0
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_engine.py -q -k brain`
Expected: FAIL (`unexpected keyword argument 'brain'`).

- [ ] **Step 3: 구현**

`engine.py` import 에 추가: `from app.services.mirofish.tradingagents import regime as regime_mod`

`run_deep_analysis` 시그니처에 `brain: dict[str, Any] | None = None` 추가. 본문 수정:
```python
    bundle = data_hub.gather_bundle(target, brain=brain) or {}
    if symbol and not bundle.get('symbol'):
        bundle['symbol'] = symbol

    rc = regime_mod.regime_context(brain)

    with llm_client.collect_generation_metadata() as llm_calls:
        reports = analysts.run_analysts(bundle, use_llm=use_llm)
        effective_rounds = int(rounds) if rounds is not None else _env_rounds()
        effective_rounds = max(_MIN_ROUNDS, min(effective_rounds, _MAX_ROUNDS))
        debate = research_debate.run_research_debate(
            target, reports, rounds=effective_rounds, use_llm=use_llm,
            regime_line=rc['line'],
        )
        debate['_analyst_mean'] = _mean_scores(reports)
        tr = trader_risk.run_trader_and_risk(
            target, bundle, debate, use_llm=use_llm,
            regime_line=rc['line'], regime_adjustment=rc['adjustment'],
        )

    verdict = _flat_verdict(debate, tr, rc)
```
`record` dict 에 `'regime_context': rc,` 한 줄 추가(예: `'verdict': verdict,` 다음).

`_flat_verdict` 에 rc 인자 추가 + regime 필드:
```python
def _flat_verdict(debate, tr, rc=None):
    pm = tr.get('pm_decision') or {}
    rc = rc or {'regime': 'unknown', 'direction': 'neutral', 'alignment': None, 'adjustment': 0.0}
    return {
        'verdict': pm.get('verdict', 'HOLD'),
        'confidence': pm.get('confidence', 0.0),
        'strong_buy': bool(pm.get('strong_buy', False)),
        'reasoning': pm.get('reasoning', ''),
        'bull_case': debate.get('bull_case', ''),
        'bear_case': debate.get('bear_case', ''),
        'risk_summary': _risk_summary(tr.get('risk_debate') or []),
        'regime': rc.get('regime', 'unknown'),
        'regime_adjustment': {
            'direction': rc.get('direction', 'neutral'),
            'alignment': rc.get('alignment'),
            'applied': rc.get('adjustment', 0.0),
        },
    }
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_tradingagents_engine.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/tradingagents/engine.py tests/test_mirofish_tradingagents_engine.py
git commit -m "feat(tradingagents): thread Brain 13D regime through run_deep_analysis"
```

---

## Task 7: store.attach_tradingagents — run 부착 헬퍼

**Files:**
- Modify: `app/services/mirofish/store.py` (신규 public 함수 `attach_tradingagents`)
- Test: `tests/test_mirofish_store_attach_ta.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_mirofish_store_attach_ta.py
def test_attach_tradingagents_writes_summary(monkeypatch, tmp_path):
    from app.services.mirofish import store
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))
    run_id = 'mf_test_005930'
    import os
    os.makedirs(store._run_dir(run_id), exist_ok=True)
    from app.utils.atomic_json import write_json_atomic
    write_json_atomic(os.path.join(store._run_dir(run_id), 'run.json'),
                      {'id': run_id, 'target': '삼성전자'}, sort_keys=False)

    ta = {'id': 'ta_1', 'method': 'rule',
          'verdict': {'verdict': 'BUY', 'confidence': 66, 'strong_buy': False,
                      'regime': 'constructive_bullish',
                      'regime_adjustment': {'direction': 'bull', 'applied': 5.0},
                      'bull_case': 'b', 'bear_case': 'r', 'risk_summary': 'x'}}
    summary = store.attach_tradingagents(run_id, ta)
    assert summary['verdict'] == 'BUY' and summary['run_id'] == 'ta_1'

    saved = store.read_run(run_id)
    assert saved['tradingagents']['verdict'] == 'BUY'
    assert saved['tradingagents']['regime'] == 'constructive_bullish'


def test_attach_tradingagents_missing_run_returns_none(monkeypatch, tmp_path):
    from app.services.mirofish import store
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))
    assert store.attach_tradingagents('mf_nope_000000', {'id': 'ta', 'verdict': {}}) is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_store_attach_ta.py -q`
Expected: FAIL (`module 'store' has no attribute 'attach_tradingagents'`).

- [ ] **Step 3: 구현**

`store.py` 에 신규 public 함수 추가(예: `get_report` 아래, `_build_run` 위 등 public 영역):
```python
def attach_tradingagents(run_id: str, ta: dict[str, Any]) -> dict[str, Any] | None:
    """TradingAgents 딥검증 결과 요약을 run.json 에 원자적으로 부착.

    run 이 없으면 None. verdict 요약만 저장(전문 트레이스는 tradingagents_runs 스토어에 별도 영속).
    """
    safe_id = _safe_run_id(run_id)
    run = read_run(safe_id)
    if not run:
        return None
    v = (ta or {}).get('verdict') or {}
    summary = {
        'run_id': ta.get('id'),
        'verdict': v.get('verdict'),
        'confidence': v.get('confidence'),
        'strong_buy': bool(v.get('strong_buy')),
        'regime': v.get('regime'),
        'regime_adjustment': v.get('regime_adjustment'),
        'method': ta.get('method'),
        'bull_case': v.get('bull_case'),
        'bear_case': v.get('bear_case'),
        'risk_summary': v.get('risk_summary'),
        'attached_at': datetime.now(timezone.utc).isoformat(),
    }
    run['tradingagents'] = summary
    write_json_atomic(os.path.join(_run_dir(safe_id), 'run.json'), run, sort_keys=False)
    return summary
```
(`datetime`, `timezone`, `os`, `write_json_atomic`, `_safe_run_id`, `read_run`, `_run_dir` 는 store.py 에 이미 존재.)

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_store_attach_ta.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/store.py tests/test_mirofish_store_attach_ta.py
git commit -m "feat(mirofish): store.attach_tradingagents run summary helper"
```

---

## Task 8: 엔드포인트 — POST /runs/<run_id>/tradingagents

**Files:**
- Modify: `app/routes/admin_mirofish_tradingagents.py` (신규 라우트)
- Test: `tests/test_admin_mirofish_tradingagents_routes.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_admin_mirofish_tradingagents_routes.py 하단에 추가
# (기존 파일의 admin 클라이언트/토큰 픽스처 패턴을 그대로 재사용한다.)
def test_run_scoped_tradingagents_attaches(monkeypatch, admin_client):
    import app.routes.admin_mirofish_tradingagents as rt
    fake_run = {'id': 'mf_x_005930', 'target': '삼성전자', 'display_name': '삼성전자',
                'symbol': '005930', 'brain_summary': {'regime': 'constructive_bullish',
                                                       'alignment_score': 0.8}}
    monkeypatch.setattr(rt.mirofish_store, 'read_run', lambda rid: fake_run)
    captured = {}
    def fake_deep(target, *, symbol=None, brain=None, **kw):
        captured['brain'] = brain
        return {'id': 'ta_9', 'method': 'rule',
                'verdict': {'verdict': 'BUY', 'confidence': 70, 'strong_buy': False,
                            'regime': 'constructive_bullish',
                            'regime_adjustment': {'direction': 'bull', 'applied': 5.0}}}
    monkeypatch.setattr(rt.engine, 'run_deep_analysis', fake_deep)
    attached = {}
    monkeypatch.setattr(rt.mirofish_store, 'attach_tradingagents',
                        lambda rid, ta: attached.setdefault('ta', ta) or {'verdict': 'BUY'})

    resp = admin_client.post('/api/admin/mirofish/runs/mf_x_005930/tradingagents')
    assert resp.status_code == 200
    assert captured['brain']['regime'] == 'constructive_bullish'   # brain 주입됨
    assert attached['ta']['id'] == 'ta_9'                          # run 에 부착 호출됨


def test_run_scoped_tradingagents_404(monkeypatch, admin_client):
    import app.routes.admin_mirofish_tradingagents as rt
    monkeypatch.setattr(rt.mirofish_store, 'read_run', lambda rid: None)
    resp = admin_client.post('/api/admin/mirofish/runs/mf_nope/tradingagents')
    assert resp.status_code == 404
```

> 주: `admin_client` 픽스처 이름/생성 방식은 기존 `tests/test_admin_mirofish_tradingagents_routes.py`
> 상단에 이미 있는 것을 그대로 사용한다(신규 픽스처 만들지 말 것). 없으면 같은 파일의 기존
> 테스트가 앱/토큰을 만드는 패턴을 복사한다.

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_tradingagents_routes.py -q -k run_scoped`
Expected: FAIL (404 for both — 라우트 없음).

- [ ] **Step 3: 구현**

`admin_mirofish_tradingagents.py` 상단 import 에 추가:
```python
from app.services.mirofish import store as mirofish_store
```
파일 끝에 라우트 추가:
```python
@admin_mirofish_tradingagents_bp.route('/runs/<run_id>/tradingagents', methods=['POST'])
@admin_or_aibain_required
def analyze_run(run_id: str):
    """라이브 run 의 Brain 13D 를 TradingAgents 딥검증에 주입하고 결과를 run 에 부착."""
    run = mirofish_store.read_run(run_id)
    if run is None:
        return jsonify({'error': 'run not found'}), 404
    target = (run.get('display_name') or run.get('target') or '').strip()
    if not target:
        return jsonify({'error': 'run has no target'}), 400
    brain = run.get('brain_summary') or None
    try:
        ta = engine.run_deep_analysis(target, symbol=run.get('symbol'), brain=brain)
        mirofish_store.attach_tradingagents(run_id, ta)
        return jsonify(ta), 200
    except Exception as exc:  # pragma: no cover - defensive production boundary
        return jsonify({'error': str(exc), 'service': 'mirofish-tradingagents'}), 500
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_tradingagents_routes.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routes/admin_mirofish_tradingagents.py tests/test_admin_mirofish_tradingagents_routes.py
git commit -m "feat(tradingagents): run-scoped Brain 13D deep-verify endpoint"
```

---

## Task 9: 프론트엔드 — API + 최소 버튼/카드

**Files:**
- Modify: `frontend-react/src/lib/mirofishApi.ts` (신규 함수 + 타입)
- Create: `frontend-react/src/components/admin/RunTradingAgentsCard.tsx`
- Modify: `frontend-react/src/pages/admin/AdminEndpointsPage.tsx` (run 결과 영역에 카드 렌더)

- [ ] **Step 1: API 함수 + 타입 추가 (`mirofishApi.ts`)**

`mirofishApi` 객체(기존 `getRun`/`getReport` 등이 정의된 곳)에 추가:
```typescript
export interface RunTradingAgentsResult {
    id: string;
    method?: string;
    verdict: {
        verdict: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | string;
        confidence: number;
        strong_buy: boolean;
        regime?: string;
        regime_adjustment?: { direction: string; alignment: number | null; applied: number };
        bull_case?: string;
        bear_case?: string;
        risk_summary?: string;
    };
}
```
`mirofishApi` 객체에 메서드 추가:
```typescript
    runTradingAgentsForRun: async (runId: string): Promise<RunTradingAgentsResult> =>
        fetchAuthAPI<RunTradingAgentsResult>(`/api/admin/mirofish/runs/${runId}/tradingagents`, {
            method: 'POST',
        }),
```
> `fetchAuthAPI` 의 POST 시그니처는 같은 파일의 기존 POST 호출(예: scanner run 트리거)과 동일 형태를 따른다.

- [ ] **Step 2: 카드 컴포넌트 작성 (`RunTradingAgentsCard.tsx`)**

```tsx
import { useState } from 'react';
import { mirofishApi, type RunTradingAgentsResult } from '@/lib/mirofishApi';

const VERDICT_STYLE: Record<string, string> = {
    STRONG_BUY: 'text-emerald-300 border-emerald-400/40 bg-emerald-500/10',
    BUY: 'text-sky-300 border-sky-400/40 bg-sky-500/10',
    HOLD: 'text-gray-300 border-white/15 bg-white/5',
    SELL: 'text-rose-300 border-rose-400/40 bg-rose-500/10',
};

export default function RunTradingAgentsCard({ runId }: { runId: string }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [result, setResult] = useState<RunTradingAgentsResult | null>(null);

    const run = async () => {
        setLoading(true); setError('');
        try {
            setResult(await mirofishApi.runTradingAgentsForRun(runId));
        } catch (e: any) {
            setError(e?.message || 'TradingAgents 딥검증 실패');
        } finally {
            setLoading(false);
        }
    };

    const v = result?.verdict;
    const adj = v?.regime_adjustment;
    return (
        <div className="rounded-2xl border border-white/10 bg-[#0e0e11] p-5">
            <div className="flex items-center justify-between gap-3 mb-3">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <i className="fas fa-shield-halved text-cyan-400" />TradingAgents 딥검증
                </h3>
                <button onClick={run} disabled={loading}
                    className="px-3 py-1.5 rounded-lg text-xs font-bold bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-40">
                    {loading ? <><i className="fas fa-spinner fa-spin mr-1" />검증 중…</> : 'Brain 13D로 딥검증'}
                </button>
            </div>
            {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
            {v && (
                <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className={`px-2 py-0.5 rounded-md border text-xs font-black ${VERDICT_STYLE[v.verdict] || VERDICT_STYLE.HOLD}`}>{v.verdict}</span>
                        <span className="text-xs text-gray-400">확신 {Math.round(v.confidence)}%</span>
                        {v.strong_buy && <span className="text-xs font-bold text-orange-300">🔥 매수 유력</span>}
                        {v.method && <span className="text-[10px] text-gray-500 uppercase">{v.method}</span>}
                    </div>
                    {v.regime && (
                        <div className="text-[11px] text-gray-400">
                            레짐 <span className="text-gray-200">{v.regime}</span>
                            {adj && adj.applied ? <> · 보정 <span className={adj.applied > 0 ? 'text-emerald-300' : 'text-rose-300'}>{adj.applied > 0 ? '+' : ''}{adj.applied}</span></> : null}
                        </div>
                    )}
                    {v.bull_case && <p className="text-[11px] text-emerald-200/80"><b>강세</b> {v.bull_case}</p>}
                    {v.bear_case && <p className="text-[11px] text-rose-200/80"><b>약세</b> {v.bear_case}</p>}
                </div>
            )}
        </div>
    );
}
```

- [ ] **Step 3: run 결과 영역에 렌더 (`AdminEndpointsPage.tsx`)**

`AdminEndpointsPage.tsx` 에서 단일 라이브 run 상세(verdict/판정을 보여주는 섹션)를 찾아
그 아래에 카드를 렌더. import 추가:
```tsx
import RunTradingAgentsCard from '@/components/admin/RunTradingAgentsCard';
```
run 객체(예: `activeRun` / `selectedRun` — 해당 파일에서 현재 run 을 담는 상태변수)가 있는 JSX 위치에:
```tsx
{run?.id && <RunTradingAgentsCard runId={run.id} />}
```
> 정확한 상태변수명/삽입 위치는 파일에서 run verdict 를 렌더하는 지점을 grep(`판정`, `verdict`, `MiroFishRun`)해 확정한다. 조건부 렌더로 run 이 있을 때만 표시.

- [ ] **Step 4: 빌드 검증**

Run:
```bash
cd "$PROJECT/frontend-react" && npx tsc --noEmit && npm run build 2>&1 | tail -5
```
Expected: 타입 에러 0, 빌드 성공.

- [ ] **Step 5: 커밋**

```bash
git add frontend-react/src/lib/mirofishApi.ts frontend-react/src/components/admin/RunTradingAgentsCard.tsx frontend-react/src/pages/admin/AdminEndpointsPage.tsx
git commit -m "feat(ui): run-scoped TradingAgents deep-verify button + card"
```

---

## Task 10: 전체 회귀 + 통합 검증 + 배포

**Files:** (없음 — 검증/배포)

- [ ] **Step 1: 전체 TradingAgents + store + 라우트 회귀**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q -k "tradingagents or mirofish or store or atomic" 2>&1 | tail -8
```
Expected: 전부 PASS (F 없음).

- [ ] **Step 2: 오프라인 통합 스모크 (rule 경로, brain 주입 → verdict.regime 확인)**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from app.services.mirofish.tradingagents import engine
r = engine.run_deep_analysis('삼성전자', symbol='005930', use_llm=False,
    brain={'regime':'constructive_bullish','alignment_score':0.8})
print('verdict=', r['verdict']['verdict'], '| regime=', r['verdict']['regime'],
      '| applied=', r['verdict']['regime_adjustment']['applied'])
"
```
Expected: `regime= constructive_bullish | applied= 5.0` 출력.

- [ ] **Step 3: 배포 (사용자 승인 하에)**

> ⚠ 백엔드 변경 → miniPC 반영은 [[feedback_minipc_flask_restart_hazard]] 준수: kill 금지, **재부팅**으로 활성화.
> 프론트 변경 → `cd frontend-react && npm run deploy` (Cloudflare Pages). git push 는 held-back 커밋과
> 엉키지 않게 이번 세션의 방식대로 처리(수정만 origin/main 반영).

배포 절차는 실행 시점에 사용자와 확인 후 진행.

- [ ] **Step 4: 라이브 검증 (실행 중 Flask)**

miniPC 실행 중 Flask 에 완료된 run 하나를 골라
`POST /api/admin/mirofish/runs/<run_id>/tradingagents` 호출 → 200 + `run.tradingagents` 부착 +
`verdict.regime` 채워짐 확인(admin 토큰은 running Flask 시크릿으로 생성).

---

## Self-Review 결과

- **스펙 커버리지**: §3.1 data_hub(T2) / §3.2·3.3·3.4 엔진·프롬프트·rule보정(T1,T3,T4,T5,T6) / §4 엔드포인트(T7,T8) / §5 FE(T9) / §6 env(T1) / §7 테스트(각 태스크 + T10) — 전 항목 태스크 매핑됨.
- **플레이스홀더**: 없음(코드 전량 기재). FE 삽입 위치만 grep 확정 지시(자기완결 컴포넌트라 안전).
- **타입 일관성**: `regime_context` 반환 키(regime/alignment/direction/adjustment/line)가 T1 정의 후 T3/T5/T6 에서 동일 사용. `attach_tradingagents(run_id, ta)` 시그니처 T7 정의 = T8 호출 일치. `run_deep_analysis(..., brain=)` T6 정의 = T8 호출 일치.
