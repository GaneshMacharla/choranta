import { ApiError, request } from './api';

/** Staff number management: Choranta's numbers at the carrier (Vobiz, or the simulated one in mock mode). */

export type InternalStatus = 'AVAILABLE' | 'ASSIGNED' | 'RELEASING' | 'RELEASED' | 'NEEDS_RECONCILIATION';
export type OperationStatus = 'PENDING' | 'SUCCEEDED' | 'FAILED' | 'UNCERTAIN' | 'NEEDS_RECONCILIATION' | 'RECOVERED';
export type NumberType = 'Landline' | 'Mobile' | 'TollFree';

export interface InventoryNumber {
  e164: string;
  country: string | null;
  region: string | null;
  number_type: NumberType | null;
  /** The carrier doesn't say; worked out from the prefix */
  number_type_derived: boolean;
  setup_fee: number | null;
  monthly_fee: number | null;
  currency: string | null;
  available: boolean;
  is_mock: boolean;
  /** Mock mode: the failure buying this number simulates */
  scenario: string | null;
}

export interface Paged<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number | null;
}

export interface InventoryPage extends Paged<InventoryNumber> {
  mock_mode: boolean;
}

export interface NumberAssignment {
  id: string;
  client_id: string;
  client_name: string | null;
  agent_id: string | null;
  agent_name: string | null;
  trunk_id: string | null;
  phone_number_id: string | null;
  status: 'ACTIVE' | 'ENDED';
  assigned_by: string | null;
  ended_by: string | null;
  end_reason: string | null;
  assigned_at: string;
  released_at: string | null;
}

export interface NumberOperation {
  id: string;
  operation_type: 'PURCHASE' | 'ASSIGN' | 'UNASSIGN' | 'RELEASE' | 'SYNC' | 'ATTACH_APP';
  operation_status: OperationStatus;
  e164: string | null;
  provider: string | null;
  provider_number_id: string | null;
  client_id: string | null;
  error_code: string | null;
  error_message: string | null;
  actor: string | null;
  is_mock: boolean;
  request: Record<string, any>;
  result: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface OwnedNumber {
  id: string;
  provider: string;
  provider_number_id: string | null;
  e164: string;
  country: string | null;
  region: string | null;
  number_type: NumberType | null;
  number_type_derived: boolean;
  capabilities: Record<string, boolean>;
  provider_status: string | null;
  internal_status: InternalStatus;
  monthly_cost: number | null;
  setup_cost: number | null;
  currency: string | null;
  application_id: string | null;
  trunk_id: string | null;
  subaccount_auth_id: string | null;
  is_mock: boolean;
  attention: string | null;
  purchased_at: string | null;
  last_synced_at: string | null;
  released_at: string | null;
  created_at: string;
  next_billing_date: string | null;
  aadhaar_verification_required: boolean;
  assignment: NumberAssignment | null;
  assignments?: NumberAssignment[];
  operations?: NumberOperation[];
  raw?: Record<string, any>;
}

export interface ProviderStatus {
  mock_mode: boolean;
  provider: string;
  configured: boolean;
  balance: number | null;
  currency: string;
  application_attached: boolean;
  error: string | null;
}

export interface OperationResult {
  operation: NumberOperation;
  number: OwnedNumber | null;
}

export interface SyncResult {
  seen: number;
  adopted: number;
  updated: number;
  missing: number;
  operations_settled: number;
  operation: NumberOperation;
}

const query = (params: Record<string, string | number | undefined | null>) => {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : '';
};

/** The operation a refused or failed request recorded, if it got that far. */
export const failedOperation = (err: unknown): NumberOperation | null =>
  err instanceof ApiError ? (err.body?.operation as NumberOperation) || null : null;

export const errorCode = (err: unknown): string | null => (err instanceof ApiError ? err.body?.code || null : null);

export const newIdempotencyKey = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;

export const numbersService = {
  providerStatus: () => request<ProviderStatus>('/numbers/provider-status'),

  inventory: (params: { country?: string; search?: string; number_type?: NumberType | ''; region?: string; page?: number; per_page?: number }) =>
    request<InventoryPage>(`/numbers/inventory${query(params)}`),

  list: (params: { status?: InternalStatus | ''; client_id?: string; search?: string; capability?: string; page?: number; per_page?: number }) =>
    request<Paged<OwnedNumber>>(`/numbers${query(params)}`),

  get: (id: string) => request<OwnedNumber>(`/numbers/${id}`),

  operations: (params: { status?: string; operation_type?: string; e164?: string; page?: number; per_page?: number }) =>
    request<Paged<NumberOperation>>(`/numbers/operations${query(params)}`),

  trunks: () => request<{ id: string; name: string }[]>('/numbers/trunks'),

  purchase: (body: {
    e164: string;
    idempotency_key: string;
    confirm: boolean;
    expected_monthly_cost: number | null;
    expected_setup_cost: number | null;
    currency: string | null;
  }) => request<OperationResult>('/numbers/purchase', { method: 'POST', body: JSON.stringify(body) }),

  assign: (id: string, body: { client_id: string; agent_id?: string | null; trunk_id?: string | null }) =>
    request<OwnedNumber>(`/numbers/${id}/assign`, { method: 'POST', body: JSON.stringify(body) }),

  unassign: (id: string) => request<OwnedNumber>(`/numbers/${id}/unassign`, { method: 'POST' }),

  release: (id: string, body: { confirm_e164: string; idempotency_key: string }) =>
    request<OperationResult>(`/numbers/${id}/release`, { method: 'POST', body: JSON.stringify(body) }),

  sync: () => request<SyncResult>('/numbers/sync', { method: 'POST' }),

  reconcile: (operationId: string) => request<OperationResult>(`/numbers/operations/${operationId}/reconcile`, { method: 'POST' }),
};

export const money = (amount: number | null | undefined, currency?: string | null) =>
  amount === null || amount === undefined
    ? 'Not given'
    : `${currency === 'INR' || !currency ? '₹' : `${currency} `}${amount.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;

export const STATUS_LABEL: Record<string, string> = {
  AVAILABLE: 'In pool',
  ASSIGNED: 'Assigned',
  RELEASING: 'Releasing',
  RELEASED: 'Released',
  NEEDS_RECONCILIATION: 'Needs attention',
  PENDING: 'Pending',
  SUCCEEDED: 'Succeeded',
  FAILED: 'Failed',
  UNCERTAIN: 'Uncertain',
  RECOVERED: 'Recovered',
};
