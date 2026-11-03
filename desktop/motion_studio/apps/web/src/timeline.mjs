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
    },
  };
  return {
    ...timeline,
    tracks: timeline.tracks.map((item) => item.id === track.id ?
      { ...item, clips: [...item.clips, clip] } : item),
  };
}

/** Single-scene runs use the legacy "motion-" prefix; episode runs use the raw project ID. */
export function wanRunMatchesProject(runProjectId, projectId) {
  return typeof runProjectId === "string" && typeof projectId === "string" &&
    projectId.length > 0 && (runProjectId === projectId || runProjectId === "motion-" + projectId);
}
