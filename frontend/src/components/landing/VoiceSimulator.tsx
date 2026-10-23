import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, RotateCcw, Check, Phone, ArrowUpRight } from 'lucide-react';
import { AUDIO_SAMPLES, AudioSample } from './landingData';

export const VoiceSimulator: React.FC<{ onOpenDemo: () => void }> = ({ onOpenDemo }) => {
  const [selectedSample, setSelectedSample] = useState<AudioSample>(AUDIO_SAMPLES[0]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [latencyMs, setLatencyMs] = useState(580);
  const timerRef = useRef<any>(null);

  useEffect(() => {
    if (isPlaying) {
      timerRef.current = setInterval(() => {
        setCurrentStep((prev) => {
          if (prev < selectedSample.dialogue.length - 1) {
            // slight realistic jitter on sub-second latency counter
            setLatencyMs(540 + Math.floor(Math.random() * 80));
            return prev + 1;
          } else {
            setIsPlaying(false);
            return prev;
          }
        });
      }, 3200);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, selectedSample]);

  const handleTogglePlay = () => {
    if (!isPlaying && currentStep >= selectedSample.dialogue.length - 1) {
      setCurrentStep(0);
    }
    setIsPlaying(!isPlaying);
  };

  const handleSelectSample = (sample: AudioSample) => {
    setSelectedSample(sample);
    setIsPlaying(false);
    setCurrentStep(0);
  };

  const handleReset = () => {
    setIsPlaying(false);
    setCurrentStep(0);
  };

  return (
    <div className="relative w-full max-w-lg mx-auto rounded-3xl border border-[#143c49] bg-gradient-to-b from-[#091b22] to-[#051116] p-5 md:p-6 shadow-[0_20px_50px_rgba(0,0,0,0.6)] backdrop-blur-xl">
      {/* Glow behind device */}
      <div className="absolute -inset-0.5 rounded-3xl bg-gradient-to-r from-[#00df8f]/20 via-transparent to-[#00f5a0]/10 blur-xl opacity-75 pointer-events-none" />

      {/* Top Header / Live Call Status */}
      <div className="relative flex items-center justify-between pb-4 border-b border-[#143c49]/80">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-2xl bg-[#00df8f]/10 border border-[#00df8f]/30 text-[#00df8f]">
            <Phone className="w-5 h-5 animate-pulse" />
            <span className="absolute -top-1 -right-1 flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00df8f] opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-[#00df8f]" />
            </span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-bold text-white tracking-wide">Choranta Live Agent</h4>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#00df8f]/15 text-[#00df8f] border border-[#00df8f]/30">
                ACTIVE
              </span>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-slate-400">
              <span>Latency: <strong className="text-emerald-400 font-mono">{latencyMs}ms</strong></span>
              <span>•</span>
              <span>Telecom DID: +91 80 4731 XXXX</span>
            </div>
          </div>
        </div>

        {/* Live Audio Waves */}
        <div className="flex items-center gap-1 h-6 px-2.5 py-1 rounded-full bg-[#06141a] border border-[#143c49]">
          {[40, 90, 60, 100, 75, 45, 80].map((h, i) => (
            <span
              key={i}
              className={`w-0.5 rounded-full bg-[#00df8f] transition-all duration-300 ${
                isPlaying ? 'animate-pulse' : 'opacity-40'
              }`}
              style={{
                height: isPlaying ? `${Math.max(20, (h * (i % 2 === 0 ? 1 : 0.7)))}%` : '30%',
                animationDelay: `${i * 120}ms`,
              }}
            />
          ))}
        </div>
      </div>

      {/* Sample Scenario Selector */}
      <div className="relative my-3 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none text-xs">
        {AUDIO_SAMPLES.map((sample) => {
          const isCurrent = sample.id === selectedSample.id;
          return (
            <button
              key={sample.id}
              onClick={() => handleSelectSample(sample)}
              className={`px-3 py-1.5 rounded-xl whitespace-nowrap transition-all text-xs font-medium ${
                isCurrent
                  ? 'bg-[#00df8f]/20 text-[#00df8f] border border-[#00df8f]/40 font-semibold'
                  : 'bg-[#0a1e27] text-slate-400 hover:text-slate-200 border border-transparent'
              }`}
            >
              {sample.title} ({sample.language})
            </button>
          );
        })}
      </div>

      {/* Interactive Conversation Transcript Stream */}
      <div className="relative my-3 h-56 rounded-2xl bg-[#040c10] border border-[#102731] p-3.5 overflow-y-auto space-y-3 font-sans text-xs">
        {selectedSample.dialogue.slice(0, currentStep + 1).map((msg, idx) => {
          const isAI = msg.speaker === 'Choranta AI';
          return (
            <div
              key={idx}
              className={`flex flex-col ${isAI ? 'items-start' : 'items-end'} animate-in fade-in slide-in-from-bottom-2 duration-300`}
            >
              <div className="flex items-center gap-1.5 mb-1 px-1">
                <span className={`text-[10px] font-semibold uppercase tracking-wider ${isAI ? 'text-[#00df8f]' : 'text-slate-400'}`}>
                  {isAI ? '🤖 Choranta Voice' : '👤 Customer'}
                </span>
                <span className="text-[9px] text-slate-500 font-mono">{msg.time}</span>
              </div>
              <div
                className={`max-w-[88%] rounded-2xl p-3 leading-relaxed ${
                  isAI
                    ? 'bg-[#0a222c] border border-[#144452] text-slate-100 rounded-tl-sm shadow-[0_2px_12px_rgba(0,0,0,0.3)]'
                    : 'bg-[#122b37] text-slate-200 rounded-tr-sm border border-[#194050]'
                }`}
              >
                {msg.text}
              </div>
            </div>
          );
        })}

        {isPlaying && currentStep < selectedSample.dialogue.length - 1 && (
          <div className="flex items-center gap-2 text-[11px] text-[#00df8f] pt-1 italic">
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00df8f] opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00df8f]" />
            </span>
            Transcribing & reasoning with sub-second speech synthesis...
          </div>
        )}
      </div>

      {/* WhatsApp / CRM Sync Notification Pill */}
      {currentStep >= selectedSample.dialogue.length - 1 && (
        <div className="relative mb-3 flex items-center justify-between p-2.5 rounded-xl bg-[#05231c] border border-[#00df8f]/30 text-xs animate-in zoom-in-95 duration-200">
          <div className="flex items-center gap-2 text-[#00df8f]">
            <Check className="w-4 h-4 shrink-0" />
            <span className="font-medium text-slate-200">
              WhatsApp notification + CRM Lead created in HubSpot
            </span>
          </div>
          <span className="text-[10px] font-mono text-[#00df8f]">SYNCED</span>
        </div>
      )}

      {/* Simulator Controls & CTA */}
      <div className="relative pt-1 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={handleTogglePlay}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#00df8f] hover:bg-[#00f59b] text-[#022016] font-semibold text-xs transition-all shadow-[0_0_15px_rgba(0,223,143,0.3)] cursor-pointer"
          >
            {isPlaying ? (
              <>
                <Pause className="w-3.5 h-3.5" /> Pause Call
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                {currentStep >= selectedSample.dialogue.length - 1 ? 'Replay Call' : 'Listen Live'}
              </>
            )}
          </button>

          <button
            onClick={handleReset}
            className="p-2 rounded-xl bg-[#0a1e27] hover:bg-[#0f2934] text-slate-400 hover:text-white transition-colors"
            title="Reset"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>

        <button
          onClick={onOpenDemo}
          className="flex items-center gap-1.5 text-xs text-[#00df8f] hover:text-[#00f59b] font-medium transition-colors"
        >
          <span>Try on your phone</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};
