import { request } from './api';

export interface Plan {
  id: string;
  name: string;
  description: string | null;
  monthly_price_inr: number;
  monthly_price_with_gst_inr: number;
  /** Credits granted each period (1 credit = ₹1); they expire when the period ends */
  monthly_credits: number;
  /** Platform rate: credits one billed call minute costs */
  credits_per_minute: number;
  approx_minutes: number;
  max_concurrent_calls: number | null;
  is_active: boolean;
  sort_order: number;
}

export type PlanInput = Omit<Plan, 'id' | 'monthly_price_with_gst_inr' | 'credits_per_minute' | 'approx_minutes'>;

export interface Subscription {
  plan: Plan | null;
  status: 'ACTIVE' | 'PAST_DUE' | 'CANCELLED';
  usable: boolean;
  in_grace: boolean;
  grace_ends_at: string | null;
  current_period_start: string;
  current_period_end: string;
  days_left: number;
  minutes_used: number;
  monthly_credits: number;
  credits_used: number;
  credits_remaining: number;
  credits_per_minute: number;
  cancel_at_period_end: boolean;
  renewed_ahead: boolean;
}

export interface CallUsage {
  call_id: string;
  plan_id: string | null;
  billed_minutes: number;
  included_minutes: number;
  overage_minutes: number;
  overage_charge_inr: number;
  plan_credits: number;
  wallet_credits: number;
  created_at: string;
}

export interface PaymentOrder {
  order_id: string;
  razorpay_order_id: string;
  amount_paise: number;
  currency: string;
  key_id: string;
  company_name: string;
  description: string;
  prefill: { name: string; email: string };
}

export type NumberType = 'Landline' | 'Mobile' | 'TollFree';

export interface NumberPrice {
  number_type: NumberType;
  monthly_rent_inr: number;
  monthly_rent_with_gst_inr: number;
  is_available: boolean;
}

export interface AvailableNumber {
  phone_number: string;
  region: string | null;
  number_type: NumberType;
  monthly_rent_inr: number;
  monthly_rent_with_gst_inr: number;
}

export const NUMBER_TYPE_LABELS: Record<NumberType, string> = { Landline: 'Landline', Mobile: 'Mobile', TollFree: 'Toll-free' };

const c = (clientId: string) => `/clients/${clientId}`;

export const plansService = {
  list: (includeArchived = false) => request<Plan[]>(`/plans${includeArchived ? '?include_archived=true' : ''}`),
  create: (data: PlanInput) => request<Plan>('/plans', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: PlanInput) => request<Plan>(`/plans/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  subscription: (clientId: string) => request<{ subscription: Subscription | null }>(`${c(clientId)}/subscription`),
  assign: (clientId: string, plan_id: string, reference: string, amount_received_inr?: number) =>
    request<{ invoice_number: string }>(`${c(clientId)}/subscription`, {
      method: 'POST',
      body: JSON.stringify({ plan_id, reference: reference || null, amount_received_inr: amount_received_inr || null }),
    }),
  setCancelAtPeriodEnd: (clientId: string, cancel_at_period_end: boolean) =>
    request<{ subscription: Subscription | null }>(`${c(clientId)}/subscription`, {
      method: 'PUT',
      body: JSON.stringify({ cancel_at_period_end }),
    }),
  usage: (clientId: string) => request<CallUsage[]>(`${c(clientId)}/usage`),
  numberPricing: () => request<NumberPrice[]>('/number-pricing'),
  updateNumberPricing: (numberType: NumberType, monthly_rent_inr: number, is_available: boolean) =>
    request<NumberPrice>(`/number-pricing/${numberType}`, { method: 'PUT', body: JSON.stringify({ monthly_rent_inr, is_available }) }),
  searchNumbersForClient: (clientId: string, numberType: NumberType, region?: string) =>
    request<AvailableNumber[]>(`${c(clientId)}/numbers/available?number_type=${numberType}${region ? `&region=${encodeURIComponent(region)}` : ''}`),
  buyNumberForClient: (clientId: string, phone_number: string, number_type: NumberType) =>
    request<{ id: string; phone_number: string }>(`${c(clientId)}/numbers/buy`, {
      method: 'POST',
      body: JSON.stringify({ phone_number, number_type }),
    }),
};

export const minutesLabel = (value: number) => `${Number.isInteger(value) ? value : value.toFixed(1)} min`;

/** 1 credit = ₹1 (excl. GST): plan credits each month, bought credits in the wallet. */
export const creditsLabel = (value: number) =>
  `${value.toLocaleString('en-IN', { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 })} credits`;
