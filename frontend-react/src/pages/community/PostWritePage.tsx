import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { communityAPI } from '@/lib/api';
import TipTapEditor from '@/components/community/TipTapEditor';

export default function PostWritePage() {
    const { boardSlug, postId } = useParams<{ boardSlug?: string; postId?: string }>();
    const navigate = useNavigate();

    const isEdit = !!postId;
    const [title, setTitle] = useState('');
    const [content, setContent] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [loadingPost, setLoadingPost] = useState(isEdit);
    const [resolvedSlug, setResolvedSlug] = useState(boardSlug || '');
    const [boardName, setBoardName] = useState('');

    // Load board name
    useEffect(() => {
        if (!boardSlug) return;
        communityAPI.getBoards().then(boards => {
            const found = boards.find(b => b.slug === boardSlug);
            if (found) setBoardName(found.name);
        });
    }, [boardSlug]);

    // Load existing post for edit mode
    useEffect(() => {
        if (!isEdit || !postId) return;
        communityAPI.getPost(Number(postId))
            .then(data => {
                const post = data.post;
                setTitle(post.title);
                setContent(post.content || '');
                if (post.board) {
                    setResolvedSlug(post.board.slug);
                    setBoardName(post.board.name);
                }
            })
            .catch(err => setError(err.message || '게시글을 불러올 수 없습니다.'))
            .finally(() => setLoadingPost(false));
    }, [isEdit, postId]);

    const handleSubmit = async () => {
        if (!title.trim()) { setError('제목을 입력하세요.'); return; }
        if (!content.trim() || content === '<p></p>') { setError('내용을 입력하세요.'); return; }
        if (!isEdit && !resolvedSlug) { setError('게시판 정보가 없습니다.'); return; }

        setSubmitting(true);
        setError('');

        try {
            if (isEdit && postId) {
                await communityAPI.updatePost(Number(postId), { title: title.trim(), content });
                navigate(`/dashboard/community/post/${postId}`);
            } else {
                const created = await communityAPI.createPost(resolvedSlug, { title: title.trim(), content });
                navigate(`/dashboard/community/post/${created.id}`);
            }
        } catch (err: any) {
            setError(err.message || '저장에 실패했습니다.');
        } finally {
            setSubmitting(false);
        }
    };

    if (loadingPost) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-8 h-8 border-2 border-[#2997ff] border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    return (
        <div className="p-4 md:p-6 lg:py-8 lg:px-10">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => navigate(-1)}
                        className="w-8 h-8 rounded-lg bg-white/[0.06] flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                    >
                        <i className="fas fa-arrow-left text-sm" />
                    </button>
                    <div>
                        <h1 className="text-lg md:text-xl font-bold text-white">
                            {isEdit ? '글 수정' : '글쓰기'}
                        </h1>
                        {boardName && (
                            <p className="text-gray-600 text-xs mt-0.5">{boardName}</p>
                        )}
                    </div>
                </div>

                <button
                    onClick={handleSubmit}
                    disabled={submitting}
                    className="bg-[#2997ff] hover:bg-[#2997ff]/85 text-white font-bold text-sm rounded-xl px-5 py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed active:scale-95 flex items-center gap-2"
                >
                    {submitting ? (
                        <>
                            <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            저장 중...
                        </>
                    ) : (
                        isEdit ? '수정' : '등록'
                    )}
                </button>
            </div>

            {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 text-red-400 text-sm mb-4 flex items-center gap-2">
                    <i className="fas fa-exclamation-circle" />{error}
                </div>
            )}

            {/* Title */}
            <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="제목을 입력하세요"
                className="w-full bg-transparent border-b border-white/10 text-white placeholder-gray-600 px-1 py-3 focus:border-[#2997ff] focus:outline-none text-lg md:text-xl font-medium mb-5 transition-colors"
            />

            {/* TipTap Editor */}
            <TipTapEditor
                content={content}
                onChange={setContent}
                placeholder="내용을 입력하세요... (이미지: 붙여넣기 또는 드래그앤드롭)"
            />
        </div>
    );
}
