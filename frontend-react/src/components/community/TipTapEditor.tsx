import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import Link from '@tiptap/extension-link';
import Placeholder from '@tiptap/extension-placeholder';
import { useRef, useCallback, useEffect } from 'react';
import { communityAPI } from '@/lib/api';

interface TipTapEditorProps {
    content: string;
    onChange: (html: string) => void;
    placeholder?: string;
}

function MenuBar({ editor, onImageUpload }: { editor: ReturnType<typeof useEditor>; onImageUpload: () => void }) {
    if (!editor) return null;

    const btn = (active: boolean) =>
        `px-2 py-1.5 rounded text-xs font-medium transition-colors ${
            active ? 'bg-white/15 text-white' : 'text-gray-400 hover:text-white hover:bg-white/10'
        }`;

    return (
        <div className="flex flex-wrap items-center gap-0.5 px-3 py-2 border-b border-white/10">
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
        </div>
    );
}

export default function TipTapEditor({ content, onChange, placeholder = '내용을 입력하세요...' }: TipTapEditorProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);

    const editor = useEditor({
        extensions: [
            StarterKit,
            Image.configure({ inline: false, allowBase64: false }),
            Link.configure({
                openOnClick: false,
                autolink: true,
                HTMLAttributes: { target: '_blank', rel: 'noopener noreferrer' },
            }),
            Placeholder.configure({ placeholder }),
        ],
        content: content || '',
        onUpdate: ({ editor: ed }) => {
            onChange(ed.getHTML());
        },
        editorProps: {
            attributes: {
                class: 'prose prose-invert prose-sm max-w-none text-gray-300 leading-relaxed ' +
                    'prose-headings:text-white prose-a:text-[#2997ff] prose-strong:text-white ' +
                    'prose-code:text-pink-400 prose-code:bg-white/5 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded ' +
                    'prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-pre:rounded-xl ' +
                    'prose-img:rounded-xl prose-img:border prose-img:border-white/10 ' +
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
        if (editor && content && !editor.getHTML().includes(content.substring(0, 20))) {
            editor.commands.setContent(content);
        }
        // Only run when content prop changes from outside, not from typing
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const uploadAndInsertImage = useCallback(async (file: File, _pos?: number) => {
        if (!editor) return;
        try {
            const result = await communityAPI.uploadImage(file);
            editor.chain().focus().setImage({ src: result.url, alt: file.name }).run();
        } catch {
            alert('이미지 업로드에 실패했습니다.');
        }
    }, [editor]);

    return (
        <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden focus-within:border-[#2997ff] transition-colors">
            <MenuBar editor={editor} onImageUpload={() => fileInputRef.current?.click()} />
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
        </div>
    );
}
