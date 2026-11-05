import test from "node:test";
import assert from "node:assert/strict";
import { addSceneSpeechClip, addTextClip, addWanSpeechClip, addWanVideoClip, compositionEndFrame, formatTimecode, restoreClipVersion, segmentGraphemes, standaloneSpeechPreviewUrl, updateClipReview, updateGraphemeStyle, wanRunMatchesProject, wanVideoPreviewUrl } from "./timeline.mjs";

test("composition duration follows clips, frame rate, and empty projects", () => {
  assert.equal(compositionEndFrame({ fps: 24, tracks: [] }), 0);
  const timeline = { fps: 30, tracks: [{ clips: [
    { start_frame: 0, duration_frames: 150 },
    { start_frame: 150, duration_frames: 45 },
  ] }] };
  assert.equal(compositionEndFrame(timeline), 195);
  assert.equal(formatTimecode(195, 30), "00:00:06:15");
  assert.equal(formatTimecode(0, 24), "00:00:00:00");
});

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

test("scene speech follows video timing, survives refresh, and is replaced with the scene", () => {
  const empty = { fps: 24, tracks: [
    { id: 'video', kind: 'video', clips: [] }, { id: 'sound', kind: 'audio', clips: [] },
  ] };
  const first = addWanVideoClip(empty, { runId: 'run1', artifactId: 'video', name: 'Cena 1', frames: 81, fps: 16 });
  const input = { runId: 'run1', artifactId: 'speech', videoArtifactId: 'video', speaker: 'Lara', text: 'Oi.', voiceProfile: 'lara' };
  const spoken = addWanSpeechClip(first, input);
  assert.equal(spoken.tracks[1].clips[0].start_frame, 0);
  assert.equal(spoken.tracks[1].clips[0].duration_frames, 122);
  assert.strictEqual(addWanSpeechClip(spoken, input), spoken);
  const oldId = spoken.tracks[0].clips[0].id;
  const revised = addWanVideoClip(spoken, { runId: 'run2', artifactId: 'video', name: 'Cena 1', frames: 81, fps: 16, replaceClipId: oldId });
  assert.equal(revised.tracks[1].clips.length, 0);
  const resynthesized = addWanSpeechClip(revised, { ...input, runId: 'run2', replaceClipId: oldId });
  assert.equal(resynthesized.tracks[1].clips[0].style.source_video_clip_id, revised.tracks[0].clips[0].id);
});

test("adds a new voice take to an existing scene without replacing the video", () => {
  const empty = { fps: 24, tracks: [
    { id: 'video', kind: 'video', clips: [] }, { id: 'sound', kind: 'audio', clips: [] },
  ] };
  const video = addWanVideoClip(empty, { runId: 'run1', artifactId: 'video', name: 'Lara', frames: 81, fps: 16 });
  const videoId = video.tracks[0].clips[0].id;
  const input = { audioId: 'take1', videoClipId: videoId, speaker: 'Lara', text: 'Quem está aí?', voiceProfile: 'lara' };
  const first = addSceneSpeechClip(video, input);
  assert.equal(first.tracks[1].clips[0].duration_frames, 122);
  assert.equal(first.tracks[1].clips[0].start_frame, 0);
  assert.equal(first.tracks[0].clips[0].id, videoId);
  assert.strictEqual(addSceneSpeechClip(first, input), first);
  const revised = addSceneSpeechClip(first, { ...input, audioId: 'take2' });
  assert.equal(revised.tracks[1].clips.length, 1);
  assert.equal(revised.tracks[1].clips[0].style.motion_speech_id, 'take2');
  assert.equal(standaloneSpeechPreviewUrl('take2'), '/api/motion/scene-speech/take2/preview');
  assert.equal(standaloneSpeechPreviewUrl('../other'), null);
});

test("reviews one scene without changing neighboring clips", () => {
  const timeline = { fps: 24, tracks: [{ id: "video", kind: "video", clips: [
    { id: "one", start_frame: 0, duration_frames: 24, style: { review_status: "pending" } },
    { id: "two", start_frame: 24, duration_frames: 24, style: { review_status: "pending" } },
  ] }] };
  const reviewed = updateClipReview(timeline, "one", { review_status: "needs_revision", review_comment: "Trocar o enquadramento" });
  assert.equal(reviewed.tracks[0].clips[0].style.review_status, "needs_revision");
  assert.equal(reviewed.tracks[0].clips[0].style.review_comment, "Trocar o enquadramento");
  assert.deepEqual(reviewed.tracks[0].clips[1], timeline.tracks[0].clips[1]);
  assert.throws(() => updateClipReview(timeline, "one", { review_status: "invalid" }), /Invalid scene review status/);
});

test("regenerating a scene replaces it in place and keeps its previous version reference", () => {
  const timeline = { fps: 24, tracks: [{ id: "video", kind: "video", clips: [
    { id: "old", name: "Cena antiga", start_frame: 12, duration_frames: 24, style: {
      motion_run_id: "run-old", motion_artifact_id: "video-old", version: 1,
    } },
  ] }] };
  const next = addWanVideoClip(timeline, {
    runId: "run-new", artifactId: "video-new", name: "Cena revisada", frames: 81, fps: 16, replaceClipId: "old",
  });
  const clip = next.tracks[0].clips[0];
  assert.equal(next.tracks[0].clips.length, 1);
  assert.equal(clip.start_frame, 12);
  assert.equal(clip.style.version, 2);
  assert.deepEqual(clip.style.previous_versions[0], {
    clip_id: "old", run_id: "run-old", artifact_id: "video-old", version: 1,
    name: "Cena antiga", start_frame: 12, duration_frames: 24,
    style: { motion_run_id: "run-old", motion_artifact_id: "video-old", version: 1 },
  });
  assert.strictEqual(addWanVideoClip(next, {
    runId: "run-old", artifactId: "video-old", frames: 81, fps: 16,
  }), next);
  const restored = restoreClipVersion(next, clip.id, 1).tracks[0].clips[0];
  assert.equal(restored.style.motion_artifact_id, "video-old");
  assert.equal(restored.style.version, 1);
});

test("video URLs remain same-origin and reject non-identifier paths", () => {
  assert.equal(wanVideoPreviewUrl("run-1", "video_01"),
    "/api/motion/runs/run-1/artifacts/video_01/preview");
  assert.equal(wanVideoPreviewUrl("run/../../outside", "video"), null);
  assert.equal(wanVideoPreviewUrl("run", "https://example.com/video.mp4"), null);
  assert.throws(() => addWanVideoClip({ fps: 24, tracks: [] },
    { runId: "run", artifactId: "../../bad", frames: 81, fps: 16 }));
});

test("imports single-scene runs whose project ID has the backend motion prefix", () => {
  assert.equal(wanRunMatchesProject("motion-project123", "project123"), true);
  assert.equal(wanRunMatchesProject("project123", "project123"), true);
  assert.equal(wanRunMatchesProject("motion-other", "project123"), false);
  assert.equal(wanRunMatchesProject(undefined, "project123"), false);
  assert.equal(wanRunMatchesProject("motion-project1234", "project123"), false);
});
