import { request } from './api';

export interface PricingPreview {
  window_days: number;
  calls: number;
  minutes: number;
  avg_cost_per_minute: number | null;
  avg_charge_per_minute: number | null;
  avg_profit_per_minute: number | null;
}

export interface PricingSettings {
  profit_percent: number;
  /** Default simultaneous calls for pay-as-you-go clients (admins can override per client) */
  payg_max_concurrent_calls: number;
  updated_at: string | null;
  updated_by: string | null;
  preview: PricingPreview;
}

export const pricingService = {
  get: () => request<PricingSettings>('/pricing'),
  update: (profit_percent: number, payg_max_concurrent_calls?: number) =>
    request<PricingSettings>('/pricing', {
      method: 'PUT',
      body: JSON.stringify({ profit_percent, payg_max_concurrent_calls }),
    }),
};

/** A suggested credit top-up by business size (1 credit = ₹1, pre-GST) */
export interface CreditPack {
  key: string;
  name: string;
  credits: number;
  suits: string;
  recommended: boolean;
  price_with_gst_inr: number;
  /** About how many call minutes / calls the pack buys at the recent per-minute rate */
  approx_minutes: number;
  approx_calls: number;
}

export interface PublicCreditPacks {
  packs: CreditPack[];
  avg_credits_per_minute: number;
  gst_rate_percent: number;
  gst_registered: boolean;
  min_topup_inr: number;
}

export const publicPricingService = {
  creditPacks: () => request<PublicCreditPacks>('/public/credit-packs'),
};
