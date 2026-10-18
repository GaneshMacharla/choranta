import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { pricingService, CarrierCheck } from '../../services/pricing';

const inr = (value: number | null | undefined, digits = 2) =>
  value == null ? '—' : `₹${value.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

/** Admin-only: Choranta's phone-line cost estimate checked against Exotel's real price per call. */
export const CarrierCostCheckCard: React.FC = () => {
  const [report, setReport] = useState<CarrierCheck | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await pricingService.carrierCheck(30));
    } catch (err: any) {
      setError(err.message || 'Could not load the Exotel cost check.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const priced = report && report.calls_priced > 0;

  return (
    <Card
      title="Exotel cost check"
      subtitle="Choranta's phone-line estimate vs what Exotel actually charged (last 30 days)"
      action={
        <Button size="sm" variant="secondary" onClick={load} isLoading={loading} disabled={loading}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
        </Button>
      }
    >
      <div className="space-y-4 text-xs">
        {error && <p className="text-rose-300">{error}</p>}

        {report && !priced && (
          <p className="leading-relaxed text-slate-400">
            No calls checked yet. A few minutes after each real call ends, Choranta fetches its price from Exotel and
            compares it here.
          </p>
        )}

        {report && priced && (
          <>
            {report.rate_too_low ? (
              <div className="flex items-start gap-2 rounded border border-rose-900/60 bg-rose-950/40 p-3 text-rose-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Exotel cost {report.gap_percent}% more than Choranta estimated, so calls are charged too little. Set{' '}
                  <code className="font-mono">TELEPHONY_RATE_PER_MINUTE_INR={report.matching_rate_per_minute_inr}</code> in
                  backend/.env (currently {report.current_rate_per_minute_inr}) and restart the backend.
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded border border-emerald-900/60 bg-emerald-950/30 p-3 text-emerald-200">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  The phone-line rate covers what Exotel charged
                  {report.gap_percent != null ? ` (difference ${report.gap_percent}%)` : ''}.
                </span>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                ['Calls checked', String(report.calls_priced)],
                ['Choranta estimate', inr(report.estimated_total_inr)],
                ['Exotel charged', inr(report.actual_total_inr)],
                ['Matching rate / min', inr(report.matching_rate_per_minute_inr, 4)],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-[#1b2030] bg-black/30 p-2">
                  <span className="block text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
                  <span className="font-mono text-sm text-slate-200">{value}</span>
                </div>
              ))}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Call</th>
                    <th className="py-1 pr-3 font-medium">Length</th>
                    <th className="py-1 pr-3 text-right font-medium">Estimate</th>
                    <th className="py-1 pr-3 text-right font-medium">Exotel</th>
                    <th className="py-1 text-right font-medium">Gap</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-slate-300">
                  {report.calls.map((c) => (
                    <tr key={c.call_id} className="border-t border-[#1b2030]">
                      <td className="py-1 pr-3">
                        {c.ended_at ? new Date(c.ended_at).toLocaleString() : c.call_id}
                        {c.is_test && <span className="ml-1 text-slate-500">(test)</span>}
                      </td>
                      <td className="py-1 pr-3">{Math.round(c.duration_seconds)}s</td>
                      <td className="py-1 pr-3 text-right">{inr(c.estimated_inr)}</td>
                      <td className="py-1 pr-3 text-right">{inr(c.actual_inr)}</td>
                      <td className={`py-1 text-right ${c.gap_inr > 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
                        {c.gap_inr > 0 ? '+' : ''}
                        {inr(c.gap_inr)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        <p className="leading-relaxed text-slate-500">
          Covers the phone line only; Sarvam doesn't report a price per call, so check its rates against the monthly
          invoice.
          {report?.gst_added ? ' Exotel prices include 18% GST, since Choranta is not GST-registered yet.' : ''}
        </p>
      </div>
    </Card>
  );
};
