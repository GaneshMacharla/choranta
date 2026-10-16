import React, { useState } from 'react';
import { Link2, Pencil, Unlink } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Select } from '../common/Select';
import { StringListEditor } from './StringListEditor';
import { AgentInstructions } from '../../types';
import { StandardCallScript, callScriptsService } from '../../services/callScripts';

const FIELD =
  'block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';

type ScriptContent = Pick<StandardCallScript, 'discovery_questions' | 'offer_points' | 'next_step'>;

const contentOf = (s: Partial<ScriptContent>): ScriptContent => ({
  discovery_questions: s.discovery_questions || [],
  offer_points: s.offer_points || [],
  next_step: s.next_step || '',
});

const sameContent = (a: ScriptContent, b: ScriptContent) => JSON.stringify(contentOf(a)) === JSON.stringify(contentOf(b));

interface CallScriptCardProps {
  instructions: AgentInstructions;
  setInstructions: (patch: Partial<AgentInstructions>) => void;
  /** Standard scripts (null while loading) */
  standards: StandardCallScript[] | null;
  onStandardSaved: (script: StandardCallScript) => void;
  isAdmin: boolean;
  /** The latest published version's instructions, to tell whether a standard script change is published yet */
  publishedInstructions?: Partial<AgentInstructions> | null;
}

/**
 * Section 4 of the workspace. An employee either uses a standard script (shared, admin-maintained, taken on
 * publish) or its own script. Admins can edit the standard, give one employee its own copy, or link it back.
 */
export const CallScriptCard: React.FC<CallScriptCardProps> = ({
  instructions: ins, setInstructions, standards, onStandardSaved, isAdmin, publishedInstructions,
}) => {
  const [editing, setEditing] = useState<ScriptContent | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const linked = standards?.find((s) => s.key === ins.script_source) || null;
  const outdated =
    !!linked && !!publishedInstructions && !sameContent(linked, publishedInstructions as ScriptContent);

  const saveStandard = async () => {
    if (!linked || !editing) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await callScriptsService.update(linked.key, editing);
      onStandardSaved(saved);
      setInstructions(contentOf(saved)); // keep this draft's copy in step
      setEditing(null);
    } catch (err: any) {
      setError(err?.message || 'Could not save the standard script.');
    } finally {
      setSaving(false);
    }
  };

  const subtitle = 'What it asks (in order), what it mentions, and the step it agrees. It skips anything already known.';

  // ---- Linked to a standard script ----
  if (linked) {
    return (
      <Card title="4. Call script" subtitle={subtitle}>
        <div className="space-y-4 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#0a4d39] bg-[#052b20] p-3">
            <span className="flex items-center gap-2 text-slate-200">
              <Link2 className="h-4 w-4 text-[#00df8f]" />
              Uses the standard <strong>{linked.name}</strong> script, shared by every employee linked to it.
            </span>
            {isAdmin && !editing && (
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => setEditing(contentOf(linked))}>
                  <Pencil className="mr-1.5 h-3.5 w-3.5" /> Edit standard script
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setInstructions({ ...contentOf(linked), script_source: '' })}
                  title="Give this employee its own copy that you can change without affecting others"
                >
                  <Unlink className="mr-1.5 h-3.5 w-3.5" /> Customise for this agent
                </Button>
              </div>
            )}
          </div>

          {outdated && !editing && (
            <p className="rounded border border-amber-800/50 bg-amber-950/30 p-2.5 text-amber-200">
              The standard script changed after this employee was last published. Publish to start using it on calls.
            </p>
          )}

          {editing ? (
            <div className="space-y-4 rounded-lg border border-[#153945] p-3">
              <p className="text-amber-200">
                Editing the standard script for every linked employee. Each one uses the change from its next publish.
              </p>
              <StringListEditor label="Questions to ask" items={editing.discovery_questions}
                placeholder="e.g. Which area are you looking in?" onChange={(items) => setEditing({ ...editing, discovery_questions: items })}
                emptyText="No questions yet." />
              <StringListEditor label="Points to mention (only the ones that fit)" items={editing.offer_points}
                placeholder="e.g. Possession timeline and RERA approval" onChange={(items) => setEditing({ ...editing, offer_points: items })}
                emptyText="No points yet." />
              <label className="block space-y-1">
                <span className="font-medium text-slate-300">Next step to agree</span>
                <input className={FIELD} value={editing.next_step} placeholder="e.g. Book a site visit"
                  onChange={(e) => setEditing({ ...editing, next_step: e.target.value })} />
              </label>
              {error && <p className="text-rose-300">{error}</p>}
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => { setEditing(null); setError(null); }}>Cancel</Button>
                <Button size="sm" variant="primary" isLoading={saving} onClick={saveStandard}
                  disabled={!editing.discovery_questions.length || !editing.next_step.trim()}>
                  Save standard script
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <span className="mb-1 block font-medium text-slate-300">Questions to ask</span>
                <ol className="list-decimal space-y-1 pl-5 text-slate-200">
                  {linked.discovery_questions.map((q, i) => <li key={i}>{q}</li>)}
                </ol>
              </div>
              {linked.offer_points.length > 0 && (
                <div>
                  <span className="mb-1 block font-medium text-slate-300">Points to mention (only the ones that fit)</span>
                  <ul className="list-disc space-y-1 pl-5 text-slate-200">
                    {linked.offer_points.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
              )}
              <div>
                <span className="mb-1 block font-medium text-slate-300">Next step to agree</span>
                <p className="text-slate-200">{linked.next_step}</p>
              </div>
              {!isAdmin && <p className="text-[11px] text-slate-500">Only admins can change the standard script.</p>}
            </div>
          )}
        </div>
      </Card>
    );
  }

  // ---- Its own script ----
  const linkable = (standards || []).filter((s) => s.key !== ins.script_source);
  return (
    <Card title="4. Call script" subtitle={subtitle}>
      <div className="space-y-4">
        {isAdmin && linkable.length > 0 && (
          <div className="max-w-sm">
            <Select
              label="Use a standard script instead"
              placeholder="This employee's own script"
              options={linkable.map((s) => ({ value: s.key, label: s.name }))}
              value=""
              onChange={(e) => {
                const pick = linkable.find((s) => s.key === e.target.value);
                if (pick) setInstructions({ ...contentOf(pick), script_source: pick.key });
              }}
              helperText="Shared with other employees and kept up to date by admins."
            />
          </div>
        )}
        <StringListEditor label="Questions to ask" items={ins.discovery_questions || []} placeholder="e.g. Would online or classroom suit you better?"
          onChange={(items) => setInstructions({ discovery_questions: items })} emptyText="No questions yet." />
        <StringListEditor label="Points to mention (only the ones that fit)" items={ins.offer_points || []} placeholder="e.g. New batch starts Monday"
          onChange={(items) => setInstructions({ offer_points: items })} emptyText="No points yet." />
        <label className="block space-y-1">
          <span className="text-xs font-medium text-slate-300">Next step to agree</span>
          <input className={FIELD} value={ins.next_step || ''} placeholder="e.g. Book a free demo class"
            onChange={(e) => setInstructions({ next_step: e.target.value })} />
        </label>
      </div>
    </Card>
  );
};
