import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type RefObject } from "react";

import { addSceneCaptionClip, addSceneSpeechClip, addTextClip, addWanSpeechClip, addWanVideoClip, compositionEndFrame, formatTimecode, makeId, restoreClipVersion, standaloneSpeechPreviewUrl, updateClipReview, updateSceneCaptionClip, wanRunMatchesProject, wanVideoPreviewUrl } from "./timeline.mjs";

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
type VisualReference = { id: string; kind: "character" | "setting"; name: string; prompt: string; image_data?: string; source: "generated_brief" | "generated_image" | "upload" };
type VoiceProfile = string;
type Timeline = { schema_version: 1; fps: number; width: number; height: number; tracks: Track[]; storyboard?: { theme: string; scenes: PlannedScene[]; references?: VisualReference[]; voice_profiles?: Record<string, VoiceProfile>; episode_status?: "draft" | "approved"; publication?: { cover_text: string; caption: string; hashtags: string } } };
type Project = { id: string; title: string; summary: string; timeline: Timeline; updated_at: string };
type Capabilities = { comfyui: { installed: boolean; status: string }; wan21_t2v_13b: { installed: boolean }; ffmpeg: { installed: boolean }; rendering: { status: string }; transcription: { status: string } };
type MotionRun = { id: string; project_id?: string; state: string; error: string | null; jobs: Array<{ id: string; adapter?: string; state: string; frames?: number | null; fps?: number | null; scene_number?: number | null; replace_clip_id?: string | null; speech_artifact_id?: string | null; speech_text?: string | null; speaker?: string | null; voice_profile?: string | null; error: string | null; artifact: { id: string; path: string; bytes: number } | null }> };
type MotionTools = { comfy_endpoint: string | null; comfy_root: string | null; allow_remote: boolean; executables: Record<string, string> | null; comfy_status?: string };
type PlannedScene = { scene: number; title: string; prompt: string; hook?: string; cliffhanger?: string; speaker?: string; dialogue?: string };

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

