import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useNotification, type AppNotification } from '@/contexts/NotificationContext';

const TOAST_DURATION = 5000;
const MAX_VISIBLE = 4;

const typeStyles: Record<string, { bg: string; icon: string; border: string }> = {
    alert:   { bg: 'bg-amber-500/10', icon: 'fas fa-bolt text-amber-400', border: 'border-amber-500/30' },
    success: { bg: 'bg-emerald-500/10', icon: 'fas fa-check-circle text-emerald-400', border: 'border-emerald-500/30' },
    info:    { bg: 'bg-blue-500/10', icon: 'fas fa-info-circle text-blue-400', border: 'border-blue-500/30' },
};

export default function NotificationToast() {
    const { notifications, dismiss } = useNotification();
    const navigate = useNavigate();
    const [visible, setVisible] = useState<string[]>([]);

    // 새 알림이 추가되면 표시 목록에 추가
    useEffect(() => {
        const unread = notifications.filter(n => !n.read).map(n => n.id);
        const newIds = unread.filter(id => !visible.includes(id));
        if (newIds.length > 0) {
            setVisible(prev => [...newIds, ...prev].slice(0, MAX_VISIBLE));
        }
    }, [notifications]); // eslint-disable-line react-hooks/exhaustive-deps

    // 자동 사라짐
    useEffect(() => {
        if (visible.length === 0) return;
        const timer = setTimeout(() => {
            setVisible(prev => prev.slice(0, -1)); // 가장 오래된 것 제거
        }, TOAST_DURATION);
        return () => clearTimeout(timer);
    }, [visible]);

    const visibleNotifs = visible
        .map(id => notifications.find(n => n.id === id))
        .filter((n): n is AppNotification => !!n);

    if (visibleNotifs.length === 0) return null;

    return (
        <div className="fixed top-16 right-4 z-[100] flex flex-col gap-2 max-w-sm w-full pointer-events-none">
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
                            setVisible(prev => prev.filter(id => id !== n.id));
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
                                    setVisible(prev => prev.filter(id => id !== n.id));
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
