"""Read-only alpha scanner research diagnostics for MCP automation.

This module does not change live scanner ranking. It turns the latest scanner
run artifacts into a compact, machine-readable research brief that an MCP
operator or agent can use before deciding whether to run deeper analysis.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

import app.services.mirofish.alpha_scanner as alpha_scanner


SCHEMA_VERSION = 'mirofish.alpha_research.v1'


def build_alpha_research_snapshot(
    run_id: str | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Build a read-only research snapshot for a scanner run.

    The output is intentionally deterministic and lookahead-safe. It reads only
    scanner run artifacts and advisory outcome summaries, then produces
    diagnostics and an MCP tool plan. It must not mutate scanner scores.
    """
    clean_limit = _clamp_int(limit, 20, 1, 100)
    run = alpha_scanner.read_scanner_run(run_id) if run_id else alpha_scanner.read_latest_scanner_run()
    if not isinstance(run, dict):
        return {
            'ok': False,
            'status': 'scanner_run_not_found',
            'schema_version': SCHEMA_VERSION,
            'run_id': run_id or 'latest',
            'lookahead_safe': True,
            'generated_at': _now_iso(),
        }

    resolved_run_id = str(run.get('id') or run_id or '')
    feature_payload = _artifact(resolved_run_id, 'feature_vectors.json')
    evidence_payload = _artifact(resolved_run_id, 'evidence_ledger.json')
    reject_payload = _artifact(resolved_run_id, 'rejected_candidates.json')

    candidates = [item for item in (run.get('candidates') or []) if isinstance(item, dict)]
    features = _feature_map(feature_payload, candidates)
    evidence_items = [
        item for item in (evidence_payload or {}).get('items', [])
        if isinstance(item, dict)
    ]
    rejected = [
        item for item in (reject_payload or {}).get('candidates', [])
        if isinstance(item, dict)
    ]

    candidate_diagnostics = [
        _candidate_diagnostic(candidate, features.get(_symbol(candidate)), evidence_items)
        for candidate in candidates[:clean_limit]
    ]
    quality = _quality_summary(candidates, features, evidence_items, run)
    factor_profile = _factor_profile(features.values(), evidence_items)
    findings = _research_findings(run, quality, factor_profile, rejected)

    return {
        'ok': True,
        'status': 'ready',
        'schema_version': SCHEMA_VERSION,
        'generated_at': _now_iso(),
        'mission': {
            'primary_objective': 'detect, rank, and validate Korean stocks with the highest forward profit potential',
            'decision_focus': 'profitable stock candidate detection based on reliable data, risk filters, and replayable outcomes',
            'mcp_role': 'supporting data, diagnostic, and automation interface only',
            'non_goal': 'MCP automation itself is not the product objective and must not replace alpha evidence quality',
        },
        'lookahead_safe': True,
        'mutates_scanner_scores': False,
        'run': _run_summary(run),
        'profit_detection_scorecard': run.get('goal_harness') or _research_goal_summary(candidate_diagnostics),
        'quality': quality,
        'factor_profile': factor_profile,
        'candidate_diagnostics': candidate_diagnostics,
        'rejected_summary': _rejected_summary(rejected),
        'research_findings': findings,
        'automation_mcp_blueprint': _automation_mcp_blueprint(findings),
        'next_actions': _next_actions(findings),
        'guardrails': [
            'LLMs may summarize evidence but must not invent numeric scores.',
            'Capital-flow, disclosure, price, and outcome data need source timestamps.',
            'Outcome feedback is advisory until enough forward samples are evaluated.',
            'Ranking changes must be tested with lookahead-safe replay before production use.',
        ],
    }


def _artifact(run_id: str, filename: str) -> dict[str, Any] | None:
    try:
        artifact = alpha_scanner.read_scanner_run_artifact(run_id, filename)
    except (OSError, ValueError):
        return None
    return artifact if isinstance(artifact, dict) else None


