import React from 'react';
import { Ban, Bot, Check, CheckCheck, Clock, Download, FileSpreadsheet, Flame, MessageCircle, PhoneCall, PhoneMissed, RotateCw } from 'lucide-react';
import { StoryPlayer, StoryScene } from './StoryPlayer';

/*
 * Campaigns told as a story for clients who aren't technical: one list of people, from the uploaded file to the
 * hot leads at the end of the day. What it says follows services/campaigns.py: calling hours between 9 am and 9 pm,
 * up to 3 retries for no-answer / busy / failed calls, and do-not-call numbers skipped.
 */

const delay = (ms: number): React.CSSProperties => ({ animationDelay: `${ms}ms` });

const FILE_ROWS = [
  { name: 'Priya Sharma', phone: '98765 43210', course: 'NEET 2027' },
  { name: 'Ravi Kumar', phone: '98765 43211', course: 'JEE Main' },
  { name: 'Asha Reddy', phone: '98765 43212', course: 'NEET 2027' },
  { name: 'Imran Khan', phone: '98765 43213', course: 'EAMCET' },
];

const UploadScene: React.FC = () => (
  <div className="w-72 space-y-2">
    <div className="story-pop flex items-center gap-2 rounded-lg border border-[#0a4d39] bg-[#052b20] px-3 py-2 text-[11px] text-emerald-50" style={delay(100)}>
      <FileSpreadsheet className="h-4 w-4 shrink-0 text-[#00df8f]" />
      <span className="flex-1 truncate font-semibold">enquiries-november.csv</span>
    </div>
    <div className="overflow-hidden rounded-lg border border-[#143c49] bg-[#06141a]">
      <div className="grid grid-cols-[1.3fr_1.1fr_0.9fr] gap-2 border-b border-[#143c49] bg-[#0a2028] px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wide text-slate-500">
        <span>Name</span>
        <span>Phone</span>
        <span>Course</span>
      </div>
      {FILE_ROWS.map((row, i) => (
        <div key={row.phone} className="story-pop grid grid-cols-[1.3fr_1.1fr_0.9fr] gap-2 border-b border-[#102d38] px-3 py-1.5 text-[10px] text-slate-200 last:border-0" style={delay(500 + i * 350)}>
          <span className="truncate">{row.name}</span>
          <span className="truncate font-mono text-slate-400">{row.phone}</span>
          <span className="truncate">{row.course}</span>
        </div>
      ))}
    </div>
    <div className="story-pop flex flex-wrap items-center justify-between gap-1 rounded-lg border border-dashed border-[#1d4b5a] px-3 py-2 text-[10px]" style={delay(2300)}>
      <span className="flex items-center gap-1 font-semibold text-[#00df8f]">
        <Check className="h-3 w-3" /> 4 people ready
      </span>
      <span className="text-slate-400">1 wrong number, 1 duplicate left out</span>
    </div>
  </div>
);

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const ScheduleScene: React.FC = () => (
  <div className="w-72 space-y-3 rounded-lg border border-[#143c49] bg-[#091b22] p-3">
    <div>
      <div className="mb-1.5 text-[10px] font-medium text-slate-400">Calling days</div>
      <div className="flex gap-1">
        {DAYS.map((day, i) => (
          <span
            key={day}
            className={`story-pop flex-1 rounded py-1 text-center text-[9px] font-semibold ${i < 6 ? 'bg-[#00df8f]/15 text-[#00df8f]' : 'bg-[#0a2028] text-slate-500'}`}
            style={delay(100 + i * 90)}
          >
            {day}
          </span>
        ))}
      </div>
    </div>
    <div>
      <div className="mb-1.5 flex justify-between text-[10px] font-medium text-slate-400">
        <span>Calling hours</span>
        <span className="story-pop text-[#00df8f]" style={delay(1100)}>10 am to 6 pm</span>
      </div>
      {/* 9 am to 9 pm is the full track; 10 am to 6 pm is 1/12 to 9/12 of it */}
      <div className="relative h-2 overflow-hidden rounded-full bg-[#143c49]">
        <span className="story-grow absolute inset-y-0 rounded-full bg-[#00df8f]" style={{ left: '8.33%', width: '66.67%', ...delay(800) }} />
      </div>
      <div className="mt-1 flex justify-between text-[9px] text-slate-500">
        <span>9 am</span>
        <span>9 pm</span>
      </div>
    </div>
    <div className="story-pop flex items-center gap-2 rounded border border-[#143c49] bg-[#06141a] px-2 py-1.5 text-[10px] text-slate-300" style={delay(1800)}>
      <RotateCw className="h-3 w-3 shrink-0 text-sky-300" />
      <span>If there's no answer, try again after 30 minutes</span>
    </div>
    <label className="story-pop flex items-center gap-1.5 text-[10px] text-slate-300" style={delay(2600)}>
      <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm bg-[#00df8f] text-[#04110c]">
        <Check className="h-2.5 w-2.5" />
      </span>
      These people agreed to be contacted
    </label>
    <div className="story-press rounded bg-[#00df8f] py-1 text-center text-[11px] font-semibold text-[#04110c]" style={delay(3400)}>
      Launch campaign
    </div>
  </div>
);

/** A status chip that says "Calling" first, then changes to the call's result. */
const CallResult: React.FC<{ at: number; className: string; children: React.ReactNode }> = ({ at, className, children }) => (
  <span className="relative inline-flex h-5 w-[5.5rem] items-center justify-end text-[9px] font-semibold">
    <span className="story-swap-out absolute right-0 flex items-center gap-1 rounded-full bg-sky-400/10 px-2 py-0.5 text-sky-300" style={delay(at)}>
      <PhoneCall className="h-2.5 w-2.5" /> Calling
    </span>
    <span className={`story-pop absolute right-0 flex items-center gap-1 rounded-full px-2 py-0.5 ${className}`} style={delay(at)}>
      {children}
    </span>
  </span>
);

const ANSWERED = 'bg-[#00df8f]/15 text-[#00df8f]';
const MISSED = 'bg-amber-400/10 text-amber-300';

const CallingScene: React.FC = () => (
  <div className="w-72 space-y-2">
    <div className="overflow-hidden rounded-lg border border-[#143c49] bg-[#06141a]">
      <div className="flex items-center justify-between border-b border-[#143c49] px-3 py-2">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-100">
          <Bot className="h-3.5 w-3.5 text-[#00df8f]" /> Your AI employee
        </span>
        <span className="flex items-center gap-1 text-[9px] text-slate-400">
          <span className="story-pulse h-1.5 w-1.5 rounded-full bg-emerald-500" /> Running
        </span>
      </div>
      <div className="flex items-center justify-between border-b border-[#102d38] px-3 py-2 text-[11px] text-slate-200">
        <span>Priya Sharma</span>
        <CallResult at={2200} className={ANSWERED}><Check className="h-2.5 w-2.5" /> Answered</CallResult>
      </div>
      <div className="flex items-center justify-between border-b border-[#102d38] px-3 py-2 text-[11px] text-slate-200">
        <span>Ravi Kumar</span>
        <CallResult at={1400} className={MISSED}><PhoneMissed className="h-2.5 w-2.5" /> No answer</CallResult>
      </div>
      <div className="flex items-center justify-between border-b border-[#102d38] px-3 py-2 text-[11px] text-slate-200">
        <span>Asha Reddy</span>
        <CallResult at={3200} className={ANSWERED}><Check className="h-2.5 w-2.5" /> Answered</CallResult>
      </div>
      <div className="flex items-center justify-between px-3 py-2 text-[11px] text-slate-500">
        <span>Imran Khan</span>
        <span className="story-pop flex items-center gap-1 rounded-full bg-rose-400/10 px-2 py-0.5 text-[9px] font-semibold text-rose-300" style={delay(300)}>
          <Ban className="h-2.5 w-2.5" /> Do-not-call
        </span>
      </div>
    </div>
    <div className="story-pop rounded-xl rounded-bl-none border border-[#0a4d39] bg-[#052b20] p-2 text-[11px] text-emerald-50" style={delay(2500)}>
      "Hi Priya! You asked about NEET 2027 coaching. Is this a good time to talk?"
    </div>
  </div>
);

const RETRY_STEPS = [
  { at: 200, time: '10:02 am', label: 'First call', Icon: PhoneMissed, tone: 'text-amber-300', result: 'No answer' },
  { at: 1100, time: '', label: 'Waits 30 minutes', Icon: Clock, tone: 'text-slate-400', result: '' },
  { at: 2000, time: '10:32 am', label: 'Second call', Icon: PhoneCall, tone: 'text-[#00df8f]', result: 'Answered' },
];

const RetryScene: React.FC = () => (
  <div className="w-72 rounded-lg border border-[#143c49] bg-[#091b22] p-3">
    <div className="mb-3 text-[11px] font-semibold text-slate-100">Ravi Kumar</div>
    <ol className="space-y-3 border-l border-dashed border-[#1d4b5a] pl-4">
      {RETRY_STEPS.map(({ at, time, label, Icon, tone, result }) => (
        <li key={label} className="story-pop relative" style={delay(at)}>
          <span className="absolute -left-[1.56rem] flex h-4 w-4 items-center justify-center rounded-full border border-[#1d4b5a] bg-[#06141a]">
            <Icon className={`h-2.5 w-2.5 ${tone}`} />
          </span>
          <div className="flex items-center justify-between text-[11px] text-slate-200">
            <span>{label}</span>
            {result && <span className={`text-[10px] font-semibold ${tone}`}>{result}</span>}
          </div>
          {time && <div className="text-[9px] text-slate-500">{time}</div>}
        </li>
      ))}
    </ol>
    <div className="story-pop mt-3 rounded border border-dashed border-[#1d4b5a] p-2 text-center text-[10px] text-slate-400" style={delay(3000)}>
      Every try is kept on Ravi's record
    </div>
  </div>
);

const STATS = [
  { value: '4', label: 'People', tone: 'text-slate-100' },
  { value: '3', label: 'Answered', tone: 'text-[#00df8f]' },
  { value: '1', label: 'Skipped', tone: 'text-rose-300' },
];

const ResultsScene: React.FC = () => (
  <div className="w-72 space-y-2">
    <div className="grid grid-cols-3 gap-2">
      {STATS.map((stat, i) => (
        <div key={stat.label} className="story-pop rounded-lg border border-[#143c49] bg-[#091b22] p-2 text-center" style={delay(100 + i * 250)}>
          <div className={`text-lg font-bold leading-tight ${stat.tone}`}>{stat.value}</div>
          <div className="text-[9px] text-slate-500">{stat.label}</div>
        </div>
      ))}
    </div>
    <div className="story-pop rounded-lg border border-[#143c49] bg-[#091b22] p-3" style={delay(1100)}>
      <div className="flex items-center gap-2 text-[11px]">
        <Flame className="h-3.5 w-3.5 text-[#00df8f]" />
        <span className="font-semibold text-slate-100">Priya Sharma</span>
        <span className="rounded bg-[#00df8f]/15 px-1.5 text-[9px] font-semibold text-[#00df8f]">Qualified lead</span>
      </div>
      <div className="mt-1 text-[10px] text-slate-400">Wants the free demo class on Saturday</div>
    </div>
    <div className="story-pop flex items-start gap-2 rounded-lg border border-[#143c49] bg-[#091b22] p-3 text-[10px] text-slate-300" style={delay(2000)}>
      <MessageCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
      <span className="flex-1">Course details sent on WhatsApp</span>
      <CheckCheck className="h-3.5 w-3.5 text-sky-400" />
    </div>
    <div className="story-pop flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-[#1d4b5a] p-2 text-[10px] text-slate-300" style={delay(2900)}>
      <Download className="h-3 w-3" /> Export all results as a spreadsheet
    </div>
  </div>
);

const SCENES: StoryScene[] = [
  {
    clock: '9:30 am',
    title: 'You upload your list',
    text: 'Upload a CSV or pick from your leads. Columns like the course become details your AI employee can use on the call. Wrong numbers and duplicates are left out.',
    Visual: UploadScene,
  },
  {
    clock: '9:35 am',
    title: 'You choose when it calls',
    text: 'Pick the days and the hours, anywhere between 9 am and 9 pm, and when to try again. Confirm these people agreed to be contacted, then launch.',
    Visual: ScheduleScene,
  },
  {
    clock: '10:00 am',
    title: 'Your AI employee works through the list',
    text: 'It makes several calls at once and uses each person\'s name and details. Numbers on your do-not-call list are skipped, and anyone who asks not to be called again is added to it.',
    Visual: CallingScene,
  },
  {
    clock: '10:32 am',
    title: 'Anyone it missed gets another try',
    text: 'Calls that go unanswered, come back busy or fail are tried again on your schedule, up to three more times, and only during your calling hours.',
    Visual: RetryScene,
  },
  {
    clock: '6:00 pm',
    title: 'You see how it went',
    text: 'Every call is summed up for you. Qualified leads land in Hot leads, they can get your WhatsApp message with the details, and you can export everything.',
    Visual: ResultsScene,
  },
];

export const CampaignStory: React.FC = () => (
  <StoryPlayer
    title="How Campaigns work"
    subtitle="From a list of numbers to a list of people worth calling back."
    footnote="Campaigns are for your existing customers and people who enquired. Promotional calls aren't supported."
    scenes={SCENES}
    sceneMs={5500}
  />
);
