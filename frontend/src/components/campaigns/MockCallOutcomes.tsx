import React, { useEffect, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { Button } from '../common/Button';
import { Input } from '../common/Input';
import { Select } from '../common/Select';
import { request } from '../../services/api';
import { MockCallOutcome, runtimeService } from '../../services/runtime';

const OUTCOMES: Array<{ value: MockCallOutcome; label: string }> = [
  { value: 'completed', label: 'Answered' },
  { value: 'no-answer', label: 'No answer' },
  { value: 'busy', label: 'Busy' },
  { value: 'failed', label: 'Failed' },
];

/**
 * Mock environment only: ends this campaign's simulated calls, as the carrier's status callback
 * would. The mock carrier never reports back, so without this recipients stay "on call".
 */
export const MockCallOutcomes: React.FC<{ campaignId: string; onDone: () => void }> = ({ campaignId, onDone }) => {
  const [isMock, setIsMock] = useState(false);
  const [outcome, setOutcome] = useState<MockCallOutcome>('completed');
  const [duration, setDuration] = useState('45');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    request<{ mock: boolean }>('/mock/environment')
      .then((environment) => setIsMock(environment.mock))
      .catch(() => setIsMock(false));
  }, []);

  if (!isMock) return null;

  const apply = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await runtimeService.completePendingMockCalls({
        status: outcome,
        duration_seconds: outcome === 'completed' ? Number(duration) || 0 : 0,
        campaign_id: campaignId,
      });
      setMessage(
        result.updated
          ? `Ended ${result.updated} simulated call${result.updated === 1 ? '' : 's'}. The dialer picks this up within a few seconds.`
          : 'No simulated calls are waiting for an outcome.'
      );
      onDone();
    } catch (e: any) {
      setMessage(e.message || 'Could not end the simulated calls.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-700/50 bg-amber-950/20 p-3 text-xs text-slate-300">
      <span className="flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-amber-300" />
        <span>
          <span className="font-semibold text-amber-300">Mock calls</span> · end this campaign's simulated calls
          {message && <span className="ml-2 text-slate-400">{message}</span>}
        </span>
      </span>
      <div className="flex items-center gap-2">
        <Select size="sm" value={outcome} onChange={(e) => setOutcome(e.target.value as MockCallOutcome)} options={OUTCOMES} />
        {outcome === 'completed' && (
          <div className="w-20">
            <Input type="number" min={0} max={3600} value={duration} onChange={(e) => setDuration(e.target.value)} />
          </div>
        )}
        {outcome === 'completed' && <span className="text-slate-500">sec</span>}
        <Button size="sm" variant="secondary" isLoading={busy} onClick={apply}>
          End pending calls
        </Button>
      </div>
    </div>
  );
};
