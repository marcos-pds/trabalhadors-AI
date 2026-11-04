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
export function addWanVideoClip(timeline, { runId, artifactId, name, frames, fps, replaceClipId, sceneNumber, plannedPrompt, plannedTitle }) {
  if (!wanVideoPreviewUrl(runId, artifactId)) throw new Error("Invalid generated video reference");
  if (!Number.isInteger(frames) || frames < 1 || frames > 3600 ||
      !Number.isInteger(fps) || fps < 1 || fps > 120) {
    throw new Error("Invalid generated video timing");
  }
  const track = timeline.tracks.find((item) => item.kind === "video");
  if (!track) throw new Error("A timeline precisa ter uma trilha de vídeo.");
  if (track.clips.some((clip) =>
      (clip.style?.motion_run_id === runId && clip.style?.motion_artifact_id === artifactId) ||
      clip.style?.previous_versions?.some((version) => version.run_id === runId && version.artifact_id === artifactId))) return timeline;
  const replaced = replaceClipId ? track.clips.find((clip) => clip.id === replaceClipId) : null;
  const start = replaced?.start_frame ?? track.clips.reduce((end, clip) => Math.max(end, clip.start_frame + clip.duration_frames), 0);
  const priorVersions = replaced ? [...(replaced.style?.previous_versions ?? []), {
    clip_id: replaced.id,
    run_id: replaced.style?.motion_run_id ?? null,
    artifact_id: replaced.style?.motion_artifact_id ?? null,
    version: Number(replaced.style?.version ?? 1),
    name: replaced.name,
    start_frame: replaced.start_frame,
    duration_frames: replaced.duration_frames,
    style: { ...replaced.style },
  }] : [];
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
      scene_number: sceneNumber ?? null,
      planned_prompt: plannedPrompt ?? "",
      planned_title: plannedTitle ?? String(name || "Cena Wan"),
      version: Number(replaced?.style?.version ?? 0) + 1,
      previous_versions: priorVersions,
      review_status: "pending",
      review_comment: "",
    },
  };
  return {
    ...timeline,
    tracks: timeline.tracks.map((item) => item.id === track.id ?
      { ...item, clips: replaced
        ? item.clips.map((candidate) => candidate.id === replaced.id ? clip : candidate)
        : [...item.clips, clip] } :
      replaced && item.kind === 'audio' ?
        { ...item, clips: item.clips.filter((candidate) => candidate.style?.source_video_clip_id !== replaced.id) } : item),
  };
}

export function addWanSpeechClip(timeline, { runId, artifactId, videoArtifactId, speaker, text, voiceProfile, replaceClipId }) {
  if (!wanVideoPreviewUrl(runId, artifactId)) throw new Error('Invalid generated audio reference');
  const video = timeline.tracks.find((track) => track.kind === 'video')?.clips.find((clip) =>
    clip.style?.motion_run_id === runId && clip.style?.motion_artifact_id === videoArtifactId);
  const audioTrack = timeline.tracks.find((track) => track.kind === 'audio');
  if (!video || !audioTrack) return timeline;
  if (audioTrack.clips.some((clip) => clip.style?.motion_run_id === runId && clip.style?.motion_artifact_id === artifactId)) return timeline;
  const clips = audioTrack.clips.filter((clip) => clip.style?.source_video_clip_id !== replaceClipId);
  clips.push({ id: makeId('speech'), kind: 'audio', name: `${speaker} · fala`,
    start_frame: video.start_frame, duration_frames: video.duration_frames,
    style: { motion_run_id: runId, motion_artifact_id: artifactId,
      source_video_clip_id: video.id, speaker, speech_text: text, voice_profile: voiceProfile } });
  return { ...timeline, tracks: timeline.tracks.map((track) => track.id === audioTrack.id ? { ...track, clips } : track) };
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

/** Restore a previous scene snapshot while retaining the selected clip identity. */
export function restoreClipVersion(timeline, clipId, version) {
  const target = timeline.tracks.flatMap((track) => track.clips)
    .find((clip) => clip.id === clipId);
  const snapshot = target?.style?.previous_versions?.find((item) => item.version === version);
  if (!target || !snapshot || !snapshot.style) throw new Error("Scene version not found");
  const restoredStyle = { ...snapshot.style, version: snapshot.version, previous_versions: (target.style.previous_versions ?? [])
    .filter((item) => item.version !== snapshot.version) };
  return {
    ...timeline,
    tracks: timeline.tracks.map((track) => ({
      ...track,
      clips: track.clips.map((clip) => clip.id === clipId ? {
        ...clip,
        name: snapshot.name ?? clip.name,
        start_frame: snapshot.start_frame,
        duration_frames: snapshot.duration_frames,
        style: restoredStyle,
      } : clip),
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
