import React, { useEffect, useState } from 'react';
import { PhoneCall, Save } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { clientsService } from '../../services/clients';
import { Client } from '../../types';

/** Admin: how many calls this client may have live at once (blank = the platform default in Settings). */
export const ClientCallLimitCard: React.FC<{ client: Client; onSaved: (client: Client) => void }> = ({ client, onSaved }) => {
  const [value, setValue] = useState(client.max_concurrent_calls ? String(client.max_concurrent_calls) : '');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    setValue(client.max_concurrent_calls ? String(client.max_concurrent_calls) : '');
  }, [client.max_concurrent_calls]);

  const number = Number(value);
  const valid = value === '' || (Number.isInteger(number) && number >= 1 && number <= 500);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await clientsService.update(client.id, { max_concurrent_calls: value === '' ? 0 : number });
      onSaved(updated);
      setMessage({ ok: true, text: value === '' ? 'Using the platform default.' : 'Call limit saved.' });
    } catch (err: any) {
      setMessage({ ok: false, text: err.message || 'Could not save the call limit.' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Call limit" subtitle="Calls this client can have running at the same time">
      <div className="flex flex-wrap items-end gap-3 text-xs">
        <label className="space-y-1">
          <span className="flex items-center gap-1.5 font-medium text-slate-300">
            <PhoneCall className="h-3.5 w-3.5 text-[#00df8f]" /> Calls at a time
          </span>
          <input
            type="number"
            min={1}
            max={500}
            placeholder="Platform default"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-40 rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
          />
        </label>
        <Button size="sm" variant="primary" onClick={save} isLoading={saving} disabled={!valid || saving}>
          <Save className="mr-1.5 h-3.5 w-3.5" /> Save
        </Button>
        <span className="text-slate-500">
          Leave blank for the default in Settings → Client Pricing. Campaigns keep one line free for incoming calls.
        </span>
        {message && <span className={message.ok ? 'text-emerald-300' : 'text-rose-300'}>{message.text}</span>}
      </div>
    </Card>
  );
};
