import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bot, CheckCircle, Loader2, PhoneCall, PhoneOutgoing } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { PortalNumber, portalService } from '../../services/portal';

type Agent = { id: string; name: string; published: boolean };

const POLL_MS = 2500;
const MAX_WAIT_MS = 120_000;

const FAILED_REASONS: Record<string, string> = {
  'NO-ANSWER': "The call wasn't answered.",
  BUSY: 'The line was busy.',
  FAILED: "The call couldn't be connected.",
  NOT_ANSWERED: "The call ended before it was answered.",
  CANCELED: 'The call was cancelled.',
};

interface Props {
  isOpen: boolean;
  onClose: () => void;
  number: PortalNumber | null;
  agents: Agent[];
  contactPhone?: string | null;
  onChanged: () => void;
}

/** Steps after buying: assign an AI employee, then a test call to the client's phone that turns the number Active. */
export const NumberActivationModal: React.FC<Props> = ({ isOpen, onClose, number, agents, contactPhone, onChanged }) => {
  const [current, setCurrent] = useState<PortalNumber | null>(number);
  const [agentId, setAgentId] = useState('');
  const [phone, setPhone] = useState('');
  const [testing, setTesting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(0);

  useEffect(() => {
    if (!isOpen || !number) return;
    setCurrent(number);
    setAgentId(number.agent_id || agents.find((a) => a.published)?.id || '');
    setPhone(contactPhone || '');
    setTesting(false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, number?.id]);

  // While a test call runs, follow it until it connects (number turns Active) or fails
  useEffect(() => {
    if (!testing || !current) return;
    const timer = setInterval(async () => {
      try {
        const fresh = await portalService.numberDetail(current.id);
        setCurrent(fresh);
        if (fresh.status === 'ACTIVE') {
          setTesting(false);
          onChanged();
        } else if (fresh.test_result && fresh.test_result !== 'CONNECTED') {
          setTesting(false);
        } else if (Date.now() - started.current > MAX_WAIT_MS) {
          setTesting(false);
          setError("We didn't hear back from the test call. Try again, or skip the test.");
        }
      } catch {
        // keep polling
      }
    }, POLL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testing, current?.id]);

  if (!current) return null;
  const assigned = !!current.agent_id;
  const active = current.status === 'ACTIVE';
  const failed = !testing && !!current.test_result && current.test_result !== 'CONNECTED' && !active;
  const publishedAgents = agents.filter((a) => a.published);

  const assign = async () => {
    setBusy('assign');
    setError(null);
    try {
      setCurrent(await portalService.assignNumber(current.id, agentId));
      onChanged();
    } catch (e: any) {
      setError(e.message || 'Could not assign the AI employee.');
    } finally {
      setBusy(null);
    }
  };

  const callMe = async () => {
    setBusy('test');
    setError(null);
    try {
      setCurrent(await portalService.testNumber(current.id, phone.trim()));
      started.current = Date.now();
      setTesting(true);
    } catch (e: any) {
      setError(e.message || 'Could not start the test call.');
    } finally {
      setBusy(null);
    }
  };

  const skip = async () => {
    setBusy('skip');
    setError(null);
    try {
      setCurrent(await portalService.activateNumber(current.id));
      onChanged();
    } catch (e: any) {
      setError(e.message || 'Could not activate the number.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Set up ${current.phone_number}`} description="Two quick steps and your number is live." maxWidth="lg">
      <div className="space-y-5 text-sm">
        {error && (
          <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-xs text-rose-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        {/* Step 1: AI employee */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 font-medium text-slate-200">
            <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${assigned ? 'bg-[#00df8f] text-[#04110c]' : 'border border-[#2a6577] text-slate-300'}`}>1</span>
            Which AI employee should answer and call from this number?
          </div>
          {publishedAgents.length === 0 ? (
            <p className="text-xs text-amber-300">You don't have a ready AI employee yet. Once Choranta finishes setting one up, come back to finish this number.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              <select
                className="min-w-[220px] flex-1 rounded border border-[#232736] bg-[#10121a] p-2 text-sm text-slate-100"
                value={agentId}
                disabled={active}
                onChange={(e) => setAgentId(e.target.value)}
              >
                {publishedAgents.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              {!active && (
                <Button variant={assigned && current.agent_id === agentId ? 'secondary' : 'primary'} leftIcon={<Bot className="h-4 w-4" />}
                  isLoading={busy === 'assign'} disabled={!agentId || current.agent_id === agentId} onClick={assign}>
                  {assigned && current.agent_id === agentId ? 'Assigned' : 'Assign'}
                </Button>
              )}
            </div>
          )}
        </div>

        {/* Step 2: test call */}
        <div className={`space-y-2 ${assigned ? '' : 'pointer-events-none opacity-40'}`}>
          <div className="flex items-center gap-2 font-medium text-slate-200">
            <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${active ? 'bg-[#00df8f] text-[#04110c]' : 'border border-[#2a6577] text-slate-300'}`}>2</span>
            Test it: we'll call your phone from this number
          </div>

          {active ? (
            <div className="flex items-start gap-2 rounded-lg border border-emerald-800/60 bg-emerald-950/30 p-3 text-emerald-200">
              <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {current.phone_number} is <strong>active</strong>
                {current.activated_by === 'test_call' ? ': the test call connected.' : '.'} Your AI employee now answers it and can call from it.
              </span>
            </div>
          ) : testing ? (
            <div className="flex items-center gap-2 rounded-lg border border-[#143c49] bg-[#06141a] p-3 text-slate-300">
              <Loader2 className="h-4 w-4 animate-spin text-[#00df8f]" />
              Calling {phone}… Answer and talk to your AI employee for a few seconds. This page updates by itself.
            </div>
          ) : (
            <>
              <p className="text-xs text-slate-400">Your phone will ring from {current.phone_number}. Answer it to hear your AI employee. When the call connects, the number turns active.</p>
              {failed && (
                <p className="text-xs text-amber-300">{FAILED_REASONS[current.test_result || ''] || "The test call didn't connect."} Try again.</p>
              )}
              <div className="flex flex-wrap gap-2">
                <input
                  className="min-w-[200px] flex-1 rounded border border-[#232736] bg-[#10121a] p-2 font-mono text-sm text-slate-100"
                  placeholder="+91 98765 43210"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
                <Button variant="primary" leftIcon={<PhoneOutgoing className="h-4 w-4" />} isLoading={busy === 'test'}
                  disabled={!assigned || phone.replace(/\D/g, '').length < 10} onClick={callMe}>
                  {failed ? 'Try again' : 'Call me now'}
                </Button>
              </div>
            </>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[#102d38] pt-4">
          {!active ? (
            <button type="button" className="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50" disabled={busy === 'skip' || testing} onClick={skip}>
              Skip the test and activate now
            </button>
          ) : <span />}
          <Button variant={active ? 'primary' : 'secondary'} leftIcon={active ? <PhoneCall className="h-4 w-4" /> : undefined} onClick={onClose}>
            {active ? 'Done' : 'Finish later'}
          </Button>
        </div>
      </div>
    </Modal>
  );
};
