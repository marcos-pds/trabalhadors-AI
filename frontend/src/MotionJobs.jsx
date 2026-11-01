import {useEffect,useRef,useState} from 'react'
import {mediaManifest,motionStates} from './motionJobs.mjs'

const input='mt-1 w-full min-w-0 rounded-xl border border-white/15 bg-panel px-3 py-2 text-xs text-copy'
const button='rounded-xl border border-white/15 px-3 py-2 text-xs disabled:opacity-40'

export default function MotionJobs({api,onToolsSaved}) {
  const [form,setForm]=useState({mode:'video',directory:'',source:'clip.mp4',output:'renders/final.mp4',composition:'Intro',language:'pt'})
  const [custom,setCustom]=useState(null),[prepared,setPrepared]=useState(null)
  const [runs,setRuns]=useState([]),[error,setError]=useState(''),[notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false),[revision,setRevision]=useState(0)
  const [tools,setTools]=useState(null),[toolsOpen,setToolsOpen]=useState(false)
  const generation=useRef(0),lock=useRef(false)
  const change=(key,value)=>{generation.current++;setPrepared(null);setCustom(null);setForm(old=>({...old,[key]:value}))}
  useEffect(()=>{
    let active=true,timer
    async function poll(){
      try {
        const result=await api('/motion/runs')
        if(!active)return
        setRuns(result)
        if(result.some(r=>['queued','running'].includes(r.state)))timer=setTimeout(poll,2000)
      }catch(e){if(active)setError(e.message)}
    }
    poll()
    return()=>{active=false;clearTimeout(timer)}
  },[api,revision])
  async function action(callback){
    if(lock.current)return
    lock.current=true;setBusy(true);setError('');setNotice('')
    try{await callback()}catch(e){setError(e.message)}finally{lock.current=false;setBusy(false)}
  }
  async function inspect(){
    const version=generation.current
    const body={manifest:custom||mediaManifest(form),directory:form.directory,request_id:crypto.randomUUID()}
    const plan=await api('/motion/plan','POST',body)
    if(version===generation.current)setPrepared({body,plan})
  }
  async function enqueue(){
    if(!prepared?.plan.executable)return
    await api('/motion/runs','POST',prepared.body)
    setPrepared(null);setNotice('Produção adicionada à fila.');setRevision(r=>r+1)
  }
  async function configure(){
    if(toolsOpen){setToolsOpen(false);return}
    const result=await api('/motion/tools')
    setTools(result);setToolsOpen(true)
  }
  async function saveTools(){
    const executables=Object.fromEntries(Object.entries(tools.executables||{}).filter(([,v])=>v.trim()))
    await api('/motion/tools','POST',{executables,comfy_root:tools.comfy_root||null,comfy_endpoint:tools.comfy_endpoint||null})
    generation.current++;setPrepared(null);setNotice('Ferramentas configuradas. Revise o plano antes de executar.');onToolsSaved?.()
  }
  async function importPlan(event){
    const file=event.target.files?.[0]
    if(!file)return
    try {
      if(file.size>256*1024)throw new Error('O plano deve ter até 256 KB.')
      const value=JSON.parse(await file.text())
      generation.current++;setCustom(value);setPrepared(null);setNotice('Plano importado; confira as etapas antes de executar.')
    }catch(e){setError(e.message)}
    event.target.value=''
  }
  return <section aria-label="Produção de mídia" className="mt-5 border-t border-white/10 pt-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-semibold">Produzir mídia</h4>
      <button type="button" className={button} disabled={busy} onClick={()=>action(configure)}>Configurar ferramentas</button></div>
    <p className="mt-2 text-xs leading-5 text-muted">Use arquivos da pasta autorizada em Computador. A produção executa ferramentas locais; composições Remotion executam o código do projeto.</p>
    {toolsOpen&&tools&&<div className="my-3 space-y-2 rounded-xl border border-white/10 p-3">
      {['ffmpeg','remotion','whisperx'].map(name=><label key={name} className="block text-xs">Caminho de {name}
        <input className={input} value={tools.executables?.[name]||''} onChange={e=>setTools({...tools,executables:{...tools.executables,[name]:e.target.value}})}/></label>)}
      <p className="text-[11px] text-muted">Remotion aceita o arquivo JS do CLI. Campo vazio usa o executável disponível no servidor.</p>
      <button type="button" className={button} disabled={busy} onClick={()=>action(saveTools)}>Salvar ferramentas</button>
    </div>}
    <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
      <label className="text-xs">Operação<select className={input} value={form.mode} onChange={e=>{
        const mode=e.target.value;change('mode',mode)
        setForm(old=>({...old,mode,source:mode==='compose'?'scene.tsx':'clip.mp4',output:mode==='audio'?'renders/final.wav':mode==='transcribe'?'renders/clip.json':'renders/final.mp4'}))
      }}><option value="video">Codificar vídeo · FFmpeg</option><option value="audio">Extrair áudio · FFmpeg</option><option value="transcribe">Transcrever · WhisperX</option><option value="compose">Renderizar composição · Remotion</option></select></label>
      <label className="text-xs">Subpasta do projeto<input className={input} value={form.directory} placeholder="Pasta autorizada" onChange={e=>change('directory',e.target.value)}/></label>
      <label className="text-xs">Arquivo de entrada<input className={input} value={form.source} onChange={e=>change('source',e.target.value)}/></label>
      <label className="text-xs">Salvar como<input className={input} value={form.output} onChange={e=>change('output',e.target.value)}/></label>
      {form.mode==='compose'&&<label className="text-xs">Composição<input className={input} value={form.composition} onChange={e=>change('composition',e.target.value)}/></label>}
      {form.mode==='transcribe'&&<label className="text-xs">Idioma<select className={input} value={form.language} onChange={e=>change('language',e.target.value)}>
        {[['pt','Português'],['en','Inglês'],['es','Espanhol'],['fr','Francês'],['de','Alemão'],['it','Italiano'],['ja','Japonês']].map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>}
    </div>
    <div className="mt-3 flex flex-wrap gap-2"><button type="button" className={button} disabled={busy} onClick={()=>action(inspect)}>Revisar produção</button>
      <label className={button+' cursor-pointer'}>Importar plano<input type="file" accept="application/json,.json" className="sr-only" onChange={importPlan}/></label>
      <button type="button" className={button} disabled={busy} onClick={()=>setRevision(r=>r+1)}>Atualizar fila</button></div>
    {custom&&<p className="mt-2 text-xs text-muted">Usando plano importado. Editar os campos retorna ao formulário.</p>}
    {prepared&&<div className="mt-3 rounded-xl border border-white/15 p-3 text-xs">
      {prepared.body.manifest.artifacts.map(a=><p key={a.id} className="break-words text-muted">{a.provenance.source==='local'?'Entrada':'Saída'}: {a.path}</p>)}
      {prepared.plan.jobs.map(j=><p key={j.id}>{j.id} · {j.adapter} · {j.status==='planned'?'Pronto':j.status==='unavailable'?'Ferramenta indisponível':'Dependência indisponível'}</p>)}
      <p className="mt-2 text-muted">Arquivos existentes não serão sobrescritos.</p>
      <button type="button" className={button+' mt-3'} disabled={busy||!prepared.plan.executable} onClick={()=>action(enqueue)}>Executar produção</button></div>}
    {notice&&<p role="status" className="mt-3 text-xs text-muted">{notice}</p>}
    {error&&<p role="alert" className="mt-3 break-words text-xs text-rose-500">{error}</p>}
    <div className="mt-4 space-y-3">{!runs.length?<p className="text-xs text-muted">Nenhuma produção nesta conta.</p>:runs.map(run=><article key={run.id} className="rounded-xl border border-white/10 p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>{motionStates[run.state]||run.state}</strong><span>{run.jobs.filter(j=>j.state==='completed').length}/{run.jobs.length} etapas</span></div>
      <p className="mt-1 text-[10px] text-muted">{new Date(run.created_at).toLocaleString('pt-BR')}</p>
      {run.error&&<p className="mt-2 break-words text-rose-500">{run.error}</p>}
      {run.jobs.map(job=><div key={job.id} className="mt-2 flex flex-wrap justify-between gap-2"><span>{job.id} · {job.adapter} · {motionStates[job.state]||job.state}</span>
        {job.artifact&&job.state==='completed'&&<a download className="underline" href={'/api/motion/runs/'+encodeURIComponent(run.id)+'/artifacts/'+encodeURIComponent(job.artifact.id)}>Baixar {job.artifact.kind==='captions'?'legendas':job.artifact.kind==='audio'?'áudio':'vídeo'}</a>}</div>)}
      {['queued','running'].includes(run.state)&&<button type="button" className={button+' mt-3'} disabled={busy||Boolean(run.cancel_requested)} onClick={()=>action(async()=>{await api('/motion/runs/'+run.id+'/cancel','POST',{});setRevision(r=>r+1)})}>{run.cancel_requested?'Cancelamento solicitado':'Cancelar produção'}</button>}
    </article>)}</div>
  </section>
}
