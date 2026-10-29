import { request } from './api';

export interface Plan {
  id: string;
  name: string;
  description: string | null;
  monthly_price_inr: number;
  monthly_price_with_gst_inr: number;
  /** Credits granted each period (1 credit = ₹1); they expire when the period ends */
  monthly_credits: number;
  /** Average credits a call minute has cost recently (calls cost real cost + profit, so this varies) */
  avg_credits_per_minute: number;
  approx_minutes: number;
  max_concurrent_calls: number | null;
  is_active: boolean;
  sort_order: number;
}

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
  avg_credits_per_minute: number;
  cancel_at_period_end: boolean;
  renewed_ahead: boolean;
}

export interface PaymentOrder {
  /** Testing mode (SIMULATED_PAYMENTS): confirm in-app instead of opening Razorpay */
  simulated?: boolean;
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
  /** One-time, charged with the first month */
  setup_fee_inr: number;
  /** Setup fee + first month's rent (credits, excl. GST) */
  due_now_inr: number;
  is_available: boolean;
}

export interface AvailableNumber {
  phone_number: string;
  region: string | null;
  number_type: NumberType;
  monthly_rent_inr: number;
  monthly_rent_with_gst_inr: number;
  setup_fee_inr: number;
  due_now_inr: number;
}

export const NUMBER_TYPE_LABELS: Record<NumberType, string> = { Landline: 'Landline', Mobile: 'Mobile', TollFree: 'Toll-free' };

export const plansService = {
  list: (includeArchived = false) => request<Plan[]>(`/plans${includeArchived ? '?include_archived=true' : ''}`),
};

/** 1 credit = ₹1 (excl. GST): plan credits each month, bought credits in the wallet. */
export const creditsLabel = (value: number) =>
  `${value.toLocaleString('en-IN', { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 })} credits`;
