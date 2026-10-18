import React, { useEffect, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { Card } from '../common/Card';
import { configurationService, SystemPromptPreview } from '../../services/configuration';
import { AgentConfigurationData } from '../../types';

interface SystemPromptPanelProps {
  agentId: string;
  config: AgentConfigurationData;
  isDirty: boolean;
}

const pill = (active: boolean) =>
  `rounded-full px-3 py-1 text-xs font-medium transition-colors ${
    active ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300 hover:text-slate-100'
  }`;

/** The exact system prompt the LLM receives on a call, rebuilt as the draft changes (unsaved edits included). */
export const SystemPromptPanel: React.FC<SystemPromptPanelProps> = ({ agentId, config, isDirty }) => {
  const [outbound, setOutbound] = useState(false);
  const [preview, setPreview] = useState<SystemPromptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        setPreview(await configurationService.getSystemPrompt(agentId, isDirty ? config : null, outbound));
        setError(null);
      } catch (e: any) {
        setError(e.message || 'Could not build the system prompt.');
      } finally {
        setLoading(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [agentId, config, isDirty, outbound]);

  const copy = async () => {
    if (!preview) return;
    try {
      await navigator.clipboard.writeText(preview.system_prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  return (
    <div className="space-y-6">
      <Card
        title="System prompt"
        subtitle={`What the LLM is told at the start of every call, built from ${isDirty ? 'your unsaved changes' : 'the saved draft'}. Edit it through the Configure tab.`}
        action={
          <div className="flex items-center gap-3">
            <div className="flex rounded-full bg-[#0a2028] p-0.5">
              <button type="button" className={pill(!outbound)} onClick={() => setOutbound(false)}>
                Incoming call
              </button>
              <button type="button" className={pill(outbound)} onClick={() => setOutbound(true)}>
                Outgoing call
              </button>
            </div>
            <button
              type="button"
              onClick={copy}
              disabled={!preview}
              className="flex items-center gap-1.5 rounded-lg border border-[#232736] px-2.5 py-1.5 text-xs text-slate-300 hover:text-slate-100 disabled:opacity-50"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-[#00df8f]" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        }
      >
        {error && <p className="mb-3 text-xs text-red-400">{error}</p>}
        {!preview && loading && <p className="text-xs text-slate-500">Building the prompt...</p>}
        {preview && (
          <div className={`space-y-4 transition-opacity ${loading ? 'opacity-60' : ''}`}>
            <p className="text-xs text-slate-500">
              {preview.system_prompt.length.toLocaleString()} characters · about{' '}
              {Math.round(preview.system_prompt.length / 4).toLocaleString()} tokens. Campaign details and caller
              variables show as "not known" here; on a real call they are filled in.
            </p>
            <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[#1b1f2d] bg-[#06080d] p-4 font-mono text-xs leading-relaxed text-slate-200">
              {preview.system_prompt}
            </pre>
          </div>
        )}
      </Card>

      {preview && (
        <Card title={`Tools the LLM can call (${preview.tools.length})`} subtitle="Sent alongside the prompt as function definitions.">
          <ul className="space-y-2 text-xs">
            {preview.tools.map((t) => (
              <li key={t.name}>
                <span className="font-mono text-[#00df8f]">{t.name}</span>
                {t.description && <span className="text-slate-400"> — {t.description}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
};
