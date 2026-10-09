// 선택 후보의 뉴스 시각 대조와 선택적 자료의 공개 경계를 검증한다.
import { act, cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { validateAlphaLabStatus } from '@/lib/alphaLabApi';
import CatalystContext from '@/components/aibain/CatalystContext';
import { validateCatalystContext } from '@/lib/catalystContext';
import { validateOpportunityEngine } from '@/lib/opportunityEngine';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
const now = Date.parse('2026-10-09T04:00:00Z');
const identity = { decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64), source_audit_hash: 'c'.repeat(64) };
const decisionAt = '2026-10-07T09:46:00Z';
function boardFixture() {
    return { schema_version: 1, policy_version: 'profit-opportunity-v1', ...identity, generated_at: decisionAt,
        latest_session: '2026-10-07', entry_session: '2026-10-08', valid_until: '2026-10-08T06:30:00Z', status: 'held', research_only: true, live_orders: false,
        coverage: { inspected: 100, eligible: 7, selected: 1 }, alternatives: [], stages: [], reasons: [],
        candidates: [{ ...identity, opportunity_id: 'd'.repeat(64), symbol: '000660', name: 'SK하이닉스', market: 'KR', strategy_id: 'mean_reversion', rank: 1,
            action: 'data_check', label: '가격 확인 대기', why_stock: '저장 가격 조건으로 선정했습니다.', why_now: '현재 가격 확인 대기', next_action: '가격 조건을 다시 확인하세요.',
            quote_session: '2026-10-07', source_at: '2026-10-07T09:00:00Z', current_price: null, quote_at: null, fetched_at: null, quote_source: null,
            valid_until: '2026-10-08T06:30:00Z', reference_weight: .04,
            plan: { basis: 'last_closed_price_reference', entry_low: 60000, entry_high: 61200, stop_price: 57000, target_price: 66000, horizon_sessions: 10 },
            ranking: { stress_mean_net_return: .03, standard_error: .005, conservative_score: .0202, correlation_penalty: 0, score: .0202, calibration_samples: 40, confirmation_samples: 20 },
            kelly: { raw_fraction: .16, fraction: .25, cap: .05, account_risk_cap: .01 }, audit: { status: 'passed', reasons: [], independent_validation: false }, reasons: [] }],
    };
}
function contextFixture() {
    const event = { event_id: 'e'.repeat(64), event_group: 'f'.repeat(64), title: 'SK하이닉스 저평가 분석', url: 'https://www.yna.co.kr/view/valuation', source: '경제신문', grade: 'B',
        published_at: '2026-10-07T00:00:00Z', collected_at: '2026-10-07T00:10:00Z', stage: 'valuation_opinion', polarity: 'supportive', timing: 'captured_before_first' };
    return { schema_version: 1, policy_version: 'alpha-catalyst-context-v1', ...identity, decision_at: decisionAt, captured_at: '2026-10-09T03:00:00Z', snapshot_id: '1'.repeat(64),
        status: 'ready', used_in_selection: false, association_status: 'unproven',
        rows: [{ symbol: '000660', name: 'SK하이닉스', first_detected_at: decisionAt, first_decision_id: identity.decision_id, events: [event,
            { ...event, event_id: '2'.repeat(64), event_group: '3'.repeat(64), title: 'SK하이닉스 이전 공개 기사 확인', url: 'https://www.yna.co.kr/view/later-capture', collected_at: '2026-10-08T00:10:00Z', timing: 'published_before_captured_after' },
            { ...event, event_id: '4'.repeat(64), event_group: '5'.repeat(64), title: 'SK하이닉스 투자 확정 보도', url: 'https://www.yna.co.kr/view/investment', published_at: '2026-10-08T01:00:00Z', collected_at: '2026-10-08T01:10:00Z', stage: 'investment', timing: 'reported_after_first' },
        ] }], validation: { status: 'collecting', hypothesis: 'price_setup_leads_catalyst_72h_v1', horizon_hours: 72,
            started_at: '2026-10-09T00:00:00Z', enrolled_decisions: 0, matured_decisions: 0, coincidence_rejected: false } };
}
function statusFixture(catalyst_context: unknown = contextFixture()) {
    return { schema_version: 1, state: 'ready', generated_at: decisionAt, error: null, opportunity_engine: boardFixture(), catalyst_context,
        report: { schema_version: 1, mode: 'research', as_of: decisionAt, input_fingerprint: identity.input_fingerprint, latest_session: '2026-10-07',
            universe: { ranked_count: 100, quality_count: 100, inspected_count: 100, scope_date: '2026-10-07' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
                point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [], forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 10, source_references: [] } },
    };
}
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now); api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('optional catalyst status boundary', () => {
    it('drops an invalid optional source without hiding the selected stock or mutating its payload', () => {
        const raw = statusFixture({ private_path: 'C:\\private\\.env' });
        const original = structuredClone(raw);
        const result = validateAlphaLabStatus(raw);
        expect(result).not.toHaveProperty('catalyst_context');
        expect(result.opportunity_engine?.candidates[0].symbol).toBe('000660');
        expect(raw).toEqual(original);
    });
    it('renders separate publication and actual capture clocks with an original public link', async () => {
        api.fetchAuthAPI.mockResolvedValue(statusFixture());
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '가격 신호와 뉴스 동행' });
        expect(region).toHaveTextContent('원래 선정은 가격 기준; 뉴스는 별도 대조');
        expect(region).toHaveTextContent('최초 판단'); expect(region).toHaveTextContent('2026-10-07 18:46:00 KST');
        expect(region).toHaveTextContent('사전 수집'); expect(region).toHaveTextContent('사전 공개·사후 수집'); expect(region).toHaveTextContent('선정 후 보도');
        expect(region).toHaveTextContent('B등급 · 일반 뉴스');
        const link = within(region).getByRole('link', { name: /SK하이닉스 저평가 분석/ });
        expect(link).toHaveAttribute('href', 'https://www.yna.co.kr/view/valuation'); expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        expect(region).toHaveTextContent('발행 2026-10-07 09:00:00 KST'); expect(region).toHaveTextContent('실제 수집 2026-10-07 09:10:00 KST');
        expect(region).toHaveTextContent('72시간'); expect(region).toHaveTextContent('미산출');
        expect(within(region).queryByText(/\d+(?:\.\d+)?%/)).not.toBeInTheDocument();
        expect(screen.getByRole('article', { name: /1위.*SK하이닉스/ })).toBeInTheDocument();
    });
    it('accepts immutable validated evidence and omits legacy context absence', () => {
        const raw = statusFixture(); const original = structuredClone(raw);
        const result = validateAlphaLabStatus(raw);
        expect(result.catalyst_context?.rows[0].events).toHaveLength(3);
        expect(result.opportunity_engine?.candidates[0].reference_weight).toBe(.04);
        expect(raw).toEqual(original);
        Reflect.deleteProperty(raw, 'catalyst_context');
        expect(validateAlphaLabStatus(raw)).not.toHaveProperty('catalyst_context');
        expect(validateCatalystContext(contextFixture(), undefined, now)).toBeUndefined();
    });
    it.each([
        ['foreign decision', (v: any) => { v.decision_id = 'f'.repeat(64); }],
        ['foreign input', (v: any) => { v.input_fingerprint = 'f'.repeat(64); }],
        ['foreign audit', (v: any) => { v.source_audit_hash = 'f'.repeat(64); }],
        ['foreign decision time', (v: any) => { v.decision_at = '2026-10-07T09:47:00Z'; }],
        ['microsecond decision mismatch', (v: any) => { v.decision_at = '2026-10-07T09:46:00.000001Z'; }],
        ['foreign symbol', (v: any) => { v.rows[0].symbol = '005930'; }],
        ['foreign name', (v: any) => { v.rows[0].name = '삼성전자'; }],
        ['missing selected row', (v: any) => { v.rows = []; }],
        ['extra selected row', (v: any) => { v.rows.push(structuredClone(v.rows[0])); }],
        ['too many events', (v: any) => { v.rows[0].events = Array(9).fill(v.rows[0].events[0]); }],
        ['duplicate event', (v: any) => { v.rows[0].events.push(structuredClone(v.rows[0].events[0])); }],
        ['duplicate URL', (v: any) => { v.rows[0].events[1].url = v.rows[0].events[0].url; }],
        ['source captured in future', (v: any) => { v.captured_at = '2026-10-09T04:00:01Z'; }],
        ['source captured a microsecond in future', (v: any) => { v.captured_at = '2026-10-09T04:00:00.000001Z'; }],
        ['source captured before decision', (v: any) => { v.captured_at = '2026-10-07T09:00:00Z'; }],
        ['first detection after decision', (v: any) => { v.rows[0].first_detected_at = '2026-10-07T09:47:00Z'; }],
        ['publication after capture', (v: any) => { v.rows[0].events[0].published_at = '2026-10-07T00:11:00Z'; }],
        ['capture after snapshot', (v: any) => { v.rows[0].events[2].collected_at = '2026-10-09T03:01:00Z'; }],
        ['missing timezone', (v: any) => { v.rows[0].events[0].published_at = '2026-10-07T00:00:00'; }],
        ['impossible calendar date', (v: any) => { v.rows[0].events[0].published_at = '2026-02-30T00:00:00Z'; }],
        ['invalid timezone offset', (v: any) => { v.rows[0].events[0].published_at = '2026-10-07T00:00:00+14:01'; }],
        ['fake pre-capture badge', (v: any) => { v.rows[0].events[1].timing = 'captured_before_first'; }],
        ['capture badge off by a microsecond', (v: any) => { v.rows[0].events[0].collected_at = '2026-10-07T09:46:00.000001Z'; }],
        ['fake post-selection badge', (v: any) => { v.rows[0].events[0].timing = 'reported_after_first'; }],
        ['fake late-capture badge', (v: any) => { v.rows[0].events[2].timing = 'published_before_captured_after'; }],
        ['unknown timing', (v: any) => { v.rows[0].events[0].timing = 'anticipated'; }],
        ['unknown stage', (v: any) => { v.rows[0].events[0].stage = 'guaranteed_investment'; }],
        ['unknown polarity', (v: any) => { v.rows[0].events[0].polarity = 'buy'; }],
        ['invented source grade', (v: any) => { v.rows[0].events[0].grade = 'A'; }],
        ['overlong title', (v: any) => { v.rows[0].events[0].title = '제'.repeat(261); }],
        ['overlong source', (v: any) => { v.rows[0].events[0].source = '출'.repeat(65); }],
        ['internal text', (v: any) => { v.rows[0].events[0].title = 'C:\\Users\\hidden'; }],
        ['embedded drive path', (v: any) => { v.rows[0].events[0].title = '/C:/internal'; }],
        ['private UNIX path', (v: any) => { v.rows[0].events[0].source = '/srv/internal'; }],
        ['secret text', (v: any) => { v.rows[0].events[0].title = 'api_key hidden'; }],
        ['compound secret key', (v: any) => { v.rows[0].events[0].title = 'client_secret=hidden'; }],
        ['private UNC path', (v: any) => { v.rows[0].events[0].source = '\\\\server\\private'; }],
        ['HTML title', (v: any) => { v.rows[0].events[0].title = '<img src=x onerror=alert(1)>'; }],
        ['incomplete HTML title', (v: any) => { v.rows[0].events[0].title = '<script src=malicious'; }],
        ['unknown internal field', (v: any) => { v.rows[0].events[0].debug = 'trace'; }],
        ['used in selection claim', (v: any) => { v.used_in_selection = true; }],
        ['association proof claim', (v: any) => { v.association_status = 'proven'; }],
        ['invented probability', (v: any) => { v.validation.probability = .8; }],
        ['false mature count', (v: any) => { v.validation.matured_decisions = 1; }],
        ['false coincidence result', (v: any) => { v.validation.coincidence_rejected = true; }],
        ['wrong horizon', (v: any) => { v.validation.horizon_hours = 24; }],
        ['validation starts after snapshot', (v: any) => { v.validation.started_at = '2026-10-09T03:00:01Z'; }],
        ['negative enrollment', (v: any) => { v.validation.enrolled_decisions = -1; }],
        ['unbounded enrollment', (v: any) => { v.validation.enrolled_decisions = 1000001; }],
    ])('drops %s without invalidating the price board', (_, mutate) => {
        const context = contextFixture(); mutate(context);
        const result = validateAlphaLabStatus(statusFixture(context));
        expect(result).not.toHaveProperty('catalyst_context');
        expect(result.opportunity_engine?.candidates[0].symbol).toBe('000660');
    });
    it.each([
        'http://www.example.com/news', 'javascript:alert(1)', 'data:text/html,<script>alert(1)</script>',
        'https://localhost/news', 'https://127.0.0.1/news', 'https://192.168.1.1/news', 'https://[::1]/news',
        'https://news.internal/news', 'https://user:pass@www.yna.co.kr/news', 'https://www.yna.co.kr:5001/news',
        'https://www.yna.co.kr/private/document', 'https://www.yna.co.kr/%2eenv',
        'https://www.yna.co.kr/news?access_token=hidden', 'https://www.yna.co.kr/%3Cscript%3E',
        'https://www.yna.co.kr/%250a', 'https://www.yna.co.kr/' + 'a'.repeat(2000),
        'https://www.example.com/news', 'https://www.yna.co.kr:80/view/news', 'http://www.yna.co.kr:443/view/news',
    ])('rejects unsafe original link %s before rendering it', url => {
        const value = contextFixture(); value.rows[0].events[0].url = url;
        render(<CatalystContext context={value} board={validateOpportunityEngine(boardFixture())} now={now} />);
        expect(screen.queryByRole('region', { name: '가격 신호와 뉴스 동행' })).not.toBeInTheDocument();
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
    });
    it('accepts timezone-qualified real timestamps and historical first decision records', () => {
        const value = contextFixture();
        value.rows[0].first_detected_at = '2026-10-06T18:46:00+09:00'; value.rows[0].first_decision_id = '9'.repeat(64);
        value.rows[0].events = [{ ...value.rows[0].events[0], published_at: '2026-10-06T09:00:00+09:00', collected_at: '2026-10-06T09:10:00+09:00' }];
        expect(validateCatalystContext(value, validateOpportunityEngine(boardFixture()), now)?.rows[0].events).toHaveLength(1);
    });
    it('accepts a distinct verified first record at the same clock when simultaneous scans tie', () => {
        const value = contextFixture(); value.rows[0].first_decision_id = '9'.repeat(64);
        expect(validateCatalystContext(value, validateOpportunityEngine(boardFixture()), now)?.rows[0].first_decision_id).toBe('9'.repeat(64));
    });
    it('preserves six-digit journal precision when the same decision clock uses a different timezone', () => {
        const board = boardFixture(); board.generated_at = '2026-10-07T09:46:02.535860Z';
        const value = contextFixture(); value.decision_at = '2026-10-07T18:46:02.535860+09:00'; value.rows[0].first_detected_at = board.generated_at;
        expect(validateCatalystContext(value, validateOpportunityEngine(board), now)?.rows[0].first_detected_at).toBe('2026-10-07T09:46:02.535860Z');
    });
    it.each(['http://www.yna.co.kr/view/AKR20261007027000008', 'https://view.asiae.co.kr/article/2026100715012973574',
        'https://www.hankyung.com:443/article/202610089746i', 'http://www.mk.co.kr:80/news/stock/1', 'https://news.mt.co.kr/news/view/1', 'https://yna.kr/1'])('keeps original known-source URL %s', url => {
        const value = contextFixture(); value.rows[0].events[0].url = url;
        expect(validateCatalystContext(value, validateOpportunityEngine(boardFixture()), now)?.rows[0].events[0].url).toBe(url);
    });
    it('requires selected row order and renders all selected symbols when news is absent', () => {
        const board = boardFixture(); const value = contextFixture();
        board.candidates.push({ ...board.candidates[0], symbol: '005930', name: '삼성전자', rank: 2, opportunity_id: '8'.repeat(64) }); board.coverage.selected = 2;
        value.rows.push({ ...value.rows[0], symbol: '005930', name: '삼성전자', events: [] });
        const validatedBoard = validateOpportunityEngine(board);
        render(<CatalystContext context={value} board={validatedBoard} now={now} />);
        expect(screen.getByRole('article', { name: '삼성전자 005930 뉴스 시각 대조' })).toHaveTextContent('뉴스 자료가 없습니다');
        value.rows.reverse();
        expect(validateCatalystContext(value, validatedBoard, now)).toBeUndefined();
    });
    it('labels heuristic topic-date groups without claiming identical events or independent catalysts', () => {
        const value = contextFixture(); value.rows[0].events[1].event_group = value.rows[0].events[0].event_group;
        render(<CatalystContext context={value} board={validateOpportunityEngine(boardFixture())} now={now} />);
        const repeated = screen.getByRole('list', { name: '같은 주제·날짜의 보도 묶음' });
        expect(within(repeated).getAllByRole('link')).toHaveLength(2);
        expect(repeated.parentElement).toHaveTextContent('같은 주제·날짜의 보도 묶음 · 2건');
        expect(repeated.parentElement).toHaveTextContent('실제 동일 사건·전재 여부는 미확인');
        expect(screen.queryByText(/독립 호재.*2건/)).not.toBeInTheDocument();
    });
    it('retains the visible board when context is absent or unsafe on refresh', async () => {
        const context = contextFixture(); context.rows[0].events[0].url = 'javascript:alert(1)';
        const value = statusFixture(context);
        api.fetchAuthAPI.mockResolvedValue(value); render(<AlphaLabPanel desk />); await act(async () => {});
        expect(screen.getByRole('article', { name: /1위.*SK하이닉스/ })).toBeInTheDocument();
        expect(screen.queryByRole('region', { name: '가격 신호와 뉴스 동행' })).not.toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
});
