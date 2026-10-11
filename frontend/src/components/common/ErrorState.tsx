import React from 'react';
import { AlertCircle, RotateCw } from 'lucide-react';
import { Button } from './Button';

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
  compact?: boolean;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  message = 'An unexpected error occurred while communicating with the server.',
  onRetry,
  compact = false,
}) => {
  if (compact) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-300">
        <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
        <span className="flex-1">{message}</span>
        {onRetry && (
          <button onClick={onRetry} className="text-red-300 hover:text-white underline">
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center p-8 text-center">
      <div className="mb-3 rounded-full bg-red-950/40 p-3 text-red-400 border border-red-900/40">
        <AlertCircle className="h-6 w-6" />
      </div>
      <h3 className="text-sm font-semibold text-slate-200">System Error</h3>
      <p className="mt-1 max-w-sm text-xs text-red-400/90">{message}</p>
      {onRetry && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onRetry}
          leftIcon={<RotateCw className="h-3.5 w-3.5" />}
          className="mt-4"
        >
          Try Again
        </Button>
      )}
    </div>
  );
};
