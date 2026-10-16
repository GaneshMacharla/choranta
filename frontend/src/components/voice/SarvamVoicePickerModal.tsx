import React, { useEffect, useMemo, useState } from 'react';
import { Check, Loader2, Pause, Play, Search, Star, X } from 'lucide-react';
import { Button } from '../common/Button';
import { LoadingState } from '../common/LoadingState';
import { CartesiaVoice } from '../../types';
import { request } from '../../services/api';
import { catalogsService } from '../../services/catalogs';
import { useVoicePreview } from './useVoicePreview';

type Provider = 'sarvam' | 'cartesia';

interface SarvamVoice {
  id: string;
  name: string;
  provider: Provider;
  description?: string | null;
  is_default: boolean;
  gender: 'female' | 'male';
  tier: number | null;
  recommended_languages: string[];
  note: string | null;
}

interface SarvamVoicePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedVoiceId?: string | null;
  /** Same shape the Cartesia picker returned, with provider 'sarvam' */
  onSelectVoice: (voice: CartesiaVoice) => void;
  /** Agent's primary language: the language filter starts on it and previews are spoken in it */
  language?: string | null;
  /** Voice provider the agent uses now; the picker opens on it */
  provider?: string | null;
}

type Gender = 'all' | 'female' | 'male';

// Languages Sarvam publishes recommended voices for
const LANGUAGES: { code: string; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'Hindi' },
  { code: 'te', label: 'Telugu' },
  { code: 'ta', label: 'Tamil' },
  { code: 'kn', label: 'Kannada' },
  { code: 'ml', label: 'Malayalam' },
  { code: 'mr', label: 'Marathi' },
  { code: 'bn', label: 'Bengali' },
  { code: 'gu', label: 'Gujarati' },
  { code: 'pa', label: 'Punjabi' },
  { code: 'od', label: 'Odia' },
];

const baseLanguage = (code?: string | null) => {
  const base = (code || '').split('-')[0].toLowerCase();
  return base === 'or' ? 'od' : base;
};

const listVoices = () => request<SarvamVoice[]>('/catalogs/sarvam-voices');

const INDIAN_LANGUAGES = LANGUAGES.map((l) => l.code);

/** Cartesia voices in the picker's shape: Indian voices count as recommended for Indian languages, and Choranta's top picks lead. */
const listCartesiaVoices = async (): Promise<SarvamVoice[]> =>
  (await catalogsService.listVoices()).map((v) => ({
    id: v.id,
    name: v.name,
    provider: 'cartesia' as const,
    description: v.description || null,
    is_default: false,
    gender: (v.gender || '').toLowerCase().startsWith('f') ? ('female' as const) : ('male' as const),
    tier: v.tier ?? null,
    recommended_languages: (v.country || '').toUpperCase() === 'IN' ? INDIAN_LANGUAGES : [],
    note: null,
  }));

/** Best first: Sarvam's picks for the language, then by quality tier; special-purpose voices never lead. */
const rank = (v: SarvamVoice, lang: string, index: number) =>
  [lang && v.recommended_languages.includes(lang) ? 0 : 1, v.note ? 1 : 0, v.tier ?? 9, index] as const;

const compare = (a: readonly number[], b: readonly number[]) => {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
};

