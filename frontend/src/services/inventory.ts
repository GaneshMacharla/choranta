import { request } from './api';

export type InventorySourceType = 'GOOGLE_SHEET' | 'API';

export interface InventorySource {
  id: string;
  client_id: string;
  name: string;
  type: InventorySourceType;
  config: { sheet_url?: string; url?: string; headers?: Record<string, string>; items_path?: string };
  field_mapping: Record<string, string>;
  sync_interval_minutes: number;
  enabled: boolean;
  last_synced_at: string | null;
  last_status: 'OK' | 'ERROR' | null;
  last_error: string | null;
  last_result: { rows?: number; added?: number; updated?: number; unavailable?: number; skipped?: number };
  active_properties: number;
}

export interface InventorySourceInput {
  name: string;
  type: InventorySourceType;
  config: InventorySource['config'];
  field_mapping?: Record<string, string>;
  sync_interval_minutes?: number;
  enabled?: boolean;
}

export interface InventoryPreview {
  columns: string[];
  mapping: Record<string, string>;
  detected_mapping: Record<string, string>;
  total_rows: number;
  rows: Array<{ row: Record<string, any>; property: Record<string, any> | null; skipped_reason: string | null }>;
}

export interface InventoryProperty {
  id: string;
  project_name: string;
  location: string;
  bhk: number;
  price: number;
  price_display: string;
  property_type: string;
  status: string;
  details: Record<string, any>;
  last_synced_at: string | null;
}

const base = (clientId: string) => `/clients/${clientId}/inventory-sources`;

export const inventoryService = {
  list: (clientId: string) => request<InventorySource[]>(base(clientId)),
  create: (clientId: string, data: InventorySourceInput) =>
    request<InventorySource>(base(clientId), { method: 'POST', body: JSON.stringify(data) }),
  update: (clientId: string, id: string, data: Partial<InventorySourceInput>) =>
    request<InventorySource>(`${base(clientId)}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  remove: (clientId: string, id: string) => request<void>(`${base(clientId)}/${id}`, { method: 'DELETE' }),
  preview: (clientId: string, id: string) => request<InventoryPreview>(`${base(clientId)}/${id}/preview`, { method: 'POST' }),
  sync: (clientId: string, id: string) => request<InventorySource>(`${base(clientId)}/${id}/sync`, { method: 'POST' }),
  properties: (clientId: string) =>
    request<{ count: number; last_synced_at: string | null; properties: InventoryProperty[] }>(`/clients/${clientId}/properties`),
};
