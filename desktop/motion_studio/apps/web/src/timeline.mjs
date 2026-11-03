export function makeId(prefix = "clip") {
  return `${prefix}_${globalThis.crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
}

export function segmentGraphemes(text) {
  if (typeof Intl.Segmenter !== "function") {
    throw new Error("Este navegador precisa oferecer suporte a Intl.Segmenter.");
  }
  return Array.from(new Intl.Segmenter("pt-BR", { granularity: "grapheme" }).segment(text), (part) => part.segment);
}

export function addTextClip(timeline, text) {
  const track = timeline.tracks.find((candidate) => candidate.kind === "text");
  if (!track) throw new Error("A timeline precisa ter uma trilha de texto.");
  const clips = track.clips;
  const end = clips.reduce((maximum, clip) => Math.max(maximum, clip.start_frame + clip.duration_frames), 0);
  const clip = {
    id: makeId(),
    kind: "text",
    name: text.slice(0, 48),
    text,
    start_frame: end,
    duration_frames: timeline.fps * 3,
    style: {
      animation: "fade",
      color: "#f8fafc",
      font_size: 72,
      graphemes: segmentGraphemes(text).map((value) => ({ value, color: "#f8fafc", animation: "fade" })),
    },
  };
  return {
    ...timeline,
    tracks: timeline.tracks.map((candidate) =>
      candidate.id === track.id ? { ...candidate, clips: [...clips, clip] } : candidate,
    ),
  };
}

export function updateGraphemeStyle(timeline, clipId, graphemeIndex, patch) {
  return {
    ...timeline,
    tracks: timeline.tracks.map((track) => ({
      ...track,
      clips: track.clips.map((clip) => {
        if (clip.id !== clipId || clip.kind !== "text") return clip;
        const graphemes = [...(clip.style.graphemes ?? [])];
        if (!graphemes[graphemeIndex]) return clip;
        graphemes[graphemeIndex] = { ...graphemes[graphemeIndex], ...patch };
        return { ...clip, style: { ...clip.style, graphemes } };
      }),
    })),
  };
}

/** Build a same-origin playback URL from server-issued identifiers, never disk paths. */
export function wanVideoPreviewUrl(runId, artifactId) {
  const safe = (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
  if (!safe(runId) || !safe(artifactId)) return null;
  return `/api/motion/runs/${runId}/artifacts/${artifactId}/preview`;
}

/** Preserve generated scenes on the project video track without duplicate imports. */
export function addWanVideoClip(timeline, { runId, artifactId, name, frames, fps }) {
  if (!wanVideoPreviewUrl(runId, artifactId)) throw new Error("Invalid generated video reference");
  if (!Number.isInteger(frames) || frames < 1 || frames > 3600 ||
      !Number.isInteger(fps) || fps < 1 || fps > 120) {
    throw new Error("Invalid generated video timing");
  }
  const track = timeline.tracks.find((item) => item.kind === "video");
  if (!track) throw new Error("A timeline precisa ter uma trilha de vídeo.");
  if (track.clips.some((clip) => clip.style?.motion_run_id === runId &&
      clip.style?.motion_artifact_id === artifactId)) return timeline;
  const start = track.clips.reduce((end, clip) => Math.max(end, clip.start_frame + clip.duration_frames), 0);
  const clip = {
    id: makeId("wan"),
    kind: "video",
    name: String(name || "Cena Wan").slice(0, 160),
    start_frame: start,
    duration_frames: Math.max(1, Math.round(frames / fps * timeline.fps)),
    style: {
      motion_run_id: runId,
      motion_artifact_id: artifactId,
      source_frames: frames,
      source_fps: fps,
      version: 1,
      review_status: "pending",
      review_comment: "",
    },
  };
  return {
    ...timeline,
    tracks: timeline.tracks.map((item) => item.id === track.id ?
      { ...item, clips: [...item.clips, clip] } : item),
  };
}

/** Update review metadata for one scene without touching other clips or artifacts. */
export function updateClipReview(timeline, clipId, patch) {
  const allowed = new Set(["pending", "approved", "needs_revision"]);
  if (patch.review_status !== undefined && !allowed.has(patch.review_status)) {
    throw new Error("Invalid scene review status");
  }
  if (patch.review_comment !== undefined && (typeof patch.review_comment !== "string" || patch.review_comment.length > 2000)) {
    throw new Error("Invalid scene review comment");
  }
  return {
    ...timeline,
    tracks: timeline.tracks.map((track) => ({
      ...track,
      clips: track.clips.map((clip) => clip.id === clipId
        ? { ...clip, style: { ...clip.style, ...patch } }
        : clip),
    })),
  };
}

/** Single-scene runs use the legacy "motion-" prefix; episode runs use the raw project ID. */
export function wanRunMatchesProject(runProjectId, projectId) {
  return typeof runProjectId === "string" && typeof projectId === "string" &&
    projectId.length > 0 && (runProjectId === projectId || runProjectId === "motion-" + projectId);
}

/** Return the exact composition end, or zero for an empty project. */
export function compositionEndFrame(timeline) {
  return (timeline?.tracks ?? []).flatMap((track) => track.clips ?? [])
    .reduce((end, clip) => Math.max(end, clip.start_frame + clip.duration_frames), 0);
}

/** Format frame-accurate timecode as HH:MM:SS:FF. */
export function formatTimecode(frame, fps) {
  const rate = Number.isFinite(fps) && fps > 0 ? Math.floor(fps) : 1;
  const value = Math.max(0, Math.floor(frame));
  const seconds = Math.floor(value / rate);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60, value % rate]
    .map((part) => String(part).padStart(2, "0")).join(":");
}
