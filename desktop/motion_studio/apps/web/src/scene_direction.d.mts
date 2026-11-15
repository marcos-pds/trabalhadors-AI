export type SceneDirection = {
  camera: "gentle" | "push_in";
  effect: "footsteps" | "lamp_clicks" | "door_slam" | "wind" | "metal_creak" | null;
  cue: number;
  expressive: "whisper" | "breathless" | null;
};
export function directScene(scene?: { title?: string; prompt?: string; image_prompt?: string; duration_frames?: number }, brief?: string): SceneDirection;
