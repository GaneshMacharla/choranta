import { request } from './api';

export type FinancePeriod = '7d' | '30d' | '90d' | 'month';

export interface FinanceBucket {
  bucket: string; // YYYY-MM-DD, or YYYY-MM for long ranges
  money_in: number;
  revenue: number;
  cost: number;
  profit: number;
}

export interface FinanceClientRow {
  client_id: string;
  name: string;
  money_in: number;
  revenue: number;
  cost: number;
  profit: number;
  margin_pct: number | null;
  wallet_balance: number;
  low_balance: boolean;
}

export interface FinanceSummary {
  period: FinancePeriod;
  currency: 'INR';
  start: string;
  end: string;
  granularity: 'day' | 'month';
  money_in: { total: number; taxable: number; gst: number; adjustments: number };
  revenue: { total: number; calls: number; number_rent: number; number_setup: number; whatsapp: number; plans: number; other: number };
  cost: { total: number; telephony: number; speech_to_text: number; text_to_speech: number; llm: number; number_rent: number };
  profit: number;
  margin_pct: number | null;
  calls: { count: number; minutes: number };
  mock_numbers: number;
  trend: FinanceBucket[];
  clients: FinanceClientRow[];
}

export interface CapacityTotals {
  peak_live_calls: number;
  inbound_refused_busy: number;
  callbacks_queued: number;
  callbacks_connected: number;
  callbacks_expired: number;
  campaign_wait_seconds: number;
  vobiz_limit_rejections: number;
  sarvam_rejections: number;
  gemini_fallbacks: number;
  live_call_minutes: number;
}

export interface CapacityReport {
  limits: {
    vobiz_lines: number;
    platform_cap: number;
    sarvam_calls: number | null;
    usable_calls: number;
    reserved_for_inbound: number;
    outbound_lines: number;
  };
  bottleneck: 'vobiz' | 'sarvam' | 'platform';
  live: { calls: number; free_inbound: number; free_outbound: number; outbound_paused_s: number };
  llm_requests_per_call_minute: { assumed: number; measured: number | null };
  today: CapacityTotals;
  last_30_days: CapacityTotals;
  hints: { level: 'warning' | 'info'; text: string }[];
}

export const financeService = {
  summary: (period: FinancePeriod) => request<FinanceSummary>(`/finance/summary?period=${period}`),
  capacity: () => request<CapacityReport>('/finance/capacity'),
};

/** ₹ amount, whole rupees once it's large enough that paise don't matter. */
export const rupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2 })}`;
