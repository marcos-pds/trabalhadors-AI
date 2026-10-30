# Delegação dinâmica de subtarefas — etapa incremental

Esta entrega complementa a PR #10, mantendo o plano de consolidação na PR #9.

## Referências

- [nightly-labs/OpenBot](https://github.com/nightly-labs/openbot): colaboração de agentes, tarefas persistentes e retomada (licença PolyForm Noncommercial 1.0.0).
- [CopilotKit/OpenBot](https://github.com/CopilotKit/OpenBot): gateway de ferramentas com verificação de identidade, permissões e auditoria (licença MIT).

A implementação nesta branch foi escrita para a Central. **Nenhum código OpenBot foi copiado** ou adicionado como dependência.

## Capacidades implementadas

Um trabalhador de arquitetura, coordenação ou implementação pode solicitar
`delegate_task` indicando um **trabalhador habilitado já existente**, o título, as
instruções verificáveis e um `request_id` estável. Isso registra uma etapa nova
no DAG, uma mensagem de tarefa e evento auditável. A etapa não recebe permissões
novas; cada ferramenta continua sujeita a workspace/grants/aprovações existentes.

A execução não é replanejada às cegas: os novos passos têm dependências
persistentes, aguardam os passos anteriores e são executados na próxima
iteração do motor. A revisão obrigatória passa a depender das novas etapas,
impedindo concluir a entrega antes do novo trabalho.

Limites: até 8 novas etapas por run, no máximo 32 etapas totais e profundidade
de delegação 4. O par `requester_step_id` + `request_id` garante deduplicação
após retomada do checkpoint. Uma repetição com conteúdo diferente é negada.

Validações negativas: identidade de outro usuário, ciclo ancestral, papéis
não autorizados, revisor iniciado, limite estourado, escopo revogado e rollback.

## Observações

As subtarefas são atribuídas a **agentes já cadastrados e habilitados**:
ainda não há criação de agentes novos nem worktrees por trabalhador.
A ordenação conservadora evita novas etapas concorrentes no mesmo workspace;
não substitui isolamento real por sistema operacional ou Git worktrees.

Rever a interface visual do monitor de etapas, o teste de retomada de run real
com modelos e o comportamento de múltiplos trabalhadores simultâneos no Windows
antes de habilitar por padrão em ambientes produtivos. Não fechar PRs e não
fazer merge na main sem CI verde e homologação local.
