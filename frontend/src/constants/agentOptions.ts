// Option lists shared by the AI Employee editor and the create wizard

export const AVAILABLE_LANGUAGES: { value: string; label: string }[] = [
  { value: 'hi', label: 'Hindi (हिन्दी / Hinglish) - hi' },
  { value: 'en-IN', label: 'English (India) - en-IN' },
  { value: 'en', label: 'English (India / Global) - en' },
  { value: 'te', label: 'Telugu (తెలుగు) - te' },
  { value: 'ta', label: 'Tamil (தமிழ்) - ta' },
  { value: 'kn', label: 'Kannada (ಕನ್ನಡ) - kn' },
  { value: 'ml', label: 'Malayalam (മലയാളം) - ml' },
  { value: 'mr', label: 'Marathi (मराठी) - mr' },
  { value: 'bn', label: 'Bengali (বাংলা) - bn' },
  { value: 'gu', label: 'Gujarati (ગુજરાતી) - gu' },
  { value: 'pa', label: 'Punjabi (ਪੰਜਾਬੀ) - pa' },
  { value: 'or', label: 'Odia (ଓଡ଼ିଆ) - or' },
  { value: 'ur', label: 'Urdu (اردو) - ur' },
];

export const getLanguageOptions = (currentValue?: string): { value: string; label: string }[] => {
  if (currentValue && !AVAILABLE_LANGUAGES.some((l) => l.value === currentValue)) {
    return [{ value: currentValue, label: `${currentValue} (Current / Custom)` }, ...AVAILABLE_LANGUAGES];
  }
  return AVAILABLE_LANGUAGES;
};

export const STT_PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: 'sarvam', label: 'Sarvam (Saaras v4, Indian languages)' },
  { value: 'cartesia', label: 'Cartesia (Realtime Streaming WebSocket STT)' },
  { value: 'mock_stt', label: 'Mock STT (Deterministic Test Mode)' },
];

export const LLM_PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: 'sarvam', label: 'Sarvam (sarvam-105b-conversations, Indian languages)' },
  { value: 'gemini', label: 'Google Gemini (Gemini 3.8 Flash / Realtime)' },
  { value: 'mock_llm', label: 'Mock LLM (Deterministic Test Mode)' },
];

export const TTS_PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: 'cartesia', label: 'Cartesia (Sonic 3, Indian voices like Siya)' },
  { value: 'sarvam', label: 'Sarvam (Bulbul v3, Indian voices)' },
  { value: 'mock_tts', label: 'Mock TTS (Deterministic Test Mode)' },
];

export const TELEPHONY_PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'None (Browser WebRTC / WebSocket Audio Only)' },
  { value: 'exotel', label: 'Exotel Voice (Inbound PSTN via Voicebot Applet)' },
  { value: 'mock_telephony', label: 'Mock Telephony (Deterministic Call Runner)' },
];

export const getProviderOptions = (
  options: { value: string; label: string }[],
  currentVal?: string | null
): { value: string; label: string }[] => {
  if (currentVal && !options.some((o) => o.value === currentVal)) {
    return [{ value: currentVal, label: `${currentVal} (Custom)` }, ...options];
  }
  return options;
};

// Roles offered when creating an AI employee (Agents page and the client page)
export const AGENT_ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: 'Receptionist', label: 'Receptionist' },
  { value: 'Appointment Coordinator', label: 'Appointment Coordinator' },
  { value: 'Customer Support Specialist', label: 'Customer Support Specialist' },
  { value: 'Sales Assistant', label: 'Sales Assistant' },
  { value: 'Lead Qualification Specialist', label: 'Lead Qualification Specialist' },
  { value: 'Batch Enrolment Caller', label: 'Batch Enrolment Caller' },
  { value: 'Scheduling Coordinator', label: 'Scheduling Coordinator' },
  { value: 'Information Desk Assistant', label: 'Information Desk Assistant' },
  { value: 'Other', label: 'Other' },
];

// Friendly first names suggested for a new AI employee (several match Sarvam voice names)
export const AGENT_NAME_SUGGESTIONS: string[] = [
  'Priya', 'Ananya', 'Kavya', 'Meera', 'Neha', 'Anjali', 'Sneha', 'Diya',
  'Arjun', 'Rahul', 'Aditya', 'Karthik', 'Rohan', 'Vikram',
];
