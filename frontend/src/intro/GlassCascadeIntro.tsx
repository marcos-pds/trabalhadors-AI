import { useEffect, useRef } from 'react';
import {
  mountGlassCascade,
  type GlassCascadeResult,
  type GlassCascadeTheme,
} from './glass-cascade.mjs';
import './glass-cascade.css';

export type GlassCascadeIntroProps = {
  enabled?: boolean;
  theme?: GlassCascadeTheme;
  sound?: boolean;
  volume?: number;
  audioUrl?: string;
  /** ID do conteúdo da Central. A sobreposição é montada fora dele, em body. */
  appRootId?: string;
  onComplete?: (result: GlassCascadeResult) => void;
};

/** Compatível com React StrictMode; não bloqueia a abertura por causa de áudio. */
export default function GlassCascadeIntro({
  enabled = true,
  theme = 'auto',
  sound = true,
  volume = 0.55,
  audioUrl,
  appRootId,
  onComplete,
}: GlassCascadeIntroProps) {
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;

  useEffect(() => {
    if (!enabled) return;
    const intro = mountGlassCascade({
      theme,
      sound,
      volume,
      audioUrl,
      appRoot: appRootId ? document.getElementById(appRootId) ?? undefined : undefined,
      onComplete: (result) => completeRef.current?.(result),
    });
    return () => intro.destroy();
  }, [enabled, theme, sound, volume, audioUrl, appRootId]);

  return null;
}
