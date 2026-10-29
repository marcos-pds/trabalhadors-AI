# QA DevTools com evidências verificáveis — entrega incremental

Esta branch parte de `chore/consolidacao-central-20261028` e altera o critério de qualidade de entregas com UI.

## O que muda

- `central/browser_quality.py` classifica respostas reais de `take_snapshot`, `list_console_messages` e `lighthouse_audit`. Sucesso da ferramenta não significa auditoria aprovada.
- O evento `workspace_action_result` registra `qa_pass` e um resumo limitado `qa_issue`, além dos campos existentes.
- O motor recusa a conclusão de uma implementação visual quando o MCP está ativo e os checks mais recentes após a última edição não foram aprovados; o reparo de entrega existente poderá enfileirar uma revisão limitada.
- Chamadas DevTools continuam exigindo aprovação individual e só acessam endereços locais.
- Node.js, Docker e Codex existentes permanecem inalterados.

## Limites conhecidos

Isso corrige a integridade do **critério de aceite**, não representa por si só navegação autônoma completa. A própria Central ainda precisa iniciar automaticamente a aplicação e testar interações reais com Playwright/DevTools. O mecanismo aceita apenas o formato conhecido do relatório do Chrome DevTools MCP fixado; formatos desconhecidos reprovam de modo conservador.

As auditorias Lighthouse com `Failed: N` superior a zero exigem correção. Consoles com mensagens `[error]` exigem correção. Uma página de console incompleta/paginada não pode ser considerada limpa. O histórico de chamadas é preservado para auditoria.

## Referências arquiteturais mantidas

1. **[nightly-labs/OpenBot](https://github.com/nightly-labs/openbot)** — sessões persistentes, colaboração entre trabalhadores, execução assistida por ferramentas e histórico de ações. A Central mantém o motor próprio e evolui seus contratos de entrega; não executa nem incorpora o código desse aplicativo.
2. **[CopilotKit/OpenBot](https://github.com/CopilotKit/OpenBot)** — política de execução com gateway, auditoria, isolamento de ferramentas e aprovação antes de ações sensíveis. A inspeção do Chrome DevTools continua passando por `workspace_tools.agent_action` e pela aprovação explícita.

**Licenças observadas na consulta de 28/10/2026:** o nightly-labs/OpenBot usa **PolyForm Noncommercial 1.0.0**, e o CopilotKit/OpenBot usa **MIT**. Esta mudança implementa conceitos próprios em arquivos da Central, sem incorporar arquivos nem dependências desses projetos. Toda futura reutilização deve respeitar a licença aplicável ao código exato e às dependências.
