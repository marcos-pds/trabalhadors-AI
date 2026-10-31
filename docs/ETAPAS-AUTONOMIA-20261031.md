# Auditoria das 11 etapas — 31/10/2026

Implementacao, testes de contrato e homologacao com ferramentas/modelos reais
sao evidencias distintas. Esta matriz nao declara as 11 etapas concluidas.
Os ensaios anteriores continuam registrados, inclusive falhas e intervencoes.

| Etapa | Estado | Evidencia e trabalho restante |
| --- | --- | --- |
| 1. QA visual e autocorrecao | Demonstrado em caso simples | `CICLO-AUTONOMO-20261029.md`: criacao e reparo pela Central com MCP, console e Lighthouse. Ampliar tipos de defeito e aplicar ao projeto full-stack. |
| 2. Pedidos curtos e ambiguidades | Avaliacao offline implementada | `central.context_evaluation` usa resolvedor real, corpus versionado e proveniencia. Nao mede qualidade de inferencia nem sucesso de entrega de um modelo real. |
| 3. Delegacao dinamica | Criacao real demonstrada; execucao integrada pendente | [Contrato e ensaio real sem Codex](DELEGACAO-OBRIGATORIA-20261031.md): subtarefa criada por API/Groq e incluida nas dependencias do revisor. Concluir a execucao da subtarefa no projeto maior. |
| 4. Workspaces e integracao | Implementados com revisao | `isolated_workspaces.py`, `worker_worktrees.py`, testes de isolamento e revisao. Worktree nao e sandbox de sistema operacional. Homologar agentes concorrentes e promocao no ensaio maior. |
| 5. Claude, Gemini CLI, OpenCode, ACP | Parcial: descoberta somente | `external_runtimes.py`: inventario, versao e initialize ACP; streaming, planejador e ferramentas NAO certificados. Nesta maquina os tres CLIs nao foram encontrados e ACP nao esta configurado. API Gemini e diferente de Gemini CLI. |
| 6. Recuperacao de falhas/conflitos | Parcial | Checkpoints, failover, reparo de entrega e conflitos com revisao existem. Ainda falta demonstrar interrupcao, retomada e conflitos em um projeto maior com modelos reais. |
| 7. Memoria/RAG e troca de modelos | Parcial | Memoria por escopo, recuperacao lexical/semantica e fallback existentes. Avaliar relevancia e continuidade com corpus e modelos reais; testes com embeddings simulados nao comprovam qualidade. |
| 8. Skills, plugins e MCP | Parcial | Catalogo, importacao, versoes, selecao e gateway existem. MCP de navegador foi utilizado no ensaio simples. Homologar ciclo completo de cada integracao com autenticacao e revogacao reais. |
| 9. Monitoramento e controles | Implementados; homologacao integrada pendente | `WorkerControls.jsx`, `ConversationActivity.jsx`, `worker_controls.py` e testes. Validar pausa/cancelamento por trabalhador sob concorrencia e reinicio real. |
| 10. AI Motion Studio | Parcial: contratos e diagnostico | Contratos de artefatos e DAG, planos tipados e endpoint de capacidades existentes. Interface de diagnostico adicionada nesta rodada; fila, execucao de midia, acompanhamento e artefatos finais continuam pendentes. |
| 11. Projeto maior integral | Pendente | `ACEITACAO-FULLSTACK-INDEPENDENTE.md` e verificador independente estao implementados. Nao existe nesta rodada uma execucao full-stack real aprovada que cumpra todos os gates. |

## Avancos desta rodada

- Avaliacoes de contexto ampliadas, com resultados por categoria, sem rotular
  testes deterministas como benchmark de modelos ou aceitar suite vazia.
  O corpus passou de 35 para 56 casos: 56 aprovados, sem chamadas a modelos.
  Referencias ausentes ou multiplos alvos exigem esclarecimento; continuacoes
  que nomeiam uma API/site/app recuperam somente o historico da mesma conversa.
- Painel AI Motion Studio na area de operacao: consulta capacidades reais,
  distingue presenca de disponibilidade para executar e oferece atualizacao.
  Nao inicia processos, downloads, modelos ou renders.
- Desktop 0.2.1: consolidacao das correcoes de inicializacao, isolamento,
  encerramento e assinatura opcional; CI alinhado ao Python do pacote validado.
- Recuperacao ACP: limpeza de diretorio temporario no Windows repete apenas
  erros transitorios de compartilhamento/acesso por ate um segundo. Testes
  mantem um handle real do diretorio para reproduzir a falha sem mascarar erros
  de protocolo. Isto nao habilita execucao de agentes ACP.

## Ordem para concluir a homologacao

Continuacao sem Codex: [laboratorio TaskLab com APIs configuradas](TASKLAB-APIS-20261031.md),
incluindo correcao de reconciliacao de worktrees e evidencias reais parciais.

1. Configurar os provedores e ferramentas reais autorizados no laboratorio,
   sem usar banco, credenciais ou projetos de producao.
2. Executar pedidos curtos com modelos reais e medir acerto, esclarecimento,
   custo, latencia e erros de escopo separadamente dos testes offline.
3. Executar o projeto TaskLab descrito no protocolo de aceitacao, incluindo
   delegacao, worktrees, revisao e integracao, QA visual e reparo pela Central.
4. Injetar falhas controladas de processo/conflito, retomar e repetir os gates.
5. Homologar adaptadores CLI/ACP antes de permitir que processem prompts ou
   executem ferramentas. Presenca de executavel nao e certificacao.
6. Implementar executor de midia e fila do Motion Studio, depois validar cada
   etapa com ferramentas reais. Nesta maquina ComfyUI/Wan, Remotion, WhisperX
   e FFmpeg nao foram detectados pelo inventario.

## Reproducao

Validacao nesta rodada: 1.183 testes Python aprovados, 31 ignorados e dois
avisos existentes; 53 testes frontend aprovados e build Vite aprovado.
Depois do congelamento do resolvedor, 124 testes de contexto/contrato foram
reexecutados e aprovados. Corpus offline: 56/56 aprovados.
O desktop tem validacao separada no seu relatorio de entrega.

```powershell
python -m central.context_evaluation
python -m pytest -q
npm test
npm run build
```

Os testes Python usam banco temporario por `tests/conftest.py`. A avaliacao de
contexto cria seu proprio banco descartavel e nao chama provedores.
O ensaio final usa o protocolo de `ACEITACAO-FULLSTACK-INDEPENDENTE.md`;
nenhum arquivo do projeto gerado deve ser corrigido pelo avaliador externo.

Os commits web e desktop desta rodada sao separados. O desktop incorpora o
commit web para manter a mesma logica de negocio nas duas interfaces. Gerar
novo pacote e necessario para atualizar o aplicativo ja instalado.
