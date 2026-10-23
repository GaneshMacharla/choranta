import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Search,
  Check,
  Play,
  Square,
  RefreshCw,
  X,
} from 'lucide-react';
import { Button } from '../common/Button';
import { Select } from '../common/Select';
import { LoadingState } from '../common/LoadingState';
import { catalogsService } from '../../services/catalogs';
import { CartesiaVoice } from '../../types';
import { useAuth } from '../../context/AuthContext';

const GENDER_FILTER_OPTIONS = [
  { value: 'any', label: 'Any gender' },
  { value: 'feminine', label: 'Female' },
  { value: 'masculine', label: 'Male' },
];

const TAG_FILTER_OPTIONS = [
  { value: 'any', label: 'Tags' },
  { value: 'customer', label: 'Customer Care' },
  { value: 'assistant', label: 'Digital Assistant' },
  { value: 'narrative', label: 'Narratives & Stories' },
  { value: 'support', label: 'Support' },
  { value: 'calm', label: 'Calm & Trust' },
];

const INDIC_LANGUAGE_OPTIONS = [
  { value: 'any', label: 'Any language' },
  { value: 'hi', label: 'Hindi (हिन्दी / Hinglish)' },
  { value: 'en', label: 'English (India)' },
  { value: 'te', label: 'Telugu (తెలుగు)' },
  { value: 'ta', label: 'Tamil (தமிழ்)' },
  { value: 'kn', label: 'Kannada (ಕನ್ನಡ)' },
  { value: 'ml', label: 'Malayalam (മലയാളം)' },
  { value: 'mr', label: 'Marathi (मराठी)' },
  { value: 'bn', label: 'Bengali (বাংলা)' },
  { value: 'gu', label: 'Gujarati (ગુજરાતી)' },
  { value: 'pa', label: 'Punjabi (ਪੰਜਾਬੀ)' },
  { value: 'or', label: 'Odia (ଓଡ଼ିଆ)' },
  { value: 'ur', label: 'Urdu (اردو)' },
];

const ACCENT_FILTER_OPTIONS = [
  { value: 'any', label: 'Any accent' },
  { value: 'indian', label: '🇮🇳 Indian' },
];

interface VoicePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedVoiceId?: string | null;
  onSelectVoice: (voice: CartesiaVoice) => void;
}

// Curated roles & titles matching Cartesia official showcase
const getVoiceRole = (voice: CartesiaVoice): string => {
  if (voice.tagline) return voice.tagline.replace(/\s*\(.*?\)\s*/g, '');
  const n = voice.name.toLowerCase();
  if (n === 'siya') return 'Gentle Narrator';
  if (n === 'kabir') return 'Composed Coordinator';
  if (n === 'sana') return 'Support Specialist';
  if (n === 'aryan') return 'Meticulous Guide';
  if (n === 'sarthak') return 'Trusted Consultant';
  if (n === 'smruti') return 'Precise Explainer';
  if (n === 'akash') return 'Briefing Specialist';
  if (n === 'alok') return 'Reassuring Advisor';
  if (n === 'skylar') return 'Friendly Guide';
  if (n === 'daniel') return 'Modern Assistant';
  if (n === 'gemma') return 'Decisive Agent';
  if (n === 'parker') return 'Supportive Pal';
  if (n === 'archie') return 'Approachable Mate';
  if (n === 'jacqueline') return 'Reassuring Agent';
  if (n === 'clive') return 'Measured Expert';
  if (n === 'ella') return 'Caring Scout';
  if (n === 'arlo') return 'Warm Mate';
  if (n === 'corey') return 'Cheerful Rep';
  if (voice.gender === 'feminine') return 'Conversational Guide';
  return 'Modern Assistant';
};

const getCountryFlag = (country?: string | null): string => {
  switch ((country || '').toUpperCase()) {
    case 'IN':
      return '🇮🇳';
    case 'US':
      return '🇺🇸';
    case 'GB':
      return '🇬🇧';
    case 'AU':
      return '🇦🇺';
    case 'CA':
      return '🇨🇦';
    case 'DE':
      return '🇩🇪';
    case 'FR':
      return '🇫🇷';
    case 'ES':
      return '🇪🇸';
    case 'IT':
      return '🇮🇹';
    case 'JP':
      return '🇯🇵';
    case 'BR':
      return '🇧🇷';
    case 'TH':
      return '🇹🇭';
    case 'ZA':
      return '🇿🇦';
    default:
      return '🌐';
  }
};

const getLanguageCount = (voice: CartesiaVoice): number => {
  const c = (voice.country || '').toUpperCase();
  if (c === 'IN') return 15;
  if (c === 'US') return 7;
  if (c === 'GB') return 24;
  if (c === 'AU') return 5;
  return 8;
};

