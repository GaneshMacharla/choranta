import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RotateCw, Home } from 'lucide-react';
import { Button } from './Button';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught component error:', error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[60vh] flex-col items-center justify-center p-6 text-center">
          <div className="mb-4 rounded-full bg-rose-950/40 border border-rose-900/50 p-3.5 text-rose-400">
            <AlertTriangle className="h-7 w-7" />
          </div>
          <h2 className="text-base font-semibold text-slate-100">Something went wrong</h2>
          <p className="mt-1.5 max-w-md text-xs text-slate-400">
            An unexpected error occurred while rendering this interface.
          </p>
          {this.state.error && (
            <div className="mt-3 max-w-lg rounded border border-rose-900/40 bg-rose-950/20 p-2.5 font-mono text-[11px] text-rose-300 overflow-x-auto text-left">
              {this.state.error.message}
            </div>
          )}
          <div className="mt-6 flex items-center gap-3">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<RotateCw className="h-3.5 w-3.5" />}
              onClick={this.handleReset}
            >
              Reload View
            </Button>
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Home className="h-3.5 w-3.5" />}
              onClick={() => (window.location.href = '/')}
            >
              Return to Overview
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
