import React, { useEffect, useState } from 'react';
import { Hash, RefreshCw } from 'lucide-react';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { InventoryPanel } from '../components/numbers/InventoryPanel';
import { OwnedNumbersPanel } from '../components/numbers/OwnedNumbersPanel';
import { OperationsPanel } from '../components/numbers/OperationsPanel';
import { MockModeBanner } from '../components/numbers/shared';
import { useAuth } from '../context/AuthContext';
import { ProviderStatus, money, numbersService } from '../services/numbers';

type Tab = 'owned' | 'inventory' | 'operations';

/** Choranta's phone numbers at Vobiz: buy, assign to clients, sync and release. */
export const NumbersPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [tab, setTab] = useState<Tab>('owned');
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  const loadStatus = () => numbersService.providerStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    loadStatus();
  }, []);

  const sync = async () => {
    setSyncing(true);
    setMessage(null);
    try {
      const r = await numbersService.sync();
      setMessage({ tone: 'ok', text: `Synced ${r.seen} numbers: ${r.adopted} new, ${r.missing} missing at the carrier, ${r.operations_settled} operations settled.` });
      setRefreshKey((k) => k + 1);
      loadStatus();
    } catch (err: any) {
      setMessage({ tone: 'error', text: err.message || 'Sync failed.' });
    } finally {
      setSyncing(false);
    }
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: 'owned', label: 'Our numbers' },
    { id: 'inventory', label: 'Buy numbers' },
    { id: 'operations', label: 'Operations' },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-4 sm:p-8">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-100"><Hash className="h-6 w-6 text-[#00df8f]" /> Phone numbers</h1>
          <p className="mt-1 text-sm text-slate-400">Numbers on Choranta's Vobiz account: buy them, give them to clients, and keep records in line with Vobiz.</p>
        </div>
        {isAdmin && (
          <Button variant="secondary" onClick={sync} isLoading={syncing} leftIcon={<RefreshCw className="h-4 w-4" />}>Sync with Vobiz</Button>
        )}
      </div>

      {status?.mock_mode && <MockModeBanner />}
      {status && (
        <Card>
          <div className="flex flex-wrap gap-x-8 gap-y-2 text-xs text-slate-400">
            <span>Carrier: <span className="text-slate-200">{status.mock_mode ? 'Simulated (mock)' : 'Vobiz'}</span></span>
            <span>Configured: <span className={status.configured ? 'text-[#00df8f]' : 'text-rose-300'}>{status.configured ? 'Yes' : 'No'}</span></span>
            <span>Balance: <span className="text-slate-200">{status.balance != null ? money(status.balance, status.currency) : 'Unknown'}</span></span>
            <span>Inbound routing: <span className={status.application_attached ? 'text-[#00df8f]' : 'text-amber-300'}>
              {status.application_attached ? 'Application set' : 'VOBIZ_APPLICATION_ID not set'}</span></span>
            {status.error && <span className="text-rose-300">{status.error}</span>}
          </div>
        </Card>
      )}
      {message && (
        <p role={message.tone === 'error' ? 'alert' : 'status'}
          className={`rounded border p-2.5 text-xs ${message.tone === 'ok' ? 'border-[#0a4d39] bg-[#052b20]/80 text-[#00df8f]' : 'border-rose-800/50 bg-rose-950/40 text-rose-300'}`}>
          {message.text}
        </p>
      )}

      <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-[#102d38]">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} type="button" onClick={() => setTab(t.id)}
            className={`whitespace-nowrap border-b-2 px-4 py-2 text-sm ${tab === t.id ? 'border-[#00df8f] font-semibold text-[#00df8f]' : 'border-transparent text-slate-400 hover:text-slate-200'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'owned' && <OwnedNumbersPanel isAdmin={isAdmin} refreshKey={refreshKey} />}
      {tab === 'inventory' && (
        <InventoryPanel canBuy={isAdmin} onBought={() => { setRefreshKey((k) => k + 1); loadStatus(); }} />
      )}
      {tab === 'operations' && <OperationsPanel isAdmin={isAdmin} refreshKey={refreshKey} />}
    </div>
  );
};
