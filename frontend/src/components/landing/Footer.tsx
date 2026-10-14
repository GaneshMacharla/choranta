import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Phone, Mail, ShieldCheck, Heart } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="relative bg-[#02070a] border-t border-[#143c49]/60 text-slate-400 text-xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-10 mb-12">
          {/* Brand info */}
          <div className="lg:col-span-2 space-y-4">
            <Link to="/" className="flex items-center gap-2.5">
              <img src="/logo.png" alt="Choranta" className="h-8 w-8 object-contain" />
              <span className="font-extrabold text-base tracking-wider text-white">CHORANTA</span>
            </Link>
            <p className="text-slate-400 text-xs leading-relaxed max-w-sm">
              Deploy human-like, autonomous AI voice agents that speak fluent Hinglish, Hindi, and English.
              Scale to 50+ concurrent customer calls with sub-600ms latency, zero hold times, and instant CRM sync.
            </p>

            <div className="flex items-center gap-2.5 text-[11px] text-[#00df8f] pt-2">
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00df8f] opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00df8f]" />
              </span>
              <span>All Systems Operational • 99.98% Telephony SLA</span>
            </div>
          </div>

          {/* Solutions */}
          <div className="space-y-3">
            <h4 className="font-bold text-white text-xs uppercase tracking-wider">Solutions</h4>
            <ul className="space-y-2">
              <li>
                <a href="#capabilities" className="hover:text-[#00df8f] transition-colors">
                  Lead Qualification &amp; Sales
                </a>
              </li>
              <li>
                <a href="#capabilities" className="hover:text-[#00df8f] transition-colors">
                  Customer Support &amp; FAQs
                </a>
              </li>
              <li>
                <a href="#capabilities" className="hover:text-[#00df8f] transition-colors">
                  Appointment Scheduling
                </a>
              </li>
              <li>
                <a href="#capabilities" className="hover:text-[#00df8f] transition-colors">
                  COD Verification &amp; Delivery
                </a>
              </li>
            </ul>
          </div>

          {/* Platform */}
          <div className="space-y-3">
            <h4 className="font-bold text-white text-xs uppercase tracking-wider">Platform</h4>
            <ul className="space-y-2">
              <li>
                <a href="#benchmark" className="hover:text-[#00df8f] transition-colors">
                  Human vs. AI Benchmark
                </a>
              </li>
              <li>
                <a href="#demo" className="hover:text-[#00df8f] transition-colors">
                  Audio Speech Demos
                </a>
              </li>
              <li>
                <a href="#roi" className="hover:text-[#00df8f] transition-colors">
                  Annual ROI Calculator
                </a>
              </li>
              <li>
                <a href="#integrations" className="hover:text-[#00df8f] transition-colors">
                  HubSpot &amp; WhatsApp Sync
                </a>
              </li>
            </ul>
          </div>

          {/* Access */}
          <div className="space-y-3">
            <h4 className="font-bold text-white text-xs uppercase tracking-wider">Access</h4>
            <ul className="space-y-2">
              <li>
                <Link to="/login" className="hover:text-[#00df8f] transition-colors flex items-center gap-1">
                  <span>Sign In</span>
                  <ArrowUpRight className="w-3 h-3" />
                </Link>
              </li>
              <li>
                <Link to="/portal" className="hover:text-[#00df8f] transition-colors">
                  Client Portal
                </Link>
              </li>
              <li>
                <a href="#faq" className="hover:text-[#00df8f] transition-colors">
                  FAQ &amp; Security
                </a>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="pt-8 border-t border-[#143c49]/60 flex flex-col sm:flex-row items-center justify-between gap-4 text-[11px] text-slate-500">
          <div>
            &copy; 2026 Choranta Inc. All rights reserved. Indian DPDP Compliant Telephony.
          </div>
          <div className="flex items-center gap-6">
            <span>Built with precision for high-growth teams</span>
          </div>
        </div>
      </div>
    </footer>
  );
};
