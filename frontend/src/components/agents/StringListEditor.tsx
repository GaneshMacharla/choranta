import React, { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '../common/Button';

interface StringListEditorProps {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
  helperText?: string;
  emptyText?: string;
}

/** Add/remove editor for a list of short strings (rules, phrases, responsibilities). */
export const StringListEditor: React.FC<StringListEditorProps> = ({
  label,
  items,
  onChange,
  placeholder,
  helperText,
  emptyText = 'Nothing added yet.',
}) => {
  const [value, setValue] = useState('');

  const add = () => {
    const next = value.trim();
    if (!next) return;
    onChange([...items, next]);
    setValue('');
  };

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-slate-300">{label}</label>
      <div className="flex gap-2">
        <input
          type="text"
          className="block flex-1 rounded-md border border-[#232736] bg-[#10121a] px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
          placeholder={placeholder}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" size="sm" variant="secondary" onClick={add} leftIcon={<Plus className="h-3.5 w-3.5" />}>
          Add
        </Button>
      </div>
      <div className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14]">
        {items.length === 0 ? (
          <div className="p-3 text-xs text-slate-500 text-center">{emptyText}</div>
        ) : (
          items.map((item, idx) => (
            <div key={`${idx}-${item}`} className="flex items-center justify-between gap-2 p-2.5 text-xs text-slate-200">
              <div className="flex items-start gap-2 min-w-0">
                <span className="font-mono text-slate-500">{idx + 1}.</span>
                <span className="break-words">{item}</span>
              </div>
              <button
                type="button"
                onClick={() => onChange(items.filter((_, i) => i !== idx))}
                className="text-slate-500 hover:text-rose-400 p-1 shrink-0"
                title="Remove"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
      {helperText && <p className="text-[11px] text-slate-500">{helperText}</p>}
    </div>
  );
};
