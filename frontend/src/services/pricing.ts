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
  infra_cost_per_minute_inr: number;
  updated_at: string | null;
  updated_by: string | null;
  preview: PricingPreview;
}

export const pricingService = {
  get: () => request<PricingSettings>('/pricing'),
  update: (profit_percent: number, infra_cost_per_minute_inr: number) =>
    request<PricingSettings>('/pricing', {
      method: 'PUT',
      body: JSON.stringify({ profit_percent, infra_cost_per_minute_inr }),
    }),
};
