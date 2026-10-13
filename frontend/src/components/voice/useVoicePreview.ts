import { useEffect, useRef, useState } from 'react';

/**
 * Plays one voice preview at a time. Previews are fetched with the user's token (an <audio> tag can't send it)
 * and kept as object URLs, so replaying a voice doesn't download it again.
 */
export function useVoicePreview(fetchPreview: (voiceId: string) => Promise<Blob>) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const urls = useRef<Record<string, string>>({});
  const [playing, setPlaying] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () => () => {
      audio.current?.pause();
      Object.values(urls.current).forEach((url) => URL.revokeObjectURL(url));
    },
    []
  );

  const stop = () => {
    audio.current?.pause();
    setPlaying(null);
  };

  const toggle = async (voiceId: string) => {
    if (playing === voiceId) return stop();
    stop();
    setError(null);
    try {
      let url = urls.current[voiceId];
      if (!url) {
        setLoading(voiceId);
        url = URL.createObjectURL(await fetchPreview(voiceId));
        urls.current[voiceId] = url;
      }
      if (!audio.current) audio.current = new Audio();
      audio.current.src = url;
      audio.current.onended = () => setPlaying(null);
      await audio.current.play();
      setPlaying(voiceId);
    } catch (e: any) {
      setError(e?.message || 'Could not play the preview.');
    } finally {
      setLoading(null);
    }
  };

  return { playing, loading, error, toggle, stop };
}
