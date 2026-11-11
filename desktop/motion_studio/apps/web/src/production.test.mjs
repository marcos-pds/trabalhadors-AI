import { test } from "node:test";
import { strict as assert } from "node:assert";
import { allSceneImagesReady, characterMasterPrompt, meanPixelDifference, parseProductionPlan, referenceAnchor, sceneReference, sceneTimingForSpeech } from "./production.mjs";

const scenes = Array.from({ length: 8 }, (_, index) => ({ scene: index + 1, title: `Cena ${index + 1}`,
  image_prompt: "Caio at the laboratory bench", prompt: "Caio lifts the flask" }));

test("planning requires a visual direction and separate image and video prompts", () => {
  const plan = parseProductionPlan('```json\n' + JSON.stringify({ visual_bible: "Caio wears blue and white", scenes }) + '\n```');
  assert.equal(plan.scenes[0].image_prompt, "Caio at the laboratory bench");
  assert.throws(() => parseProductionPlan(JSON.stringify({ visual_bible: "Same character", scenes: scenes.map(({ image_prompt, ...rest }) => rest) })), /direção visual/);
});

test("planning accepts multiple worker proposals and uses the final complete one", () => {
  const first = { visual_bible: "First proposal", scenes };
  const final = { visual_bible: "Final proposal", scenes: scenes.map((scene) => ({ ...scene, dialogue: "Caio ouve pensamentos." })) };
  const output = `## Designer IA\n${JSON.stringify(first)}\n\n## Revisor IA\n${JSON.stringify(final)}`;
  assert.equal(parseProductionPlan(output).visual_bible, "Final proposal");
});

test("video stage waits until every scene has its image", () => {
  const references = scenes.slice(0, 7).map((scene) => ({ scene_number: scene.scene, kind: "setting", image_data: "data:image/png;base64,AA==" }));
  assert.equal(allSceneImagesReady(scenes, references), false);
  references.push({ scene_number: 8, kind: "setting", image_data: "data:image/png;base64,AA==" });
  assert.equal(allSceneImagesReady(scenes, references), true);
});

test("image review detects nearly unchanged frames before video", () => {
  const first = new Uint8ClampedArray([30, 40, 50, 255, 60, 70, 80, 255]);
  const same = new Uint8ClampedArray([32, 42, 52, 255, 62, 72, 82, 255]);
  const changed = new Uint8ClampedArray([90, 100, 110, 255, 120, 130, 140, 255]);
  assert.ok(meanPixelDifference(first, same) < 10);
  assert.ok(meanPixelDifference(first, changed) >= 10);
});

test("spoken scenes reserve more playback time within the local video limit", () => {
  assert.deepEqual(sceneTimingForSpeech(""), { frames: 49, fps: 16 });
  assert.deepEqual(sceneTimingForSpeech("Pensamentos flutuam ao redor."), { frames: 49, fps: 12 });
});

test("uploaded master anchors each scene; otherwise the prior scene does", () => {
  const prior = { scene_number: 1, kind: "setting", image_data: "prior" };
  const master = { kind: "character", image_data: "master" };
  assert.equal(referenceAnchor([prior], 2), prior);
  assert.equal(referenceAnchor([prior, master], 2), master);
});

test("generated character master anchors later scenes and carries the visual bible", () => {
  const master = { kind: "character", image_data: "master", source: "generated_image" };
  const prior = { scene_number: 1, kind: "setting", image_data: "prior" };
  assert.equal(referenceAnchor([prior, master], 2), master);
  assert.match(characterMasterPrompt("Caio wears blue goggles and a white coat"), /blue goggles and a white coat/);
});

test("revised scene references keep earlier versions and select the latest", () => {
  const references = [{ scene_number: 6, image_data: "orange jacket" }, { scene_number: 6, image_data: "gray coat" }];
  assert.equal(sceneReference(references, 6).image_data, "gray coat");
  assert.equal(references.length, 2);
});
