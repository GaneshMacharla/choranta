import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle, Clock, FileCheck2, ShieldCheck, Upload } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { BusinessVerification, portalService } from '../../services/portal';

const FIELDS: Array<{ key: string; label: string; placeholder: string; hint?: string; required?: boolean; upper?: boolean; multiline?: boolean }> = [
  { key: 'legal_name', label: 'Registered business name', placeholder: 'As on your PAN / GST certificate', required: true },
  { key: 'pan', label: 'Business PAN', placeholder: 'ABCDE1234F', required: true, upper: true },
  { key: 'gstin', label: 'GSTIN (if registered)', placeholder: '36ABCDE1234F1Z5', upper: true },
  { key: 'cin', label: 'CIN / LLPIN (companies and LLPs)', placeholder: 'U12345TG2020PTC123456', upper: true },
  { key: 'registered_address', label: 'Registered address', placeholder: 'Full address with PIN code', required: true, multiline: true },
  { key: 'signatory_name', label: 'Authorised signatory', placeholder: 'Owner, director or partner', required: true },
  { key: 'signatory_designation', label: 'Their designation', placeholder: 'e.g. Director, Proprietor' },
  { key: 'signatory_phone', label: 'Their phone', placeholder: '+91 98765 43210' },
];

const MAX_MB = 5;

/** Client portal: one-time business verification (KYC) before buying phone numbers. */
export const PortalVerificationPage: React.FC = () => {
  const [current, setCurrent] = useState<BusinessVerification | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    portalService
      .verification()
      .then((v) => {
        setCurrent(v);
        setValues(Object.fromEntries(FIELDS.map((f) => [f.key, String((v as any)[f.key] || '')])));
      })
      .catch((e) => setLoadError(e.message || 'Could not load your verification.'));

  useEffect(() => {
    load();
  }, []);

  if (loadError) return <ErrorState message={loadError} onRetry={load} />;
  if (!current) return <LoadingState message="Loading..." />;

  const editable = current.status === 'NOT_STARTED' || current.status === 'REJECTED';
  const uploaded = new Set((current.documents || []).map((d) => d.kind));
  const needsGst = !!values.gstin?.trim();
  const requiredDocs = ['pan_card', 'address_proof', 'signatory_id', ...(needsGst ? ['gst_certificate'] : [])];
  const missingDocs = requiredDocs.filter((k) => !files[k] && !uploaded.has(k));
  const missingFields = FIELDS.filter((f) => f.required && !values[f.key]?.trim());
  const ready = missingDocs.length === 0 && missingFields.length === 0;

  const pickFile = (kind: string, file: File | null) => {
    setError(null);
    if (file && file.size > MAX_MB * 1024 * 1024) {
      setError(`${current.document_kinds[kind]}: files must be ${MAX_MB} MB or smaller.`);
      return;
    }
    setFiles((prev) => ({ ...prev, [kind]: file }));
  };

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const form = new FormData();
      FIELDS.forEach((f) => form.append(f.key, (values[f.key] || '').trim()));
      Object.entries(files).forEach(([kind, file]) => file && form.append(kind, file, file.name));
      const saved = await portalService.submitVerification(form);
      setCurrent(saved);
      setFiles({});
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e: any) {
      setError(e.message || 'Could not submit. Please check the details and try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <ShieldCheck className="h-5 w-5 text-[#00df8f]" /> Verify your business
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          A one-time step before you get phone numbers. Indian telecom rules require every business number to be linked to a verified business.
        </p>
      </div>

      {current.status === 'APPROVED' && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-800/60 bg-emerald-950/30 p-4 text-sm text-emerald-200">
          <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Your business is verified. <Link to="/portal/numbers" className="font-semibold underline">Get a phone number</Link>
          </span>
        </div>
      )}
      {current.status === 'PENDING' && (
        <div className="flex items-start gap-2 rounded-lg border border-sky-800/60 bg-sky-950/30 p-4 text-sm text-sky-100">
          <Clock className="mt-0.5 h-4 w-4 shrink-0" />
          <span>Thanks! We're reviewing your details, usually within 1–3 business days. We'll notify you here when it's done.</span>
        </div>
      )}
      {current.status === 'REJECTED' && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/30 p-4 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            <strong>Please fix this and resubmit:</strong> {current.admin_note}
          </span>
        </div>
      )}

      <Card title="Business details">
        <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          {FIELDS.map((f) => (
            <label key={f.key} className={`space-y-1 ${f.multiline ? 'sm:col-span-2' : ''}`}>
              <span className="block text-xs font-medium text-slate-300">
                {f.label} {f.required && <span className="text-rose-400">*</span>}
              </span>
              {f.multiline ? (
                <textarea
                  rows={2}
                  disabled={!editable}
                  className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100 disabled:opacity-70"
                  placeholder={f.placeholder}
                  value={values[f.key] || ''}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                />
              ) : (
                <input
                  disabled={!editable}
                  className={`w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100 disabled:opacity-70 ${f.upper ? 'font-mono uppercase' : ''}`}
                  placeholder={f.placeholder}
                  value={values[f.key] || ''}
                  onChange={(e) => setValues({ ...values, [f.key]: f.upper ? e.target.value.toUpperCase() : e.target.value })}
                />
              )}
            </label>
          ))}
        </div>
      </Card>

      <Card title="Documents" subtitle={`PDF, JPG or PNG, up to ${MAX_MB} MB each. Clear, full-page scans avoid delays.`}>
        <div className="space-y-3 text-sm">
          {Object.entries(current.document_kinds).map(([kind, label]) => {
            const required = requiredDocs.includes(kind);
            const doc = (current.documents || []).find((d) => d.kind === kind);
            const picked = files[kind];
            return (
              <div key={kind} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#143c49] bg-[#06141a] p-3">
                <div className="min-w-0">
                  <div className="text-slate-200">
                    {label} {required && <span className="text-rose-400">*</span>}
                    {!required && kind === 'gst_certificate' && <span className="text-xs text-slate-500"> (needed if you entered a GSTIN)</span>}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                    {picked ? (
                      <><Upload className="h-3 w-3" /> {picked.name} (will be uploaded)</>
                    ) : doc ? (
                      <><FileCheck2 className="h-3 w-3 text-[#00df8f]" /> {doc.filename}</>
                    ) : (
                      'Not uploaded yet'
                    )}
                  </div>
                </div>
                {editable && (
                  <label className="cursor-pointer rounded-md border border-[#1e4e5e] px-3 py-1.5 text-xs text-slate-200 hover:border-[#00df8f]">
                    {doc || picked ? 'Replace' : 'Choose file'}
                    <input type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" className="hidden"
                      onChange={(e) => pickFile(kind, e.target.files?.[0] || null)} />
                  </label>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {editable && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          {!ready && (
            <span className="text-xs text-slate-500">
              {missingFields.length ? `Fill in: ${missingFields.map((f) => f.label).join(', ')}. ` : ''}
              {missingDocs.length ? `Upload: ${missingDocs.map((k) => current.document_kinds[k]).join('; ')}.` : ''}
            </span>
          )}
          <Button variant="primary" leftIcon={<ShieldCheck className="h-4 w-4" />} disabled={!ready || saving} isLoading={saving} onClick={submit}>
            {current.status === 'REJECTED' ? 'Resubmit for review' : 'Submit for review'}
          </Button>
        </div>
      )}
    </div>
  );
};
