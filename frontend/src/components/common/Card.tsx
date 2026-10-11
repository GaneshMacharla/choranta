import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  noPadding?: boolean;
}

export const Card: React.FC<CardProps> = ({
  children,
  className = '',
  title,
  subtitle,
  action,
  noPadding = false,
}) => {
  return (
    <div className={`rounded-lg border border-[#143c49] bg-[#091b22] shadow-sm ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between border-b border-[#102d38] px-5 py-3.5">
          <div>
            {typeof title === 'string' ? (
              <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
            ) : (
              title
            )}
            {subtitle && (
              <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      <div className={noPadding ? '' : 'p-5'}>
        {children}
      </div>
    </div>
  );
};
