import React from 'react';
import { inr, WalletTransaction } from '../../services/portal';

const TYPE_STYLES: Record<WalletTransaction['type'], string> = {
  CREDIT: 'text-emerald-300',
  DEBIT: 'text-slate-300',
  ADJUSTMENT: 'text-sky-300',
};

/** Wallet ledger table shared by the admin billing card and the client portal. */
export const WalletLedger: React.FC<{ transactions: WalletTransaction[] }> = ({ transactions }) => (
  <div className="max-h-96 overflow-auto">
    <table className="w-full text-left text-xs">
      <thead className="sticky top-0 border-b border-[#1f2433] bg-[#0c0e14] text-slate-400">
        <tr>
          <th className="px-4 py-2.5">Date</th>
          <th className="px-4 py-2.5">Description</th>
          <th className="px-4 py-2.5 text-right">Amount</th>
          <th className="px-4 py-2.5 text-right">Balance</th>
        </tr>
      </thead>
      <tbody>
        {transactions.length === 0 && (
          <tr>
            <td colSpan={4} className="px-4 py-6 text-center text-slate-500">No wallet activity yet.</td>
          </tr>
        )}
        {transactions.map((t) => (
          <tr key={t.id} className="border-b border-[#151a26]">
            <td className="px-4 py-2.5 text-slate-400">{new Date(t.created_at).toLocaleString('en-IN')}</td>
            <td className="px-4 py-2.5 text-slate-300">
              {t.note || t.type}
              {t.reference && <span className="ml-1 text-slate-500">· {t.reference}</span>}
            </td>
            <td className={`px-4 py-2.5 text-right font-mono ${TYPE_STYLES[t.type]}`}>
              {t.amount_inr > 0 ? '+' : ''}
              {inr(t.amount_inr)}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-slate-400">{inr(t.balance_after_inr)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);