def _feature_map(
    feature_payload: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    features = [
        item for item in (feature_payload or {}).get('features', [])
        if isinstance(item, dict)
    ]
    if not features:
        features = [_feature_from_candidate(candidate) for candidate in candidates]
    return {
        _symbol(item): item
        for item in features
        if _symbol(item)
    }


def _feature_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    replay = candidate.get('replay_context') if isinstance(candidate.get('replay_context'), dict) else {}
    return {
        'symbol': candidate.get('symbol'),
        'name': candidate.get('name') or candidate.get('display_name'),
        'market': candidate.get('market'),
        'action': candidate.get('action'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
        'ranking_score': candidate.get('ranking_score'),
        'signal_quality': candidate.get('signal_quality'),
        'strategy_tags': candidate.get('strategy_tags') or [],
        'source_count': profile.get('source_count'),
        'evidence_quality': profile.get('evidence_quality'),
        'confidence_cap': profile.get('confidence_cap'),
        'profitability_scorecard': profile.get('profitability_scorecard'),
        'goal_fit_score': (profile.get('profitability_scorecard') or {}).get('goal_fit_score')
            if isinstance(profile.get('profitability_scorecard'), dict) else None,
        'goal_verdict': (profile.get('profitability_scorecard') or {}).get('goal_verdict')
            if isinstance(profile.get('profitability_scorecard'), dict) else None,
        'freshness_status': profile.get('freshness_status'),
        'data_sources': replay.get('data_sources') or [],
        'current_price': price.get('current_price'),
        'change_rate': price.get('change_rate'),
        'volume': price.get('volume'),
        'trading_value': price.get('trading_value'),
        'trend_quality': profile.get('trend_quality'),
        'volume_accumulation': profile.get('volume_accumulation'),
        'trend_5d_pct': profile.get('trend_5d_pct'),
        'trend_20d_pct': profile.get('trend_20d_pct'),
        'volume_ratio': profile.get('volume_ratio'),
        'volatility_20d_pct': profile.get('volatility_20d_pct'),
        'drawdown_20d_pct': profile.get('drawdown_20d_pct'),
    }


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    freshness = run.get('freshness') if isinstance(run.get('freshness'), dict) else {}
    performance = run.get('performance_advisory') if isinstance(run.get('performance_advisory'), dict) else {}
    return {
        'id': run.get('id'),
        'status': run.get('status'),
        'source': run.get('source'),
        'generated_at': run.get('generated_at') or run.get('created_at'),
        'candidate_count': run.get('candidate_count'),
        'screened_count': run.get('screened_count'),
        'rejected_candidate_count': run.get('rejected_candidate_count'),
        'freshness_status': freshness.get('status'),
        'performance_advisory': {
            'available': bool(performance.get('available')),
            'applied_to_scoring': bool(performance.get('applied_to_scoring')),
            'evaluated_count': performance.get('evaluated_count'),
            'hit_rate_recent': performance.get('hit_rate_recent'),
            'lookahead_safe': performance.get('lookahead_safe', True),
        },
    }


def _quality_summary(
    candidates: list[dict[str, Any]],
    features: dict[str, dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    run: dict[str, Any],
) -> dict[str, Any]:
    selected_features = [features.get(_symbol(candidate), {}) for candidate in candidates]
    grades = Counter()
    freshness = Counter()
    source_counts: list[float] = []
    confidence_caps: list[float] = []
    high_risk = 0
    for candidate in candidates:
        feature = features.get(_symbol(candidate), {})
        grade = _evidence_grade(candidate, feature)
        grades[grade] += 1
        freshness[str(feature.get('freshness_status') or 'unknown')] += 1
        source_counts.append(_float(feature.get('source_count')))
        cap = _float(feature.get('confidence_cap'))
        if cap:
            confidence_caps.append(cap)
        if _float(candidate.get('risk_score')) >= 65:
            high_risk += 1
    return {
        'candidate_count': len(candidates),
        'selected_evidence_grades': dict(grades),
        'freshness_status_counts': dict(freshness),
        'average_source_count': _round(_average(source_counts)),
        'average_confidence_cap': _round(_average(confidence_caps)),
        'high_risk_count': high_risk,
        'weak_evidence_count': grades.get('weak', 0),
        'single_source_count': sum(1 for value in source_counts if value < 3),
        'stale_or_missing_sources': _stale_or_missing_sources(run),
        'evidence_rows': len(evidence_items),
        'feature_rows': len(selected_features),
    }


def _factor_profile(
    feature_values: Any,
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    features = [item for item in feature_values if isinstance(item, dict)]
    fields = [
        'alpha_score',
        'risk_score',
        'ranking_score',
        'change_rate',
        'trend_quality',
        'volume_accumulation',
        'trend_5d_pct',
        'trend_20d_pct',
        'volume_ratio',
        'volatility_20d_pct',
        'drawdown_20d_pct',
        'trading_value',
    ]
    averages = {
        field: _round(_average([_float(item.get(field)) for item in features]))
        for field in fields
    }
    tag_counts = Counter()
    source_counts = Counter()
    market_counts = Counter()
    action_counts = Counter()
    for item in features:
        market_counts[str(item.get('market') or 'UNKNOWN')] += 1
        action_counts[str(item.get('action') or 'UNKNOWN')] += 1
        for tag in item.get('strategy_tags') or []:
            tag_counts[str(tag)] += 1
        for source in item.get('data_sources') or []:
            source_counts[str(source)] += 1
    evidence_sources = Counter()
    for item in evidence_items:
        for evidence in item.get('evidence') or []:
            if isinstance(evidence, dict):
                evidence_sources[str(evidence.get('source') or 'unknown')] += 1
    return {
        'averages': averages,
        'strategy_tag_counts': dict(tag_counts.most_common(12)),
        'data_source_counts': dict(source_counts.most_common(12)),
        'evidence_source_counts': dict(evidence_sources.most_common(12)),
        'market_counts': dict(market_counts),
        'action_counts': dict(action_counts),
        'missing_clusters': _missing_clusters(features, evidence_sources),
    }


def _candidate_diagnostic(
    candidate: dict[str, Any],
    feature: dict[str, Any] | None,
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    feature = feature or {}
    symbol = _symbol(candidate)
    evidence = _candidate_evidence(symbol, evidence_items, candidate)
    sources = _source_set(feature, evidence)
    risks = _candidate_risks(candidate, feature, sources)
    missing = _candidate_missing_clusters(feature, sources)
    scorecard = feature.get('profitability_scorecard') if isinstance(feature.get('profitability_scorecard'), dict) else None
    if scorecard is None:
        scorecard = _fallback_profitability_scorecard(candidate, feature, missing, risks)
    return {
        'symbol': symbol,
        'name': candidate.get('name') or candidate.get('display_name') or feature.get('name'),
        'market': candidate.get('market') or feature.get('market'),
        'rank': candidate.get('rank'),
        'action': candidate.get('action'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
        'ranking_score': candidate.get('ranking_score'),
        'profitability_scorecard': scorecard,
        'goal_fit_score': scorecard.get('goal_fit_score'),
        'goal_verdict': scorecard.get('goal_verdict'),
        'evidence_grade': _evidence_grade(candidate, feature),
        'confidence_cap': feature.get('confidence_cap'),
        'top_strengths': _top_strengths(evidence),
        'primary_risks': risks,
        'missing_evidence_clusters': missing,
        'recommended_mcp_calls': _recommended_mcp_calls(symbol, missing, risks),
    }


def _research_findings(
    run: dict[str, Any],
    quality: dict[str, Any],
    factor_profile: dict[str, Any],
    rejected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    missing_clusters = set(factor_profile.get('missing_clusters') or [])
    if 'capital_flow' in missing_clusters:
        findings.append(_finding(
            'P0',
            'capital_flow_confirmation_missing',
            'Add KIS/KRX/Kiwoom foreigner/institution flow confirmation before raising conviction.',
            'High',
            'Price momentum without confirmed money flow should keep confidence capped.',
        ))
    if quality.get('weak_evidence_count', 0) > 0 or quality.get('single_source_count', 0) > 0:
        findings.append(_finding(
            'P0',
            'evidence_depth_gap',
            'Require at least three independent evidence clusters for strong scanner conviction.',
            'High',
            'Weak evidence candidates can still be queued, but should not dominate Top3.',
        ))
    if 'disclosure_event' in missing_clusters:
        findings.append(_finding(
            'P1',
            'dart_event_risk_missing',
            'Attach OpenDART event and capital-action risk tags to every BUY_CANDIDATE.',
            'Medium',
            'Disclosure risk catches dilution, audit, ownership, and policy catalysts.',
        ))
    if 'factor_validation' in missing_clusters or not (run.get('performance_advisory') or {}).get('available'):
        findings.append(_finding(
            'P1',
            'factor_validation_sample_needed',
            'Promote outcome feedback into an IC/quintile-style validation report before live weight changes.',
            'Medium',
            'This keeps alpha improvements replayable and avoids lookahead bias.',
        ))
    if quality.get('high_risk_count', 0) or rejected:
        findings.append(_finding(
            'P1',
            'risk_rejection_ledger_useful',
            'Use rejected candidate reasons as a negative training ledger for false-positive filters.',
            'Medium',
            'Bad candidates are as useful as winners for reducing noisy scanner alerts.',
        ))
    if 'technical_live_confirmation' in missing_clusters:
        findings.append(_finding(
            'P2',
            'technical_mcp_confirmation_optional',
            'Use TradingView or cached technical MCP only as confirmation, not as a primary buy signal.',
            'Medium',
            'Fail-open technical data should never block the deterministic scanner alone.',
        ))
    return findings


def _fallback_profitability_scorecard(
    candidate: dict[str, Any],
    feature: dict[str, Any],
    missing: list[str],
    risks: list[str],
) -> dict[str, Any]:
    """Best-effort scorecard for historical scanner runs created before goal harness."""
    alpha = _float(candidate.get('alpha_score') or feature.get('alpha_score'))
    risk = _float(candidate.get('risk_score') or feature.get('risk_score'))
    source_count = _float(feature.get('source_count'))
    grade = str(_evidence_grade(candidate, feature)).lower()
    freshness = str(feature.get('freshness_status') or 'unknown').lower()
    score = 0.0
    score += min(22.0, max(0.0, alpha / 100 * 22.0))
    score += min(18.0, max(0.0, (100.0 - risk) / 100 * 18.0))
    score += {'strong': 16.0, 'moderate': 10.0, 'weak': 4.0}.get(grade, 3.0)
    score += min(10.0, source_count / 4 * 10.0)
    score += 12.0 if freshness == 'fresh' else 6.0 if freshness == 'stale' else 2.0
    score += 8.0 if str(candidate.get('action') or feature.get('action')) == 'BUY_CANDIDATE' else 4.0
    score -= min(18.0, len(missing) * 4.0)
    score -= min(18.0, len(risks) * 3.0)
    score = round(max(0.0, min(100.0, score)), 2)
    hard_blockers = [
        item for item in risks
        if item in {'high_risk_score', 'single_source_or_low_source_count', 'source_freshness_risk'}
    ]
    if hard_blockers:
        verdict = 'blocked_by_guardrail'
    elif score >= 70:
        verdict = 'candidate_needs_confirmation' if missing else 'prime_profit_candidate'
    elif score >= 50:
        verdict = 'watch_only'
    else:
        verdict = 'reject_for_now'
    return {
        'schema_version': 'mirofish.profitability_goal.v1',
        'goal': 'detect profitable stock candidates from reliable data',
        'goal_fit_score': score,
        'goal_verdict': verdict,
        'hard_blockers': hard_blockers,
        'missing_confirmations': missing,
        'ranking_effect': 'none_advisory_only',
        'mcp_role': 'supporting_data_confirmation_only',
        'lookahead_safe': True,
        'historical_fallback': True,
    }


def _automation_mcp_blueprint(findings: list[dict[str, Any]]) -> dict[str, Any]:
    finding_codes = {str(item.get('code')) for item in findings}
    return {
        'implemented_tools': [
            {
                'name': 'get_alpha_research_snapshot',
                'mode': 'read_only',
                'purpose': 'Diagnose latest scanner run quality, missing evidence clusters, and next MCP calls.',
                'status': 'implemented',
            },
        ],
        'recommended_tools': [
            {
                'name': 'score_candidate_flow_confirmation',
                'mode': 'read_only_provider',
                'source': 'KIS/KRX/Kiwoom investor flow',
                'trigger': 'capital_flow_confirmation_missing' in finding_codes,
                'expected_effect': 'Raise or cap conviction based on foreigner/institution flow alignment.',
            },
            {
                'name': 'get_dart_event_risk',
                'mode': 'read_only_provider',
                'source': 'OpenDART',
                'trigger': 'dart_event_risk_missing' in finding_codes,
                'expected_effect': 'Penalize dilution, audit, ownership, and event uncertainty risk.',
            },
            {
                'name': 'run_factor_validation_report',
                'mode': 'read_only_evaluation',
                'source': 'scanner feature vectors + forward outcomes',
                'trigger': 'factor_validation_sample_needed' in finding_codes,
                'expected_effect': 'Measure IC, hit rate by tag, and false-positive clusters before changing weights.',
            },
            {
                'name': 'refresh_walk_forward_outcomes',
                'mode': 'guarded_mutation',
                'source': 'daily_prices.csv forward replay',
                'trigger': True,
                'expected_effect': 'Keep Top3 performance feedback fresh without lookahead.',
            },
        ],
    }


def _next_actions(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_rank = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
    actions = [
        {
            'priority': item.get('priority'),
            'code': item.get('code'),
            'action': item.get('recommendation'),
            'impact': item.get('expected_impact'),
            'owner': 'alpha-scanner-mcp',
        }
        for item in findings
    ]
    actions.sort(key=lambda item: priority_rank.get(str(item.get('priority')), 99))
    return actions[:8]


def _research_goal_summary(candidate_diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_float(item.get('goal_fit_score')) for item in candidate_diagnostics]
    verdicts = Counter(str(item.get('goal_verdict') or 'unknown') for item in candidate_diagnostics)
    missing = Counter()
    blockers = Counter()
    for item in candidate_diagnostics:
        scorecard = item.get('profitability_scorecard') if isinstance(item.get('profitability_scorecard'), dict) else {}
        for value in scorecard.get('missing_confirmations') or []:
            missing[str(value)] += 1
        for value in scorecard.get('hard_blockers') or []:
            blockers[str(value)] += 1
    return {
        'schema_version': 'mirofish.profitability_goal.research.v1',
        'primary_objective': 'detect profitable stock candidates from reliable data',
        'average_goal_fit_score': _round(_average(scores)) or 0.0,
        'top_goal_fit_score': round(max(scores), 2) if scores else None,
        'verdict_counts': dict(verdicts),
        'missing_confirmation_counts': dict(missing),
        'hard_blocker_counts': dict(blockers),
        'ranking_effect': 'none_advisory_only',
        'lookahead_safe': True,
    }


def _rejected_summary(rejected: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = Counter()
    for item in rejected:
        for reason in item.get('rejection_reasons') or []:
            reasons[str(reason)] += 1
    return {
        'count': len(rejected),
        'top_rejection_reasons': dict(reasons.most_common(8)),
    }


def _finding(
    priority: str,
    code: str,
    recommendation: str,
    expected_impact: str,
    rationale: str,
) -> dict[str, Any]:
    return {
        'priority': priority,
        'code': code,
        'recommendation': recommendation,
        'expected_impact': expected_impact,
        'rationale': rationale,
    }


def _candidate_evidence(
    symbol: str,
    evidence_items: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    for item in evidence_items:
        if _symbol(item) == symbol:
            return [e for e in (item.get('evidence') or []) if isinstance(e, dict)]
    return [e for e in (candidate.get('evidence') or []) if isinstance(e, dict)]


def _top_strengths(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(evidence, key=lambda item: _float(item.get('score')), reverse=True)
    strengths = []
    for item in ranked[:4]:
        score = _float(item.get('score'))
        if score <= 0:
            continue
        strengths.append({
            'source': item.get('source'),
            'field': item.get('field'),
            'score': _round(score),
            'confidence': item.get('confidence'),
        })
    return strengths


def _candidate_risks(
    candidate: dict[str, Any],
    feature: dict[str, Any],
    sources: set[str],
) -> list[str]:
    risks: list[str] = []
    risk_score = _float(candidate.get('risk_score') or feature.get('risk_score'))
    if risk_score >= 65:
        risks.append('high_risk_score')
    elif risk_score >= 45:
        risks.append('medium_risk_score')
    if _float(feature.get('change_rate')) >= 15:
        risks.append('gap_chase_risk')
    if _float(feature.get('volatility_20d_pct')) >= 8:
        risks.append('volatility_spike_risk')
    if _float(feature.get('drawdown_20d_pct')) <= -12:
        risks.append('drawdown_risk')
    if _float(feature.get('source_count')) < 3:
        risks.append('single_source_or_low_source_count')
    if str(feature.get('freshness_status') or '').lower() not in {'fresh', ''}:
        risks.append('source_freshness_risk')
    if not _has_any_source(sources, ('flow', 'investor', 'institution', 'foreigner', 'kis', 'krx', 'kiwoom')):
        risks.append('unconfirmed_capital_flow')
    return risks


def _candidate_missing_clusters(
    feature: dict[str, Any],
    sources: set[str],
) -> list[str]:
    missing: list[str] = []
    if not _has_any_source(sources, ('flow', 'investor', 'institution', 'foreigner', 'kis', 'krx', 'kiwoom')):
        missing.append('capital_flow')
    if not _has_any_source(sources, ('dart', 'disclosure', 'filing')):
        missing.append('disclosure_event')
    if not _has_any_source(sources, ('tradingview', 'technical')):
        missing.append('technical_live_confirmation')
    if _float(feature.get('source_count')) < 3:
        missing.append('source_convergence')
    return missing


def _recommended_mcp_calls(
    symbol: str,
    missing: list[str],
    risks: list[str],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if 'capital_flow' in missing or 'unconfirmed_capital_flow' in risks:
        calls.append({'tool': 'get_kiwoom_institution_trend', 'args': {'symbol': symbol}})
        calls.append({'tool': 'get_kiwoom_market_investors', 'args': {'market': '001'}})
    if 'disclosure_event' in missing:
        calls.append({'tool': 'get_dart_disclosures', 'args': {'symbol': symbol}})
    if 'technical_live_confirmation' in missing:
        calls.append({'tool': 'analyze_target_comprehensive', 'args': {'symbol': symbol}})
    return calls[:5]


def _missing_clusters(
    features: list[dict[str, Any]],
    evidence_sources: Counter,
) -> list[str]:
    sources = set(evidence_sources.keys())
    for feature in features:
        sources |= set(str(source) for source in (feature.get('data_sources') or []))
    missing: list[str] = []
    if not _has_any_source(sources, ('flow', 'investor', 'institution', 'foreigner', 'kis', 'krx', 'kiwoom')):
        missing.append('capital_flow')
    if not _has_any_source(sources, ('dart', 'disclosure', 'filing')):
        missing.append('disclosure_event')
    if not _has_any_source(sources, ('tradingview', 'technical')):
        missing.append('technical_live_confirmation')
    if not evidence_sources:
        missing.append('factor_validation')
    return missing


def _source_set(feature: dict[str, Any], evidence: list[dict[str, Any]]) -> set[str]:
    sources = {str(source).lower() for source in (feature.get('data_sources') or []) if source}
    sources |= {str(item.get('source') or '').lower() for item in evidence if item.get('source')}
    return sources


def _has_any_source(sources: set[str] | Counter, needles: tuple[str, ...]) -> bool:
    source_text = ' '.join(str(source).lower() for source in sources)
    return any(needle in source_text for needle in needles)


def _evidence_grade(candidate: dict[str, Any], feature: dict[str, Any]) -> str:
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    quality = profile.get('evidence_quality') or feature.get('evidence_quality') or {}
    if isinstance(quality, dict):
        return str(quality.get('grade') or 'unknown')
    return 'unknown'


def _stale_or_missing_sources(run: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for source in run.get('source_files') or []:
        if not isinstance(source, dict):
            continue
        status = str(source.get('freshness_status') or source.get('status') or '').lower()
        if status in {'stale', 'missing', 'partial', 'unknown'}:
            items.append({
                'name': source.get('name') or source.get('file'),
                'role': source.get('role'),
                'status': status,
                'age_days': source.get('age_days'),
            })
    return items


def _symbol(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ''
    return str(item.get('symbol') or '').strip()


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _average(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError):
        clean = default
    return max(low, min(clean, high))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
