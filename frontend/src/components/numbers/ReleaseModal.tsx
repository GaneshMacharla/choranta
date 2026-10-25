import React, { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { OperationResult, OwnedNumber, newIdempotencyKey, numbersService } from '../../services/numbers';

/** Gives a number back to the carrier. Typed confirmation; one idempotency key per opening. */
export const ReleaseModal: React.FC<{ number: OwnedNumber | null; onClose: () => void; onDone: (r: OperationResult) => void }> = ({
  number, onClose, onDone,
}) => {
  const [typed, setTyped] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (number) {
      setTyped('');
      setKey(newIdempotencyKey());
      setError(null);
    }
  }, [number]);

  if (!number) return null;

  const release = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await numbersService.release(number.id, { confirm_e164: typed.trim(), idempotency_key: key }));
    } catch (err: any) {
      setError(err.message || "Couldn't release the number.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Release ${number.e164}`} description="Gives the number back to the carrier." maxWidth="md">
      <div className="space-y-3 text-sm">
        <p className="flex items-start gap-2 rounded border border-amber-800/50 bg-amber-950/40 p-2.5 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          Choranta stops paying its monthly rental, but Vobiz may charge a release fee and the number can be bought by someone else.
          {number.is_mock && ' (Mock mode: simulated, nothing is charged.)'}
        </p>
        <label className="block space-y-1">
          <span className="text-xs text-slate-300">Type <span className="font-mono text-slate-100">{number.e164}</span> to confirm</span>
          <input className="w-full rounded border border-[#153945] bg-[#071419] px-2.5 py-2 font-mono text-xs text-slate-100 focus:border-rose-500 focus:outline-none"
            aria-label="Confirm number" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </label>
        {error && <p role="alert" className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-xs text-rose-300">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="danger" size="sm" disabled={typed.trim() !== number.e164 || busy} isLoading={busy} onClick={release}>
            Release number
          </Button>
        </div>
      </div>
    </Modal>
  );
};
