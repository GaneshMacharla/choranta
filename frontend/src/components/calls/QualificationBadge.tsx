import React from 'react';
import { Qualification } from '../../services/qualification';

const STYLE: Record<Qualification['status'], string> = {
  qualified: 'bg-[#00df8f]/15 text-[#00df8f]',
  not_qualified: 'bg-slate-500/15 text-slate-300',
  unknown: 'bg-amber-500/15 text-amber-300',
};

const LABEL: Record<Qualification['status'], string> = {
  qualified: 'Qualified lead',
  not_qualified: 'Not qualified',
  unknown: "Can't tell yet",
};

const SOURCE: Record<Qualification['source'], string> = {
  rules: 'your rules',
  ai: 'AI check',
  interest: "caller's interest",
};

/** Whether the caller is a qualified lead, and why. */
export const QualificationBadge: React.FC<{ qualification?: Qualification | null }> = ({ qualification }) => {
  if (!qualification?.status) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${STYLE[qualification.status]}`}>{LABEL[qualification.status]}</span>
      {qualification.reason && <span className="text-slate-300">{qualification.reason}</span>}
      <span className="text-[10px] text-slate-500">({SOURCE[qualification.source] || qualification.source})</span>
    </div>
  );
};
