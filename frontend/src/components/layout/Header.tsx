import React, { useEffect, useState } from 'react';
import { ShieldCheck, FlaskConical } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { request } from '../../services/api';

export const Header: React.FC = () => {
  const { user } = useAuth();
  const [isMock, setIsMock] = useState<boolean | null>(null);

  useEffect(() => {
    request<{ mock: boolean }>('/mock/environment')
      .then((environment) => setIsMock(environment.mock))
      .catch(() => setIsMock(null));
  }, []);

  return (
    <header className="h-14 border-b border-[#102731] bg-[#051116]/85 backdrop-blur-md px-6 flex items-center justify-between shrink-0 select-none">
      <div className="flex items-center gap-3">
        <span className="flex h-2 w-2 relative">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00df8f] opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00df8f]"></span>
        </span>
        <span className="text-xs font-mono text-slate-300">
          Choranta Internal Core &bull; Connected
        </span>
      </div>

      <div className="flex items-center gap-4">
        {isMock === true && (
          <div className="flex items-center gap-2 rounded border border-amber-700/60 bg-amber-950/40 px-2.5 py-1 text-xs font-semibold text-amber-300">
            <FlaskConical className="h-3.5 w-3.5" />
            <span>MOCK ENVIRONMENT - NO EXTERNAL PROVIDER CALLS</span>
          </div>
        )}
        <div className="flex items-center gap-2 rounded border border-[#143c49] bg-[#071820] px-2.5 py-1 text-xs text-slate-300">
          <ShieldCheck className="h-3.5 w-3.5 text-[#00df8f]" />
          <span>Internal Access Only</span>
        </div>
        <div className="text-xs text-slate-400">
          <span className="text-slate-500">Logged in as:</span>{' '}
          <span className="font-mono text-slate-200">{user?.email}</span>
        </div>
      </div>
    </header>
  );
};
