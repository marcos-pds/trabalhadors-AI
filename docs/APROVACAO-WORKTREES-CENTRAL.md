# Revisão de worktrees na interface da Central — fase experimental

Referências de arquitetura preservadas:
- [nightly-labs/OpenBot](https://github.com/nightly-labs/openbot) — sessões e coordenação; PolyForm Noncommercial 1.0.0
- [CopilotKit/OpenBot](https://github.com/CopilotKit/OpenBot) — permissões, gateway e auditoria; MIT

Sem incorporar código dos repositórios OpenBot.

## Entrega

A revisão de alterações de worktrees agora pode ser feita por um operador autenticado no painel **Logs → Worktrees Git**, com as seguintes proteções:

- Migração aditiva **19**, para vincular worktrees e planos de revisão a conta, execução, etapa e pasta original
- Operações HTTP restritas a **localhost**, com autenticação de sessão, proteção CSRF, validação do responsável pela execução e autorização atual do workspace
- Criação de worktree apenas quando a execução não está ativa e o workspace aprovado é a **raiz exata** de um repositório Git sem mudanças pendentes
- Revisão de diffs, token de confirmação de uso único e bloqueio em caso de alterações posteriores, conflito, revogação ou tentativa de acesso por outro usuário
- Sem acesso do modelo aos tokens de aprovação, sem Git push, commit ou merge automático
- Após incorporar os arquivos, a evidência de build/teste é **invalidada**: os testes devem ser refeitos sobre o projeto principal

A integração apenas prepara/aplica alterações **do operador**; não direciona automaticamente as ferramentas do trabalhador para a cópia isolada. Um worktree Git não é sandbox de processos. A aplicação de múltiplos worktrees em sequência ainda exige conciliação manual, pois o checkout principal precisa estar limpo e alinhado.

## Usar na cópia de homologação (PowerShell)

Com a versão desta branch já instalada numa pasta de teste e com seus dados separados da Central de produção:

```powershell
$env:CENTRAL_WORKTREE_REVIEWS_ENABLED = "1"
$env:CENTRAL_DATA_DIR = "C:\Projetos\Central-IA\review-consolidacao\data"
$env:CENTRAL_PORT = "8876"
.\.venv\Scripts\python.exe run.py
```

Em **Computador**, autorize a raiz de um **projeto Git de teste**, com pasta `.git`; não utilize o próprio repositório da Central em operação. Abra uma execução autônoma relacionada a esse projeto; após encerrá-la, entre na aba **Logs** do painel de execução. Escolha a etapa, clique **Preparar cópia**, edite esse worktree com VS Code e clique **Revisar diferenças**. Verifique cada diff e só depois escolha **Aprovar e integrar arquivos**.

A funcionalidade está **desligada por padrão**, inclusive em servidor. Se não aparecer, confira a variável de ambiente e reinicie a cópia de homologação. Não copie credenciais e bancos de dados da instância principal para o ambiente de testes.

## Próximo bloqueio arquitetural

Para que cada trabalhador use automaticamente o próprio worktree, ainda faltam:
1. Roteamento de todas as ações de leitura/escrita/build por step, com revisão do contrato de autorização e checkpoints
2. Etapa do scheduler que aguarde a integração aprovada antes de liberar revisores e testes de entrega
3. Revalidação funcional e visual do código já integrado, inclusive quando há múltiplos worktrees com conflitos

Nenhuma dessas funcionalidades é considerada concluída por esta PR.
