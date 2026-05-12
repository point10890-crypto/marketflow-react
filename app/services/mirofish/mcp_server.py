"""FastMCP adapter for the MiroFish autonomous control-plane."""

from __future__ import annotations

import json
import os
from typing import Any

import app.services.mirofish.alpha_scanner as alpha_scanner
import app.services.mirofish.autonomous_mcp as autonomous_mcp
import app.services.mirofish.workflow as workflow

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    FastMCP = None  # type: ignore[assignment]


def create_mcp_server(
    *,
    host: str | None = None,
    port: int | None = None,
    streamable_http_path: str | None = None,
) -> Any:
    """Create a FastMCP server exposing MiroFish autonomous tools."""
    if FastMCP is None:
        raise RuntimeError('mcp package is not installed. Install requirements.txt first.')
    clean_host = host or os.getenv('MIROFISH_MCP_HOST', '127.0.0.1')
    clean_port = int(port or os.getenv('MIROFISH_MCP_PORT', '8765'))
    clean_path = streamable_http_path or os.getenv('MIROFISH_MCP_PATH', '/mcp')

    mcp = FastMCP(
        'MarketFlow MiroFish Autonomous MCP',
        host=clean_host,
        port=clean_port,
        streamable_http_path=clean_path,
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    def get_autonomous_status() -> dict[str, Any]:
        """Return redacted scanner/workflow/learning/Telegram MCP status."""
        return autonomous_mcp.get_autonomous_status()

    @mcp.tool()
    def get_mcp_security_policy() -> dict[str, Any]:
        """Return the redacted MCP security policy and allowlist."""
        return autonomous_mcp.get_mcp_security_policy()

    @mcp.tool()
    def get_market_clock() -> dict[str, Any]:
        """Return KST market-session and scanner schedule status."""
        return autonomous_mcp.get_market_clock()

    @mcp.tool()
    def get_repository_state() -> dict[str, Any]:
        """Return a read-only git branch/head/dirty summary."""
        return autonomous_mcp.get_repository_state()

    @mcp.tool()
    def list_recent_scanner_runs(limit: int = 20) -> dict[str, Any]:
        """List recent deterministic alpha scanner runs."""
        return autonomous_mcp.list_recent_scanner_runs(limit=limit)

    @mcp.tool()
    def list_recent_workflows(limit: int = 20) -> dict[str, Any]:
        """List recent scanner-to-analysis workflow runs."""
        return autonomous_mcp.list_recent_workflows(limit=limit)

    @mcp.tool()
    def list_safe_artifacts(kind: str = 'all', limit: int = 50) -> dict[str, Any]:
        """List small read-only MiroFish artifacts from the safe allowlist."""
        return autonomous_mcp.list_safe_artifacts(kind=kind, limit=limit)

    @mcp.tool()
    def read_safe_artifact(path: str) -> dict[str, Any]:
        """Read one allowlisted MiroFish artifact by relative path or resource link."""
        return autonomous_mcp.read_safe_artifact(path)

    @mcp.tool()
    def run_candidate_detection_alert(
        dry_run: bool = True,
        send_telegram: bool = False,
        confirmation: str = '',
        api_key: str = '',
        limit: int = 20,
        min_alpha: float = 70,
        max_risk: float = 45,
        max_events: int = 8,
        symbols: str = '',
        allow_stale_sources: bool = False,
        channel: bool = False,
        commit_state: bool = True,
    ) -> dict[str, Any]:
        """Detect new alpha candidates and optionally send Telegram alerts."""
        return autonomous_mcp.run_candidate_detection_alert({
            'dry_run': dry_run,
            'send_telegram': send_telegram,
            'confirmation': confirmation,
            'api_key': api_key,
            'limit': limit,
            'min_alpha': min_alpha,
            'max_risk': max_risk,
            'max_events': max_events,
            'symbols': symbols,
            'allow_stale_sources': allow_stale_sources,
            'channel': channel,
            'commit_state': commit_state,
        })

    @mcp.tool()
    def run_autonomous_scan_analysis(
        dry_run: bool = True,
        sync: bool = False,
        send_telegram: bool = False,
        confirmation: str = '',
        api_key: str = '',
        limit: int = 20,
        min_alpha: float = 50,
        max_risk: float = 65,
        max_events: int = 5,
        agent_count: int = 10,
        top_n: int = 3,
        max_parallel: int = 3,
        symbols: str = '',
        actions: str = '',
        mode: str = 'full',
        force: bool = False,
        allow_stale_sources: bool = False,
        channel: bool = False,
        commit_event_state: bool = True,
        refresh_learning: bool = True,
    ) -> dict[str, Any]:
        """Run scan -> GraphRAG analysis -> outcome learning -> optional Telegram."""
        return autonomous_mcp.run_autonomous_scan_analysis({
            'dry_run': dry_run,
            'sync': sync,
            'send_telegram': send_telegram,
            'confirmation': confirmation,
            'api_key': api_key,
            'limit': limit,
            'min_alpha': min_alpha,
            'max_risk': max_risk,
            'max_events': max_events,
            'agent_count': agent_count,
            'top_n': top_n,
            'max_parallel': max_parallel,
            'symbols': symbols,
            'actions': actions,
            'mode': mode,
            'force': force,
            'allow_stale_sources': allow_stale_sources,
            'channel': channel,
            'commit_event_state': commit_event_state,
            'refresh_learning': refresh_learning,
        })

    @mcp.tool()
    def refresh_learning_feedback(
        api_key: str = '',
        limit: int = 20,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Refresh look-ahead-safe outcome feedback without mutating live weights."""
        return autonomous_mcp.refresh_learning_feedback({
            'api_key': api_key,
            'limit': limit,
            'commit': commit,
        })

    @mcp.tool()
    def send_latest_workflow_telegram(
        confirmation: str,
        api_key: str = '',
        workflow_id: str = '',
        channel: bool = False,
        commit_event_state: bool = True,
    ) -> dict[str, Any]:
        """Send the latest or selected completed workflow Top-N message to Telegram."""
        return autonomous_mcp.send_latest_workflow_telegram({
            'confirmation': confirmation,
            'api_key': api_key,
            'workflow_id': workflow_id,
            'channel': channel,
            'commit_event_state': commit_event_state,
        })

    @mcp.tool()
    def get_workflow_share_payload(
        workflow_id: str = '',
        rank: int | None = None,
    ) -> dict[str, Any]:
        """KakaoTalk 공유용 풍부한 페이로드 (5인 페르소나 인용 + CIO reasoning).

        Args:
            workflow_id: 빈 문자열이면 최신 workflow 사용.
            rank: 1|2|3 단일 종목, None 이면 TOP 3 전체.

        Returns:
            {'title', 'description', 'image_url', 'link_url',
             'top_items', 'list_contents', 'kakao_buttons',
             'analyst_quote', 'cio_reasoning', 'cio_opposing'}
        """
        wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
        if wf is None:
            return {'error': 'workflow not found', 'workflow_id': workflow_id or 'latest'}
        try:
            payload = workflow.build_share_payload(wf, rank=rank)
            return payload
        except ValueError as exc:
            return {'error': str(exc)}

    @mcp.tool()
    def get_top3_summary(workflow_id: str = '') -> dict[str, Any]:
        """현재 또는 지정 workflow 의 TOP 3 핵심 요약 — Claude 가 즉시 응답 가능한 형태.

        AI 애널리스트 (5인 페르소나) 의 핵심 인용 + CIO reasoning + 검증 결과를 포함.
        Claude Desktop 에서 "이번 주 TOP 3 알려줘" 같은 자연어 질의에 답하기 위해 사용.

        Args:
            workflow_id: 빈 문자열이면 최신 workflow.

        Returns:
            {'workflow_id', 'completed_at', 'top_count', 'top_items': [{...}], 'one_liner'}
        """
        wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
        if wf is None:
            return {'error': 'workflow not found'}
        payload = workflow.build_share_payload(wf, rank=None)
        top_items = payload.get('top_items', [])
        one_liner = ' / '.join(
            f"#{it['rank']} {it['name']} {it['action']} {it['confidence_pct']}%"
            for it in top_items
        )
        return {
            'workflow_id': payload.get('workflow_id'),
            'completed_at': payload.get('completed_at'),
            'top_count': len(top_items),
            'top_items': top_items,
            'one_liner': one_liner,
            'description': payload.get('description'),
        }

    @mcp.resource('mirofish://workflows/share')
    def latest_share_resource() -> str:
        """최신 workflow 의 카카오톡 공유 페이로드 (5인 인용 + CIO 포함)."""
        wf = workflow.read_latest_workflow()
        if wf is None:
            return _json({'error': 'workflow not found'})
        try:
            return _json(workflow.build_share_payload(wf, rank=None))
        except Exception as exc:
            return _json({'error': str(exc)})

    @mcp.resource('mirofish://autonomous/status')
    def autonomous_status_resource() -> str:
        """Redacted autonomous MCP status."""
        return _json(autonomous_mcp.get_autonomous_status())

    @mcp.resource('mirofish://autonomous/security')
    def autonomous_security_resource() -> str:
        """Redacted autonomous MCP security policy."""
        return _json(autonomous_mcp.get_mcp_security_policy())

    @mcp.resource('mirofish://autonomous/learning')
    def autonomous_learning_resource() -> str:
        """Latest advisory learning feedback artifact."""
        return _json(autonomous_mcp.read_learning_feedback() or {'available': False})

    @mcp.resource('mirofish://market/clock')
    def market_clock_resource() -> str:
        """KST market-session and scanner schedule status."""
        return _json(autonomous_mcp.get_market_clock())

    @mcp.resource('mirofish://scanner/latest')
    def latest_scanner_resource() -> str:
        """Latest deterministic alpha scanner run."""
        return _json(alpha_scanner.read_latest_scanner_run() or {'error': 'scanner run not found'})

    @mcp.resource('mirofish://workflows/latest')
    def latest_workflow_resource() -> str:
        """Latest scanner-to-analysis workflow run."""
        return _json(workflow.read_latest_workflow() or {'error': 'workflow not found'})

    # =========================================================
    # 금융 분석 도구 (KIS/Kiwoom/DART/수급/차트/통합)
    # =========================================================

    @mcp.tool()
    def get_kiwoom_quote(symbol: str) -> dict[str, Any]:
        """단일 종목 실시간 시세 (키움 OpenAPI).

        Args:
            symbol: 종목 코드 (예: '005930' 삼성전자)
        Returns:
            현재가, 등락률, 거래량, 거래대금, 시고저가
        """
        try:
            from engine.kiwoom_client import get_stock_quote
            return get_stock_quote(symbol) or {'error': 'no quote', 'symbol': symbol}
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'symbol': symbol}

    @mcp.tool()
    def get_kiwoom_daily_chart(symbol: str) -> dict[str, Any]:
        """일봉 차트 데이터 (키움). 약 60일 OHLCV.

        Args:
            symbol: 종목 코드
        Returns:
            일별 OHLCV 배열 (분석/패턴 인식용)
        """
        try:
            from engine.kiwoom_client import get_daily_ohlcv
            return get_daily_ohlcv(symbol) or {'error': 'no chart', 'symbol': symbol}
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'symbol': symbol}

    @mcp.tool()
    def get_kiwoom_institution_trend(symbol: str, start_date: str = '', end_date: str = '') -> dict[str, Any]:
        """기관 매매 누적 추세 (키움).

        Args:
            symbol: 종목 코드
            start_date: YYYYMMDD (옵션, 기본 30일 전)
            end_date: YYYYMMDD (옵션, 기본 오늘)
        Returns:
            일별 외인/기관 순매수 누적
        """
        try:
            from engine.kiwoom_client import get_institution_trend
            return get_institution_trend(symbol, start_date, end_date) or {'error': 'no data', 'symbol': symbol}
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'symbol': symbol}

    @mcp.tool()
    def get_kiwoom_market_investors(market: str = '000', after_close: bool = False) -> dict[str, Any]:
        """시장 전체 투자자별 순매수 (키움).

        Args:
            market: '000'=전체, '001'=KOSPI, '101'=KOSDAQ
            after_close: True 면 장마감 후 확정치, False 면 장중 추정치
        Returns:
            외국인/기관/개인 순매수 (시장 전체)
        """
        try:
            from engine.kiwoom_client import get_investor_trading_market, get_investor_after_close
            if after_close:
                return get_investor_after_close(market, '3') or {'error': 'no data'}
            return get_investor_trading_market(market, '3') or {'error': 'no data'}
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    @mcp.tool()
    def get_dart_disclosures(symbol: str) -> dict[str, Any]:
        """DART 전자공시 (호재/악재 분류 포함, 캐시 우선).

        Args:
            symbol: 종목 코드
        Returns:
            최근 공시 리스트 + 호재공시 유무 + 분류
        """
        try:
            from engine.dart_deep_pipeline import get_cached_result
            cached = get_cached_result(symbol)
            if cached:
                return cached
            return {'symbol': symbol, 'disclosures': [], 'cached': False, 'note': 'no cache hit'}
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'symbol': symbol}

    @mcp.tool()
    def get_outcomes_kpi(days: int = 30) -> dict[str, Any]:
        """추천 종목 실적 KPI (forward outcomes 집계).

        Args:
            days: 윈도우 일수 (기본 30)
        Returns:
            hit_rate, avg_return, false_positive, 표본수, 종목별 outcome
        """
        try:
            from app.services.mirofish.pipeline_overview import get_outcomes_board
            return get_outcomes_board(days=days, limit=50)
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    @mcp.tool()
    def get_pipeline_today_snapshot() -> dict[str, Any]:
        """오늘 검출 파이프라인 + 시장 컨텍스트 종합 스냅샷.

        Returns:
            market(KR phase/gate/VIX/F&G) + funnel(scanner→batch→graphrag→top3)
            + 7d/30d KPI + 다음 자동 스캔 ETA
        """
        try:
            from app.services.mirofish.pipeline_overview import get_pipeline_today_snapshot as _snap
            return _snap()
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    @mcp.tool()
    def analyze_target_comprehensive(symbol: str) -> dict[str, Any]:
        """단일 종목 종합 분석 — 모든 데이터 소스 1-call 통합.

        시세 + 차트 + 외인/기관 수급 + DART 공시 + 기술적 분석(매수/목표/손절)
        을 한 번에 수집하여 LLM 분석용 컨텍스트 패키지로 반환.

        Args:
            symbol: 종목 코드 (예: '005930')
        Returns:
            {quote, chart, institution_trend, disclosures, technical_levels}
        """
        result: dict[str, Any] = {'symbol': symbol}
        # 1) 시세
        try:
            from engine.kiwoom_client import get_stock_quote
            result['quote'] = get_stock_quote(symbol) or {}
        except Exception as exc:
            result['quote'] = {'error': f'{type(exc).__name__}: {exc}'}
        # 2) 차트
        try:
            from engine.kiwoom_client import get_daily_ohlcv
            result['chart'] = get_daily_ohlcv(symbol) or {}
        except Exception as exc:
            result['chart'] = {'error': f'{type(exc).__name__}: {exc}'}
        # 3) 기관 수급
        try:
            from engine.kiwoom_client import get_institution_trend
            result['institution_trend'] = get_institution_trend(symbol, '', '') or {}
        except Exception as exc:
            result['institution_trend'] = {'error': f'{type(exc).__name__}: {exc}'}
        # 4) DART 공시
        try:
            from engine.dart_deep_pipeline import get_cached_result
            result['disclosures'] = get_cached_result(symbol) or {'cached': False}
        except Exception as exc:
            result['disclosures'] = {'error': f'{type(exc).__name__}: {exc}'}
        # 5) 기술적 분석 (SMA + ATR + 진입/목표/손절)
        try:
            from app.services.mirofish.technical_analysis import analyze_target_with_levels
            result['technical_levels'] = analyze_target_with_levels(target=symbol)
        except Exception as exc:
            result['technical_levels'] = {'error': f'{type(exc).__name__}: {exc}'}
        # 6) 메타
        from datetime import datetime as _dt, timezone as _tz
        result['generated_at'] = _dt.now(_tz.utc).isoformat()
        return result

    @mcp.tool()
    def get_alpha_scanner_diagnostics() -> dict[str, Any]:
        """알파 스캐너 진단 (데이터 신선도/소스 시그니처/이슈 리스트)."""
        try:
            return alpha_scanner.get_scanner_diagnostics()
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    @mcp.tool()
    def get_auto_runner_status() -> dict[str, Any]:
        """Stage 2 자동 실행기 상태 (phase/cooldown/today 카운터/recent cycles)."""
        try:
            from app.services.mirofish import auto_runner
            return auto_runner.get_status()
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    # =========================================================
    # 외부 데이터 소스 & 종목 검색 (Phase 3 확장)
    # =========================================================

    @mcp.tool()
    def search_news_perplexity(query: str, max_results: int = 5) -> dict[str, Any]:
        """Perplexity 실시간 뉴스 검색 (한국어 우선).

        Args:
            query: 검색어 (예: '현대무벡스 호재', 'KOSPI 외국인')
            max_results: 인용 최대 개수 (기본 5)
        Returns:
            {answer, citations[], usage} 또는 {error}
        """
        import os
        import requests as _requests
        api_key = os.getenv('PERPLEXITY_API_KEY')
        if not api_key:
            return {'error': 'PERPLEXITY_API_KEY missing'}
        try:
            resp = _requests.post(
                'https://api.perplexity.ai/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': os.getenv('PERPLEXITY_MODEL', 'sonar'),
                    'messages': [
                        {'role': 'system', 'content': '한국어로 간결히 2-3 문장 + 출처 link 제공.'},
                        {'role': 'user', 'content': query},
                    ],
                    'max_tokens': 600,
                    'return_citations': True,
                },
                timeout=25,
            )
            if resp.status_code != 200:
                return {'error': f'HTTP {resp.status_code}: {resp.text[:200]}'}
            data = resp.json()
            choice = (data.get('choices') or [{}])[0]
            citations = data.get('citations') or choice.get('citations') or []
            return {
                'answer': (choice.get('message') or {}).get('content', ''),
                'citations': citations[:max_results],
                'model': data.get('model'),
                'usage': data.get('usage', {}),
            }
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    @mcp.tool()
    def scrape_naver_finance(symbol: str) -> dict[str, Any]:
        """네이버 금융 종목 페이지 핵심 메타 (시총/PER/EPS/외국인비율/52주).

        Args:
            symbol: 종목 코드 (예: '005930')
        Returns:
            {symbol, name, price, change_pct, market_cap, per, eps, foreign_ratio, week52_high, week52_low}
        """
        import re
        import requests as _requests
        try:
            url = f'https://finance.naver.com/item/main.naver?code={symbol}'
            r = _requests.get(url, headers={'User-Agent': 'Mozilla/5.0 MiroFish/1.0'}, timeout=10)
            if r.status_code != 200:
                return {'error': f'HTTP {r.status_code}', 'symbol': symbol}
            html = r.text
            def find(pattern: str, default: str = '') -> str:
                m = re.search(pattern, html)
                return (m.group(1).strip() if m else default)
            # 핵심 메트릭 정규식 추출 (네이버 마크업 안정적)
            name = find(r'<dt class="line_b">([^<]+?)</dt>', '')
            if not name:
                name = find(r'<title>([^<]+?)</title>', '').replace(' - 네이버 증권', '').replace(' : 네이버 증권', '').strip()
            price = find(r'<span class="blind">현재가</span>[\s\S]*?<span class="blind">(\d[\d,]*)</span>', '')
            change_pct = find(r'<em[^>]*class="no_exday[^"]*">[\s\S]*?<span class="blind">([+-]?\d[\d\.,]*)%?</span>', '')
            market_cap = find(r'시가총액[^<]*</span>[\s\S]*?<em[^>]*>([^<]+)</em>', '')
            per = find(r'<em id="_per">([^<]+)</em>', '')
            eps = find(r'<em id="_eps">([^<]+)</em>', '')
            foreign_ratio = find(r'외국인소진율[\s\S]*?<em[^>]*>([0-9\.]+)</em>', '')
            week_52_high = find(r'52주최고[^<]*</th>[\s\S]*?<em[^>]*>([0-9,]+)</em>', '')
            week_52_low = find(r'52주최저[^<]*</th>[\s\S]*?<em[^>]*>([0-9,]+)</em>', '')
            return {
                'symbol': symbol,
                'name': name,
                'price': price,
                'change_pct': change_pct,
                'market_cap': market_cap,
                'per': per,
                'eps': eps,
                'foreign_ratio': foreign_ratio,
                'week52_high': week_52_high,
                'week52_low': week_52_low,
                'source_url': url,
            }
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'symbol': symbol}

    @mcp.tool()
    def get_backtest_summary() -> dict[str, Any]:
        """저장된 백테스트 결과 CSV 요약 (종가베팅 V2 등 누적 결과).

        Returns:
            {files: [{name, rows, columns, head, summary}, ...]}
        """
        import csv
        import glob
        import os
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        data_root = os.path.join(repo_root, 'data')
        candidates = []
        for path in glob.glob(os.path.join(data_root, '*backtest*.csv')):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    rows = list(csv.reader(fh))
                if not rows:
                    continue
                header = rows[0]
                body = rows[1:]
                candidates.append({
                    'name': os.path.basename(path),
                    'rows': len(body),
                    'columns': header[:10],
                    'head': body[:3],
                })
            except Exception as exc:
                candidates.append({
                    'name': os.path.basename(path),
                    'error': f'{type(exc).__name__}: {exc}',
                })
        return {'files': candidates, 'data_root': data_root}

    @mcp.tool()
    def resolve_target(query: str) -> dict[str, Any]:
        """한글 종목명 / 종목코드 → 정규화된 메타 (data sources + KIS 상태 포함).

        Args:
            query: '삼성전자', '005930', 'NVDA' 등
        Returns:
            target_snapshot (resolved + source_files + signal_count + kis 상태)
        """
        try:
            from app.services.mirofish.store import resolve_target_snapshot
            return resolve_target_snapshot(query)
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'query': query}

    @mcp.tool()
    def search_targets(query: str, limit: int = 16) -> dict[str, Any]:
        """종목명/코드 부분 검색 → 후보 목록 (autocomplete 용).

        Args:
            query: 검색 키워드
            limit: 최대 후보 수 (기본 16)
        """
        try:
            from app.services.mirofish.store import search_target_candidates
            return search_target_candidates(query, limit=limit)
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}', 'query': query}

    return mcp


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
