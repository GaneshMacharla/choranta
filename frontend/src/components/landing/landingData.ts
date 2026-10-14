export interface WorkflowTab {
  id: string;
  label: string;
  iconName: string;
  badge: string;
  title: string;
  description: string;
  ctaText: string;
  features: string[];
}

export interface BenchmarkFactor {
  id: string;
  category: 'cost' | 'operations' | 'scalability' | 'fit';
  title: string;
  subtitle: string;
  human: string;
  ai: string;
  humanNote?: string;
  aiNote?: string;
  isHighlight?: boolean;
}

export interface AudioSample {
  id: string;
  title: string;
  language: string;
  industry: string;
  duration: string;
  dialogue: {
    speaker: 'Caller' | 'Choranta AI';
    text: string;
    time: string;
  }[];
}

export const WORKFLOW_TABS: WorkflowTab[] = [
  {
    id: 'sales',
    label: 'Lead Qualification & Sales',
    iconName: 'TrendingUp',
    badge: 'Lead Qualification & Sales',
    title: 'Turn Every Inbound Call into a Qualified Opportunity',
    description:
      'Never let a warm prospect bounce. The AI instantly answers callers from your website, ads, or offline campaigns, asks qualifying questions (budget, timeline, requirements), and schedules a sales call directly onto your calendar.',
    ctaText: 'Build an AI Voice Agent for this workflow',
    features: [
      'Instant 0-sec response to ad leads',
      'Budget & intent qualification',
      'Live warm transfer to sales reps',
      'CRM logging into HubSpot/Zoho',
    ],
  },
  {
    id: 'support',
    label: 'Customer Support & Inquiries',
    iconName: 'Headphones',
    badge: 'Customer Support & Inquiries',
    title: 'Resolve Inquiries Instantly Without Queuing Callers',
    description:
      'Eliminate hold times and IVR mazes forever. Choranta resolves tier-1 FAQs, warranty lookups, store locations, and account queries 24/7 with human-level empathy and zero wait time.',
    ctaText: 'Build an AI Voice Agent for this workflow',
    features: [
      'Instant 0-wait tier-1 resolution',
      'Multilingual support in 10+ Indian dialects',
      'Context-aware knowledge base search',
      'Warm escalation to human with full call summary',
    ],
  },
  {
    id: 'appointments',
    label: 'Appointment & Meeting Scheduling',
    iconName: 'Calendar',
    badge: 'Appointment & Meeting Scheduling',
    title: 'Fill Your Calendar Without Endless Phone Tag',
    description:
      'Perfect for clinics, salons, real estate, and professional consultancies. The AI checks live availability in Google Calendar or Outlook, locks slots in real time, and sends instant WhatsApp confirmations.',
    ctaText: 'Build an AI Voice Agent for this workflow',
    features: [
      'Live 2-way Google/Outlook calendar slot locking',
      'Automated reschedule & cancellation handling',
      'Instant WhatsApp confirmation & location ping',
      'Zero double-bookings & no-show reduction',
    ],
  },
  {
    id: 'retail',
    label: 'Retail, E-commerce & Delivery',
    iconName: 'ShoppingBag',
    badge: 'Retail, E-commerce & Delivery',
    title: 'Slash RTO and Automate Order Inquiries on Autopilot',
    description:
      'Verify Cash-on-Delivery orders before shipping, answer live tracking questions, and guide customers through returns seamlessly. Cut return-to-origin losses by up to 35%.',
    ctaText: 'Build an AI Voice Agent for this workflow',
    features: [
      'Automated COD verification & address confirmation',
      'Live courier tracking & ETA status lookup',
      'Self-service return & exchange guidance',
      'Abandoned checkout callback & cart recovery',
    ],
  },
];

