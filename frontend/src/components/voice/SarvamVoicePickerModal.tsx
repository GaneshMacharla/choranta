import React, { useEffect, useMemo, useState } from 'react';
import { Check, Loader2, Pause, Play, Search, X } from 'lucide-react';
import { Button } from '../common/Button';
import { LoadingState } from '../common/LoadingState';
import { CartesiaVoice } from '../../types';
import { request } from '../../services/api';
import { fetchAuthedBlob } from '../../services/portal';
import { useVoicePreview } from './useVoicePreview';

interface SarvamVoice {
  id: string;
  name: string;
  provider: 'sarvam';
  is_default: boolean;
}

interface SarvamVoicePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedVoiceId?: string | null;
  /** Same shape the Cartesia picker returned, with provider 'sarvam' */
  onSelectVoice: (voice: CartesiaVoice) => void;
}

const listVoices = () => request<SarvamVoice[]>('/catalogs/sarvam-voices');
const fetchPreview = (voiceId: string) => fetchAuthedBlob(`/catalogs/sarvam-voices/${encodeURIComponent(voiceId)}/preview`);

/** Studio voice picker: Sarvam Bulbul voices with a play button on each. */
export const SarvamVoicePickerModal: React.FC<SarvamVoicePickerModalProps> = ({ isOpen, onClose, selectedVoiceId, onSelectVoice }) => {
  const [voices, setVoices] = useState<SarvamVoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const preview = useVoicePreview(fetchPreview);

  useEffect(() => {
    if (!isOpen || voices) return;
    listVoices()
      .then(setVoices)
      .catch((e) => setError(e.message || 'Could not load voices.'));
  }, [isOpen, voices]);

  useEffect(() => {
    if (!isOpen) preview.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (voices || []).filter((v) => !q || v.name.toLowerCase().includes(q));
  }, [voices, search]);

  if (!isOpen) return null;

  const choose = (v: SarvamVoice) =>
    onSelectVoice({ id: v.id, name: v.name, provider: 'sarvam', is_default: v.is_default, language: null });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-2xl border border-[#232736] bg-[#12141b] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="space-y-4 border-b border-[#1f2230] p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-slate-100">Select a voice</h2>
              <p className="text-xs text-slate-400">Sarvam AI voices, made for Indian languages. Press play to listen.</p>
            </div>
            <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-slate-400 hover:text-slate-100">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-500" />
            <input
              autoFocus
              className="w-full rounded-lg border border-[#232736] bg-[#1a1d27] py-2.5 pl-9 pr-3 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none"
              placeholder="Search voices"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {preview.error && <p className="text-xs text-rose-300">{preview.error}</p>}
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {error ? (
            <p className="py-10 text-center text-sm text-rose-300">{error}</p>
          ) : !voices ? (
            <LoadingState message="Loading Sarvam voices..." />
          ) : shown.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-500">No voices match.</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {shown.map((v) => {
                const selected = selectedVoiceId === v.id;
                return (
                  <div
                    key={v.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => choose(v)}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && choose(v)}
                    className={`flex cursor-pointer items-center justify-between gap-2 rounded-lg border p-3 transition-colors ${
                      selected ? 'border-[#00df8f] bg-[#00df8f]/10' : 'border-[#232736] hover:border-slate-500'
                    }`}
                  >
                    <span className="min-w-0">
                      <span className={`flex items-center gap-1.5 text-sm ${selected ? 'font-semibold text-[#00df8f]' : 'text-slate-200'}`}>
                        {selected && <Check className="h-3.5 w-3.5" />}
                        {v.name}
                      </span>
                      {v.is_default && <span className="text-[10px] uppercase tracking-wide text-slate-500">Default</span>}
                    </span>
                    <button
                      type="button"
                      aria-label={preview.playing === v.id ? `Stop ${v.name}` : `Play ${v.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        preview.toggle(v.id);
                      }}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#1f2230] text-slate-200 hover:bg-[#2a2e3f]"
                    >
                      {preview.loading === v.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : preview.playing === v.id ? (
                        <Pause className="h-3.5 w-3.5" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[#1f2230] px-6 py-4">
          <span className="text-xs text-slate-500">
            {voices ? `Showing ${shown.length} of ${voices.length} Sarvam voices` : ''}
          </span>
          <Button variant="secondary" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  );
};
