import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';

export interface AppNotification {
    id: string;
    type: 'info' | 'success' | 'alert';
    title: string;
    message: string;
    link?: string;
    timestamp: number;
    read: boolean;
}

interface NotificationContextType {
    notifications: AppNotification[];
    unreadCount: number;
    notify: (n: Omit<AppNotification, 'id' | 'timestamp' | 'read'>) => void;
    dismiss: (id: string) => void;
    markAllRead: () => void;
    clearAll: () => void;
    showBrowserNotification: (title: string, body: string, link?: string) => void;
}

const NotificationContext = createContext<NotificationContextType | null>(null);

const STORAGE_KEY = 'bitman_notifications';
const MAX_NOTIFICATIONS = 30;

function loadFromStorage(): AppNotification[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw) as AppNotification[];
        // 24시간 이내 것만 유지
        const cutoff = Date.now() - 24 * 60 * 60 * 1000;
        return parsed.filter(n => n.timestamp > cutoff).slice(0, MAX_NOTIFICATIONS);
    } catch {
        return [];
    }
}

function saveToStorage(notifications: AppNotification[]) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications.slice(0, MAX_NOTIFICATIONS)));
    } catch { /* quota exceeded */ }
}

export function NotificationProvider({ children }: { children: ReactNode }) {
    const [notifications, setNotifications] = useState<AppNotification[]>(loadFromStorage);
    const [permission, setPermission] = useState<NotificationPermission>('default');

    // 브라우저 알림 권한 체크
    useEffect(() => {
        if ('Notification' in window) {
            setPermission(Notification.permission);
        }
    }, []);

    // 권한 요청 (첫 알림 시)
    const requestPermission = useCallback(async () => {
        if ('Notification' in window && Notification.permission === 'default') {
            const result = await Notification.requestPermission();
            setPermission(result);
            return result;
        }
        return Notification.permission;
    }, []);

    // 브라우저 네이티브 알림
    const showBrowserNotification = useCallback((title: string, body: string, link?: string) => {
        if (permission !== 'granted' || document.visibilityState === 'visible') return;
        try {
            const notification = new Notification(title, {
                body,
                icon: '/icon-192.png',
                badge: '/icon-192.png',
                tag: 'bitman-' + Date.now(),
            });
            notification.onclick = () => {
                window.focus();
                if (link) window.location.hash = '';  // will navigate via React
                notification.close();
            };
        } catch { /* mobile may not support */ }
    }, [permission]);

    const notify = useCallback((n: Omit<AppNotification, 'id' | 'timestamp' | 'read'>) => {
        const newNotif: AppNotification = {
            ...n,
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            timestamp: Date.now(),
            read: false,
        };

        setNotifications(prev => {
            const updated = [newNotif, ...prev].slice(0, MAX_NOTIFICATIONS);
            saveToStorage(updated);
            return updated;
        });

        // 권한 없으면 첫 알림 시 요청
        if (permission === 'default') {
            requestPermission();
        }

        // 백그라운드 탭이면 브라우저 알림
        if (document.visibilityState !== 'visible') {
            showBrowserNotification(n.title, n.message, n.link);
        }
    }, [permission, requestPermission, showBrowserNotification]);

    const dismiss = useCallback((id: string) => {
        setNotifications(prev => {
            const updated = prev.filter(n => n.id !== id);
            saveToStorage(updated);
            return updated;
        });
    }, []);

    const markAllRead = useCallback(() => {
        setNotifications(prev => {
            const updated = prev.map(n => ({ ...n, read: true }));
            saveToStorage(updated);
            return updated;
        });
    }, []);

    const clearAll = useCallback(() => {
        setNotifications([]);
        saveToStorage([]);
    }, []);

    const unreadCount = notifications.filter(n => !n.read).length;

    return (
        <NotificationContext.Provider value={{ notifications, unreadCount, notify, dismiss, markAllRead, clearAll, showBrowserNotification }}>
            {children}
        </NotificationContext.Provider>
    );
}

export function useNotification() {
    const ctx = useContext(NotificationContext);
    if (!ctx) throw new Error('useNotification must be inside NotificationProvider');
    return ctx;
}
