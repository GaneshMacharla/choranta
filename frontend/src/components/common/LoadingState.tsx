import React from 'react';

export const LoadingState: React.FC<{ message?: string }> = ({ message = 'Loading...' }) => {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-400">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#00df8f] border-t-transparent" />
      <span className="mt-3 text-xs font-medium tracking-wide">{message}</span>
    </div>
  );
};
