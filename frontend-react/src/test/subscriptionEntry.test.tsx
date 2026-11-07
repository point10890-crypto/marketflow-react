import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import SubscriptionEntry from '@/components/subscription/SubscriptionEntry';
const m=vi.hoisted(()=>({auth:{user:null as any,token:'token',loading:false},status:vi.fn()}));
vi.mock('@/contexts/AuthContext',()=>({useAuth:()=>m.auth}));
vi.mock('@/lib/api',()=>({subscriptionAPI:{getStatus:m.status}}));
beforeEach(()=>{vi.clearAllMocks();sessionStorage.clear();m.auth.user={id:1,name:'회원',role:'user',status:'approved',tier:null};m.status.mockResolvedValue({requests:[]});});
function show(path='/community'){return render(<MemoryRouter initialEntries={[path]}><SubscriptionEntry /></MemoryRouter>);}
it('shows a dismissible signup popup and retains entry',async()=>{show();expect(await screen.findByRole('dialog')).toHaveTextContent('구독을 시작해 보세요');fireEvent.click(screen.getByRole('button',{name:'나중에 보기'}));await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());expect(screen.getByRole('link',{name:'구독 신청하기'})).toHaveAttribute('href','/plan-select');});
it('lets an expired member compare renewal plans before payment',async()=>{m.auth.user={...m.auth.user,status:'expired',tier:'pro',is_pro_expired:true};show();expect(await screen.findByRole('link',{name:/재구독 플랜 선택/})).toHaveAttribute('href','/plan-select?resubscribe=1&from=expired');});
it('shows pending instead of another payment',async()=>{m.status.mockResolvedValue({requests:[{status:'pending'}]});show();expect(await screen.findByRole('link',{name:'신청 상태 확인'})).toHaveAttribute('href','/pending-approval');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('does not interrupt payment',()=>{show('/payment-request?plan=pro');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(m.status).not.toHaveBeenCalled();});
it('does not cover plan selection with another subscription popup',()=>{show('/plan-select?change=1');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(m.status).not.toHaveBeenCalled();});
it('does not offer payment if status fails',async()=>{m.status.mockRejectedValue(new Error('offline'));show();expect(await screen.findByRole('button',{name:'다시 확인'})).toBeInTheDocument();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('does not prompt an active member or admin',()=>{m.auth.user={...m.auth.user,tier:'pro',status:'approved'};show();expect(m.status).not.toHaveBeenCalled();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('remembers dismissal in this session',async()=>{sessionStorage.setItem('subscription-entry:v2:1:subscribe:',String(Date.now()));show();expect(await screen.findByRole('link',{name:'구독 신청하기'})).toBeInTheDocument();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('shows expired AI Brain renewal immediately without blocking the base dashboard',async()=>{
 m.auth.user={...m.auth.user,tier:'pro',status:'approved',is_pro_expired:false,is_aibain_expired:true,aibain_expires_at:'2026-09-30T00:00:00Z'};
 show('/dashboard');expect(await screen.findByRole('dialog')).toHaveTextContent('AI Brain을 다시 이용하세요');
 expect(within(screen.getByRole('dialog')).getByRole('link',{name:/AI Brain·제갈공명 재구독/})).toHaveAttribute('href','/payment-request?plan=pro&aibain=1');
});
it('suppresses the popup for a pending request outside the displayed history',async()=>{
 m.status.mockResolvedValue({requests:[{status:'rejected'}],user:{has_pending_subscription:true},pending_request:{id:9,status:'pending'}});
 show();expect(await screen.findByRole('link',{name:'신청 상태 확인'})).toBeInTheDocument();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('checks fresh pending status before reopening after thirty minutes',async()=>{
 show();await screen.findByRole('dialog');fireEvent.click(screen.getByRole('button',{name:'나중에 보기'}));
 let resolveStatus!: (value:any)=>void;
 m.status.mockImplementation(()=>new Promise(resolve=>{resolveStatus=resolve;}));
 const later=Date.now()+31*60*1000;vi.spyOn(Date,'now').mockReturnValue(later);
 try {
  act(()=>window.dispatchEvent(new Event('focus')));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('link',{name:'구독 신청하기'})).not.toBeInTheDocument();
  await act(async()=>resolveStatus({requests:[],pending_request:{id:10,status:'pending'}}));
  expect(screen.getByRole('link',{name:'신청 상태 확인'})).toBeInTheDocument();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
 } finally {vi.restoreAllMocks();}
});
it('moves the banner into the dashboard host after authentication hydrates',async()=>{
 m.auth.loading=true;const view=show('/dashboard');
 const host=document.createElement('div');host.id='subscription-entry-dashboard';document.body.append(host);
 try {m.auth.loading=false;view.rerender(<MemoryRouter initialEntries={['/dashboard']}><SubscriptionEntry /></MemoryRouter>);await waitFor(()=>expect(within(host).getByLabelText('구독 안내')).toBeInTheDocument());}
 finally {view.unmount();host.remove();}
});

it('promotes the conversion on the dashboard only for eligible members', () => {
    m.auth.user = { ...m.auth.user, tier: 'pro', ai_bundle_conversion: {
        eligible: false, amount: 10000, expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    }};
    const hidden = show('/dashboard');
    expect(screen.queryByLabelText('제갈공명 전환 안내')).not.toBeInTheDocument();
    hidden.unmount();
    m.auth.user.ai_bundle_conversion.eligible = true;
    show('/dashboard');
    const banner = screen.getByLabelText('제갈공명 전환 안내');
    expect(banner).toHaveTextContent('10,000원');
    expect(within(banner).getByRole('link', { name: '제갈공명 전환 신청' }))
        .toHaveAttribute('href', '/payment-request?plan=aibain_kongming_conversion');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
