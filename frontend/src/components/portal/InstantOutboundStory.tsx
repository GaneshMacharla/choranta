import React from 'react';
import { Bot, Check, CheckCheck, Flame, Globe, KeyRound, MessageCircle, PhoneCall, User } from 'lucide-react';
import { StoryPlayer, StoryScene } from './StoryPlayer';

/*
 * Instant outbound told as a 30-second story for clients who aren't technical: one enquiry, from the form on
 * their website to the AI employee's call and the result in their portal.
 */

const Browser: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="w-64 overflow-hidden rounded-lg border border-[#1d4b5a] bg-[#06141a] shadow-lg">
    <div className="flex items-center gap-1.5 border-b border-[#143c49] bg-[#0a2028] px-2 py-1.5">
      <span className="h-2 w-2 rounded-full bg-rose-400/70" />
      <span className="h-2 w-2 rounded-full bg-amber-400/70" />
      <span className="h-2 w-2 rounded-full bg-emerald-400/70" />
      <span className="ml-2 flex-1 truncate rounded bg-[#06141a] px-2 text-[9px] text-slate-500">yourwebsite.com/contact</span>
    </div>
    <div className="space-y-2 p-3">{children}</div>
  </div>
);

const Field: React.FC<{ label: string; value: string; delay: number }> = ({ label, value, delay }) => (
  <div>
    <div className="text-[9px] text-slate-500">{label}</div>
    <div className="h-6 overflow-hidden rounded border border-[#143c49] bg-[#040d12] px-2 text-[11px] leading-6 text-slate-100">
      <span className="story-type inline-block overflow-hidden whitespace-nowrap align-top" style={{ animationDelay: `${delay}ms` }}>
        {value}
      </span>
    </div>
  </div>
);

const FormScene: React.FC = () => (
  <Browser>
    <div className="text-[11px] font-semibold text-slate-200">Enquire about a course</div>
    <Field label="Name" value="Priya Sharma" delay={200} />
    <Field label="Phone" value="98765 43210" delay={1100} />
    <Field label="Course" value="NEET 2027" delay={2000} />
    <label className="story-pop flex items-center gap-1.5 text-[10px] text-slate-300" style={{ animationDelay: '2800ms' }}>
      <span className="flex h-3.5 w-3.5 items-center justify-center rounded-sm bg-[#00df8f] text-[#04110c]">
        <Check className="h-2.5 w-2.5" />
      </span>
      Yes, call me about my enquiry
    </label>
    <div className="story-press rounded bg-[#00df8f] py-1 text-center text-[11px] font-semibold text-[#04110c]" style={{ animationDelay: '3400ms' }}>
      Submit
    </div>
  </Browser>
);

