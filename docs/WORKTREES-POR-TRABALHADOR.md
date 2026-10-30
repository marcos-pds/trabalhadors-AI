# Git worktrees por trabalhador — fase 1 de isolamento

A Central conserva os dois OpenBot como referências arquiteturais:
- https://github.com/nightly-labs/openbot — sessões de agentes, tarefas e execução (PolyForm Noncommercial 1.0.0).
- https://github.com/CopilotKit/OpenBot — isolamento, permissões e auditoria (MIT).

Esta implementação é original da Central e **não copia código** desses projetos.

## Entregue nesta fase

O módulo \`central.worker_worktrees\` cria worktrees Git **independentes para cada par run/step** dentro da pasta explicitamente escolhida. A branch principal e seu HEAD não são alterados. O módulo:
- exige a **raiz exata de um repositório Git**, com checkout base limpo;
- valida identificadores, impede travessia, links simbólicos/junções e substituição de diretórios existentes;
- usa \`git worktree add --detach\` com hooks de checkout desativados para esta operação;
- mantém o checkout isolado em \`.central-worker-worktrees/<run>/<step>\`, ignorado pelo Git e bloqueado para ferramentas de arquivos de agentes;
- permite examinar status/arquivos modificados sem expor conteúdos;
- recusa qualquer remoção se houver alterações rastreadas **ou não rastreadas**, sem \`--force\`;
- não executa merge, reset, delete de arquivos editados, push ou instalação de dependências.

**Não é uma sandbox de processos nem oferece isolamento de segurança do sistema operacional.** Apenas separa as árvores de arquivos do Git.

## Teste manual seguro — PowerShell

Em uma pasta **Git de teste, com todas as mudanças salvas** (não use o repositório da Central em execução):

\`\`\`powershell
python -m central.worker_worktrees prepare --repo "C:\Projetos\Central-IA\meu-projeto-git" --run "teste-001" --step "frontend-01"
python -m central.worker_worktrees prepare --repo "C:\Projetos\Central-IA\meu-projeto-git" --run "teste-001" --step "backend-01"
python -m central.worker_worktrees inspect --repo "C:\Projetos\Central-IA\meu-projeto-git" --run "teste-001" --step "frontend-01"
\`\`\`

**Somente para worktree sem alterações:** execute \`remove-clean\` com \`--confirm-remove\`. Se houver código criado ou modificado, a remoção é bloqueada; preserve o worktree e revise o conteúdo no VS Code.

## Ainda falta antes de ativar automaticamente

1. Registrar cada worktree no banco de dados com escopo de usuário, projeto, execução e etapa.
2. Fazer o motor enviar read/write/build para **a árvore de cada trabalhador**, sem fuga de escopo e com revalidação das permissões.
3. Criar mecanismo de conciliação com preview de diff, conflitos e **aprovação explícita antes de integrar** a árvore isolada à principal.
4. Confirmar que QA/preview e evidências de entrega só utilizem código integrado e testado novamente.
5. Testar isolamento + retomada no Windows, incluindo quedas de energia, Git com mudanças pendentes e worktrees interrompidos.

**Status:** fundação operacional e testes automatizados; isolamento automático e integração segura ainda **pendentes**. Não altere \`main\` até a homologação.