function lastVideoFrameDataUrl(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "auto";
    video.muted = true;
    video.onloadedmetadata = () => { video.currentTime = Math.max(0, video.duration - 1 / 16); };
    video.onseeked = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Não foi possível ler o quadro do vídeo.");
        context.drawImage(video, 0, 0);
        resolve(canvas.toDataURL("image/png"));
      } catch (reason) { reject(reason); }
      finally { video.removeAttribute("src"); video.load(); }
    };
    video.onerror = () => reject(new Error("Não foi possível extrair o último quadro da primeira tomada."));
    video.src = url;
  });
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
  const [wanConfigSaved, setWanConfigSaved] = useState(false);
  const [, setWanConfigStatus] = useState("Iniciando automaticamente os motores locais…");
  const [scenePrompt, setScenePrompt] = useState("Vertical cinematic 3D horror scene, a small geometric glass figure crossing a dim abandoned hallway, cold blue moonlight, deep shadows, slow camera push, unsettling atmosphere, polished motion design, no text.");
  const [sceneSpeechText, setSceneSpeechText] = useState("");
  const [sceneSpeaker, setSceneSpeaker] = useState("Lara");
  const [sceneSpeechBusy, setSceneSpeechBusy] = useState(false);
  const [episodeNumber] = useState(1);
  const [sceneNumber] = useState(1);
  const [videoModel] = useState<"wan" | "ltxv">("wan");
  const [characterReferenceId] = useState("");
  const [wanRun, setWanRun] = useState<MotionRun | null>(null);
  const [wanBusy, setWanBusy] = useState(false);
  const [, setEpisodeRun] = useState(false);
  const [voiceCatalog, setVoiceCatalog] = useState<{ ready: boolean; voices: { id: string; name: string }[] }>({ ready: false, voices: [] });
  const [chatPrompt, setChatPrompt] = useState("Crie um mini episódio vertical animado, com humor e suspense, sobre uma máquina de refrigerantes que transforma palavras em mundos. Narração clara em português brasileiro, personagens 3D estilizados, cores vivas, cenas conectadas e final com gancho. Use o vídeo de referência apenas como inspiração de ritmo e linguagem visual; crie história e personagens originais.");
  const [autoProgress, setAutoProgress] = useState("");
  const [autoBusy, setAutoBusy] = useState(false);
  const [finalExport, setFinalExport] = useState<{ id: string | null; url: string | null; duration?: number } | null>(null);
  const [episodePlan, setEpisodePlan] = useState<PlannedScene[]>([]);
  const [referenceKind, setReferenceKind] = useState<VisualReference["kind"]>("character");
  const [referenceProvider, setReferenceProvider] = useState<"local_comfyui" | "huggingface">("local_comfyui");
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [playheadFrame, setPlayheadFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [importNotice, setImportNotice] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pendingPlaybackClipRef = useRef<string | null>(null);
  const embedded = new URLSearchParams(window.location.search).get("embedded") === "central";

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
    void centralRequest<{ ready: boolean; voices: { id: string; name: string }[] }>("/api/motion/voices")
      .then(setVoiceCatalog).catch(() => setVoiceCatalog({ ready: false, voices: [] }));
    let active = true;
    void centralRequest<MotionTools>("/api/motion/tools")
      .then((config) => {
        if (!active) return;
        const configured = Boolean(config.comfy_endpoint && config.comfy_root);
        setWanConfigSaved(configured);
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
        setWanConfigSaved(false);
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
  const fps = project?.timeline.fps ?? 24;
  const projectLength = project ? compositionEndFrame(project.timeline) : 0;
  const videoClips = project?.timeline.tracks.filter((track) => track.kind === "video").flatMap((track) => track.clips) ?? [];
  const visualReferences = project?.timeline.storyboard?.references ?? [];
  const characterReferences = visualReferences.filter((reference) => reference.kind === "character" && reference.image_data);
  const characterReference = characterReferences.find((reference) => reference.id === characterReferenceId) ?? characterReferences[0];
  const plannedScenesComplete = !episodePlan.length || episodePlan.every((scene) => videoClips.some((clip) => clip.style.scene_number === scene.scene));

  function saveVisualReference(reference: VisualReference) {
    if (!project) return;
    const storyboard = project.timeline.storyboard ?? { theme: project.summary, scenes: [] };
    void persist({ ...project, timeline: { ...project.timeline, storyboard: {
      ...storyboard, references: [...(storyboard.references ?? []), reference],
    } } });
  }

  function uploadVisualReference(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !project) return;
    if (!/image\/(png|jpeg|webp)/.test(file.type) || file.size > 6 * 1024 * 1024) {
      setError("Envie PNG, JPG ou WebP de até 6 MB."); return;
    }
    const reader = new FileReader();
    reader.onload = () => saveVisualReference({ id: makeId("ref"), kind: referenceKind,
      name: file.name.replace(/\.[^.]+$/, ""), prompt: "Referência visual enviada pelo usuário.",
      image_data: String(reader.result), source: "upload" });
    reader.readAsDataURL(file);
  }

  async function generateVisualReference() {
    if (!project || referenceBusy) return;
    setReferenceBusy(true);
    try {
      const prompt = `Original ${referenceKind === "character" ? "character sheet" : "setting sheet"} for ${project.summary.slice(0, 350)}. Consistent stylized 3D animation, vertical 9:16, no text.`;
      const result = await centralRequest<{ image_data: string }>("/api/motion/references/generate", {
        method: "POST", body: JSON.stringify({ provider: referenceProvider, prompt }),
      });
      saveVisualReference({ id: makeId("ref"), kind: referenceKind,
        name: referenceKind === "character" ? "Personagem" : "Cenário", prompt,
        image_data: result.image_data, source: "generated_image" });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na imagem de referência."); }
    finally { setReferenceBusy(false); }
  }

  const episodeApproved = project?.timeline.storyboard?.episode_status === "approved";
  const finalArtifact = wanRun?.state === "completed" && episodeApproved ? wanRun.jobs.find((job) => job.id === "assemble" && job.artifact)?.artifact : null;
  const activeVideoClip = project ? (clipAtFrame(project.timeline, playheadFrame, "video") ??
    (selected?.kind === "video" ? selected : undefined)) : undefined;
  const activeAudioClip = project && activeVideoClip ? project.timeline.tracks
    .filter((track) => track.kind === "audio").flatMap((track) => track.clips)
    .find((clip) => clip.style.source_video_clip_id === activeVideoClip.id) : undefined;
  const activeAudioUrl = activeAudioClip ? (activeAudioClip.style.motion_speech_id
    ? standaloneSpeechPreviewUrl(activeAudioClip.style.motion_speech_id)
    : wanVideoPreviewUrl(activeAudioClip.style.motion_run_id, activeAudioClip.style.motion_artifact_id)) : null;

  useEffect(() => {
    setReviewComment(selected?.kind === "video" ? String(selected.style.review_comment ?? "") : "");
  }, [selected?.id, selected?.kind, selected?.style.review_comment]);

  useEffect(() => {
    if (selected?.kind !== "video" || !project) return;
    const speech = project.timeline.tracks.filter((track) => track.kind === "audio")
      .flatMap((track) => track.clips).find((clip) => clip.style.source_video_clip_id === selected.id);
    setSceneSpeechText(String(speech?.style.speech_text ?? ""));
    const planned = project.timeline.storyboard?.scenes.find((scene) => scene.scene === selected.style.scene_number);
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
        job.adapter === "comfyui_wan" && job.state === "completed" && job.artifact &&
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
      if (video.speechText) timeline = addSceneCaptionClip(timeline, {
        runId: video.runId, videoArtifactId: video.artifactId, text: video.speechText,
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
    if (!project) return;
    const clip = clipAtFrame(project.timeline, Math.min(next, Math.max(0, projectLength - 1)), "video");
    if (clip) {
      setSelectedClip(clip.id);
      if (clip.id === activeVideoClip?.id && videoRef.current) {
        videoRef.current.currentTime = (next - clip.start_frame) / fps;
        if (audioRef.current) audioRef.current.currentTime = (next - clip.start_frame) / fps;
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
        audioRef.current.currentTime = player.currentTime;
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
    audioRef.current?.pause();
    const next = videoClips.find((clip) => clip.start_frame >= activeVideoClip.start_frame + activeVideoClip.duration_frames);
    if (!next) {
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
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao criar projeto.");
    }
  }

  async function createReferencePilot() {
    const reference = characterReference;
    if (!reference?.image_data || autoBusy) return;
    setAutoBusy(true);
    setError("");
    try {
      const voice = voiceCatalog.voices.find((item) => /pt-br|brasileir/i.test(item.name)) ?? voiceCatalog.voices[0];
      if (!voiceCatalog.ready || !voice) throw new Error("Instale uma voz em português para testar as falas.");
      const identity = "Luna, exactly the same girl as the input image: short golden blond bob, large blue eyes, magenta-purple hoodie, white pants. Polished 3D animation in a luminous mint-green forest. One stable medium shot, locked camera. Keep her centered and preserve her face, hair, outfit and background. No text or extra people. ";
      const scenes: PlannedScene[] = [
        { scene: 1, title: "Luna encontra a luz", prompt: identity + "She notices a tiny glow, blinks and gently lifts one hand. Subtle natural motion; she does not walk or turn away.", speaker: "Luna", dialogue: "Olha, uma luz!" },
        { scene: 2, title: "Luna segue a luz", prompt: identity + "Continue seamlessly from the input frame. She smiles and slightly raises her hand toward the light. Her body and camera stay in place.", speaker: "Luna", dialogue: "Ela abriu o caminho!" },
      ];
      setAutoProgress("Preparando duas tomadas com a mesma imagem mestra…");
      const created = await request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ title: `Teste de continuidade · ${reference.name}`, summary: "Piloto de duas tomadas com imagem mestra e voz de Luna." }) });
      const seeded = await request<Project>(`/api/projects/${created.id}`, { method: "PUT", body: JSON.stringify({ title: created.title, summary: created.summary, timeline: {
        ...initialTimeline(), width: 720, height: 1280, storyboard: { theme: created.summary, scenes,
          references: [reference], voice_profiles: { Luna: voice.id }, episode_status: "draft" },
      } }) });
      setProject(seeded);
      setProjects((current) => [seeded, ...current]);
      setEpisodePlan(scenes);
      let imageData = reference.image_data;
      for (const scene of scenes) {
        setAutoProgress(`Gerando tomada ${scene.scene}/2 com imagem mestra e voz…`);
        const queued = await centralRequest<MotionRun>("/api/motion/ltx/scenes", { method: "POST", body: JSON.stringify({
          project_id: seeded.id, episode: 1, scene: scene.scene, prompt: scene.prompt,
          image_data: imageData, width: 480, height: 832, frames: 49, fps: 16,
          speech_text: scene.dialogue, speaker: "Luna", voice_profile: voice.id,
        }) });
        setWanRun(queued);
        let latest = queued;
        for (let attempt = 0; attempt < 600 && ["queued", "running"].includes(latest.state); attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          latest = await centralRequest<MotionRun>(`/api/motion/runs/${queued.id}`);
          setWanRun(latest);
        }
        if (latest.state !== "completed") throw new Error(`Tomada ${scene.scene}: ${latest.error || latest.state}.`);
        await syncCompletedVideos([latest], seeded.id);
        if (scene.scene === 1) {
          const artifact = latest.jobs.find((job) => job.adapter === "comfyui_wan")?.artifact;
          const preview = artifact && wanVideoPreviewUrl(latest.id, artifact.id);
          if (!preview) throw new Error("A primeira tomada não trouxe um MP4 para continuar a cena.");
          imageData = await lastVideoFrameDataUrl(preview);
        }
      }
      setAutoProgress("Montando o piloto com voz e legendas…");
      await exportCurrentEpisode(seeded.id);
      setAutoProgress("Piloto de duas tomadas pronto para comparar na timeline.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha no piloto com imagem mestra.");
      setAutoProgress("As tomadas concluídas foram preservadas para revisão.");
    } finally { setAutoBusy(false); }
  }

  async function createEpisodeFromChat() {
    const idea = chatPrompt.trim();
    if (!idea || autoBusy) return;
    setAutoBusy(true);
    setError("");
    try {
      let scenes: PlannedScene[];
      let planned: Project;
      if (project?.summary === idea && project.timeline.storyboard?.scenes.length === 8) {
        scenes = project.timeline.storyboard.scenes;
        planned = project;
        setAutoProgress("Retomando as cenas pendentes deste projeto…");
      } else {
      setAutoProgress("Trabalhadores criando roteiro, falas e direção visual…");
      const conversation = await centralRequest<{ id: string }>("/api/conversations", { method: "POST", body: JSON.stringify({ title: `Mini episódio · ${idea.slice(0, 60)}` }) });
      const planning = await centralRequest<{ id: string }>("/api/runs", { method: "POST", body: JSON.stringify({ conversation_id: conversation.id, mode: "auto", autonomous: false, prompt: [
        "Escreva somente JSON com roteiro e descrições visuais de uma minissérie vertical animada original para Instagram.",
        `Brief narrativo: "${idea.replace(/["\r\n]/g, " ")}"`,
        "O roteiro deve ter exatamente 8 cenas consecutivas de cerca de 7 segundos. Cada ação deve decorrer claramente da cena anterior. Visual 3D estilizado 9:16, personagens com aparência e roupa consistentes, ações filmáveis em Wan e sem texto legível na imagem. Uma fala curta por cena ou fala vazia. Falas devem caber em 7 segundos e usar português brasileiro natural, sem palavras de outro idioma. Prefira narração fora de cena quando houver personagem falando, pois sincronização labial ainda não está disponível.",
        "Responda SOMENTE JSON válido: [{\"scene\":1,\"title\":\"...\",\"hook\":\"...\",\"prompt\":\"direção visual detalhada em inglês, vertical 9:16, sem texto na imagem\",\"speaker\":\"Narradora\",\"dialogue\":\"fala curta em português\",\"cliffhanger\":\"...\"}].",
      ].join("\n") }) });
      let status = "queued";
      for (let attempt = 0; attempt < 180 && ["queued", "running", "awaiting_approval"].includes(status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        status = (await centralRequest<{ status: string }>(`/api/runs/${planning.id}`)).status;
      }
      if (status !== "completed") throw new Error(`O planejamento terminou com estado ${status}.`);
      const messages = await centralRequest<Array<{ role: string; content: string }>>(`/api/conversations/${conversation.id}/messages`);
      const raw = messages.filter((message) => message.role === "assistant").at(-1)?.content ?? "";
      const jsonBlock = raw.match(/\[\s*\{[\s\S]*?\}\s*\]/)?.[0];
      if (!jsonBlock) throw new Error("O planejamento não trouxe cenas estruturadas.");
      scenes = JSON.parse(jsonBlock) as PlannedScene[];
      if (!Array.isArray(scenes) || scenes.length !== 8 || scenes.some((scene, index) => scene.scene !== index + 1 || !scene.title?.trim() || !scene.prompt?.trim())) throw new Error("O roteiro não retornou oito cenas válidas.");
      setAutoProgress("Criando o projeto e preparando a produção…");
      const created = await request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ title: `${scenes[0].title.slice(0, 110)} | Episódio 1`, summary: idea }) });
      const fresh = await request<Project>(`/api/projects/${created.id}`, { method: "PUT", body: JSON.stringify({ title: created.title, summary: idea, timeline: { ...initialTimeline(), fps: 24, width: 720, height: 1280 } }) });
      setProjects((current) => [fresh, ...current]);
      setProject(fresh);
      const profiles = await centralRequest<typeof voiceCatalog>("/api/motion/voices");
      const voice = profiles.voices.find((item) => /pt-br|brasileir/i.test(item.name)) ?? profiles.voices[0];
      if (scenes.some((scene) => scene.dialogue?.trim()) && (!profiles.ready || !voice)) throw new Error("Instale o motor de voz pt-BR e crie um perfil antes de produzir falas.");
      const cast = [...new Set(scenes.filter((scene) => scene.dialogue?.trim()).map((scene) => scene.speaker?.trim() || "Narradora"))];
      const alternatives = profiles.voices.filter((item) => item.id !== voice?.id);
      const voiceProfiles = Object.fromEntries(cast.map((speaker, index) => [speaker,
        /narrad/i.test(speaker) || index === 0 ? voice?.id ?? "" : alternatives[(index - 1) % alternatives.length]?.id ?? voice?.id ?? ""]));
      planned = await request<Project>(`/api/projects/${fresh.id}`, { method: "PUT", body: JSON.stringify({ title: fresh.title, summary: idea, timeline: { ...fresh.timeline, storyboard: { theme: idea, scenes, voice_profiles: voiceProfiles, episode_status: "draft" } } }) });
      setProject(planned);
      setProjects((current) => current.map((item) => item.id === planned.id ? planned : item));
      setEpisodePlan(scenes);
      }
      const voiceProfiles = planned.timeline.storyboard?.voice_profiles ?? {};
      for (const scene of scenes) {
        const current = await request<Project>(`/api/projects/${planned.id}`);
        if (current.timeline.tracks.some((track) => track.kind === "video" && track.clips.some((clip) => clip.style.scene_number === scene.scene))) continue;
        setAutoProgress(`Produzindo cena ${scene.scene}/8 com vídeo${scene.dialogue?.trim() ? " e voz" : ""}…`);
        const generated = await centralRequest<MotionRun>("/api/motion/wan/scenes", { method: "POST", body: JSON.stringify({
          project_id: planned.id, episode: 1, scene: scene.scene, prompt: scene.prompt.slice(0, 1024), frames: 121, fps: 16,
          ...(scene.dialogue?.trim() ? { speech_text: scene.dialogue.trim().slice(0, 300), speaker: scene.speaker?.trim() || "Narradora", voice_profile: voiceProfiles[scene.speaker?.trim() || "Narradora"] } : {}),
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
      }
      setAutoProgress("Montando o MP4 final com as falas das oito cenas…");
      await exportCurrentEpisode(planned.id);
      setAutoProgress("Mini episódio pronto. Assista ao MP4 e revise cada cena e fala na timeline.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível produzir o episódio.");
      setAutoProgress("Produção interrompida; as cenas concluídas foram preservadas.");
    } finally { setAutoBusy(false); }
  }

  async function exportCurrentEpisode(projectId = project?.id) {
    if (!projectId) return;
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
    if (videoModel === "ltxv" && !characterReference?.image_data) {
      setError("Selecione uma imagem mestra da personagem para gerar com LTX.");
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
          scene: replaceClipId ? Number(selected?.style.scene_number ?? sceneNumber) : sceneNumber,
          prompt,
          frames: 121,
          fps: 16,
          ...(videoModel === "ltxv" ? { image_data: characterReference?.image_data } : {}),
          replace_clip_id: replaceClipId ?? null,
          ...(sceneSpeechText.trim() ? { speech_text: sceneSpeechText.trim(), speaker: sceneSpeaker,
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

  async function regenerateSelectedScene() {
    if (!selected || selected.kind !== "video" || wanBusy) return;
    const direction = String(selected.style.planned_prompt ?? scenePrompt).trim();
    const revision = reviewComment.trim();
    const revisedPrompt = revision ? `${direction} Revision requested: ${revision}`.slice(0, 1024) : direction;
    setScenePrompt(revisedPrompt);
    await renderWanScene(selected.id, revisedPrompt);
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
        <div className="project-switch"><span>PROJETO</span><select aria-label="Projeto ativo" value={project?.id ?? ""} onChange={(event) => setProject(projects.find((item) => item.id === event.target.value) ?? null)}><option value="">Selecione projeto</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select><button className="icon-button" onClick={() => void createProject()} aria-label="Criar novo projeto">＋</button></div>
        <div className="top-actions"><span className={saved ? "save-status" : "save-status pending"}><i />{saved ? "SALVO" : "SALVANDO"}</span>{finalExport?.url ? <a className="export-button" download href={finalExport.url}>BAIXAR EPISÓDIO <span>↗</span></a> : finalArtifact ? <a className="export-button" download href={`/api/motion/runs/${wanRun!.id}/artifacts/${finalArtifact.id}`}>EXPORTAR <span>↗</span></a> : <button className="export-button" disabled title={episodeApproved ? "Aguardando montagem final" : "Aguardando cenas e montagem final"}>EXPORTAR <span>↗</span></button>}</div>
      </header>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")} aria-label="Fechar erro">×</button></div>}
      <section className="workspace">
        <aside className="creation-chat panel">
          <div className="panel-heading"><span>01 / CRIAR COM IA</span></div>
          <h2>Conte sua ideia</h2>
          <p>O roteiro, as cenas e as falas são preparados a partir de um único pedido. Depois, revise cada trecho na timeline.</p>
          <label className="field-label" htmlFor="creation-prompt">SEU PEDIDO</label>
          <textarea id="creation-prompt" value={chatPrompt} onChange={(event) => setChatPrompt(event.target.value)} maxLength={2000} rows={12} placeholder="Descreva o tema, personagens e estilo do mini episódio…" />
          <button className="primary-wide" onClick={() => void createEpisodeFromChat()} disabled={!embedded || !wanConfigSaved || autoBusy || !chatPrompt.trim()}>{autoBusy ? "PRODUZINDO…" : "✦ CRIAR MINI EPISÓDIO"}</button>
          <p className="helper-text" role="status">{autoProgress || "Vídeo e voz são gerados por cena. A timeline é preenchida conforme cada cena termina."}</p>
          <p className="helper-text">As vozes são alinhadas ao início de cada cena. A sincronização dos lábios ainda requer um motor específico e será indicada como pendente na revisão.</p>
          {wanRun && <p className="helper-text">Última cena: {wanRun.state}{wanRun.error ? ` · ${wanRun.error}` : ""}</p>}
          <details className="chat-references"><summary>Referências visuais opcionais ({visualReferences.length})</summary>
            <p className="helper-text">Envie uma imagem mestra para testar duas tomadas consecutivas antes de produzir um episódio inteiro.</p>
            <select aria-label="Tipo de referência" value={referenceKind} onChange={(event) => setReferenceKind(event.target.value as VisualReference["kind"])}><option value="character">Personagem</option><option value="setting">Cenário</option></select>
            <select aria-label="Provedor de imagem" value={referenceProvider} onChange={(event) => setReferenceProvider(event.target.value as "local_comfyui" | "huggingface")}><option value="local_comfyui">Local</option><option value="huggingface">Gratuito</option></select>
            <button className="quiet-button" onClick={() => void generateVisualReference()} disabled={!project || referenceBusy || autoBusy}>{referenceBusy ? "GERANDO…" : "GERAR IMAGEM"}</button>
            <label className="reference-upload">ENVIAR IMAGEM<input type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadVisualReference} disabled={!project || autoBusy} /></label>
            <div className="reference-thumbs">{visualReferences.map((reference) => reference.image_data && <img key={reference.id} src={reference.image_data} alt={reference.name} title={reference.name} />)}</div>
            <button className="quiet-button" onClick={() => void createReferencePilot()} disabled={!embedded || !characterReference?.image_data || autoBusy}>TESTAR 2 TOMADAS COM IMAGEM MESTRA</button>
          </details>
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
                  if (audioRef.current && Math.abs(audioRef.current.currentTime - seconds) > .12) audioRef.current.currentTime = seconds;
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
                      if (audioRef.current) { audioRef.current.currentTime = 0; void audioRef.current.play(); }
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
                const seconds = videoRef.current?.currentTime ?? Math.max(0, (playheadFrame - activeAudioClip.start_frame) / fps);
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
            <div className="review-actions"><button className="quiet-button" onClick={() => saveSceneReview("approved")}>✓ APROVAR CENA</button><button className="quiet-button" onClick={() => saveSceneReview("needs_revision")}>MARCAR REVISÃO</button><button className="quiet-button" onClick={() => void regenerateSelectedScene()} disabled={!embedded || wanBusy}>↻ REFAZER CENA</button></div>
            {Array.isArray(selected.style.previous_versions) && selected.style.previous_versions.map((version: any) => <button className="quiet-button" key={version.version} onClick={() => restoreSelectedVersion(Number(version.version))}>RESTAURAR VERSÃO {version.version}</button>)}
            <label className="field-label" htmlFor="review-speech">FALA DESTA CENA</label>
            <textarea id="review-speech" value={sceneSpeechText} maxLength={300} onChange={(event) => setSceneSpeechText(event.target.value)} />
            <label className="field-label" htmlFor="review-speaker">PERSONAGEM / NARRADOR</label>
            <input id="review-speaker" value={sceneSpeaker} maxLength={64} onChange={(event) => setSceneSpeaker(event.target.value)} />
            <label className="field-label" htmlFor="review-voice">VOZ DE {sceneSpeaker}</label>
            <select id="review-voice" value={project?.timeline.storyboard?.voice_profiles?.[sceneSpeaker] ?? ""} onChange={(event) => setSceneVoice(event.target.value)}>
              <option value="">Selecione uma voz</option>{voiceCatalog.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}
            </select>
            <button className="quiet-button" onClick={() => void generateSelectedSceneSpeech()} disabled={!embedded || sceneSpeechBusy || !sceneSpeechText.trim()}>{sceneSpeechBusy ? "GERANDO FALA…" : "↻ REFAZER FALA"}</button>
          </> : <><p className="helper-text">Selecione um clipe de vídeo na timeline para aprovar ou solicitar uma alteração.</p><button className="quiet-button" onClick={approveEpisode} disabled={!videoClips.length || !plannedScenesComplete || videoClips.some((clip) => clip.style.review_status !== "approved")}>APROVAR EPISÓDIO</button></>}
          {[2, 8].includes(episodePlan.length) && videoClips.length === episodePlan.length && <button className="quiet-button" onClick={() => void exportCurrentEpisode().catch((reason) => setError(reason instanceof Error ? reason.message : "Falha na montagem."))} disabled={autoBusy}>ATUALIZAR MP4 FINAL</button>}
        </section>      </section>
      <footer className="statusbar"><span><i className={capabilities?.comfyui.status === "available" ? "dot online" : "dot"} /> COMFYUI {capabilities?.comfyui.status === "available" ? "CONECTADO" : "DESCONECTADO"}</span><span>ARMAZENAMENTO LOCAL · SQLITE</span><span>AI MOTION STUDIO 0.1.0</span></footer>
    </main>
  );
}
