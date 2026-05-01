"""MiroFish 로컬 라이브 스모크 테스트 — 실제 Gemini API 호출.

전체 파이프라인:
1. Brain 13D 실데이터 로드
2. GraphRAG (실제 Gemini structured output)
3. 5-agent 토론 (실제 Gemini)
4. ReACT CIO (실제 Gemini)
5. 비용 + 시간 측정
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 강제 .env 로드 (shell에 빈 환경변수 있을 수 있음)
env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ[k] = v


def banner(title: str):
    print('\n' + '=' * 70)
    print(f'  {title}')
    print('=' * 70)


def main():
    sample_text = """
    삼성전자가 3분기 실적 호조에 힘입어 5% 상승했다. HBM3E 메모리 수요 폭증이
    배경이며, 엔비디아의 AI 반도체 추가 발주가 확정됐다고 발표했다. SK하이닉스도
    동반 강세를 보이며 반도체 섹터 전반적인 모멘텀이 재점화되고 있다.

    그러나 연준의 금리 동결 기조와 달러 강세는 여전히 부담 요인. 일부 애널리스트는
    중국 경기 둔화에 따른 수요 감소를 우려하고 있다. KOSPI는 2% 상승 마감했지만
    외국인 매도세는 지속되고 있다.

    한편 코스닥 바이오 섹터는 임상 3상 실패 뉴스로 급락했고, 2차전지 관련주는
    유럽 보조금 정책 변경으로 변동성이 커졌다.
    """

    target = "삼성전자"
    cost_estimate = 0.0  # USD

    # ─── 1. Brain 13D ───────────────────────────────
    banner('1. Brain 13D 실데이터 로드')
    t0 = time.time()
    from app.services.mirofish import load_brain_13d_snapshot
    brain = load_brain_13d_snapshot(target)
    t_brain = time.time() - t0

    print(f"⏱️  {t_brain:.2f}s")
    print(f"📊 alignment_score: {brain['alignment_score']}")
    print(f"📊 regime: {brain['regime']}")
    valid = sum(1 for v in brain['dimensions'].values() if v.get('score') is not None)
    print(f"📊 dimensions populated: {valid}/13")
    for name, dim in brain['dimensions'].items():
        score = dim.get('score')
        if score is not None:
            print(f"   - {name}: {score}/100 ({dim.get('evidence', '')[:60]})")

    # ─── 2. GraphRAG (LLM) ──────────────────────────
    banner('2. GraphRAG 추출 (Gemini 2.5 Flash 라이브 호출)')
    t0 = time.time()
    from app.services.mirofish import graphrag_extractor as gr
    graph = gr.extract_graph(sample_text, use_llm=True)
    t_graph = time.time() - t0

    print(f"⏱️  {t_graph:.2f}s")
    print(f"🔧 method: {graph['method']}")
    print(f"📦 entities: {len(graph['entities'])}")
    for e in graph['entities'][:8]:
        print(f"   - [{e['type']}] {e['name']}: {e.get('description', '')[:50]}")
    print(f"🔗 relations: {len(graph['relations'])}")
    for r in graph['relations'][:5]:
        print(f"   - {r['source_id']} --{r['relation_type']}({r['strength']:.2f})--> {r['target_id']}")
        if r.get('evidence'):
            print(f"     근거: {r['evidence'][:60]}")

    # EKG 병합
    stats = gr.merge_into_ekg(graph)
    print(f"📚 EKG: +{stats['new_entities']} entities, +{stats['new_relations']} relations "
          f"(total: {stats['total_entities']}/{stats['total_relations']})")

    if graph['method'] == 'llm':
        cost_estimate += 0.0005  # ~rough Gemini Flash cost per call

    # ─── 3. Multi-agent 토론 (LLM) ──────────────────
    banner('3. 5-agent 토론 (Gemini 라이브 호출)')
    t0 = time.time()
    from app.services.mirofish import agent_debate as ad
    debate = ad.run_debate(target, brain, rounds=2, use_llm=True)
    t_debate = time.time() - t0

    print(f"⏱️  {t_debate:.2f}s")
    print(f"🔧 method: {debate['method']}")
    print(f"🎭 rounds: {len(debate['rounds'])}")
    for r in debate['rounds']:
        print(f"\n  Round {r['round']}:")
        for msg in r['messages']:
            print(f"    {msg['icon']} {msg['agent_name']} [{msg['stance']}] "
                  f"({msg['confidence']:.2f}, cited: {msg['cited_dimensions']})")
            print(f"       \"{msg['message'][:120]}\"")

    consensus = debate['final_consensus']
    print(f"\n🎯 Consensus: {consensus['action']} ({consensus['confidence']:.2f}) "
          f"split={consensus['split']}")

    if debate['method'] == 'llm':
        cost_estimate += 0.002

    # ─── 4. ReACT CIO (LLM) ─────────────────────────
    banner('4. ReACT CIO 7-tool 추론 (Gemini 라이브 호출)')
    t0 = time.time()
    from app.services.mirofish import cio_react as cr
    cio = cr.run_cio(target, brain, debate, use_llm=True)
    t_cio = time.time() - t0

    print(f"⏱️  {t_cio:.2f}s")
    print(f"🔧 method: {cio['method']}")
    print(f"🔁 loops_used: {cio['loops_used']}")
    for step in cio['trace']:
        tool = step['action']['tool']
        thought = step['thought'][:100]
        print(f"\n  Loop {step['loop']} | tool={tool}")
        print(f"    💭 {thought}")
        obs_snippet = json.dumps(step['observation'], ensure_ascii=False)[:120]
        print(f"    👁️  {obs_snippet}")

    fa = cio['final_answer']
    print(f"\n🏁 FINAL VERDICT")
    print(f"   Action: {fa['action']}")
    print(f"   Confidence: {fa['confidence']}")
    print(f"   Allocation: {fa['allocation_pct']}%")
    print(f"   Reasoning: {fa['reasoning'][:200]}")
    print(f"   Opposing: {fa['opposing_scenario'][:200]}")

    if cio['method'] == 'llm':
        cost_estimate += 0.002

    # ─── Summary ───────────────────────────────────
    banner('Summary')
    total_time = t_brain + t_graph + t_debate + t_cio
    print(f"⏱️  Total: {total_time:.2f}s")
    print(f"   Brain:   {t_brain:.2f}s")
    print(f"   GraphRAG:{t_graph:.2f}s ({graph['method']})")
    print(f"   Debate:  {t_debate:.2f}s ({debate['method']})")
    print(f"   CIO:     {t_cio:.2f}s ({cio['method']})")
    print(f"💰 Est. LLM cost: ~${cost_estimate:.4f} USD")
    print()
    print('✅ ALL PHASES COMPLETED')


if __name__ == '__main__':
    main()
