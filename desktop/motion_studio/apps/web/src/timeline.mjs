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
