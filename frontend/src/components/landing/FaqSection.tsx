import React, { useState } from 'react';
import { ChevronDown, HelpCircle } from 'lucide-react';

export const FaqSection: React.FC = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  const faqs = [
    {
      q: 'Can Choranta really speak naturally in Hinglish and switch languages mid-sentence?',
      a: 'Yes! Choranta is purpose-built for the Indian linguistic landscape. It recognizes and speaks fluid Hinglish, pure Hindi, Indian English, and regional dialects (like Telugu and Tamil). If a customer starts in English and transitions into Hindi, Choranta code-switches instantly with native pronunciation and inflection.',
    },
    {
      q: 'How does Choranta connect with our existing company phone number?',
      a: 'You can either forward incoming calls from your existing landline or mobile carrier (Airtel, Jio, Vi) to your dedicated Choranta virtual DID, or port your numbers directly via SIP trunking. Setup takes less than 15 minutes without any hardware required.',
    },
    {
      q: 'What happens when a caller asks a complex question the AI cannot answer?',
      a: 'Choranta supports Warm Live Transfer. The AI courteously acknowledges the query ("Ek second, main aapko hamare senior manager se connect kar deta hoon"), sends an instant WhatsApp/Slack briefing to your team with the caller\'s context, and patches the live call through to a human rep.',
    },
    {
      q: 'How does the pricing work compared to hiring human telecallers?',
      a: 'A typical in-house or outsourced BPO caller costs ₹20,000–₹25,000/month loaded with overhead, yet delivers only ~45% productive talk time. Choranta starts with a predictable retainer (₹6,000–₹17,000 depending on tier) with sub-second per-minute billing for active talk-time. Most clients reduce total call center spend by 65–75%.',
    },
    {
      q: 'How fast can our business go live with Choranta?',
      a: 'You can configure your agent\'s personality, business knowledge base, and calendar rules in under a few hours. After a round of simulated test calls in our studio, your AI employee can be answering real customer calls on day one.',
    },
    {
      q: 'Is customer data protected under Indian DPDP regulations?',
      a: 'Absolutely. All voice data, transcripts, and customer records are processed with TLS 1.3 encryption and stored in compliant Indian data centers (Mumbai and Hyderabad). We enforce strict SOC2-aligned privacy controls and zero unauthorized model training on client call records.',
    },
  ];

  const handleToggle = (index: number) => {
    setOpenIndex(openIndex === index ? null : index);
  };

  return (
    <section id="faq" className="relative py-24 bg-[#040d12] text-slate-100">
      <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider text-[#00df8f] bg-[#052119] border border-[#00df8f]/30">
            <HelpCircle className="w-3.5 h-3.5" />
            <span>Frequently Asked Questions</span>
          </div>

          <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
            Everything You Need to Know
          </h2>

          <p className="text-slate-400 text-base">
            Answers to common questions about deploying Choranta AI voice agents for your team.
          </p>
        </div>

        <div className="space-y-4">
          {faqs.map((faq, idx) => {
            const isOpen = openIndex === idx;
            return (
              <div
                key={idx}
                className="rounded-2xl border border-[#143c49] bg-[#071922] transition-colors overflow-hidden"
              >
                <button
                  onClick={() => handleToggle(idx)}
                  className="w-full flex items-center justify-between p-5 sm:p-6 text-left cursor-pointer hover:bg-[#0a232f] transition-colors"
                >
                  <span className="text-base sm:text-lg font-semibold text-white pr-4">
                    {faq.q}
                  </span>
                  <ChevronDown
                    className={`w-5 h-5 text-[#00df8f] shrink-0 transition-transform duration-200 ${
                      isOpen ? 'rotate-180' : ''
                    }`}
                  />
                </button>
                {isOpen && (
                  <div className="px-5 pb-6 sm:px-6 sm:pb-6 text-sm sm:text-base text-slate-300 leading-relaxed border-t border-[#102a35] pt-4">
                    {faq.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};
