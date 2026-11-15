// Editorial decisions are derived from the requested action, never from scene number.
export function directScene(scene, brief = "") {
  const action = `${scene?.title ?? ""} ${scene?.prompt ?? ""} ${scene?.image_prompt ?? ""}`.toLocaleLowerCase("pt-BR");
  const whole = `${brief} ${action}`.toLocaleLowerCase("pt-BR");
  const camera = /(walk\w*|steps?|approach\w*|advance\w*|push\w*\s+forward|camera.{0,30}forward|move\w*\s+forward|andar|caminh\w*|passos?|aproxim\w*|avan[cç]\w*)/i.test(action)
    ? "push_in" : "gentle";
  let effect = null;
  if (/\b(door|porta)\b.*\b(slam|shut|close|bat|fecha|impact)|\b(slam|shut|close|bat|fecha|impact)\b.*\b(door|porta)\b/i.test(action)) effect = "door_slam";
  else if (/\b(lamp|light|bulb|luz|luzes|lâmpada|lampada)\b.*\b(flicker|click|pisca|estala|apaga)|\b(flicker|click|pisca|estala|apaga)\b.*\b(lamp|light|bulb|luz|luzes|lâmpada|lampada)\b/i.test(action)) effect = "lamp_clicks";
  else if (/\b(metal|hinge|dobradiça|rang|creak)\b/i.test(action)) effect = "metal_creak";
  else if (/(walk\w*|steps?|footsteps|andar|caminh\w*|passos?)/i.test(action) ||
           (camera === "push_in" && /(passos?|footsteps)/i.test(brief))) effect = "footsteps";
  else if (/\b(wind|vento|brisa|draft)\b/i.test(action)) effect = "wind";
  const expressive = /(sussurr\w*|whisper\w*)/i.test(whole) ? "whisper" :
    /(ofegant\w*|sem ar|f[ôo]lego|breathless|panting)/i.test(whole) ? "breathless" : null;
  const seconds = Math.max(1, (scene?.duration_frames ?? 360) / 24);
  return { camera, effect, cue: Math.min(seconds - .5, Math.max(.5, effect === "door_slam" ? seconds * .62 : seconds * .45)), expressive };
}
