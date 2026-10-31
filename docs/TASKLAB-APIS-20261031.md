# TaskLab com APIs configuradas, sem Codex — 31/10/2026

## Resultado e limites

Laboratorio real iniciado em `C:\Projetos\Central-IA\lab-api-tasklab-20261031`.
Execucao: `2bc730a3-4baa-4cc4-b42f-a482b5479b05`.
A arquitetura concluiu via Qwen/Groq e o backend iniciou um worktree Git real,
criando arquivos Python e React/TypeScript por ferramentas da Central.
Houve failover real entre APIs, inclusive apos limites de requisicoes.

**A aceitacao full-stack continua pendente.** Arquivos criados ou uma etapa
concluida nao comprovam autenticacao, persistencia, delegacao, integracao nem QA.
Nao foi produzido nesta rodada um TaskLab maior inteiramente aprovado. O
primeiro planejamento nao criou uma subtarefa dinamica; o avaliador deve
continuar reprovando esse criterio enquanto a evidencia real nao existir.

Codex nao foi usado como trabalhador neste laboratorio. O banco do ensaio
contem apenas provedores de API permitidos. `codex_cli`, `openai_chatgpt`,
runtimes nativos, Ollama e modelos cujo nome inclui Codex sao excluidos da
selecao e do fallback. As configuracoes de provedores da producao nao mudam.

O brief deste ensaio e detalhado e vem do protocolo de aceitacao. Ele nao e
evidencia de criacao full-stack a partir de poucas palavras.

## Correcoes implementadas

- `Engine.finish_promoted_step` reconcilia uma promocao ja aprovada, confirma
  escopo, arquivos, etapa e estado, e persiste conclusao/handoff/recibo na mesma
  transacao. Repeticao nao duplica mensagens nem reexecuta o implementador.
- A retomada recupera interrupcao depois de aplicar os arquivos e antes de
  reconciliar a etapa, sem reutilizar token consumido. Etapa ainda nao aprovada
  nao pode ser retomada como se estivesse integrada.
- O endpoint verifica conta e encerramento da execucao antes da promocao.
  Esta era uma lacuna real: chamava um metodo inexistente depois de aplicar
  os arquivos. Nao foi tratado como problema do modelo.
- A resolucao de checkpoints e a consulta de status aceitam uma tarefa cancelada
  com isolamento, mantendo as verificacoes de conta, pasta e permissao atuais.
  Ferramentas continuam bloqueadas ate a retomada explicita. Essa falha foi
  reproduzida ao retomar o primeiro segmento e corrigida com teste real de Git.
- O adaptador de APIs do laboratorio le o banco original com SQLite `mode=ro`,
  sem bootstrap/migracoes. Exige um unico proprietario ou selecao explicita.
  Credenciais sao decriptadas somente em memoria durante cada chamada; o
  banco do laboratorio guarda identificadores e endpoints ficticios, sem chaves.
- Cada chamada revalida habilitacao/rotacao na origem. Desabilitar ou alterar
  o provedor bloqueia chamadas posteriores daquele snapshot.
- Chamadas sao limitadas por segmento, e cada resposta tem prazo total de
  90 segundos. Isso permite failover mesmo se um stream continuar enviando
  keepalives. O primeiro segmento foi iniciado antes dessa ultima melhoria;
  ela passa a valer ao retomar com o codigo atualizado.
- Respostas HTTP 413 acionam ate duas reducoes do historico de ferramentas,
  mantendo o pedido inicial, atualizacoes do usuario e resultados recentes
  completos. A reducao so e aplicada quando diminui o tamanho real do texto.
  Nao resume codigo, nao altera permissoes e orienta releitura de dados ausentes.
  Sem reducao segura, o erro segue para o failover normal.

Validacao: 26 testes de reconciliacao com Git/SQLite/HTTP reais; regressao
completa com 1.213 aprovados, 31 ignorados e dois avisos existentes.
Apos as melhorias adicionais do adaptador, seus seis testes focados passaram,
incluindo exclusao do Codex, isolamento, revogacao e fechamento por timeout.
  Mais 131 testes de autonomia/delegacao/contexto e 11 de checkpoints passaram
  apos a recuperacao de HTTP 413; a retomada cancelada teve regressao adicional.
Esses testes controlados nao sao inferencia real nem substituem a aceitacao.

## Operar o laboratorio

As chamadas usam a cota das APIs selecionadas. `--max-calls` limita tentativas
por segmento, inclusive chamadas que falham; nao e um teto de cobranca monetaria.
Use um destino novo para preparar outro ensaio. Nunca use o workspace de
producao como destino. A chave da origem nao deve ser enviada pela linha de comando.

```powershell
python -m examples.validate_api_tasklab prepare C:\Projetos\Central-IA\novo-lab `
  --source-data C:\CAMINHO\CENTRAL\data --max-calls 80
python -m examples.validate_api_tasklab run C:\Projetos\Central-IA\novo-lab `
  --source-data C:\CAMINHO\CENTRAL\data --max-calls 80 --timeout 600
python -m examples.validate_api_tasklab status C:\Projetos\Central-IA\novo-lab
```

`run` retorna 2 se a execucao ainda nao concluiu e preserva journal/checkpoints.
Mesmo status `completed` do motor nao equivale a aceitacao independente.
Preview e navegador local possuem autorizacao previa limitada ao ensaio;
instalacoes de dependencias e promocao exigem revisao concreta do operador.
O harness nao escreve ou corrige o codigo da aplicacao gerada.

Para uma solicitacao de instalacao pendente, inspecione `request_json` e a
pasta da etapa no status e use `approve-action --approval-id ID` se aprovada.
Para integrar uma etapa, execute `review --step-id ID`, inspecione os diffs e
use `approve --step-id ID --confirmation TOKEN`. O token e de uso unico.
Depois execute `run` novamente; nao repita uma aprovacao consumida.

O verificador de [aceitacao full-stack independente](ACEITACAO-FULLSTACK-INDEPENDENTE.md)
continua sendo o gate final. Ele deve comprovar tanto a execucao da Central
quanto a API e interface reais. Nenhuma falha foi convertida em aprovacao.
