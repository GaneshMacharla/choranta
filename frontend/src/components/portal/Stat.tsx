import React from 'react';

/** Dashboard stat tile: label, big value, optional hint. */
export const Stat: React.FC<{ icon: React.ReactNode; label: string; value: string; hint?: string }> = ({ icon, label, value, hint }) => (
  <div className="rounded-xl border border-[#1b2030] bg-[#0c0e14] p-4">
    <div className="flex items-center justify-between text-xs text-slate-400">
      <span>{label}</span>
      {icon}
    </div>
    <p className="mt-2 font-mono text-2xl font-bold text-slate-100">{value}</p>
    {hint && <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
  </div>
);
