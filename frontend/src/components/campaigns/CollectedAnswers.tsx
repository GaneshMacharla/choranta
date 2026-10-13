import React from 'react';

/** Bars of the most common answers per collected variable: {variable: {value: count}}. */
export const CollectedAnswers: React.FC<{ collected: Record<string, Record<string, number>>; columns?: string }> = ({
  collected,
  columns = 'md:grid-cols-2 xl:grid-cols-3',
}) => (
  <div className={`grid grid-cols-1 gap-4 ${columns}`}>
    {Object.entries(collected).map(([name, counts]) => {
      const max = Math.max(...Object.values(counts));
      return (
        <div key={name} className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">{name.replace(/_/g, ' ')}</div>
          {Object.entries(counts).map(([value, count]) => (
            <div key={value} className="flex items-center gap-2 text-xs">
              <span className="w-28 shrink-0 truncate text-slate-300" title={value}>
                {value}
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#143c49]">
                <span className="block h-full bg-[#00df8f]" style={{ width: `${(count / max) * 100}%` }} />
              </span>
              <span className="w-8 text-right text-slate-400">{count}</span>
            </div>
          ))}
        </div>
      );
    })}
  </div>
);
