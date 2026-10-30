# AI Motion Studio — renderizador FFmpeg local (piloto experimental)

Esta fase acrescenta a primeira **execução real possível** do módulo Motion:
codificação de um arquivo MP4/H.264 ou WAV/PCM via FFmpeg local,
exclusivamente em CLI invocado pelo operador. Não é interface gráfica,
não processa Wan/ComfyUI/Remotion/WhisperX e não integra ainda o agendador.

## Uso no Windows em um projeto de testes

1. Instale manualmente uma versão confiável do FFmpeg, verifique
   que o comando ffmpeg está no PATH e mantenha a entrada de vídeo ou
   áudio em pasta isolada criada para este teste. Não use mídia sensível.
2. Crie um arquivo JSON manifest.json com um único job:

```json
{
  "schema_version": 1,
  "project_id": "motion_lab",
  "artifacts": [
    {"id":"src","kind":"video","path":"clip.mp4",
     "provenance":{"source":"local"}},
    {"id":"out","kind":"video","path":"render.mp4",
     "provenance":{"source":"planned","job_id":"encode1","inputs":["src"]}}
  ],
  "jobs": [
    {"id":"encode1","adapter":"ffmpeg","stage":"encode",
     "inputs":["src"],"outputs":["out"],"params":{"profile":"h264"}}
  ]
}
```

3. Na raiz da Central atualizada, rode:

```powershell
.\.venv\Scripts\python.exe -m examples.render_motion_ffmpeg `
  --project 'C:\Projetos\Central-IA\motion-lab' `
  --manifest 'C:\Projetos\Central-IA\motion-lab\manifest.json'
```

4. Confira o job, digite RENDERIZAR, e valide o vídeo com ffprobe
   e reprodução visual. O relatório retorna caminho, bytes e SHA-256;
   não afirma qualidade visual nem presença de áudio correto.

## Barreiras de segurança

- O recurso não foi registrado como ferramenta de IA, rota HTTP ou execução
  automática. Requer confirmação textual de operador no terminal.
- Somente um job com adaptador ffmpeg, perfis h264 ou pcm_s16le, sem shell.
- Entradas até 64 MiB, resultados até 128 MiB e timeout máximo de 180 s.
- Apenas caminhos internos validados e arquivo de saída inexistente.
- Copia entrada para diretório temporário privado; ffmpeg recebe protocolo
  file, saída temporária, argumentos fixos, ambiente sem chaves de API.
- A promoção para o destino usa hard-link exclusivo: nunca sobrescreve
  um arquivo existente. Falha ou timeout não entrega um arquivo como renderizado.
- Esta ferramenta não é sandbox de processos. Executar FFmpeg sobre mídia
  não confiável exige isolamento do SO e administração do operador.
- Testes automatizados usam um processo falso; não demonstram renderização
  real, GPU, qualidade de vídeo, áudio ou instalação do FFmpeg no Windows.

## Próximas fases (issue #19)

Falta o editor React com linha do tempo, efeitos por letra/palavra/frase,
prévia e sugestões de edição; além de um job runner assíncrono com progresso,
cancelamento, isolamento real e integrações testadas com WhisperX, Remotion
e ComfyUI/Wan. O piloto não declara essas capacidades concluídas.
