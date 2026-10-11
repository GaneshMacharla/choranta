import { request } from './api';
import { Call, CallDetail } from './telephony';

export interface WalletTransaction {
  id: string;
  type: 'CREDIT' | 'DEBIT' | 'ADJUSTMENT';
  amount_inr: number;
  balance_after_inr: number;
  call_id: string | null;
  invoice_id: string | null;
  reference: string | null;
  note: string | null;
  created_at: string;
}

export interface Wallet {
  client_id: string;
  balance_inr: number;
  low_balance_threshold_inr: number;
  low_balance: boolean;
  calls_blocked: boolean;
  transactions: WalletTransaction[];
}

export interface InvoiceSummary {
  id: string;
  number: string;
  issue_date: string;
  taxable_inr: number;
  cgst_inr: number;
  sgst_inr: number;
  igst_inr: number;
  total_inr: number;
  payment_reference: string | null;
}

export interface PortalSummary {
  client_name: string;
  user_name: string;
  wallet: Pick<Wallet, 'balance_inr' | 'low_balance_threshold_inr' | 'low_balance' | 'calls_blocked'>;
  month: { calls: number; minutes: number; spend_inr: number };
  daily: Array<{ date: string; calls: number; minutes: number; spend_inr: number }>;
}

export interface PaymentInstructions {
  upi_id: string | null;
  bank_details: string | null;
  gst_rate_percent: number;
  note: string;
}

/** Authenticated binary download (PDF, audio) that browsers can't fetch with an Authorization header otherwise. */
export async function fetchAuthedBlob(path: string): Promise<Blob> {
  const token = localStorage.getItem('choranta_token');
  const response = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json())?.detail || detail;
    } catch {
      // non-JSON body
    }
    throw new Error(detail || 'Download failed.');
  }
  return response.blob();
}

export async function downloadAuthed(path: string, filename: string): Promise<void> {
  const blob = await fetchAuthedBlob(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const portalService = {
  summary: () => request<PortalSummary>('/portal/summary'),
  calls: (limit = 100) => request<Call[]>(`/portal/calls?limit=${limit}`),
  call: (id: string) => request<CallDetail>(`/portal/calls/${id}`),
  recording: (id: string) => fetchAuthedBlob(`/portal/calls/${id}/recording`),
  wallet: () => request<Wallet>('/portal/wallet'),
  invoices: () => request<InvoiceSummary[]>('/portal/invoices'),
  downloadInvoice: (invoice: InvoiceSummary) =>
    downloadAuthed(`/portal/invoices/${invoice.id}/pdf`, `${invoice.number.replace(/\//g, '-')}.pdf`),
  properties: () =>
    request<{
      count: number;
      last_synced_at: string | null;
      properties: Array<{ id: string; project_name: string; location: string; bhk: number; price_display: string; property_type: string; status: string }>;
    }>('/portal/properties'),
  paymentInstructions: () => request<PaymentInstructions>('/portal/payment-instructions'),
};

export const inr = (value: number, digits = 2) =>
  `₹${(value || 0).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
