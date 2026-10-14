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
