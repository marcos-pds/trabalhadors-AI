import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { addTextClip, addWanVideoClip, makeId, updateGraphemeStyle, wanRunMatchesProject, wanVideoPreviewUrl } from "./timeline.mjs";

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
type Timeline = { schema_version: 1; fps: number; width: number; height: number; tracks: Track[] };
type Project = { id: string; title: string; summary: string; timeline: Timeline; updated_at: string };
type Capabilities = { comfyui: { installed: boolean; status: string }; wan21_t2v_13b: { installed: boolean }; ffmpeg: { installed: boolean }; rendering: { status: string }; transcription: { status: string } };
type MotionRun = { id: string; project_id?: string; state: string; error: string | null; jobs: Array<{ id: string; adapter?: string; state: string; frames?: number | null; fps?: number | null; error: string | null; artifact: { id: string; path: string; bytes: number } | null }> };
type MotionTools = { comfy_endpoint: string | null; comfy_root: string | null; allow_remote: boolean; executables: Record<string, string> | null; comfy_status?: string };

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

const episodeDialogue = [
  { start: 10.5, speaker: "Lara", text: "Ué... como assim? Esse é o meu número." },
  { start: 20, speaker: "Voz desconhecida", text: "Lara... sou eu. Você precisa me escutar." },
  { start: 28, speaker: "Lara", text: "Quem tá falando?" },
  { start: 32.5, speaker: "Voz desconhecida", text: "Não abre a porta. Não importa quem seja." },
  { start: 44, speaker: "Lara", text: "Meu Deus... quem tá aí?" },
  { start: 51, speaker: "Voz atrás da porta", text: "Lara... abre. Eu sou você." },
];

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

function timecode(frame: number, fps: number): string {
  const value = Math.max(0, Math.floor(frame));
  const seconds = Math.floor(value / fps);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60, value % fps]
    .map((part) => String(part).padStart(2, "0")).join(":");
}

function clock(seconds: number): string {
  return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
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
      {!src && !textClip && <div className="preview-empty"><span className="play-glyph">▶</span><strong>PREVIEW DA COMPOSIÇÃO</strong><small>Gere uma cena Wan ou adicione um título à timeline.</small></div>}
      {textClip && <div className="preview-title" style={{ color: String(textClip.style.color ?? "#f8fafc") }}>
        {words.map((word, index) => <span key={word + "-" + index} style={{ color: textClip.style.word_colors?.[index] ?? textClip.style.color }}>{word} </span>)}
      </div>}
      <span className="preview-time">{timecode(frame, timeline.fps)}</span>
    </div>
  );
}