export const BENCHMARK_FACTORS: BenchmarkFactor[] = [
  {
    id: 'monthly-cost',
    category: 'cost',
    title: 'Fixed monthly cost',
    subtitle: 'Up to 70% cheaper fixed overhead',
    human: '₹20,000 salary (~₹23–24k loaded w/ overhead)',
    ai: '₹6,000–17,000 retainer (tier-dependent)',
    isHighlight: true,
  },
  {
    id: 'idle-cost',
    category: 'cost',
    title: 'Cost when idle/zero calls',
    subtitle: 'Zero idle payroll drain',
    human: 'Still ₹20k+ — you pay regardless',
    ai: '₹0 beyond retainer',
  },
  {
    id: 'talk-time',
    category: 'operations',
    title: 'Productive talk-time',
    subtitle: '2.2x higher operational efficiency',
    human: '~45% of shift (rest = breaks, admin, wrap-up)',
    ai: '~100% — every paid minute is working',
    isHighlight: true,
  },
  {
    id: 'concurrency',
    category: 'scalability',
    title: 'Concurrent calls handled',
    subtitle: 'Zero busy tones for customers',
    human: '1 at a time',
    ai: 'Up to 4 (Starter tier channel limit, scales to 50+)',
  },
  {
    id: 'availability',
    category: 'operations',
    title: 'Availability',
    subtitle: '100% attendance & weekend coverage',
    human: '8hr shift, sick days, attrition, notice period',
    ai: '24/7, never sick, never quits',
    isHighlight: true,
  },
  {
    id: 'ramp-up',
    category: 'operations',
    title: 'Ramp-up time',
    subtitle: 'Go live in under 24 hours',
    human: 'Weeks (hiring + training)',
    ai: 'Hours (deploy/configure)',
  },
  {
    id: 'multilingual',
    category: 'fit',
    title: 'Multilingual',
    subtitle: 'Hinglish, Hindi, Tamil, Telugu, etc.',
    human: 'Usually 1–2 languages per hire',
    ai: 'Multiple Indian languages, same agent',
    isHighlight: true,
  },
  {
    id: 'scaling',
    category: 'scalability',
    title: 'Scaling up',
    subtitle: 'Instant burst capacity',
    human: 'Hire another agent (₹20k+ more, more training)',
    ai: 'Upgrade tier / add channels, same day',
  },
  {
    id: 'best-fit',
    category: 'fit',
    title: 'Best fit',
    subtitle: 'Ideal hybrid division of labor',
    human: 'High-touch, complex, emotionally sensitive calls',
    ai: 'High-volume routine calls: bookings, FAQs, confirmations',
  },
];

export const AUDIO_SAMPLES: AudioSample[] = [
  {
    id: 'real-estate',
    title: 'Real Estate Lead Qualification',
    language: 'Hinglish',
    industry: 'Real Estate',
    duration: '0:34',
    dialogue: [
      { speaker: 'Caller', time: '0:01', text: 'Hi, I saw your Instagram ad for the 3BHK flat in Sector 82.' },
      { speaker: 'Choranta AI', time: '0:04', text: 'Haanji namaste! Bilkul, Sector 82 premium towers mein 3BHK units available hain with clubhouse access. Are you looking to move in immediately ya investment perspective hai?' },
      { speaker: 'Caller', time: '0:14', text: 'Hum agle 2 mahine mein shift karna chahte hain. Approximate budget 1.4 Cr hai.' },
      { speaker: 'Choranta AI', time: '0:20', text: 'Perfect! Aapke budget mein do higher-floor corner units available hain. Main kal shaam 4 baje project manager ke saath site visit book kar doon?' },
      { speaker: 'Caller', time: '0:29', text: 'Haan, 4 baje theek rahega. Details WhatsApp kar dijiye.' },
      { speaker: 'Choranta AI', time: '0:32', text: 'Done! Location link aur brochure aapke WhatsApp pe bhej diya hai. Thank you!' },
    ],
  },
  {
    id: 'dental-clinic',
    title: 'Clinic Appointment & Pricing',
    language: 'Hindi & English',
    industry: 'Healthcare',
    duration: '0:28',
    dialogue: [
      { speaker: 'Caller', time: '0:01', text: 'Hello, mujhe teeth whitening aur root canal ka consultation karwana tha.' },
      { speaker: 'Choranta AI', time: '0:05', text: 'Namaste! Apex Dental Clinic mein welcome. Dr. Verma root canal specialist hain aur consultation fee ₹500 hai. Kya aap Indiranagar branch visit karna chahenge?' },
      { speaker: 'Caller', time: '0:15', text: 'Haan, Indiranagar. Wednesday subah 11 baje koi slot open hai?' },
      { speaker: 'Choranta AI', time: '0:20', text: 'Wednesday 11:30 AM slot open hai. Kya main aapka naam aur phone number lock kar doon?' },
      { speaker: 'Caller', time: '0:25', text: 'Ji bilkul, Amit Sharma.' },
      { speaker: 'Choranta AI', time: '0:27', text: 'Appointment confirmed! Aapko WhatsApp par token slip bhej di hai.' },
    ],
  },
  {
    id: 'd2c-order',
    title: 'COD Verification & Address Confirmation',
    language: 'Hinglish',
    industry: 'D2C E-commerce',
    duration: '0:24',
    dialogue: [
      { speaker: 'Choranta AI', time: '0:01', text: 'Hello Rajesh ji! Main UrbanKicks se baat kar rahi hoon. Aapne running shoes ka ₹2,499 ka Cash on Delivery order place kiya tha?' },
      { speaker: 'Caller', time: '0:08', text: 'Haan, maine order kiya tha.' },
      { speaker: 'Choranta AI', time: '0:11', text: 'Great! House number 42, Green Glen Layout, Bellandur address confirm hai dispatch ke liye?' },
      { speaker: 'Caller', time: '0:17', text: 'Haan, wahi address hai. Saturday tak deliver ho jayega?' },
      { speaker: 'Choranta AI', time: '0:20', text: 'Bilkul, Saturday evening tak expected delivery hai. Order dispatch kar diya gaya hai. Thank you!' },
    ],
  },
];