const HandoffScene: React.FC = () => (
  <div className="flex items-center gap-2 sm:gap-4">
    <div className="flex flex-col items-center gap-1.5">
      <div className="flex h-16 w-16 items-center justify-center rounded-xl border border-[#1d4b5a] bg-[#06141a]">
        <Globe className="h-7 w-7 text-sky-300" />
      </div>
      <span className="text-[10px] text-slate-400">Your website</span>
    </div>
    <div className="relative h-16 w-28 sm:w-40">
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 border-t border-dashed border-[#1d4b5a]" />
      <span className="story-packet absolute top-1/2 flex -translate-y-1/2 items-center gap-1 rounded-full border border-[#0a4d39] bg-[#052b20] px-1.5 py-0.5 text-[9px] text-[#00df8f]">
        <User className="h-2.5 w-2.5" /> Priya
      </span>
      <div className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1 text-[9px] text-slate-500">
        <KeyRound className="h-2.5 w-2.5" /> sent with your secret key
      </div>
    </div>
    <div className="flex flex-col items-center gap-1.5">
      <div className="story-glow flex h-16 w-16 items-center justify-center rounded-xl border border-[#0a4d39] bg-[#052b20]">
        <img src="/logo.png" alt="" className="h-8 w-8 object-contain" />
      </div>
      <span className="text-[10px] text-slate-400">Choranta</span>
    </div>
  </div>
);

const CallScene: React.FC = () => (
  <div className="flex items-end gap-3">
    <div className="story-ring w-36 rounded-[22px] border-2 border-[#1d4b5a] bg-[#040d12] p-2 shadow-lg">
      <div className="rounded-2xl bg-gradient-to-b from-[#0a2a22] to-[#06141a] px-2 py-4 text-center">
        <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-[#00df8f]/20">
          <PhoneCall className="h-5 w-5 text-[#00df8f]" />
        </div>
        <div className="mt-2 text-[11px] font-semibold text-slate-100">Incoming call</div>
        <div className="text-[10px] text-slate-400">Your business</div>
        <div className="mt-3 flex justify-center gap-4">
          <span className="h-6 w-6 rounded-full bg-rose-500/80" />
          <span className="story-pulse h-6 w-6 rounded-full bg-emerald-500" />
        </div>
      </div>
      <div className="mt-1 text-center text-[9px] text-slate-500">Priya's phone</div>
    </div>
    <div className="story-pop mb-6 max-w-[11rem] rounded-xl rounded-bl-none border border-[#0a4d39] bg-[#052b20] p-2 text-[11px] text-emerald-50" style={{ animationDelay: '1200ms' }}>
      <div className="mb-1 flex items-center gap-1 text-[9px] font-semibold text-[#00df8f]">
        <Bot className="h-3 w-3" /> Your AI employee
      </div>
      "Hi Priya! You just asked about NEET 2027 coaching. Can I tell you about our next batch?"
    </div>
  </div>
);

const ResultScene: React.FC = () => (
  <div className="w-64 space-y-2">
    <div className="story-pop rounded-lg border border-[#143c49] bg-[#091b22] p-3" style={{ animationDelay: '200ms' }}>
      <div className="flex items-center gap-2 text-[11px]">
        <Flame className="h-3.5 w-3.5 text-[#00df8f]" />
        <span className="font-semibold text-slate-100">Priya Sharma</span>
        <span className="rounded bg-[#00df8f]/15 px-1.5 text-[9px] font-semibold text-[#00df8f]">Qualified lead</span>
      </div>
      <div className="mt-1 text-[10px] text-slate-400">Booked the free demo class, Saturday 10 am</div>
    </div>
    <div className="story-pop flex items-start gap-2 rounded-lg border border-[#143c49] bg-[#091b22] p-3 text-[10px] text-slate-300" style={{ animationDelay: '1100ms' }}>
      <MessageCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
      <span className="flex-1">Course details sent to her on WhatsApp</span>
      <CheckCheck className="h-3.5 w-3.5 text-sky-400" />
    </div>
    <div className="story-pop rounded-lg border border-dashed border-[#1d4b5a] p-2 text-center text-[10px] text-slate-400" style={{ animationDelay: '2000ms' }}>
      Your team just follows up: it's all in Hot leads
    </div>
  </div>
);

const SCENES: StoryScene[] = [
  {
    clock: '0:00',
    title: 'Someone fills the form on your website',
    text: 'Priya wants NEET coaching. She leaves her name and number and ticks "Yes, call me".',
    Visual: FormScene,
  },
  {
    clock: '0:02',
    title: 'Your website passes it to Choranta',
    text: 'In the background, your website sends her details to your Choranta address, with your secret key. Nobody has to do anything.',
    Visual: HandoffScene,
  },
  {
    clock: '0:20',
    title: 'Your AI employee calls her within 30 seconds',
    text: "She's still thinking about you, so she picks up. The AI already knows her name and the course she asked about.",
    Visual: CallScene,
  },
  {
    clock: '0:30',
    title: 'You see the result',
    text: 'The call is summed up for you. Qualified leads land in Hot leads, and she can get your WhatsApp message with the details.',
    Visual: ResultScene,
  },
];

export const InstantOutboundStory: React.FC = () => (
  <StoryPlayer
    title="How Instant Outbound works"
    subtitle="From a form on your website to a phone call, in 30 seconds."
    footnote="Calls happen during the calling hours you choose. An enquiry at night is called as soon as your hours start."
    scenes={SCENES}
  />
);
