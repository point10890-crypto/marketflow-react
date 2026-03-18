'use client';

export default function USError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] p-6">
            <div className="p-8 rounded-2xl bg-[#1c1c1e] border border-red-500/20 max-w-md w-full text-center">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-500/10 flex items-center justify-center">
                    <i className="fas fa-exclamation-triangle text-red-400 text-2xl"></i>
                </div>
                <h2 className="text-xl font-bold text-white mb-2">페이지 로드 오류</h2>
                <p className="text-sm text-gray-400 mb-6">
                    US Market 데이터를 불러오는 중 오류가 발생했습니다.
                </p>
                <button
                    onClick={reset}
                    className="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm transition-colors"
                >
                    <i className="fas fa-redo mr-2"></i>
                    다시 시도
                </button>
                <p className="text-[10px] text-gray-600 mt-4">
                    {error.message}
                </p>
            </div>
        </div>
    );
}
