import { useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import { communityAPI } from '@/lib/api';

interface PostEditorProps {
    content: string;
    onChange: (content: string) => void;
}

export default function PostEditor({ content, onChange }: PostEditorProps) {
    const [tab, setTab] = useState<'write' | 'preview'>('write');
    const [uploading, setUploading] = useState(false);
    const fileRef = useRef<HTMLInputElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setUploading(true);
        try {
            const result = await communityAPI.uploadImage(file);
            const markdown = `![image](${result.url})`;
            const ta = textareaRef.current;
            if (ta) {
                const start = ta.selectionStart;
                const before = content.slice(0, start);
                const after = content.slice(ta.selectionEnd);
                const newContent = before + markdown + after;
                onChange(newContent);
                // Move cursor after inserted text
                requestAnimationFrame(() => {
                    ta.selectionStart = ta.selectionEnd = start + markdown.length;
                    ta.focus();
                });
            } else {
                onChange(content + '\n' + markdown);
            }
        } catch {
            /* silent */
        } finally {
            setUploading(false);
            // Reset file input so same file can be re-selected
            if (fileRef.current) fileRef.current.value = '';
        }
    };

    return (
        <div>
            {/* Tabs + toolbar */}
            <div className="flex items-center justify-between border-b border-white/10 mb-2">
                <div className="flex">
                    <button
                        onClick={() => setTab('write')}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                            tab === 'write'
                                ? 'text-[#2997ff] border-[#2997ff]'
                                : 'text-gray-500 border-transparent hover:text-white'
                        }`}
                    >
                        작성
                    </button>
                    <button
                        onClick={() => setTab('preview')}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                            tab === 'preview'
                                ? 'text-[#2997ff] border-[#2997ff]'
                                : 'text-gray-500 border-transparent hover:text-white'
                        }`}
                    >
                        미리보기
                    </button>
                </div>
                <div>
                    <input
                        ref={fileRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={handleImageUpload}
                    />
                    <button
                        onClick={() => fileRef.current?.click()}
                        disabled={uploading}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-white border border-white/10 rounded-lg transition-colors disabled:opacity-40"
                    >
                        {uploading ? (
                            <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
                                <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                            </svg>
                        ) : (
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                            </svg>
                        )}
                        {uploading ? '업로드 중...' : '이미지'}
                    </button>
                </div>
            </div>

            {/* Write / Preview */}
            {tab === 'write' ? (
                <textarea
                    ref={textareaRef}
                    value={content}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder="내용을 입력하세요... (마크다운 지원)"
                    className="w-full min-h-[300px] bg-white/5 border border-white/10 text-white rounded-xl px-4 py-3 text-sm placeholder-gray-600 resize-y focus:outline-none focus:border-[#2997ff]/50"
                />
            ) : (
                <div className="min-h-[300px] bg-white/5 border border-white/10 rounded-xl px-4 py-3 prose prose-invert prose-sm max-w-none">
                    {content ? (
                        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                            {content}
                        </ReactMarkdown>
                    ) : (
                        <p className="text-gray-600 text-sm">미리보기할 내용이 없습니다.</p>
                    )}
                </div>
            )}
        </div>
    );
}
