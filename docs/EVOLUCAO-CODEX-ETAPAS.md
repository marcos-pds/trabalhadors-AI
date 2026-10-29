# Codex integrado e etapas restantes — 28/10/2026

## Estado atual

A Central executa trabalhadores usando o Codex App Server local. O CLI gerencia
o login ChatGPT. Arquivos, comandos, aprovações e evidências continuam passando
pelas ferramentas da Central. O runtime nativo produz texto e ações estruturadas;
não recebe shell, ferramentas de arquivo, navegador, MCP ou plugins nativos.
Este é o adaptador inicial de execução Codex, não uma reprodução de todas as
funcionalidades da interface nativa do Codex.

Compatibilidade validada: `codex-cli 0.164.0-alpha.11.1`; modelo real testado:
`gpt-6.1-sol`. Outras versões do CLI são recusadas até nova inspeção. O catálogo
de modelos não comprova elegibilidade: apenas uma inferência bem-sucedida confirma
o acesso naquela chamada. Login por API key não é usado por este adaptador.

## Referências realmente aplicadas

| Referência | Conceito usado | Implementação na Central |
| --- | --- | --- |
| nightly-labs/OpenBot | Sessões de agentes persistentes, App Server por stdio, comunicação | `codex_bridge.py`, `codex_step_sessions`, mensagens e passagem de resultados do DAG |
| CopilotKit/OpenBot | Gateway central para decidir e auditar ferramentas | Codex gera decisões; `WorkspaceExecutor`, grants, hashes e aprovações executam ações |
| Documentação oficial do Codex | Handshake, threads, turnos, retomada e saída estruturada | `initialize`, `thread/start`, `thread/resume`, `turn/start`, eventos e envelope de ação |

Fontes consultadas:

- https://github.com/nightly-labs/openbot
- https://github.com/nightly-labs/openbot/blob/main/docs/ARCHITECTURE.md
- https://github.com/CopilotKit/OpenBot
- https://github.com/CopilotKit/OpenBot/blob/main/docs/architecture.md
- https://developers.openai.com/codex/app-server
- https://developers.openai.com/codex/config-reference

Nenhum código OpenBot foi incorporado. A observação de licenças da auditoria
anterior continua registrada em `EVOLUCAO-OPENBOT-20261028.md`. Não houve nova
dependência externa de runtime nesta etapa.

## Alterações verificáveis

- `central/codex_bridge.py`: adaptador de execução; sessão vinculada a usuário,
  execução, etapa, provedor, modelo e identidade da conta. Lease com fencing,
  cancelamento, timeout, limites de saída, subprocesso encerrado por chamada e
  retomada do histórico nativo na chamada seguinte. Mudanças de contexto podem
  exigir reconstrução da sessão a partir do checkpoint; não se promete continuidade perfeita.
- `central/codex_runtime.py`: cliente JSONL com notificações ordenadas e limites
  configuráveis. Solicitações de ferramentas/aprovações do servidor são recusadas.
- `central/providers.py`, `central/engine.py`: runtime `codex_cli` no ciclo de
  trabalhadores já existente; seleção de Skills, validações e revisão preservadas.
- Migration 16: sessões Codex por etapa. IDs nativos nunca são aceitos do navegador.
- Migration 17: reconciliação auditada de vínculos antigos sem organização,
  exclusivamente com o espaço pessoal do próprio proprietário. Pasta, modo e
  executor permanecem iguais; organizações compartilhadas não são adotadas.
- API e frontend: conectar modelo Codex e criar trabalhador; manter o login CLI
  ao desconectar a integração; eventos de sessão no monitor de execução.
- Seleção manual de implementador inclui revisão obrigatória automaticamente.
  A conexão Codex oferece implementador e revisor no mesmo runtime; agentes
  existentes não têm seus provedores alterados. Fluxos explícitos sem revisão
  continuam sendo recusados.
- `specialist_profiles.py`: cinco perfis adicionais, com instalação idempotente
  e preservação de configurações existentes: QA, Segurança, Banco de Dados,
  Automação e Integrações MCP.
- Diagnóstico de erros internos registra somente tipo e localização da exceção,
  sem copiar valores de credenciais para eventos.

## Evidências reais

1. Inspeção do runtime instalado contra um gravador HTTP local:
   `{"tool_names":[],"count":0}`. O script reutiliza a configuração de produção.
   Isto verifica a superfície de ferramentas; não é prova de inferência.
2. Equipe Codex com três agentes concluída, com resultados persistidos e recebidos.
   Execução: `b96f66fe-8c4a-43cb-a028-e85ac86dadcf`.
3. Aplicação com frontend HTML/JavaScript e backend Python criada pela Central:
   `C:\Projetos\Central-IA\validacao-codex-projeto-20261028-b\workspace\server.py`.
   Execução: `3845e4a2-cc5d-4c26-a2d1-e0c2ed8cbf7b`.
   O programador criou o arquivo e validou; o revisor leu o arquivo e validou.
   O journal registra oito turnos Codex e seis retomadas nativas.
4. Playwright real contra a aplicação: desktop e celular aprovados; cinco cliques
   produziram contador 5; backend `/api/health` retornou `{"ok":true}`; sem erros
   JavaScript, falhas de rede ou overflow horizontal nesses testes.
   As verificações de navegador foram executadas pelo kit externo de avaliação,
   não pelo próprio trabalhador via MCP. Essa automação interna permanece pendente.
5. Pausa por limite, saída do processo e retomada em novo processo:
   execução `032160e1-75c2-4fb9-9b06-3698ed156bae` concluída, seis retomadas nativas.
   Esse ensaio encontrou a inconsistência de tenant antiga corrigida na migration 17.
