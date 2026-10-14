import React from 'react';

/** Page loader: the Choranta logo breathing inside a circling brand-green arc. */
export const LoadingState: React.FC<{ message?: string }> = ({ message = 'Loading...' }) => {
  return (
    <div role="status" aria-live="polite" className="flex flex-col items-center justify-center py-16 text-slate-400">
      <div className="relative flex h-16 w-16 items-center justify-center">
        <div className="choranta-loader-ring absolute inset-0 rounded-full" />
        <img src="/logo.png" alt="" aria-hidden="true" className="choranta-loader-logo h-10 w-10 object-contain" />
      </div>
      <span className="mt-3 text-xs font-medium tracking-wide">{message}</span>
    </div>
  );
};
