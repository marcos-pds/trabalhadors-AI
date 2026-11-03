import test from "node:test";
import assert from "node:assert/strict";
import { addTextClip, addWanVideoClip, segmentGraphemes, updateGraphemeStyle, wanVideoPreviewUrl } from "./timeline.mjs";

test("segments composed and accented text as Unicode graphemes", () => {
  assert.deepEqual(segmentGraphemes("Ação 👩🏽‍🚀 e\u0301"), ["A", "ç", "ã", "o", " ", "👩🏽‍🚀", " ", "é"]);
});

test("adds text to the next frame after existing clips and preserves distinct per-grapheme styles", () => {
  const timeline = {
    fps: 24,
    tracks: [{ id: "text", name: "Text", kind: "text", clips: [
      { id: "old", kind: "text", name: "old", text: "Oi", start_frame: 0, duration_frames: 48, style: {} },
    ] }],
  };
  const added = addTextClip(timeline, "AÇÃO");
  const clip = added.tracks[0].clips[1];
  assert.equal(clip.start_frame, 48);
  const styled = updateGraphemeStyle(added, clip.id, 0, { color: "#ff00ff", animation: "spring" });
  assert.equal(styled.tracks[0].clips[1].style.graphemes[0].color, "#ff00ff");
  assert.equal(styled.tracks[0].clips[1].style.graphemes[0].animation, "spring");
  assert.equal(styled.tracks[0].clips[1].style.graphemes[1].color, "#f8fafc");
});

test("imports a completed Wan scene at the end of the video track exactly once", () => {
  const timeline = {
    fps: 24,
    tracks: [
      { id: "video_main", name: "Video", kind: "video", clips: [] },
      { id: "titles", name: "Titles", kind: "text", clips: [] },
    ],
  };
  const input = { runId: "scene-run-1", artifactId: "video", name: "Cena 1", frames: 81, fps: 16 };
  const first = addWanVideoClip(timeline, input);
  assert.equal(first.tracks[0].clips.length, 1);
  assert.equal(first.tracks[0].clips[0].duration_frames, 122);
  assert.equal(first.tracks[0].clips[0].start_frame, 0);
  assert.strictEqual(addWanVideoClip(first, input), first);
  const second = addWanVideoClip(first, { ...input, artifactId: "video_02", frames: 121 });
  assert.equal(second.tracks[0].clips[1].start_frame, 122);
  assert.equal(second.tracks[0].clips[1].duration_frames, 182);
  assert.equal(second.tracks[1].clips.length, 0);
});

test("video URLs remain same-origin and reject non-identifier paths", () => {
  assert.equal(wanVideoPreviewUrl("run-1", "video_01"),
    "/api/motion/runs/run-1/artifacts/video_01/preview");
  assert.equal(wanVideoPreviewUrl("run/../../outside", "video"), null);
  assert.equal(wanVideoPreviewUrl("run", "https://example.com/video.mp4"), null);
  assert.throws(() => addWanVideoClip({ fps: 24, tracks: [] },
    { runId: "run", artifactId: "../../bad", frames: 81, fps: 16 }));
});
