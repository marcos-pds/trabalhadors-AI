# Consolidação da Central — 28/10/2026

## Escopo e segurança

Esta branch deriva de `feat/isolated-preview-semantic-memory` no commit `777661c2078b85642a67274e2179b53b48533d25`. Ela prepara uma integração revisável para a branch `main`, preservando integralmente o histórico da origem e deixando a `main` inalterada até aprovação da integração. Nenhum banco de dados local, segredo, workspace ou branch histórica foi apagado.

A branch avançada estava 326 commits à frente de `main`, sem commits atrás, na auditoria inicial. Isso facilita uma proposta única de integração, mas **não garante que todos os conteúdos das branches divergentes estejam incluídos**.

## Modificações de higiene

- Removidos do controle de versão **68 arquivos de teste temporários** localizados em diretórios `.pytest-*` na raiz. Esses objetos continuam no histórico Git anterior, mas deixam de aparecer na árvore ativa.
- Acrescentada regra `/.pytest-*/` em `.gitignore` para evitar reincidência.
- O teste de padrões Chrome DevTools agora detecta quando `URLPattern` não existe no Node 22, preservando todos os testes Python de restrições de URL.
- O CI executa **também um teste real com `URLPattern` no Node 24**; não basta ignorar a verificação de compatibilidade.

## Pull requests e branches anteriores

| PR | Head | Base atual | Orientação |
| --- | --- | --- | --- |
| #2 | `feat/local-project-workspaces` | `main` | Revisar funcionalidades não representadas na consolidação antes de encerrar |
| #3 | `feat/uiux-skills-architect-autonomy` | `feat/local-project-workspaces` | Comparar diferenças sem reintroduzir código antigo |
| #4 | `feat/chat-principal-menu-hamburguer` | `main` | Verificar equivalência do chat na interface consolidada |
| #5 | `feat/chat-first-slash-integrated` | `feat/uiux-skills-architect-autonomy` | Verificar comandos slash e integrações |
| #6 | `feat/gemini-visual-minimalista` | `feat/chat-first-slash-integrated` | Verificar tema e navegação |
| #7 | `feat/zai-modelscope-siliconflow` | `main` | É ancestral do #8; avaliar fechamento apenas após integração final |
| #8 | `feat/isolated-preview-semantic-memory` | `feat/zai-modelscope-siliconflow` | Principal desenvolvimento atual; preservar até consolidar |

Não fechar ou excluir PRs e branches em massa. Os históricos de #2 a #6 divergem: revisá-los por funcionalidade, não por número de commits. Integrar sem duplicação e sem perda de dados é mais importante que deixar a lista de PRs visualmente vazia.

## Gates antes de integrar na main

1. CI Windows e Ubuntu **verde**, incluindo Python, frontend e execução explícita do URLPattern em Node 24.
2. Testes reais de isolamento Docker e PostgreSQL/Redis aprovados.
3. Auditoria funcional das branches divergentes #2–#6.
4. Teste manual no Windows da Central, com os dados da conta preservados; confirmar chat, Codex, Skills/MCP, permissões e prévia.
5. Teste de entrega: criar e modificar um projeto via Central, abrir pelo navegador e fazer validação visual autônoma — registrar o que ainda depende de operador.
6. Confirmar backups/restauração e compatibilidade das migrations.
7. Somente depois: autorizar merge em `main` e encerrar PRs redundantes; manter tags ou referências de rollback.

## Atualização da cópia local

Verifique primeiro se há trabalho local pendente: `git status -sb` e `git log -1 --oneline`.

Para inspecionar esta branch sem interferir na pasta em uso, prefira uma cópia de trabalho ou worktree *nova* (somente se o caminho não existir):

```powershell
git fetch origin --prune
git worktree add -b review/consolidacao-local C:\Projetos\Central-IA\review-consolidacao origin/chore/consolidacao-central-20261028
```

Esse comando é **opcional e manual**; não foi executado nesta operação remota. Não altere a instalação local de produção antes da homologação.
