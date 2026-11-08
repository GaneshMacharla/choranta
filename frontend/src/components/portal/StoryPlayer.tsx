import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Pause, Play } from 'lucide-react';

/*
 * A feature told as a short story for clients who aren't technical. Plays by itself; viewers can pause or step
 * through it. The stories themselves are InstantOutboundStory and CampaignStory.
 */

export interface StoryScene {
  clock: string;
  title: string;
  text: string;
  Visual: React.FC;
}

interface StoryPlayerProps {
  title: string;
  subtitle: string;
  footnote: string;
  scenes: StoryScene[];
  sceneMs?: number;
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

export const StoryPlayer: React.FC<StoryPlayerProps> = ({ title, subtitle, footnote, scenes, sceneMs = 4500 }) => {
  const [scene, setScene] = useState(0);
  const [playing, setPlaying] = useState(() => !prefersReducedMotion());
  // Time left on a paused scene, so playing again carries on where it stopped (the progress bar freezes with it)
  const left = useRef({ scene: 0, ms: sceneMs });

  useEffect(() => {
    if (!playing) return;
    const ms = left.current.scene === scene ? left.current.ms : sceneMs;
    const started = Date.now();
    const timer = setTimeout(() => setScene((s) => (s + 1) % scenes.length), ms);
    return () => {
      clearTimeout(timer);
      left.current = { scene, ms: Math.max(0, ms - (Date.now() - started)) };
    };
  }, [scene, playing, scenes.length, sceneMs]);

  const go = (next: number) => setScene((next + scenes.length) % scenes.length);
  const { Visual, title: sceneTitle, text, clock } = scenes[scene];

  return (
    <section
      className="overflow-hidden rounded-xl border border-[#143c49] bg-gradient-to-br from-[#091b22] via-[#071820] to-[#05231b]"
      aria-roledescription="carousel"
      aria-label={title}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#102d38] px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <p className="text-xs text-slate-400">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-[#1d4b5a] bg-[#040d12] px-3 py-1 font-mono text-sm text-[#00df8f]">
          <span className="h-2 w-2 animate-pulse rounded-full bg-[#00df8f]" /> {clock}
        </div>
      </div>

      <div className="grid items-center gap-6 px-5 py-6 md:grid-cols-[1fr_1.1fr]">
        <div className="space-y-3" aria-live="polite">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[#00df8f]">
            Step {scene + 1} of {scenes.length}
          </div>
          <h3 className="text-lg font-bold text-slate-100">{sceneTitle}</h3>
          <p className="text-sm leading-relaxed text-slate-300">{text}</p>
        </div>
        {/* Keyed by scene so its animations start again each time it appears */}
        <div key={scene} className="story-scene flex min-h-[270px] items-center justify-center">
          <Visual />
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-[#102d38] px-5 py-3">
        <div className="flex flex-1 gap-1.5">
          {scenes.map((s, i) => (
            <button
              key={s.title}
              type="button"
              aria-label={`Step ${i + 1}: ${s.title}`}
              aria-current={i === scene}
              onClick={() => go(i)}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#143c49]"
            >
              <span
                key={`${scene}-${i}`}
                className={`block h-full rounded-full bg-[#00df8f] ${i < scene ? 'w-full' : i === scene ? 'story-progress' : 'w-0'}`}
                style={i === scene ? { animationDuration: `${sceneMs}ms`, animationPlayState: playing ? 'running' : 'paused' } : undefined}
              />
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 text-slate-400">
          <button type="button" aria-label="Previous step" onClick={() => go(scene - 1)} className="rounded p-1 hover:bg-[#0f2c38] hover:text-slate-100">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label={playing ? 'Pause' : 'Play'}
            onClick={() => setPlaying((p) => !p)}
            className="rounded p-1 hover:bg-[#0f2c38] hover:text-slate-100"
          >
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>
          <button type="button" aria-label="Next step" onClick={() => go(scene + 1)} className="rounded p-1 hover:bg-[#0f2c38] hover:text-slate-100">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <p className="border-t border-[#102d38] px-5 py-2 text-[11px] text-slate-500">{footnote}</p>
    </section>
  );
};
