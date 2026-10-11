import React, { useEffect, useState } from 'react';
import { Volume2, AlertTriangle } from 'lucide-react';
import { telephonyService } from '../../services/telephony';

interface CallRecordingPlayerProps {
  callId: string;
  /** Loads the recording; defaults to the internal call endpoint (the client portal passes its own). */
  fetchBlob?: (callId: string) => Promise<Blob>;
}

/**
 * Plays a call's stereo recording (caller left, agent right). The file is fetched with the
 * user's auth token and played from an object URL, since <audio src> can't send headers.
 */
export const CallRecordingPlayer: React.FC<CallRecordingPlayerProps> = ({ callId, fetchBlob }) => {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setAudioUrl(null);
    setError(null);
    (fetchBlob ? fetchBlob(callId) : telephonyService.getRecordingBlob(callId))
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Could not load the recording.');
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [callId]);

  return (
    <div className="p-3 bg-[#052b20]/25 border border-[#0a4d39]/50 rounded space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-[#00df8f] flex items-center gap-1.5">
          <Volume2 className="h-4 w-4" />
          Call Recording
        </span>
        <span className="text-[10px] text-slate-500">Caller: left channel · Agent: right channel</span>
      </div>
      {error ? (
        <p className="flex items-center gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="h-3.5 w-3.5" /> {error}
        </p>
      ) : audioUrl ? (
        <audio controls src={audioUrl} className="w-full h-8" />
      ) : (
        <p className="text-xs text-slate-500">Loading recording...</p>
      )}
    </div>
  );
};
