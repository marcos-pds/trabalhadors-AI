import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type RefObject } from "react";

import { addContinuousNarrationClip, addSceneCaptionClip, addSceneSpeechClip, addTextClip, addWanSpeechClip, addWanVideoClip, compactSceneSequence, compositionEndFrame, formatTimecode, makeId, restoreClipVersion, standaloneSpeechPreviewUrl, updateClipReview, updateSceneCaptionClip, wanRunMatchesProject, wanVideoPreviewUrl } from "./timeline.mjs";
import { allSceneImagesReady, characterMasterPrompt, meanPixelDifference, parseDirectedScript, parseProductionPlan, referenceAnchor, referenceKeyframeCount, sceneImageEditPrompt, sceneTimingForSpeech, timeScenesFromScript, voiceDirectionFromScript, sceneReference as findSceneReference } from "./production.mjs";
import { directScene } from "./scene_direction.mjs";

type Clip = {
  id: string;
  kind: "video" | "image" | "audio" | "text";
  name: string;
  start_frame: number;
  duration_frames: number;
  text?: string | null;
  style: Record<string, any>;
};
type Track = { id: string; name: string; kind: Clip["kind"]; clips: Clip[] };
type VisualReference = { id: string; kind: "character" | "setting"; name: string; prompt: string; image_data?: string; source: "generated_brief" | "generated_image" | "upload"; scene_number?: number };
type VoiceProfile = string;
type VisualQualityReview = { scene: number; reference_id: string; status: "pass" | "needs_revision"; findings: string[]; reviewer: string };
type Timeline = { schema_version: 1; fps: number; width: number; height: number; tracks: Track[]; storyboard?: { theme: string; visual_bible?: string; scenes: PlannedScene[]; references?: VisualReference[]; quality_reviews?: VisualQualityReview[]; voice_profiles?: Record<string, VoiceProfile>; captions_enabled?: boolean; episode_status?: "draft" | "approved"; publication?: { cover_text: string; caption: string; hashtags: string } } };
type Project = { id: string; title: string; summary: string; timeline: Timeline; updated_at: string };
type Capabilities = { comfyui: { installed: boolean; status: string }; wan21_t2v_13b: { installed: boolean }; ffmpeg: { installed: boolean }; rendering: { status: string }; transcription: { status: string } };
type MotionRun = { id: string; project_id?: string; state: string; error: string | null; jobs: Array<{ id: string; adapter?: string; state: string; frames?: number | null; fps?: number | null; scene_number?: number | null; replace_clip_id?: string | null; effect_preset?: string | null; effect_cue?: number | null; camera_motion?: string | null; speech_artifact_id?: string | null; speech_text?: string | null; speaker?: string | null; voice_profile?: string | null; error: string | null; artifact: { id: string; path: string; bytes: number } | null }> };
type MotionTools = { comfy_endpoint: string | null; comfy_root: string | null; allow_remote: boolean; executables: Record<string, string> | null; comfy_status?: string };
type VoiceBeat = { speaker: string; text: string; direction: "neutral" | "whisper" | "breathless" | "fear" | "sad" | "excited" | "angry" | "calm" | "suspense"; pause_ms: number };
type PlannedScene = { scene: number; title: string; prompt: string; image_prompt?: string; hook?: string; cliffhanger?: string; speaker?: string; dialogue?: string; voice_direction?: VoiceBeat['direction']; voice_beats?: VoiceBeat[]; duration_frames?: number; pose_count?: number };

const initialTimeline = (): Timeline => ({
  schema_version: 1,
  fps: 24,
  width: 1280,
  height: 720,
  tracks: [
    { id: "video_main", name: "VÍDEO 01", kind: "video", clips: [] },
    { id: "overlay", name: "IMAGEM / OVERLAY", kind: "image", clips: [] },
    { id: "titles", name: "TÍTULOS", kind: "text", clips: [] },
    { id: "sound", name: "ÁUDIO", kind: "audio", clips: [] },
  ],
});

function request<T>(url: string, init?: RequestInit): Promise<T> {
  const embedded = new URLSearchParams(window.location.search).get("embedded") === "central";
  const endpoint = embedded ? `/api/motion-studio${url}` : url;
  const headers = {
    "Content-Type": "application/json",
    ...init?.headers,
    ...(embedded ? { "X-Central-Request": "1" } : {}),
  };
  return fetch(endpoint, { ...init, headers }).then(async (response) => {
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
    return response.json() as Promise<T>;
  });
}
function centralRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = { "Content-Type": "application/json", ...init?.headers, "X-Central-Request": "1" };
  return fetch(url, { ...init, headers }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail ?? `HTTP ${response.status}`);
    }
    return response.json() as Promise<T>;
  });
}

function clipAtFrame(timeline: Timeline, frame: number, kind: Clip["kind"]): Clip | undefined {
  return timeline.tracks.filter((track) => track.kind === kind).flatMap((track) => track.clips)
    .find((clip) => frame >= clip.start_frame && frame < clip.start_frame + clip.duration_frames);
}

function clock(seconds: number): string {
  return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
}

async function imagePixels(source: string): Promise<Uint8ClampedArray> {
  const image = new Image();
  image.src = source;
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = 64; canvas.height = 64;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Não foi possível conferir os quadros da história.");
  context.drawImage(image, 0, 0, 64, 64);
  return context.getImageData(0, 0, 64, 64).data;
}

function Preview({
  timeline, frame, videoClip, videoRef, onVideoTime, onVideoEnded, onVideoReady,
}: {
  timeline: Timeline;
  frame: number;
  videoClip?: Clip;
  videoRef: RefObject<HTMLVideoElement | null>;
  onVideoTime: (seconds: number) => void;
  onVideoEnded: () => void;
  onVideoReady: () => void;
}) {
  const textClip = clipAtFrame(timeline, frame, "text");
  const words = textClip?.text?.split(" ") ?? [];
  const src = videoClip && wanVideoPreviewUrl(videoClip.style.motion_run_id, videoClip.style.motion_artifact_id);
  return (
    <div className={"preview-frame" + (src ? " preview-has-video" : "")}>
      <div className="preview-grid" />
      {src && videoClip && <video
        key={videoClip.id} ref={videoRef} className="preview-video" src={src}
        playsInline preload="metadata" aria-label={"Vídeo " + videoClip.name}
        onTimeUpdate={(event) => onVideoTime(event.currentTarget.currentTime)}
        onLoadedMetadata={onVideoReady} onEnded={onVideoEnded}
      />}
      {!src && !textClip && <div className="preview-empty"><span className="play-glyph">▶</span><strong>PREVIEW DA COMPOSIÇÃO</strong><small>Gere uma cena ou adicione um título à timeline.</small></div>}
      {textClip && <div className={textClip.style.caption ? "preview-title preview-caption" : "preview-title"} style={{ color: String(textClip.style.color ?? "#f8fafc") }}>
        {words.map((word, index) => <span key={word + "-" + index} style={{ color: textClip.style.word_colors?.[index] ?? textClip.style.color }}>{word} </span>)}
      </div>}
      <span className="preview-time">{formatTimecode(frame, timeline.fps)}</span>
    </div>
  );
}

