import React, { useEffect, useState } from 'react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { clientsService } from '../../services/clients';
import { agentsService } from '../../services/agents';
import { OwnedNumber, numbersService } from '../../services/numbers';

const FIELD = 'w-full rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-xs text-slate-100 focus:border-[#00df8f] focus:outline-none';

/** Gives a pooled number to a client, optionally an AI employee and a SIP trunk. */
export const AssignModal: React.FC<{ number: OwnedNumber | null; onClose: () => void; onDone: (n: OwnedNumber) => void }> = ({
  number, onClose, onDone,
}) => {
  const [clients, setClients] = useState<{ id: string; name: string }[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string; status?: string }[]>([]);
  const [trunks, setTrunks] = useState<{ id: string; name: string }[]>([]);
  const [form, setForm] = useState({ client_id: '', agent_id: '', trunk_id: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!number) return;
    setForm({ client_id: '', agent_id: '', trunk_id: '' });
    setError(null);
    clientsService.list({ limit: 100 }).then((r) => setClients(r.items)).catch(() => setClients([]));
    numbersService.trunks().then(setTrunks).catch(() => setTrunks([]));
  }, [number]);

  useEffect(() => {
    setAgents([]);
    if (form.client_id) {
      agentsService.list({ client_id: form.client_id, limit: 100 }).then((r: any) => setAgents(r.items || [])).catch(() => setAgents([]));
    }
  }, [form.client_id]);

  if (!number) return null;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await numbersService.assign(number.id, { client_id: form.client_id, agent_id: form.agent_id || null, trunk_id: form.trunk_id || null }));
    } catch (err: any) {
      setError(err.message || "Couldn't assign the number.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Assign ${number.e164}`} description="The client will see it under Phone numbers in their portal." maxWidth="md">
      <div className="space-y-3 text-sm">
        <label className="block space-y-1">
          <span className="text-xs font-medium text-slate-300">Client</span>
          <select className={FIELD} value={form.client_id} onChange={(e) => setForm({ client_id: e.target.value, agent_id: '', trunk_id: form.trunk_id })}>
            <option value="">Choose a client</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-medium text-slate-300">AI employee (optional)</span>
          <select className={FIELD} value={form.agent_id} disabled={!form.client_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })}>
            <option value="">None yet</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <span className="block text-[11px] text-slate-500">It must have a published version. Inbound calls go to that version.</span>
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-medium text-slate-300">SIP trunk (optional)</span>
          <select className={FIELD} value={form.trunk_id} onChange={(e) => setForm({ ...form, trunk_id: e.target.value })}>
            <option value="">No trunk (calls use Choranta's answer URL)</option>
            {trunks.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
        <p className="text-[11px] text-slate-500">
          Assigning points the number at Choranta's Vobiz application and, if chosen, assigns the trunk on Vobiz. The client
          relationship and AI employee are recorded in Choranta.
        </p>
        {error && <p role="alert" className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-xs text-rose-300">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" disabled={!form.client_id || busy} isLoading={busy} onClick={save}>Assign</Button>
        </div>
      </div>
    </Modal>
  );
};
