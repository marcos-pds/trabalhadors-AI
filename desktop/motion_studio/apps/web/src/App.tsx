import { useCallback, useEffect, useMemo, useState } from "react";

import { addTextClip, makeId, updateGraphemeStyle } from "./timeline.mjs";

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

function clipAtFrame(timeline: Timeline, frame: number): Clip | undefined {
  return timeline.tracks.flatMap((track) => track.clips).find((clip) => frame >= clip.start_frame && frame < clip.start_frame + clip.duration_frames);
}

function Preview({ timeline }: { timeline: Timeline }) {
  const clip = clipAtFrame(timeline, Math.floor(timeline.fps * 1.1));
  const words = clip?.text?.split(" ") ?? [];
  return (
    <div className="preview-frame">
      <div className="preview-grid" />
      {clip?.kind === "text" ? (
        <div className="preview-title" style={{ color: String(clip.style.color ?? "#f8fafc") }}>
          {words.map((word, index) => <span key={`${word}-${index}`} style={{ color: clip.style.word_colors?.[index] ?? clip.style.color }}>{word} </span>)}
        </div>
      ) : <div className="preview-empty"><span className="play-glyph">▶</span><strong>PREVIEW DA COMPOSIÇÃO</strong><small>Adicione um título à timeline para visualizar o motion.</small></div>}
      <span className="preview-time">00:00:01:02</span>
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
  const projectLength = project ? Math.max(12, ...project.timeline.tracks.flatMap((track) => track.clips.map((clip) => clip.start_frame + clip.duration_frames))) : 12;

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
          <div className="engine-row"><span className="engine-icon">W</span><span><b>ComfyUI / Wan 2.1</b><small>{capabilities?.wan21_t2v_13b.installed ? "Modelo encontrado" : "Modelo não localizado"}</small></span><i className={`dot ${capabilities?.comfyui.status === "available" ? "online" : ""}`} /></div>
          <div className="engine-row"><span className="engine-icon">F</span><span><b>FFmpeg</b><small>{capabilities?.ffmpeg.installed ? "Instalado" : "Não encontrado"}</small></span><i className={`dot ${capabilities?.ffmpeg.installed ? "online" : ""}`} /></div>
          <div className="engine-row"><span className="engine-icon">R</span><span><b>Remotion</b><small>Player configurado</small></span><i className="dot online" /></div>
          <div className="notice"><b>Geração Wan indisponível</b><p>O serviço ComfyUI precisa estar iniciado localmente. O Studio não simula resultados.</p></div>
        </aside>
        <section className="center-column">
          <div className="preview-panel panel">
            <div className="panel-heading"><span>02 / MONITOR</span><span className="resolution">1280 × 720 · 24 FPS</span></div>
            <Preview timeline={project?.timeline ?? initialTimeline()} />
            <div className="transport"><button aria-label="Voltar ao início">|◀</button><button className="transport-play" aria-label="Reproduzir prévia" disabled>▶</button><button aria-label="Avançar">▶|</button><span>00:00:00:00 <b>/</b> 00:00:15:00</span><button className="quiet-button" aria-label="Ajustar monitor">⛶</button></div>
          </div>
          <div className="timeline-panel panel">
            <div className="timeline-toolbar"><div className="panel-heading"><span>03 / TIMELINE</span><span className="timeline-hint">TEMPO EM FRAMES · {project?.timeline.fps ?? 24} FPS</span></div><div className="timeline-tools"><button onClick={addTitle} disabled={!project}>＋ TÍTULO</button><button disabled>MARCADOR</button><button disabled title="Atalho: Ctrl+Z">↶</button><button disabled title="Atalho: Ctrl+Shift+Z">↷</button></div></div>
            <div className="ruler"><span>00:00</span><span>00:03</span><span>00:06</span><span>00:09</span><span>00:12</span><span>00:15</span></div>
            <div className="tracks">{project?.timeline.tracks.map((track) => (
              <div className="track-row" key={track.id}><div className="track-label"><b>{track.name}</b><button aria-label={`Bloquear trilha ${track.name}`} disabled>⌑</button></div><div className="track-lane">{track.clips.map((clip) => {
                const left = clip.start_frame / projectLength * 100;
                const width = Math.max(3, clip.duration_frames / projectLength * 100);
                const isSelected = selectedClip === clip.id;
                const className = `clip clip-${clip.kind} ${isSelected ? "selected" : ""}`;
                const style = { left: `${left}%`, width: `${width}%` };
                return <button key={clip.id} className={className} style={style} onClick={() => setSelectedClip(clip.id)} title={clip.name}><span>{clip.kind === "text" ? "T " : "◧ "}{clip.name}</span></button>;
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
            </div>}
        </aside>
      </section>
      <footer className="statusbar"><span><i className={capabilities?.comfyui.status === "available" ? "dot online" : "dot"} /> COMFYUI {capabilities?.comfyui.status === "available" ? "CONECTADO" : "DESCONECTADO"}</span><span>ARMAZENAMENTO LOCAL · SQLITE</span><span>AI MOTION STUDIO 0.1.0</span></footer>
    </main>
  );
}
