import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, HelpCircle } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { InventoryNumber, NumberOperation, OperationResult, failedOperation, money, newIdempotencyKey, numbersService } from '../../services/numbers';

/**
 * Confirms a purchase with the carrier's own prices. One idempotency key per opening, so pressing Buy twice (or a
 * retry after a dropped connection) can never buy the number twice.
 */
export const PurchaseConfirmModal: React.FC<{
  number: InventoryNumber | null;
  onClose: () => void;
  onDone: (result: OperationResult) => void;
}> = ({ number, onClose, onDone }) => {
  const [key, setKey] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<NumberOperation | null>(null);

  useEffect(() => {
    if (number) {
      setKey(newIdempotencyKey());
      setConfirmed(false);
      setError(null);
      setOutcome(null);
    }
  }, [number]);

  if (!number) return null;
  const firstCharge = (number.setup_fee ?? 0) + (number.monthly_fee ?? 0);

  const buy = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await numbersService.purchase({
        e164: number.e164, idempotency_key: key, confirm: true, expected_monthly_cost: number.monthly_fee,
        expected_setup_cost: number.setup_fee, currency: number.currency,
      });
      setOutcome(result.operation);
      onDone(result);
    } catch (err: any) {
      setError(err.message || 'The purchase failed.');
      setOutcome(failedOperation(err));
    } finally {
      setBusy(false);
    }
  };

  const status = outcome?.operation_status;
  const bought = status === 'SUCCEEDED' || status === 'RECOVERED';
  const unsure = status === 'UNCERTAIN' || status === 'NEEDS_RECONCILIATION' || status === 'PENDING';

  return (
    <Modal isOpen onClose={onClose} title={`Buy ${number.e164}`} description="This debits Choranta's Vobiz balance." maxWidth="md">
      <div className="space-y-4 text-sm">
        {number.is_mock && (
          <p className="rounded border border-purple-700/40 bg-purple-950/30 p-2 text-xs text-purple-200">
            Mock mode: this purchase is simulated. Nothing is bought on Vobiz.
          </p>
        )}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-[#143c49] bg-[#071419] p-4">
          <dt className="text-slate-400">Number</dt>
          <dd className="font-mono text-slate-100">{number.e164}</dd>
          <dt className="text-slate-400">Type / region</dt>
          <dd className="text-slate-200">{number.number_type || 'Unknown'}{number.number_type_derived ? ' (from prefix)' : ''} · {number.region || '-'}</dd>
          <dt className="text-slate-400">Setup fee (one time)</dt>
          <dd className="text-slate-200">{money(number.setup_fee, number.currency)}</dd>
          <dt className="text-slate-400">Monthly rental (recurring)</dt>
          <dd className="text-slate-200">{money(number.monthly_fee, number.currency)} / month</dd>
          <dt className="text-slate-400">Charged now</dt>
          <dd className="font-semibold text-slate-100">{money(firstCharge, number.currency)} <span className="text-xs font-normal text-slate-500">(setup + first month)</span></dd>
          <dt className="text-slate-400">Currency</dt>
          <dd className="text-slate-200">{number.currency || 'Not given'}</dd>
        </dl>
        {number.scenario && <p className="text-xs text-amber-300">{number.scenario}</p>}
        <p className="text-xs text-slate-400">
          Prices are what Vobiz lists right now; the purchase is refused if they change before it goes through. Releasing a number
          later may cost a release fee.
        </p>

        {bought && (
          <p role="status" className="flex items-start gap-2 rounded border border-[#0a4d39] bg-[#052b20]/80 p-2.5 text-[#00df8f]">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            {status === 'RECOVERED' ? 'Bought. The carrier was slow to answer, so Choranta checked and confirmed it.' : 'Bought. It is now in the pool, ready to assign.'}
          </p>
        )}
        {unsure && (
          <p role="status" className="flex items-start gap-2 rounded border border-amber-800/50 bg-amber-950/40 p-2.5 text-amber-200">
            <HelpCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {outcome?.error_message || "We couldn't confirm whether it was bought."} It won't be retried automatically; check it under Operations.
          </p>
        )}
        {error && !unsure && (
          <p role="alert" className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
          </p>
        )}

        {!outcome && (
          <label className="flex items-start gap-2 text-slate-300">
            <input type="checkbox" className="mt-1 accent-[#00df8f]" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            I confirm buying {number.e164} for {money(firstCharge, number.currency)} now and {money(number.monthly_fee, number.currency)} every month.
          </label>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>{outcome ? 'Close' : 'Cancel'}</Button>
          {!outcome && (
            <Button variant="primary" size="sm" disabled={!confirmed || busy} isLoading={busy} onClick={buy}>
              Buy number
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
};
