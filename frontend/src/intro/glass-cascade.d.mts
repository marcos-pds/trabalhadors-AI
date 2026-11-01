export const GLASS_CASCADE_DURATION_MS: 7000;
export type GlassCascadeTheme = 'auto' | 'light' | 'dark';
export type GlassCascadeResult = {
  reason: 'completed' | 'skipped' | 'destroyed';
  durationMs: 7000;
  elapsedMs: number;
};
export type GlassCascadeOptions = {
  theme?: GlassCascadeTheme;
  sound?: boolean;
  volume?: number;
  audioUrl?: string;
  container?: HTMLElement;
  appRoot?: HTMLElement;
  onComplete?: (result: GlassCascadeResult) => void;
};
export type GlassCascadeController = {
  finished: Promise<GlassCascadeResult>;
  enableSound: () => Promise<boolean>;
  setMuted: (muted: boolean) => Promise<boolean>;
  skip: () => void;
  destroy: () => void;
};
export function mountGlassCascade(options?: GlassCascadeOptions): GlassCascadeController;
export function sampleGlassCascade(elapsedMs: number, index: number, reducedMotion?: boolean): {
  x: number; y: number; scale: number; rotate: number; rotateY: number;
  opacity: number; exit: number; complete: boolean;
};