6. Suíte Python: 721 aprovados, 26 ignorados, nenhum xfail; frontend: 44 aprovados;
   build Vite concluído. Testes de protocolo usam subprocessos locais de fixture e
   estão separados das inferências reais acima.
7. Pedido curto real: **“Deixe o botão verde.”** aplicado ao projeto existente,
   com alteração salva, revisão e validação. Execução
   `64520dc0-25c5-40c2-ae31-a4338a4449b2`. O teste de navegador confirmou também
   o verde calculado pelo CSS e o contador em desktop/celular.
8. Regressão visual/funcional final: 20 testes Playwright aprovados (18 controles
   da Central e dois da aplicação), com dois opt-ins de início de prévia ignorados.
   A conexão Codex e adição dos cinco especialistas foram exercitadas pela
   interface autenticada real, preservando os perfis anteriores.

Capturas: `codex-demo-desktop-20261028.png` e `codex-demo-mobile-20261028.png`.
Conexão pela interface: `codex-conectado-20261028.png`.
Os ensaios anteriores que falharam permanecem em seus diretórios e não foram
substituídos por resultados fabricados.

A Central foi reiniciada com zero tarefas ativas; migrations 16/17 aplicadas e
integridade SQLite confirmada. A interface real conectou o Codex e instalou os
especialistas: há 18 agentes e 15 provedores, incluindo implementador/revisor Codex.
Uma restauração temporária do backup foi comparada ao banco atual: todas as linhas
originais de usuários, projetos, conversas, mensagens, agentes, provedores,
recursos, checkpoints e permissões foram preservadas integralmente; a chave de
criptografia original também permaneceu igual. Foram adicionados sete agentes e
um provedor. Nenhum push ou merge remoto foi realizado.

Demonstração local: http://127.0.0.1:8891/ . Ela foi mantida em execução para
inspeção. Para iniciar novamente, execute `server.py` na pasta do projeto de
demonstração com o Python da `.venv` da Central. A prévia Python ainda não é
gerenciada pelo painel de servidores npm da Central.

## Etapas ainda faltantes, em ordem de prioridade

| Prioridade | Etapa | Critério para concluir |
| --- | --- | --- |
| 1 | QA visual autônomo e prévia controlada | A própria Central inicia a aplicação, navega, detecta um defeito introduzido, corrige e repete os testes com evidências |
| 2 | Contexto com pedidos curtos | Avaliações reais de criação, ajustes, continuação e ambiguidades, mantendo isolamento entre conversas/projetos e sem prompts técnicos detalhados |
| 3 | Delegação dinâmica | Coordenador cria subtarefas executáveis com dependências, limites e revisão; prevenção de ciclos e recuperação testadas |
| 4 | Isolamento por trabalhador | Worktrees/branches ou sandbox por agente, integração de diffs, conflitos e limpeza de recursos verificados |
| 5 | Outros runtimes e ACP | Adaptadores Claude Code, Gemini CLI, OpenCode e ACP usando documentação/versões verificadas e testes reais quando instalados |
| 6 | Recuperação ampliada | Interrupção inesperada, conflito, cancelamento, aprovação negada e indisponibilidade de provedor exercitados ponta a ponta, sem repetir efeitos irreversíveis |
| 7 | Memória/RAG e troca de modelos | Avaliações de relevância, compactação e retomada entre modelos; proveniência e isolamento comprovados |
| 8 | Skills, plugins e MCP completos | Importar, aplicar, atualizar/reverter e executar servidor local de teste com política por ferramenta e auditoria |
| 9 | Monitoramento de equipes | Dependências, bloqueios, mensagens e controles individuais de pausa/retomada, incluindo estados de erro em desktop/celular |
| 10 | Interfaces AI Motion Studio | Contratos de serviços e artefatos para ComfyUI/Wan/Remotion/WhisperX/FFmpeg, sem acoplar o motor principal |
| 11 | Aceitação final integrada | Projeto maior criado com pedido curto, construído, iniciado, testado e corrigido pela própria Central; regressão e recuperação aprovadas |

O diagnóstico e a execução básica persistente do Codex deixaram de ser lacunas.
A demonstração simples funciona, mas não comprova capacidade irrestrita de
construir qualquer aplicação nem encerra a missão completa de quinze fases.

## Reprodução e recuperação

```powershell
.\.venv\Scripts\python.exe -m examples.inspect_codex_tools
.\.venv\Scripts\python.exe -m examples.validate_local_team C:\Projetos\Central-IA\novo-codex --runtime codex --model gpt-6.1-sol --project
.\.venv\Scripts\python.exe -m examples.validate_local_team C:\Projetos\Central-IA\novo-checkpoint --runtime codex --model gpt-6.1-sol --project --pause-test
.\.venv\Scripts\python.exe -m examples.validate_local_team C:\Projetos\Central-IA\novo-checkpoint --resume
```

Cada criação exige destino novo; a retomada utiliza o diretório já existente.
As inferências consomem a cota da conta ChatGPT conectada ao CLI.

Backup prévio desta etapa:
`C:\Users\marco\Documents\Central-de-Trabalhadores-IA-MVP\backup-codex-runtime-20261028-203954`.
Código conferido por SHA-256 sem divergências; banco criptografado com Fernet e
verificado. Para retorno integral, restaure o banco em uma pasta nova com a chave
de recuperação, retorne o código correspondente e faça o build. Não apague tabelas
de sessões ou o ledger de migrations diretamente em produção.
