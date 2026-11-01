# Avanço de recuperação e monitoramento — 01/11/2026

## Implementado

- Etapas 6/7: erros JSON com códigos explícitos de contexto excedido em HTTP 400/422 usam a recuperação limitada que já atendia HTTP 413. São no máximo duas reduções, somente quando o histórico realmente diminui; pedido inicial, atualizações do usuário e resultados recentes são preservados. Sem redução segura, o erro segue para o failover. Não se inferem esses códigos de texto livre.
- Etapa 6: respostas com códigos explícitos de modelo indisponível suspendem apenas esse par conexão/modelo por 30 minutos. Outros modelos continuam elegíveis. A suspensão persiste no banco; depois há uma única tentativa de recuperação, sem desabilitar permanentemente o provedor.
- Etapa 9: o chat passa a mostrar os eventos reais de redução de contexto e suspensão temporária, além de distinguir contexto excedido e modelo indisponível. Não indica entrega concluída por causa dessas ações.
- Laboratório: pedidos de navegador fora da prévia ativa recebem recusa explícita da política do ensaio, em vez de aguardarem indefinidamente. Instalações e promoções continuam exigindo revisão concreta. A recusa encerra a tentativa pela fronteira de permissão existente; não é autocorreção do trabalhador.

## Ensaio real sem Codex

Retomada do laboratório `lab-api-delegacao-20261031`, execução `27f9bbcd-9ca7-4299-88c0-2b0d18de1d96`, com as APIs configuradas na web acessadas somente por leitura. Primeiro segmento: limite de 16 chamadas/180 segundos, três chamadas realizadas, cancelamento pelo prazo com pedido de navegador pendente. Segundo: limite de dez chamadas/120 segundos, duas chamadas realizadas; o pedido para abrir localhost:5173 sem prévia correspondente foi recusado e a etapa falhou explicitamente.

Gemini retomou o ciclo e solicitou ferramentas de navegador; Groq voltou a rejeitar uma requisição. A rejeição observada continuou genérica: não se afirma que sua causa foi contexto ou modelo indisponível. Não houve evento real de compactação neste ensaio. As novas recuperações foram demonstradas em testes controlados, não homologadas por essa inferência real.

Nenhum arquivo da aplicação gerada foi escrito pelo avaliador. O banco do laboratório confirmou zero provedores Codex e zero credenciais persistidas. Não houve promoção de worktree, aplicação integrada, teste HTTP/Playwright independente ou aprovação do gate final. Evidências: `evidence/tasklab-segment-20261101-before-recovery.json`, `evidence/tasklab-segment-20261101-policy-boundary.json` e `evidence/tasklab-scope-20261101.json`.

## Validação e etapas restantes

62 testes direcionados de conectores/saúde/autonomia/ponte de APIs passaram; 93 de checkpoints, recuperação, promoção, delegação e aceitação passaram; após as últimas mudanças de observabilidade/política, 13 testes direcionados passaram. Frontend: 77 testes e build Vite aprovados. Esses testes não substituem a aceitação de um projeto gerado.

Regressão completa: **1.272 testes Python aprovados, 31 ignorados e dois avisos existentes**, em 266,80 segundos. Os 13 testes direcionados cobrem também as últimas mudanças do feed e da política do laboratório.

As 11 etapas continuam parcialmente concluídas conforme a matriz de 31/10. Permanecem: entrega full-stack e QA visual com reparo pela Central, delegação executada e integrada, concorrência/controles e retomada comprovados no projeto maior, homologação Claude/ACP pendente, avaliação real de memória e pedidos curtos, ciclo autenticado/revogação de integrações e execução de mídia no Motion Studio. Esta rodada avança as etapas 6, 7 e 9; não conclui a etapa 11.
