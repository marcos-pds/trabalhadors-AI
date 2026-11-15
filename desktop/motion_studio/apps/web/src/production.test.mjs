import { test } from "node:test";
import { strict as assert } from "node:assert";
import { allSceneImagesReady, characterMasterPrompt, meanPixelDifference, parseDirectedScript, parseProductionPlan, referenceAnchor, referenceKeyframeCount, sceneImageEditPrompt, sceneReference, sceneTimingForSpeech, timeScenesFromScript, voiceDirectionFromScript } from "./production.mjs";

test("workers choose different numbers of full-scene keyframes", () => {
  assert.equal(referenceKeyframeCount(8), 2);
  assert.equal(referenceKeyframeCount(15), 3);
  assert.equal(referenceKeyframeCount(20), 4);
  assert.equal(referenceKeyframeCount(30), 5);
});

const scenes = Array.from({ length: 8 }, (_, index) => ({ scene: index + 1, title: `Cena ${index + 1}`,
  image_prompt: "Caio at the laboratory bench", prompt: "Caio lifts the flask" }));

test("scene lengths follow the script and exact requested total", () => {
  const scripted = scenes.map((scene, index) => ({ ...scene, duration_frames: index === 0 ? 240 : 96,
    dialogue: index === 1 ? 'Esta frase precisa de mais tempo para ser narrada com clareza e emoção.' : '' }));
  const natural = timeScenesFromScript(scripted, 'Uma história');
  assert.equal(natural[0].duration_frames, 240);
  assert.ok(natural[1].duration_frames > 96);
  const exact = timeScenesFromScript(scripted, 'Vídeo de 2 minutos');
  assert.equal(exact.reduce((sum, scene) => sum + scene.duration_frames, 0), 120 * 24);
  assert.ok(exact[0].duration_frames > exact[2].duration_frames);
  assert.throws(() => timeScenesFromScript(scripted, 'Duração: 8 segundos'), /não comporta/);
  assert.equal(timeScenesFromScript(scripted, 'O episódio deve durar 2 minutos').reduce((sum, scene) => sum + scene.duration_frames, 0), 2880);
});

test("explicit emotion in a scene guides its narration", () => {
  assert.equal(voiceDirectionFromScript({ ...scenes[0], dialogue: 'Ela sussurra: alguém está aqui.', voice_direction: 'neutral' }), 'whisper');
  assert.equal(voiceDirectionFromScript({ ...scenes[0], prompt: 'Narrador fala com medo.', voice_direction: 'neutral' }), 'fear');
});

test("five timed scenes preserve speakers, exact speech and silent beats", () => {
  const script = `### CENA 1 — O INÍCIO (0–10s)
[EMOÇÃO: Calma.] "Era quase meia-noite." [PAUSA: 0,8 segundo.]
### CENA 2 — O PRIMEIRO SINAL (10–20s)
[EMOÇÃO: Desconfiança.] "Ele morava sozinho."
[EMOÇÃO: Voz feminina suave, distante.] "Lucas... abre a porta. Sou eu, sua mãe."
### CENA 3 — O MEDO (20–31s)
[EMOÇÃO: Choque contido.] "Lucas congelou."
[PAUSA: 1 segundo.] [EMOÇÃO: Voz feminina insistente.] "Filho... por favor."
### CENA 4 — A REVELAÇÃO (31–46s)
[EMOÇÃO: Ansiedade intensa.] "Lucas se aproximou."
[PAUSA: 0,6 segundo.] [EMOÇÃO: Voz masculina em sussurro.] "Não abre!"
### CENA 5 — O FINAL (46–60s)
[EMOÇÃO: Terror silencioso.] "A gravação dizia apenas..."
[EMOÇÃO: Voz feminina urgente.] "Lucas... eu também estou ouvindo essa voz."
[SILÊNCIO FINAL: 1 segundo.]`;
  const parsed = parseDirectedScript(script);
  assert.deepEqual(parsed.map((scene) => scene.duration_frames), [240, 240, 264, 360, 336]);
  assert.equal(parsed[1].voice_beats[1].speaker, 'Mãe');
  assert.equal(parsed[3].voice_beats.at(-1).speaker, 'Lucas');
  assert.equal(parsed[0].voice_beats[1].pause_ms, 800);
  assert.equal(parsed[4].voice_beats.at(-1).pause_ms, 1000);
  assert.equal(parsed.map((scene) => scene.duration_frames).reduce((a, b) => a + b), 1440);
  assert.ok(!parsed.some((scene) => /EMOÇÃO|PAUSA/.test(scene.dialogue)));
});

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

test("planning accepts a scene-specific image count and long timing", () => {
  const longScenes = scenes.map((scene, index) => ({ ...scene, duration_frames: 360, pose_count: index % 2 ? 10 : 6 }));
  assert.equal(parseProductionPlan(JSON.stringify({ visual_bible: "Same corridor", scenes: longScenes })).scenes[1].pose_count, 10);
  assert.throws(() => parseProductionPlan(JSON.stringify({ visual_bible: "Same corridor", scenes: longScenes.map((scene) => ({ ...scene, pose_count: 31 })) })), /oito cenas/);
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

test("each scene requires the same character master rather than a prior scene", () => {
  const prior = { scene_number: 1, kind: "setting", image_data: "prior" };
  const master = { kind: "character", image_data: "master" };
  assert.equal(referenceAnchor([prior]), undefined);
  assert.equal(referenceAnchor([prior, master]), master);
});

test("generated character master anchors later scenes and carries the visual bible", () => {
  const master = { kind: "character", image_data: "master", source: "generated_image" };
  const prior = { scene_number: 1, kind: "setting", image_data: "prior" };
  assert.equal(referenceAnchor([prior, master]), master);
  assert.match(characterMasterPrompt("Caio wears blue goggles and a white coat"), /blue goggles and a white coat/);
  assert.match(characterMasterPrompt("Caio wears blue goggles", "A young scientist"), /Young clean-shaven face/);
  assert.match(characterMasterPrompt("Caio wears blue goggles", "Um jovem cientista"), /no beard or moustache/);
  assert.match(characterMasterPrompt("Caio wears blue goggles", "Um jovem cientista sem barba"), /no beard or moustache/);
  const concise = characterMasterPrompt("Caio has blue goggles. Cenários: laboratory, corridor, rainy street", "Conte oito cenas em cenários diferentes");
  assert.doesNotMatch(concise, /corridor|rainy street|Conte oito cenas/);
  assert.match(concise, /No collage, storyboard, contact sheet/);
});

test("scene image edit follows the isolated one-master method and keeps the action", () => {
  const prompt = sceneImageEditPrompt({ scene: 2, title: "Fuga", image_prompt: "Caio runs through a hospital corridor", prompt: "Camera follows" }, "show both feet off the ground");
  assert.match(prompt, /exact same protagonist from <image1>/);
  assert.doesNotMatch(prompt, /<image2>|scene canvas/);
  assert.match(prompt, /Caio runs through a hospital corridor/);
  assert.match(prompt, /show both feet off the ground/);
  assert.match(prompt, /flat 2D drawing style/);
  assert.doesNotMatch(prompt, /visual_bible|Locations:/);
});

test("revised scene references keep earlier versions and select the latest", () => {
  const references = [{ scene_number: 6, image_data: "orange jacket" }, { scene_number: 6, image_data: "gray coat" }];
  assert.equal(sceneReference(references, 6).image_data, "gray coat");
  assert.equal(references.length, 2);
});
