import React, { useState } from 'react';
import {
  Scale,
  Table as TableIcon,
  LayoutGrid,
  User,
  Bot,
  CheckCircle,
  MinusCircle,
  ArrowRight,
  ShieldCheck,
  ArrowLeftRight,
} from 'lucide-react';
import { BENCHMARK_FACTORS } from './landingData';

interface BenchmarkSectionProps {
  onOpenDemo: () => void;
}

export const BenchmarkSection: React.FC<BenchmarkSectionProps> = ({ onOpenDemo }) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'table' | 'cards'>('table');

  const categories = [
    { id: 'all', label: 'All Factors', count: 9 },
    { id: 'cost', label: 'Cost & Economics', count: 2 },
    { id: 'operations', label: 'Operations & Hours', count: 3 },
    { id: 'scalability', label: 'Scalability & Speed', count: 3 },
    { id: 'fit', label: 'Capabilities & Fit', count: 1 },
  ];

  const filteredFactors = BENCHMARK_FACTORS.filter((factor) => {
    if (selectedCategory === 'all') return true;
    return factor.category === selectedCategory;
  });

  return (
    <section id="benchmark" className="relative py-24 md:py-32 bg-[#040d12] text-slate-100">
      {/* Background ambient lighting */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-[#00df8f]/5 rounded-full blur-[180px] pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-12">
          <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full text-xs font-semibold tracking-wider uppercase text-[#00df8f] bg-[#052119] border border-[#00df8f]/30">
            <Scale className="w-3.5 h-3.5" />
            <span>Economic &amp; Operational Benchmark</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            Human Agent vs.{' '}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#00df8f] to-[#00f5a0]">
              choranta (AI)
            </span>
          </h2>

          <p className="text-base sm:text-lg text-slate-400 leading-relaxed">
            Full breakdown of real costs, hidden overheads, productive talk-time, and call capacity.
            See where AI automates routine volume and where humans remain irreplaceable.
          </p>
        </div>

        {/* Filter Chips & View Mode Switcher */}
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 mb-8">
          {/* Category Chips */}
          <div className="flex items-center gap-2 overflow-x-auto w-full md:w-auto pb-2 md:pb-0 scrollbar-none">
            {categories.map((cat) => {
              const isActive = selectedCategory === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => setSelectedCategory(cat.id)}
                  className={`flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs sm:text-sm font-semibold whitespace-nowrap transition-all cursor-pointer ${
                    isActive
                      ? 'bg-[#00df8f] text-[#022016] shadow-[0_0_15px_rgba(0,223,143,0.3)]'
                      : 'bg-[#081b24] text-slate-300 hover:text-white hover:bg-[#0d2a37] border border-[#143c49]/60'
                  }`}
                >
                  <span>{cat.label}</span>
                  <span
                    className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                      isActive ? 'bg-[#022016]/20 text-[#022016]' : 'bg-[#102731] text-slate-400'
                    }`}
                  >
                    {cat.count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Table / Cards View Toggle */}
          <div className="flex items-center p-1 rounded-xl bg-[#081b24] border border-[#143c49] self-end md:self-auto shrink-0">
            <button
              onClick={() => setViewMode('table')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                viewMode === 'table'
                  ? 'bg-[#0f2d3a] text-[#00df8f] font-semibold'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <TableIcon className="w-3.5 h-3.5" />
              <span>Table</span>
            </button>
            <button
              onClick={() => setViewMode('cards')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                viewMode === 'cards'
                  ? 'bg-[#0f2d3a] text-[#00df8f] font-semibold'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" />
              <span>Cards</span>
            </button>
          </div>
        </div>

        {/* Benchmark Display: Table Mode (Matching Screenshot 3 & 4) */}
        {viewMode === 'table' ? (
          <div className="rounded-3xl border border-[#143c49] bg-[#071720]/90 backdrop-blur-md overflow-hidden shadow-2xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#143c49] bg-[#05131a]">
                    <th className="py-5 px-6 text-xs font-bold uppercase tracking-wider text-slate-400 w-1/3">
                      FACTOR
                    </th>
                    <th className="py-5 px-6 text-xs font-bold uppercase tracking-wider text-slate-300 w-1/3 border-l border-[#143c49]">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-lg bg-[#0e2733] border border-[#194050] flex items-center justify-center text-slate-300">
                          <User className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="text-white text-xs font-bold">HUMAN AGENT</div>
                          <div className="text-[10px] text-slate-400 font-normal lowercase">in-house / bpo</div>
                        </div>
                      </div>
                    </th>
                    <th className="py-5 px-6 text-xs font-bold uppercase tracking-wider text-[#00df8f] w-1/3 border-l border-[#143c49] bg-[#061b20]">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/40 flex items-center justify-center text-[#00df8f]">
                            <Bot className="w-4 h-4" />
                          </div>
                          <div>
                            <div className="text-white text-xs font-bold">CHORANTA (AI)</div>
                            <div className="text-[10px] text-emerald-400 font-normal">24/7 autonomous</div>
                          </div>
                        </div>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#00df8f] text-[#022016] uppercase tracking-wider">
                          AI VOICE
                        </span>
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#102731]">
                  {filteredFactors.map((factor) => (
                    <tr
                      key={factor.id}
                      className="hover:bg-[#0a202c]/50 transition-colors group"
                    >
                      {/* Factor Title & Subtitle */}
                      <td className="py-4 px-6 align-middle">
                        <div className="font-semibold text-sm text-white group-hover:text-[#00df8f] transition-colors">
                          {factor.title}
                        </div>
                        <div className="text-xs text-slate-400 font-normal">
                          {factor.subtitle}
                        </div>
                      </td>

                      {/* Human Agent Column */}
                      <td className="py-4 px-6 align-middle border-l border-[#143c49]">
                        <div className="flex items-start gap-2.5">
                          <MinusCircle className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                          <span className="text-sm text-slate-300 font-medium">
                            {factor.human}
                          </span>
                        </div>
                      </td>

                      {/* Choranta AI Column */}
                      <td className="py-4 px-6 align-middle border-l border-[#143c49] bg-[#061a20]/40">
                        <div className="flex items-start gap-2.5">
                          {factor.id === 'best-fit' ? (
                            <ArrowLeftRight className="w-4 h-4 text-[#00df8f] shrink-0 mt-0.5" />
                          ) : (
                            <CheckCircle className="w-4 h-4 text-[#00df8f] shrink-0 mt-0.5" />
                          )}
                          <span className="text-sm text-white font-semibold">
                            {factor.ai}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          /* Cards View Mode */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {filteredFactors.map((factor) => (
              <div
                key={factor.id}
                className="rounded-2xl border border-[#143c49] bg-gradient-to-b from-[#091b22] to-[#06141a] p-6 space-y-4 hover:border-[#00df8f]/50 transition-all shadow-lg"
              >
                <div>
                  <h4 className="text-base font-bold text-white">{factor.title}</h4>
                  <p className="text-xs text-[#00df8f] font-medium">{factor.subtitle}</p>
                </div>

                <div className="space-y-3 pt-2 border-t border-[#143c49]/60">
                  <div className="rounded-xl bg-[#051116] p-3 border border-[#102731]">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1 flex items-center gap-1.5">
                      <User className="w-3 h-3" />
                      <span>Human Agent</span>
                    </div>
                    <div className="text-xs text-slate-300 font-medium">
                      {factor.human}
                    </div>
                  </div>

                  <div className="rounded-xl bg-[#061c20] p-3 border border-[#00df8f]/30">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-[#00df8f] mb-1 flex items-center gap-1.5">
                      <Bot className="w-3 h-3" />
                      <span>Choranta AI (24/7)</span>
                    </div>
                    <div className="text-xs text-white font-semibold">
                      {factor.ai}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Recommended Hybrid Model Card - Exactly matching Screenshot 4 */}
        <div className="mt-12 rounded-3xl border border-[#00df8f]/40 bg-gradient-to-r from-[#071f24] via-[#09282f] to-[#061a1e] p-8 md:p-10 shadow-[0_0_40px_-10px_rgba(0,223,143,0.25)] relative overflow-hidden">
          <div className="absolute top-0 right-0 -mr-20 -mt-20 w-64 h-64 bg-[#00df8f]/10 rounded-full blur-3xl pointer-events-none" />

          <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-8 relative">
            <div className="space-y-4 max-w-3xl">
              {/* Badge */}
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold text-[#00df8f] bg-[#032318] border border-[#00df8f]/40">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>RECOMMENDED: THE HYBRID MODEL</span>
              </div>

              {/* Heading */}
              <h3 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight leading-snug">
                Automate 80% Routine Calls with choranta, Reserve Humans for VIP Escalations
              </h3>

              {/* Description */}
              <p className="text-slate-300 text-sm sm:text-base leading-relaxed">
                Leading clinics, realtors, and firms do not fire their best staff—they liberate them.
                Let choranta handle 24/7 bookings, pricing inquiries, Hindi/English FAQs, and
                qualification calls instantly. Your high-value human team only steps in for emotional
                negotiation and closing.
              </p>
            </div>

            {/* CTA Button */}
            <div className="shrink-0 w-full lg:w-auto">
              <button
                onClick={onOpenDemo}
                className="w-full lg:w-auto flex items-center justify-center gap-2.5 py-4 px-8 rounded-full font-bold text-base text-[#022016] bg-[#00df8f] hover:bg-[#00f59b] transition-all duration-200 shadow-[0_0_25px_rgba(0,223,143,0.4)] hover:shadow-[0_0_35px_rgba(0,223,143,0.6)] hover:scale-105 active:scale-[0.98] cursor-pointer"
              >
                <span>Deploy choranta for Your Calls</span>
                <ArrowRight className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
