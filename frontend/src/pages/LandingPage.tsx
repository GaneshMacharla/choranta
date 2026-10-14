import React, { useState } from 'react';
import { Navbar } from '../components/landing/Navbar';
import { HeroSection } from '../components/landing/HeroSection';
import { UniversalCapabilitiesSection } from '../components/landing/UniversalCapabilitiesSection';
import { BenchmarkSection } from '../components/landing/BenchmarkSection';
import { RoiCalculatorSection } from '../components/landing/RoiCalculatorSection';
import { AudioShowcaseSection } from '../components/landing/AudioShowcaseSection';
import { SecurityIntegrationsSection } from '../components/landing/SecurityIntegrationsSection';
import { FaqSection } from '../components/landing/FaqSection';
import { Footer } from '../components/landing/Footer';
import { DemoModal } from '../components/landing/DemoModal';

export const LandingPage: React.FC = () => {
  const [isDemoModalOpen, setIsDemoModalOpen] = useState(false);
  const [demoWorkflow, setDemoWorkflow] = useState<string>('sales');

  const handleOpenDemo = (workflow: string = 'sales') => {
    setDemoWorkflow(workflow);
    setIsDemoModalOpen(true);
  };

  const handleCloseDemo = () => {
    setIsDemoModalOpen(false);
  };

  return (
    <div className="min-h-screen bg-[#040d12] text-slate-100 selection:bg-[#00df8f]/30 selection:text-[#00df8f]">
      {/* Top Fixed Navigation */}
      <Navbar onOpenDemo={() => handleOpenDemo('sales')} />

      {/* Main Landing Sections */}
      <main>
        {/* Hero Section (Matching Screenshot 1) */}
        <HeroSection onOpenDemo={handleOpenDemo} />

        {/* Universal Capabilities Section (Matching Screenshot 2) */}
        <UniversalCapabilitiesSection onOpenDemo={handleOpenDemo} />

        {/* Economic & Operational Benchmark Section (Matching Screenshot 3 & 4) */}
        <BenchmarkSection onOpenDemo={() => handleOpenDemo('hybrid')} />

        {/* Interactive Cost & ROI Calculator */}
        <RoiCalculatorSection onOpenDemo={() => handleOpenDemo('roi')} />

        {/* Real Audio Showcase & Speech Nuances */}
        <AudioShowcaseSection onOpenDemo={handleOpenDemo} />

        {/* Enterprise Security & CRM Integrations */}
        <SecurityIntegrationsSection onOpenDemo={() => handleOpenDemo('integrations')} />

        {/* Frequently Asked Questions */}
        <FaqSection />
      </main>

      {/* Footer */}
      <Footer />

      {/* Interactive Pilot Call Request Modal */}
      <DemoModal
        isOpen={isDemoModalOpen}
        onClose={handleCloseDemo}
        initialWorkflow={demoWorkflow}
      />
    </div>
  );
};

export default LandingPage;
