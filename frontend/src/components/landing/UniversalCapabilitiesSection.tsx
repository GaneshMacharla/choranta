import React, { useState } from 'react';
import { TrendingUp, Headphones, Calendar, ShoppingBag, CheckCircle, ArrowRight, Sparkles } from 'lucide-react';
import { WORKFLOW_TABS, WorkflowTab } from './landingData';

interface UniversalCapabilitiesSectionProps {
  onOpenDemo: (workflowId: string) => void;
}

export const UniversalCapabilitiesSection: React.FC<UniversalCapabilitiesSectionProps> = ({ onOpenDemo }) => {
  const [activeTabId, setActiveTabId] = useState<string>('sales');

  const activeTab: WorkflowTab =
    WORKFLOW_TABS.find((t) => t.id === activeTabId) || WORKFLOW_TABS[0];

  const getTabIcon = (iconName: string, className: string) => {
    switch (iconName) {
      case 'TrendingUp':
        return <TrendingUp className={className} />;
      case 'Headphones':
        return <Headphones className={className} />;
      case 'Calendar':
        return <Calendar className={className} />;
      case 'ShoppingBag':
        return <ShoppingBag className={className} />;
      default:
        return <Sparkles className={className} />;
    }
  };

  return (
    <section id="capabilities" className="relative py-24 md:py-32 bg-[#040d12] text-slate-100">
      {/* Background glow element */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[350px] bg-[#00df8f]/5 rounded-full blur-[160px] pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold tracking-wider uppercase text-[#00df8f] bg-[#052119] border border-[#00df8f]/30">
            Universal Capabilities
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            Built for Any Business or Team That Takes Calls
          </h2>

          <p className="text-base sm:text-lg text-slate-400 leading-relaxed">
            Whether you are an enterprise, high-growth startup, real estate agency, or local service
            firm, choranta adapts to your exact operational workflow.
          </p>
        </div>

        {/* Tab Navigation Container */}
        <div className="rounded-2xl border border-[#143c49] bg-[#071720]/80 p-2 max-w-4xl mx-auto mb-10 backdrop-blur-md shadow-xl">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {WORKFLOW_TABS.map((tab) => {
              const isActive = tab.id === activeTabId;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTabId(tab.id)}
                  className={`flex items-center justify-center sm:justify-start gap-2.5 px-4 py-3 rounded-xl text-xs sm:text-sm font-semibold transition-all duration-200 cursor-pointer ${
                    isActive
                      ? 'bg-[#00df8f] text-[#022016] shadow-[0_0_20px_rgba(0,223,143,0.35)]'
                      : 'text-slate-300 hover:text-white hover:bg-[#0c232e]'
                  }`}
                >
                  {getTabIcon(
                    tab.iconName,
                    `w-4 h-4 shrink-0 ${isActive ? 'text-[#022016]' : 'text-slate-400'}`
                  )}
                  <span className="truncate">{tab.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Active Tab Card - Exactly matching Screenshot 2 */}
        <div className="rounded-3xl border border-[#143c49] bg-gradient-to-br from-[#091b22] to-[#06141a] p-8 md:p-12 shadow-2xl relative overflow-hidden">
          {/* Subtle accent border top */}
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-[#00df8f]/50 to-transparent" />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
            {/* Left Column */}
            <div className="lg:col-span-7 space-y-6">
              {/* Active Tab Badge */}
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold text-[#00df8f] bg-[#05261d] border border-[#00df8f]/40">
                {getTabIcon(activeTab.iconName, 'w-3.5 h-3.5 text-[#00df8f]')}
                <span>{activeTab.badge}</span>
              </div>

              {/* Title */}
              <h3 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-white tracking-tight leading-snug">
                {activeTab.title}
              </h3>

              {/* Description */}
              <p className="text-slate-300 text-base sm:text-lg leading-relaxed">
                {activeTab.description}
              </p>

              {/* Action Link */}
              <div className="pt-2">
                <button
                  onClick={() => onOpenDemo(activeTab.id)}
                  className="inline-flex items-center gap-2 text-[#00df8f] hover:text-[#00f59b] font-semibold text-base border-b-2 border-[#00df8f] hover:border-[#00f59b] pb-0.5 transition-all group cursor-pointer"
                >
                  <span>{activeTab.ctaText}</span>
                  <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-1" />
                </button>
              </div>
            </div>

            {/* Right Column: 4 Structured Feature Cards */}
            <div className="lg:col-span-5 space-y-3.5">
              {activeTab.features.map((feature, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-3.5 p-4 rounded-2xl bg-[#05141a]/90 border border-[#143c49] hover:border-[#00df8f]/40 transition-colors shadow-sm"
                >
                  <div className="w-6 h-6 rounded-full bg-[#05261d] border border-[#00df8f] flex items-center justify-center text-[#00df8f] shrink-0 shadow-[0_0_10px_rgba(0,223,143,0.3)]">
                    <CheckCircle className="w-4 h-4 fill-[#00df8f]/10" />
                  </div>
                  <span className="text-sm sm:text-base font-medium text-slate-200">
                    {feature}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
