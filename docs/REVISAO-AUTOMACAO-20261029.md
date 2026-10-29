# Revisão da automação — 29/10/2026

> Etapa posterior concluída: [ciclo real de criação, defeito e correção](CICLO-AUTONOMO-20261029.md).
> O texto abaixo registra o estado anterior a esse ensaio; suas pendências devem
> ser lidas junto aos resultados e limites do relatório posterior.

## Versão revisada

A pasta principal estava em `777661c`. Após `git fetch origin`, a sequência mais
recente disponível terminava em `c1d7915`, na branch
`feat/aprovacao-worktrees-na-central-20261029`. Essa sequência contém a
consolidação, QA DevTools, delegação dinâmica, worktrees, promoção de arquivos e
aprovação autenticada pela interface. Foi criada a branch local
`revisao/automacao-20261029` a partir dela. Nenhum histórico foi reescrito.
As correções desta revisão estão no working tree, sem novo commit ou push.

## Referências conferidas

- [nightly-labs/OpenBot — agentes](https://github.com/nightly-labs/openbot/blob/main/docs/architecture/agents.md): tarefas persistentes, coordenação e recuperação.
- [nightly-labs/OpenBot — navegador](https://github.com/nightly-labs/openbot/blob/main/docs/architecture/browser.md): contratos de ferramentas e checagem de acesso às abas.
- [CopilotKit/OpenBot — arquitetura](https://github.com/CopilotKit/OpenBot/blob/main/docs/architecture.md): gateway decide, registra e só então executa; escopo por pessoa e trabalhador.
- [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp): servidor oficial; schemas de `click`, `fill`, navegação e Lighthouse conferidos no pacote instalado **1.0.1**, também exercitado por MCP real.

Os conceitos continuam adequados à evolução da Central. Não foi incorporado
código dos projetos OpenBot nem instalado um plugin novo. A existência de uma
funcionalidade nas referências não comprova sua implementação na Central.

## Correções aplicadas

- Geração estruturada agora permite `delegate_task` com os campos e limites que
  o parser exige. Antes, provedores com schema restrito não conseguiam pedir
  delegação pelo contrato publicado.
- Delegação valida todo o DAG e a consistência do plano persistido; rejeita
  ciclos e dependências inválidas; permite repetição idempotente de uma
  solicitação já registrada, mantendo a checagem atual de escopo.
- Execuções autônomas vinculadas a uma pasta compartilhada executam uma etapa
  por vez e releem as dependências antes da próxima. Isso evita sobreposição
  dentro do mesmo run e uso de dependências desatualizadas após delegação.
  Não é um lock global entre runs e não substitui isolamento por trabalhador.
- DevTools aceita `click` e `fill` com página e UID do snapshot, argumentos
  limitados e aprovação individual. Revalida o endereço após a interação e
  fecha abas externas novas detectadas. Isso não é uma sandbox de rede: código
  da própria página ainda pode emitir requisições.
- Falhas esperadas do DevTools voltam ao trabalhador como resultado de ferramenta
  auditado, permitindo diagnóstico e nova tentativa, em vez de encerrar o run
  imediatamente. Cancelamentos continuam propagando.
- Falha de uma verificação posterior invalida QA aprovado anteriormente.
  A classificação considera o relatório antes de truncar sua exibição; JSON
  de saída não é cortado no meio. Evidência acima do limite reprova.
- Coleta CrUX foi desativada no subprocesso DevTools.
- Worktrees: ambiente Git não pode redirecionar o repositório; metadados precisam
  corresponder ao registro; limpeza preserva arquivos ignorados; caminhos
  reservados do Windows, arquivos binários e planos corrompidos são recusados;
  rollback evita sobrescrever uma edição concorrente; permissões existentes
  são preservadas na substituição.

## Verificação

- Suíte Python completa: **818 aprovados, 30 ignorados**, dois avisos existentes.
- Agendador: **4 testes direcionados aprovados**, incluindo sobreposição real
  de corrotinas e releitura de dependências. Executados separadamente também.
- Frontend: **44 aprovados**; build Vite concluído.
- Interface autenticada em desktop/celular: **18 aprovados**, dois testes de
  iniciar prévia ignorados porque dependem de opt-in.
- `git diff --check`: aprovado.
- Ensaio MCP real com página efêmera: snapshot, preenchimento, clique e contador
  de 0 para 1; console limpo; Lighthouse desktop/mobile com **44 auditorias
  aprovadas e zero reprovadas** em cada; erro de console injetado detectado.

O primeiro ensaio Lighthouse reprovou `robots.txt` e `llms.txt` da fixture. Os
arquivos da fixture foram corrigidos e a auditoria repetida até passar. Isso foi
feito pelo ensaio de engenharia, **não por um trabalhador IA autônomo**. Não houve
nova inferência paga ou tarefa enviada a modelos nesta revisão.

Reproduzir o ensaio isolado (não usa banco nem perfil do usuário):

```powershell
.\.venv\Scripts\python.exe -m examples.validate_browser_tools --lighthouse
```

## Dados e servidor

Backup criptografado e verificado antes do reinício:
`C:\Users\marco\Documents\Central-de-Trabalhadores-IA-MVP\backup-revisao-20261029`.
Diretório com ACL restrita ao usuário; chave e dados não pertencem ao repositório.
O verificador confirmou integridade; não foi executada uma restauração completa
nesta revisão.

Servidor reiniciado sem tarefas ativas em `http://127.0.0.1:8765/`, com HTTP 200,
schema 19, `integrity_check=ok` e nenhum erro de chave estrangeira. Contagens
antes/depois idênticas: usuários 1, projetos 4, conversas 16, mensagens 133,
agentes 18, provedores 17, recursos 30, checkpoints 49, permissões de computador
1 e runs 54. A conferência por contagem não é uma comparação de todas as linhas.

## Pendências reais

1. Iniciar a aplicação pelo trabalhador usando prévia controlada e comprovar um
   ciclo completo de defeito → diagnóstico → correção → interação → reteste.
   As chamadas de navegador ainda pedem aprovação individual.
2. Direcionar cada trabalhador ao próprio worktree e bloquear revisão/entrega
   até a integração aprovada e os testes no projeto principal. A interface de
   worktrees permanece experimental e desligada por padrão.
3. Homologar delegação dinâmica com inferência real e recuperação de falhas;
   os testes novos de DAG/agendador usam SQLite temporário e modelos simulados.
4. Ampliar avaliações de pedidos curtos, indisponibilidade de provedores,
   memória/RAG, runtimes adicionais e ciclo de skills/plugins/MCP.

A ferramenta disponível agora permite testar interações; isso não equivale a
comprovar autonomia completa nem a reprodução integral dos projetos OpenBot.
