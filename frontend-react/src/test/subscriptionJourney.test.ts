import { describe, it, expect } from 'vitest';
import { reminderDue, SUBSCRIPTION_REMINDER_MS, subscriptionJourney } from '@/lib/subscriptionJourney';
const base={id:1,email:'test@example.test',name:'test',role:'user',status:'approved',tier:'pro',is_pro_expired:false};
describe('renewal journey',()=>{
 it('respects half-hour dismissal then reminds again',()=>{
  expect(reminderDue('1000',1000+SUBSCRIPTION_REMINDER_MS-1)).toBe(false);
  expect(reminderDue('1000',1000+SUBSCRIPTION_REMINDER_MS)).toBe(true);
 });
 it('keeps the cancelled Ultra preference without assuming a pending application',()=>{
  expect(subscriptionJourney({...base,status:'pending',tier:null,requested_tier:'premium',has_pending_subscription:false})?.payment).toBe('/payment-request?plan=premium');
 });
 it('prioritizes base expiry when both subscriptions expire',()=>{
  const result=subscriptionJourney({...base,status:'expired',is_pro_expired:true,is_aibain_expired:true});
  expect(result?.kind).toBe('base-expired');expect(result?.payment).toBe('/payment-request?plan=pro&resubscribe=1');
 });
 it('does not claim an unpurchased AI Brain has expired',()=>{
  expect(subscriptionJourney({...base,is_aibain_active:false,is_aibain_expired:false})).toBeNull();
 });
});