const matchesLanguage = (voiceLanguage: string | null | undefined, selectedLanguage: string): boolean => {
  const normalizedVoiceLanguage = (voiceLanguage || '').toLowerCase().trim();
  const normalizedSelectedLanguage = selectedLanguage.toLowerCase().trim();
  return (
    normalizedVoiceLanguage === normalizedSelectedLanguage ||
    normalizedVoiceLanguage.startsWith(`${normalizedSelectedLanguage}-`)
  );
};

export const VoicePickerModal: React.FC<VoicePickerModalProps> = ({
  isOpen,
  onClose,
  selectedVoiceId,
  onSelectVoice,
}) => {
  const { token } = useAuth();
  const [voices, setVoices] = useState<CartesiaVoice[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Tab: 'featured' | 'all' (No "My voices" or "Saved" as user explicitly instructed)
  const [activeTab, setActiveTab] = useState<'featured' | 'all'>('featured');

  // Search & Filter Dropdowns matching Cartesia UI
  const [searchQuery, setSearchQuery] = useState('');
  const [genderFilter, setGenderFilter] = useState<string>('any');
  const [tagFilter, setTagFilter] = useState<string>('any');
  const [languageFilter, setLanguageFilter] = useState<string>('any');
  const [accentFilter, setAccentFilter] = useState<string>('any');

  // Audio Playback
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const [audioLoadingVoiceId, setAudioLoadingVoiceId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadVoices();
    } else {
      stopAudio();
    }
  }, [isOpen]);

  useEffect(() => {
    return () => {
      stopAudio();
    };
  }, []);

  const loadVoices = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await catalogsService.listVoices();
      setVoices(data);
    } catch (err: any) {
      console.error('Failed to load Cartesia voices:', err);
      setError(err.message || 'Failed to load Cartesia voice catalog.');
    } finally {
      setIsLoading(false);
    }
  };

  const stopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    setPlayingVoiceId(null);
    setAudioLoadingVoiceId(null);
  };

  const playPreview = async (e: React.MouseEvent, voice: CartesiaVoice) => {
    e.stopPropagation();

    if (playingVoiceId === voice.id) {
      stopAudio();
      return;
    }

    stopAudio();
    setAudioLoadingVoiceId(voice.id);

    try {
      const previewUrl = voice.preview_url || catalogsService.getVoicePreviewUrl(voice.id, token);
      const audio = new Audio(previewUrl);
      audioRef.current = audio;

      audio.oncanplay = () => {
        setAudioLoadingVoiceId(null);
        setPlayingVoiceId(voice.id);
      };

      audio.onended = () => {
        setPlayingVoiceId(null);
        audioRef.current = null;
      };

      audio.onerror = (err) => {
        console.error('Voice preview audio playback error:', err);
        setAudioLoadingVoiceId(null);
        setPlayingVoiceId(null);
        audioRef.current = null;
      };

      await audio.play();
    } catch (err) {
      console.error('Failed to play voice preview:', err);
      setAudioLoadingVoiceId(null);
      setPlayingVoiceId(null);
    }
  };

  // Filter and sort voices (India prioritized)
  const filteredVoices = useMemo(() => {
    let result = [...voices];

    // Tab filter
    if (activeTab === 'featured') {
      // In featured mode, prioritize Indian voices and top recommended voices
      result = result.filter(
        (v) =>
          (v.country || '').toUpperCase() === 'IN' ||
          (v.language || '').toLowerCase() === 'hi' ||
          ['Skylar', 'Daniel', 'Gemma', 'Parker', 'Archie', 'Jacqueline', 'Clive', 'Ella'].includes(
            v.name
          )
      );
    }

    // Gender filter
    if (genderFilter !== 'any') {
      result = result.filter((v) => (v.gender || '').toLowerCase() === genderFilter);
    }

    // Language filter
    if (languageFilter !== 'any') {
      result = result.filter((v) => matchesLanguage(v.language, languageFilter));
    }

    // Accent filter
    if (accentFilter !== 'any') {
      result = result.filter((v) => {
        const c = (v.country || '').toUpperCase();
        if (accentFilter === 'indian') return c === 'IN' || matchesLanguage(v.language, 'hi');
        if (accentFilter === 'american') return c === 'US';
        if (accentFilter === 'british') return c === 'GB';
        if (accentFilter === 'australian') return c === 'AU';
        return true;
      });
    }

    // Tag filter
    if (tagFilter !== 'any') {
      result = result.filter((v) => {
        const desc = ((v.description || '') + ' ' + (v.tagline || '')).toLowerCase();
        return desc.includes(tagFilter.toLowerCase());
      });
    }

    // Search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(
        (v) =>
          v.name.toLowerCase().includes(q) ||
          (v.description || '').toLowerCase().includes(q) ||
          (v.tagline || '').toLowerCase().includes(q) ||
          (v.country || '').toLowerCase().includes(q) ||
          (v.language || '').toLowerCase().includes(q) ||
          v.id.toLowerCase().includes(q)
      );
    }

    // Always sort India voices to the top
    result.sort((a, b) => {
      const aIsIndia =
        (a.country || '').toUpperCase() === 'IN' || (a.language || '').toLowerCase() === 'hi';
      const bIsIndia =
        (b.country || '').toUpperCase() === 'IN' || (b.language || '').toLowerCase() === 'hi';
      if (aIsIndia && !bIsIndia) return -1;
      if (!aIsIndia && bIsIndia) return 1;
      return a.name.localeCompare(b.name);
    });

    return result;
  }, [voices, activeTab, genderFilter, tagFilter, languageFilter, accentFilter, searchQuery]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-4xl rounded-2xl border border-[#232734] bg-[#111318] text-slate-100 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        style={{
          boxShadow: '0 25px 60px -15px rgba(0, 0, 0, 0.9), 0 0 30px rgba(0, 223, 143, 0.05)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ========================================================= */}
        {/* MODAL HEADER: Title & Close Button */}
        {/* ========================================================= */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h2 className="text-lg font-semibold text-slate-100 tracking-tight">Select a voice</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-100 hover:bg-[#1c202a] transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* ========================================================= */}
        {/* SEARCH BAR (Exact Cartesia dark pill design) */}
        {/* ========================================================= */}
        <div className="px-6 pb-3">
          <div className="relative">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-xl border border-[#222634] bg-[#181b24] pl-10 pr-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f] transition-all"
            />
          </div>
        </div>

        {/* ========================================================= */}
        {/* FILTER BAR & TABS (Exact Cartesia controls layout) */}
        {/* ========================================================= */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 pb-3 border-b border-[#1d212d]">
          {/* Left: Dropdown Filters */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {/* Any gender dropdown */}
            <div className="w-28">
              <Select
                size="sm"
                options={GENDER_FILTER_OPTIONS}
                value={genderFilter}
                onChange={(e) => setGenderFilter(e.target.value)}
              />
            </div>

            {/* Tags dropdown */}
            <div className="w-32">
              <Select
                size="sm"
                options={TAG_FILTER_OPTIONS}
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
              />
            </div>

            {/* Any language dropdown - ONLY Indian languages supported by Cartesia */}
            <div className="w-44">
              <Select
                size="sm"
                options={INDIC_LANGUAGE_OPTIONS}
                value={languageFilter}
                onChange={(e) => setLanguageFilter(e.target.value)}
              />
            </div>

            {/* Any accent dropdown - Focus on Indian accents */}
            <div className="w-28">
              <Select
                size="sm"
                options={ACCENT_FILTER_OPTIONS}
                value={accentFilter}
                onChange={(e) => setAccentFilter(e.target.value)}
              />
            </div>
          </div>

          {/* Right: Category Tabs (Featured vs All Voices - NO My voices) */}
          <div className="flex items-center gap-5 text-sm font-medium">
            <button
              type="button"
              onClick={() => setActiveTab('featured')}
              className={`pb-1 transition-colors relative ${
                activeTab === 'featured'
                  ? 'text-slate-100 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Featured
              {activeTab === 'featured' && (
                <div className="absolute bottom-[-13px] left-0 right-0 h-[2px] bg-slate-100 rounded-full" />
              )}
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('all')}
              className={`pb-1 transition-colors relative ${
                activeTab === 'all'
                  ? 'text-slate-100 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              All voices
              {activeTab === 'all' && (
                <div className="absolute bottom-[-13px] left-0 right-0 h-[2px] bg-slate-100 rounded-full" />
              )}
            </button>
          </div>
        </div>

        {/* ========================================================= */}
        {/* VOICE LIST CONTENT (Exact Cartesia rows) */}
        {/* ========================================================= */}
        <div className="flex-1 overflow-y-auto px-6 py-2 divide-y divide-[#181c26] max-h-[520px]">
          {isLoading ? (
            <div className="py-20">
              <LoadingState message="Loading Cartesia voices..." />
            </div>
          ) : error ? (
            <div className="my-8 p-6 text-center rounded-xl border border-rose-900/40 bg-rose-950/20 text-rose-300 space-y-3">
              <p className="text-xs">{error}</p>
              <Button variant="secondary" size="sm" onClick={loadVoices}>
                <RefreshCw className="h-3.5 w-3.5 mr-1" /> Retry
              </Button>
            </div>
          ) : filteredVoices.length === 0 ? (
            <div className="py-16 text-center text-xs text-slate-500">
              No voices found matching your criteria.
            </div>
          ) : (
            filteredVoices.map((voice) => {
              const isSelected = selectedVoiceId === voice.id;
              const isPlaying = playingVoiceId === voice.id;
              const isAudioLoading = audioLoadingVoiceId === voice.id;
              const isIndia =
                (voice.country || '').toUpperCase() === 'IN' ||
                (voice.language || '').toLowerCase() === 'hi';
              const flag = getCountryFlag(voice.country);
              const langCount = getLanguageCount(voice);
              const role = getVoiceRole(voice);

              return (
                <div
                  key={voice.id}
                  onClick={() => {
                    stopAudio();
                    onSelectVoice(voice);
                    onClose();
                  }}
                  className={`group flex items-center justify-between py-3 px-3 -mx-3 rounded-xl transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-[#142621]/40 border border-[#00df8f]/30'
                      : 'hover:bg-[#161922]'
                  }`}
                >
                  {/* Left: Round Play Button + Voice Info */}
                  <div className="flex items-center gap-3.5 min-w-0 pr-4">
                    {/* Cartesia round green play button */}
                    <button
                      type="button"
                      onClick={(e) => playPreview(e, voice)}
                      title={isPlaying ? 'Pause preview' : 'Play preview'}
                      className={`h-10 w-10 shrink-0 rounded-full flex items-center justify-center transition-all ${
                        isPlaying
                          ? 'bg-[#00df8f] text-[#051f15] shadow-lg shadow-[#00df8f]/20 scale-105'
                          : isAudioLoading
                          ? 'bg-[#1b3528] text-[#00df8f]'
                          : 'bg-[#1a382b] hover:bg-[#234c3a] text-[#00df8f]'
                      }`}
                    >
                      {isAudioLoading ? (
                        <RefreshCw className="h-4 w-4 animate-spin text-[#00df8f]" />
                      ) : isPlaying ? (
                        <Square className="h-4 w-4 fill-current text-[#051f15]" />
                      ) : (
                        <Play className="h-4 w-4 fill-current ml-0.5" />
                      )}
                    </button>

                    {/* Name, Subtitle, Verified Badge, Description */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-semibold text-sm text-slate-100 group-hover:text-white">
                          {voice.name}
                        </span>
                        <span className="text-slate-400 text-sm font-normal">-</span>
                        <span className="text-slate-300 text-sm font-normal">{role}</span>

                        {/* Verified badge checkmark circle */}
                        <span
                          className="inline-flex items-center justify-center h-3.5 w-3.5 rounded-full bg-slate-600/80 text-[9px] text-white font-bold shrink-0"
                          title="Cartesia Verified Voice"
                        >
                          ✓
                        </span>

                        {/* India Focus Badge */}
                        {isIndia && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800/40 shrink-0">
                            🇮🇳 India
                          </span>
                        )}

                        {/* Selected Indicator */}
                        {isSelected && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.2 rounded text-[10px] font-semibold bg-[#00df8f]/20 text-[#00df8f] border border-[#00df8f]/50 shrink-0">
                            <Check className="h-2.5 w-2.5" /> Active
                          </span>
                        )}
                      </div>

                      {/* Description */}
                      <p className="text-xs text-slate-400 line-clamp-1 mt-0.5 group-hover:text-slate-300">
                        {voice.description || 'Natural Cartesia Sonic neural voice model.'}
                      </p>
                    </div>
                  </div>

                  {/* Right: Flag + Count, Bookmark, Select Button */}
                  <div className="flex items-center gap-3 shrink-0">
                    {/* Country Flag + Language count */}
                    <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-[#181b24] border border-[#232736] text-xs text-slate-300 font-mono">
                      <span>{flag}</span>
                      <span className="text-slate-400">+{langCount}</span>
                    </div>

                    {/* Select / Use Voice Button */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        stopAudio();
                        onSelectVoice(voice);
                        onClose();
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        isSelected
                          ? 'bg-[#00df8f]/20 text-[#00df8f] border border-[#00df8f]/40 font-semibold'
                          : 'bg-[#181b24] hover:bg-[#00df8f] text-slate-300 hover:text-[#051f15] border border-[#232736] hover:border-[#00df8f]'
                      }`}
                    >
                      {isSelected ? 'Selected' : 'Select'}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* ========================================================= */}
        {/* FOOTER: Voice count & Close */}
        {/* ========================================================= */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-[#1d212d] bg-[#0e1014] text-xs text-slate-400">
          <span>
            Showing {filteredVoices.length} of {voices.length} Cartesia voices
          </span>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </div>
  );
};
