import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Clock, Flame, PhoneCall, PhoneForwarded, Sparkles, Timer, Zap } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Stat } from './Stat';
import { CollectedAnswers } from '../campaigns/CollectedAnswers';
import { HotLead, OutboundInsights as Insights, portalService } from '../../services/portal';

const PERIODS = [7, 30, 90];

const pct = (rate: number | null | undefined) => (rate === null || rate === undefined ? '—' : `${Math.round(rate * 100)}%`);

const seconds = (s: number | null | undefined) => {
  if (s === null || s === undefined) return '—';
  if (s < 1) return '<1 s';
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
};

const campaignPath = (kind: string, id: string) => (kind === 'TRIGGER' ? `/portal/instant-outbound/${id}` : `/portal/campaigns/${id}`);

/** Called → answered → interested → callback, each bar sized against the people called. */
const Funnel: React.FC<{ funnel: Insights['funnel'] }> = ({ funnel }) => {
  const stages: Array<[string, number, number, string]> = [
    ['Called', funnel.called, funnel.called, 'bg-indigo-500/70'],
    ['Answered', funnel.answered, funnel.called, 'bg-sky-500/70'],
    ['Interested', funnel.interested, funnel.answered, 'bg-[#00df8f]/80'],
    ['Asked for a call back', funnel.callbacks, funnel.interested, 'bg-amber-500/70'],
  ];
  return (
    <div className="space-y-3">
      {stages.map(([label, count, previous, color], i) => (
        <div key={label}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-slate-300">{label}</span>
            <span className="font-mono text-slate-200">
              {count.toLocaleString('en-IN')}
              {i > 0 && <span className="ml-2 text-slate-500">{previous ? pct(count / previous) : '—'}</span>}
            </span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-[#141a26]">
            <div className={`h-full rounded-full ${color}`} style={{ width: `${funnel.called ? (count / funnel.called) * 100 : 0}%` }} />
          </div>
        </div>
      ))}
      <p className="pt-1 text-[11px] text-slate-500">
        {funnel.not_interested} not interested · {funnel.do_not_call} asked not to be called (added to your do-not-call list)
      </p>
    </div>
  );
};

const HotLeads: React.FC<{ leads: HotLead[]; total: number; onFollowedUp: (id: string) => void }> = ({ leads, total, onFollowedUp }) => {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const markDone = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await portalService.markFollowedUp(id);
      onFollowedUp(id);
    } catch (e: any) {
      setError(e.message || 'Could not update this lead.');
    } finally {
      setBusy(null);
    }
  };

  if (!leads.length) return <p className="py-6 text-center text-xs text-slate-500">No hot leads in this period.</p>;
  return (
    <div className="divide-y divide-[#151a26]">
      {error && <p className="pb-2 text-xs text-rose-400">{error}</p>}
      {leads.map((lead) => (
        <div key={lead.recipient_id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold text-slate-100">{lead.name || 'Unknown'}</span>
              <span className="font-mono text-xs text-slate-400">{lead.phone}</span>
              {lead.interest === 'callback' ? (
                <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                  Call back{lead.callback_time ? `: ${lead.callback_time}` : ''}
                </span>
              ) : (
                <span className="rounded bg-[#00df8f]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[#00df8f]">Interested</span>
              )}
            </div>
            {lead.summary && <p className="text-xs text-slate-300">{lead.summary}</p>}
            <p className="text-[11px] text-slate-500">
              <Link to={campaignPath(lead.campaign_kind, lead.campaign_id)} className="hover:text-slate-300 hover:underline">
                {lead.campaign_name}
              </Link>{' '}
              · {new Date(lead.called_at + 'Z').toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            {lead.call_id && (
              <Link to={`/portal/calls?call=${lead.call_id}`}>
                <Button size="sm" variant="secondary">View call</Button>
              </Link>
            )}
            <Button
              size="sm"
              variant="secondary"
              isLoading={busy === lead.recipient_id}
              leftIcon={<CheckCircle2 className="h-3.5 w-3.5" />}
              onClick={() => markDone(lead.recipient_id)}
            >
              Followed up
            </Button>
          </div>
        </div>
      ))}
      {total > leads.length && <p className="pt-3 text-[11px] text-slate-500">Showing the latest {leads.length} of {total}.</p>}
    </div>
  );
};

/** Answer rate per local hour within calling hours. */
const BestHours: React.FC<{ hours: Insights['best_hours'] }> = ({ hours }) => {
  const best = hours.reduce<Insights['best_hours'][number] | null>(
    (top, h) => (h.attempts >= 3 && (h.answer_rate ?? 0) > (top?.answer_rate ?? -1) ? h : top),
    null
  );
  return (
    <div>
      <div className="flex h-28 items-end gap-1.5">
        {hours.map((h) => (
          <div key={h.hour} className="group relative flex-1">
            <div
              className={`w-full rounded-t ${h === best ? 'bg-[#00df8f]/80' : 'bg-sky-500/60'}`}
              style={{ height: `${Math.max(2, (h.answer_rate ?? 0) * 112)}px`, opacity: h.attempts ? 1 : 0.25 }}
            />
            <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded bg-black/90 px-2 py-1 text-[10px] text-slate-200 group-hover:block">
              {h.hour}:00 · {pct(h.answer_rate)} answered of {h.attempts} dials
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        {hours.map((h) => (
          <span key={h.hour} className="flex-1 text-center">{h.hour}</span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        {best ? `People answer most at ${best.hour}:00–${best.hour + 1}:00 (${pct(best.answer_rate)}).` : 'Not enough calls yet to compare hours.'}
      </p>
    </div>
  );
};

/** Outbound insights for the client dashboard: campaigns and instant website-lead calls together. */
export const OutboundInsights: React.FC = () => {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    portalService
      .insights(days)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message || 'Could not load outbound insights.'));
  }, [days]);

  useEffect(load, [load]);

  if (error) return <p className="text-xs text-rose-400">{error}</p>;
  if (!data || !data.has_outbound) return null;
  const { funnel, instant } = data;

  const removeHotLead = (id: string) =>
    setData((d) => d && { ...d, hot_leads: d.hot_leads.filter((l) => l.recipient_id !== id), hot_leads_total: d.hot_leads_total - 1 });

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold">
            <Sparkles className="h-4 w-4 text-[#00df8f]" /> Outbound insights
          </h2>
          <p className="text-xs text-slate-400">Your campaigns and instant website-lead calls</p>
        </div>
        <div className="flex rounded-lg border border-[#1b2030] p-0.5 text-xs">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setDays(p)}
              className={`rounded-md px-3 py-1 ${p === days ? 'bg-[#00df8f]/15 text-[#00df8f]' : 'text-slate-400 hover:text-slate-200'}`}
            >
              {p} days
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat icon={<PhoneCall className="h-4 w-4 text-indigo-400" />} label="People called" value={funnel.called.toLocaleString('en-IN')} hint={`${funnel.minutes} min talked`} />
        <Stat icon={<PhoneForwarded className="h-4 w-4 text-sky-400" />} label="Answer rate" value={pct(funnel.answer_rate)} hint={`${funnel.answered} answered`} />
        <Stat icon={<Flame className="h-4 w-4 text-[#00df8f]" />} label="Interested" value={String(funnel.interested)} hint={`${funnel.callbacks} want a call back`} />
        <Stat icon={<Clock className="h-4 w-4 text-amber-400" />} label="Avg. talk time" value={seconds(funnel.avg_talk_seconds)} hint="answered calls" />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Outcome funnel" subtitle={`Last ${days} days`}>
          <Funnel funnel={funnel} />
        </Card>
        {instant ? (
          <Card title="Instant website leads" subtitle="How fast new leads were called">
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <p className="flex items-center gap-1 text-slate-400"><Zap className="h-3.5 w-3.5 text-[#00df8f]" /> Median time to call</p>
                <p className="mt-1 font-mono text-2xl font-bold text-slate-100">{seconds(instant.median_seconds_to_call)}</p>
              </div>
              <div>
                <p className="flex items-center gap-1 text-slate-400"><Timer className="h-3.5 w-3.5 text-sky-400" /> Called within 1 min</p>
                <p className="mt-1 font-mono text-2xl font-bold text-slate-100">{pct(instant.called_within_60s_pct)}</p>
              </div>
              <div>
                <p className="text-slate-400">Leads received</p>
                <p className="mt-1 font-mono text-lg text-slate-200">{instant.leads}</p>
              </div>
              <div>
                <p className="text-slate-400">Reached · interested</p>
                <p className="mt-1 font-mono text-lg text-slate-200">{instant.reached} · {instant.interested}</p>
              </div>
            </div>
            {instant.queued_for_hours > 0 && (
              <p className="mt-3 text-[11px] text-slate-500">
                {instant.queued_for_hours} lead{instant.queued_for_hours === 1 ? '' : 's'} arrived outside calling hours and{' '}
                {instant.queued_for_hours === 1 ? 'was' : 'were'} called when the window opened (not counted in the timings).
              </p>
            )}
          </Card>
        ) : (
          <Card title="Best time to call" subtitle="Answer rate by hour (local time)">
            <BestHours hours={data.best_hours} />
          </Card>
        )}
      </div>

      <Card
        title={`Hot leads to follow up${data.hot_leads_total ? ` (${data.hot_leads_total})` : ''}`}
        subtitle="Interested or asked for a call back. Mark them once your team has followed up."
      >
        <HotLeads leads={data.hot_leads} total={data.hot_leads_total} onFollowedUp={removeHotLead} />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {instant && (
          <Card title="Best time to call" subtitle="Answer rate by hour (local time)">
            <BestHours hours={data.best_hours} />
          </Card>
        )}
        {Object.keys(data.top_answers).length > 0 && (
          <Card title="What people told your AI employee" subtitle="Most common answers on answered calls" className={instant ? '' : 'md:col-span-2'}>
            <CollectedAnswers collected={data.top_answers} columns={instant ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'} />
          </Card>
        )}
      </div>

      {data.campaigns.length > 0 && (
        <Card title="Campaigns compared" subtitle={`Last ${days} days`} noPadding>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-[#1f2433] text-slate-400">
                <tr>
                  <th className="px-4 py-3">Campaign</th>
                  <th className="px-4 py-3 text-right">Called</th>
                  <th className="px-4 py-3 text-right">Answer rate</th>
                  <th className="px-4 py-3 text-right">Interested</th>
                  <th className="px-4 py-3 text-right">Minutes</th>
                </tr>
              </thead>
              <tbody>
                {data.campaigns.map((c) => (
                  <tr key={c.id} className="border-b border-[#151a26]">
                    <td className="px-4 py-3">
                      <Link to={campaignPath(c.kind, c.id)} className="text-slate-200 hover:text-[#00df8f] hover:underline">
                        {c.name}
                      </Link>
                      <span className="ml-2 text-[10px] text-slate-500">{c.kind === 'TRIGGER' ? 'Instant' : 'Bulk'} · {c.status.toLowerCase()}</span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">{c.called}</td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">{pct(c.answer_rate)}</td>
                    <td className="px-4 py-3 text-right font-mono text-[#00df8f]">{c.interested}</td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">{c.minutes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </section>
  );
};
