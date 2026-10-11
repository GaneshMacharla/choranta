import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  label?: string;
  options: SelectOption[];
  value?: string | number | readonly string[];
  onChange?: (e: { target: { value: string; name?: string } }) => void;
  error?: string;
  helperText?: string;
  placeholder?: string;
  className?: string;
  id?: string;
  name?: string;
  required?: boolean;
  disabled?: boolean;
  size?: 'sm' | 'md';
}

export const Select: React.FC<SelectProps> = ({
  label,
  options,
  value,
  onChange,
  error,
  helperText,
  placeholder = 'Select option...',
  className = '',
  id,
  name,
  required,
  disabled = false,
  size = 'md',
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

  // Find currently selected option
  const selectedOption = options.find((opt) => String(opt.value) === String(value));

  // Handle outside click to close popover
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // Handle keyboard navigation
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isOpen) return;
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleSelect = (optValue: string) => {
    if (disabled) return;
    if (onChange) {
      onChange({
        target: {
          value: optValue,
          name,
        },
      });
    }
    setIsOpen(false);
  };

  return (
    <div className="w-full space-y-1.5" ref={containerRef}>
      {label && (
        <label htmlFor={selectId} className="block text-xs font-medium text-slate-300">
          {label} {required && <span className="text-red-400">*</span>}
        </label>
      )}

      <div className="relative">
        {/* Hidden Input for form compatibility */}
        <input
          type="hidden"
          id={selectId}
          name={name}
          value={value !== undefined ? String(value) : ''}
        />

        {/* Custom Trigger Button */}
        <button
          type="button"
          disabled={disabled}
          onClick={() => !disabled && setIsOpen(!isOpen)}
          aria-haspopup="listbox"
          aria-expanded={isOpen}
          className={`
            w-full rounded-md border text-left transition-all duration-150
            bg-[#06141a] text-slate-100
            flex items-center justify-between gap-2
            ${size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-sm'}
            ${error
              ? 'border-red-500/60 focus:border-red-500 focus:ring-1 focus:ring-red-500'
              : isOpen
              ? 'border-[#00df8f] ring-1 ring-[#00df8f] shadow-[0_0_12px_rgba(0,223,143,0.15)]'
              : 'border-[#153945] hover:border-[#1e4e5e]'
            }
            ${disabled ? 'opacity-50 cursor-not-allowed bg-[#040d12]' : 'cursor-pointer'}
            ${className}
          `}
        >
          <span className={`truncate ${!selectedOption && placeholder ? 'text-slate-500' : 'text-slate-200'}`}>
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          <ChevronDown
            className={`${size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} text-slate-400 transition-transform duration-200 shrink-0 ${
              isOpen ? 'rotate-180 text-[#00df8f]' : ''
            }`}
          />
        </button>

        {/* Custom Popover Menu */}
        {isOpen && (
          <div
            role="listbox"
            className="absolute z-50 left-0 right-0 mt-1.5 rounded-lg border border-[#143c49] bg-[#091b22] py-1 shadow-2xl shadow-black/80 max-h-60 overflow-y-auto focus:outline-none"
            style={{
              boxShadow: '0 12px 30px rgba(0,0,0,0.8), 0 0 15px rgba(0, 223, 143, 0.08)',
            }}
          >
            {options.map((opt) => {
              const isSelected = String(opt.value) === String(value);

              return (
                <div
                  key={opt.value}
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => handleSelect(opt.value)}
                  className={`
                    w-full text-left
                    flex items-center justify-between gap-2
                    transition-colors duration-100 cursor-pointer select-none
                    ${size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-xs md:text-sm'}
                    ${isSelected
                      ? 'bg-[#00df8f]/15 text-[#00df8f] font-medium'
                      : 'text-slate-200 hover:bg-[#00df8f]/10 hover:text-[#00df8f]'
                    }
                  `}
                >
                  <span className="truncate">{opt.label}</span>
                  {isSelected && (
                    <Check className={`${size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} text-[#00df8f] shrink-0`} />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
      {!error && helperText && <p className="text-xs text-slate-500 mt-1">{helperText}</p>}
    </div>
  );
};
