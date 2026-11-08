import React from 'react';
import { Shield, Cpu, CheckCircle2, ArrowRight } from 'lucide-react';

export const SecurityIntegrationsSection: React.FC<{ onOpenDemo: () => void }> = ({ onOpenDemo }) => {
  const integrations = [
    { name: 'WhatsApp Cloud API', desc: 'Instant confirmation & brochures', icon: '💬' },
    { name: 'Google Calendar', desc: '2-way live slot booking', icon: '📅' },
    { name: 'HubSpot CRM', desc: 'Lead logging & call recording sync', icon: '🟠' },
    { name: 'Zoho CRM', desc: 'Native pipeline & contact updates', icon: '🔴' },
    { name: 'Vobiz', desc: 'Indian carrier DIDs & SIP trunking', icon: '📞' },
    { name: 'Custom Webhooks', desc: 'POST payload to any backend or Zapier', icon: '⚡' },
  ];

  const specs = [
    { title: 'Sub-600ms Latency', desc: 'Streaming speech-to-text and token-by-token TTS pipeline for natural turn-taking.' },
    { title: 'Indian DPDP Compliant', desc: 'Data residency in Indian cloud regions (Mumbai & Hyderabad) with end-to-end encryption.' },
    { title: 'Telecom Virtual DIDs', desc: 'Pre-integrated with leading telecom providers. Bring your own SIP or get local Indian numbers.' },
    { title: '99.98% High Availability', desc: 'Auto-scaling voice channels handling sudden traffic surges without customer busy tones.' },
  ];

  return (
    <section id="integrations" className="relative py-24 md:py-32 bg-[#051117] text-slate-100 border-t border-[#143c49]/50">
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Top Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider text-[#00df8f] bg-[#052119] border border-[#00df8f]/30">
            <Cpu className="w-3.5 h-3.5" />
            <span>Enterprise Architecture</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            Seamless Sync with Your Tech Stack
          </h2>

          <p className="text-slate-400 text-base sm:text-lg">
            Choranta connects directly to your existing CRM, calendar, and messaging tools with zero disruption to your daily operations.
          </p>
        </div>

        {/* Integrations Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 mb-16">
          {integrations.map((item, idx) => (
            <div
              key={idx}
              className="rounded-2xl border border-[#143c49] bg-[#081a24] p-5 flex items-start gap-4 hover:border-[#00df8f]/50 transition-all shadow-md group"
            >
              <div className="text-2xl p-2 rounded-xl bg-[#051116] border border-[#102731] group-hover:scale-110 transition-transform">
                {item.icon}
              </div>
              <div>
                <h4 className="text-sm font-bold text-white group-hover:text-[#00df8f] transition-colors">
                  {item.name}
                </h4>
                <p className="text-xs text-slate-400 mt-1">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Security & Telecom Specs */}
        <div className="rounded-3xl border border-[#143c49] bg-gradient-to-r from-[#071922] to-[#0a232e] p-8 md:p-12 shadow-2xl">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
            <div className="lg:col-span-5 space-y-4">
              <div className="inline-flex items-center gap-2 text-xs font-semibold text-[#00df8f]">
                <Shield className="w-4 h-4" />
                <span>BANK-GRADE TELEPHONY INFRASTRUCTURE</span>
              </div>

              <h3 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
                Engineered for High-Concurrency Production Calls
              </h3>

              <p className="text-slate-300 text-sm leading-relaxed">
                Whether taking 50 simultaneous incoming calls during an ad campaign or dialling 10,000 verified leads, Choranta scales dynamically with zero latency degradation.
              </p>

              <div className="pt-2">
                <button
                  onClick={onOpenDemo}
                  className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[#00df8f] hover:text-[#00f59b] transition-colors"
                >
                  <span>Review Telephony Specs</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-2 gap-4">
              {specs.map((spec, i) => (
                <div key={i} className="rounded-2xl bg-[#05141b] border border-[#143c49] p-4 space-y-1.5">
                  <div className="flex items-center gap-2 text-white font-semibold text-sm">
                    <CheckCircle2 className="w-4 h-4 text-[#00df8f] shrink-0" />
                    <span>{spec.title}</span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed pl-6">
                    {spec.desc}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
