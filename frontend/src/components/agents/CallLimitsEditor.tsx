import React from 'react';
import { Info } from 'lucide-react';
import { AgentCallLimits } from '../../types';
import { Input } from '../common/Input';
import { StringListEditor } from './StringListEditor';

interface CallLimitsEditorProps {
  limits: AgentCallLimits;
  onChange: (limits: AgentCallLimits) => void;
}

type NumericLimit = Exclude<keyof AgentCallLimits, 'end_call_phrases'>;

// Platform defaults mirror backend settings (CALL_*, VOICE_MAX_REPLY_CHARS, MAX_TOOL_ROUNDS)
const FIELDS: { key: NumericLimit; label: string; unit: string; min: number; max: number; step: number; fallback: string; help: string }[] = [
  { key: 'max_call_duration_s', label: 'Max call duration', unit: 'seconds', min: 60, max: 3600, step: 30, fallback: '600', help: 'Agent says goodbye and hangs up after this long.' },
  { key: 'silence_reprompt_s', label: 'Ask "Are you still there?" after', unit: 'seconds of silence', min: 3, max: 60, step: 1, fallback: '8', help: 'How long to wait for a silent caller before checking in.' },
  { key: 'silence_hangup_s', label: 'Hang up after a further', unit: 'seconds of silence', min: 3, max: 120, step: 1, fallback: '8', help: 'Ends dead-air calls you would otherwise pay for.' },
  { key: 'max_reply_chars', label: 'Max reply length', unit: 'characters', min: 80, max: 1000, step: 20, fallback: '280', help: 'Long replies are cut after the sentence that crosses this. Voice is billed per character.' },
  { key: 'max_tool_rounds', label: 'Max tool steps per turn', unit: 'steps', min: 1, max: 6, step: 1, fallback: '4', help: 'Each step is an extra AI model call.' },
];

/** Per-agent cost controls. A blank field uses the platform default. */
export const CallLimitsEditor: React.FC<CallLimitsEditorProps> = ({ limits, onChange }) => {
  const setNumber = (key: NumericLimit, raw: string) => {
    const parsed = raw.trim() === '' ? null : Number(raw);
    onChange({ ...limits, [key]: parsed === null || Number.isNaN(parsed) ? null : parsed });
  };

  const outOfRange = (key: NumericLimit, min: number, max: number) => {
    const value = limits[key];
    return value !== null && (value < min || value > max) ? `Must be between ${min} and ${max}` : undefined;
  };

  return (
    <div className="space-y-5 text-xs">
      <div className="flex items-start gap-2 rounded-md border border-[#1b3a33] bg-[#0b1a17] p-3 text-[11px] text-emerald-200/90">
        <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span>Shorter limits lower the cost of every call. Leave a field blank to use the platform default.</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {FIELDS.map((f) => (
          <Input
            key={f.key}
            type="number"
            label={`${f.label} (${f.unit})`}
            min={f.min}
            max={f.max}
            step={f.step}
            placeholder={`Default (${f.fallback})`}
            value={limits[f.key] ?? ''}
            onChange={(e) => setNumber(f.key, e.target.value)}
            error={outOfRange(f.key, f.min, f.max)}
            helperText={f.help}
          />
        ))}
      </div>

      <StringListEditor
        label="End-call phrases"
        items={limits.end_call_phrases}
        onChange={(end_call_phrases) => onChange({ ...limits, end_call_phrases })}
        placeholder='e.g. not interested'
        emptyText="No end-call phrases. The AI decides when to end the call."
        helperText="If the caller says one of these in a short reply (6 words or fewer), the agent says its farewell and hangs up without an AI model call."
      />
    </div>
  );
};

/** True when every numeric limit is blank or within its allowed range. */
export const callLimitsValid = (limits: AgentCallLimits): boolean =>
  FIELDS.every((f) => {
    const value = limits[f.key];
    return value === null || (value >= f.min && value <= f.max);
  });
