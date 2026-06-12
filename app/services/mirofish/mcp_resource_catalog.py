"""Read-only MCP resource catalog for alpha-detection source planning.

The scanner should not know about every possible external MCP server.  This
module keeps resource metadata, source-gap checks, and adoption priorities in a
small deterministic layer that can be exposed to the admin UI or MCP server.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


CATALOG_VERSION = 'mirofish.mcp_resource_catalog.v1'
ALPHA_ENDPOINT_BLUEPRINT_VERSION = 'mirofish.alpha_endpoint_blueprint.v1'


_RESOURCE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        'id': 'kis_mcp',
        'name': 'KIS MCP Server',
        'category': 'market_data',
        'adoption_phase': 'now',
        'alpha_value_score': 95,
        'source_grade': 'S',
        'data_roles': ['kr_live_quote', 'kr_price_history', 'capital_flow', 'sector_index'],
        'alpha_use': [
            'confirm live price and liquidity before Top 3 notification',
            'cross-check foreigner/institution flow when available',
            'reduce stale local-file false positives',
        ],
        'risk_controls': [
            'read_only_only',
            'block_order_and_account_tools',
            'freshness_required_for_telegram',
            'rate_limit_per_symbol',
        ],
        'blocked_capabilities': ['order', 'balance', 'account', 'withdrawal'],
        'notes': 'Best first resource because MarketFlow already depends on KIS-style Korean market data.',
    },
    {
        'id': 'korea_stock_mcp',
        'name': 'Korea Stock MCP (KRX + OpenDART)',
        'category': 'filing_fundamental',
        'adoption_phase': 'now',
        'alpha_value_score': 90,
        'source_grade': 'S',
        'data_roles': ['krx_reference', 'dart_disclosure', 'financial_statement', 'hard_blocker'],
        'alpha_use': [
            'detect disclosure and financial hard blockers',
            'improve evidence quality for scanner candidates',
            'separate policy/earnings evidence from rumor-only themes',
        ],
        'risk_controls': [
            'cache_filings',
            'classify_disclosures_before_scoring',
            'never_use_single_filing_as_buy_signal',
        ],
        'blocked_capabilities': [],
        'notes': 'High value for Korean equity evidence and risk filtering.',
    },
    {
        'id': 'krx_short_credit_mcp',
        'name': 'KRX Short/Credit Risk MCP',
        'category': 'risk_gate',
        'adoption_phase': 'now',
        'alpha_value_score': 88,
        'source_grade': 'S',
        'data_roles': ['short_selling', 'credit_balance', 'investment_warning', 'trading_halt'],
        'alpha_use': [
            'remove short/credit crowding traps before Top 3 ranking',
            'separate healthy momentum from leverage-driven blow-off risk',
            'hard-block management, halt, and investment-warning candidates',
        ],
        'risk_controls': [
            'read_only_only',
            'hard_blocker_before_llm',
            'freshness_required_for_telegram',
            'do_not_use_as_buy_signal',
        ],
        'blocked_capabilities': ['order', 'account', 'balance'],
        'notes': 'High false-positive reduction value; should sit before GraphRAG and LLM debate.',
    },
    {
        'id': 'alpha_vantage_mcp',
        'name': 'Alpha Vantage MCP',
        'category': 'global_regime',
        'adoption_phase': 'pilot',
        'alpha_value_score': 78,
        'source_grade': 'A',
        'data_roles': ['global_index', 'fx', 'etf', 'macro_indicator', 'technical_indicator'],
        'alpha_use': [
            'add DXY, USD/KRW proxy, US index, ETF, and macro context',
            'cap conviction when global regime conflicts with Korean flow',
        ],
        'risk_controls': [
            'use_as_regime_context_not_primary_signal',
            'cache_and_track_rate_limit',
            'show_provider_latency',
        ],
        'blocked_capabilities': [],
        'notes': 'Useful for regime and cross-market confirmation, not a Korean stock detector by itself.',
    },
    {
        'id': 'bok_fred_macro_mcp',
        'name': 'BOK ECOS + FRED Macro Regime MCP',
        'category': 'global_regime',
        'adoption_phase': 'pilot',
        'alpha_value_score': 76,
        'source_grade': 'S',
        'data_roles': ['usd_krw', 'rates', 'dxy_proxy', 'macro_liquidity', 'risk_regime'],
        'alpha_use': [
            'cap confidence when macro/FX regime conflicts with Korean flow',
            'raise sustainability score when liquidity, FX, and flow align',
            'prevent Top 3 overconfidence during risk-off sessions',
        ],
        'risk_controls': [
            'regime_context_only',
            'no_single_factor_buy_signal',
            'source_timestamp_required',
        ],
        'blocked_capabilities': [],
        'notes': 'Useful for confidence caps and regime labels; not a standalone stock picker.',
    },
    {
        'id': 'exa_search_mcp',
        'name': 'Exa Search MCP',
        'category': 'news_research',
        'adoption_phase': 'pilot',
        'alpha_value_score': 68,
        'source_grade': 'B',
        'data_roles': ['news_search', 'policy_event', 'theme_validation'],
        'alpha_use': [
            'validate whether a theme has fresh external evidence',
            'collect URLs for GraphRAG evidence packets',
        ],
        'risk_controls': [
            'secondary_evidence_only',
            'source_grade_required',
            'dedupe_by_url_and_timestamp',
        ],
        'blocked_capabilities': [],
        'notes': 'Good evidence collector, but must not become a standalone buy signal.',
    },
    {
        'id': 'firecrawl_mcp',
        'name': 'Firecrawl MCP',
        'category': 'news_research',
        'adoption_phase': 'pilot',
        'alpha_value_score': 64,
        'source_grade': 'B',
        'data_roles': ['web_extract', 'report_extract', 'news_extract'],
        'alpha_use': [
            'convert articles and reports into structured evidence packets',
            'improve GraphRAG source text coverage',
        ],
        'risk_controls': [
            'respect_site_terms',
            'secondary_evidence_only',
            'store_fetch_time_and_url',
        ],
        'blocked_capabilities': [],
        'notes': 'Useful only when paired with official price/filing/flow data.',
    },
    {
        'id': 'naver_attention_mcp',
        'name': 'Naver DataLab/Search Attention MCP',
        'category': 'news_research',
        'adoption_phase': 'pilot',
        'alpha_value_score': 62,
        'source_grade': 'C',
        'data_roles': ['search_attention', 'news_frequency', 'theme_attention'],
        'alpha_use': [
            'detect attention expansion after official flow and price confirmation',
            'flag crowded attention as overheating risk',
            'collect Korean keyword evidence for GraphRAG source packets',
        ],
        'risk_controls': [
            'secondary_evidence_only',
            'never_buy_from_attention_alone',
            'crowding_can_increase_risk',
        ],
        'blocked_capabilities': [],
        'notes': 'Helpful as a supporting signal, but C-grade attention data must not drive Top 3 alone.',
    },
    {
        'id': 'neo4j_mcp',
        'name': 'Neo4j MCP',
        'category': 'graph_memory',
        'adoption_phase': 'later',
        'alpha_value_score': 72,
        'source_grade': 'infra',
        'data_roles': ['knowledge_graph', 'entity_relation', 'multi_hop_reasoning'],
        'alpha_use': [
            'persist entity relationships for theme and supply-chain reasoning',
            'support replayable GraphRAG instead of one-off run artifacts',
        ],
        'risk_controls': [
            'schema_allowlist',
            'read_write_split',
            'graph_updates_audited',
        ],
        'blocked_capabilities': ['generic_cypher_mutation_from_llm'],
        'notes': 'Good architecture upgrade after source quality gates are stable.',
    },
    {
        'id': 'qdrant_mcp',
        'name': 'Qdrant MCP',
        'category': 'vector_memory',
        'adoption_phase': 'later',
        'alpha_value_score': 70,
        'source_grade': 'infra',
        'data_roles': ['evidence_memory', 'outcome_memory', 'similar_case_search'],
        'alpha_use': [
            'retrieve similar past winners and false positives',
            'connect Top 3 results with forward outcome memory',
        ],
        'risk_controls': [
            'lookahead_safe_indexing',
            'separate_train_and_forward_windows',
            'store_source_grade',
        ],
        'blocked_capabilities': [],
        'notes': 'Valuable for learning, but only after outcome labels are disciplined.',
    },
    {
        'id': 'enterprise_market_data_mcp',
        'name': 'Enterprise Market Data MCP (FactSet/LSEG/S&P)',
        'category': 'enterprise_data',
        'adoption_phase': 'defer',
        'alpha_value_score': 82,
        'source_grade': 'A',
        'data_roles': ['institutional_data', 'fundamental_data', 'professional_news'],
        'alpha_use': [
            'raise institutional-grade source coverage when licensed',
            'replace weak public proxies with high-quality vendor data',
        ],
        'risk_controls': [
            'license_review_required',
            'cost_gate_required',
            'do_not_cache_beyond_contract',
        ],
        'blocked_capabilities': [],
        'notes': 'Strong data, but not a near-term implementation without licensing.',
    },
    {
        'id': 'softr_portal',
        'name': 'Softr Portal/API',
        'category': 'portal_feedback',
        'adoption_phase': 'defer',
        'alpha_value_score': 35,
        'source_grade': 'ops',
        'data_roles': ['subscriber_portal', 'feedback_capture'],
        'alpha_use': [
            'collect user feedback on Top 3 results',
            'show read-only operating snapshots to subscribers',
        ],
        'risk_controls': [
            'backend_proxy_only',
            'no_admin_mutations_from_portal',
            'rotate_plaintext_tokens',
        ],
        'blocked_capabilities': ['admin_trigger', 'scanner_mutation', 'telegram_send'],
        'notes': 'Useful for workflow UX, not a direct alpha source.',
    },
)


_SOURCE_REQUIREMENTS: tuple[dict[str, Any], ...] = (
    {
        'id': 'kr_live_price',
        'label': 'KR live price and liquidity',
        'required_for_top3': True,
        'resource_ids': ['kis_mcp'],
        'primary_patterns': ['kis api', 'kis_quote', 'kis_live_price_flow', 'kis_live_snapshot_latest.json', 'inquire-price', 'live quote'],
        'fallback_patterns': ['daily_prices.csv', 'price_history'],
    },
    {
        'id': 'capital_flow',
        'label': 'Foreigner/institution flow confirmation',
        'required_for_top3': True,
        'resource_ids': ['kis_mcp'],
        'primary_patterns': [
            'investor flow',
            'foreign_net',
            'institution_net',
            'all_institutional_trend_data.csv',
            'capital_flow_confirmation',
        ],
        'fallback_patterns': [],
    },
    {
        'id': 'filing_fundamental',
        'label': 'KRX/DART filing and financial hard blockers',
        'required_for_top3': True,
        'resource_ids': ['korea_stock_mcp'],
        'primary_patterns': ['dart', 'opendart', 'filing', 'financial_statement', 'kind_blacklist'],
        'fallback_patterns': ['korean_stocks_list.csv', 'ticker_to_yahoo_map.csv'],
    },
    {
        'id': 'short_credit_risk',
        'label': 'Short selling, credit balance, and market-warning risk gates',
        'required_for_top3': True,
        'resource_ids': ['krx_short_credit_mcp', 'korea_stock_mcp'],
        'primary_patterns': [
            'credit_balance',
            'credit_balance_risk',
            'short_selling',
            'short sale',
            'risk_blacklist',
            'kind_blacklist',
            'investment_warning',
            'trading_halt',
        ],
        'fallback_patterns': ['kind_blacklist_latest.json', 'credit_balance_latest.json'],
    },
    {
        'id': 'global_regime',
        'label': 'Global macro, FX, ETF, and regime context',
        'required_for_top3': False,
        'resource_ids': ['bok_fred_macro_mcp', 'alpha_vantage_mcp'],
        'primary_patterns': ['dxy', 'usd-krw', 'usd_krw', 'treasury', 'rates', 'ecos', 'fred', 'etf', 'global_index'],
        'fallback_patterns': ['market_gate', 'fear_greed'],
    },
    {
        'id': 'news_issue_validation',
        'label': 'News, policy, and theme validation',
        'required_for_top3': False,
        'resource_ids': ['exa_search_mcp', 'firecrawl_mcp'],
        'primary_patterns': ['news', 'briefing', 'policy_event', 'theme_validation', 'web_extract'],
        'fallback_patterns': ['market_briefing'],
    },
    {
        'id': 'attention_secondary',
        'label': 'Search/news/social attention as secondary signal only',
        'required_for_top3': False,
        'resource_ids': ['naver_attention_mcp', 'exa_search_mcp', 'firecrawl_mcp'],
        'primary_patterns': ['search_attention', 'datalab', 'naver', 'news_theme_social', 'theme_attention'],
        'fallback_patterns': ['news_theme_social_latest.json', 'market_briefing'],
    },
    {
        'id': 'graph_memory',
        'label': 'GraphRAG entity and relationship memory',
        'required_for_top3': False,
        'resource_ids': ['neo4j_mcp'],
        'primary_patterns': ['graphrag', 'knowledge_graph', 'entity_relation', 'source_packets'],
        'fallback_patterns': ['hybrid_rag_source_packets'],
    },
    {
        'id': 'outcome_memory',
        'label': 'Forward outcome and similar-case memory',
        'required_for_top3': True,
        'resource_ids': ['qdrant_mcp'],
        'primary_patterns': ['outcome', 'performance_memory', 'forward_return', 'hit_rate'],
        'fallback_patterns': ['performance_advisory', 'backtest'],
    },
)


_ALPHA_ENDPOINT_BLUEPRINTS: tuple[dict[str, Any], ...] = (
    {
        'id': 'kr_flow_batch',
        'priority': 'P0',
        'name': 'KR capital-flow confirmation batch',
        'http_method': 'GET',
        'internal_path': '/api/admin/mirofish/sources/kr-flow/batch',
        'mcp_tool': 'get_kr_investor_flow_batch',
        'resource_ids': ['kis_mcp'],
        'requirement_ids': ['capital_flow', 'kr_live_price'],
        'source_grade': 'S',
        'alpha_impact': 'Boost only when price, liquidity, and foreigner/institution flow align; penalize price-up/flow-out divergence.',
        'pipeline_position': 'before_rank_and_before_telegram',
    },
    {
        'id': 'kr_disclosure_risk_batch',
        'priority': 'P0',
        'name': 'DART/KIND disclosure risk batch',
        'http_method': 'GET',
        'internal_path': '/api/admin/mirofish/sources/disclosure-risk/batch',
        'mcp_tool': 'get_disclosure_risk_batch',
        'resource_ids': ['korea_stock_mcp'],
        'requirement_ids': ['filing_fundamental', 'short_credit_risk'],
        'source_grade': 'S',
        'alpha_impact': 'Hard-filter capital impairment, trading halt, audit, dilution, and management-risk events before Top 3.',
        'pipeline_position': 'risk_gate_before_graphrag',
    },
    {
        'id': 'kr_short_credit_pressure',
        'priority': 'P0',
        'name': 'Short/credit pressure gate',
        'http_method': 'GET',
        'internal_path': '/api/admin/mirofish/sources/kr-risk/short-credit',
        'mcp_tool': 'get_short_credit_pressure',
        'resource_ids': ['krx_short_credit_mcp'],
        'requirement_ids': ['short_credit_risk'],
        'source_grade': 'S',
        'alpha_impact': 'Remove leverage/crowding traps and raise risk when credit or short pressure is stale or adverse.',
        'pipeline_position': 'false_positive_gate',
    },
    {
        'id': 'macro_regime_cap',
        'priority': 'P1',
        'name': 'BOK/FRED macro and FX regime cap',
        'http_method': 'GET',
        'internal_path': '/api/admin/mirofish/sources/macro-regime',
        'mcp_tool': 'get_macro_regime_snapshot',
        'resource_ids': ['bok_fred_macro_mcp', 'alpha_vantage_mcp'],
        'requirement_ids': ['global_regime'],
        'source_grade': 'S/A',
        'alpha_impact': 'Cap conviction when USD/KRW, rates, volatility, or global risk regime conflicts with KR flow.',
        'pipeline_position': 'confidence_cap_after_rank',
    },
    {
        'id': 'attention_secondary_signal',
        'priority': 'P2',
        'name': 'Naver/news attention secondary signal',
        'http_method': 'GET',
        'internal_path': '/api/admin/mirofish/sources/attention',
        'mcp_tool': 'get_attention_secondary_signal',
        'resource_ids': ['naver_attention_mcp', 'exa_search_mcp', 'firecrawl_mcp'],
        'requirement_ids': ['attention_secondary', 'news_issue_validation'],
        'source_grade': 'B/C',
        'alpha_impact': 'Use only as supporting evidence or overheating warning after official flow/price/disclosure checks pass.',
        'pipeline_position': 'supporting_context_only',
    },
    {
        'id': 'outcome_memory_similar_cases',
        'priority': 'P1',
        'name': 'Outcome-memory similar-case search',
        'http_method': 'GET',
        'internal_path': '/api/admin/mirofish/learning/similar-cases',
        'mcp_tool': 'get_similar_outcome_cases',
        'resource_ids': ['qdrant_mcp'],
        'requirement_ids': ['outcome_memory'],
        'source_grade': 'infra',
        'alpha_impact': 'Compare each candidate with past winners/false positives without look-ahead leakage and adjust ranking bounds.',
        'pipeline_position': 'after_feature_vector_before_top3',
    },
)


def list_mcp_resource_catalog(
    *,
    include_deferred: bool = True,
    category: str | None = None,
    min_alpha_value: int | float | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic MCP resource candidates sorted by alpha value."""
    clean_category = str(category or '').strip().lower()
    floor = _number(min_alpha_value)
    items: list[dict[str, Any]] = []
    for item in _RESOURCE_CATALOG:
        if not include_deferred and item['adoption_phase'] == 'defer':
            continue
        if clean_category and item['category'] != clean_category:
            continue
        if floor is not None and float(item['alpha_value_score']) < floor:
            continue
        items.append(_resource_view(item))
    items.sort(key=lambda row: (float(row['alpha_value_score']), row['id']), reverse=True)
    return items


