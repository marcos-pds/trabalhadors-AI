# Promoção aprovada de worktrees — fase incremental

**Referências:** [nightly-labs/OpenBot](https://github.com/nightly-labs/openbot)
(licença PolyForm Noncommercial) e [CopilotKit/OpenBot](https://github.com/CopilotKit/OpenBot)
(licença MIT). A implementação nesta branch é original da Central, sem reutilização direta
do código desses repositórios.

## O que foi implementado

O novo módulo \`central.worker_worktree_reviews\` faz a revisão e a **promoção local**
de arquivos de um worktree isolado para a raiz Git principal.

- \`plan\` verifica identidade do worktree, repositório base limpo, revisão do Git \`HEAD\`,
  arquivos permitidos, extensão textual, limites de tamanho e conteúdo UTF-8.
- Mostra diff por arquivo, hashes SHA-256 e fornece uma confirmação humana de uso único.
- \`apply\` exige confirmação e plano ainda válido (30 min), verifica novamente os
  conteúdos e a base, bloqueia integrações concorrentes e copia somente os arquivos
  revisados.
- Nenhum \`git merge\`, \`commit\`, \`push\`, \`reset\`, rebase, exclusão de worktree
  ou publicação acontece automaticamente. O projeto integrado **fica com mudanças locais**,
  exigindo validação/build novo e revisão Git antes de commit.
- Planos ficam na pasta protegida \`.git/central-merge-plans\`; a confirmação é
  armazenada somente como hash. Uma aplicação interrompida não é repetida
  automaticamente. Erros tentam restaurar os bytes anteriores e exigem
  inspeção manual caso haja falha ou interrupção.
- Deleções, renomeações, symlinks, binários, credenciais, código acima dos limites
  e objetos fora do escopo são rejeitados.

## Executar em projeto Git de TESTE (nunca sobre a Central de produção)

\`\`\`powershell
python -m central.worker_worktrees prepare --repo "C:\Projetos\Central-IA\git-de-teste" --run "run-123" --step "frontend-01"
# Faça uma alteração textual dentro do worktree de teste.
python -m central.worker_worktree_reviews plan --repo "C:\Projetos\Central-IA\git-de-teste" --run "run-123" --step "frontend-01"
# Leia o diff retornado. Só depois:
python -m central.worker_worktree_reviews apply --repo "C:\Projetos\Central-IA\git-de-teste" --plan-id "ID_QUE_O_PLAN_MOSTROU" --confirmation "TOKEN_QUE_O_PLAN_MOSTROU"
\`\`\`

Atenção: um token passado na linha de comando pode aparecer no histórico do PowerShell
e em ferramentas locais de inspeção de processos. Utilize a API programática
sob autorização explícita e armazenamento seguro ao integrar com a interface.

## Pendências

**Ainda não há** roteamento automático das ações de IA para os worktrees, nem
uma tela de aprovação com identidade de usuário, nem aplicação de merges em tempo real
no job scheduler. O próximo passo é persistir essas aprovações no banco multiusuário
e expor preview de diff por meio de ação autorizada, integrando os checkpoints
e os testes de compilação/QA após a promoção.

Os worktrees isolam arquivos Git, não isolam processos nem código de dependências.
Somente a hospedagem em sandbox de processos pode oferecer segurança operacional.

CI e homologação com Git real no Windows/Linux são obrigatórios antes de ativar
esse caminho para trabalhadores sem supervisão.
