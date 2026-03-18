'use client';

export default function DashboardError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return (
        <div className="flex flex-col items-center justify-center h-full p-8 text-white">
            <h2 className="text-xl font-bold mb-4 text-red-400">Dashboard Error</h2>
            <pre className="bg-zinc-900 p-4 rounded-lg text-sm text-red-300 max-w-2xl overflow-auto mb-4 whitespace-pre-wrap">
                {error.message}
            </pre>
            <pre className="bg-zinc-900 p-4 rounded-lg text-xs text-gray-400 max-w-2xl overflow-auto mb-6 whitespace-pre-wrap max-h-64">
                {error.stack}
            </pre>
            <button
                onClick={reset}
                className="px-4 py-2 bg-blue-600 rounded-lg hover:bg-blue-500 transition"
            >
                Try Again
            </button>
        </div>
    );
}
