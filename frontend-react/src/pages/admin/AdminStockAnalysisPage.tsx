import { Navigate, useSearchParams } from 'react-router-dom';

// Keep bookmarked admin URLs usable after moving the tool into chart analysis.
export default function AdminStockAnalysisPage() {
    const [params] = useSearchParams();
    const next = new URLSearchParams(params);
    const code = next.get('code') ?? '';
    if (/^\d{6}$/.test(code) && code !== '000000') next.set('adminCode', code);
    else { next.delete('code'); next.delete('adminCode'); }
    const search = next.toString();
    return <Navigate replace to={{ pathname: '/dashboard/ai-bain/chart-predict', search: search ? `?${search}` : '', hash: '#admin-stock-analysis' }} />;
}
