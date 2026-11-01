export function mediaManifest({mode,source,output,composition='Intro',language='pt'}) {
  const adapter=mode==='transcribe'?'whisperx':mode==='compose'?'remotion':'ffmpeg'
  const stage={ffmpeg:'encode',whisperx:'transcribe',remotion:'compose'}[adapter]
  const inputKind=mode==='compose'?'composition':source.toLowerCase().endsWith('.wav')?'audio':'video'
  const outputKind=mode==='transcribe'?'captions':mode==='audio'?'audio':'video'
  const params=mode==='transcribe'?{language,model:'tiny'}:mode==='compose'?{composition,fps:30}:{profile:mode==='audio'?'pcm_s16le':'h264'}
  return {schema_version:1,project_id:'motion',artifacts:[
    {id:'source',kind:inputKind,path:source,provenance:{source:'local'}},
    {id:'result',kind:outputKind,path:output,provenance:{source:'planned',job_id:'render',inputs:['source']}}],
    jobs:[{id:'render',adapter,stage,inputs:['source'],outputs:['result'],params}]}
}

export const motionStates={queued:'Na fila',running:'Em execução',completed:'Concluída',failed:'Falhou',cancelled:'Cancelada',interrupted:'Interrompida · revisão necessária'}
