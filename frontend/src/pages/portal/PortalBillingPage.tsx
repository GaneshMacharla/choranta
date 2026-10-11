import React, { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { inr, InvoiceSummary, portalService, Wallet } from '../../services/portal';
import { WalletLedger } from '../../components/billing/WalletLedger';

export const PortalBillingPage: React.FC = () => {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([portalService.wallet(), portalService.invoices()])
      .then(([w, i]) => {
        setWallet(w);
        setInvoices(i);
      })
      .catch((err) => setError(err.message || 'Could not load billing.'));
  }, []);

  const download = async (invoice: InvoiceSummary) => {
    setDownloading(invoice.id);
    try {
      await portalService.downloadInvoice(invoice);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setDownloading(null);
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!wallet) return <LoadingState message="Loading billing..." />;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-xl font-bold">Billing</h1>
        <p className="text-sm">
          Wallet balance: <span className="font-mono font-bold text-[#00df8f]">{inr(wallet.balance_inr)}</span>
          <span className="ml-1 text-xs text-slate-500">(excl. GST)</span>
        </p>
      </div>

      <Card title="Invoices" subtitle="GST tax invoices for your recharges" noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#1f2433] text-slate-400">
              <tr>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Taxable</th>
                <th className="px-4 py-3">GST</th>
                <th className="px-4 py-3">Total</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-500">No invoices yet.</td>
                </tr>
              )}
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-b border-[#151a26] text-slate-300">
                  <td className="px-4 py-3 font-mono">{inv.number}</td>
                  <td className="px-4 py-3">{new Date(inv.issue_date).toLocaleDateString('en-IN')}</td>
                  <td className="px-4 py-3 font-mono">{inr(inv.taxable_inr)}</td>
                  <td className="px-4 py-3 font-mono">{inr(inv.cgst_inr + inv.sgst_inr + inv.igst_inr)}</td>
                  <td className="px-4 py-3 font-mono font-semibold">{inr(inv.total_inr)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button size="sm" variant="secondary" isLoading={downloading === inv.id} onClick={() => download(inv)}>
                      <Download className="mr-1 h-3.5 w-3.5" /> PDF
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Wallet activity" subtitle="Recharges and call charges" noPadding>
        <WalletLedger transactions={wallet.transactions} />
      </Card>
    </div>
  );
};
