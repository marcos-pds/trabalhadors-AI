# Delegacao obrigatoria e pausa por limite — 31/10/2026

## Mudanca de comportamento

Uma etapa de fluxo pode declarar `required_actions: ["delegate_task"]`.
O requisito e validado e persistido no plano da execucao. Apenas etapas de
agentes com papel autorizado a delegar e execucoes autonomas podem usa-lo.
Fluxos antigos, sem esse campo, mantem o comportamento anterior.

Antes de aceitar `finish`, o trabalhador verifica uma subtarefa persistida em
`dynamic_step_requests`, com o mesmo run e a etapa solicitante. Uma promessa,
um plano ou mensagem `task_request` nao satisfaz o requisito. A primeira
conclusao sem evidencia recebe orientacao para chamar a ferramenta; a segunda
e recusada e permite failover. O modelo continua escolhendo a subtarefa e o
destinatario habilitado. O contrato nao cria identidades ou concede ferramentas.

```json
{"id":"architecture","kind":"agent","agent_id":"ID_REAL",
 "deps":[],"required_actions":["delegate_task"]}
```

O exemplo representa uma etapa dentro de um fluxo valido, nao um fluxo completo.
O campo pode ser enviado pela definicao JSON ou pelo editor visual: em cada
etapa, marque Exigir criacao de subtarefa antes de concluir. A interface usa
a capacidade can_delegate calculada pelo servidor, bloqueia o revisor e
preserva instrucoes e requisito ao reabrir o fluxo. Selecionar um fluxo com
esse requisito ativa o modo autonomo; a permissao da pasta continua obrigatoria.

O limite global de chamadas do laboratorio agora produz `WorkerPaused` e um
checkpoint `paused_limit`. Ele nao prejudica a saude de provedores que nem
chegaram a receber uma chamada, nem gera tentativas de fallback sem orcamento.
Falhas reais da API continuam registradas e seguem as regras normais.

## Evidencia real sem Codex

Laboratorio separado: `C:\Projetos\Central-IA\lab-api-delegacao-20261031`.
Run: `27f9bbcd-9ca7-4299-88c0-2b0d18de1d96`.

- Arquiteto concluiu via Groq/API, modelo `openai/gpt-oss-20b`, depois de criar
  uma delegacao real. Qwen/Groq apresentou rate limit e houve failover.
- Subetapa criada pelo trabalhador: `7a67e026-0223-432b-988d-ac6e154992a4`,
  destinatario `code`, solicitante `architecture`, profundidade 1.
- O DAG persistido passou a exigir essa subetapa antes do revisor. A nova
  etapa aguarda arquitetura, backend e frontend, sem ciclos.
- O segmento inicial foi limitado a 12 chamadas. Depois da correcao do limite,
  uma retomada com uma chamada terminou em `paused_limit`, preservando o
  checkpoint do backend, em vez de falhar atraves de todos os provedores.
- Codex nao esta entre os provedores do banco do laboratorio e nao participou
  como trabalhador ou fallback. Credenciais nao foram copiadas para esse banco.
- Nenhuma delegacao foi inserida pelo avaliador. Nenhum codigo da aplicacao
  gerada foi escrito ou corrigido pelo harness.

**Isto comprova criacao/dependencia da subtarefa, nao sua execucao final.**
O backend ficou pausado; frontend, subetapa dinamica e revisao continuam
pendentes. Nao houve promocao aprovada nem aceitacao full-stack final.
O journal e `latest.json` foram preservados e nao ficou worker do ensaio ativo.

## Verificacao

Regressao completa: 1.220 aprovados, 31 ignorados, dois avisos existentes.
A ultima correcao do limite foi validada depois em testes direcionados:
77 testes de delegacao, autonomia, checkpoints e adaptador de
APIs passaram depois das alteracoes. Eles incluem conclusao falsa rejeitada,
delegacao real aceita, contrato persistido e validado, e pausa sem acusar
falha de provedor.

O [protocolo full-stack](ACEITACAO-FULLSTACK-INDEPENDENTE.md) continua sendo o
gate de conclusao do projeto maior. O [ensaio anterior](TASKLAB-APIS-20261031.md)
permanece documentado, inclusive suas falhas; esta evidencia nao o substitui.


## Recuperacao de provedores

O roteamento agora coloca candidatos sem circuito aberto antes dos que estao
em recuperacao, mesmo quando o provedor em recuperacao era o preferido do
trabalhador. O prazo de suspensao continua obrigatorio; depois dele, uma unica
sondagem continua permitida se as alternativas nao concluirem. Uma resposta
bem-sucedida restaura a preferencia normal. Nao concede acesso nem habilita
provedores desativados. Testes de SQLite/relogio controlado cobrem essa ordem
e o retorno apos recuperacao; nao comprovam que uma cota externa foi liberada.
