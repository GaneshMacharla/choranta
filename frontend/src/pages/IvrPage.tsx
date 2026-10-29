import React from 'react';
import { Network, GitBranch, Voicemail, Clock } from 'lucide-react';

const PLANNED = [
  { icon: GitBranch, title: 'Menu builder', text: 'Press 1 for admissions, 2 for fees: route callers by keypad or by voice.' },
  { icon: Network, title: 'Hand-off to AI employees', text: 'Send each menu branch to the right AI employee or a human number.' },
  { icon: Clock, title: 'Business hours', text: 'Different greetings and routing for working hours, after hours and holidays.' },
  { icon: Voicemail, title: 'Voicemail & callbacks', text: 'Capture a message or schedule a callback when nobody can take the call.' },
];

/** Placeholder for the IVR builder; shared by the internal studio and the client portal. */
export const IvrPage: React.FC = () => (
  <div className="mx-auto max-w-3xl py-10">
    <div className="flex flex-col items-center text-center">
      <div className="mb-4 rounded-full border border-[#00df8f]/30 bg-[#00df8f]/10 p-4 text-[#00df8f]">
        <Network className="h-7 w-7" />
      </div>
      <span className="mb-2 rounded-full border border-amber-400/40 bg-amber-400/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300">
        Coming soon
      </span>
      <h1 className="text-lg font-semibold text-slate-100">IVR</h1>
      <p className="mt-1 max-w-md text-xs text-slate-400">
        Build call menus that greet callers, route them to the right AI employee and handle after-hours calls.
      </p>
    </div>

    <div className="mt-8 grid gap-3 sm:grid-cols-2">
      {PLANNED.map(({ icon: Icon, title, text }) => (
        <div key={title} className="rounded-lg border border-[#102d38] bg-[#071419] p-4 opacity-80">
          <div className="mb-1.5 flex items-center gap-2 text-sm font-medium text-slate-200">
            <Icon className="h-4 w-4 text-[#00df8f]" /> {title}
          </div>
          <p className="text-xs text-slate-400">{text}</p>
        </div>
      ))}
    </div>
  </div>
);
