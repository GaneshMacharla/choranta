import React from 'react';
import { AGENT_NAME_SUGGESTIONS } from '../../constants/agentOptions';

interface NameSuggestionsProps {
  onPick: (name: string) => void;
  /** Names already in use (e.g. the client's other AI employees); they aren't suggested again */
  exclude?: string[];
  current?: string;
  limit?: number;
}

/** Clickable name ideas shown under an "Employee Name" field. */
export const NameSuggestions: React.FC<NameSuggestionsProps> = ({ onPick, exclude = [], current = '', limit = 8 }) => {
  const taken = new Set(exclude.map((n) => n.trim().toLowerCase()));
  const names = AGENT_NAME_SUGGESTIONS.filter((n) => !taken.has(n.toLowerCase())).slice(0, limit);
  if (names.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] text-slate-500">Suggestions:</span>
      {names.map((name) => {
        const active = current.trim().toLowerCase() === name.toLowerCase();
        return (
          <button
            key={name}
            type="button"
            onClick={() => onPick(name)}
            className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
              active
                ? 'border-[#00df8f] bg-[#00df8f]/15 text-[#00df8f]'
                : 'border-[#1b3a46] text-slate-300 hover:border-[#00df8f]/60 hover:text-slate-100'
            }`}
          >
            {name}
          </button>
        );
      })}
    </div>
  );
};
