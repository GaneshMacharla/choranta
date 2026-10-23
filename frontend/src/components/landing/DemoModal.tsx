import React, { useState } from 'react';
import { X, CheckCircle, PhoneCall, Sparkles, ShieldCheck, ArrowRight, ChevronDown } from 'lucide-react';

interface DemoModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialWorkflow?: string;
}

export const DemoModal: React.FC<DemoModalProps> = ({ isOpen, onClose, initialWorkflow = 'sales' }) => {
  const [formData, setFormData] = useState({
    fullName: '',
    phone: '',
    email: '',
    company: '',
    workflow: initialWorkflow,
    language: 'Hinglish',
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    // Simulate API registration & simulated automated test call trigger
    setTimeout(() => {
      setIsSubmitting(false);
      setIsSubmitted(true);
    }, 1200);
  };

  const handleReset = () => {
    setIsSubmitted(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg rounded-2xl border border-[#143c49] bg-[#081820] shadow-[0_0_50px_-10px_rgba(0,223,143,0.3)] p-6 md:p-8 text-slate-100 overflow-hidden">
        {/* Glow corner */}
        <div className="absolute top-0 right-0 -mr-16 -mt-16 w-48 h-48 bg-[#00df8f]/10 rounded-full blur-3xl pointer-events-none" />

        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-2 rounded-lg text-slate-400 hover:text-white hover:bg-[#0f2a36] transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {!isSubmitted ? (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#00df8f]/10 text-[#00df8f] border border-[#00df8f]/30">
                <Sparkles className="w-3 h-3" />
                Live Pilot Experience
              </span>
            </div>

            <h3 className="text-2xl font-bold text-white mb-2">
              Experience Choranta Voice AI for Your Business
            </h3>
            <p className="text-sm text-slate-400 mb-6 leading-relaxed">
              Fill in your details below. Our autonomous voice agent can call your phone in under 60 seconds with your custom business script.
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Your Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.fullName}
                    onChange={(e) => setFormData({ ...formData, fullName: e.target.value })}
                    placeholder="Ganesh Macharla"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#051116] border border-[#143c49] text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#00df8f] transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Mobile Number *
                  </label>
                  <input
                    type="tel"
                    required
                    value={formData.phone}
                    onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                    placeholder="+91 98765 43210"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#051116] border border-[#143c49] text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#00df8f] transition-colors"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Work Email *
                  </label>
                  <input
                    type="email"
                    required
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    placeholder="ganesh@company.com"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#051116] border border-[#143c49] text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#00df8f] transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Company / Organization
                  </label>
                  <input
                    type="text"
                    value={formData.company}
                    onChange={(e) => setFormData({ ...formData, company: e.target.value })}
                    placeholder="e.g. Apex Realty"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#051116] border border-[#143c49] text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#00df8f] transition-colors"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Primary Workflow
                  </label>
                  <div className="relative">
                  <select
                    value={formData.workflow}
                    onChange={(e) => setFormData({ ...formData, workflow: e.target.value })}
                    className="w-full appearance-none truncate pl-3.5 pr-10 py-2.5 rounded-xl bg-[#051116] border border-[#143c49] text-sm text-slate-100 [color-scheme:dark] focus:outline-none focus:border-[#00df8f] transition-colors cursor-pointer [&>option]:bg-[#051116] [&>option]:text-slate-100"
                  >
                    <option value="sales">Lead Qualification & Sales</option>
                    <option value="support">Customer Support & FAQs</option>
                    <option value="appointments">Appointment Scheduling</option>
                    <option value="retail">COD Verification & Delivery</option>
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Test Language
                  </label>
                  <div className="relative">
                  <select
                    value={formData.language}
                    onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                    className="w-full appearance-none truncate pl-3.5 pr-10 py-2.5 rounded-xl bg-[#051116] border border-[#143c49] text-sm text-slate-100 [color-scheme:dark] focus:outline-none focus:border-[#00df8f] transition-colors cursor-pointer [&>option]:bg-[#051116] [&>option]:text-slate-100"
                  >
                    <option value="Hinglish">Natural Hinglish (Recommended)</option>
                    <option value="Hindi">Pure Hindi</option>
                    <option value="English">Indian English</option>
                    <option value="Telugu">Telugu</option>
                    <option value="Tamil">Tamil</option>
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  </div>
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="w-full flex items-center justify-center gap-2 py-3.5 px-6 rounded-xl font-semibold text-[#022016] bg-[#00df8f] hover:bg-[#00f59b] transition-all duration-200 shadow-[0_0_20px_-3px_rgba(0,223,143,0.4)] disabled:opacity-50 cursor-pointer"
                >
                  {isSubmitting ? (
                    <>
                      <div className="w-4 h-4 border-2 border-[#022016] border-t-transparent rounded-full animate-spin" />
                      <span>Scheduling Instant Pilot Call...</span>
                    </>
                  ) : (
                    <>
                      <PhoneCall className="w-4 h-4" />
                      <span>Request Instant Demo Call</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>

              <div className="flex items-center justify-center gap-4 text-[11px] text-slate-400 pt-1">
                <span className="flex items-center gap-1">
                  <ShieldCheck className="w-3.5 h-3.5 text-[#00df8f]" />
                  Zero spam guarantee
                </span>
                <span>•</span>
                <span>Sub-600ms latency</span>
                <span>•</span>
                <span>No credit card required</span>
              </div>
            </form>
          </div>
        ) : (
          <div className="text-center py-6 space-y-4">
            <div className="w-16 h-16 rounded-full bg-[#00df8f]/20 border border-[#00df8f] text-[#00df8f] flex items-center justify-center mx-auto shadow-[0_0_25px_rgba(0,223,143,0.4)]">
              <CheckCircle className="w-8 h-8" />
            </div>

            <h3 className="text-2xl font-bold text-white">Call Dispatched!</h3>
            <p className="text-sm text-slate-300 max-w-sm mx-auto leading-relaxed">
              We've queued a demo call to <span className="font-mono text-[#00df8f]">{formData.phone}</span> in{' '}
              <span className="font-semibold text-white">{formData.language}</span> for your{' '}
              <span className="text-white font-medium">{formData.workflow}</span> use case.
            </p>

            <div className="rounded-xl border border-[#143c49] bg-[#051116] p-4 text-xs text-left space-y-2">
              <div className="flex items-center justify-between text-slate-400">
                <span>Dispatch Mode:</span>
                <span className="text-emerald-400 font-mono">Autonomous Outbound</span>
              </div>
              <div className="flex items-center justify-between text-slate-400">
                <span>WhatsApp Summary:</span>
                <span className="text-slate-200">Will be sent upon call wrap-up</span>
              </div>
              <div className="flex items-center justify-between text-slate-400">
                <span>Enterprise SLA:</span>
                <span className="text-slate-200">99.98% High Availability</span>
              </div>
            </div>

            <button
              onClick={handleReset}
              className="px-6 py-2.5 rounded-xl font-medium bg-[#0f2934] hover:bg-[#143c49] text-slate-200 transition-colors text-sm"
            >
              Close Window
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
