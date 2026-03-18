'use client';

import { useEffect, useState, useRef } from 'react';
import { chatbotAPI } from '@/lib/api';

interface Message {
    role: 'user' | 'bot';
    content: string;
    timestamp: string;
}

export default function ChatbotPage() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [botStatus, setBotStatus] = useState<string>('');
    const messagesEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadWelcome();
    }, []);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const loadWelcome = async () => {
        try {
            const res = await chatbotAPI.getWelcome();
            if (res.message) {
                setMessages([{
                    role: 'bot',
                    content: res.message,
                    timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
                }]);
            }
        } catch {
            setMessages([{
                role: 'bot',
                content: 'Smart Money Bot에 오신 것을 환영합니다! 궁금한 종목이나 시장 상황을 물어보세요.',
                timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
            }]);
        }
        try {
            const status = await chatbotAPI.getStatus();
            setBotStatus(status.gemini_available ? 'AI Connected' : 'Fallback Mode');
        } catch {
            setBotStatus('Offline');
        }
    };

    const sendMessage = async () => {
        if (!input.trim() || loading) return;

        const userMsg: Message = {
            role: 'user',
            content: input.trim(),
            timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
        };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setLoading(true);

        try {
            const res = await chatbotAPI.sendMessage(userMsg.content);
            const botMsg: Message = {
                role: 'bot',
                content: res.response || res.error || 'No response',
                timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
            };
            setMessages(prev => [...prev, botMsg]);
        } catch (e) {
            setMessages(prev => [...prev, {
                role: 'bot',
                content: 'Error: Failed to get response. Please try again.',
                timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
            }]);
        } finally {
            setLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    const formatContent = (text: string) => {
        return text.split('\n').map((line, i) => {
            // Bold
            const formatted = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            return <p key={i} className="mb-1" dangerouslySetInnerHTML={{ __html: formatted }} />;
        });
    };

    return (
        <div className="flex flex-col h-[calc(100vh-120px)]">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-2xl font-bold text-white">Smart Money Bot</h1>
                    <p className="text-gray-500 text-sm mt-1">AI Stock Analysis Chatbot</p>
                </div>
                <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${botStatus === 'AI Connected' ? 'bg-emerald-400' : botStatus === 'Fallback Mode' ? 'bg-yellow-400' : 'bg-red-400'}`} />
                    <span className="text-xs text-gray-500">{botStatus}</span>
                </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto rounded-xl bg-gray-900/50 border border-gray-700/50 p-4 space-y-4">
                {messages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[80%] rounded-xl px-4 py-3 ${
                            msg.role === 'user'
                                ? 'bg-blue-500/20 border border-blue-500/30 text-white'
                                : 'bg-gray-800/80 border border-gray-700/50 text-gray-200'
                        }`}>
                            <div className="text-sm leading-relaxed">{formatContent(msg.content)}</div>
                            <div className="text-xs text-gray-500 mt-2 text-right">{msg.timestamp}</div>
                        </div>
                    </div>
                ))}
                {loading && (
                    <div className="flex justify-start">
                        <div className="bg-gray-800/80 border border-gray-700/50 rounded-xl px-4 py-3">
                            <div className="flex gap-1">
                                <div className="w-2 h-2 rounded-full bg-gray-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                                <div className="w-2 h-2 rounded-full bg-gray-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                                <div className="w-2 h-2 rounded-full bg-gray-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                            </div>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="mt-4 flex gap-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about stocks, market, sectors..."
                    className="flex-1 rounded-xl bg-gray-800/50 border border-gray-700/50 px-4 py-3 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-colors"
                    disabled={loading}
                />
                <button
                    onClick={sendMessage}
                    disabled={loading || !input.trim()}
                    className="px-6 py-3 rounded-xl bg-blue-500/20 border border-blue-500/30 text-blue-400 font-bold text-sm hover:bg-blue-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    Send
                </button>
            </div>

            {/* Quick Commands */}
            <div className="mt-2 flex gap-2 flex-wrap">
                {['What to buy today?', 'Market overview', '/status', '/help'].map((cmd) => (
                    <button
                        key={cmd}
                        onClick={() => { setInput(cmd); }}
                        className="text-xs px-3 py-1.5 rounded-lg bg-gray-800/30 border border-gray-700/30 text-gray-400 hover:text-gray-300 hover:border-gray-600/50 transition-colors"
                    >
                        {cmd}
                    </button>
                ))}
            </div>
        </div>
    );
}