def get_mcp_resource(resource_id: str) -> dict[str, Any] | None:
    """Return one resource from the catalog."""
    clean_id = str(resource_id or '').strip().lower()
    for item in _RESOURCE_CATALOG:
        if item['id'] == clean_id:
            return _resource_view(item)
    return None


def build_mcp_resource_snapshot(
    *,
    scanner_run: dict[str, Any] | None | bool = None,
    workflow: dict[str, Any] | None | bool = None,
    include_deferred: bool = True,
    category: str | None = None,
) -> dict[str, Any]:
    """Return catalog plus source-gap and adoption-plan summaries.

    Passing False for scanner_run or workflow skips latest-artifact loading. This
    keeps tests and callers deterministic when they only need the catalog.
    """
    loaded_scanner = _latest_scanner_run() if scanner_run is None else None if scanner_run is False else scanner_run
    loaded_workflow = _latest_workflow() if workflow is None else None if workflow is False else workflow
    catalog = list_mcp_resource_catalog(include_deferred=include_deferred, category=category)
    source_gaps = evaluate_mcp_source_gaps(
        scanner_run=loaded_scanner if isinstance(loaded_scanner, dict) else None,
        workflow=loaded_workflow if isinstance(loaded_workflow, dict) else None,
    )
    adoption_plan = build_mcp_adoption_plan(source_gaps=source_gaps, catalog=catalog)
    endpoint_blueprint = build_alpha_endpoint_blueprint(
        scanner_run=loaded_scanner if isinstance(loaded_scanner, dict) else None,
        workflow=loaded_workflow if isinstance(loaded_workflow, dict) else None,
        source_gaps=source_gaps,
        catalog=catalog,
    )
    return {
        'schema_version': CATALOG_VERSION,
        'mode': 'alpha_detection_resource_planning',
        'generated_at': _now_iso(),
        'catalog_count': len(catalog),
        'catalog': catalog,
        'source_gaps': source_gaps,
        'adoption_plan': adoption_plan,
        'alpha_endpoint_blueprint': endpoint_blueprint,
        'rules': {
            'primary_goal': 'detect, rank, validate, and monitor forward-profit candidates',
            'no_direct_scanner_coupling': True,
            'orders_blocked': True,
            'news_social_secondary_only': True,
            'secrets_redacted': True,
        },
    }


