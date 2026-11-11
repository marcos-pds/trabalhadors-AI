export function parseProductionPlan(raw) {
  const input = String(raw ?? "").trim();
  const fenced = input.match(/```(?:json)?\s*([\s\S]*?)\s*```/i)?.[1];
  const candidates = [input, fenced, input.slice(input.indexOf("{"), input.lastIndexOf("}") + 1)].filter(Boolean);
  let plan;
  for (const candidate of candidates) {
    try { plan = JSON.parse(candidate); break; } catch { /* Try the next JSON boundary. */ }
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
  return references.find((reference) => reference.scene_number === number && reference.image_data);
}

export function allSceneImagesReady(scenes, references) {
  return scenes.length > 0 && scenes.every((scene) => Boolean(sceneReference(references, scene.scene)));
}

export function referenceAnchor(references, number) {
  return references.find((reference) => reference.kind === "character" && reference.image_data && !reference.scene_number) ??
    sceneReference(references, number - 1);
}