export default function App() {
  const theme = new URLSearchParams(window.location.search).get("theme") === "light" ? "light" : "dark";
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [selectedClip, setSelectedClip] = useState<string | null>(null);
  const [titleDraft] = useState("O FUTURO COMEÇA AGORA");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(true);
  const [, setWanConfigStatus] = useState("Iniciando automaticamente os motores locais…");
  const [scenePrompt, setScenePrompt] = useState("Vertical cinematic 3D horror scene, a small geometric glass figure crossing a dim abandoned hallway, cold blue moonlight, deep shadows, slow camera push, unsettling atmosphere, polished motion design, no text.");
  const [sceneSpeechText, setSceneSpeechText] = useState("");
  const [sceneSpeaker, setSceneSpeaker] = useState("Lara");
  const [sceneSpeechBusy, setSceneSpeechBusy] = useState(false);
  const [voiceReferenceText, setVoiceReferenceText] = useState("");
  const [newVoiceName, setNewVoiceName] = useState("");
  const [voiceReferenceBusy, setVoiceReferenceBusy] = useState(false);
  const [episodeNumber] = useState(1);
  const [sceneNumber] = useState(1);
  const [videoModel] = useState<"wan" | "ltxv">("ltxv");
  const [characterReferenceId] = useState("");
  const [wanRun, setWanRun] = useState<MotionRun | null>(null);
  const [wanBusy, setWanBusy] = useState(false);
  const [sceneImageBusy, setSceneImageBusy] = useState(false);
  const [, setEpisodeRun] = useState(false);
  const [voiceCatalog, setVoiceCatalog] = useState<{ ready: boolean; engine?: string; voices: { id: string; name: string }[] }>({ ready: false, voices: [] });
  const [chatPrompt, setChatPrompt] = useState("");
  const [chatMessages, setChatMessages] = useState<Array<{ id: string; role: "user" | "assistant"; text: string }>>([]);
  const [promptImage, setPromptImage] = useState<{ name: string; image_data: string } | null>(null);
  const promptImageInputRef = useRef<HTMLInputElement | null>(null);
  const [autoProgress, setAutoProgress] = useState("");
  const [autoBusy, setAutoBusy] = useState(false);
  const [finalExport, setFinalExport] = useState<{ id: string | null; url: string | null; duration?: number } | null>(null);
  const [episodePlan, setEpisodePlan] = useState<PlannedScene[]>([]);
  const [playheadFrame, setPlayheadFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [importNotice, setImportNotice] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [effectPreset, setEffectPreset] = useState("wind");
  const [effectCue, setEffectCue] = useState(8);
  const [effectBusy, setEffectBusy] = useState(false);
  const [visualReviewBusy, setVisualReviewBusy] = useState(false);
  const [cameraBusy, setCameraBusy] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const chatFeedRef = useRef<HTMLDivElement | null>(null);
  const pendingPlaybackClipRef = useRef<string | null>(null);
  const embedded = new URLSearchParams(window.location.search).get("embedded") === "central";

  function addChatMessage(role: "user" | "assistant", text: string) {
    setChatMessages((messages) => [...messages, { id: makeId("chat"), role, text }]);
  }

  function uploadPromptImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!/image\/(png|jpeg|webp)/.test(file.type) || file.size > 6 * 1024 * 1024) {
      setError("Envie PNG, JPG ou WebP de até 6 MB."); return;
    }
    const reader = new FileReader();
    reader.onload = () => setPromptImage({ name: file.name, image_data: String(reader.result) });
    reader.onerror = () => setError("Não foi possível ler a imagem enviada.");
    reader.readAsDataURL(file);
  }

  const load = useCallback(async () => {
    try {
      const [list, system] = await Promise.all([
        request<Project[]>("/api/projects"),
        request<Capabilities>("/api/capabilities"),
      ]);
      setProjects(list);
      setCapabilities(system);
      if (!project && list.length) setProject(list[0]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível conectar à API local.");
    }
  }, [project]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!embedded || !project?.id) return;
    setFinalExport(null);
    void centralRequest<{ id: string | null; url: string | null }>(`/api/motion/projects/${project.id}/export`)
      .then(setFinalExport).catch(() => setFinalExport(null));
  }, [embedded, project?.id]);

  useEffect(() => {
    if (!embedded) return;
    void centralRequest<typeof voiceCatalog>("/api/motion/voicestudio/voices")
      .then((catalog) => setVoiceCatalog({ ready: catalog.ready, voices: catalog.voices.map((voice) => ({ ...voice, name: `VoiceStudio · ${voice.name}` })) }))
      .catch(() => setVoiceCatalog({ ready: false, voices: [] }));
    let active = true;
    void centralRequest<MotionTools>("/api/motion/tools")
      .then((config) => {
        if (!active) return;
        const configured = Boolean(config.comfy_endpoint && config.comfy_root);
        setCapabilities((current) => current ? {
          ...current,
          comfyui: { ...current.comfyui, status: config.comfy_status === "running" ? "available" : "unavailable" },
        } : current);
        setWanConfigStatus(configured && config.comfy_status === "running"
          ? "ComfyUI/Wan iniciado automaticamente e pronto."
          : "Motores locais iniciados automaticamente.");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setCapabilities((current) => current ? {
          ...current,
          comfyui: { ...current.comfyui, status: "unavailable" },
        } : current);
        setWanConfigStatus(reason instanceof Error ? reason.message : "Não foi possível carregar a configuração local.");
      });
    return () => { active = false; };
  }, [embedded]);

  const persist = useCallback(async (next: Project) => {
    setProject(next);
    setFinalExport(null);
    setSaved(false);
    try {
      const result = await request<Project>(`/api/projects/${next.id}`, {
        method: "PUT",
        body: JSON.stringify({ title: next.title, summary: next.summary, timeline: next.timeline }),
      });
      setProject(result);
      setProjects((current) => current.map((item) => item.id === result.id ? result : item));
      setSaved(true);
      setError("");
      if (embedded) {
        void centralRequest<{ id: string | null; url: string | null }>(`/api/motion/projects/${result.id}/export`)
          .then(setFinalExport).catch(() => setFinalExport(null));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao salvar projeto.");
    }
  }, [embedded]);

  const selected = useMemo(
    () => project?.timeline.tracks.flatMap((track) => track.clips).find((clip) => clip.id === selectedClip),
    [project, selectedClip],
  );
  const selectedScene = selected?.kind === "video" ? project?.timeline.storyboard?.scenes.find((scene) => scene.scene === selected.style.scene_number) : undefined;
  const selectedReference = selectedScene ? findSceneReference(project?.timeline.storyboard?.references ?? [], selectedScene.scene) : undefined;
  const selectedQualityReview = project?.timeline.storyboard?.quality_reviews?.find((review) =>
    review.scene === selectedScene?.scene && review.reference_id === selectedReference?.id);
  const fps = project?.timeline.fps ?? 24;
  const projectLength = project ? compositionEndFrame(project.timeline) : 0;
  const videoClips = project?.timeline.tracks.filter((track) => track.kind === "video").flatMap((track) => track.clips) ?? [];
  const visualReferences = project?.timeline.storyboard?.references ?? [];
  const sceneImages = episodePlan.map((scene) => findSceneReference(visualReferences, scene.scene)).filter((reference): reference is VisualReference => Boolean(reference));
  const imageStageReady = allSceneImagesReady(episodePlan, visualReferences);
  const characterReferences = visualReferences.filter((reference) => reference.kind === "character" && reference.image_data);
  const characterReference = characterReferences.find((reference) => reference.id === characterReferenceId) ?? characterReferences[0];
  const plannedScenesComplete = !episodePlan.length || episodePlan.every((scene) => videoClips.some((clip) => clip.style.scene_number === scene.scene));
  const hasContinuousNarration = project?.timeline.tracks.some((track) => track.kind === "audio" &&
    track.clips.some((clip) => clip.style.continuous_narration)) ?? false;

  useEffect(() => {
    if (chatFeedRef.current) chatFeedRef.current.scrollTop = chatFeedRef.current.scrollHeight;
  }, [chatMessages, autoProgress, sceneImages.length]);

  const episodeApproved = project?.timeline.storyboard?.episode_status === "approved";
  const finalArtifact = wanRun?.state === "completed" && episodeApproved ? wanRun.jobs.find((job) => job.id === "assemble" && job.artifact)?.artifact : null;
  const activeVideoClip = project ? (clipAtFrame(project.timeline, playheadFrame, "video") ??
    (selected?.kind === "video" ? selected : undefined)) : undefined;
  const activeAudioClip = project && activeVideoClip ? project.timeline.tracks
    .filter((track) => track.kind === "audio").flatMap((track) => track.clips)
    .find((clip) => clip.style.source_video_clip_id === activeVideoClip.id || clip.style.continuous_narration) : undefined;
  const activeAudioUrl = activeAudioClip ? (activeAudioClip.style.motion_speech_id
    ? standaloneSpeechPreviewUrl(activeAudioClip.style.motion_speech_id)
    : wanVideoPreviewUrl(activeAudioClip.style.motion_run_id, activeAudioClip.style.motion_artifact_id)) : null;

  useEffect(() => {
    setReviewComment(selected?.kind === "video" ? String(selected.style.review_comment ?? "") : "");
    if (selected?.kind === "video") {
      const direction = directScene(project?.timeline.storyboard?.scenes.find((scene) => scene.scene === selected.style.scene_number), project?.summary);
      setEffectPreset(String(selected.style.effect_preset ?? direction.effect ?? "wind"));
      setEffectCue(Number(selected.style.effect_cue ?? direction.cue));
    }
  }, [selected?.id, selected?.kind, selected?.style.review_comment]);

  useEffect(() => {
    if (selected?.kind !== "video" || !project) return;
    const speech = project.timeline.tracks.filter((track) => track.kind === "audio")
      .flatMap((track) => track.clips).find((clip) => clip.style.source_video_clip_id === selected.id);
    const planned = project.timeline.storyboard?.scenes.find((scene) => scene.scene === selected.style.scene_number);
    setSceneSpeechText(String(speech?.style.speech_text ?? planned?.dialogue ?? ""));
    setSceneSpeaker(String(speech?.style.speaker ?? planned?.speaker ?? "Narradora"));
  }, [selected?.id, project?.id]);

  useEffect(() => {
    const storyboard = project?.timeline.storyboard;
    if (!storyboard) return;
    setEpisodePlan(storyboard.scenes ?? []);
  }, [project?.id]);

  useEffect(() => {
    videoRef.current?.pause();
    audioRef.current?.pause();
    setPlaying(false);
    setPlayheadFrame(0);
    setSelectedClip(null);
  }, [project?.id]);

  // A saved scene remains available after a refresh; imports are deduplicated by run and artifact ID.
  const syncCompletedVideos = useCallback(async (runs: MotionRun[], targetProjectId: string) => {
    const videos = [...runs].reverse()
      .filter((run) => wanRunMatchesProject(run.project_id, targetProjectId))
      .flatMap((run) => run.jobs.filter((job) =>
        (job.adapter === "comfyui_wan" || job.adapter === "photo_sequence") && job.state === "completed" && job.artifact &&
        Number.isInteger(job.frames) && Number.isInteger(job.fps),
      ).map((job) => ({
        runId: run.id, artifactId: job.artifact!.id,
        name: "Cena " + String(job.scene_number ?? job.id.replace("scene_", "")).padStart(2, "0"),
        frames: job.frames!, fps: job.fps!,
        sceneNumber: job.scene_number ?? (Number(job.id.replace("scene_", "")) || undefined),
        replaceClipId: job.replace_clip_id ?? undefined,
        speechArtifactId: job.speech_artifact_id ?? undefined,
        speechText: job.speech_text ?? undefined,
        speaker: job.speaker ?? undefined,
        voiceProfile: job.voice_profile ?? undefined,
        effectPreset: job.effect_preset ?? undefined,
        effectCue: job.effect_cue ?? undefined,
        cameraMotion: job.camera_motion ?? undefined,
      })));
    if (!videos.length) return;
    const fresh = await request<Project>("/api/projects/" + targetProjectId);
    let timeline = fresh.timeline;
    for (const video of videos) {
      const planned = timeline.storyboard?.scenes.find((scene) => scene.scene === video.sceneNumber);
      timeline = addWanVideoClip(timeline, { ...video, name: planned?.title || video.name, plannedPrompt: planned?.prompt, plannedTitle: planned?.title });
      if (video.speechArtifactId) timeline = addWanSpeechClip(timeline, {
        runId: video.runId, artifactId: video.speechArtifactId, videoArtifactId: video.artifactId,
        speaker: video.speaker ?? "Personagem", text: video.speechText ?? "",
        voiceProfile: video.voiceProfile ?? "", replaceClipId: video.replaceClipId,
      });
      if (timeline.storyboard?.captions_enabled !== false && !/sem legendas/i.test(timeline.storyboard?.theme ?? "") && (video.speechText || planned?.dialogue)) timeline = addSceneCaptionClip(timeline, {
        runId: video.runId, videoArtifactId: video.artifactId, text: video.speechText ?? planned?.dialogue ?? "",
      });
    }
    if (timeline === fresh.timeline) return;
    if (timeline.storyboard?.episode_status === "approved") {
      timeline = { ...timeline, storyboard: { ...timeline.storyboard, episode_status: "draft" } };
    }
    const updated = await request<Project>("/api/projects/" + targetProjectId, {
      method: "PUT",
      body: JSON.stringify({ title: fresh.title, summary: fresh.summary, timeline }),
    });
    setFinalExport(null);
    setProjects((current) => current.map((item) => item.id === targetProjectId ? updated : item));
    setProject((current) => current?.id === targetProjectId ? updated : current);
    const last = timeline.tracks.find((track) => track.kind === "video")?.clips.at(-1);
    if (last) {
      videoRef.current?.pause();
      setPlaying(false);
      setSelectedClip(last.id);
      setPlayheadFrame(last.start_frame);
      setImportNotice("Cena adicionada à timeline. Use ▶ para reproduzir.");
    }
  }, []);

  useEffect(() => {
    if (!embedded || !project?.id) return;
    let active = true;
    void centralRequest<MotionRun[]>("/api/motion/runs")
      .then((runs) => {
        if (!active) return;
        const completedEpisode = runs.find((run) => wanRunMatchesProject(run.project_id, project.id) && run.state === "completed" && run.jobs.some((job) => job.id === "assemble" && job.artifact));
        if (completedEpisode) setWanRun(completedEpisode);
        return syncCompletedVideos(runs, project.id);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Não foi possível recuperar as cenas Wan.");
      });
    return () => { active = false; };
  }, [embedded, project?.id, syncCompletedVideos]);

  function seekTo(frame: number) {
    const next = Math.max(0, Math.min(projectLength, Math.floor(frame)));
    pendingPlaybackClipRef.current = null;
    videoRef.current?.pause();
    audioRef.current?.pause();
    setPlaying(false);
    setPlayheadFrame(next);
    if (audioRef.current && activeAudioClip?.style.continuous_narration) audioRef.current.currentTime = next / fps;
    if (!project) return;
    const clip = clipAtFrame(project.timeline, Math.min(next, Math.max(0, projectLength - 1)), "video");
    if (clip) {
      setSelectedClip(clip.id);
      if (clip.id === activeVideoClip?.id && videoRef.current) {
        videoRef.current.currentTime = (next - clip.start_frame) / fps;
        if (audioRef.current) audioRef.current.currentTime = activeAudioClip?.style.continuous_narration ? next / fps : (next - clip.start_frame) / fps;
      }
    }
  }

  async function playActiveClip() {
    const player = videoRef.current;
    if (!player || !activeVideoClip) return;
    player.currentTime = Math.max(0, (playheadFrame - activeVideoClip.start_frame) / fps);
    try {
      await player.play();
      if (audioRef.current) {
        audioRef.current.currentTime = activeAudioClip?.style.continuous_narration
          ? (activeVideoClip.start_frame / fps + player.currentTime) : player.currentTime;
        await audioRef.current.play();
      }
      setPlaying(true);
    } catch {
      setPlaying(false);
      setError("O navegador não conseguiu reproduzir o MP4. Confira a autorização de pasta e o arquivo.");
    }
  }

  async function togglePlayback() {
    const player = videoRef.current;
    if (!player || !activeVideoClip) return;
    if (!player.paused) {
      player.pause();
      audioRef.current?.pause();
      setPlaying(false);
      return;
    }
    try {
      await playActiveClip();
    } catch { setPlaying(false); }
  }

  function handleVideoEnded() {
    if (!project || !activeVideoClip) return;
    if (!activeAudioClip?.style.continuous_narration) audioRef.current?.pause();
    const next = videoClips.find((clip) => clip.start_frame >= activeVideoClip.start_frame + activeVideoClip.duration_frames);
    if (!next) {
      audioRef.current?.pause();
      pendingPlaybackClipRef.current = null;
      setPlaying(false);
      setPlayheadFrame(projectLength);
      return;
    }
    pendingPlaybackClipRef.current = next.id;
    setSelectedClip(next.id);
    setPlayheadFrame(next.start_frame);
  }

  async function createProject() {
    try {
      const created = await request<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ title: "Novo projeto", summary: "" }),
      });
      const seeded = await request<Project>(`/api/projects/${created.id}`, {
        method: "PUT",
        body: JSON.stringify({ title: created.title, summary: "", timeline: initialTimeline() }),
      });
      setProject(seeded);
      setProjects((current) => [seeded, ...current]);
      setSelectedClip(null);
      setChatMessages([]);
      setChatPrompt("");
      setPromptImage(null);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao criar projeto.");
    }
  }

  async function reviewReference(projectId: string, scene: PlannedScene, force = false) {
    const current = await request<Project>(`/api/projects/${projectId}`);
    const reference = findSceneReference(current.timeline.storyboard?.references ?? [], scene.scene);
    if (!reference) throw new Error(`Falta a imagem da cena ${scene.scene}.`);
    const existing = current.timeline.storyboard?.quality_reviews?.find((item) =>
      item.scene === scene.scene && item.reference_id === reference.id);
    if (existing?.status === "pass" && !force) return existing;
    const result = await centralRequest<{ status: "pass" | "needs_revision"; findings: string[]; reviewer: string }>(
      "/api/motion/photo/review", { method: "POST", body: JSON.stringify({ project_id: projectId, scene: scene.scene }) });
    const review: VisualQualityReview = { scene: scene.scene, reference_id: reference.id, ...result };
    const storyboard = current.timeline.storyboard!;
    const updated = await request<Project>(`/api/projects/${projectId}`, { method: "PUT", body: JSON.stringify({
      title: current.title, summary: current.summary, timeline: { ...current.timeline, storyboard: {
        ...storyboard, quality_reviews: [...(storyboard.quality_reviews ?? []).filter((item) => item.scene !== scene.scene), review],
      } },
    }) });
    setProject(updated);
    return review;
  }

  async function correctReference(projectId: string, scene: PlannedScene, findings: string[]) {
    const current = await request<Project>(`/api/projects/${projectId}`);
    const storyboard = current.timeline.storyboard!;
    const reference = findSceneReference(storyboard.references ?? [], scene.scene);
    if (!reference?.image_data || (storyboard.references ?? []).length >= 32) throw new Error("Não há espaço para outra versão da imagem.");
    const correction = findings.join('; ').slice(0, 600);
    setAutoProgress(`Corrigindo somente a imagem da cena ${scene.scene}: ${correction}`);
    const image = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
      method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1", reference_image_data: reference.image_data,
        prompt: `Edit the supplied image while preserving its architecture, camera angle and visual identity. Scene: ${scene.title}. Required visible state: ${scene.image_prompt ?? scene.prompt}. Correct only these verified issues: ${correction}. One coherent vertical 9:16 frame, no text.`.slice(0, 4096) }),
    });
    const revised: VisualReference = { id: makeId("ref"), kind: "setting", scene_number: scene.scene,
      name: `Cena ${scene.scene} · revisão visual`, prompt: correction,
      image_data: image.image_data, source: "generated_image" };
    const updated = await request<Project>(`/api/projects/${projectId}`, { method: "PUT", body: JSON.stringify({
      title: current.title, summary: current.summary, timeline: { ...current.timeline, storyboard: {
        ...storyboard, references: [...(storyboard.references ?? []), revised], episode_status: "draft",
      } },
    }) });
    setProject(updated);
    return revised;
  }

  async function applyAutomaticSceneEffect(projectId: string, scene: PlannedScene, brief: string) {
    const direction = directScene(scene, brief);
    if (!direction.effect) return;
    const current = await request<Project>(`/api/projects/${projectId}`);
    const clip = current.timeline.tracks.find((track) => track.kind === "video")?.clips.find((item) => item.style.scene_number === scene.scene);
    if (!clip || clip.style.effect_preset) return;
    setAutoProgress(`Direção sonora: aplicando ${direction.effect} à cena ${scene.scene}…`);
    const edited = await centralRequest<MotionRun>("/api/motion/photo/effects", { method: "POST", body: JSON.stringify({
      project_id: projectId, clip_id: clip.id, preset: direction.effect, cue_seconds: direction.cue,
    }) });
    await syncCompletedVideos([edited], projectId);
  }

  async function createEpisodeFromChat(ideaOverride?: string, reviewAfterImages = false, resumeProject?: Project) {
    const idea = (ideaOverride ?? chatPrompt).trim();
    const directedScript = parseDirectedScript(idea);
    const longEpisode = /(?:2\s*minutos|120\s*segundos)/i.test(idea);
    const planningBrief = idea;
    if (!idea || autoBusy || !embedded) return;
    addChatMessage("user", idea + (promptImage ? ` · Imagem: ${promptImage.name}` : ""));
    setAutoBusy(true);
    setError("");
    try {
      let scenes: PlannedScene[];
      let planned: Project;
      const sourceProject = resumeProject ?? project;
      if (!promptImage && sourceProject?.summary === idea && sourceProject.timeline.storyboard?.scenes.length) {
        scenes = sourceProject.timeline.storyboard.scenes;
        planned = sourceProject;
        setAutoProgress("Retomando imagens ou cenas pendentes deste projeto…");
      } else {
      setAutoProgress("Trabalhadores criando roteiro, falas e direção visual…");
      addChatMessage("assistant", "Vou montar a história e definir a aparência dos personagens antes de gerar os quadros.");
      const conversation = await centralRequest<{ id: string }>("/api/conversations", { method: "POST", body: JSON.stringify({ title: `Mini episódio · ${idea.slice(0, 60)}` }) });
      const planning = await centralRequest<{ id: string }>("/api/runs", { method: "POST", body: JSON.stringify({ conversation_id: conversation.id, mode: "auto", autonomous: false, prompt: [
        "Planejamento criativo de uma minissérie vertical animada original para Instagram. Resposta exclusivamente em JSON com história e instruções para imagem e vídeo; esta etapa é apenas texto.",
        `Brief narrativo: "${planningBrief.replace(/["\r\n]/g, " ")}"`,
        promptImage ? "O usuário enviou uma imagem mestra. Use sua composição e identidade como âncora visual; não invente detalhes incompatíveis com ela." : "Sem imagem enviada: defina uma identidade visual original, estável e detalhada para os personagens e cenários.",
        `O roteiro tem exatamente ${directedScript?.length ?? 8} cenas consecutivas. Cada ação decorre da anterior. Determine a duração de CADA cena pelo tempo necessário para sua ação e fala, de 1 a 30 segundos. ${directedScript ? `Preserve as cinco cenas e seus intervalos: ${directedScript.map((scene) => `${scene.scene}: ${scene.duration_frames / 24}s`).join(', ')}. Não reescreva as falas do usuário; forneça apenas direção visual e ações.` : 'Se o pedido especificar duração total, distribua o tempo segundo o roteiro.'} Defina duration_frames em quadros a 24 FPS. Escolha pose_count entre 2 e 30. Composição vertical 9:16. Respeite personagens e ambiente. visual_bible descreve a identidade visual. image_prompt representa um quadro estático em inglês; prompt descreve ação progressiva. Mantenha a identidade visual dos personagens. ${directedScript ? 'As falas, pausas e emoções serão preservadas diretamente do roteiro enviado.' : 'Em cada cena, defina voice_direction conforme a emoção: neutral, whisper, breathless, fear, sad, excited, angry, calm ou suspense.'}`,
        "Responda SOMENTE JSON válido: {\"visual_bible\":\"identidade visual e cenário consistentes\",\"scenes\":[{\"scene\":1,\"title\":\"...\",\"image_prompt\":\"quadro estático detalhado em inglês\",\"prompt\":\"movimento progressivo em inglês\",\"speaker\":\"Narrador\",\"dialogue\":\"\",\"voice_direction\":\"suspense\",\"duration_frames\":168,\"pose_count\":8}]}. Não inclua explicações fora do JSON.",
      ].join("\n") }) });
      let status = "queued";
      for (let attempt = 0; attempt < 180 && ["queued", "running", "awaiting_approval"].includes(status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        status = (await centralRequest<{ status: string }>(`/api/runs/${planning.id}`)).status;
      }
      if (status !== "completed") throw new Error(`O planejamento terminou com estado ${status}.`);
      const messages = await centralRequest<Array<{ role: string; content: string }>>(`/api/conversations/${conversation.id}/messages`);
      const raw = messages.filter((message) => message.role === "assistant").at(-1)?.content ?? "";
      const plan = parseProductionPlan(raw);
      if (directedScript && plan.scenes.length !== directedScript.length) throw new Error('O planejamento mudou o número de cenas do roteiro. Gere novamente sem alterar as cinco cenas.');
      const timedScenes = directedScript ? plan.scenes.map((scene, index) => ({ ...scene, ...directedScript[index] })) : timeScenesFromScript(plan.scenes, idea);
      scenes = timedScenes.map((scene) => ({ ...scene,
        voice_direction: voiceDirectionFromScript(scene),
        pose_count: longEpisode ? Math.max(8, scene.pose_count ?? 8) : (scene.pose_count ?? 4) }));
      addChatMessage("assistant", `História pronta: ${scenes.map((scene) => `${scene.scene}. ${scene.title}`).join(" · ")}. Agora vou gerar os cenários e as poses de cada cena.`);
      setAutoProgress("Criando o projeto e preparando a produção…");
      const created = project?.summary === idea && !project.timeline.storyboard?.scenes.length ? project :
        await request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ title: `${(directedScript ? idea.match(/^#\s+(.+)$/m)?.[1] ?? scenes[0].title : scenes[0].title).slice(0, 110)} | Episódio 1`, summary: idea }) });
      const fresh = await request<Project>(`/api/projects/${created.id}`, { method: "PUT", body: JSON.stringify({ title: created.title, summary: idea, timeline: { ...initialTimeline(), fps: 24, width: 720, height: 1280 } }) });
      setProjects((current) => [fresh, ...current.filter((item) => item.id !== fresh.id)]);
      setProject(fresh);
      const studio = await centralRequest<typeof voiceCatalog>("/api/motion/voicestudio/voices");
      const allVoices = studio.ready ? studio.voices.filter((item) => !/^minha voz$/i.test(item.name.trim())) : [];
      const voice = allVoices.find((item) => /padr[aã]o|narrad/i.test(item.name)) ?? allVoices[0];
      if (scenes.some((scene) => scene.dialogue?.trim()) && !voice) throw new Error("Crie ou ative uma voz no VoiceStudio antes de produzir falas.");
      const cast = [...new Set(scenes.flatMap((scene) => scene.voice_beats?.length ? scene.voice_beats.filter((beat) => beat.text).map((beat) => beat.speaker) : scene.dialogue?.trim() ? [scene.speaker?.trim() || "Narradora"] : []))];
      if (cast.length > allVoices.length) throw new Error(`O roteiro tem ${cast.length} personagens com fala. Crie ${cast.length - allVoices.length} voz(es) no VoiceStudio antes de continuar; sua voz pessoal não será escolhida automaticamente.`);
      const alternatives = allVoices.filter((item) => item.id !== voice?.id);
      const voiceProfiles = Object.fromEntries(cast.map((speaker, index) => [speaker,
        (speaker === "Mãe" ? allVoices.find((item) => /lara|narradora|feminin|voz atrás da porta/i.test(item.name) && item.id !== voice?.id)?.id : undefined) ??
        (/^narrad/i.test(speaker) ? allVoices.find((item) => /padr[aã]o|narrad/i.test(item.name))?.id : undefined) ??
        allVoices.find((item) => item.name.toLocaleLowerCase("pt-BR").startsWith(speaker.toLocaleLowerCase("pt-BR")) && /pt-br|brasil/i.test(item.name))?.id ??
        allVoices.find((item) => item.name.toLocaleLowerCase("pt-BR").startsWith(speaker.toLocaleLowerCase("pt-BR")))?.id ??
        (/narrad/i.test(speaker) ? allVoices.find((item) => /narrad/i.test(item.name))?.id : undefined) ??
        (index === 0 ? voice?.id : alternatives[(index - 1) % alternatives.length]?.id) ?? voice?.id ?? ""]));
      if (new Set(Object.values(voiceProfiles)).size !== cast.length) throw new Error("Atribua uma voz diferente do VoiceStudio para cada personagem.");
      const masters: VisualReference[] = promptImage ? [{ id: makeId("ref"), kind: "character", name: promptImage.name,
        prompt: "Imagem mestra enviada no chat.", image_data: promptImage.image_data, source: "upload" }] : [];
      planned = await request<Project>(`/api/projects/${fresh.id}`, { method: "PUT", body: JSON.stringify({ title: fresh.title, summary: idea, timeline: { ...fresh.timeline, storyboard: { theme: idea, visual_bible: plan.visual_bible, scenes, references: masters, voice_profiles: voiceProfiles, captions_enabled: !/sem legendas/i.test(idea), episode_status: "draft" } } }) });
      setPromptImage(null);
      setProject(planned);
      setProjects((current) => current.map((item) => item.id === planned.id ? planned : item));
      setEpisodePlan(scenes);
      }
      const voiceProfiles = planned.timeline.storyboard?.voice_profiles ?? {};
      const cast = [...new Set(scenes.flatMap((scene) => scene.voice_beats?.length ? scene.voice_beats.filter((beat) => beat.text).map((beat) => beat.speaker) : [scene.speaker?.trim() || "Narradora"]))];
      const continuousNarrator = scenes.every((scene) => scene.dialogue?.trim()) &&
        cast.every((speaker) => /^[a-f0-9]{8}$/.test(voiceProfiles[speaker] ?? ""));
      if (!(planned.timeline.storyboard?.references ?? []).some((reference) => reference.kind === "character" && reference.image_data && !reference.scene_number)) {
        setAutoProgress("Criando a imagem mestra do personagem antes dos cenários…");
        const status = await centralRequest<{ qwen_image_2_1: { available: boolean } }>("/api/motion/reference-providers");
        if (!status.qwen_image_2_1.available) throw new Error("O motor local Qwen Image 2.1 não está instalado. A produção aguarda o modelo de imagens.");
        const masterPrompt = longEpisode && /corredor/i.test(idea) ?
          `Create a single dark, indistinct human SHADOW silhouette, isolated on a plain light background. No distinct face, no clothing details, no corridor, no text. Match this visual direction: ${planned.timeline.storyboard?.visual_bible ?? "psychological horror"}.` :
          characterMasterPrompt(planned.timeline.storyboard?.visual_bible, idea);
        const master = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
          method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1", prompt: masterPrompt }),
        });
        const current = await request<Project>(`/api/projects/${planned.id}`);
        const storyboard = current.timeline.storyboard!;
        planned = await request<Project>(`/api/projects/${planned.id}`, { method: "PUT", body: JSON.stringify({
          title: current.title, summary: current.summary, timeline: { ...current.timeline,
            storyboard: { ...storyboard, references: [...(storyboard.references ?? []), { id: makeId("ref"), kind: "character",
              name: "Imagem mestra do personagem", prompt: masterPrompt, image_data: master.image_data, source: "generated_image" }] } },
        }) });
        setProject(planned);
        addChatMessage("assistant", `Imagem mestra salva. Vou usá-la para manter o personagem nas ${scenes.length} cenas.`);
      }
      for (const scene of scenes) {
        let current = await request<Project>(`/api/projects/${planned.id}`);
        if (findSceneReference(current.timeline.storyboard?.references ?? [], scene.scene)) continue;
        setAutoProgress(`Trabalhador de arte e motor de imagem: cena ${scene.scene}/${scenes.length} com imagem mestra…`);
        const references = current.timeline.storyboard?.references ?? [];
        const anchor = referenceAnchor(references);
        if (!anchor?.image_data || anchor.kind !== "character") throw new Error("Falta a imagem mestra do personagem para a cena.");
        const imagePrompt = longEpisode && /corredor/i.test(idea) ?
          `Photorealistic cinematic horror still, vertical 9:16. Same old dark corridor, same lamps and door at the far end. Scene ${scene.scene}: ${scene.image_prompt}. Preserve architecture and camera angle; show the requested change in lighting, door or shadow. No text, no subtitles, no collage.` :
          sceneImageEditPrompt(scene);
        const settingAnchor = longEpisode && /corredor/i.test(idea) && scene.scene > 1 ?
          findSceneReference(references, 1)?.image_data : undefined;
        const image = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
          method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1", prompt: imagePrompt,
            reference_image_data: settingAnchor ?? (longEpisode && /corredor/i.test(idea) ? undefined : anchor.image_data) }),
        });
        const generatedReference: VisualReference = { id: makeId("ref"), kind: "setting",
          name: `Cena ${scene.scene} · ${scene.title}`, prompt: imagePrompt,
          image_data: image.image_data, source: "generated_image", scene_number: scene.scene };
        const storyboard = current.timeline.storyboard!;
        current = await request<Project>(`/api/projects/${planned.id}`, { method: "PUT", body: JSON.stringify({
          title: current.title, summary: current.summary, timeline: { ...current.timeline,
            storyboard: { ...storyboard, references: [...references, generatedReference] } },
        }) });
        setProject(current);
      }
      const ready = await request<Project>(`/api/projects/${planned.id}`);
      if (!allSceneImagesReady(scenes, ready.timeline.storyboard?.references ?? [])) {
        throw new Error(`A montagem aguarda as ${scenes.length} imagens de referência.`);
      }
      for (const scene of scenes) {
        setAutoProgress(`Trabalhador de revisão visual: conferindo cena ${scene.scene}/${scenes.length} com roteiro e imagem mestra…`);
        let review: VisualQualityReview;
        try {
          review = await reviewReference(planned.id, scene);
        } catch (reason) {
          if (!directedScript) throw reason;
          addChatMessage("assistant", `Cena ${scene.scene}: revisor visual indisponível. O quadro permanece pendente de aprovação na timeline.`);
          continue;
        }
        if (review.status === "needs_revision") {
          if (directedScript) {
            addChatMessage("assistant", `Cena ${scene.scene} marcada para revisão visual: ${review.findings.join("; ")}. Vou manter o quadro salvo no teste e deixar a correção disponível na timeline.`);
            continue;
          }
          addChatMessage("assistant", `Cena ${scene.scene}: encontrei ${review.findings.join("; ")}. Vou corrigir esse quadro e conferir novamente.`);
          await correctReference(planned.id, scene, review.findings);
          review = await reviewReference(planned.id, scene);
          if (review.status === "needs_revision") throw new Error(`A cena ${scene.scene} ainda precisa de revisão: ${review.findings.join("; ") || "verifique a imagem"}.`);
        }
      }
      const imageSamples = await Promise.all(scenes.map(async (scene) => imagePixels(findSceneReference(ready.timeline.storyboard?.references ?? [], scene.scene)!.image_data!)));
      for (let index = 1; index < imageSamples.length; index += 1) {
        if (meanPixelDifference(imageSamples[index - 1], imageSamples[index]) < 10) {
          addChatMessage("assistant", `Os quadros ${index} e ${index + 1} têm aparência próxima. Vou manter a continuidade visual e conferir se as poses mostram ações diferentes na revisão.`);
        }
      }
      if (reviewAfterImages || !ideaOverride) {
        setAutoProgress(`Revise os ${scenes.length} quadros. A identidade do personagem precisa de aprovação antes de renderizar os vídeos.`);
        addChatMessage("assistant", "As imagens estão salvas. Confira rosto, cabelo, roupa e cenários. Se estiverem fiéis, use Continuar produção; caso contrário, refaça as referências.");
        return;
      }
      addChatMessage("assistant", `As ${scenes.length} imagens estão prontas. Vou montar cada cena na timeline.`);
      for (const scene of scenes) {
        const current = await request<Project>(`/api/projects/${planned.id}`);
        const existingSceneClip = current.timeline.tracks.find((track) => track.kind === "video")?.clips.find((clip) => clip.style.scene_number === scene.scene);
        const keyframeCount = referenceKeyframeCount(scene.pose_count);
        const needsReferenceUpgrade = (directedScript || longEpisode && /corredor/i.test(idea)) && existingSceneClip?.style.version === 1 &&
          (scene.scene === 1 || keyframeCount > 2);
        if (existingSceneClip && !needsReferenceUpgrade) {
          if (!directedScript || !/sem m[uú]sica ou efeitos/i.test(idea)) await applyAutomaticSceneEffect(planned.id, scene, idea);
          continue;
        }
        const sceneReference = findSceneReference(current.timeline.storyboard?.references ?? [], scene.scene);
        if (!sceneReference?.image_data) throw new Error(`Falta a imagem da cena ${scene.scene}.`);
        const anchor = referenceAnchor(current.timeline.storyboard?.references ?? []);
        if (!anchor?.image_data) throw new Error("Falta a imagem mestra do personagem.");
        if (directedScript || longEpisode && /corredor/i.test(idea)) {
          const previous = scene.scene > 1
            ? findSceneReference(current.timeline.storyboard?.references ?? [], scene.scene - 1)
            : sceneReference;
          const keyframes = [previous?.image_data ?? sceneReference.image_data];
          for (let index = 1; index < keyframeCount - 1; index += 1) {
            setAutoProgress(`Criando quadro de ação ${index + 1}/${keyframeCount} da cena ${scene.scene}/${scenes.length}…`);
            const intermediate = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
              method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1",
                prompt: `Cinematic psychological suspense, vertical 9:16. Preserve the EXACT room architecture, door, lighting and Lucas's face and clothing from the supplied reference. Scene ${scene.scene}: ${scene.title}. Action: ${scene.prompt}. This is intermediate keyframe ${index + 1} of ${keyframeCount}, ${Math.round(index / (keyframeCount - 1) * 100)} percent through the action. Show a small, physically plausible progression. No text, no magenta background, no collage.`,
                reference_image_data: sceneReference.image_data }),
            });
            keyframes.push(intermediate.image_data);
          }
          keyframes.push(sceneReference.image_data);
          setAutoProgress(`Montando cena ${scene.scene}/${scenes.length} com ${keyframes.length} quadros e movimento de câmera…`);
          const generated = await centralRequest<MotionRun>("/api/motion/photo/scenes", { method: "POST", body: JSON.stringify({
            project_id: planned.id, scene: scene.scene, mode: "reference",
            replace_clip_id: existingSceneClip?.id,
            background_data: sceneReference.image_data,
            poses: keyframes,
            frames: scene.duration_frames ?? 360,
            camera_motion: directScene(scene, idea).camera,
          }) });
          await syncCompletedVideos([generated], planned.id);
          if (!directedScript || !/sem m[uú]sica ou efeitos/i.test(idea)) await applyAutomaticSceneEffect(planned.id, scene, idea);
          addChatMessage("assistant", `Cena ${scene.scene}/${scenes.length} pronta na timeline.`);
          continue;
        }
        setAutoProgress(`Criando cenário fixo da cena ${scene.scene}/${scenes.length}…`);
        const background = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
          method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1",
            prompt: `Empty location plate for this story scene, ${longEpisode ? "photorealistic cinematic horror" : "2D illustrated style"}, vertical 9:16. Scene: ${scene.title}. Setting details: ${scene.image_prompt}. Draw ONLY architecture, scenery, lighting and stationary props. Absolutely no person, human figure, silhouette, face, hand, clothing, magenta or pink backdrop, or text. Leave the central foreground clear for a character to be composited later.` }),
        });
        const poseCount = Math.max(longEpisode ? 8 : 2, Math.min(30, scene.pose_count ?? (longEpisode ? 8 : 4)));
        const phases = Array.from({ length: poseCount }, (_, index) => `step ${index + 1} of ${poseCount}, ${Math.round(index / (poseCount - 1) * 100)} percent through the action`);
        const poses: string[] = [];
        for (let index = 0; index < phases.length; index += 1) {
          setAutoProgress(`Gerando pose ${index + 1}/${phases.length} da cena ${scene.scene}/${scenes.length}…`);
          const pose = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
            method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1",
              prompt: longEpisode && /corredor/i.test(idea) ?
                `ONE vague dark human SHADOW silhouette isolated on perfectly uniform solid bright magenta (#FF00FF) background. No corridor, no door, no floor, no text, no face, no clothing details. Preserve the shadow shape of the supplied reference. Scene action: ${scene.prompt}. This is pose ${index + 1} of ${poseCount}, ${phases[index]}. Small progressive movement only.` :
                `ONE full-body character, isolated on perfectly uniform solid bright magenta (#FF00FF) background. No scenery, no floor, no gradients, no text, no collage. Preserve exactly the face, hair, accessories, outfit, colors and art style of the supplied character reference. Character identity: ${current.timeline.storyboard?.visual_bible ?? "Use the supplied reference exactly."}. Scene action: ${scene.prompt}. This is pose ${index + 1} of ${poseCount}, ${phases[index]}. Change only the character pose and any small object held by the character. Keep body proportions and clothing stable.`,
              reference_image_data: anchor.image_data }),
          });
          poses.push(pose.image_data);
        }
        setAutoProgress(`Montando cena ${scene.scene}/${scenes.length} por fotos sobre cenário fixo…`);
        const generated = await centralRequest<MotionRun>("/api/motion/photo/scenes", { method: "POST", body: JSON.stringify({
          project_id: planned.id, scene: scene.scene, background_data: background.image_data,
          poses, frames: scene.duration_frames ?? 96,
        }) });
        setWanRun(generated);
        let latest = generated;
        for (let attempt = 0; attempt < 1200 && ["queued", "running"].includes(latest.state); attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 1500));
          latest = await centralRequest<MotionRun>(`/api/motion/runs/${generated.id}`);
          setWanRun(latest);
        }
        if (latest.state !== "completed") throw new Error(`Cena ${scene.scene}: ${latest.error || latest.state}. As cenas prontas permanecem na timeline.`);
        await syncCompletedVideos([latest], planned.id);
        if (!directedScript || !/sem m[uú]sica ou efeitos/i.test(idea)) await applyAutomaticSceneEffect(planned.id, scene, idea);
        addChatMessage("assistant", `Cena ${scene.scene}/${scenes.length} pronta na timeline.`);
      }
      if (continuousNarrator) {
        const current = await request<Project>(`/api/projects/${planned.id}`);
        const hasNarration = current.timeline.tracks.some((track) => track.kind === "audio" &&
          track.clips.some((clip) => clip.style.continuous_narration));
        if (!hasNarration) {
          setAutoProgress("Gerando uma única narração com a voz brasileira escolhida…");
          const narrated = await centralRequest<{ id: string; speaker: string; text: string; voice_profile: string }>(`/api/motion/projects/${planned.id}/narration`, { method: "POST", body: "{}" });
          const timeline = addContinuousNarrationClip(current.timeline, {
            audioId: narrated.id, speaker: narrated.speaker, text: narrated.text, voiceProfile: narrated.voice_profile,
          });
          const updated = await request<Project>(`/api/projects/${planned.id}`, { method: "PUT", body: JSON.stringify({
            title: current.title, summary: current.summary, timeline,
          }) });
          setProject(updated);
          addChatMessage("assistant", "Narração contínua pronta e visível na trilha de áudio. Vou montar a prévia do episódio.");
        }
      }
      setAutoProgress("Montando o MP4 final com a narração e as cenas…");
      await exportCurrentEpisode(planned.id);
      setAutoProgress("Mini episódio pronto. Assista ao MP4 e revise cada cena e fala na timeline.");
      addChatMessage("assistant", "O episódio está montado. Você pode assistir, revisar cada trecho e baixar o MP4.");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Não foi possível produzir o episódio.";
      setError(message);
      setAutoProgress("Produção interrompida; as cenas concluídas foram preservadas.");
      addChatMessage("assistant", `A produção parou: ${message} O roteiro, as imagens e as cenas concluídas continuam salvos para retomar.`);
    } finally { setAutoBusy(false); }
  }

  async function redoImagesAndContinue(resetGeneratedMaster = false) {
    if (!project || autoBusy || videoClips.length) return;
    const storyboard = project.timeline.storyboard;
    if (!storyboard?.scenes.length) return;
    const updated = await request<Project>(`/api/projects/${project.id}`, { method: "PUT", body: JSON.stringify({
      title: project.title, summary: project.summary, timeline: { ...project.timeline,
        storyboard: { ...storyboard, references: (storyboard.references ?? []).filter((reference) => !reference.scene_number && (!resetGeneratedMaster || reference.source === "upload")) } },
    }) });
    setProject(updated);
    addChatMessage("assistant", resetGeneratedMaster ? `Vou criar uma nova imagem mestra e refazer os ${storyboard.scenes.length} quadros.` : `Vou refazer os ${storyboard.scenes.length} quadros a partir da imagem mestra atual.`);
    await createEpisodeFromChat(updated.summary, true, updated);
  }

  async function regenerateNarration() {
    if (!project || !plannedScenesComplete || autoBusy || !hasContinuousNarration) return;
    setAutoBusy(true);
    setError("");
    setAutoProgress("Refazendo a narração para começar cada fala junto da cena…");
    try {
      const narrated = await centralRequest<{ id: string; speaker: string; text: string; voice_profile: string }>(`/api/motion/projects/${project.id}/narration`, { method: "POST", body: "{}" });
      const current = await request<Project>(`/api/projects/${project.id}`);
      const timeline = addContinuousNarrationClip(current.timeline, {
        audioId: narrated.id, speaker: narrated.speaker, text: narrated.text, voiceProfile: narrated.voice_profile,
      });
      const updated = await request<Project>(`/api/projects/${project.id}`, { method: "PUT", body: JSON.stringify({
        title: current.title, summary: current.summary, timeline,
      }) });
      setProject(updated);
      setFinalExport(null);
      setAutoProgress("Montando o MP4 com a narração alinhada…");
      await exportCurrentEpisode(project.id);
      setAutoProgress("Narração alinhada e MP4 atualizado. Revise o episódio na timeline.");
      addChatMessage("assistant", "Refiz a narração para cada fala começar na cena correspondente e atualizei o MP4.");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Não foi possível refazer a narração.";
      setError(message);
      setAutoProgress("A narração anterior permanece salva.");
      addChatMessage("assistant", `A narração não foi alterada: ${message}`);
    } finally { setAutoBusy(false); }
  }

  async function exportCurrentEpisode(projectId = project?.id) {
    if (!projectId) return;
    const current = await request<Project>(`/api/projects/${projectId}`);
    const timeline = compactSceneSequence(current.timeline);
    if (timeline !== current.timeline) {
      const repaired = await request<Project>(`/api/projects/${projectId}`, { method: "PUT", body: JSON.stringify({
        title: current.title, summary: current.summary, timeline,
      }) });
      setProject(repaired);
      setProjects((items) => items.map((item) => item.id === projectId ? repaired : item));
    }
    const rendered = await centralRequest<{ id: string; url: string; duration: number }>(`/api/motion/projects/${projectId}/export`, { method: "POST", body: "{}" });
    setFinalExport(rendered);
  }

  async function refreshWanRun(runId: string, targetProjectId: string) {
    try {
      const latest = await centralRequest<MotionRun>("/api/motion/runs/" + runId);
      setWanRun(latest);
      if (latest.jobs.some((job) => job.adapter === "comfyui_wan" && job.state === "completed" && job.artifact)) {
        await syncCompletedVideos([latest], targetProjectId);
      }
      if (latest.state === "queued" || latest.state === "running") {
        window.setTimeout(() => void refreshWanRun(runId, targetProjectId), 1500);
      } else {
        setWanBusy(false);
      }
    } catch (reason) {
      setWanBusy(false);
      setError(reason instanceof Error ? reason.message : "Não foi possível consultar a renderização.");
    }
  }

  async function renderWanScene(replaceClipId?: string, promptOverride?: string) {
    const prompt = (promptOverride ?? scenePrompt).trim();
    if (!project || !prompt || wanBusy) return;
    const targetScene = replaceClipId ? Number(selected?.style.scene_number ?? sceneNumber) : sceneNumber;
    const sceneImage = findSceneReference(project.timeline.storyboard?.references ?? [], targetScene)?.image_data ?? characterReference?.image_data;
    if (videoModel === "ltxv" && !sceneImage) {
      setError("Esta cena precisa de uma imagem de referência antes da animação.");
      return;
    }
    setWanBusy(true);
    setEpisodeRun(false);
    setWanRun(null);
    try {
      const run = await centralRequest<MotionRun>(videoModel === "ltxv" ? "/api/motion/ltx/scenes" : "/api/motion/wan/scenes", {
        method: "POST",
        body: JSON.stringify({
          project_id: project.id,
          episode: episodeNumber,
          scene: targetScene,
          prompt,
          ...(videoModel === "ltxv" ? sceneTimingForSpeech(sceneSpeechText) : { frames: 121, fps: 16 }),
          ...(videoModel === "ltxv" ? { image_data: sceneImage, width: 480, height: 832 } : {}),
          replace_clip_id: replaceClipId ?? null,
          ...(sceneSpeechText.trim() && !(/^[a-f0-9]{8}$/.test(project.timeline.storyboard?.voice_profiles?.[sceneSpeaker] ?? "") && /^narrad/i.test(sceneSpeaker)) ? { speech_text: sceneSpeechText.trim(), speaker: sceneSpeaker,
            voice_profile: project.timeline.storyboard?.voice_profiles?.[sceneSpeaker] ?? null } : {}),
        }),
      });
      setWanRun(run);
      setError("");
      void refreshWanRun(run.id, project.id);
    } catch (reason) {
      setWanBusy(false);
      setError(reason instanceof Error ? reason.message : "Não foi possível iniciar a cena Wan.");
    }
  }

  async function generateSelectedSceneSpeech() {
    if (!project || selected?.kind !== "video" || !sceneSpeechText.trim() || sceneSpeechBusy) return;
    const profile = project.timeline.storyboard?.voice_profiles?.[sceneSpeaker];
    if (!profile) { setError(`Escolha uma voz para ${sceneSpeaker}.`); return; }
    setSceneSpeechBusy(true);
    try {
      if (/^[a-f0-9]{8}$/.test(profile) && /^narrad/i.test(sceneSpeaker)) {
        const storyboard = project.timeline.storyboard;
        const scenes = storyboard?.scenes.map((scene) => scene.scene === Number(selected.style.scene_number)
          ? { ...scene, dialogue: sceneSpeechText.trim(), speaker: sceneSpeaker } : scene) ?? [];
        if (storyboard && scenes.every((scene) => scene.dialogue?.trim() && /^narrad/i.test(scene.speaker?.trim() || ""))) {
          const saved = await request<Project>(`/api/projects/${project.id}`, { method: "PUT", body: JSON.stringify({
            title: project.title, summary: project.summary, timeline: { ...project.timeline,
              storyboard: { ...storyboard, scenes, episode_status: "draft" } },
          }) });
          const narrated = await centralRequest<{ id: string; speaker: string; text: string; voice_profile: string }>(`/api/motion/projects/${project.id}/narration`, { method: "POST", body: "{}" });
          const timeline = addContinuousNarrationClip(saved.timeline, { audioId: narrated.id,
            speaker: narrated.speaker, text: narrated.text, voiceProfile: narrated.voice_profile });
          const updated = await request<Project>(`/api/projects/${project.id}`, { method: "PUT", body: JSON.stringify({
            title: saved.title, summary: saved.summary, timeline,
          }) });
          setProject(updated);
          setProjects((current) => current.map((item) => item.id === updated.id ? updated : item));
          setFinalExport(null);
          setImportNotice("Narração contínua atualizada na trilha de áudio. Atualize o MP4 final após a revisão.");
          return;
        }
      }
      const result = await centralRequest<{ id: string; speaker: string; text: string; voice_profile: string }>("/api/motion/scene-speech", {
        method: "POST", body: JSON.stringify({
          run_id: selected.style.motion_run_id, video_artifact_id: selected.style.motion_artifact_id,
          text: sceneSpeechText.trim(), speaker: sceneSpeaker, voice_profile: profile,
        }),
      });
      const timeline = updateSceneCaptionClip(addSceneSpeechClip(project.timeline, {
        audioId: result.id, videoClipId: selected.id, speaker: result.speaker,
        text: result.text, voiceProfile: result.voice_profile,
      }), selected.id, result.text);
      setSaved(false);
      const updated = await request<Project>(`/api/projects/${project.id}`, {
        method: "PUT", body: JSON.stringify({ title: project.title, summary: project.summary, timeline }),
      });
      setProject(updated);
      setProjects((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSaved(true);
      setImportNotice(`Fala de ${result.speaker} adicionada à trilha de áudio da cena.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível gerar a fala da cena.");
    } finally { setSceneSpeechBusy(false); }
  }

  async function importBrazilianVoice(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !newVoiceName.trim() || !voiceReferenceText.trim() || voiceReferenceBusy) return;
    if (file.type !== "audio/wav" && !file.name.toLowerCase().endsWith(".wav")) {
      setError("Envie uma gravação WAV da voz do personagem."); return;
    }
    if (file.size > 5_000_000) { setError("A gravação deve ter até 5 MB."); return; }
    setVoiceReferenceBusy(true);
    try {
      const audio_data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("Não foi possível ler a gravação."));
        reader.readAsDataURL(file);
      });
      const imported = await centralRequest<{ id: string; name: string }>("/api/motion/voicestudio/voices/import", {
        method: "POST", body: JSON.stringify({ name: newVoiceName.trim(),
          transcript: voiceReferenceText.trim(), audio_data }),
      });
      setVoiceCatalog((current) => ({ ready: true, voices: [{ ...imported, name: `VoiceStudio · ${imported.name}` }, ...current.voices] }));
      setImportNotice(`Voz ${imported.name} criada no VoiceStudio. Agora você pode atribuí-la a um personagem.`);
      if (selected?.kind === "video") setSceneVoice(imported.id);
      setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível importar a voz."); }
    finally { setVoiceReferenceBusy(false); }
  }

  async function regenerateSelectedScene() {
    if (!selected || selected.kind !== "video" || wanBusy) return;
    const direction = String(selected.style.planned_prompt ?? scenePrompt).trim();
    const revision = reviewComment.trim();
    const revisedPrompt = revision ? `${direction} Revision requested: ${revision}`.slice(0, 1024) : direction;
    setScenePrompt(revisedPrompt);
    await renderWanScene(selected.id, revisedPrompt);
  }

  async function applySelectedSceneEffect() {
    if (!project || selected?.kind !== "video" || effectBusy) return;
    setEffectBusy(true);
    setError("");
    try {
      const result = await centralRequest<MotionRun>("/api/motion/photo/effects", {
        method: "POST", body: JSON.stringify({ project_id: project.id, clip_id: selected.id,
          preset: effectPreset, cue_seconds: effectCue }),
      });
      await syncCompletedVideos([result], project.id);
      await exportCurrentEpisode(project.id);
      addChatMessage("assistant", `Edição de som e movimento aplicada à cena ${selected.style.scene_number}. A versão anterior permanece disponível na revisão.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível aplicar o efeito à cena.");
    } finally { setEffectBusy(false); }
  }

  async function reviewSelectedSceneImage() {
    if (!project || !selectedScene || visualReviewBusy) return;
    setVisualReviewBusy(true);
    setError("");
    try {
      const result = await reviewReference(project.id, selectedScene, true);
      addChatMessage("assistant", `Revisor visual · cena ${selectedScene.scene}: ${result.status === "pass" ? "sem falha evidente" : "precisa de revisão"}${result.findings.length ? ` — ${result.findings.join("; ")}` : ""}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha na revisão visual.");
    } finally { setVisualReviewBusy(false); }
  }

  async function correctSelectedSceneImage() {
    if (!project || !selectedScene || !selectedQualityReview?.findings.length || visualReviewBusy) return;
    setVisualReviewBusy(true);
    setError("");
    try {
      await correctReference(project.id, selectedScene, selectedQualityReview.findings);
      const result = await reviewReference(project.id, selectedScene);
      addChatMessage("assistant", `Imagem da cena ${selectedScene.scene} corrigida e reavaliada: ${result.status === "pass" ? "sem falha evidente" : result.findings.join("; ")}. A cena de vídeo anterior permanece até ser refeita.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao corrigir a imagem.");
    } finally { setVisualReviewBusy(false); }
  }

  async function pushSelectedCamera() {
    if (!project || selected?.kind !== "video" || cameraBusy) return;
    setCameraBusy(true);
    setError("");
    try {
      const generated = await centralRequest<MotionRun>("/api/motion/photo/camera-push", { method: "POST",
        body: JSON.stringify({ project_id: project.id, clip_id: selected.id }) });
      await syncCompletedVideos([generated], project.id);
      await exportCurrentEpisode(project.id);
      addChatMessage("assistant", `Movimento de avanço aplicado à cena ${selected.style.scene_number}; a versão anterior foi preservada.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha no movimento de câmera.");
    } finally { setCameraBusy(false); }
  }

  async function regenerateSelectedSceneImage() {
    if (!project || selected?.kind !== "video" || sceneImageBusy) return;
    const sceneNumber = Number(selected.style.scene_number);
    const scene = project.timeline.storyboard?.scenes.find((item) => item.scene === sceneNumber);
    if (!scene || !characterReference?.image_data) {
      setError("Esta cena precisa do roteiro e da imagem mestra do personagem.");
      return;
    }
    setSceneImageBusy(true);
    setError("");
    try {
      const prompt = sceneImageEditPrompt(scene, reviewComment);
      const image = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
        method: "POST", body: JSON.stringify({ provider: "qwen_image_2_1", prompt,
          reference_image_data: characterReference.image_data }),
      });
      const current = await request<Project>(`/api/projects/${project.id}`);
      const storyboard = current.timeline.storyboard!;
      const reference: VisualReference = { id: makeId("ref"), kind: "setting", name: `Cena ${sceneNumber} · ${scene.title}`,
        prompt, image_data: image.image_data, source: "generated_image", scene_number: sceneNumber };
      const updated = await request<Project>(`/api/projects/${project.id}`, { method: "PUT", body: JSON.stringify({
        title: current.title, summary: current.summary, timeline: { ...current.timeline,
          storyboard: { ...storyboard, references: [...(storyboard.references ?? []), reference] } },
      }) });
      setProject(updated);
      setProjects((items) => items.map((item) => item.id === updated.id ? updated : item));
      addChatMessage("assistant", `Nova imagem da cena ${sceneNumber} salva. Confira o quadro e use “Refazer cena” para animá-lo na timeline.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível refazer a imagem da cena.");
    } finally { setSceneImageBusy(false); }
  }

  function addTitle() {
    if (!project || !titleDraft.trim()) return;
    const timeline = project.timeline.tracks.some((track) => track.kind === "text")
      ? addTextClip(project.timeline, titleDraft.trim())
      : { ...project.timeline, tracks: [...project.timeline.tracks, { id: makeId("text"), name: "TÍTULOS", kind: "text" as const, clips: [] }] };
    const updatedTimeline = timeline.tracks.some((track) => track.clips.length) ? timeline : addTextClip(timeline, titleDraft.trim());
    const clip = updatedTimeline.tracks.flatMap((track) => track.clips).at(-1);
    if (clip) setSelectedClip(clip.id);
    void persist({ ...project, timeline: updatedTimeline });
  }

  function saveSceneReview(status: "pending" | "approved" | "needs_revision") {
    if (!project || !selected || selected.kind !== "video") return;
    const reviewedTimeline = updateClipReview(project.timeline, selected.id, {
      review_status: status,
      review_comment: reviewComment.trim(),
    });
    void persist({ ...project, timeline: { ...reviewedTimeline, storyboard: reviewedTimeline.storyboard
      ? { ...reviewedTimeline.storyboard, episode_status: "draft" } : reviewedTimeline.storyboard } });
  }

  function setSceneVoice(profile: string) {
    if (!project || !sceneSpeaker || !profile) return;
    const storyboard = project.timeline.storyboard ?? { theme: project.summary, scenes: [] };
    void persist({ ...project, timeline: { ...project.timeline, storyboard: {
      ...storyboard, voice_profiles: { ...storyboard.voice_profiles, [sceneSpeaker]: profile }, episode_status: "draft",
    } } });
  }

  function restoreSelectedVersion(version: number) {
    if (!project || !selected || selected.kind !== "video") return;
    const restoredTimeline = restoreClipVersion(project.timeline, selected.id, version);
    void persist({ ...project, timeline: { ...restoredTimeline, storyboard: restoredTimeline.storyboard
      ? { ...restoredTimeline.storyboard, episode_status: "draft" } : restoredTimeline.storyboard } });
  }

  function approveEpisode() {
    if (!project || !videoClips.length || !plannedScenesComplete || videoClips.some((clip) => clip.style.review_status !== "approved")) return;
    void persist({ ...project, timeline: { ...project.timeline, storyboard: {
      ...(project.timeline.storyboard ?? { theme: "", scenes: [] }), episode_status: "approved",
    } } });
  }

  return (
    <main className="studio" data-theme={theme}>
      <header className="topbar">
        <a className="brand" href="#" aria-label="AI Motion Studio início"><span className="brand-mark">M</span><span>AI MOTION <b>STUDIO</b><small>LOCAL CREATIVE SUITE</small></span></a>
        <div className="project-switch"><span>PROJETO</span><select aria-label="Projeto ativo" value={project?.id ?? ""} onChange={(event) => { setProject(projects.find((item) => item.id === event.target.value) ?? null); setChatMessages([]); setChatPrompt(""); setPromptImage(null); }}><option value="">Selecione projeto</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select><button className="icon-button" onClick={() => void createProject()} aria-label="Criar novo projeto">＋</button></div>
        <div className="top-actions"><span className={saved ? "save-status" : "save-status pending"}><i />{saved ? "SALVO" : "SALVANDO"}</span>{finalExport?.url ? <a className="export-button" download href={finalExport.url}>BAIXAR EPISÓDIO <span>↗</span></a> : finalArtifact ? <a className="export-button" download href={`/api/motion/runs/${wanRun!.id}/artifacts/${finalArtifact.id}`}>EXPORTAR <span>↗</span></a> : <button className="export-button" disabled title={episodeApproved ? "Aguardando montagem final" : "Aguardando cenas e montagem final"}>EXPORTAR <span>↗</span></button>}</div>
      </header>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")} aria-label="Fechar erro">×</button></div>}
      <section className="workspace">
        <aside className="motion-chat panel" aria-label="Chat de produção do Motion Studio">
          <div className="motion-chat-header"><span className="motion-chat-mark">✦</span><div><strong>Central IA</strong><small>Direção do Motion Studio</small></div><span className="motion-chat-status">{autoBusy ? "Produzindo" : imageStageReady ? "Imagens prontas" : "Pronta"}</span></div>
          <div className="motion-chat-feed" ref={chatFeedRef} aria-live="polite">
            {!chatMessages.length && !episodePlan.length && <div className="motion-chat-welcome"><span className="motion-chat-orbit">✧</span><h2>Qual é a história?</h2><p>Conte o tema em uma mensagem. Você pode anexar uma imagem ou deixar a Central criar todas as referências.</p><button onClick={() => setChatPrompt("Um inventor descobre que uma gota muda a cor de todo o laboratório. Mini série vertical, humor e suspense, com Caio como protagonista.")}>Experimentar um tema</button></div>}
            {chatMessages.map((message) => <div key={message.id} className={`motion-chat-message ${message.role}`}><span>{message.role === "user" ? "Você" : "✦ Central IA"}</span><p>{message.text}</p></div>)}
            {episodePlan.length > 0 && <div className="motion-chat-message assistant"><span>✦ Central IA</span><p>Roteiro de {episodePlan.length} cenas salvo. {sceneImages.length}/{episodePlan.length} imagens prontas. {videoClips.length}/{episodePlan.length} vídeos na timeline.</p>{project?.summary && (!plannedScenesComplete || !finalExport?.url) && <button className="motion-chat-continue" onClick={() => void (plannedScenesComplete ? exportCurrentEpisode() : createEpisodeFromChat(project.summary))} disabled={autoBusy || Boolean(promptImage)}>{plannedScenesComplete ? "Montar MP4 final →" : imageStageReady ? "Continuar produção →" : "Continuar este episódio →"}</button>}{project?.summary && plannedScenesComplete && /corredor/i.test(project.summary) && episodePlan.some((scene) => referenceKeyframeCount(scene.pose_count) > 2 && videoClips.some((clip) => clip.style.scene_number === scene.scene && clip.style.version === 1)) && <button className="motion-chat-continue" onClick={() => void createEpisodeFromChat(project.summary)} disabled={autoBusy}>Aprimorar movimentos das cenas →</button>}{plannedScenesComplete && hasContinuousNarration && <button className="motion-chat-continue" onClick={() => void regenerateNarration()} disabled={autoBusy}>Refazer narração e MP4 →</button>}</div>}
            {episodePlan.length > 0 && imageStageReady && !videoClips.length && !autoBusy && <><button className="motion-chat-continue" onClick={() => void redoImagesAndContinue()}>Refazer os {episodePlan.length} quadros</button>{characterReference?.source === "generated_image" && <button className="motion-chat-continue" onClick={() => void redoImagesAndContinue(true)}>Refazer personagem e quadros</button>}</>}
            {characterReference?.image_data && <div className="motion-chat-images"><strong>Imagem mestra do personagem</strong><div><figure><img src={characterReference.image_data} alt="Imagem mestra do personagem" /><figcaption>{characterReference.name}</figcaption></figure></div></div>}
            {sceneImages.length > 0 && <div className="motion-chat-images"><strong>Quadros de referência · {sceneImages.length}/{episodePlan.length || 8}</strong><div>{sceneImages.map((reference) => <figure key={reference.id}><img src={reference.image_data} alt={reference.name} /><figcaption>{reference.name}</figcaption></figure>)}</div></div>}
            {autoProgress && <p className="motion-chat-progress" role="status">✦ {autoProgress}</p>}
            {wanRun && <p className="motion-chat-run">Cena em andamento: {wanRun.state}{wanRun.error ? ` · ${wanRun.error}` : ""}</p>}
          </div>
          <div className="motion-chat-composer">
            <details className="chat-references"><summary>VoiceStudio · criar voz</summary>
              <p className="helper-text">Gravação WAV PCM com 3 a 20 segundos de fala clara. A transcrição deve corresponder exatamente ao áudio.</p>
              <label className="field-label" htmlFor="chat-voice-name">NOME DA VOZ</label>
              <input id="chat-voice-name" value={newVoiceName} maxLength={80} onChange={(event) => setNewVoiceName(event.target.value)} />
              <label className="field-label" htmlFor="chat-voice-text">TEXTO DA GRAVAÇÃO</label>
              <input id="chat-voice-text" value={voiceReferenceText} maxLength={300} onChange={(event) => setVoiceReferenceText(event.target.value)} />
              <label className="reference-upload">{voiceReferenceBusy ? "CRIANDO VOZ…" : "ENVIAR GRAVAÇÃO WAV"}
                <input type="file" accept="audio/wav,.wav" onChange={(event) => void importBrazilianVoice(event)} disabled={voiceReferenceBusy || !newVoiceName.trim() || !voiceReferenceText.trim()} />
              </label>
              <p className="helper-text">{voiceCatalog.ready ? `${voiceCatalog.voices.length} vozes disponíveis` : "VoiceStudio indisponível"}</p>
            </details>
            {promptImage && <div className="motion-chat-attachment"><img src={promptImage.image_data} alt="Imagem anexada ao pedido" /><span>{promptImage.name}</span><button onClick={() => setPromptImage(null)} aria-label="Remover imagem anexada">×</button></div>}
            <div className="motion-chat-input-row"><button className="motion-attach" onClick={() => promptImageInputRef.current?.click()} disabled={autoBusy} aria-label="Anexar imagem de referência">＋</button>
              <input ref={promptImageInputRef} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadPromptImage} />
              <textarea aria-label="Mensagem para a Central IA" value={chatPrompt} onChange={(event) => setChatPrompt(event.target.value)} maxLength={2000} rows={3} placeholder="Conte um tema ou peça para continuar…" onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void createEpisodeFromChat(); } }} />
              <button className="motion-send" onClick={() => void createEpisodeFromChat()} disabled={!embedded || autoBusy || !chatPrompt.trim()} aria-label="Enviar pedido para criar episódio">➤</button></div>
            <small>Roteiro → cenário fixo e poses → montagem por fotos → narração → revisão na timeline</small>
          </div>
        </aside>
        <section className="center-column">
          <div className="preview-panel panel">
            <div className="panel-heading"><span>02 / MONITOR</span><span className="resolution">{project?.timeline.width ?? 1280} × {project?.timeline.height ?? 720} · {fps} FPS</span></div>
            <Preview
              timeline={project?.timeline ?? initialTimeline()}
              frame={playheadFrame}
              videoClip={activeVideoClip} videoRef={videoRef}
              onVideoTime={(seconds) => {
                if (activeVideoClip) {
                  setPlayheadFrame(Math.min(projectLength, activeVideoClip.start_frame + Math.round(seconds * fps)));
                  const audioSeconds = activeAudioClip?.style.continuous_narration
                    ? activeVideoClip.start_frame / fps + seconds : seconds;
                  if (audioRef.current && Math.abs(audioRef.current.currentTime - audioSeconds) > .12) audioRef.current.currentTime = audioSeconds;
                }
              }}
              onVideoEnded={handleVideoEnded}
              onVideoReady={() => {
                if (videoRef.current && activeVideoClip) {
                  const player = videoRef.current;
                  if (pendingPlaybackClipRef.current === activeVideoClip.id) {
                    pendingPlaybackClipRef.current = null;
                    player.currentTime = 0;
                    void player.play().then(() => {
                      setPlaying(true);
                      if (audioRef.current) {
                        const target = activeAudioClip?.style.continuous_narration ? activeVideoClip.start_frame / fps : 0;
                        if (Math.abs(audioRef.current.currentTime - target) > .12) audioRef.current.currentTime = target;
                        if (audioRef.current.paused) void audioRef.current.play();
                      }
                    }).catch(() => {
                      setPlaying(false);
                      setError("O navegador não conseguiu reproduzir a próxima cena Wan.");
                    });
                  } else {
                    player.currentTime = Math.max(0, (playheadFrame - activeVideoClip.start_frame) / fps);
                  }
                }
              }}
            />
            {activeAudioClip && <audio key={activeAudioClip.id} ref={audioRef}
              src={activeAudioUrl ?? undefined}
              preload="metadata" aria-label={`Fala de ${activeAudioClip.style.speaker}`}
              onLoadedMetadata={(event) => {
                const seconds = activeAudioClip.style.continuous_narration ? playheadFrame / fps :
                  (videoRef.current?.currentTime ?? Math.max(0, (playheadFrame - activeAudioClip.start_frame) / fps));
                event.currentTarget.currentTime = seconds;
                if (videoRef.current && !videoRef.current.paused) void event.currentTarget.play();
              }} />}
            <div className="transport">
              <button aria-label="Voltar ao início" onClick={() => seekTo(0)}>|◀</button>
              <button className="transport-play" aria-label={playing ? "Pausar prévia" : "Reproduzir prévia"}
                disabled={!activeVideoClip} onClick={() => void togglePlayback()}>{playing ? "Ⅱ" : "▶"}</button>
              <button aria-label="Próxima cena" disabled={!videoClips.length}
                onClick={() => seekTo(videoClips.find((clip) => clip.start_frame > playheadFrame)?.start_frame ?? 0)}>▶|</button>
              <span>{formatTimecode(playheadFrame, fps)} <b>/</b> {formatTimecode(projectLength, fps)}</span>
            </div>
            <input className="timeline-scrubber" aria-label="Posição da prévia na timeline" type="range"
              min={0} max={projectLength} step={1} value={Math.min(playheadFrame, projectLength)}
              onChange={(event) => seekTo(Number(event.target.value))} disabled={!project} />
            {activeVideoClip && wanVideoPreviewUrl(activeVideoClip.style.motion_run_id, activeVideoClip.style.motion_artifact_id) && (
              <div className="render-meta">
                <span>{activeVideoClip.name} · Vídeo gerado</span>
                <a href={wanVideoPreviewUrl(activeVideoClip.style.motion_run_id, activeVideoClip.style.motion_artifact_id)!.replace(/\/preview$/, "")}>
                  Baixar MP4
                </a>
                {activeAudioUrl && <a href={activeAudioUrl.replace(/\/preview$/, "")}>Baixar WAV</a>}
              </div>
            )}
            {importNotice && <p className="preview-import-notice" role="status">{importNotice}</p>}
          </div>
          <div className="timeline-panel panel">
            <div className="timeline-toolbar"><div className="panel-heading"><span>03 / TIMELINE</span><span className="timeline-hint">TEMPO EM FRAMES · {project?.timeline.fps ?? 24} FPS</span></div><div className="timeline-tools"><button onClick={addTitle} disabled={!project}>＋ TÍTULO</button><button disabled>MARCADOR</button><button disabled title="Atalho: Ctrl+Z">↶</button><button disabled title="Atalho: Ctrl+Shift+Z">↷</button></div></div>
            <div className="ruler">{Array.from({ length: 6 }, (_, index) => <span key={index}>{clock(projectLength ? Math.round(index * projectLength / (5 * fps)) : 0)}</span>)}</div>
            <div className="tracks">{project?.timeline.tracks.map((track) => (
              <div className="track-row" key={track.id}><div className="track-label"><b>{track.name}</b><button aria-label={`Bloquear trilha ${track.name}`} disabled>⌑</button></div><div className="track-lane">{track.clips.map((clip) => {
                const left = projectLength ? clip.start_frame / projectLength * 100 : 0;
                const width = projectLength ? Math.max(3, clip.duration_frames / projectLength * 100) : 0;
                const isSelected = selectedClip === clip.id;
                const className = `clip clip-${clip.kind} ${isSelected ? "selected" : ""}`;
                const style = { left: `${left}%`, width: `${width}%` };
                return <button key={clip.id} className={className} style={style} onClick={() => { seekTo(clip.start_frame); setSelectedClip(clip.id); }} title={clip.name}><span>{clip.kind === "text" ? "T " : "◧ "}{clip.name}</span></button>;
              })}</div></div>
            )) ?? <div className="empty-project"><b>Crie um projeto para começar.</b><button onClick={() => void createProject()}>NOVO PROJETO</button></div>}</div>
          </div>
        </section>
        <section className="scene-review panel">
          <div className="panel-heading"><span>REVISÃO DA CENA</span></div>
          {selected?.kind === "video" ? <>
            <b>{selected.name}</b>
            <p className="helper-text">Selecione uma cena na timeline, descreva a alteração e gere somente essa parte.</p>
            <textarea aria-label="Alteração desejada na cena" value={reviewComment} maxLength={2000} placeholder="O que deve mudar nesta cena?" onChange={(event) => setReviewComment(event.target.value)} />
            <div className="review-actions"><button className="quiet-button" onClick={() => saveSceneReview("approved")}>✓ APROVAR CENA</button><button className="quiet-button" onClick={() => saveSceneReview("needs_revision")}>MARCAR REVISÃO</button><button className="quiet-button" onClick={() => void regenerateSelectedSceneImage()} disabled={!embedded || sceneImageBusy}>↻ {sceneImageBusy ? "GERANDO IMAGEM…" : "REFAZER IMAGEM"}</button><button className="quiet-button" onClick={() => void regenerateSelectedScene()} disabled={!embedded || wanBusy || sceneImageBusy}>↻ REFAZER CENA</button></div>
            <button className="quiet-button" onClick={() => void reviewSelectedSceneImage()} disabled={!embedded || visualReviewBusy || !selectedReference}>{visualReviewBusy ? "REVISANDO IMAGEM…" : "REVISAR IMAGEM COM IA"}</button>
            {selectedQualityReview && <p className="helper-text" role="status">Revisor visual: {selectedQualityReview.status === "pass" ? "sem falha evidente" : "revisão necessária"}{selectedQualityReview.findings.length ? ` · ${selectedQualityReview.findings.join("; ")}` : ""}</p>}
            {selectedQualityReview?.status === "needs_revision" && <button className="quiet-button" onClick={() => void correctSelectedSceneImage()} disabled={visualReviewBusy}>CORRIGIR IMAGEM SINALIZADA</button>}
            <button className="quiet-button" onClick={() => void pushSelectedCamera()} disabled={!embedded || cameraBusy || effectBusy}>{cameraBusy ? "MOVENDO CÂMERA…" : "AVANÇAR CÂMERA PELA CENA"}</button>
            <label className="field-label" htmlFor="scene-effect">MOVIMENTO E EFEITO SONORO</label>
            <select id="scene-effect" value={effectPreset} onChange={(event) => setEffectPreset(event.target.value)}>
              <option value="footsteps">Passos com movimento suave</option>
              <option value="lamp_clicks">Lâmpadas estalando</option>
              <option value="door_slam">Porta batendo · corte e tremor</option>
              <option value="wind">Vento ambiente</option>
              <option value="metal_creak">Metal rangendo</option>
            </select>
            <label className="field-label" htmlFor="effect-cue">INSTANTE DA AÇÃO NA CENA (SEGUNDOS)</label>
            <input id="effect-cue" type="number" min="0.5" max={Math.max(.5, selected.duration_frames / (project?.timeline.fps ?? 24) - .5)} step="0.1" value={effectCue} onChange={(event) => setEffectCue(Number(event.target.value))} />
            <button className="quiet-button" onClick={() => void applySelectedSceneEffect()} disabled={!embedded || effectBusy || autoBusy}>{effectBusy ? "APLICANDO EDIÇÃO…" : "APLICAR EDIÇÃO À CENA"}</button>
            {Array.isArray(selected.style.previous_versions) && selected.style.previous_versions.map((version: any) => <button className="quiet-button" key={version.version} onClick={() => restoreSelectedVersion(Number(version.version))}>RESTAURAR VERSÃO {version.version}</button>)}
            <label className="field-label" htmlFor="review-speech">FALA DESTA CENA</label>
            <textarea id="review-speech" value={sceneSpeechText} maxLength={300} onChange={(event) => setSceneSpeechText(event.target.value)} />
            <label className="field-label" htmlFor="review-speaker">PERSONAGEM / NARRADOR</label>
            <input id="review-speaker" value={sceneSpeaker} maxLength={64} onChange={(event) => setSceneSpeaker(event.target.value)} />
            <label className="field-label" htmlFor="review-voice">VOZ DE {sceneSpeaker}</label>
            <select id="review-voice" value={project?.timeline.storyboard?.voice_profiles?.[sceneSpeaker] ?? ""} onChange={(event) => setSceneVoice(event.target.value)}>
              <option value="">Selecione uma voz</option>{voiceCatalog.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}
            </select>
            <button className="quiet-button" onClick={() => void generateSelectedSceneSpeech()} disabled={!embedded || sceneSpeechBusy || !sceneSpeechText.trim()}>{sceneSpeechBusy ? "GERANDO FALA…" : /^[a-f0-9]{8}$/.test(project?.timeline.storyboard?.voice_profiles?.[sceneSpeaker] ?? "") && /^narrad/i.test(sceneSpeaker) ? "↻ REFAZER NARRAÇÃO" : "↻ REFAZER FALA"}</button>
          </> : <><p className="helper-text">Selecione um clipe de vídeo na timeline para aprovar ou solicitar uma alteração.</p><button className="quiet-button" onClick={approveEpisode} disabled={!videoClips.length || !plannedScenesComplete || videoClips.some((clip) => clip.style.review_status !== "approved")}>APROVAR EPISÓDIO</button></>}
          {[2, 8].includes(episodePlan.length) && videoClips.length === episodePlan.length && <button className="quiet-button" onClick={() => void exportCurrentEpisode().catch((reason) => setError(reason instanceof Error ? reason.message : "Falha na montagem."))} disabled={autoBusy}>ATUALIZAR MP4 FINAL</button>}
        </section>      </section>
      <footer className="statusbar"><span><i className={capabilities?.comfyui.status === "available" ? "dot online" : "dot"} /> COMFYUI {capabilities?.comfyui.status === "available" ? "CONECTADO" : "DESCONECTADO"}</span><span>ARMAZENAMENTO LOCAL · SQLITE</span><span>AI MOTION STUDIO 0.1.0</span></footer>
    </main>
  );
}
