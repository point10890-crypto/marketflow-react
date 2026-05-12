/**
 * MiroFish 자연어 채팅 패널 — inline (검색폼 아래) 또는 floating FAB.
 *
 * 사용:
 *   <MirofishChatPanel />                    // floating FAB
 *   <MirofishChatPanel variant="inline" />   // 항상 펼침
 *
 * - 백엔드 /api/admin/mirofish/chat 호출 (Gemini function calling)
 * - 안전한 read-only MCP 도구 자동 호출
 * - 히스토리 최근 10턴 유지
 * - Anthropic warm dark + orange 액센트
 */
import { useEffect, useRef, useState } from 'react';
import { MiroFishChatToolCall, mirofishApi } from '@/lib/mirofishApi';

export type MirofishChatVariant = 'floating' | 'inline';

interface MirofishChatPanelProps {
    variant?: MirofishChatVariant;
    defaultOpen?: boolean;
}

interface ChatMessage {
    role: 'user' | 'assistant';
    content: string;
    tool_calls?: MiroFishChatToolCall[];
    timestamp: string;
}

const SUGGESTIONS = [
    '삼성전자 매수가 목표가 손절가 알려줘',
    '이번 TOP 3 알려줘',
    'SK하이닉스 추세 분석',
    '지금 한국 장 열려 있어?',
    '카카오 매수 진입가 분석',
    'TOP 1 카톡 공유 정보 줘',
];

const STORAGE_KEY = 'mirofish_chat_history_v1';

function loadHistory(): ChatMessage[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed.slice(-20) : [];
    } catch {
        return [];
    }
}

function saveHistory(messages: ChatMessage[]) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-20)));
    } catch {
        /* quota or disabled */
    }
}

