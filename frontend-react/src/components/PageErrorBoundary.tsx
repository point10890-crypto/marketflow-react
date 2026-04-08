import { Component, type ReactNode } from 'react';

interface Props {
    children: ReactNode;
    /** 라우트 경로 등 — 변경 시 에러 상태를 자동 리셋해 사이드바 네비를 살아 있게 유지. */
    resetKey?: string;
}

interface State {
    hasError: boolean;
}

/**
 * 페이지 단위 에러 경계.
 * - DashboardLayout 의 <Outlet /> 주변에 두어 한 페이지가 터져도 사이드바·헤더·다른 페이지 네비는 살아 있게 함.
 * - 백엔드 다운 등 일시 장애에는 "다시 시도" 버튼만 노출 (전체 새로고침 강제 X).
 */
export class PageErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false };

    static getDerivedStateFromError(): State {
        return { hasError: true };
    }

    componentDidCatch(error: Error) {
        console.error('[PageErrorBoundary]', error);
    }

    componentDidUpdate(prevProps: Props) {
        if (prevProps.resetKey !== this.props.resetKey && this.state.hasError) {
            this.setState({ hasError: false });
        }
    }

    handleRetry = () => this.setState({ hasError: false });

    render() {
        if (!this.state.hasError) return this.props.children;
        return (
            <div className="flex items-center justify-center h-full min-h-[400px]">
                <div className="text-center p-8 max-w-md">
                    <i className="fas fa-cloud text-amber-400 text-4xl mb-4 block" />
                    <h2 className="text-white text-lg font-bold mb-2">데이터를 불러올 수 없습니다</h2>
                    <p className="text-gray-400 text-sm mb-1">백엔드 서버가 잠시 점검 중일 수 있습니다.</p>
                    <p className="text-gray-500 text-xs mb-6">사이드바에서 다른 페이지로 이동할 수 있습니다.</p>
                    <button
                        onClick={this.handleRetry}
                        className="px-5 py-2 bg-amber-500 text-black rounded-lg font-bold text-sm hover:bg-amber-400 transition"
                    >
                        다시 시도
                    </button>
                </div>
            </div>
        );
    }
}
