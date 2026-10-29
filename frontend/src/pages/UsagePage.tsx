import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowDownLeft, IndianRupee, Info, Receipt, TrendingUp, Wallet } from 'lucide-react';
import { Card } from '../components/common/Card';
import { Badge } from '../components/common/Badge';
import { FinanceBucket, FinancePeriod, FinanceSummary, financeService, rupees } from '../services/finance';

const PERIODS: { value: FinancePeriod; label: string }[] = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: 'month', label: 'This month' },
];

// Categorical slots 1-3 stepped for the dark surface, checked with the dataviz palette validator
const SERIES = {
  revenue: { label: 'Revenue', color: '#3987e5' },
  cost: { label: 'Cost', color: '#d95926' },
  profit: { label: 'Profit', color: '#199e70' },
} as const;

const pct = (value: number | null) => (value === null ? '—' : `${value.toLocaleString('en-IN', { maximumFractionDigits: 1 })}%`);

const bucketLabel = (bucket: string, long = false) => {
  const [y, m, d] = bucket.split('-').map(Number);
  const date = new Date(y, m - 1, d || 1);
  if (!d) return date.toLocaleDateString('en-IN', { month: 'short', year: long ? 'numeric' : '2-digit' });
  return date.toLocaleDateString('en-IN', long ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short' });
};

export const UsagePage: React.FC = () => {
  const [period, setPeriod] = useState<FinancePeriod>('30d');
  const [data, setData] = useState<FinanceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    financeService
      .summary(period)
      .then((res) => live && setData(res))
      .catch((err) => live && setError(err.message || 'Could not load finance figures.'))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [period]);

  const empty = data && data.money_in.total === 0 && data.revenue.total === 0 && data.cost.total === 0;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
            <IndianRupee className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-100">Finance</h1>
            <p className="text-xs text-slate-400 mt-0.5">Money collected, revenue earned, what it cost and the profit, across all clients.</p>
          </div>
        </div>
        <div role="radiogroup" aria-label="Period" className="flex rounded-lg border border-[#143c49] bg-[#091b22] p-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              role="radio"
              aria-checked={period === p.value}
              onClick={() => setPeriod(p.value)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                period === p.value ? 'bg-[#00df8f]/15 text-[#00df8f]' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-800/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {!data && loading && <div className="py-16 text-center text-sm text-slate-500">Loading finance figures…</div>}

      {data && (
        <div className={`space-y-6 transition-opacity ${loading ? 'opacity-60' : ''}`}>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Kpi
              label="Money in"
              value={rupees(data.money_in.total)}
              icon={<ArrowDownLeft className="h-4 w-4" />}
              note={`${rupees(data.money_in.taxable)} credits + ${rupees(data.money_in.gst)} GST`}
            />
            <Kpi
              label="Revenue"
              value={rupees(data.revenue.total)}
              icon={<Receipt className="h-4 w-4" />}
              note={`${data.calls.count} billed calls · ${data.calls.minutes.toLocaleString('en-IN')} min`}
            />
            <Kpi label="Cost" value={rupees(data.cost.total)} icon={<Wallet className="h-4 w-4" />} note="Carrier, speech, AI model and number rent" />
            <Kpi
              label="Profit"
              value={rupees(data.profit)}
              icon={<TrendingUp className="h-4 w-4" />}
              note={`Margin ${pct(data.margin_pct)}`}
              negative={data.profit < 0}
            />
          </div>

          {empty ? (
            <Card>
              <div className="py-10 text-center text-sm text-slate-400">
                No payments, charges or billed calls in this period yet.
              </div>
            </Card>
          ) : (
            <>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                  <div>
                    <h2 className="text-sm font-semibold text-slate-100">Revenue, cost and profit</h2>
                    <p className="text-xs text-slate-400">Per {data.granularity === 'month' ? 'month' : 'day'}, in ₹ (excl. GST)</p>
                  </div>
                  <Legend />
                </div>
                <TrendChart trend={data.trend} />
              </Card>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Card>
                  <h2 className="text-sm font-semibold text-slate-100 mb-4">Revenue by source</h2>
                  <Breakdown
                    total={data.revenue.total}
                    rows={[
                      ['Call charges', data.revenue.calls],
                      ['Number rent', data.revenue.number_rent],
                      ['Number setup fees', data.revenue.number_setup],
                      ['WhatsApp messages', data.revenue.whatsapp],
                      ['Plans', data.revenue.plans],
                      ['Other', data.revenue.other],
                    ]}
                  />
                </Card>
                <Card>
                  <h2 className="text-sm font-semibold text-slate-100 mb-4">Cost by component</h2>
                  <Breakdown
                    total={data.cost.total}
                    rows={[
                      ['Carrier minutes', data.cost.telephony],
                      ['Speech-to-text', data.cost.speech_to_text],
                      ['Text-to-speech', data.cost.text_to_speech],
                      ['AI model', data.cost.llm],
                      ['Number rent (carrier)', data.cost.number_rent],
                    ]}
                  />
                </Card>
              </div>
            </>
          )}

          <Card>
            <h2 className="text-sm font-semibold text-slate-100 mb-4">By client</h2>
            {data.clients.length === 0 ? (
              <p className="text-sm text-slate-400">No client activity in this period.</p>
            ) : (
              <div className="overflow-x-auto -mx-2">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                      <th className="px-2 py-2 font-medium">Client</th>
                      <th className="px-2 py-2 font-medium text-right">Money in</th>
                      <th className="px-2 py-2 font-medium text-right">Revenue</th>
                      <th className="px-2 py-2 font-medium text-right">Cost</th>
                      <th className="px-2 py-2 font-medium text-right">Profit</th>
                      <th className="px-2 py-2 font-medium text-right">Margin</th>
                      <th className="px-2 py-2 font-medium text-right">Wallet</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#102d38]">
                    {data.clients.map((c) => (
                      <tr key={c.client_id} className="hover:bg-[#0c242d]">
                        <td className="px-2 py-2.5">
                          <Link to={`/clients/${c.client_id}`} className="font-medium text-slate-100 hover:text-[#00df8f]">
                            {c.name}
                          </Link>
                        </td>
                        <td className="px-2 py-2.5 text-right font-mono text-slate-300">{rupees(c.money_in)}</td>
                        <td className="px-2 py-2.5 text-right font-mono text-slate-300">{rupees(c.revenue)}</td>
                        <td className="px-2 py-2.5 text-right font-mono text-slate-300">{rupees(c.cost)}</td>
                        <td className={`px-2 py-2.5 text-right font-mono ${c.profit < 0 ? 'text-rose-300' : 'text-slate-100'}`}>{rupees(c.profit)}</td>
                        <td className="px-2 py-2.5 text-right font-mono text-slate-400">{pct(c.margin_pct)}</td>
                        <td className="px-2 py-2.5 text-right">
                          <span className="inline-flex items-center gap-2 font-mono text-slate-300">
                            {c.low_balance && (
                              <Badge variant="yellow" size="sm">
                                <AlertTriangle className="h-3 w-3" /> Low
                              </Badge>
                            )}
                            {rupees(c.wallet_balance)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="flex items-start gap-2 text-xs text-slate-500">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <p>
              Call cost is estimated from the configured provider rates (the same ones calls are charged from), not a carrier
              invoice; compare with Settings → Carrier cost check. Revenue and cost exclude GST; test calls aren't counted.
              {data.mock_numbers > 0 && ` Includes ${data.mock_numbers} simulated (mock mode) number${data.mock_numbers === 1 ? '' : 's'}.`}
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

const Kpi: React.FC<{ label: string; value: string; note: string; icon: React.ReactNode; negative?: boolean }> = ({
  label, value, note, icon, negative,
}) => (
  <Card className="relative overflow-hidden border-l-4 border-l-[#00df8f]">
    <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
      <span className="font-medium uppercase tracking-wider text-[11px]">{label}</span>
      <span className="text-[#00df8f]">{icon}</span>
    </div>
    <div className={`text-2xl font-bold font-mono ${negative ? 'text-rose-300' : 'text-slate-100'}`}>{value}</div>
    <div className="mt-2 text-[11px] text-slate-500">{note}</div>
  </Card>
);

const Legend: React.FC = () => (
  <div className="flex items-center gap-4 text-xs text-slate-300">
    {(['revenue', 'cost'] as const).map((k) => (
      <span key={k} className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[k].color }} />
        {SERIES[k].label}
      </span>
    ))}
    <span className="flex items-center gap-1.5">
      <svg width="16" height="8" aria-hidden>
        <line x1="0" y1="4" x2="16" y2="4" stroke={SERIES.profit.color} strokeWidth="2" />
        <circle cx="8" cy="4" r="3" fill={SERIES.profit.color} />
      </svg>
      {SERIES.profit.label}
    </span>
  </div>
);

const Breakdown: React.FC<{ rows: [string, number][]; total: number }> = ({ rows, total }) => {
  const shown = rows.filter(([, v]) => v > 0);
  if (shown.length === 0) return <p className="text-sm text-slate-400">Nothing in this period.</p>;
  const max = Math.max(...shown.map(([, v]) => v));
  return (
    <ul className="space-y-3">
      {shown.map(([label, value]) => (
        <li key={label}>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-300">{label}</span>
            <span className="font-mono text-slate-100">
              {rupees(value)} <span className="text-slate-500">· {total > 0 ? Math.round((value / total) * 100) : 0}%</span>
            </span>
          </div>
          <div className="h-2 rounded bg-[#0c242d]">
            <div className="h-2 rounded" style={{ width: `${(value / max) * 100}%`, background: SERIES.revenue.color }} />
          </div>
        </li>
      ))}
    </ul>
  );
};

const HEIGHT = 240;
const PAD = { top: 12, right: 12, bottom: 28, left: 56 };

/** Grouped revenue/cost bars per bucket with the profit line on the same ₹ axis; hover shows the bucket's values. */
const TrendChart: React.FC<{ trend: FinanceBucket[] }> = ({ trend }) => {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [asTable]);

  const scale = useMemo(() => {
    const hi = Math.max(1, ...trend.flatMap((b) => [b.revenue, b.cost, b.profit]));
    const lo = Math.min(0, ...trend.map((b) => b.profit));
    const step = niceStep((hi - lo) / 4);
    const top = Math.ceil(hi / step) * step;
    const bottom = Math.floor(lo / step) * step;
    const ticks: number[] = [];
    for (let v = bottom; v <= top + step / 2; v += step) ticks.push(v);
    return { top, bottom, ticks };
  }, [trend]);

  if (asTable) {
    return (
      <div>
        <ToggleView asTable onToggle={() => setAsTable(false)} />
        <div className="overflow-x-auto max-h-80">
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="py-1.5 pr-2 font-medium">Date</th>
                <th className="py-1.5 px-2 font-medium text-right">Revenue</th>
                <th className="py-1.5 px-2 font-medium text-right">Cost</th>
                <th className="py-1.5 pl-2 font-medium text-right">Profit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#102d38] font-mono text-slate-300">
              {trend.map((b) => (
                <tr key={b.bucket}>
                  <td className="py-1.5 pr-2 font-sans">{bucketLabel(b.bucket, true)}</td>
                  <td className="py-1.5 px-2 text-right">{rupees(b.revenue)}</td>
                  <td className="py-1.5 px-2 text-right">{rupees(b.cost)}</td>
                  <td className="py-1.5 pl-2 text-right">{rupees(b.profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const band = plotW / Math.max(1, trend.length);
  const y = (v: number) => PAD.top + ((scale.top - v) / (scale.top - scale.bottom || 1)) * plotH;
  const barW = Math.max(1, Math.min(18, (band - 6) / 2 - 1));
  const labelEvery = Math.ceil(trend.length / Math.max(2, Math.floor(plotW / 64)));
  const cx = (i: number) => PAD.left + band * i + band / 2;
  const hovered = hover !== null ? trend[hover] : null;

  return (
    <div>
      <ToggleView asTable={false} onToggle={() => setAsTable(true)} />
      <div ref={wrap} className="relative" onMouseLeave={() => setHover(null)}>
        <svg width={width} height={HEIGHT} role="img" aria-label="Revenue, cost and profit over time">
          {scale.ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? '#2a4a55' : '#102d38'} strokeWidth={1} />
              <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize="10" fill="#64748b">
                {compactRupees(t)}
              </text>
            </g>
          ))}
          {hover !== null && <rect x={PAD.left + band * hover} y={PAD.top} width={band} height={plotH} fill="#ffffff" opacity={0.04} />}
          {trend.map((b, i) => (
            <g key={b.bucket}>
              <Bar x={cx(i) - barW - 1} w={barW} y0={y(0)} y1={y(b.revenue)} color={SERIES.revenue.color} />
              <Bar x={cx(i) + 1} w={barW} y0={y(0)} y1={y(b.cost)} color={SERIES.cost.color} />
              {i % labelEvery === 0 && (
                <text x={cx(i)} y={HEIGHT - 8} textAnchor="middle" fontSize="10" fill="#64748b">
                  {bucketLabel(b.bucket)}
                </text>
              )}
            </g>
          ))}
          <polyline
            points={trend.map((b, i) => `${cx(i)},${y(b.profit)}`).join(' ')}
            fill="none"
            stroke={SERIES.profit.color}
            strokeWidth={2}
            strokeLinejoin="round"
          />
          {trend.map((b, i) =>
            trend.length <= 31 || i === hover ? (
              <circle key={b.bucket} cx={cx(i)} cy={y(b.profit)} r={hover === i ? 5 : 3.5} fill={SERIES.profit.color} stroke="#091b22" strokeWidth={2} />
            ) : null,
          )}
          {trend.map((b, i) => (
            <rect key={b.bucket} x={PAD.left + band * i} y={PAD.top} width={band} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} />
          ))}
        </svg>
        {hovered && hover !== null && (
          <div
            className="pointer-events-none absolute top-2 z-10 min-w-[150px] rounded-lg border border-[#143c49] bg-[#061419] px-3 py-2 text-xs shadow-xl"
            style={cx(hover) > width / 2 ? { right: width - cx(hover) + 12 } : { left: cx(hover) + 12 }}
          >
            <div className="mb-1 font-medium text-slate-200">{bucketLabel(hovered.bucket, true)}</div>
            {(['revenue', 'cost', 'profit'] as const).map((k) => (
              <div key={k} className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-1.5 text-slate-400">
                  <span className="h-2 w-2 rounded-sm" style={{ background: SERIES[k].color }} />
                  {SERIES[k].label}
                </span>
                <span className="font-mono text-slate-100">{rupees(hovered[k])}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/** A bar from the zero baseline, with 4px rounding on its data end only. */
const Bar: React.FC<{ x: number; w: number; y0: number; y1: number; color: string }> = ({ x, w, y0, y1, color }) => {
  const h = Math.abs(y0 - y1);
  if (h < 0.5) return null;
  const r = Math.min(4, w / 2, h);
  const top = Math.min(y0, y1);
  const d = `M${x},${top + h} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${top + h} Z`;
  return <path d={d} fill={color} />;
};

const ToggleView: React.FC<{ asTable: boolean; onToggle: () => void }> = ({ asTable, onToggle }) => (
  <div className="flex justify-end -mt-2 mb-1">
    <button onClick={onToggle} className="text-[11px] text-slate-400 hover:text-slate-200 underline-offset-2 hover:underline">
      {asTable ? 'Show chart' : 'Show as table'}
    </button>
  </div>
);

const niceStep = (raw: number) => {
  if (raw <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
};

const compactRupees = (v: number) => {
  const a = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (a >= 100000) return `${sign}₹${(a / 100000).toLocaleString('en-IN', { maximumFractionDigits: 1 })}L`;
  if (a >= 1000) return `${sign}₹${(a / 1000).toLocaleString('en-IN', { maximumFractionDigits: 1 })}k`;
  return `${sign}₹${a.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
};
