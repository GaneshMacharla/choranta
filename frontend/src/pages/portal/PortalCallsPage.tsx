import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CallOutputsCard } from '../../components/calls/CallOutputsCard';
import { PhoneIncoming, PhoneOutgoing } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Modal } from '../../components/common/Modal';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { CallRecordingPlayer } from '../../components/telephony/CallRecordingPlayer';
import { CallCostCard } from '../../components/telephony/CallCostCard';
import { Call, CallDetail } from '../../services/telephony';
import { inr, portalService } from '../../services/portal';

const duration = (s: number) => (s ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : '—');

export const PortalCallsPage: React.FC = () => {
  const [calls, setCalls] = useState<Call[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CallDetail | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    portalService.calls().then(setCalls).catch((err) => setError(err.message || 'Could not load calls.'));
  }, []);

  // Opened from a link such as the dashboard's hot leads (/portal/calls?call=<id>)
  const [searchParams] = useSearchParams();
  const linkedCall = searchParams.get('call');
  useEffect(() => {
    if (linkedCall) open(linkedCall);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedCall]);

  const open = async (id: string) => {
    setOpenId(id);
    setDetail(null);
    try {
      setDetail(await portalService.call(id));
    } catch (err: any) {
      setError(err.message);
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!calls) return <LoadingState message="Loading calls..." />;

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <h1 className="text-xl font-bold">Calls</h1>
      <Card noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#1f2433] text-slate-400">
              <tr>
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Number</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Charge</th>
              </tr>
            </thead>
            <tbody>
              {calls.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-slate-500">No calls yet.</td>
                </tr>
              )}
              {calls.map((c) => (
                <tr key={c.id} onClick={() => open(c.id)} className="cursor-pointer border-b border-[#151a26] hover:bg-[#0f141d]">
                  <td className="px-4 py-3 text-slate-400">{new Date(c.created_at).toLocaleString('en-IN')}</td>
                  <td className="px-4 py-3 font-mono text-slate-200">
                    {c.direction === 'OUTBOUND' ? (
                      <PhoneOutgoing className="mr-1.5 inline h-3.5 w-3.5 text-indigo-400" />
                    ) : (
                      <PhoneIncoming className="mr-1.5 inline h-3.5 w-3.5 text-emerald-400" />
                    )}
                    {c.direction === 'OUTBOUND' ? c.destination_number : c.caller_number}
                  </td>
                  <td className="px-4 py-3 text-slate-300">{c.status}</td>
                  <td className="px-4 py-3 font-mono text-slate-300">{duration(c.duration_seconds)}</td>
                  <td className="px-4 py-3 font-mono text-amber-300">{c.cost ? inr(c.cost.charge_total) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Modal isOpen={!!openId} onClose={() => setOpenId(null)} title="Call details">
        {!detail ? (
          <LoadingState message="Loading call..." />
        ) : (
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-3 gap-2 text-slate-300">
              <div><span className="block text-slate-500">Status</span>{detail.status}</div>
              <div><span className="block text-slate-500">Duration</span>{duration(detail.duration_seconds)}</div>
              <div><span className="block text-slate-500">Direction</span>{detail.direction}</div>
            </div>
            {detail.has_recording && <CallRecordingPlayer callId={detail.id} fetchBlob={portalService.recording} />}
            <CallOutputsCard metadata={detail.metadata} />
            <div className="max-h-64 space-y-2 overflow-y-auto rounded border border-[#1b2030] bg-[#090b12] p-3">
              {detail.conversation.length === 0 ? (
                <p className="text-center text-slate-500">No conversation recorded.</p>
              ) : (
                detail.conversation.map((turn, i) => (
                  <div key={i} className={`flex ${turn.role === 'caller' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[80%] rounded-lg px-3 py-2 ${turn.role === 'caller' ? 'bg-emerald-950/40 text-emerald-200' : 'bg-[#151824] text-slate-200'}`}>
                      {turn.content}
                    </div>
                  </div>
                ))
              )}
            </div>
            {detail.cost && <CallCostCard cost={detail.cost} />}
          </div>
        )}
      </Modal>
    </div>
  );
};
