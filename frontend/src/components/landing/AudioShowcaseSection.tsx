import React, { useState } from 'react';
import { Volume2, Play, Pause, Languages, Sparkles, MessageSquare, PhoneCall } from 'lucide-react';
import { AUDIO_SAMPLES, AudioSample } from './landingData';

interface AudioShowcaseSectionProps {
  onOpenDemo: (workflow?: string) => void;
}

export const AudioShowcaseSection: React.FC<AudioShowcaseSectionProps> = ({ onOpenDemo }) => {
  const [activeSampleId, setActiveSampleId] = useState<string>(AUDIO_SAMPLES[0].id);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [activeStep, setActiveStep] = useState<number>(0);

  const sample = AUDIO_SAMPLES.find((s) => s.id === activeSampleId) || AUDIO_SAMPLES[0];

  const handleToggle = () => {
    setIsPlaying(!isPlaying);
  };

  const handleSelect = (s: AudioSample) => {
    setActiveSampleId(s.id);
    setIsPlaying(false);
    setActiveStep(0);
  };

  return (
    <section id="demo" className="relative py-24 md:py-32 bg-[#040d12] text-slate-100">
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider text-[#00df8f] bg-[#052119] border border-[#00df8f]/30">
            <Languages className="w-3.5 h-3.5" />
            <span>Natural Indian Speech &amp; Dialects</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            Listen to Choranta in Real Business Scenarios
          </h2>

          <p className="text-slate-400 text-base sm:text-lg">
            No robotic stiffness. Experience hyper-realistic code-switching across Hinglish, Hindi,
            English, and regional Indian nuances with sub-600ms conversational turn-taking.
          </p>
        </div>

        {/* Audio Player Card */}
        <div className="max-w-4xl mx-auto rounded-3xl border border-[#143c49] bg-gradient-to-br from-[#081a22] to-[#040f14] p-6 sm:p-10 shadow-2xl space-y-8">
          {/* Sample Tabs */}
          <div className="flex flex-wrap gap-3 pb-2 border-b border-[#143c49]/60">
            {AUDIO_SAMPLES.map((s) => {
              const isActive = s.id === activeSampleId;
              return (
                <button
                  key={s.id}
                  onClick={() => handleSelect(s)}
                  className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                    isActive
                      ? 'bg-[#00df8f] text-[#022016] shadow-[0_0_15px_rgba(0,223,143,0.3)]'
                      : 'bg-[#091f28] text-slate-300 hover:text-white border border-[#143c49]'
                  }`}
                >
                  <Volume2 className="w-4 h-4" />
                  <span>{s.title}</span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-mono ${
                      isActive ? 'bg-[#022016]/20 text-[#022016]' : 'bg-[#051116] text-[#00df8f]'
                    }`}
                  >
                    {s.language}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Player Display */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-center">
            {/* Visualizer & Controls */}
            <div className="md:col-span-5 rounded-2xl bg-[#06141a] border border-[#143c49] p-6 flex flex-col items-center justify-center text-center space-y-5">
              <div className="relative">
                <div className="w-20 h-20 rounded-full bg-[#00df8f]/10 border-2 border-[#00df8f] flex items-center justify-center text-[#00df8f] shadow-[0_0_25px_rgba(0,223,143,0.3)]">
                  {isPlaying ? (
                    <Volume2 className="w-9 h-9 animate-bounce" />
                  ) : (
                    <PhoneCall className="w-9 h-9" />
                  )}
                </div>
              </div>

              <div>
                <h4 className="font-bold text-white text-base">{sample.title}</h4>
                <p className="text-xs text-[#00df8f] font-mono mt-0.5">
                  {sample.industry} • {sample.language} • {sample.duration}
                </p>
              </div>

              {/* Animated waveform bars */}
              <div className="flex items-center gap-1.5 h-10 w-full justify-center px-4 py-2 bg-[#040c10] rounded-xl border border-[#102731]">
                {[30, 75, 45, 90, 60, 100, 80, 50, 70, 95, 40, 85, 55, 90].map((bar, i) => (
                  <span
                    key={i}
                    className={`w-1 rounded-full bg-[#00df8f] transition-all duration-200 ${
                      isPlaying ? 'animate-pulse' : 'opacity-30'
                    }`}
                    style={{
                      height: isPlaying ? `${Math.max(25, bar * 0.9)}%` : '25%',
                      animationDelay: `${i * 90}ms`,
                    }}
                  />
                ))}
              </div>

              <div className="flex items-center gap-3 w-full">
                <button
                  onClick={handleToggle}
                  className="flex-1 flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-bold text-xs text-[#022016] bg-[#00df8f] hover:bg-[#00f59b] transition-all shadow-[0_0_15px_rgba(0,223,143,0.3)] cursor-pointer"
                >
                  {isPlaying ? (
                    <>
                      <Pause className="w-4 h-4" /> Pause Audio
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" /> Play Call Preview
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Transcript Area */}
            <div className="md:col-span-7 space-y-3 max-h-[360px] overflow-y-auto pr-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-2">
                <MessageSquare className="w-3.5 h-3.5 text-[#00df8f]" />
                <span>Live Turn-By-Turn Transcript</span>
              </div>

              {sample.dialogue.map((item, idx) => {
                const isAI = item.speaker === 'Choranta AI';
                return (
                  <div
                    key={idx}
                    className={`p-3.5 rounded-2xl text-xs sm:text-sm leading-relaxed border transition-all ${
                      isAI
                        ? 'bg-[#0a232e] border-[#144452] text-slate-100'
                        : 'bg-[#071720] border-[#102a35] text-slate-300'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span
                        className={`text-[11px] font-bold ${
                          isAI ? 'text-[#00df8f]' : 'text-slate-400'
                        }`}
                      >
                        {isAI ? '🤖 Choranta Voice AI' : '👤 Customer / Lead'}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">{item.time}</span>
                    </div>
                    <div>{item.text}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
