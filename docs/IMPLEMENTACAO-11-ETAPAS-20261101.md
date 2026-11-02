# Fechamento das 11 etapas — trabalho em andamento

Pedido: concluir a lista preservando a distinção entre implementação, testes controlados e homologação real. Codex permanece excluído dos trabalhadores e do fallback do laboratório. Nenhum arquivo do TaskLab foi corrigido pelo avaliador externo.

## Dependência externa confirmada

O usuário confirmou que não tem acesso à API Anthropic. A execução real do Claude Code não pode ser homologada com as conexões disponíveis. Não substituir por um simulador, outro provedor ou uma assinatura pessoal do CLI sem autorização. Os demais itens continuam sendo trabalhados.

## Entregas verificadas nesta continuação

- Recuperação de prévia após checkpoint: estado do navegador/processos não é confundido com arquivos persistidos. A retomada do TaskLab reiniciou a prévia e voltou a usar a URL real, console, snapshot e Lighthouse desktop/mobile. O projeto maior ainda não foi aprovado.
- Ação tipada `preview start_api`: inicia apenas `main:app` com Uvicorn na `.venv` do cwd autorizado, em loopback e porta livre. Não aceita shell, porta ou módulo arbitrário. Mantém posse por tarefa/workspace, encerra a árvore própria, revalida permissão e fornece logs de falha ao trabalhador. `stop_api` é separado do frontend.
- Motion Studio: fila SQLite persistente, escopo de conta/pasta, revisão antes de executar, idempotência, DAG, hashes de entradas e executáveis, recibos de artefatos, cancelamento e identificação de execução interrompida. Não repete silenciosamente um render interrompido sobre arquivos existentes. As ferramentas são configuradas pela conta local; não se herdam chaves de provedores.
- Interface Motion com formulário de vídeo/áudio, transcrição e composição, importação de plano, configuração de ferramentas, acompanhamento e download autenticado. Teste real no navegador configurou FFmpeg, revisou/executou um render e verificou download HTTP 200 com MP4 válido.
- **FFmpeg 7.1 real**: dois jobs dependentes concluídos; vídeo e áudio decodificados independentemente. Evidência: `evidence/motion-ffmpeg-real-20261101.json`.
- **Remotion 4.0.539 real**: composição de fixture renderizada e decodificada. Ferramentas instaladas em diretório isolado; override local de Zod 4.6.6 eliminou o alerta do audit, e o render funcionou. O comando de diagnóstico de versões alerta que essa versão difere do pin do Remotion; não se afirma compatibilidade universal.
- **WhisperX 3.8.6 real**, CPU/int8/Silero: reconheceu a frase sintética de teste e alinhou 16 palavras. Evidência conjunta: `evidence/motion-remotion-whisperx-real-20261101.json`.

Esses ensaios de mídia usam fixtures declaradas (cena de referência e fala sintetizada), não geração autônoma de uma aplicação nem vídeo Wan. Modelos/cache ficam separados por conta na área de dados do laboratório.

## Critérios ainda abertos

### Integração local de prévia FastAPI e Vite

A prévia Vite iniciada pelo trabalhador recebe `CENTRAL_PREVIEW_API_URL` somente
quando uma API da mesma conta, execução e pasta está rodando. O endereço é
validado como loopback com porta explícita e não é herdado de variáveis do
processo da Central. No `vite.config.js` do projeto gerado, o proxy pode usar
`process.env.CENTRAL_PREVIEW_API_URL` como destino de `/api`. Inicie `start_api`
antes de `start`; se a API iniciar depois, reinicie a prévia frontend. Essa
integração ainda depende de aceitação HTTP e visual do projeto gerado.

1. QA visual com reparo comprovado no projeto maior.
2. Avaliação real mais ampla de pedidos curtos/ambíguos, separada do corpus offline.
3. Subtarefa delegada executada, revisada e integrada na entrega.
4. Concorrência e integração de workspaces demonstradas com modelos reais.
5. Claude bloqueado por credencial externa; ampliar ACP registrado sem executar agentes arbitrários desconhecidos.
6. Recuperação completa de interrupção/conflito na entrega maior.
7. Relevância de memória/RAG e continuidade entre modelos avaliadas com dados e modelos reais.
8. Ciclo autenticado de Skills/plugins/MCP e revogação real.
9. Pausa/cancelamento/retomada por trabalhador sob concorrência e reinício.
10. ComfyUI/Wan, incluindo fila remota própria e artefato real; finalizar integração dos quatro adaptadores.
11. Aceitação independente integral do TaskLab.

## Validação intermediária

Motion: 84 testes aprovados e um ignorado (contratos/fila/API); preview/API/schema/migrações: 67 aprovados. Frontend: 79 testes e build Vite aprovados antes dos últimos ajustes de rótulos. A suíte completa será repetida após consolidar as mudanças. Isso não conclui os critérios acima.

## Referências primárias consultadas

- [FFmpeg CLI](https://ffmpeg.org/ffmpeg.html)
- [Remotion render](https://www.remotion.dev/docs/cli/render)
- [WhisperX: CPU, VAD e alinhamento](https://github.com/m-bain/whisperX)
- [ComfyUI: prompt, fila e histórico](https://docs.comfy.org/development/comfyui-server/comms_routes)
