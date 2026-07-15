import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import Link from '@tiptap/extension-link';
import Placeholder from '@tiptap/extension-placeholder';
import { FontSize, TextStyle } from '@tiptap/extension-text-style';
import Youtube from '@tiptap/extension-youtube';
import { useRef, useCallback, useEffect, useState } from 'react';
import { communityAPI, API_BASE } from '@/lib/api';

const FONT_SIZES = [
    { label: '12', value: '12px' },
    { label: '14', value: '14px' },
    { label: '16', value: '16px' },
    { label: '18', value: '18px' },
    { label: '20', value: '20px' },
    { label: '24', value: '24px' },
    { label: '28', value: '28px' },
];

interface TipTapEditorProps {
    content: string;
    onChange: (html: string) => void;
    placeholder?: string;
}

function MenuBar({ editor, onImageUpload, onVideoUpload, uploading }: {
    editor: ReturnType<typeof useEditor>;
    onImageUpload: () => void;
    onVideoUpload: () => void;
    uploading: boolean;
}) {
    const [showFontSize, setShowFontSize] = useState(false);
    if (!editor) return null;

    const btn = (active: boolean) =>
        `px-2 py-1.5 rounded text-xs font-medium transition-colors ${
            active ? 'bg-white/15 text-white' : 'text-gray-400 hover:text-white hover:bg-white/10'
        }`;

    const currentFontSize = editor.getAttributes('textStyle')?.fontSize || null;

    const setFontSizeValue = (size: string | null) => {
        if (size) {
            editor.chain().focus().setFontSize(size).run();
        } else {
            editor.chain().focus().unsetFontSize().run();
        }
        setShowFontSize(false);
    };

    const handleYoutube = () => {
        const url = window.prompt('YouTube URL을 입력하세요:');
        if (url) {
            editor.commands.setYoutubeVideo({ src: url, width: 640, height: 360 });
        }
    };

    return (
        <div className="flex flex-wrap items-center gap-0.5 px-3 py-2 border-b border-white/10">
            {/* Font Size Dropdown */}
            <div className="relative">
                <button
                    type="button"
                    onClick={() => setShowFontSize(!showFontSize)}
                    className={`${btn(!!currentFontSize)} flex items-center gap-1`}
                    title="글자 크기"
                >
                    <i className="fas fa-text-height" />
                    <span className="text-[10px]">{currentFontSize ? currentFontSize.replace('px', '') : '—'}</span>
                    <i className="fas fa-chevron-down text-[8px] opacity-50" />
                </button>
                {showFontSize && (
                    <div className="absolute top-full left-0 mt-1 bg-[#1a1a2e] border border-white/10 rounded-lg shadow-xl z-50 py-1 min-w-[80px]">
                        <button
                            type="button"
                            onClick={() => setFontSizeValue(null)}
                            className="w-full text-left px-3 py-1.5 text-xs text-gray-400 hover:text-white hover:bg-white/10"
                        >
                            기본
                        </button>
                        {FONT_SIZES.map(s => (
                            <button
                                key={s.value}
                                type="button"
                                onClick={() => setFontSizeValue(s.value)}
                                className={`w-full text-left px-3 py-1.5 text-xs transition-colors ${
                                    currentFontSize === s.value
                                        ? 'text-[#2997ff] bg-white/10'
                                        : 'text-gray-300 hover:text-white hover:bg-white/10'
                                }`}
                                style={{ fontSize: s.value }}
                            >
                                {s.label}px
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <span className="w-px h-5 bg-white/10 mx-1" />

            <button type="button" onClick={() => editor.chain().focus().toggleBold().run()} className={btn(editor.isActive('bold'))} title="굵게 (Ctrl+B)">
                <i className="fas fa-bold" />
            </button>
            <button type="button" onClick={() => editor.chain().focus().toggleItalic().run()} className={btn(editor.isActive('italic'))} title="기울임 (Ctrl+I)">
                <i className="fas fa-italic" />
            </button>
            <button type="button" onClick={() => editor.chain().focus().toggleStrike().run()} className={btn(editor.isActive('strike'))} title="취소선">
                <i className="fas fa-strikethrough" />
            </button>

            <span className="w-px h-5 bg-white/10 mx-1" />

            <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} className={btn(editor.isActive('heading', { level: 2 }))} title="제목 2">
                H2
            </button>
            <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} className={btn(editor.isActive('heading', { level: 3 }))} title="제목 3">
                H3
            </button>

            <span className="w-px h-5 bg-white/10 mx-1" />

            <button type="button" onClick={() => editor.chain().focus().toggleBulletList().run()} className={btn(editor.isActive('bulletList'))} title="목록">
                <i className="fas fa-list-ul" />
            </button>
            <button type="button" onClick={() => editor.chain().focus().toggleOrderedList().run()} className={btn(editor.isActive('orderedList'))} title="순서 목록">
                <i className="fas fa-list-ol" />
            </button>

            <span className="w-px h-5 bg-white/10 mx-1" />

            <button type="button" onClick={() => editor.chain().focus().toggleBlockquote().run()} className={btn(editor.isActive('blockquote'))} title="인용">
                <i className="fas fa-quote-right" />
            </button>
            <button type="button" onClick={() => editor.chain().focus().toggleCodeBlock().run()} className={btn(editor.isActive('codeBlock'))} title="코드 블록">
                <i className="fas fa-code" />
            </button>
            <button type="button" onClick={() => editor.chain().focus().setHorizontalRule().run()} className={btn(false)} title="구분선">
                <i className="fas fa-minus" />
            </button>

            <span className="w-px h-5 bg-white/10 mx-1" />

            <button
                type="button"
                onClick={() => {
                    const url = window.prompt('링크 URL을 입력하세요:');
                    if (url) {
                        editor.chain().focus().setLink({ href: url }).run();
                    }
                }}
                className={btn(editor.isActive('link'))}
                title="링크"
            >
                <i className="fas fa-link" />
            </button>

            {editor.isActive('link') && (
                <button type="button" onClick={() => editor.chain().focus().unsetLink().run()} className={btn(false)} title="링크 해제">
                    <i className="fas fa-unlink" />
                </button>
            )}

            <button type="button" onClick={onImageUpload} className={btn(false)} title="이미지">
                <i className="fas fa-image" />
            </button>

            <span className="w-px h-5 bg-white/10 mx-1" />

            {/* Video buttons */}
            <button type="button" onClick={handleYoutube} className={btn(editor.isActive('youtube'))} title="YouTube 동영상">
                <i className="fab fa-youtube" />
            </button>
            <button type="button" onClick={onVideoUpload} disabled={uploading} className={`${btn(false)} ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`} title="동영상 업로드">
                {uploading ? (
                    <i className="fas fa-spinner fa-spin" />
                ) : (
                    <i className="fas fa-video" />
                )}
            </button>
        </div>
    );
}

export default function TipTapEditor({ content, onChange, placeholder = '내용을 입력하세요...' }: TipTapEditorProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const videoInputRef = useRef<HTMLInputElement>(null);
    const lastExternalContentRef = useRef(content || '');
    const [videoUploading, setVideoUploading] = useState(false);

    const editor = useEditor({
        extensions: [
            StarterKit,
            TextStyle,
            FontSize,
            Image.configure({ inline: false, allowBase64: false }),
            Link.configure({
                openOnClick: false,
                autolink: true,
                HTMLAttributes: { target: '_blank', rel: 'noopener noreferrer' },
            }),
            Youtube.configure({
                inline: false,
                ccLanguage: 'ko',
                interfaceLanguage: 'ko',
            }),
            Placeholder.configure({ placeholder }),
        ],
        content: content || '',
        onUpdate: ({ editor: ed }) => {
            const html = ed.getHTML();
            lastExternalContentRef.current = html;
            onChange(html);
        },
        editorProps: {
            attributes: {
                class: 'prose prose-invert prose-sm max-w-none text-gray-300 leading-relaxed ' +
                    'prose-headings:text-white prose-a:text-[#2997ff] prose-strong:text-white ' +
                    'prose-code:text-pink-400 prose-code:bg-white/5 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded ' +
                    'prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-pre:rounded-xl ' +
                    'prose-img:rounded-xl prose-img:border prose-img:border-white/10 ' +
                    '[&_iframe]:rounded-xl [&_iframe]:my-4 [&_iframe]:w-full [&_iframe]:aspect-video ' +
                    '[&_video]:rounded-xl [&_video]:border [&_video]:border-white/10 [&_video]:max-w-full [&_video]:my-4 ' +
                    'min-h-[350px] px-4 py-3 focus:outline-none',
            },
            handleDrop: (view, event, _slice, moved) => {
                if (!moved && event.dataTransfer?.files?.length) {
                    const file = event.dataTransfer.files[0];
                    if (file.type.startsWith('image/')) {
                        event.preventDefault();
                        uploadAndInsertImage(file, view.state.selection.from);
                        return true;
                    }
                    if (file.type.startsWith('video/')) {
                        event.preventDefault();
                        uploadAndInsertVideo(file);
                        return true;
                    }
                }
                return false;
            },
            handlePaste: (_view, event) => {
                const items = event.clipboardData?.items;
                if (!items) return false;
                for (const item of items) {
                    if (item.type.startsWith('image/')) {
                        event.preventDefault();
                        const file = item.getAsFile();
                        if (file) uploadAndInsertImage(file);
                        return true;
                    }
                }
                return false;
            },
        },
    });

    // Sync external content changes (e.g., loading existing post for edit)
    useEffect(() => {
        if (!editor) return;
        const nextContent = content || '';
        if (nextContent === lastExternalContentRef.current) return;
        if (nextContent !== editor.getHTML()) {
            editor.commands.setContent(nextContent);
        }
        lastExternalContentRef.current = nextContent;
    }, [editor, content]);

    const uploadAndInsertImage = useCallback(async (file: File, _pos?: number) => {
        if (!editor) return;
        try {
            const result = await communityAPI.uploadImage(file);
            const imgUrl = result.url.startsWith('/') ? `${API_BASE}${result.url}` : result.url;
            editor.chain().focus().setImage({ src: imgUrl, alt: file.name }).run();
        } catch {
            alert('이미지 업로드에 실패했습니다.');
        }
    }, [editor]);

    const uploadAndInsertVideo = useCallback(async (file: File) => {
        if (!editor) return;
        if (file.size > 100 * 1024 * 1024) {
            alert('동영상 파일은 100MB 이하만 업로드 가능합니다.');
            return;
        }
        setVideoUploading(true);
        try {
            const result = await communityAPI.uploadVideo(file);
            const videoUrl = result.url.startsWith('/') ? `${API_BASE}${result.url}` : result.url;
            editor.chain().focus().insertContent(
                `<video src="${videoUrl}" controls playsinline style="width:100%;max-width:100%"></video>`
            ).run();
        } catch (err: any) {
            alert(err.message || '동영상 업로드에 실패했습니다.');
        } finally {
            setVideoUploading(false);
        }
    }, [editor]);

    return (
        <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden focus-within:border-[#2997ff] transition-colors">
            <MenuBar
                editor={editor}
                onImageUpload={() => fileInputRef.current?.click()}
                onVideoUpload={() => videoInputRef.current?.click()}
                uploading={videoUploading}
            />
            {videoUploading && (
                <div className="px-3 py-1.5 bg-blue-500/10 border-b border-blue-500/20 text-blue-400 text-xs flex items-center gap-2">
                    <i className="fas fa-spinner fa-spin" />
                    동영상 업로드 중...
                </div>
            )}
            <EditorContent editor={editor} />
            <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={e => {
                    const file = e.target.files?.[0];
                    if (file) uploadAndInsertImage(file);
                    e.target.value = '';
                }}
            />
            <input
                ref={videoInputRef}
                type="file"
                accept="video/mp4,video/mov,video/webm,video/*"
                className="hidden"
                onChange={e => {
                    const file = e.target.files?.[0];
                    if (file) uploadAndInsertVideo(file);
                    e.target.value = '';
                }}
            />
        </div>
    );
}