/** Studio voice picker: Sarvam Bulbul voices, best first, with gender and language filters and a play button on each. */
export const SarvamVoicePickerModal: React.FC<SarvamVoicePickerModalProps> = ({
  isOpen, onClose, selectedVoiceId, onSelectVoice, language, provider: currentProvider,
}) => {
  const agentLanguage = LANGUAGES.some((l) => l.code === baseLanguage(language)) ? baseLanguage(language) : '';
  const startProvider: Provider = currentProvider === 'cartesia' ? 'cartesia' : 'sarvam';
  const [provider, setProvider] = useState<Provider>(startProvider);
  const [catalog, setCatalog] = useState<Record<Provider, SarvamVoice[] | null>>({ sarvam: null, cartesia: null });
  const voices = catalog[provider];
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [gender, setGender] = useState<Gender>('all');
  const [lang, setLang] = useState(agentLanguage);
  // Previews are spoken in the chosen language (or the agent's, when no language is picked)
  const previewLanguage = lang || language || '';
  const preview = useVoicePreview(
    (voiceId) =>
      provider === 'cartesia'
        ? catalogsService.fetchCartesiaPreview(voiceId, previewLanguage)
        : catalogsService.fetchSarvamPreview(voiceId, previewLanguage),
    `${provider}:${previewLanguage}`
  );

  useEffect(() => {
    if (!isOpen || voices) return;
    setError(null);
    (provider === 'cartesia' ? listCartesiaVoices() : listVoices())
      .then((list) => setCatalog((c) => ({ ...c, [provider]: list })))
      .catch((e) => setError(e.message || 'Could not load voices.'));
  }, [isOpen, voices, provider]);

  useEffect(() => {
    if (isOpen) {
      setLang(agentLanguage);
      setProvider(startProvider);
    } else preview.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const { recommended, others } = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = (voices || [])
      .map((v, index) => ({ v, index }))
      .filter(({ v }) => (gender === 'all' || v.gender === gender) && (!q || v.name.toLowerCase().includes(q)))
      .sort((a, b) => compare(rank(a.v, lang, a.index), rank(b.v, lang, b.index)))
      .map(({ v }) => v);
    return {
      recommended: lang ? filtered.filter((v) => v.recommended_languages.includes(lang)) : [],
      others: lang ? filtered.filter((v) => !v.recommended_languages.includes(lang)) : filtered,
    };
  }, [voices, search, gender, lang]);

  if (!isOpen) return null;

  const langLabel = LANGUAGES.find((l) => l.code === lang)?.label;
  const shownCount = recommended.length + others.length;
  const choose = (v: SarvamVoice) =>
    onSelectVoice({ id: v.id, name: v.name, provider: v.provider, is_default: v.is_default, gender: v.gender, language: null });

  const card = (v: SarvamVoice) => {
    const selected = selectedVoiceId === v.id;
    const topRated = v.tier === 1 && !v.note;
    return (
      <div
        key={v.id}
        role="button"
        tabIndex={0}
        title={v.note || v.description || undefined}
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
          <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] uppercase tracking-wide">
            <span className={v.gender === 'female' ? 'text-pink-300' : 'text-sky-300'}>{v.gender}</span>
            {topRated && (
              <span className="flex items-center gap-0.5 text-amber-300">
                <Star className="h-2.5 w-2.5 fill-current" /> {v.provider === 'cartesia' ? 'Top pick' : 'Top rated'}
              </span>
            )}
            {v.note && <span className="text-slate-500">Dramatic</span>}
            {v.provider === 'cartesia' && v.recommended_languages.length > 0 && <span className="text-[#00df8f]">Indian</span>}
            {v.is_default && <span className="text-slate-500">Default</span>}
          </span>
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
  };

  const grid = (list: SarvamVoice[]) => <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">{list.map(card)}</div>;

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
              <p className="text-xs text-slate-400">
                {provider === 'cartesia'
                  ? 'Cartesia voices: the most natural-sounding, and they speak Indian languages too. Press play to hear one in the chosen language.'
                  : 'Sarvam AI voices, made for Indian languages. Every voice speaks every language; press play to hear it in the chosen one.'}
              </p>
              <div className="mt-3 inline-flex rounded-lg border border-[#232736] bg-[#1a1d27] p-1 text-xs">
                {(['sarvam', 'cartesia'] as Provider[]).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => {
                      preview.stop();
                      setProvider(p);
                    }}
                    className={`rounded-md px-3 py-1.5 ${provider === p ? 'bg-[#00df8f]/15 font-semibold text-[#00df8f]' : 'text-slate-400 hover:text-slate-200'}`}
                  >
                    {p === 'sarvam' ? 'Sarvam' : 'Cartesia'}
                  </button>
                ))}
              </div>
            </div>
            <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-slate-400 hover:text-slate-100">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-500" />
              <input
                autoFocus
                className="w-full rounded-lg border border-[#232736] bg-[#1a1d27] py-2.5 pl-9 pr-3 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none"
                placeholder="Search voices"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="flex rounded-lg border border-[#232736] bg-[#1a1d27] p-1 text-xs">
              {(['all', 'female', 'male'] as Gender[]).map((g) => (
                <button
                  key={g}
                  type="button"
                  onClick={() => setGender(g)}
                  className={`rounded-md px-3 py-1.5 capitalize ${gender === g ? 'bg-[#00df8f]/15 font-semibold text-[#00df8f]' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  {g}
                </button>
              ))}
            </div>
            <select
              aria-label="Language"
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              className="rounded-lg border border-[#232736] bg-[#1a1d27] px-3 py-2 text-sm text-slate-100 focus:border-[#00df8f] focus:outline-none"
            >
              <option value="">All languages</option>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                  {l.code === agentLanguage ? " (this employee's)" : ''}
                </option>
              ))}
            </select>
          </div>
          {preview.error && <p className="text-xs text-rose-300">{preview.error}</p>}
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-6">
          {error ? (
            <p className="py-10 text-center text-sm text-rose-300">{error}</p>
          ) : !voices ? (
            <LoadingState message="Loading voices..." />
          ) : shownCount === 0 ? (
            <p className="py-10 text-center text-sm text-slate-500">No voices match.</p>
          ) : (
            <>
              {recommended.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[#00df8f]">{provider === 'cartesia' ? `Recommended for ${langLabel} (Indian voices)` : `Recommended by Sarvam for ${langLabel}`}</h3>
                  {grid(recommended)}
                </section>
              )}
              {others.length > 0 && (
                <section className="space-y-2">
                  {recommended.length > 0 && (
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">More voices (best rated first)</h3>
                  )}
                  {grid(others)}
                </section>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[#1f2230] px-6 py-4">
          <span className="text-xs text-slate-500">
            {voices ? `Showing ${shownCount} of ${voices.length} ${provider === 'cartesia' ? 'Cartesia' : 'Sarvam'} voices` : ''}
          </span>
          <Button variant="secondary" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  );
};
