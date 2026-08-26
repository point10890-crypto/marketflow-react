import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useNotification, type AppNotification } from '@/contexts/NotificationContext';

const TOAST_DURATION = 5000;
const MAX_VISIBLE = 3;

const typeStyles: Record<string, { bg: string; icon: string; border: string }> = {
    alert:   { bg: 'bg-amber-500/10', icon: 'fas fa-bolt text-amber-400', border: 'border-amber-500/30' },
    success: { bg: 'bg-emerald-500/10', icon: 'fas fa-check-circle text-emerald-400', border: 'border-emerald-500/30' },
    info:    { bg: 'bg-blue-500/10', icon: 'fas fa-info-circle text-blue-400', border: 'border-blue-500/30' },
};

export default function NotificationToast() {
    const { notifications, dismiss, markRead } = useNotification();
    const navigate = useNavigate();
    const [visible, setVisible] = useState<string[]>([]);
    const initializedRef = useRef(false);
    const seenIdsRef = useRef(new Set<string>());
    const timersRef = useRef(new Map<string, number>());

    // 저장소에서 복원한 unread는 알림 센터에만 남기고, 이 탭에서 새로
    // 도착한 알림만 toast로 표시한다. 새로고침 때 과거 toast가 재생되는
    // 현상과 다음 알림 때 과거 unread가 다시 쌓이는 현상을 함께 막는다.
    useEffect(() => {
        const currentIds = new Set(notifications.map(n => n.id));
        for (const id of seenIdsRef.current) {
            if (!currentIds.has(id)) seenIdsRef.current.delete(id);
        }

        if (!initializedRef.current) {
            notifications.forEach(n => seenIdsRef.current.add(n.id));
            initializedRef.current = true;
            return;
        }

        const unread = notifications.filter(n => !n.read).map(n => n.id);
        const newIds = unread.filter(id => !seenIdsRef.current.has(id));
        notifications.forEach(n => seenIdsRef.current.add(n.id));

        if (newIds.length > 0) {
            setVisible(prev => {
                const merged = [...newIds, ...prev];
                const unique = Array.from(new Set(merged));
                return unique.slice(0, MAX_VISIBLE);
            });

            for (const id of newIds) {
                const timer = window.setTimeout(() => {
                    setVisible(prev => prev.filter(visibleId => visibleId !== id));
                    timersRef.current.delete(id);
                }, TOAST_DURATION);
                timersRef.current.set(id, timer);
            }
        }
    }, [notifications]);

    useEffect(() => {
        const timers = timersRef.current;
        return () => {
            timers.forEach(timer => window.clearTimeout(timer));
            timers.clear();
        };
    }, []);

    const hideToast = useCallback((id: string) => {
        const timer = timersRef.current.get(id);
        if (timer !== undefined) window.clearTimeout(timer);
        timersRef.current.delete(id);
        setVisible(prev => prev.filter(visibleId => visibleId !== id));
    }, []);

    const visibleNotifs = visible
        .map(id => notifications.find(n => n.id === id))
        .filter((n): n is AppNotification => !!n);

    if (visibleNotifs.length === 0) return null;

    return (
        <div className="notification-toast-stack fixed left-3 right-3 z-[100] flex flex-col gap-2 pointer-events-none sm:left-auto sm:right-4 sm:w-full sm:max-w-sm">
            {visibleNotifs.map((n, i) => {
                const style = typeStyles[n.type] || typeStyles.info;
                return (
                    <div
                        key={n.id}
                        className={`${style.bg} ${style.border} border rounded-xl p-3 backdrop-blur-md shadow-2xl pointer-events-auto cursor-pointer
                            animate-in slide-in-from-right duration-300`}
                        style={{ animationDelay: `${i * 50}ms` }}
                        onClick={() => {
                            if (n.link) navigate(n.link);
                            markRead(n.id);
                            hideToast(n.id);
                        }}
                    >
                        <div className="flex items-start gap-3">
                            <i className={`${style.icon} text-sm mt-0.5`}></i>
                            <div className="flex-1 min-w-0">
                                <div className="text-xs font-bold text-white truncate">{n.title}</div>
                                <div className="text-[11px] text-gray-400 mt-0.5 line-clamp-2">{n.message}</div>
                            </div>
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    hideToast(n.id);
                                    dismiss(n.id);
                                }}
                                className="text-gray-500 hover:text-white text-xs p-1"
                            >
                                <i className="fas fa-times"></i>
                            </button>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
