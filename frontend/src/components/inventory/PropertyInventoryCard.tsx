import React, { useEffect, useState } from 'react';
import { Building, RefreshCw, Plus, Eye, Trash2, AlertTriangle, CheckCircle2, Sheet, Webhook } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import {
  inventoryService,
  InventoryPreview,
  InventoryProperty,
  InventorySource,
  InventorySourceType,
} from '../../services/inventory';

const FIELDS: Array<{ key: string; label: string; required?: boolean }> = [
  { key: 'project_name', label: 'Project', required: true },
  { key: 'location', label: 'Location', required: true },
  { key: 'price', label: 'Price', required: true },
  { key: 'bhk', label: 'BHK' },
  { key: 'status', label: 'Status' },
  { key: 'property_type', label: 'Type' },
  { key: 'amenities', label: 'Amenities' },
  { key: 'external_id', label: 'Unique ID' },
];

const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100';

const timeAgo = (iso: string | null) => {
  if (!iso) return 'never';
  const minutes = Math.round((Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.round(minutes / 60)} h ago`;
};

/**
 * Client's property inventory, kept in sync from a Google Sheet or CRM/API so the agent
 * always quotes current prices and availability. Admins manage sources; operators view.
 */
export const PropertyInventoryCard: React.FC<{ clientId: string }> = ({ clientId }) => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [sources, setSources] = useState<InventorySource[]>([]);
  const [properties, setProperties] = useState<InventoryProperty[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Add-source form
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [type, setType] = useState<InventorySourceType>('GOOGLE_SHEET');
  const [name, setName] = useState('Property inventory');
  const [sheetUrl, setSheetUrl] = useState('');
  const [apiUrl, setApiUrl] = useState('');
  const [authHeader, setAuthHeader] = useState('');
  const [itemsPath, setItemsPath] = useState('');
  const [interval, setInterval] = useState(15);

  // Preview / mapping
  const [previewFor, setPreviewFor] = useState<InventorySource | null>(null);
  const [preview, setPreview] = useState<InventoryPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [showInventory, setShowInventory] = useState(false);

  const load = async () => {
    try {
      const [srcs, props] = await Promise.all([inventoryService.list(clientId), inventoryService.properties(clientId)]);
      setSources(srcs);
      setProperties(props.properties);
    } catch (err: any) {
      setError(err.message || 'Could not load inventory.');
    }
  };

  useEffect(() => {
    load();
  }, [clientId]);

  const run = async (key: string, action: () => Promise<any>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      await load();
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  const addSource = () =>
    run('add', async () => {
      const headers: Record<string, string> = authHeader.trim() ? { Authorization: authHeader.trim() } : {};
      const config: InventorySource['config'] =
        type === 'GOOGLE_SHEET'
          ? { sheet_url: sheetUrl.trim() }
          : {
              url: apiUrl.trim(),
              items_path: itemsPath.trim(),
              headers,
            };
      const created = await inventoryService.create(clientId, { name, type, config, sync_interval_minutes: interval });
      setIsAddOpen(false);
      await openPreview(created);
    });

  const openPreview = async (source: InventorySource) => {
    setPreviewFor(source);
    setPreview(null);
    setError(null);
    try {
      const data = await inventoryService.preview(clientId, source.id);
      setPreview(data);
      setMapping(Object.keys(source.field_mapping || {}).length ? source.field_mapping : data.detected_mapping);
    } catch (err: any) {
      setError(err.message || 'Could not read the source.');
    }
  };

  const saveMappingAndSync = () =>
    run('sync-' + previewFor!.id, async () => {
      await inventoryService.update(clientId, previewFor!.id, { field_mapping: mapping });
      await inventoryService.sync(clientId, previewFor!.id);
      setPreviewFor(null);
    });

  const activeCount = properties.filter((p) => p.status !== 'UNAVAILABLE').length;

  return (
    <Card
      title="Property Inventory"
      subtitle="Synced automatically from the client's Google Sheet or CRM, so the agent always quotes current prices"
    >
      <div className="space-y-4 text-xs">
        {error && (
          <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-slate-300">
            <Building className="mr-1 inline h-3.5 w-3.5 text-[#00df8f]" />
            {activeCount} active properties
            {properties.length > 0 && (
              <button className="ml-2 text-[#00df8f] hover:underline" onClick={() => setShowInventory((v) => !v)}>
                {showInventory ? 'Hide' : 'View'}
              </button>
            )}
          </span>
          {isAdmin && (
            <Button size="sm" variant="primary" onClick={() => setIsAddOpen(true)}>
              <Plus className="mr-1 h-3.5 w-3.5" /> Connect source
            </Button>
          )}
        </div>

        {sources.length === 0 ? (
          <p className="rounded border border-dashed border-[#232736] p-4 text-center text-slate-500">
            No inventory source yet. Connect the client's Google Sheet or CRM API, and the agent will search it live.
          </p>
        ) : (
          sources.map((s) => (
            <div key={s.id} className="space-y-2 rounded border border-[#1b2030] bg-[#0d101a] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-slate-200">
                  {s.type === 'GOOGLE_SHEET' ? (
                    <Sheet className="h-4 w-4 text-emerald-400" />
                  ) : (
                    <Webhook className="h-4 w-4 text-indigo-400" />
                  )}
                  <span className="font-medium">{s.name}</span>
                  {s.last_status === 'OK' && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
                  {s.last_status === 'ERROR' && <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />}
                </div>
                {isAdmin && (
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="secondary" onClick={() => openPreview(s)}>
                      <Eye className="mr-1 h-3.5 w-3.5" /> Mapping
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      isLoading={busy === 'sync-' + s.id}
                      onClick={() => run('sync-' + s.id, () => inventoryService.sync(clientId, s.id))}
                    >
                      <RefreshCw className="mr-1 h-3.5 w-3.5" /> Sync now
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      isLoading={busy === 'del-' + s.id}
                      onClick={() => run('del-' + s.id, () => inventoryService.remove(clientId, s.id))}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
              <p className="text-slate-500">
                Every {s.sync_interval_minutes} min · last synced {timeAgo(s.last_synced_at)} · {s.active_properties} properties
                {s.last_result?.rows != null &&
                  ` · last run: ${s.last_result.added ?? 0} added, ${s.last_result.updated ?? 0} updated, ${s.last_result.unavailable ?? 0} no longer listed`}
              </p>
              {s.last_status === 'ERROR' && s.last_error && <p className="text-rose-300">{s.last_error}</p>}
            </div>
          ))
        )}

        {showInventory && (
          <div className="max-h-64 overflow-auto rounded border border-[#1b2030]">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-[#0c0d14] text-slate-500">
                <tr>
                  <th className="px-2 py-1.5">Project</th>
                  <th className="px-2 py-1.5">Location</th>
                  <th className="px-2 py-1.5">BHK</th>
                  <th className="px-2 py-1.5">Price</th>
                  <th className="px-2 py-1.5">Status</th>
                </tr>
              </thead>
              <tbody>
                {properties.map((p) => (
                  <tr key={p.id} className="border-t border-[#1b2030] text-slate-300">
                    <td className="px-2 py-1.5">{p.project_name}</td>
                    <td className="px-2 py-1.5">{p.location}</td>
                    <td className="px-2 py-1.5">{p.bhk || '—'}</td>
                    <td className="px-2 py-1.5 font-mono">{p.price_display}</td>
                    <td className="px-2 py-1.5">{p.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Connect a source */}
      <Modal
        isOpen={isAddOpen}
        onClose={() => setIsAddOpen(false)}
        title="Connect inventory source"
        description="Choranta re-reads it on a schedule; nobody has to update the agent by hand."
      >
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-2 gap-2">
            {(['GOOGLE_SHEET', 'API'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setType(t)}
                className={`rounded border p-2.5 text-left ${type === t ? 'border-[#00df8f] bg-[#00df8f]/10 text-slate-100' : 'border-[#232736] text-slate-400'}`}
              >
                <span className="block font-semibold">{t === 'GOOGLE_SHEET' ? 'Google Sheet' : 'CRM / website API'}</span>
                <span className="text-[11px]">{t === 'GOOGLE_SHEET' ? 'Paste the sheet link' : 'JSON endpoint with auth'}</span>
              </button>
            ))}
          </div>
          <label className="block space-y-1">
            <span className="text-slate-300">Name</span>
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          {type === 'GOOGLE_SHEET' ? (
            <label className="block space-y-1">
              <span className="text-slate-300">Google Sheet link</span>
              <input
                className={inputClass}
                placeholder="https://docs.google.com/spreadsheets/d/..."
                value={sheetUrl}
                onChange={(e) => setSheetUrl(e.target.value)}
              />
              <span className="block text-[11px] text-slate-500">
                In Google Sheets: Share → General access → "Anyone with the link" → Viewer. Open the tab with the listings
                before copying the link.
              </span>
            </label>
          ) : (
            <>
              <label className="block space-y-1">
                <span className="text-slate-300">API URL (GET)</span>
                <input className={inputClass} placeholder="https://crm.example.com/api/listings" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} />
              </label>
              <label className="block space-y-1">
                <span className="text-slate-300">Authorization header (optional)</span>
                <input className={inputClass} placeholder="Bearer xxxxx" value={authHeader} onChange={(e) => setAuthHeader(e.target.value)} />
              </label>
              <label className="block space-y-1">
                <span className="text-slate-300">Path to the list in the JSON (optional)</span>
                <input className={inputClass} placeholder="data.properties" value={itemsPath} onChange={(e) => setItemsPath(e.target.value)} />
              </label>
            </>
          )}
          <label className="block space-y-1">
            <span className="text-slate-300">Sync every (minutes)</span>
            <input
              type="number"
              min={5}
              max={1440}
              className={inputClass}
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
            />
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setIsAddOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" isLoading={busy === 'add'} onClick={addSource}>
              Connect & preview
            </Button>
          </div>
        </div>
      </Modal>

      {/* Preview + column mapping */}
      <Modal
        isOpen={!!previewFor}
        onClose={() => setPreviewFor(null)}
        title="Check column mapping"
        description="Match the source's columns to property fields, then sync."
      >
        <div className="space-y-3 text-xs">
          {!preview ? (
            <p className="text-slate-400">{error ? error : 'Reading the source...'}</p>
          ) : (
            <>
              <p className="text-slate-400">{preview.total_rows} rows found.</p>
              <div className="grid grid-cols-2 gap-2">
                {FIELDS.map((f) => (
                  <label key={f.key} className="block space-y-1">
                    <span className="text-slate-300">
                      {f.label}
                      {f.required && <span className="text-rose-400"> *</span>}
                    </span>
                    <select
                      className={inputClass}
                      value={mapping[f.key] || ''}
                      onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value }))}
                    >
                      <option value="">— not in source —</option>
                      {preview.columns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <div className="max-h-40 overflow-auto rounded border border-[#1b2030]">
                <table className="w-full text-left text-[11px]">
                  <tbody>
                    {preview.rows.map((r, i) => (
                      <tr key={i} className="border-t border-[#1b2030] text-slate-300">
                        {r.property ? (
                          <td className="px-2 py-1">
                            {r.property.project_name} · {r.property.location} · {r.property.bhk || '—'} BHK ·{' '}
                            <span className="font-mono">{r.property.price_display}</span> · {r.property.status}
                          </td>
                        ) : (
                          <td className="px-2 py-1 text-amber-300">Skipped: {r.skipped_reason}</td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-slate-500">
                Preview uses the auto-detected mapping; saving applies your choices. Listings removed from the source are
                marked "no longer listed", never deleted.
              </p>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setPreviewFor(null)}>
                  Close
                </Button>
                <Button
                  variant="primary"
                  isLoading={busy === 'sync-' + previewFor?.id}
                  disabled={!mapping.project_name || !mapping.location || !mapping.price}
                  onClick={saveMappingAndSync}
                >
                  Save mapping & sync
                </Button>
              </div>
            </>
          )}
        </div>
      </Modal>
    </Card>
  );
};
