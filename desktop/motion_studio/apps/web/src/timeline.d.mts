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
  video: { runId: string; artifactId: string; name: string; frames: number; fps: number; replaceClipId?: string; sceneNumber?: number; plannedPrompt?: string; plannedTitle?: string },
): T;
export function addWanSpeechClip<T extends TimelineShape>(
  timeline: T,
  speech: { runId: string; artifactId: string; videoArtifactId: string; speaker: string; text: string; voiceProfile: string; replaceClipId?: string },
): T;
export function addSceneCaptionClip<T extends TimelineShape>(
  timeline: T,
  caption: { runId: string; videoArtifactId: string; text: string },
): T;
export function updateSceneCaptionClip<T extends TimelineShape>(timeline: T, videoClipId: string, text: string): T;
export function standaloneSpeechPreviewUrl(audioId: string): string | null;
export function addSceneSpeechClip<T extends TimelineShape>(
  timeline: T,
  speech: { audioId: string; videoClipId: string; speaker: string; text: string; voiceProfile: string },
): T;

export function wanRunMatchesProject(runProjectId: string | undefined, projectId: string): boolean;
export function compositionEndFrame(timeline: TimelineShape): number;
export function formatTimecode(frame: number, fps: number): string;
export function updateClipReview<T extends TimelineShape>(timeline: T, clipId: string, patch: {
  review_status?: "pending" | "approved" | "needs_revision";
  review_comment?: string;
}): T;
export function restoreClipVersion<T extends TimelineShape>(timeline: T, clipId: string, version: number): T;
