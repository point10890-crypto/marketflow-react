import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import SubscriptionEntry from '@/components/subscription/SubscriptionEntry';
const m=vi.hoisted(()=>({auth:{user:null as any,token:'token',loading:false},status:vi.fn()}));
vi.mock('@/contexts/AuthContext',()=>({useAuth:()=>m.auth}));
vi.mock('@/lib/api',()=>({subscriptionAPI:{getStatus:m.status}}));
beforeEach(()=>{vi.clearAllMocks();sessionStorage.clear();m.auth.user={id:1,name:'회원',role:'user',status:'approved',tier:null};m.status.mockResolvedValue({requests:[]});});
function show(path='/plan-select'){return render(<MemoryRouter initialEntries={[path]}><SubscriptionEntry /></MemoryRouter>);}
it('shows a dismissible signup popup and retains entry',async()=>{show();expect(await screen.findByRole('dialog')).toHaveTextContent('구독을 시작해 보세요');fireEvent.click(screen.getByRole('button',{name:'플랜 화면에서 살펴보기'}));await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());expect(screen.getByRole('link',{name:'구독 신청하기'})).toHaveAttribute('href','/plan-select');});
it('takes an expired member directly to their previous plan',async()=>{m.auth.user={...m.auth.user,status:'expired',tier:'pro',is_pro_expired:true};show();expect(await screen.findByRole('link',{name:/Pro 재구독/})).toHaveAttribute('href','/payment-request?plan=pro&resubscribe=1');});
it('shows pending instead of another payment',async()=>{m.status.mockResolvedValue({requests:[{status:'pending'}]});show();expect(await screen.findByRole('link',{name:'신청 상태 확인'})).toHaveAttribute('href','/pending-approval');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('does not interrupt payment',()=>{show('/payment-request?plan=pro');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(m.status).not.toHaveBeenCalled();});
it('does not offer payment if status fails',async()=>{m.status.mockRejectedValue(new Error('offline'));show();expect(await screen.findByRole('button',{name:'다시 확인'})).toBeInTheDocument();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('does not prompt an active member or admin',()=>{m.auth.user={...m.auth.user,tier:'pro',status:'approved'};show();expect(m.status).not.toHaveBeenCalled();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
it('remembers dismissal in this session',async()=>{sessionStorage.setItem('subscription-entry:v1:1:new','1');show();expect(await screen.findByRole('link',{name:'구독 신청하기'})).toBeInTheDocument();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();});
