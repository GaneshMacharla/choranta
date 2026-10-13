import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

export interface MultiSelectOption {
  value: string;
  label: string;
  hint?: string;
  disabled?: boolean;
}

interface MultiSelectProps {
  label?: string;
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  helperText?: string;
  error?: string;
}

/** Checkbox popover in the same style as Select, for choosing several options. */
export const MultiSelect: React.FC<MultiSelectProps> = ({
  label,
  options,
  value,
  onChange,
  placeholder = 'Select...',
  disabled = false,
  required,
  helperText,
  error,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setIsOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const selected = options.filter((o) => value.includes(o.value));
  const toggle = (opt: MultiSelectOption) => {
    if (opt.disabled) return;
    onChange(value.includes(opt.value) ? value.filter((v) => v !== opt.value) : [...value, opt.value]);
  };

  return (
    <div className="w-full space-y-1.5" ref={containerRef}>
      {label && (
        <label className="block text-xs font-medium text-slate-300">
          {label} {required && <span className="text-red-400">*</span>}
        </label>
      )}
      <div className="relative">
        <button
          type="button"
          disabled={disabled}
          onClick={() => !disabled && setIsOpen(!isOpen)}
          aria-haspopup="listbox"
          aria-expanded={isOpen}
          className={`flex w-full items-center justify-between gap-2 rounded-md border bg-[#06141a] px-3 py-2 text-left text-sm transition-all duration-150 ${
            error
              ? 'border-red-500/60'
              : isOpen
              ? 'border-[#00df8f] ring-1 ring-[#00df8f]'
              : 'border-[#153945] hover:border-[#1e4e5e]'
          } ${disabled ? 'cursor-not-allowed bg-[#040d12] opacity-50' : 'cursor-pointer'}`}
        >
          <span className={`truncate ${selected.length ? 'text-slate-200' : 'text-slate-500'}`}>
            {selected.length === 0
              ? placeholder
              : selected.length <= 2
              ? selected.map((o) => o.label).join(', ')
              : `${selected.length} selected`}
          </span>
          <ChevronDown className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${isOpen ? 'rotate-180 text-[#00df8f]' : ''}`} />
        </button>

        {isOpen && (
          <div
            role="listbox"
            aria-multiselectable="true"
            className="absolute left-0 right-0 z-50 mt-1.5 max-h-60 overflow-y-auto rounded-lg border border-[#143c49] bg-[#091b22] py-1 shadow-2xl shadow-black/80"
          >
            {options.length === 0 && <div className="px-3 py-2 text-xs text-slate-500">Nothing to choose from.</div>}
            {options.map((opt) => {
              const isSelected = value.includes(opt.value);
              return (
                <div
                  key={opt.value}
                  role="option"
                  aria-selected={isSelected}
                  aria-disabled={opt.disabled}
                  onClick={() => toggle(opt)}
                  className={`flex items-center gap-2.5 px-3 py-2 text-xs md:text-sm select-none ${
                    opt.disabled
                      ? 'cursor-not-allowed text-slate-500'
                      : isSelected
                      ? 'cursor-pointer bg-[#00df8f]/10 text-[#00df8f]'
                      : 'cursor-pointer text-slate-200 hover:bg-[#00df8f]/10'
                  }`}
                >
                  <span
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                      isSelected ? 'border-[#00df8f] bg-[#00df8f] text-[#04110c]' : 'border-[#1e4e5e]'
                    }`}
                  >
                    {isSelected && <Check className="h-3 w-3" />}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{opt.label}</span>
                  {opt.hint && <span className="shrink-0 text-[11px] text-slate-500">{opt.hint}</span>}
                </div>
              );
            })}
          </div>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
      {!error && helperText && <p className="mt-1 text-xs text-slate-500">{helperText}</p>}
    </div>
  );
};
