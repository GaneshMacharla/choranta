// Timezones offered for clients and campaigns (IANA names, India first)

export const DEFAULT_TIMEZONE = 'Asia/Kolkata';

export const TIMEZONES: { value: string; label: string }[] = [
  { value: 'Asia/Kolkata', label: 'India (IST, UTC+5:30) - Asia/Kolkata' },
  { value: 'Asia/Dubai', label: 'UAE (GST, UTC+4) - Asia/Dubai' },
  { value: 'Asia/Riyadh', label: 'Saudi Arabia (UTC+3) - Asia/Riyadh' },
  { value: 'Asia/Singapore', label: 'Singapore (UTC+8) - Asia/Singapore' },
  { value: 'Asia/Kathmandu', label: 'Nepal (UTC+5:45) - Asia/Kathmandu' },
  { value: 'Asia/Dhaka', label: 'Bangladesh (UTC+6) - Asia/Dhaka' },
  { value: 'Asia/Colombo', label: 'Sri Lanka (UTC+5:30) - Asia/Colombo' },
  { value: 'Europe/London', label: 'United Kingdom - Europe/London' },
  { value: 'America/New_York', label: 'US Eastern - America/New_York' },
  { value: 'America/Los_Angeles', label: 'US Pacific - America/Los_Angeles' },
  { value: 'Australia/Sydney', label: 'Australia Eastern - Australia/Sydney' },
  { value: 'UTC', label: 'UTC' },
];

/** Dropdown options, keeping a saved value that isn't in the list so it still shows. */
export const timezoneOptions = (current?: string | null) =>
  current && !TIMEZONES.some((tz) => tz.value === current)
    ? [{ value: current, label: current }, ...TIMEZONES]
    : TIMEZONES;
