import React from 'react';
import { Zap, Check, ArrowRight, PhoneCall, ShieldCheck, Headphones, Calendar, Sparkles } from 'lucide-react';
import { VoiceSimulator } from './VoiceSimulator';

interface HeroSectionProps {
  onOpenDemo: (workflow?: string) => void;
}

export const HeroSection: React.FC<HeroSectionProps> = ({ onOpenDemo }) => {
  return (
    <section className="relative pt-32 pb-20 md:pt-40 md:pb-32 overflow-hidden">
      {/* Background radial glow */}
      <div className="absolute top-1/4 left-1/4 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-[#00df8f]/10 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute top-1/3 right-10 w-[400px] h-[400px] bg-[#00b875]/8 rounded-full blur-[120px] pointer-events-none" />

      {/* Subtle grid pattern overlay */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, #00df8f 1px, transparent 0)',
          backgroundSize: '40px 40px',
        }}
      />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-8 items-center">
          {/* Left Column: Headline, subtext, checklist, CTAs */}
          <div className="lg:col-span-7 space-y-8">
            {/* Pill Badge */}
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#052119] border border-[#00df8f]/40 shadow-[0_0_15px_-3px_rgba(0,223,143,0.3)]">
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00df8f] opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00df8f]" />
              </span>
              <Zap className="w-3.5 h-3.5 text-[#00df8f] fill-[#00df8f]/20" />
              <span className="text-xs font-semibold tracking-wide text-[#00df8f]">
                Autonomous AI Voice Agents for Any Business
              </span>
            </div>

            {/* Display Headline */}
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-white leading-[1.12]">
              Deploy a Human-Like{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#00df8f] via-[#00f5a0] to-[#45e0af] drop-shadow-[0_0_35px_rgba(0,223,143,0.35)]">
                AI Voice Agent
              </span>{' '}
              for Your Business.
            </h1>

            {/* Subtitle */}
            <p className="text-lg md:text-xl text-slate-300 font-normal leading-relaxed max-w-2xl">
              Never lose a customer to a missed call or busy tone again. Our custom AI voice agents
              answer in natural Hinglish, Hindi, and English with sub-second latency—qualifying
              leads, booking meetings, answering inquiries, and sending instant WhatsApp updates.
            </p>

            {/* Checklist items matching Screenshot 1 */}
            <div className="space-y-4 pt-1">
              <div className="flex items-start gap-3.5">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-[#05261d] border border-[#00df8f] flex items-center justify-center text-[#00df8f] mt-0.5 shadow-[0_0_10px_rgba(0,223,143,0.3)]">
                  <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                </div>
                <div className="text-sm md:text-base text-slate-200">
                  <strong className="text-white font-semibold">Handles Any Business Workflow:</strong>{' '}
                  Sales qualification, customer support, or calendar booking
                </div>
              </div>

              <div className="flex items-start gap-3.5">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-[#05261d] border border-[#00df8f] flex items-center justify-center text-[#00df8f] mt-0.5 shadow-[0_0_10px_rgba(0,223,143,0.3)]">
                  <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                </div>
                <div className="text-sm md:text-base text-slate-200">
                  <strong className="text-white font-semibold">100% Pickup Rate:</strong>{' '}
                  Scales to 50+ concurrent calls with zero customer hold time
                </div>
              </div>

              <div className="flex items-start gap-3.5">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-[#05261d] border border-[#00df8f] flex items-center justify-center text-[#00df8f] mt-0.5 shadow-[0_0_10px_rgba(0,223,143,0.3)]">
                  <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                </div>
                <div className="text-sm md:text-base text-slate-200">
                  <strong className="text-white font-semibold">Natural Indian Speech:</strong>{' '}
                  Code-switches seamlessly in Hinglish, Hindi, English &amp; regional tongues
                </div>
              </div>

              <div className="flex items-start gap-3.5">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-[#05261d] border border-[#00df8f] flex items-center justify-center text-[#00df8f] mt-0.5 shadow-[0_0_10px_rgba(0,223,143,0.3)]">
                  <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                </div>
                <div className="text-sm md:text-base text-slate-200">
                  <strong className="text-white font-semibold">Instant Sync:</strong>{' '}
                  WhatsApp notifications, Google Calendar locks, and CRM integrations
                </div>
              </div>
            </div>

            {/* CTAs */}
            <div className="pt-2 flex flex-col sm:flex-row items-stretch sm:items-center gap-4">
              <button
                onClick={() => onOpenDemo('sales')}
                className="flex items-center justify-center gap-2 py-4 px-8 rounded-full font-bold text-base text-[#022016] bg-[#00df8f] hover:bg-[#00f59b] transition-all duration-200 shadow-[0_0_30px_-5px_rgba(0,223,143,0.5)] hover:shadow-[0_0_35px_-2px_rgba(0,223,143,0.7)] hover:scale-[1.02] active:scale-[0.99] cursor-pointer"
              >
                <span>Deploy AI Voice Agent</span>
                <ArrowRight className="w-5 h-5" />
              </button>

              <a
                href="#demo"
                className="flex items-center justify-center gap-2 py-4 px-7 rounded-full font-semibold text-base text-slate-200 bg-[#091b22] hover:bg-[#0f2934] border border-[#143c49] hover:border-[#00df8f]/50 transition-all duration-200"
              >
                <PhoneCall className="w-4 h-4 text-[#00df8f]" />
                <span>Hear Audio Demos</span>
              </a>
            </div>

            {/* Quick Metrics Bar */}
            <div className="pt-4 border-t border-[#143c49]/60 grid grid-cols-3 gap-4 max-w-lg">
              <div>
                <div className="text-xl sm:text-2xl font-bold font-mono text-[#00df8f]">&lt;600ms</div>
                <div className="text-xs text-slate-400">Response Latency</div>
              </div>
              <div>
                <div className="text-xl sm:text-2xl font-bold font-mono text-white">50+</div>
                <div className="text-xs text-slate-400">Parallel Channels</div>
              </div>
              <div>
                <div className="text-xl sm:text-2xl font-bold font-mono text-[#00df8f]">100%</div>
                <div className="text-xs text-slate-400">Zero Hold Time</div>
              </div>
            </div>
          </div>

          {/* Right Column: Live Voice Simulator Widget */}
          <div className="lg:col-span-5 flex justify-center">
            <VoiceSimulator onOpenDemo={() => onOpenDemo('sales')} />
          </div>
        </div>
      </div>
    </section>
  );
};
