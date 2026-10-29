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

export const financeService = {
  summary: (period: FinancePeriod) => request<FinanceSummary>(`/finance/summary?period=${period}`),
};

/** ₹ amount, whole rupees once it's large enough that paise don't matter. */
export const rupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2 })}`;
