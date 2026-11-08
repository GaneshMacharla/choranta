import { request } from './api';
import { Call, CallDetail } from './telephony';
import { AvailableNumber, NumberPrice, NumberType, PaymentOrder, Subscription } from './plans';
import { CreditPack } from './pricing';

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
  /** Calls at a time the balance covers (each live call holds a full-length call's credits); null = no limit */
  max_concurrent_calls: number | null;
  live_calls: number;
  /** False until the company is GST-registered: no GST is charged and payments get a receipt */
  gst_registered: boolean;
  /** False while Choranta isn't issuing invoices or receipts: those screens are hidden */
  invoices_enabled: boolean;
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

export type CallInterest = 'interested' | 'callback' | 'not_interested' | 'do_not_call' | 'unclear';

export interface HotLead {
  /** Campaign recipient id, or the call id for an inbound caller */
  recipient_id: string;
  kind: 'campaign' | 'inbound';
  reason: string | null;
  name: string | null;
  phone: string;
  campaign_id: string | null;
  campaign_name: string;
  campaign_kind: 'BULK' | 'TRIGGER' | null;
  interest: CallInterest;
  summary: string | null;
  callback_time: string | null;
  call_id: string | null;
  called_at: string;
}

export interface OutboundInsights {
  days: number;
  has_outbound: boolean;
  funnel: {
    called: number;
    answered: number;
    interested: number;
    qualified: number;
    callbacks: number;
    not_interested: number;
    do_not_call: number;
    answer_rate: number | null;
    avg_talk_seconds: number | null;
    minutes: number;
  };
  hot_leads: HotLead[];
  hot_leads_total: number;
  instant: {
    leads: number;
    reached: number;
    interested: number;
    median_seconds_to_call: number | null;
    called_within_60s_pct: number | null;
    queued_for_hours: number;
  } | null;
  top_answers: Record<string, Record<string, number>>;
  best_hours: Array<{ hour: number; attempts: number; answered: number; answer_rate: number | null }>;
  campaigns: Array<{
    id: string;
    name: string;
    kind: 'BULK' | 'TRIGGER';
    status: string;
    called: number;
    answered: number;
    answer_rate: number | null;
    interested: number;
    minutes: number;
  }>;
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
  /** Present on the single-number endpoint: the activation test call's progress */
  test_call_id?: string | null;
  test_call_status?: string | null;
  test_result?: string | null;
  activated_by?: string | null;
}

export type VerificationStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'VERIFIED';
export type KycType = 'INDIVIDUAL' | 'BUSINESS';
export type KycCheckKind = 'pan' | 'gst' | 'cin' | 'aadhaar';

export interface KycCheck {
  status: 'verified' | 'failed' | 'pending';
  label: string;
  value?: string | null;
  name?: string | null;
  message?: string | null;
  checked_at?: string;
}

/** Business verification (KYC): Vobiz checks each document on the client's own sub-account. */
export interface BusinessVerification {
  status: VerificationStatus;
  client_id?: string | null;
  client_name?: string | null;
  client_code?: string | null;
  kyc_type?: KycType;
  email?: string;
  calls_blocked?: boolean;
  checks?: Partial<Record<KycCheckKind, KycCheck>>;
  verified_at?: string | null;
  updated_at?: string;
  created_at?: string;
  kyc_types: Record<KycType, { label: string; hint: string }>;
  mock?: boolean;
  test_inputs?: boolean; // Vobiz's KYC test mode: magic values like TESTSUCCESS0001 instead of real numbers
}

export interface CinMatch {
  cin: string;
  company_name: string;
  status: string;
}

export interface PaymentInstructions {
  upi_id: string | null;
  bank_details: string | null;
  gst_rate_percent: number;
  gst_registered: boolean;
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
  insights: (days: number) => request<OutboundInsights>(`/portal/insights?days=${days}`),
  markFollowedUp: (recipientId: string) =>
    request<void>(`/portal/insights/hot-leads/${recipientId}/followed-up`, { method: 'POST' }),
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
      gst_registered: boolean;
      payg_only: boolean;
      /** Typical credits one call minute costs (recent average) */
      avg_credits_per_minute: number;
      credit_packs: CreditPack[];
    }>('/portal/subscription'),
  numbers: () =>
    request<{
      numbers: PortalNumber[];
      pricing: NumberPrice[];
      grace_days: number;
      verification_status: VerificationStatus;
      contact_phone: string | null;
    }>('/portal/numbers'),
  numberDetail: (id: string) => request<PortalNumber>(`/portal/numbers/${id}`),
  testNumber: (id: string, phone: string) =>
    request<PortalNumber>(`/portal/numbers/${id}/test`, { method: 'POST', body: JSON.stringify({ phone }) }),
  activateNumber: (id: string) => request<PortalNumber>(`/portal/numbers/${id}/activate`, { method: 'POST' }),
  verification: () => request<BusinessVerification>('/portal/verification'),
  startVerification: (kyc_type: KycType, email: string) =>
    request<BusinessVerification>('/portal/verification/start', { method: 'POST', body: JSON.stringify({ kyc_type, email }) }),
  verifyPan: (pan: string) =>
    request<BusinessVerification>('/portal/verification/pan', { method: 'POST', body: JSON.stringify({ pan }) }),
  verifyGst: (gstin: string) =>
    request<BusinessVerification>('/portal/verification/gst', { method: 'POST', body: JSON.stringify({ gstin }) }),
  searchCin: (company_name: string) =>
    request<{ matches: CinMatch[] }>('/portal/verification/cin/search', { method: 'POST', body: JSON.stringify({ company_name }) }),
  confirmCin: (company_name: string, cin: string) =>
    request<BusinessVerification>('/portal/verification/cin', { method: 'POST', body: JSON.stringify({ company_name, cin }) }),
  startAadhaar: (return_url: string) =>
    request<{ auth_url: string }>('/portal/verification/aadhaar/start', { method: 'POST', body: JSON.stringify({ return_url }) }),
  completeAadhaar: (state: string) =>
    request<BusinessVerification>('/portal/verification/aadhaar/complete', { method: 'POST', body: JSON.stringify({ state }) }),
  availableNumbers: (numberType: NumberType, region?: string) =>
    request<AvailableNumber[]>(`/portal/numbers/available?number_type=${numberType}${region ? `&region=${encodeURIComponent(region)}` : ''}`),
  buyNumber: (phone_number: string, number_type: NumberType) =>
    request<PortalNumber>('/portal/numbers', { method: 'POST', body: JSON.stringify({ phone_number, number_type }) }),
  assignNumber: (id: string, agent_id: string | null) =>
    request<PortalNumber>(`/portal/numbers/${id}`, { method: 'PATCH', body: JSON.stringify({ agent_id }) }),
  releaseNumber: (id: string, now = false) => request<PortalNumber>(`/portal/numbers/${id}${now ? '?now=true' : ''}`, { method: 'DELETE' }),
  keepNumber: (id: string) => request<PortalNumber>(`/portal/numbers/${id}/keep`, { method: 'POST' }),
  agents: () => request<Array<{ id: string; name: string; role: string; published: boolean; live: boolean }>>('/portal/agents'),
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
