export function parseProductionPlan(raw) {
  const input = String(raw ?? "").trim();
  const fenced = input.match(/```(?:json)?\s*([\s\S]*?)\s*```/i)?.[1];
  const sections = input.split(/(?:^|\n)##\s+[^\n]+\n/).map((section) => section.slice(section.indexOf("{"), section.lastIndexOf("}") + 1));
  const candidates = [input, fenced, ...sections].filter(Boolean);
  let plan;
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (parsed && typeof parsed === "object" && Array.isArray(parsed.scenes) && parsed.scenes.length === 8) plan = parsed;
    } catch { /* Worker messages may contain several titled JSON proposals. */ }
  }
  if (!plan || typeof plan !== "object" || Array.isArray(plan) ||
      typeof plan.visual_bible !== "string" || !plan.visual_bible.trim() || plan.visual_bible.length > 2000 ||
      !Array.isArray(plan.scenes) || plan.scenes.length !== 8 ||
      plan.scenes.some((scene, index) => !scene || scene.scene !== index + 1 ||
        typeof scene.title !== "string" || !scene.title.trim() || scene.title.length > 120 ||
        typeof scene.image_prompt !== "string" || !scene.image_prompt.trim() || scene.image_prompt.length > 1024 ||
        typeof scene.prompt !== "string" || !scene.prompt.trim() || scene.prompt.length > 1024 ||
        (scene.dialogue && (typeof scene.dialogue !== "string" || scene.dialogue.length > 300)))) {
    throw new Error("O roteiro precisa trazer oito cenas com direção visual e ação para o vídeo.");
  }
  return plan;
}

export function sceneReference(references, number) {
  return references.findLast((reference) => reference.scene_number === number && reference.image_data);
}

export function allSceneImagesReady(scenes, references) {
  return scenes.length > 0 && scenes.every((scene) => Boolean(sceneReference(references, scene.scene)));
}

export function meanPixelDifference(left, right) {
  if (!left || !right || left.length !== right.length || left.length % 4) throw new Error("Quadros inválidos para comparação.");
  let total = 0;
  for (let index = 0; index < left.length; index += 4) {
    total += Math.abs(left[index] - right[index]) + Math.abs(left[index + 1] - right[index + 1]) + Math.abs(left[index + 2] - right[index + 2]);
  }
  return total / (left.length / 4 * 3);
}

export function sceneTimingForSpeech(dialogue) {
  return { frames: 49, fps: String(dialogue ?? "").trim() ? 12 : 16 };
}

export function referenceAnchor(references) {
  return references.find((reference) => reference.kind === "character" && reference.image_data && !reference.scene_number);
}

export function characterMasterPrompt(visualBible, brief = "") {
  const identity = String(visualBible ?? "").split(/\b(?:cenários|cenarios|scenes|locations|paleta|palette)\s*:/i)[0].trim();
  const source = `${brief} ${identity}`;
  const youngWithoutBeard = /\b(young|boy|child|jovem|menino|criança)\b/i.test(source) &&
    (!/\b(beard|moustache|barba|bigode)\b/i.test(source) ||
      /\b(no|sem|without)\s+(beard|moustache|barba|bigode)\b/i.test(source));
  return ["Create ONE clean full-body 2D animated character portrait, front three-quarter view, on a plain light background.",
    "Exactly one person in one image. Single panel only. No collage, storyboard, contact sheet, multiple poses, insets or scene examples.",
    youngWithoutBeard ? "Young clean-shaven face, no beard or moustache." : "Honor the character's age and facial hair.",
    identity,
    "Crisp flat colors, clean outlines, consistent proportions. No laboratory or other location, no text or captions."].join(" ").slice(0, 4096);
}

export function sceneImageEditPrompt(scene, correction = "") {
  const direction = String(scene?.image_prompt || scene?.prompt || "").trim();
  const action = String(scene?.prompt || "").trim();
  return [
    "Transform <image1> into one full-body action frame in the requested location.",
    "The exact same protagonist from <image1> performs the action below. Preserve exactly the face, hair, skin, accessories, clothes and flat 2D drawing style.",
    direction,
    action && action !== direction ? `Show the key visible pose from this action: ${action}` : "",
    correction ? `Requested correction: ${String(correction).trim()}` : "",
    "Show the complete scene background, with no inset panels or repeated character. Vertical 9:16, no text.",
  ].filter(Boolean).join(" ").slice(0, 4096);
}
