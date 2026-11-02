import test from "node:test";
import assert from "node:assert/strict";
import { addTextClip, segmentGraphemes, updateGraphemeStyle } from "./timeline.mjs";

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
