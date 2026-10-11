import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button } from '../components/common/Button';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="font-mono text-4xl font-bold text-slate-500 mb-2">404</div>
      <h2 className="text-base font-semibold text-slate-200">Page Not Found</h2>
      <p className="mt-1 max-w-sm text-xs text-slate-400">
        The requested operations screen does not exist or has been relocated.
      </p>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => navigate('/')}
        leftIcon={<ArrowLeft className="h-3.5 w-3.5" />}
        className="mt-4"
      >
        Return to Overview
      </Button>
    </div>
  );
};
