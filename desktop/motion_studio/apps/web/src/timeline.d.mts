type TimelineShape = {
  fps: number;
  tracks: {
    id: string;
    kind: string;
    clips: {
      id: string;
      start_frame: number;
      duration_frames: number;
    }[];
  }[];
};

export function makeId(prefix?: string): string;
export function segmentGraphemes(text: string): string[];
export function addTextClip<T extends TimelineShape>(timeline: T, text: string): T;
export function updateGraphemeStyle<T extends TimelineShape>(
  timeline: T,
  clipId: string,
  graphemeIndex: number,
  patch: Record<string, string>,
): T;

export function wanVideoPreviewUrl(runId: string, artifactId: string): string | null;
export function addWanVideoClip<T extends TimelineShape>(
  timeline: T,
  video: { runId: string; artifactId: string; name: string; frames: number; fps: number },
): T;
