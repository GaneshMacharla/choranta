import { request } from './api';
import { downloadAuthed, InvoiceSummary, Wallet } from './portal';

export interface BillingProfile {
  legal_name: string;
  gstin: string | null;
  address: string | null;
  state_code: string | null;
  billing_email: string | null;
}

export interface GstSplit {
  taxable_inr: number;
  cgst_inr: number;
  sgst_inr: number;
  igst_inr: number;
  total_inr: number;
  place_of_supply: string;
  intra_state: boolean;
  /** False until the company is GST-registered: no GST, the whole amount becomes credits */
  gst_registered: boolean;
}

export interface ClientLogin {
  id: string;
  email: string;
  name: string;
  status: string;
}

const c = (clientId: string) => `/clients/${clientId}`;

export const billingService = {
  profile: (clientId: string) => request<BillingProfile>(`${c(clientId)}/billing-profile`),
  saveProfile: (clientId: string, data: Partial<BillingProfile>) =>
    request<BillingProfile>(`${c(clientId)}/billing-profile`, { method: 'PUT', body: JSON.stringify(data) }),
  wallet: (clientId: string) => request<Wallet>(`${c(clientId)}/wallet`),
  previewPayment: (clientId: string, amount_received_inr: number) =>
    request<GstSplit>(`${c(clientId)}/wallet/payments/preview`, { method: 'POST', body: JSON.stringify({ amount_received_inr }) }),
  recordPayment: (clientId: string, amount_received_inr: number, reference: string) =>
    request<GstSplit & { invoice_number: string; balance_inr: number }>(`${c(clientId)}/wallet/payments`, {
      method: 'POST',
      body: JSON.stringify({ amount_received_inr, reference: reference || null }),
    }),
  adjust: (clientId: string, amount_inr: number, note: string) =>
    request<Wallet>(`${c(clientId)}/wallet/adjustments`, { method: 'POST', body: JSON.stringify({ amount_inr, note }) }),
  invoices: (clientId: string) => request<InvoiceSummary[]>(`${c(clientId)}/invoices`),
  downloadInvoice: (invoice: InvoiceSummary) => downloadAuthed(`/invoices/${invoice.id}/pdf`, `${invoice.number.replace(/\//g, '-')}.pdf`),
  logins: (clientId: string) => request<ClientLogin[]>(`${c(clientId)}/users`),
  inviteLogin: (clientId: string, email: string, name: string) =>
    request<ClientLogin>(`${c(clientId)}/users`, { method: 'POST', body: JSON.stringify({ email, name: name || null }) }),
  removeLogin: (clientId: string, userId: string) => request<void>(`${c(clientId)}/users/${userId}`, { method: 'DELETE' }),
};
