import React from 'react';
import { FlaskConical } from 'lucide-react';
import { Badge } from '../common/Badge';
import { STATUS_LABEL } from '../../services/numbers';

const VARIANT: Record<string, 'green' | 'yellow' | 'red' | 'gray' | 'purple'> = {
  AVAILABLE: 'gray',
  ASSIGNED: 'green',
  RELEASING: 'yellow',
  RELEASED: 'gray',
  NEEDS_RECONCILIATION: 'red',
  PENDING: 'yellow',
  SUCCEEDED: 'green',
  RECOVERED: 'green',
  FAILED: 'red',
  UNCERTAIN: 'yellow',
};

export const NumberStatusBadge: React.FC<{ status: string }> = ({ status }) => (
  <Badge variant={VARIANT[status] || 'gray'} size="sm">{STATUS_LABEL[status] || status}</Badge>
);

export const MockBadge: React.FC = () => (
  <span className="rounded border border-purple-700/50 bg-purple-950/50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-purple-300">
    Mock
  </span>
);

/** Shown on every number screen while PHONE_NUMBER_MOCK_MODE is on. */
export const MockModeBanner: React.FC = () => (
  <div role="status" className="flex items-start gap-3 rounded-lg border border-purple-700/40 bg-purple-950/30 p-3 text-sm text-purple-200">
    <FlaskConical className="mt-0.5 h-4 w-4 shrink-0" />
    <div>
      <p className="font-semibold">Mock mode: nothing here is real</p>
      <p className="text-xs text-purple-300/80">
        Numbers, prices and purchases come from a simulated carrier. Nothing is bought on Vobiz and no money is spent.
        Numbers labelled "Simulates" reproduce failures (low balance, timeouts) for testing.
      </p>
    </div>
  </div>
);

export const formatDate = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';
