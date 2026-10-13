import { request } from './api';
import { Call, CallDetail } from './telephony';
import { AvailableNumber, CallUsage, NumberPrice, NumberType, PaymentOrder, Subscription } from './plans';

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
  calls_blocked_reason: string | null;
  subscription: Subscription | null;
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
  description: string;
}

export interface PortalSummary {
  client_name: string;
  user_name: string;
  wallet: Pick<Wallet, 'balance_inr' | 'low_balance_threshold_inr' | 'low_balance' | 'calls_blocked' | 'calls_blocked_reason'>;
  subscription: Subscription | null;
  numbers_past_due: Array<{ phone_number: string; monthly_rent_inr: number; grace_ends_at: string | null }>;
  month: { calls: number; minutes: number; spend_inr: number };
  daily: Array<{ date: string; calls: number; minutes: number; spend_inr: number }>;
}

export interface PortalNumber {
  id: string;
  phone_number: string;
  number_type: NumberType | null;
  status: string;
  agent_id: string | null;
  agent_name: string | null;
  created_at: string;
  monthly_rent_inr: number | null;
  rental_status: 'ACTIVE' | 'PAST_DUE' | 'RELEASED' | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  grace_ends_at: string | null;
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

export interface PortalNotification {
  id: string;
  kind: string;
  level: 'info' | 'success' | 'warning';
  title: string;
  body: string | null;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface NotificationList {
  unread: number;
  items: PortalNotification[];
}

export const portalService = {
  notifications: () => request<NotificationList>('/portal/notifications'),
  readAllNotifications: () => request<NotificationList>('/portal/notifications/read', { method: 'POST' }),
  readNotification: (id: string) => request<NotificationList>(`/portal/notifications/${id}/read`, { method: 'POST' }),
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
  subscription: () =>
    request<{
      subscription: Subscription | null;
      online_payments: boolean;
      simulated_payments?: boolean;
      grace_days: number;
      min_topup_inr: number;
      gst_rate_percent: number;
    }>('/portal/subscription'),
  usage: () => request<CallUsage[]>('/portal/usage'),
  numbers: () => request<{ numbers: PortalNumber[]; pricing: NumberPrice[]; grace_days: number }>('/portal/numbers'),
  availableNumbers: (numberType: NumberType, region?: string) =>
    request<AvailableNumber[]>(`/portal/numbers/available?number_type=${numberType}${region ? `&region=${encodeURIComponent(region)}` : ''}`),
  buyNumber: (phone_number: string, number_type: NumberType) =>
    request<PortalNumber>('/portal/numbers', { method: 'POST', body: JSON.stringify({ phone_number, number_type }) }),
  assignNumber: (id: string, agent_id: string | null) =>
    request<PortalNumber>(`/portal/numbers/${id}`, { method: 'PATCH', body: JSON.stringify({ agent_id }) }),
  releaseNumber: (id: string, now = false) => request<PortalNumber>(`/portal/numbers/${id}${now ? '?now=true' : ''}`, { method: 'DELETE' }),
  keepNumber: (id: string) => request<PortalNumber>(`/portal/numbers/${id}/keep`, { method: 'POST' }),
  agents: () => request<Array<{ id: string; name: string; role: string; published: boolean }>>('/portal/agents'),
  createOrder: (body: { purpose: 'SUBSCRIPTION' | 'WALLET_TOPUP'; plan_id?: string; amount_inr?: number }) =>
    request<PaymentOrder>('/portal/payments/orders', { method: 'POST', body: JSON.stringify(body) }),
  simulatePayment: (orderId: string) =>
    request<{ status: string; invoice_id: string | null; subscription: Subscription | null }>(
      `/portal/payments/orders/${orderId}/simulate`,
      { method: 'POST' }
    ),
  verifyPayment: (orderId: string, razorpay_payment_id: string, razorpay_signature: string) =>
    request<{ status: string; invoice_id: string | null; subscription: Subscription | null }>(
      `/portal/payments/orders/${orderId}/verify`,
      { method: 'POST', body: JSON.stringify({ razorpay_payment_id, razorpay_signature }) }
    ),
};

export const inr = (value: number, digits = 2) =>
  `₹${(value || 0).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
