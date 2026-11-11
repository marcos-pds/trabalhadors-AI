import { test } from "node:test";
import { strict as assert } from "node:assert";
import { allSceneImagesReady, parseProductionPlan, referenceAnchor } from "./production.mjs";

const scenes = Array.from({ length: 8 }, (_, index) => ({ scene: index + 1, title: `Cena ${index + 1}`,
  image_prompt: "Caio at the laboratory bench", prompt: "Caio lifts the flask" }));

test("planning requires a visual direction and separate image and video prompts", () => {
  const plan = parseProductionPlan('```json\n' + JSON.stringify({ visual_bible: "Caio wears blue and white", scenes }) + '\n```');
  assert.equal(plan.scenes[0].image_prompt, "Caio at the laboratory bench");
  assert.throws(() => parseProductionPlan(JSON.stringify({ visual_bible: "Same character", scenes: scenes.map(({ image_prompt, ...rest }) => rest) })), /direção visual/);
});

test("video stage waits until every scene has its image", () => {
  const references = scenes.slice(0, 7).map((scene) => ({ scene_number: scene.scene, kind: "setting", image_data: "data:image/png;base64,AA==" }));
  assert.equal(allSceneImagesReady(scenes, references), false);
  references.push({ scene_number: 8, kind: "setting", image_data: "data:image/png;base64,AA==" });
  assert.equal(allSceneImagesReady(scenes, references), true);
});

test("uploaded master anchors each scene; otherwise the prior scene does", () => {
  const prior = { scene_number: 1, kind: "setting", image_data: "prior" };
  const master = { kind: "character", image_data: "master" };
  assert.equal(referenceAnchor([prior], 2), prior);
  assert.equal(referenceAnchor([prior, master], 2), master);
});
