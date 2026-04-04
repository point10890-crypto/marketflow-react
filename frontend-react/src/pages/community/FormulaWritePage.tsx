import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { communityAPI } from '@/lib/api';
import TipTapEditor from '@/components/community/TipTapEditor';

export default function FormulaWritePage() {
    const navigate = useNavigate();

    const [name, setName] = useState('');
    const [content, setContent] = useState('');
    const [price, setPrice] = useState('');
    const [isPublic, setIsPublic] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async () => {
        if (!name.trim()) { setError('이름을 입력하세요.'); return; }
        if (!content.trim() || content === '<p></p>') { setError('내용을 입력하세요.'); return; }

        setSubmitting(true);
        setError('');

        try {
            let fileUrl: string | undefined;
            let fileName: string | undefined;

            // Upload formula file if selected
            if (file) {
                const uploaded = await communityAPI.uploadFile(file);
                fileUrl = uploaded.url;
                fileName = uploaded.original_name;
            }

            const created = await communityAPI.createPost('formula-market', {
                title: name.trim(),
                content,
                price: price.trim() || undefined,
                is_public: isPublic,
                file_url: fileUrl,
                file_name: fileName,
            } as any);

            navigate(`/dashboard/community/post/${created.id}`);
        } catch (err: any) {
            setError(err.message || '등록에 실패했습니다.');
        } finally {
            setSubmitting(false);
        }
    };

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
                    <h1 className="text-lg md:text-xl font-bold text-yellow-400">수식 등록</h1>
                </div>

                <button
                    onClick={handleSubmit}
                    disabled={submitting}
                    className="bg-yellow-500 hover:bg-yellow-500/85 text-black font-bold text-sm rounded-xl px-5 py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed active:scale-95 flex items-center gap-2"
                >
                    {submitting ? (
                        <>
                            <div className="w-3.5 h-3.5 border-2 border-black border-t-transparent rounded-full animate-spin" />
                            등록 중...
                        </>
                    ) : '등록'}
                </button>
            </div>

            {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 text-red-400 text-sm mb-4 flex items-center gap-2">
                    <i className="fas fa-exclamation-circle" />{error}
                </div>
            )}

            {/* Form */}
            <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl overflow-hidden">
                {/* 공개여부 */}
                <div className="flex items-center border-b border-white/[0.06]">
                    <label className="w-32 md:w-40 px-5 py-4 text-sm font-bold text-gray-300 bg-white/[0.02] flex-shrink-0">
                        공개여부
                    </label>
                    <div className="flex items-center gap-5 px-5 py-4">
                        <label className="flex items-center gap-2 cursor-pointer text-sm">
                            <input
                                type="radio"
                                name="visibility"
                                checked={isPublic}
                                onChange={() => setIsPublic(true)}
                                className="w-4 h-4 accent-yellow-500"
                            />
                            <span className="text-gray-300">공개</span>
                        </label>
                        <label className="flex items-center gap-2 cursor-pointer text-sm">
                            <input
                                type="radio"
                                name="visibility"
                                checked={!isPublic}
                                onChange={() => setIsPublic(false)}
                                className="w-4 h-4 accent-yellow-500"
                            />
                            <span className="text-gray-300">비공개</span>
                        </label>
                    </div>
                </div>

                {/* 이름 */}
                <div className="flex items-center border-b border-white/[0.06]">
                    <label className="w-32 md:w-40 px-5 py-4 text-sm font-bold text-gray-300 bg-white/[0.02] flex-shrink-0">
                        이름
                    </label>
                    <div className="flex-1 px-5 py-3">
                        <input
                            type="text"
                            value={name}
                            onChange={e => setName(e.target.value)}
                            placeholder="이름을 입력하세요."
                            className="w-full bg-transparent text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff]/50 text-sm"
                        />
                    </div>
                </div>

                {/* 내용 */}
                <div className="flex border-b border-white/[0.06]">
                    <label className="w-32 md:w-40 px-5 py-4 text-sm font-bold text-gray-300 bg-white/[0.02] flex-shrink-0">
                        내용
                    </label>
                    <div className="flex-1 p-3 md:p-4 min-h-[300px]">
                        <TipTapEditor
                            content={content}
                            onChange={setContent}
                            placeholder="내용을 입력하세요..."
                        />
                    </div>
                </div>

                {/* 가격 */}
                <div className="flex items-center border-b border-white/[0.06]">
                    <label className="w-32 md:w-40 px-5 py-4 text-sm font-bold text-gray-300 bg-white/[0.02] flex-shrink-0">
                        가격
                    </label>
                    <div className="flex-1 px-5 py-3">
                        <input
                            type="text"
                            value={price}
                            onChange={e => setPrice(e.target.value)}
                            placeholder="가격을 입력하세요."
                            className="w-full bg-transparent text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff]/50 text-sm"
                        />
                    </div>
                </div>

                {/* 식파일 */}
                <div className="flex items-center">
                    <label className="w-32 md:w-40 px-5 py-4 text-sm font-bold text-gray-300 bg-white/[0.02] flex-shrink-0">
                        식파일
                    </label>
                    <div className="flex items-center gap-3 px-5 py-3">
                        <label className="cursor-pointer bg-white/[0.08] hover:bg-white/[0.12] text-gray-300 text-xs font-bold px-3 py-2 rounded-lg transition-colors border border-white/10">
                            파일 선택
                            <input
                                type="file"
                                accept=".txt,.csv,.xlsx,.xls,.pdf,.zip,.hwp,.docx"
                                onChange={e => setFile(e.target.files?.[0] || null)}
                                className="hidden"
                            />
                        </label>
                        <span className="text-gray-500 text-xs">
                            {file ? file.name : '선택된 파일 없음'}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
}
