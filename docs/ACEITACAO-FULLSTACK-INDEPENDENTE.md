# Aceitação full-stack independente — piloto issue #17

Esta etapa adiciona verificadores **reais**, mas não afirma que a Central já tenha concluído o projeto maior.
O verificador não gera arquivos da aplicação, não executa modelos nem aprova ações.

## Pedido para a Central em laboratório isolado

Use um repositório Git novo, com commit inicial, um banco da Central separado e
agentes Codex autorizados para arquitetura, frontend, backend e revisão. Ative
o isolamento por trabalhador e exija delegação dinâmica real e integração
de alterações mediante aprovação explícita do operador.

> Crie um gerenciador de tarefas TaskLab com React, Vite, TypeScript,
> FastAPI e SQLite. Implemente cadastro, login JWT/Bearer, equipes,
> CRUD de tarefas, atualização de status e filtros, com responsividade.
> API: GET /api/health devolve {"ok":true}; POST /api/auth/register
> recebe email/password; POST /api/auth/login devolve access_token;
> POST /api/teams recebe name e devolve id; POST /api/tasks recebe
> title/team_id/status e devolve id; PATCH /api/tasks/{id} muda status;
> GET /api/tasks e GET /api/tasks?status=doing devolvem listas.
> Rotas privadas recusam acesso anônimo com HTTP 401/403.
> UI com data-testid: login-email, login-password, login-button,
> task-card, create-task-title, create-task-button. Login deve mostrar
> tarefas persistidas; a criação de tarefas deve usar a API real.
> Crie frontend/package.json, frontend/src/App.tsx e backend/main.py.
> Use a própria Central para editar, testar, iniciar prévia, delegar
> subetapas e fazer Chrome DevTools MCP: snapshot, fill, click,
> list_console_messages, Lighthouse desktop e mobile; corrija falhas.
> Integre worktrees somente após revisão do operador e execute testes
> novamente no projeto principal. Não finalize apenas com um plano.

## Verificação independente

Depois que o operador iniciar os serviços frontend e backend do projeto
gerado, ambos em 127.0.0.1, execute na raiz do checkout da Central:

```powershell
.\.venv\Scripts\python.exe -m examples.verify_fullstack_acceptance `
  --db 'C:\Projetos\Central-IA\lab-fullstack\data\central.sqlite3' `
  --run-id 'ID_REAL' --user-id 'ID_REAL_DA_CONTA' `
  --workspace 'C:\Projetos\Central-IA\lab-fullstack\workspace' `
  --ui-url 'http://127.0.0.1:5173/' --api-url 'http://127.0.0.1:8000/' `
  --kit 'C:\Projetos\Central-IA\playwright-kit' `
  --output 'C:\Projetos\Central-IA\fullstack-evidence-01'
```

A instalação do pacote @playwright/test e Chromium no kit é manual,
fora deste script. Ele não instala dependências nem roda comandos do projeto gerado.

Os resultados ficam em independent.json, acceptance.json e capturas desktop/mobile
se o login chegar à tela. Um resultado verde exige: conta e execução corretas;
quatro papéis concluídos; delegação persistida; promoção de worktree;
arquivos reais frontend/backend; testes depois de integração; DevTools
qualificado após alteração; API real com auth, equipe, CRUD, filtro;
Playwright com login e criação de tarefa em desktop/mobile e sem erros.

O SQLite da Central é aberto **somente para leitura**, sem migração. O navegador
bloqueia redes não locais e as URLs iniciais aceitam apenas HTTP loopback.
Os testes criam conta e tarefas de laboratório na aplicação gerada e
podem modificá-la pela própria interface/API. Nunca use contra produção.

## O que ainda não está comprovado

A aceitação permanece PENDENTE até este comando retornar passed: true
num projeto real gerado pela Central. Não prova reinício do backend, sandbox
de sistema operacional, execução de ACP/CLI externo, GPU ou Motion Studio.
A homologação com Codex/DevTools exige a máquina local autorizada.

Referências: nightly-labs/OpenBot (PolyForm Noncommercial) e
CopilotKit/OpenBot (MIT). Nenhum código desses projetos foi copiado.