export default function App() {
  const theme = new URLSearchParams(window.location.search).get("theme") === "light" ? "light" : "dark";
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [selectedClip, setSelectedClip] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("O FUTURO COMEÇA AGORA");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(true);
  const [wanConfigSaved, setWanConfigSaved] = useState(false);
  const [wanConfigStatus, setWanConfigStatus] = useState("Iniciando automaticamente os motores locais…");
  const [scenePrompt, setScenePrompt] = useState("Vertical cinematic 3D horror scene, a small geometric glass figure crossing a dim abandoned hallway, cold blue moonlight, deep shadows, slow camera push, unsettling atmosphere, polished motion design, no text.");
  const [episodeNumber, setEpisodeNumber] = useState(1);
  const [sceneNumber, setSceneNumber] = useState(1);
  const [wanRun, setWanRun] = useState<MotionRun | null>(null);
  const [wanBusy, setWanBusy] = useState(false);
  const [episodePromptDraft, setEpisodePromptDraft] = useState([
    "Vertical 9:16 cinematic photoreal horror, a dark small Brazilian apartment during a violent rainstorm at night, slow camera dolly down a narrow corridor toward a bright digital clock with clearly visible seven-segment digits 03:17, a smartphone vibrates alone on a table, cold blue lightning, realistic wet window reflections, no other readable text, no subtitles.",
    "Vertical 9:16 cinematic horror, Lara, a young Brazilian woman with shoulder-length dark brown hair wearing a red cardigan, wakes in the dim bedroom and sees her smartphone ringing, close-up of the screen with an incoming call from her own contact, screen text indistinct, storm light, no subtitles.",
    "Vertical 9:16 cinematic horror, Lara, the same young Brazilian woman with shoulder-length dark brown hair and the red cardigan from the previous scene, answers the phone with trembling hands, tight close-up on her worried face and the phone, rain and static atmosphere, warm bedside lamp fighting cold blue shadows, no visible text, no subtitles.",
    "Vertical 9:16 cinematic horror close-up, Lara, the same woman with shoulder-length dark brown hair and red cardigan, listens to a whisper through the phone, her eyes shift toward the apartment door at the end of the corridor, tense shallow depth of field, no subtitles.",
    "Vertical 9:16 cinematic horror, three violent knocks shake the closed apartment door, camera jolts subtly, Lara, the same young woman with shoulder-length dark brown hair and red cardigan, stands frozen in the deep background, lightning flashes through the corridor, dramatic shadows, no subtitles.",
    "Vertical 9:16 cinematic horror close-up, Lara, the same young woman with shoulder-length dark brown hair and red cardigan, whispers in fear while staring at the apartment door, pale face, trembling phone in foreground, slow camera push, no subtitles.",
    "Vertical 9:16 cinematic horror, view of the apartment door from inside, the peephole is dark and a human silhouette matching Lara, the same young woman with shoulder-length dark brown hair and red cardigan, stands motionless outside, a second shadow appears behind the frosted glass, lightning, no subtitles.",
    "Vertical 9:16 cinematic horror finale, Lara, the same young woman with shoulder-length dark brown hair and red cardigan, recoils as the locked apartment door handle turns by itself, a silhouette identical to Lara appears through the narrow gap, abrupt cut to total black at the end, ominous impact feeling, no text, no subtitles.",
  ].join("\n"));
  const [episodeRun, setEpisodeRun] = useState(false);
  const [playheadFrame, setPlayheadFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [importNotice, setImportNotice] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
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
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível conectar à API local.");
    }
  }, [project]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!embedded) return;
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
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao salvar projeto.");
    }
  }, []);

  const selected = useMemo(
    () => project?.timeline.tracks.flatMap((track) => track.clips).find((clip) => clip.id === selectedClip),
    [project, selectedClip],
  );
  const fps = project?.timeline.fps ?? 24;
  const projectLength = project ? Math.max(fps * 15, ...project.timeline.tracks.flatMap((track) => track.clips.map((clip) => clip.start_frame + clip.duration_frames))) : fps * 15;
  const videoClips = project?.timeline.tracks.filter((track) => track.kind === "video").flatMap((track) => track.clips) ?? [];
  const activeVideoClip = project ? (clipAtFrame(project.timeline, playheadFrame, "video") ??
    (selected?.kind === "video" ? selected : undefined)) : undefined;

  useEffect(() => {
    videoRef.current?.pause();
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
        name: "Cena Wan " + job.id.replace("scene_", ""),
        frames: job.frames!, fps: job.fps!,
      })));
    if (!videos.length) return;
    const fresh = await request<Project>("/api/projects/" + targetProjectId);
    let timeline = fresh.timeline;
    for (const video of videos) timeline = addWanVideoClip(timeline, video);
    if (timeline === fresh.timeline) return;
    const updated = await request<Project>("/api/projects/" + targetProjectId, {
      method: "PUT",
      body: JSON.stringify({ title: fresh.title, summary: fresh.summary, timeline }),
    });
    setProjects((current) => current.map((item) => item.id === targetProjectId ? updated : item));
    setProject((current) => current?.id === targetProjectId ? updated : current);
    const last = timeline.tracks.find((track) => track.kind === "video")?.clips.at(-1);
    if (last) {
      videoRef.current?.pause();
      setPlaying(false);
      setSelectedClip(last.id);
      setPlayheadFrame(last.start_frame);
      setImportNotice("Cena Wan adicionada à timeline. Use ▶ para reproduzir.");
    }
  }, []);

  useEffect(() => {
    if (!embedded || !project?.id) return;
    let active = true;
    void centralRequest<MotionRun[]>("/api/motion/runs")
      .then((runs) => active ? syncCompletedVideos(runs, project.id) : undefined)
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Não foi possível recuperar as cenas Wan.");
      });
    return () => { active = false; };
  }, [embedded, project?.id, syncCompletedVideos]);

  function seekTo(frame: number) {
    const next = Math.max(0, Math.min(projectLength, Math.floor(frame)));
    videoRef.current?.pause();
    setPlaying(false);
    setPlayheadFrame(next);
    if (!project) return;
    const clip = clipAtFrame(project.timeline, next, "video");
    if (clip) {
      setSelectedClip(clip.id);
      if (clip.id === activeVideoClip?.id && videoRef.current) {
        videoRef.current.currentTime = (next - clip.start_frame) / fps;
      }
    }
  }

  async function togglePlayback() {
    const player = videoRef.current;
    if (!player || !activeVideoClip) return;
    if (!player.paused) {
      player.pause();
      setPlaying(false);
      return;
    }
    try {
      if (player.currentTime >= player.duration - 0.1) player.currentTime = 0;
      await player.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
      setError("O navegador não conseguiu reproduzir o MP4. Confira a autorização de pasta e o arquivo.");
    }
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

  async function renderWanScene() {
    if (!project || !scenePrompt.trim() || wanBusy) return;
    setWanBusy(true);
    setEpisodeRun(false);
    setWanRun(null);
    try {
      const run = await centralRequest<MotionRun>("/api/motion/wan/scenes", {
        method: "POST",
        body: JSON.stringify({
          project_id: project.id,
          episode: episodeNumber,
          scene: sceneNumber,
          prompt: scenePrompt.trim(),
          frames: 81,
          fps: 16,
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

  async function renderWanEpisode() {
    if (!project || wanBusy) return;
    const prompts = episodePromptDraft.split(/\r?\n/).map((prompt) => prompt.trim()).filter(Boolean);
    if (prompts.length !== 8) {
      setError("Informe exatamente oito direções, uma por linha, para gerar o episódio de 60 s.");
      return;
    }
    setWanBusy(true);
    setEpisodeRun(true);
    setWanRun(null);
    try {
      const run = await centralRequest<MotionRun>("/api/motion/wan/episodes", {
        method: "POST",
        body: JSON.stringify({ project_id: project.id, episode: episodeNumber, scene_prompts: prompts, dialogue: episodeDialogue }),
      });
      setWanRun(run);
      setError("");
      void refreshWanRun(run.id, project.id);
    } catch (reason) {
      setWanBusy(false);
      setError(reason instanceof Error ? reason.message : "Não foi possível iniciar o episódio Wan.");
    }
  }

  async function cancelWanRun() {
    if (!wanRun) return;
    try {
      const run = await centralRequest<MotionRun>(`/api/motion/runs/${wanRun.id}/cancel`, {
        method: "POST",
        body: "{}",
      });
      setWanRun(run);
      setWanBusy(run.state === "running");
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível cancelar a renderização.");
    }
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

  function setTextStyle(patch: Record<string, string | number>) {
    if (!project || !selected || selected.kind !== "text") return;
    const tracks = project.timeline.tracks.map((track) => ({
      ...track,
      clips: track.clips.map((clip) => clip.id === selected.id ? { ...clip, style: { ...clip.style, ...patch } } : clip),
    }));
    void persist({ ...project, timeline: { ...project.timeline, tracks } });
  }

  function setGrapheme(index: number, patch: Record<string, string>) {
    if (!project || !selected) return;
    void persist({ ...project, timeline: updateGraphemeStyle(project.timeline, selected.id, index, patch) });
  }

  return (
    <main className="studio" data-theme={theme}>
      <header className="topbar">
        <a className="brand" href="#" aria-label="AI Motion Studio início"><span className="brand-mark">M</span><span>AI MOTION <b>STUDIO</b><small>LOCAL CREATIVE SUITE</small></span></a>
        <div className="project-switch"><span>PROJETO</span><select aria-label="Projeto ativo" value={project?.id ?? ""} onChange={(event) => setProject(projects.find((item) => item.id === event.target.value) ?? null)}><option value="">Selecione projeto</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select><button className="icon-button" onClick={() => void createProject()} aria-label="Criar novo projeto">＋</button></div>
        <div className="top-actions"><span className={saved ? "save-status" : "save-status pending"}><i />{saved ? "SALVO" : "SALVANDO"}</span><button className="export-button" disabled>EXPORTAR <span>↗</span></button></div>
      </header>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")} aria-label="Fechar erro">×</button></div>}
      <section className="workspace">
        <aside className="library panel">
          <div className="panel-heading"><span>01 / BIBLIOTECA</span><button className="quiet-button" aria-label="Atualizar capacidades" onClick={() => void load()}>↻</button></div>
          <div className="library-tabs"><button className="active">MÍDIA</button><button disabled>TEXTO</button><button disabled>EFEITOS</button></div>
          <button className="media-import" disabled><span>＋</span><b>IMPORTAR MÍDIA</b><small>Vídeo, imagem ou áudio</small></button>
          <div className="section-label">MOTORES LOCAIS</div>
          <div className="engine-row"><span className="engine-icon">W</span><span><b>ComfyUI / Wan 2.1</b><small>{wanConfigStatus}</small></span><i className={`dot ${wanConfigSaved ? "online" : ""}`} /></div>
          <div className="engine-row"><span className="engine-icon">F</span><span><b>Montagem local</b><small>PyAV e H.264 no runtime instalado</small></span><i className="dot online" /></div>
          <div className="engine-row"><span className="engine-icon">R</span><span><b>Remotion</b><small>Player configurado</small></span><i className="dot online" /></div>
          <div className="notice"><b>Produção automática</b><p>O Studio inicia os motores locais e gera vídeo, voz pt-BR, efeitos, legendas e montagem final.</p></div>
        </aside>
        <section className="center-column">
          <div className="preview-panel panel">
            <div className="panel-heading"><span>02 / MONITOR</span><span className="resolution">{project?.timeline.width ?? 1280} × {project?.timeline.height ?? 720} · {fps} FPS</span></div>
            <Preview
              timeline={project?.timeline ?? initialTimeline()}
              frame={playheadFrame}
              videoClip={activeVideoClip} videoRef={videoRef}
              onVideoTime={(seconds) => {
                if (activeVideoClip) setPlayheadFrame(Math.min(projectLength, activeVideoClip.start_frame + Math.round(seconds * fps)));
              }}
              onVideoEnded={() => { setPlaying(false); if (activeVideoClip) setPlayheadFrame(activeVideoClip.start_frame + activeVideoClip.duration_frames - 1); }}
              onVideoReady={() => {
                if (videoRef.current && activeVideoClip) {
                  videoRef.current.currentTime = Math.max(0, (playheadFrame - activeVideoClip.start_frame) / fps);
                }
              }}
            />
            <div className="transport">
              <button aria-label="Voltar ao início" onClick={() => seekTo(0)}>|◀</button>
              <button className="transport-play" aria-label={playing ? "Pausar prévia" : "Reproduzir prévia"}
                disabled={!activeVideoClip} onClick={() => void togglePlayback()}>{playing ? "Ⅱ" : "▶"}</button>
              <button aria-label="Próxima cena" disabled={!videoClips.length}
                onClick={() => seekTo(videoClips.find((clip) => clip.start_frame > playheadFrame)?.start_frame ?? 0)}>▶|</button>
              <span>{timecode(playheadFrame, fps)} <b>/</b> {timecode(projectLength, fps)}</span>
            </div>
            <input className="timeline-scrubber" aria-label="Posição da prévia na timeline" type="range"
              min={0} max={projectLength} step={1} value={Math.min(playheadFrame, projectLength)}
              onChange={(event) => seekTo(Number(event.target.value))} disabled={!project} />
            {activeVideoClip && wanVideoPreviewUrl(activeVideoClip.style.motion_run_id, activeVideoClip.style.motion_artifact_id) && (
              <div className="render-meta">
                <span>{activeVideoClip.name} · Vídeo Wan</span>
                <a href={wanVideoPreviewUrl(activeVideoClip.style.motion_run_id, activeVideoClip.style.motion_artifact_id)!.replace(/\/preview$/, "")}>
                  Baixar MP4
                </a>
              </div>
            )}
            {importNotice && <p className="preview-import-notice" role="status">{importNotice}</p>}
          </div>
          <div className="timeline-panel panel">
            <div className="timeline-toolbar"><div className="panel-heading"><span>03 / TIMELINE</span><span className="timeline-hint">TEMPO EM FRAMES · {project?.timeline.fps ?? 24} FPS</span></div><div className="timeline-tools"><button onClick={addTitle} disabled={!project}>＋ TÍTULO</button><button disabled>MARCADOR</button><button disabled title="Atalho: Ctrl+Z">↶</button><button disabled title="Atalho: Ctrl+Shift+Z">↷</button></div></div>
            <div className="ruler">{Array.from({ length: 6 }, (_, index) => <span key={index}>{clock(Math.round(index * projectLength / (5 * fps)))}</span>)}</div>
            <div className="tracks">{project?.timeline.tracks.map((track) => (
              <div className="track-row" key={track.id}><div className="track-label"><b>{track.name}</b><button aria-label={`Bloquear trilha ${track.name}`} disabled>⌑</button></div><div className="track-lane">{track.clips.map((clip) => {
                const left = clip.start_frame / projectLength * 100;
                const width = Math.max(3, clip.duration_frames / projectLength * 100);
                const isSelected = selectedClip === clip.id;
                const className = `clip clip-${clip.kind} ${isSelected ? "selected" : ""}`;
                const style = { left: `${left}%`, width: `${width}%` };
                return <button key={clip.id} className={className} style={style} onClick={() => { seekTo(clip.start_frame); setSelectedClip(clip.id); }} title={clip.name}><span>{clip.kind === "text" ? "T " : "◧ "}{clip.name}</span></button>;
              })}</div></div>
            )) ?? <div className="empty-project"><b>Crie um projeto para começar.</b><button onClick={() => void createProject()}>NOVO PROJETO</button></div>}</div>
          </div>
        </section>
        <aside className="properties panel">
          <div className="panel-heading"><span>04 / PROPRIEDADES</span></div>
          {!project ? <div className="properties-empty"><span>◈</span><b>Nenhum projeto aberto</b><button onClick={() => void createProject()}>CRIAR PROJETO</button></div> :
            <div className="property-content">
              <label className="field-label" htmlFor="project-title">NOME DO PROJETO</label><input id="project-title" value={project.title} onChange={(event) => void persist({ ...project, title: event.target.value })} />
              <div className="property-divider" />
              {selected?.kind === "text" ? <>
                <div className="selected-label"><span className="tag">TEXTO</span><b>{selected.name}</b></div>
                <label className="field-label" htmlFor="title-content">CONTEÚDO</label><textarea id="title-content" value={selected.text ?? ""} onChange={(event) => {
                  const text = event.target.value;
                  const graphemes = typeof Intl.Segmenter === "function" ? Array.from(new Intl.Segmenter("pt-BR", { granularity: "grapheme" }).segment(text), (part) => part.segment) : Array.from(text);
                  const tracks = project.timeline.tracks.map((track) => ({ ...track, clips: track.clips.map((clip) => clip.id === selected.id ? { ...clip, name: text.slice(0, 48), text, style: { ...clip.style, graphemes: graphemes.map((value) => ({ value, color: clip.style.color ?? "#f8fafc", animation: clip.style.animation ?? "fade" })) } } : clip) }));
                  void persist({ ...project, timeline: { ...project.timeline, tracks } });
                }} />
                <div className="property-grid"><div><label className="field-label" htmlFor="title-color">COR</label><input id="title-color" type="color" value={String(selected.style.color ?? "#f8fafc")} onChange={(event) => setTextStyle({ color: event.target.value })} /></div><div><label className="field-label" htmlFor="title-size">TAMANHO</label><input id="title-size" type="number" min="12" max="240" value={Number(selected.style.font_size ?? 72)} onChange={(event) => setTextStyle({ font_size: Number(event.target.value) })} /></div></div>
                <label className="field-label" htmlFor="title-motion">ANIMAÇÃO</label><select id="title-motion" value={String(selected.style.animation ?? "fade")} onChange={(event) => setTextStyle({ animation: event.target.value })}><option value="fade">Fade</option><option value="spring">Spring</option><option value="typewriter">Typewriter</option><option value="glitch">Glitch</option></select>
                <div className="property-divider" /><div className="field-label">ESTILO POR GRAFEMA</div><div className="grapheme-list">{(selected.style.graphemes ?? []).map((item: any, index: number) => <div className="grapheme-row" key={`${index}-${item.value}`}><code>{item.value === " " ? "␠" : item.value}</code><input aria-label={`Cor do grafema ${item.value || index}`} type="color" value={item.color ?? selected.style.color ?? "#f8fafc"} onChange={(event) => setGrapheme(index, { color: event.target.value })} /><select aria-label={`Animação do grafema ${item.value || index}`} value={item.animation ?? "fade"} onChange={(event) => setGrapheme(index, { animation: event.target.value })}><option value="fade">Fade</option><option value="spring">Spring</option><option value="glitch">Glitch</option></select></div>)}</div>
              </> : <>
                <div className="selected-label"><span className="tag">TIMELINE</span><b>{selected?.name ?? "Composição"}</b></div><div className="section-label">DIREÇÃO DE MOTION</div><p className="helper-text">Adicione um título para editar cor, animação e estilo de cada grafema.</p><label className="field-label" htmlFor="title-draft">NOVO TÍTULO</label><textarea id="title-draft" value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} /><button className="primary-wide" onClick={addTitle}>＋ ADICIONAR À TIMELINE</button>
              </>}
              <div className="property-divider" /><div className="section-label">PROJETO</div><div className="project-meta"><span>FORMATO</span><b>{project.timeline.width} × {project.timeline.height}</b><span>FRAME RATE</span><b>{project.timeline.fps} FPS</b></div>
              <div className="property-divider" />
              <div className="section-label">PRODUÇÃO WAN · TERROR</div>
              <p className="helper-text">O Studio sobe ComfyUI/Wan, voz pt-BR, efeitos, legendas e montagem H.264 sem abrir outros aplicativos.</p>
              <p className="helper-text" role="status">{wanConfigStatus}</p>
              <div className="property-grid">
                <div><label className="field-label" htmlFor="episode-number">EPISÓDIO</label><input id="episode-number" type="number" min="1" max="99" value={episodeNumber} onChange={(event) => setEpisodeNumber(Number(event.target.value))} /></div>
                <div><label className="field-label" htmlFor="scene-number">CENA</label><input id="scene-number" type="number" min="1" max="64" value={sceneNumber} onChange={(event) => setSceneNumber(Number(event.target.value))} /></div>
              </div>
              <label className="field-label" htmlFor="wan-scene-prompt">DIREÇÃO DA CENA</label>
              <textarea id="wan-scene-prompt" value={scenePrompt} maxLength={1024} onChange={(event) => setScenePrompt(event.target.value)} />
              <button className="primary-wide" onClick={() => void renderWanScene()} disabled={!embedded || !wanConfigSaved || wanBusy || !project || !scenePrompt.trim()}>{wanBusy ? "RENDERIZANDO CENA…" : "GERAR CENA WAN · 5 S"}</button>
              <div className="property-divider" />
              <label className="field-label" htmlFor="wan-episode-prompts">ROTEIRO VISUAL · 8 CENAS, UMA DIREÇÃO POR LINHA</label>
              <textarea id="wan-episode-prompts" value={episodePromptDraft} maxLength={8192} rows={10} onChange={(event) => setEpisodePromptDraft(event.target.value)} />
              <p className="helper-text">7 cenas de 121 quadros + 1 de 113 = 60 s exatos. Narração pt-BR, efeitos sonoros e legendas entram automaticamente no MP4 final.</p>
              <button className="primary-wide" onClick={() => void renderWanEpisode()} disabled={!embedded || !wanConfigSaved || wanBusy || !project}>{wanBusy && episodeRun ? "RENDERIZANDO EPISÓDIO…" : "GERAR 8 CENAS WAN · 60 S"}</button>
              {wanRun && <div className="helper-text" role="status">
                <b>{wanRun.state === "completed" ? (episodeRun ? "Episódio finalizado: 60 s, narração e legendas incluídas." : "Cena pronta.") : wanRun.state === "failed" ? "A renderização falhou." : `${episodeRun ? `Fila do episódio · ${wanRun.jobs.filter((job) => job.state === "completed").length}/9 etapas` : "Fila Wan"}: ${wanRun.state}.`}</b>
                {wanRun.error && <span> {wanRun.error}</span>}
                {wanRun.jobs.filter((job) => job.artifact).map((job) => <a key={job.artifact!.id} href={`/api/motion/runs/${wanRun.id}/artifacts/${job.artifact!.id}`}> Baixar {job.id === "assemble" ? "episódio final MP4" : job.id.replace("scene_", "cena ")}</a>)}
                {(wanRun.state === "queued" || wanRun.state === "running") && <button className="quiet-button" onClick={() => void cancelWanRun()}>CANCELAR</button>}
              </div>}
            </div>}
        </aside>
      </section>
      <footer className="statusbar"><span><i className={capabilities?.comfyui.status === "available" ? "dot online" : "dot"} /> COMFYUI {capabilities?.comfyui.status === "available" ? "CONECTADO" : "DESCONECTADO"}</span><span>ARMAZENAMENTO LOCAL · SQLITE</span><span>AI MOTION STUDIO 0.1.0</span></footer>
    </main>
  );
}
