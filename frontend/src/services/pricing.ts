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
  updated_at: string | null;
  updated_by: string | null;
  preview: PricingPreview;
}

export interface CarrierCheckCall {
  call_id: string;
  ended_at: string | null;
  direction: string;
  is_test: boolean;
  duration_seconds: number;
  estimated_inr: number;
  exotel_price_inr: number;
  actual_inr: number;
  gap_inr: number;
}

/** Choranta's phone-line estimate vs what Exotel actually charged */
export interface CarrierCheck {
  days: number;
  calls_priced: number;
  estimated_total_inr: number;
  actual_total_inr: number;
  gap_percent: number | null;
  alert_percent: number;
  rate_too_low: boolean;
  current_rate_per_minute_inr: number;
  /** The per-minute rate that would have matched Exotel exactly */
  matching_rate_per_minute_inr: number | null;
  /** True when 18% GST is added to Exotel's price (not GST-registered yet) */
  gst_added: boolean;
  calls: CarrierCheckCall[];
}

export const pricingService = {
  get: () => request<PricingSettings>('/pricing'),
  carrierCheck: (days = 30) => request<CarrierCheck>(`/pricing/carrier-check?days=${days}`),
  update: (profit_percent: number) =>
    request<PricingSettings>('/pricing', {
      method: 'PUT',
      body: JSON.stringify({ profit_percent }),
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
