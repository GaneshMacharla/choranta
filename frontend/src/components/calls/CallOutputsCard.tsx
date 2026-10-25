import React from 'react';
import { ClipboardList } from 'lucide-react';
import { QualificationBadge } from './QualificationBadge';

export const formatOutputValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
};

const label = (name: string) => name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

/** What the agent collected on a call: its output variables and a one-line summary, extracted after the call. */
export const CallOutputsCard: React.FC<{ metadata?: Record<string, any> | null }> = ({ metadata }) => {
  const status = metadata?.outputs_status as string | undefined;
  const outputs = (metadata?.outputs || {}) as Record<string, unknown>;
  const summary = metadata?.summary as string | undefined;
  if (!status) return null;

  return (
    <div className="space-y-2 rounded border border-[#143c49] bg-[#06141a]/60 p-3 text-xs">
      <span className="flex items-center gap-1.5 font-semibold text-[#00df8f]">
        <ClipboardList className="h-4 w-4" /> Collected on this call
      </span>
      {status === 'pending' && <p className="text-slate-400">Reading the transcript…</p>}
      {status === 'failed' && <p className="text-amber-400">Couldn't extract details from this call.</p>}
      <QualificationBadge qualification={metadata?.qualification} />
      {summary && <p className="text-slate-300">{summary}</p>}
      {Object.keys(outputs).length > 0 && (
        <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 gap-y-1">
          {Object.entries(outputs).map(([name, value]) => (
            <React.Fragment key={name}>
              <dt className="text-slate-500">{label(name)}</dt>
              <dd className={value === null || value === undefined ? 'text-slate-600' : 'text-slate-200'}>{formatOutputValue(value)}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
    </div>
  );
};