def build_alpha_endpoint_blueprint(
    *,
    scanner_run: dict[str, Any] | None | bool = None,
    workflow: dict[str, Any] | None | bool = None,
    source_gaps: dict[str, Any] | None = None,
    catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return implementation-grade endpoint contracts focused on Top 3 quality."""
    loaded_scanner = _latest_scanner_run() if scanner_run is None else None if scanner_run is False else scanner_run
    loaded_workflow = _latest_workflow() if workflow is None else None if workflow is False else workflow
    resources = {item['id']: item for item in (catalog or list_mcp_resource_catalog())}
    gaps = source_gaps or evaluate_mcp_source_gaps(
        scanner_run=loaded_scanner if isinstance(loaded_scanner, dict) else None,
        workflow=loaded_workflow if isinstance(loaded_workflow, dict) else None,
    )
    requirements = {item['id']: item for item in gaps.get('requirements') or []}
    endpoints: list[dict[str, Any]] = []
    for blueprint in _ALPHA_ENDPOINT_BLUEPRINTS:
        requirement_rows = [
            requirements.get(requirement_id, {
                'id': requirement_id,
                'status': 'unknown',
                'required_for_top3': False,
                'evidence_hits': [],
            })
            for requirement_id in blueprint['requirement_ids']
        ]
        resource_rows = [
            resources.get(resource_id) or get_mcp_resource(resource_id)
            for resource_id in blueprint['resource_ids']
        ]
        endpoints.append({
            **blueprint,
            'current_status': _endpoint_status(requirement_rows),
            'requirements': requirement_rows,
            'resources': [
                {
                    'id': resource['id'],
                    'name': resource['name'],
                    'category': resource['category'],
                    'alpha_value_score': resource['alpha_value_score'],
                    'adoption_phase': resource['adoption_phase'],
                    'source_grade': resource['source_grade'],
                }
                for resource in resource_rows
                if isinstance(resource, dict)
            ],
            'risk_controls': _merge_resource_controls(resource_rows),
            'read_only_required': True,
            'orders_blocked': True,
            'implementation_contract': {
                'facts_must_be_deterministic': True,
                'store_source_grade': True,
                'store_fetched_at': True,
                'store_freshness': True,
                'llm_may_explain_not_invent': True,
            },
        })

    priority_order = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
    endpoints.sort(key=lambda item: (priority_order.get(item['priority'], 9), item['id']))
    return {
        'schema_version': ALPHA_ENDPOINT_BLUEPRINT_VERSION,
        'objective': 'improve profitable Top 3 candidate detection, not MCP automation for its own sake',
        'generated_at': _now_iso(),
        'scanner_run_id': (loaded_scanner or {}).get('id') if isinstance(loaded_scanner, dict) else None,
        'workflow_id': (loaded_workflow or {}).get('id') if isinstance(loaded_workflow, dict) else None,
        'source_readiness': {
            'status': gaps.get('readiness'),
            'required_total': gaps.get('required_total'),
            'required_covered': gaps.get('required_covered'),
            'required_partial': gaps.get('required_partial'),
            'required_missing': gaps.get('required_missing'),
            'summary': gaps.get('summary'),
        },
        'endpoint_count': len(endpoints),
        'p0_count': sum(1 for item in endpoints if item['priority'] == 'P0'),
        'endpoints': endpoints,
        'next_actions': _next_endpoint_actions(endpoints),
        'non_goals': [
            'do not add order/account/balance tools',
            'do not promote news/social/search attention to standalone buy evidence',
            'do not allow an LLM to create tickers, prices, or disclosures',
        ],
    }


def evaluate_mcp_source_gaps(
    *,
    scanner_run: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate which evidence roles are covered by latest scanner/workflow data."""
    searchable = _searchable_text(scanner_run, workflow)
    requirements: list[dict[str, Any]] = []
    missing_required = 0
    partial_required = 0
    covered_required = 0

    for requirement in _SOURCE_REQUIREMENTS:
        primary_hits = _matching_patterns(searchable, requirement['primary_patterns'])
        fallback_hits = _matching_patterns(searchable, requirement['fallback_patterns'])
        if primary_hits:
            status = 'covered'
            covered = True
        elif fallback_hits:
            status = 'partial'
            covered = False
        else:
            status = 'missing'
            covered = False

        required = bool(requirement['required_for_top3'])
        if required and status == 'covered':
            covered_required += 1
        elif required and status == 'partial':
            partial_required += 1
        elif required and status == 'missing':
            missing_required += 1

        requirements.append({
            'id': requirement['id'],
            'label': requirement['label'],
            'required_for_top3': required,
            'status': status,
            'covered': covered,
            'evidence_hits': primary_hits or fallback_hits,
            'fallback_only': bool(fallback_hits and not primary_hits),
            'recommended_resource_ids': list(requirement['resource_ids']),
        })

    required_total = covered_required + partial_required + missing_required
    if not scanner_run and not workflow:
        readiness = 'unknown'
    elif missing_required:
        readiness = 'blocked'
    elif partial_required:
        readiness = 'limited'
    else:
        readiness = 'ready'

    return {
        'readiness': readiness,
        'required_total': required_total,
        'required_covered': covered_required,
        'required_partial': partial_required,
        'required_missing': missing_required,
        'scanner_run_id': (scanner_run or {}).get('id'),
        'workflow_id': (workflow or {}).get('id'),
        'requirements': requirements,
        'summary': _gap_summary(readiness, covered_required, partial_required, missing_required),
    }


def build_mcp_adoption_plan(
    *,
    source_gaps: dict[str, Any],
    catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a prioritized adoption plan from source gaps and catalog metadata."""
    resources = {item['id']: item for item in (catalog or list_mcp_resource_catalog())}
    needed_ids: set[str] = set()
    for requirement in source_gaps.get('requirements') or []:
        if requirement.get('status') == 'covered':
            continue
        for resource_id in requirement.get('recommended_resource_ids') or []:
            needed_ids.add(str(resource_id))

    immediate: list[dict[str, Any]] = []
    pilot: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for resource_id in sorted(needed_ids):
        resource = resources.get(resource_id) or get_mcp_resource(resource_id)
        if not resource:
            continue
        row = {
            'id': resource['id'],
            'name': resource['name'],
            'category': resource['category'],
            'alpha_value_score': resource['alpha_value_score'],
            'adoption_phase': resource['adoption_phase'],
            'data_roles': resource['data_roles'],
            'risk_controls': resource['risk_controls'],
        }
        if resource['adoption_phase'] == 'now':
            immediate.append(row)
        elif resource['adoption_phase'] == 'pilot':
            pilot.append(row)
        else:
            later.append(row)

    for bucket in (immediate, pilot, later):
        bucket.sort(key=lambda row: (float(row['alpha_value_score']), row['id']), reverse=True)

    return {
        'objective': 'close evidence gaps that matter for Top 3 alpha detection',
        'immediate': immediate,
        'pilot': pilot,
        'later': later,
        'do_not_attach_directly': [
            'order execution tools',
            'account/balance tools',
            'generic filesystem tools',
            'unverified social/news-only signals',
        ],
    }


def _endpoint_status(requirements: list[dict[str, Any]]) -> str:
    statuses = {str(item.get('status') or 'unknown').lower() for item in requirements}
    required = [item for item in requirements if item.get('required_for_top3')]
    required_statuses = {str(item.get('status') or 'unknown').lower() for item in required}
    if required and required_statuses <= {'covered'}:
        return 'ready'
    if 'missing' in required_statuses:
        return 'blocked'
    if 'partial' in required_statuses:
        return 'limited'
    if statuses and statuses <= {'covered'}:
        return 'ready'
    if 'covered' in statuses and not required:
        return 'optional_ready'
    if 'partial' in statuses:
        return 'optional_limited'
    if 'missing' in statuses:
        return 'planned'
    return 'unknown'


def _merge_resource_controls(resources: list[dict[str, Any] | None]) -> list[str]:
    controls: set[str] = set()
    for resource in resources or []:
        if not isinstance(resource, dict):
            continue
        controls.update(str(item) for item in resource.get('risk_controls') or [])
    return sorted(controls)


def _next_endpoint_actions(endpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_order = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
    rows = []
    for endpoint in endpoints:
        if endpoint.get('current_status') in {'ready', 'optional_ready'}:
            continue
        rows.append({
            'id': endpoint.get('id'),
            'priority': endpoint.get('priority'),
            'name': endpoint.get('name'),
            'current_status': endpoint.get('current_status'),
            'reason': _endpoint_action_reason(endpoint),
            'internal_path': endpoint.get('internal_path'),
            'mcp_tool': endpoint.get('mcp_tool'),
        })
    rows.sort(key=lambda row: (priority_order.get(str(row.get('priority')), 9), str(row.get('id'))))
    return rows[:6]


def _endpoint_action_reason(endpoint: dict[str, Any]) -> str:
    missing = [
        str(item.get('label') or item.get('id'))
        for item in endpoint.get('requirements') or []
        if str(item.get('status') or '').lower() in {'missing', 'partial', 'unknown'}
    ]
    if not missing:
        return 'Endpoint contract is ready; attach live adapter only if it improves freshness.'
    return 'Needs fresh deterministic source coverage: ' + ', '.join(missing)


def _resource_view(item: dict[str, Any]) -> dict[str, Any]:
    view = dict(item)
    view['recommended_for_alpha'] = float(item['alpha_value_score']) >= 70 and item['adoption_phase'] != 'defer'
    view['read_only_required'] = True
    return view


def _searchable_text(scanner_run: dict[str, Any] | None, workflow: dict[str, Any] | None) -> str:
    selected = {
        'scanner_run': _compact(scanner_run, depth=3),
        'workflow': _compact(workflow, depth=3),
    }
    try:
        return json.dumps(selected, ensure_ascii=False, sort_keys=True).lower()
    except TypeError:
        return str(selected).lower()


def _compact(value: Any, *, depth: int) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if depth <= 0:
        return None
    if isinstance(value, dict):
        keep: dict[str, Any] = {}
        for key, item in value.items():
            if key in {
                'id',
                'source',
                'mode',
                'providers',
                'freshness',
                'source_files',
                'analysis_artifacts',
                'goal_harness',
                'performance_advisory',
                'candidates',
                'summary',
                'top3',
                'outcome_status',
                'outcome_summary',
                'graphrag',
                'source_freshness',
                'analysis_runs',
                'data_context',
                'file',
                'exists',
                'generated_at',
                'modified_at',
                'freshness',
                'role',
                'required',
                'alert_required',
                'evidence',
                'source',
                'field',
                'value',
                'confidence',
                'data_sources',
                'replay_context',
                'analysis_profile',
            }:
                keep[str(key)] = _compact(item, depth=depth - 1)
        return keep
    if isinstance(value, list):
        return [_compact(item, depth=depth - 1) for item in value[:8]]
    return str(value)


def _matching_patterns(text: str, patterns: list[str] | tuple[str, ...]) -> list[str]:
    if not text:
        return []
    hits = []
    for pattern in patterns or []:
        clean = str(pattern or '').strip().lower()
        if clean and clean in text:
            hits.append(clean)
    return hits


def _gap_summary(readiness: str, covered: int, partial: int, missing: int) -> str:
    if readiness == 'unknown':
        return 'No scanner/workflow artifact was available for source-gap evaluation.'
    if readiness == 'ready':
        return f'All required evidence roles are covered ({covered} covered).'
    if readiness == 'limited':
        return f'Required evidence is usable but limited ({covered} covered, {partial} partial).'
    return f'Required evidence gaps block high-confidence Top 3 notification ({missing} missing, {partial} partial).'


def _latest_scanner_run() -> dict[str, Any] | None:
    try:
        from app.services.mirofish import alpha_scanner

        return alpha_scanner.read_latest_scanner_run()
    except Exception:
        return None


def _latest_workflow() -> dict[str, Any] | None:
    try:
        from app.services.mirofish import workflow

        return workflow.read_latest_workflow()
    except Exception:
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