export default function MirofishChatPanel({
    variant = 'floating',
    defaultOpen = false,
}: MirofishChatPanelProps = {}) {
    const inline = variant === 'inline';
    const [open, setOpen] = useState(inline ? true : defaultOpen);
    const [messages, setMessages] = useState<ChatMessage[]>(() => loadHistory());
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const composingRef = useRef(false);

    useEffect(() => {
        saveHistory(messages);
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, open]);

    async function send(textOverride?: string) {
        const text = (textOverride ?? input).trim();
        if (!text || busy) return;
        setError(null);
        setInput('');
        const now = new Date().toISOString();
        const userMsg: ChatMessage = { role: 'user', content: text, timestamp: now };
        const nextMessages = [...messages, userMsg];
        setMessages(nextMessages);
        setBusy(true);
        try {
            const history = nextMessages
                .filter((m) => m.role === 'user' || m.role === 'assistant')
                .map((m) => ({ role: m.role, content: m.content }))
                .slice(-10);
            const resp = await mirofishApi.chat(text, history.slice(0, -1));
            const assistantMsg: ChatMessage = {
                role: 'assistant',
                content: resp.reply || '(응답 비어 있음)',
                tool_calls: resp.tool_calls,
                timestamp: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, assistantMsg]);
        } catch (err) {
            console.error('[chat] failed', err);
            const msg = err instanceof Error ? err.message : 'AI 호출 실패';
            setError(msg);
            setMessages((prev) => [
                ...prev,
                {
                    role: 'assistant',
                    content: `요청 처리 중 오류가 발생했습니다: ${msg}`,
                    timestamp: new Date().toISOString(),
                },
            ]);
        } finally {
            setBusy(false);
        }
    }

    function clearHistory() {
        if (!confirm('대화 기록을 모두 지웁니다. 계속하시겠어요?')) return;
        setMessages([]);
        saveHistory([]);
    }

    // 공통 헤더 (Clear + 닫기 버튼, inline 시 닫기 숨김)
    const HeaderBlock = (
        <header className="flex items-center justify-between border-b border-anthropic-darkLine px-4 py-3">
            <div className="flex items-center gap-2">
                <span className="inline-flex h-2 w-2 rounded-full bg-anthropic-orange animate-pulse" />
                <span className="font-serif text-sm font-medium text-anthropic-cream">MiroFish 어시스턴트</span>
                <span className="text-[10px] uppercase tracking-wider text-anthropic-darkMuted">read-only</span>
            </div>
            <div className="flex items-center gap-1">
                <button
                    type="button"
                    onClick={clearHistory}
                    className="rounded-md px-2 py-1 text-[11px] text-anthropic-darkMuted hover:bg-anthropic-dark2 hover:text-anthropic-cream"
                    title="대화 기록 지우기"
                >
                    Clear
                </button>
                {!inline && (
                    <button
                        type="button"
                        onClick={() => setOpen(false)}
                        className="rounded-md p-1 text-anthropic-darkMuted hover:bg-anthropic-dark2 hover:text-anthropic-cream"
                        aria-label="닫기"
                    >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                )}
            </div>
        </header>
    );

    // inline 모드 — 별도 section, 명확한 orange 보더 + 헤로 라벨
    if (inline) {
        return (
            <section className="rounded-xl border-2 border-anthropic-orange/40 bg-anthropic-dark shadow-xl shadow-anthropic-orange/[0.06]">
                {/* 강조 헤더 — 사용자가 즉시 인식하도록 */}
                <div className="flex items-center justify-between border-b border-anthropic-darkLine bg-gradient-to-r from-anthropic-orange/[0.15] to-transparent px-5 py-3">
                    <div className="flex items-center gap-3">
                        <div className="grid h-10 w-10 place-items-center rounded-lg bg-anthropic-orange text-white shadow-lg">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                            </svg>
                        </div>
                        <div>
                            <h2 className="font-serif text-lg font-medium text-anthropic-cream">MiroFish 어시스턴트</h2>
                            <p className="text-xs text-anthropic-darkMuted">자연어로 분석 데이터 물어보기 · read-only · Gemini function calling</p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={clearHistory}
                        className="rounded-md px-3 py-1.5 text-xs text-anthropic-darkMuted hover:bg-anthropic-dark2 hover:text-anthropic-cream"
                        title="대화 기록 지우기"
                    >
                        Clear
                    </button>
                </div>
                <div className="flex flex-col">
                    <div ref={scrollRef} className="max-h-[480px] min-h-[200px] overflow-y-auto px-5 py-4 space-y-3">
                        {messages.length === 0 && (
                            <div className="rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 p-4 text-sm text-anthropic-darkText">
                                <div className="text-anthropic-cream mb-3 font-medium">💬 예시 질문을 클릭하거나 직접 입력하세요</div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                    {SUGGESTIONS.map((s) => (
                                        <button
                                            key={s}
                                            type="button"
                                            onClick={() => send(s)}
                                            className="rounded-lg border border-anthropic-darkLine bg-anthropic-dark px-3 py-2 text-left text-xs text-anthropic-darkText transition-colors hover:border-anthropic-orange/40 hover:bg-anthropic-orange/[0.05] hover:text-anthropic-cream"
                                        >
                                            {s}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                        {messages.map((m, idx) => (
                            <div key={idx} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                                <div
                                    className={`max-w-[88%] rounded-lg px-3 py-2 text-[13px] leading-6 ${
                                        m.role === 'user'
                                            ? 'bg-anthropic-orange text-white'
                                            : 'border border-anthropic-darkLine bg-anthropic-dark2 text-anthropic-darkText'
                                    }`}
                                >
                                    <div className="whitespace-pre-wrap break-words">{m.content}</div>
                                    {m.tool_calls && m.tool_calls.length > 0 && (
                                        <details className="mt-2 text-[11px] opacity-80">
                                            <summary className="cursor-pointer hover:opacity-100">
                                                🔧 도구 호출 {m.tool_calls.length}개
                                            </summary>
                                            <div className="mt-1 space-y-1.5">
                                                {m.tool_calls.map((tc, i) => (
                                                    <div key={i} className="rounded border border-anthropic-darkLine bg-anthropic-dark/60 p-1.5 font-mono">
                                                        <div className="text-anthropic-orange">{tc.name}({JSON.stringify(tc.args).slice(1, -1) || ''})</div>
                                                        <div className="mt-0.5 text-anthropic-darkMuted break-all">{tc.result_preview.slice(0, 200)}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        </details>
                                    )}
                                </div>
                            </div>
                        ))}
                        {busy && (
                            <div className="flex justify-start">
                                <div className="rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 px-3 py-2 text-[13px] text-anthropic-darkMuted">
                                    <span className="inline-flex items-center gap-1.5">
                                        <span className="h-1.5 w-1.5 rounded-full bg-anthropic-orange animate-pulse" />
                                        분석 중...
                                    </span>
                                </div>
                            </div>
                        )}
                        {error && (
                            <div className="rounded-md border border-red-500/30 bg-red-500/[0.08] px-3 py-2 text-[12px] text-red-400">
                                {error}
                            </div>
                        )}
                    </div>
                    {/* 입력 */}
                    <div className="border-t border-anthropic-darkLine bg-anthropic-dark2 p-3">
                        <div className="flex items-end gap-2">
                            <textarea
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onCompositionStart={() => (composingRef.current = true)}
                                onCompositionEnd={() => (composingRef.current = false)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey && !composingRef.current) {
                                        e.preventDefault();
                                        send();
                                    }
                                }}
                                placeholder="MiroFish 에게 자연어로 물어보세요 (Enter 전송 · Shift+Enter 줄바꿈)"
                                rows={2}
                                className="min-h-10 flex-1 resize-none rounded-lg border border-anthropic-darkLine bg-anthropic-dark px-3 py-2 text-[13px] text-anthropic-cream placeholder:text-anthropic-darkMuted focus:border-anthropic-orange/40 focus:outline-none"
                                disabled={busy}
                            />
                            <button
                                type="button"
                                onClick={() => send()}
                                disabled={busy || !input.trim()}
                                className="h-10 rounded-lg bg-anthropic-orange px-4 text-sm font-medium text-white hover:bg-anthropic-orangeHover disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                전송
                            </button>
                        </div>
                        <div className="mt-1.5 text-[10px] text-anthropic-darkMuted">
                            Gemini function calling · read-only MCP 도구만 호출 · 대화 기록 로컬 저장
                        </div>
                    </div>
                </div>
            </section>
        );
    }

    // floating 모드 (기본)
    return (
        <>
            {/* FAB (우하단 고정) */}
            {!open && (
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    className="fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 rounded-full bg-anthropic-orange px-5 py-3 text-sm font-medium text-white shadow-xl transition-transform hover:scale-105 hover:bg-anthropic-orangeHover"
                    aria-label="MiroFish 채팅 열기"
                >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                    </svg>
                    MiroFish 대화
                </button>
            )}

            {/* 채팅 패널 */}
            {open && (
                <div className="fixed bottom-0 right-0 z-40 flex h-[80vh] max-h-[680px] w-full max-w-md flex-col rounded-t-2xl border border-anthropic-darkLine bg-anthropic-dark shadow-2xl sm:bottom-5 sm:right-5 sm:rounded-2xl">
                    {HeaderBlock}

                    {/* 메시지 영역 */}
                    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
                        {messages.length === 0 && (
                            <div className="rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 p-4 text-sm text-anthropic-darkText">
                                <div className="font-medium text-anthropic-cream mb-2">👋 안녕하세요</div>
                                <p className="text-anthropic-darkMuted text-[13px] leading-6">
                                    MiroFish 분석 데이터에 대해 자연어로 물어보세요. 한국어 OK.
                                </p>
                                <div className="mt-3 space-y-1.5">
                                    {SUGGESTIONS.map((s) => (
                                        <button
                                            key={s}
                                            type="button"
                                            onClick={() => send(s)}
                                            className="block w-full rounded-md border border-anthropic-darkLine bg-anthropic-dark px-3 py-2 text-left text-[12px] text-anthropic-darkText hover:border-anthropic-orange/40 hover:text-anthropic-cream"
                                        >
                                            💬 {s}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                        {messages.map((m, idx) => (
                            <div key={idx} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                                <div
                                    className={`max-w-[88%] rounded-lg px-3 py-2 text-[13px] leading-6 ${
                                        m.role === 'user'
                                            ? 'bg-anthropic-orange text-white'
                                            : 'border border-anthropic-darkLine bg-anthropic-dark2 text-anthropic-darkText'
                                    }`}
                                >
                                    <div className="whitespace-pre-wrap break-words">{m.content}</div>
                                    {m.tool_calls && m.tool_calls.length > 0 && (
                                        <details className="mt-2 text-[11px] opacity-80">
                                            <summary className="cursor-pointer hover:opacity-100">
                                                🔧 도구 호출 {m.tool_calls.length}개
                                            </summary>
                                            <div className="mt-1 space-y-1.5">
                                                {m.tool_calls.map((tc, i) => (
                                                    <div key={i} className="rounded border border-anthropic-darkLine bg-anthropic-dark/60 p-1.5 font-mono">
                                                        <div className="text-anthropic-orange">{tc.name}({JSON.stringify(tc.args).slice(1, -1) || ''})</div>
                                                        <div className="mt-0.5 text-anthropic-darkMuted break-all">{tc.result_preview.slice(0, 200)}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        </details>
                                    )}
                                </div>
                            </div>
                        ))}
                        {busy && (
                            <div className="flex justify-start">
                                <div className="rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 px-3 py-2 text-[13px] text-anthropic-darkMuted">
                                    <span className="inline-flex items-center gap-1.5">
                                        <span className="h-1.5 w-1.5 rounded-full bg-anthropic-orange animate-pulse" />
                                        분석 중...
                                    </span>
                                </div>
                            </div>
                        )}
                        {error && (
                            <div className="rounded-md border border-red-500/30 bg-red-500/[0.08] px-3 py-2 text-[12px] text-red-400">
                                {error}
                            </div>
                        )}
                    </div>

                    {/* 입력 */}
                    <div className="border-t border-anthropic-darkLine bg-anthropic-dark2 p-3">
                        <div className="flex items-end gap-2">
                            <textarea
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onCompositionStart={() => (composingRef.current = true)}
                                onCompositionEnd={() => (composingRef.current = false)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey && !composingRef.current) {
                                        e.preventDefault();
                                        send();
                                    }
                                }}
                                placeholder="MiroFish 에게 물어보세요 (Enter 전송 · Shift+Enter 줄바꿈)"
                                rows={2}
                                className="min-h-10 flex-1 resize-none rounded-lg border border-anthropic-darkLine bg-anthropic-dark px-3 py-2 text-[13px] text-anthropic-cream placeholder:text-anthropic-darkMuted focus:border-anthropic-orange/40 focus:outline-none"
                                disabled={busy}
                            />
                            <button
                                type="button"
                                onClick={() => send()}
                                disabled={busy || !input.trim()}
                                className="h-10 rounded-lg bg-anthropic-orange px-4 text-sm font-medium text-white hover:bg-anthropic-orangeHover disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                전송
                            </button>
                        </div>
                        <div className="mt-1.5 text-[10px] text-anthropic-darkMuted">
                            Gemini function calling · read-only MCP 도구만 호출 · 대화 기록 로컬 저장
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
