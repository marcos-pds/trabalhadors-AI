# PROJETO: CENTRAL DE TRABALHADORES IA — PLATAFORMA MULTIAGENTE INTELIGENTE

## MISSÃO PRINCIPAL

Atue como uma equipe de especialistas seniores em arquitetura de software, inteligência artificial, engenharia de agentes, sistemas distribuídos, UX/UI, frontend, backend, DevOps e segurança.

Desenvolva uma plataforma profissional chamada **Central de Trabalhadores IA**, capaz de conectar diferentes provedores de inteligência artificial, criar agentes especializados, distribuir tarefas automaticamente, executar trabalhos em paralelo, coordenar fluxos complexos e garantir continuidade operacional quando um agente ou provedor apresentar falhas.

Quero uma aplicação real e funcional, não apenas uma interface ilustrativa ou protótipo.

Se houver um projeto existente no workspace, investigue sua arquitetura e integre a Central de Trabalhadores IA de maneira modular, preservando suas funcionalidades e identidade visual. Caso não exista, crie uma aplicação independente preparada para futuras integrações.

O sistema deve proporcionar uma experiência moderna, elegante e intuitiva, com destaque para um chat inteligente e dinâmico.

---

# FASE 1 — ARQUITETURA MULTIAGENTE

Crie uma arquitetura baseada em orquestração inteligente de agentes.

Estrutura principal:

USUÁRIO → CHAT → ORQUESTRADOR → PLANEJADOR → TRABALHADORES IA → REVISOR → CONSOLIDADOR → RESULTADO

## Orquestrador central

Responsabilidades:

1. Receber solicitações do usuário.
2. Interpretar o objetivo.
3. Identificar a complexidade.
4. Dividir tarefas em subtarefas.
5. Identificar dependências entre tarefas.
6. Selecionar agentes especializados.
7. Escolher modelos de IA adequados.
8. Executar tarefas independentes em paralelo.
9. Controlar limites de concorrência.
10. Monitorar execução, desempenho e custos.
11. Detectar erros e indisponibilidades.
12. Acionar substituições automáticas.
13. Validar e reunir os resultados.
14. Exibir o andamento no chat em tempo real.
15. Solicitar aprovação humana quando necessário.

Utilize uma arquitetura extensível com componentes separados para orquestração, execução, persistência, integração de provedores e interface.

Não crie dependências rígidas de um único fornecedor de IA.

---

# FASE 2 — INTEGRAÇÃO COM DIFERENTES INTELIGÊNCIAS ARTIFICIAIS

Desenvolva uma camada de conectores para múltiplos provedores e modelos.

Avalie integrações com:

- OpenAI.
- Anthropic Claude.
- Google Gemini.
- DeepSeek.
- xAI Grok.
- Mistral.
- Modelos open source executados localmente.
- Ollama.
- Provedores compatíveis com APIs de modelos.

Não assuma que todos os serviços possuem as mesmas funcionalidades, preços, limites ou permissões.

Cada integração deve ser habilitada somente quando existir API oficial ou mecanismo autorizado, com credenciais válidas.

## Cadastro de modelos

O administrador deve conseguir:

- Cadastrar e conectar provedores.
- Adicionar credenciais de API.
- Testar conexões.
- Consultar modelos disponíveis quando a API permitir.
- Ativar ou desativar modelos.
- Configurar prioridade.
- Definir limites de gastos.
- Definir modelos preferenciais.
- Configurar modelos de reserva.
- Associar modelos a especialidades.

Armazene credenciais de forma segura, sem expô-las no frontend, nos logs ou nas respostas dos agentes.

Exiba informações reais sobre disponibilidade e capacidade de cada provedor. Nunca invente status ou medições.

---

# FASE 3 — CRIAÇÃO DE TRABALHADORES IA

Crie um módulo chamado **Trabalhadores IA**.

Cada trabalhador deve ter:

- Nome.
- Avatar.
- Especialidade.
- Descrição.
- Instruções de sistema.
- Modelo principal.
- Modelos de reserva.
- Ferramentas autorizadas.
- Permissões.
- Limite de tarefas simultâneas.
- Limite de gastos.
- Histórico de execução.
- Indicadores de desempenho.
- Status operacional.

## Trabalhadores iniciais sugeridos

**1. Arquiteto IA**

Planejamento técnico, arquitetura, decomposição de problemas e design de sistemas.

**2. Frontend IA**

Interfaces modernas, React, componentes, responsividade, acessibilidade, animações e experiência do usuário.

**3. Backend IA**

Servidores, autenticação, APIs, bancos de dados, integrações e regras de negócio.

**4. Designer IA**

Layouts, componentes visuais, design systems, microinterações e identidade de produto.

**5. Programador IA**

Implementação de código e integração de funcionalidades.

**6. Revisor IA**

Revisão de código, validação de resultados, testes e identificação de defeitos.

**7. Pesquisador IA**

Pesquisa técnica, documentação e comparação de tecnologias.

**8. DevOps IA**

Configuração de ambientes, pipelines, infraestrutura e diagnóstico operacional.

**9. Vídeo e Legendas IA**

Transcrição, sincronização, estilos de legendas, processamento de vídeo e efeitos.

**10. Coordenador IA**

Supervisão dos demais trabalhadores, controle de prioridades e consolidação dos resultados.

Permita criar trabalhadores personalizados, clonar configurações, editar especialidades e associar várias capacidades a um único trabalhador.

Não obrigue cada trabalhador a utilizar um modelo diferente. Diferentes agentes podem utilizar o mesmo modelo com instruções, ferramentas e responsabilidades distintas.

---

# FASE 4 — SELEÇÃO INTELIGENTE DE IA POR ESPECIALIDADE

Implemente um mecanismo de roteamento inteligente.

Quando uma tarefa chegar, o orquestrador deverá avaliar:

- Tipo e dificuldade da tarefa.
- Especialidade necessária.
- Ferramentas exigidas.
- Capacidades suportadas pelo modelo.
- Desempenho histórico.
- Latência observada.
- Custo estimado.
- Disponibilidade.
- Limites de uso.
- Privacidade e sensibilidade dos dados.
- Preferências do usuário.

Exemplo:

O usuário solicita:

"Crie uma página de dashboard com login, gráficos e banco de dados."

O sistema deverá:

1. Acionar o Arquiteto para preparar a implementação.
2. Delegar layout ao Designer.
3. Delegar componentes ao Frontend.
4. Delegar API e persistência ao Backend.
5. Coordenar interfaces e contratos de dados.
6. Encaminhar o resultado ao Revisor.
7. Executar testes.
8. Apresentar a entrega consolidada.

As tarefas independentes devem ser executadas simultaneamente quando isso for seguro.

O usuário poderá escolher entre:

- Seleção automática de agente.
- Seleção manual.
- Equipe de agentes.
- Modelo específico.
- Modo econômico.
- Modo equilibrado.
- Modo de máxima qualidade.

---

# FASE 5 — SISTEMA DE FAILOVER AUTOMÁTICO

Esta funcionalidade é obrigatória.

Se uma IA parar de responder, exceder o tempo limite ou ficar indisponível, o sistema deve tentar continuar a execução utilizando um modelo alternativo compatível.

## Regras de failover

Detectar e classificar:

- Timeout.
- Erro de rede.
- Indisponibilidade temporária.
- Rate limit.
- Erro de autenticação.
- Falta de créditos.
- Falha de ferramenta.
- Resposta inválida.
- Interrupção de execução.

Não tratar todas as falhas da mesma maneira.

Por exemplo, erros de credenciais e falta de créditos devem bloquear ou desativar aquele provedor até que a situação seja corrigida, em vez de provocar tentativas infinitas.

## Estratégias técnicas

Implementar:

1. Timeouts configuráveis.
2. Retries com exponential backoff e jitter.
3. Circuit breaker.
4. Health checks.
5. Modelos de reserva ordenados por compatibilidade.
6. Limites de tentativas.
7. Persistência de tarefas.
8. Checkpoints.
9. Filas duráveis.
10. Idempotência.
11. Dead-letter queue para falhas não recuperáveis.
12. Cancelamento e retomada.
13. Proteção contra loops de reexecução.

## Continuidade contextual

Antes de transferir uma tarefa para outra IA:

- Salve o estado atual.
- Preserve resultados parciais válidos.
- Registre subtarefas concluídas.
- Identifique operações pendentes.
- Resuma o contexto necessário.
- Preserve referências a arquivos e artefatos.
- Transfira somente os dados permitidos pelas regras de segurança.
- Evite repetir ações externas já realizadas.

Caso uma tarefa tenha falhado durante uma operação com efeitos externos, confirme seu resultado antes de reexecutá-la.

Exemplo:

Uma IA começou a desenvolver um componente React e parou.

O orquestrador deve disponibilizar ao agente de reserva os arquivos modificados, o contexto e o estado da tarefa para que continue sem refazer todo o trabalho.

Se não houver modelo compatível disponível, mantenha a tarefa em estado recuperável e informe o usuário.

Nunca declare que houve transferência bem-sucedida antes da confirmação.

---

# FASE 6 — MOTOR DE FLUXOS DE TRABALHO

Crie um editor visual de fluxos.

O usuário deverá conseguir montar automações conectando blocos.

Tipos de blocos:

- Entrada de usuário.
- Agente IA.
- Ferramenta.
- Condição.
- Aprovação humana.
- Execução paralela.
- Espera.
- Transformação de dados.
- Revisão.
- Saída.
- Tratamento de erros.

## Fluxos suportados

**Fluxo sequencial**

Agente A → Agente B → Agente C.

**Fluxo paralelo**

Agentes A, B e C executam trabalhos independentes simultaneamente.

**Fluxo condicional**

O sistema escolhe um caminho conforme as regras ou resultados.

**Fluxo de revisão**

Um trabalhador executa e outro valida.

**Fluxo de recuperação**

Quando um agente falha, o sistema decide entre tentar novamente, trocar o modelo ou solicitar intervenção humana.

**Fluxo com aprovação**

A execução fica pausada até o usuário autorizar uma operação sensível.

Permita salvar fluxos, duplicá-los, editá-los, versioná-los e reutilizá-los em diferentes projetos.

Use um modelo de execução baseado em estados persistidos, suportando grafos de dependências e evitando ciclos infinitos.

---

# FASE 7 — FRONTEND PREMIUM E ESTILOSO

Desenvolva uma interface moderna e de alto padrão.

A experiência visual deve transmitir a sensação de uma central de operações de inteligência artificial.

Se o Estúdio já possuir identidade visual, preserve-a e evolua seus componentes de maneira consistente.

Caso seja um projeto independente, utilize uma direção visual premium com:

- Tema escuro elegante.
- Tema claro.
- Tons de grafite e superfícies com boa hierarquia.
- Acentos em azul, violeta ou ciano.
- Bordas discretas.
- Tipografia moderna.
- Microanimações suaves.
- Componentes responsivos.
- Ícones consistentes.
- Estados visuais informativos.
- Contraste e acessibilidade adequados.

Evite efeitos visuais excessivos que prejudiquem a legibilidade ou o desempenho.

## Navegação principal

Criar:

1. Dashboard.
2. Chat IA.
3. Trabalhadores.
4. Fluxos.
5. Projetos.
6. Histórico.
7. Monitoramento.
8. Provedores.
9. Configurações.

### Dashboard

Exibir indicadores reais:

- Trabalhadores ativos.
- Tarefas em execução.
- Tarefas concluídas.
- Falhas recuperadas.
- Tempo de execução.
- Gastos por modelo.
- Saúde dos provedores.
- Filas pendentes.

Adicionar gráficos, indicadores e histórico de atividade.

Não utilizar números fictícios apresentados como dados reais.

---

# FASE 8 — CHAT DINÂMICO MULTIAGENTE

O chat será o centro da experiência.

Crie uma interface moderna, fluida, responsiva e visualmente atraente.

## Recursos obrigatórios

- Conversas em tempo real.
- Respostas progressivas por streaming.
- Markdown.
- Blocos de código.
- Destaque de sintaxe.
- Botão para copiar código.
- Upload de arquivos.
- Histórico persistente.
- Busca em conversas.
- Regeneração de respostas.
- Edição de mensagens.
- Cancelamento de execução.
- Seleção de agente.
- Seleção de equipe.
- Seleção de modelo.
- Indicadores de execução.
- Identificação do agente que está respondendo.
- Mensagens de erro e recuperação.
- Visualização dos resultados de ferramentas.
- Pré-visualização de artefatos compatíveis.

## Chat com vários trabalhadores

Quando uma tarefa envolver vários agentes, o chat deverá mostrar claramente a participação de cada trabalhador.

Exemplo:

Usuário: "Crie uma tela de login profissional."

Arquiteto IA: "Defini a estrutura e os requisitos."

Designer IA: "Preparei a proposta visual."

Frontend IA: "Implementei os componentes."

Revisor IA: "Validei os requisitos e os testes."

Coordenador IA: "Aqui está o resultado consolidado."

Essas mensagens devem refletir eventos reais dos agentes e não ser meramente simuladas.

## Interface do chat

Criar:

**Painel esquerdo**
- Conversas.
- Projetos.
- Equipes de agentes.
- Fluxos favoritos.

**Área central**
- Conversação.
- Respostas em streaming.
- Código e artefatos.
- Resultado final consolidado.

**Painel direito opcional**
- Trabalhadores ativos.
- Etapas da execução.
- Progresso.
- Modelos utilizados.
- Consumo de tokens e custos quando disponíveis.
- Eventos relevantes.
- Falhas e recuperações.

Permitir recolher painéis para ampliar a área da conversa.

---

# FASE 9 — ANIMAÇÃO DE ESTADOS E ATIVIDADES

Crie indicadores visuais que representem o andamento real do sistema.

Estados sugeridos:

- Disponível.
- Planejando.
- Executando.
- Aguardando dependência.
- Revisando.
- Aguardando aprovação.
- Pausado.
- Concluído.
- Falhou.
- Em recuperação.

Ao ocorrer um failover, exibir um evento discreto e compreensível.

Exemplo:

"Modelo principal indisponível. Retomando a tarefa com um modelo alternativo."

O chat deve continuar apresentando os resultados assim que o novo trabalhador estiver operacional.

Adicionar transições suaves, indicadores de atividade, skeletons e animações de progresso.

Utilizar SSE ou WebSockets, conforme a arquitetura, para transmitir eventos reais do backend.

Garantir reconexão, recuperação de eventos perdidos e consistência visual após atualizar a página.

---

# FASE 10 — MEMÓRIA, CONTEXTO E COLABORAÇÃO

Implemente memória contextual por projeto e por execução, respeitando permissões.

Os agentes devem compartilhar apenas os dados necessários para sua tarefa.

Criar:

- Contexto da conversa.
- Contexto do projeto.
- Documentação de decisões.
- Artefatos produzidos.
- Histórico de alterações.
- Checkpoints.
- Resumos de tarefas.
- Estado das dependências.

Não compartilhe automaticamente informações sensíveis entre provedores sem autorização e políticas claras.

Use armazenamento estruturado e recuperação semântica quando houver necessidade comprovada.

Evite encaminhar todo o histórico para cada chamada de IA, reduzindo custos e melhorando eficiência.

---

# FASE 11 — SEGURANÇA E CONTROLE

Implementar:

- Autenticação.
- Controle de acesso por permissões.
- Isolamento entre usuários e projetos.
- Criptografia de credenciais.
- Segredos somente no backend.
- Validação de entradas.
- Proteção contra prompt injection.
- Controle de acesso a ferramentas.
- Sandboxing para execução de código.
- Auditoria de operações.
- Limites de gastos.
- Limites de concorrência.
- Aprovação para operações irreversíveis.

Nenhum agente deve possuir acesso irrestrito a arquivos, bancos de dados, contas externas ou infraestrutura por padrão.

Ações como excluir dados, publicar conteúdo, efetuar pagamentos ou alterar produção devem exigir aprovação explícita.

---

# FASE 12 — PERFORMANCE E CUSTOS

O sistema deve utilizar os recursos disponíveis de maneira eficiente.

Crie um roteador de tarefas que considere custo, qualidade e latência.

Exemplo:

- Tarefas simples: modelo econômico adequado.
- Programação complexa: modelo com melhor desempenho em código.
- Pesquisa: agente com ferramentas de busca autorizadas.
- Revisão: modelo apropriado para verificação independente.
- Tarefas sensíveis: provedor autorizado pela política de dados.

Implemente controle de orçamento por usuário, projeto, fluxo e trabalhador.

Exiba estimativas quando possível e gastos efetivos quando confirmados.

Não repita tarefas caras desnecessariamente.

Reutilize resultados válidos quando seguro.

---

# FASE 13 — STACK TECNOLÓGICA

Primeiro examine a arquitetura do projeto.

Priorize as tecnologias já utilizadas no workspace.

Para uma implementação independente, avalie:

**Frontend**
- React e TypeScript.
- Next.js ou Vite, conforme a necessidade.
- Tailwind CSS.
- Biblioteca de componentes acessíveis.
- React Flow ou alternativa adequada para fluxos.
- Sistema de animações leve.

**Backend**
- Node.js/TypeScript ou Python.
- API modular.
- Camada de abstração de provedores.
- Workers de execução.
- Orquestração de fluxos.

**Persistência e mensageria**
- PostgreSQL.
- Redis, quando necessário.
- Fila durável adequada à stack.
- Armazenamento de artefatos.
- Sistema de eventos.

**IA e observabilidade**
- SDKs oficiais dos provedores.
- Framework de agentes apenas quando justificar sua complexidade.
- Logs estruturados.
- Rastreamento distribuído.
- Métricas de latência, custos e falhas.

Não introduza serviços desnecessários. Justifique as decisões arquiteturais antes de criar dependências importantes.

---

# FASE 14 — TESTES OBRIGATÓRIOS

Teste o sistema completo.

## Teste A — Seleção automática

Envie uma tarefa de frontend e verifique se o roteador seleciona um agente compatível.

## Teste B — Trabalho em paralelo

Envie uma tarefa envolvendo frontend e backend.

Comprove que as partes independentes executam simultaneamente e que a consolidação respeita as dependências.

## Teste C — Falha de provedor

Simule uma falha no modelo principal.

Verifique:

1. Detecção da falha.
2. Classificação correta.
3. Seleção de modelo compatível.
4. Transferência do estado.
5. Continuidade ou retomada segura.
6. Preservação dos resultados válidos.
7. Notificação ao usuário.

## Teste D — Limite de gastos

Configure um orçamento pequeno e confirme que o sistema impede novas operações que excederiam o limite definido.

## Teste E — Persistência

Inicie uma tarefa, atualize a página e verifique se seu estado e eventos continuam consistentes.

## Teste F — Revisão

Introduza uma resposta incorreta em ambiente controlado e confirme que o revisor detecta o problema segundo critérios definidos.

## Teste G — Segurança

Confirme que trabalhadores sem permissões não conseguem acessar ferramentas, credenciais ou informações de outros usuários.

## Teste H — Chat

Valide streaming, cancelamento, reconexão, histórico, erros, visualização de artefatos e funcionamento em dispositivos móveis.

---

# FASE 15 — ORDEM DE DESENVOLVIMENTO

Desenvolva de forma incremental.

**Etapa 1 — Base funcional**
- Arquitetura do sistema.
- Autenticação.
- Integração inicial de provedores.
- Chat real com streaming.
- Persistência de conversas.
- Cadastro de trabalhadores.

**Etapa 2 — Orquestração**
- Planejamento e divisão de tarefas.
- Roteamento por especialidade.
- Execução paralela.
- Dependências.
- Consolidação e revisão.

**Etapa 3 — Resiliência**
- Tratamento de falhas.
- Failover.
- Filas persistentes.
- Checkpoints.
- Retomada de tarefas.

**Etapa 4 — Interface avançada**
- Dashboard.
- Editor visual de fluxos.
- Painel de trabalhadores.
- Monitoramento em tempo real.
- Experiência responsiva.

**Etapa 5 — Qualidade**
- Testes automatizados.
- Auditoria de segurança.
- Testes de carga.
- Otimização.
- Documentação.

Ao concluir cada etapa, execute testes e corrija regressões antes de continuar.

---

# CRITÉRIOS DE ACEITAÇÃO

Considere o sistema concluído somente quando:

1. Usuários conseguirem cadastrar provedores autorizados.
2. O chat funcionar com modelos reais e credenciais válidas.
3. Agentes especializados puderem ser criados e configurados.
4. O orquestrador conseguir dividir uma tarefa complexa.
5. Subtarefas independentes puderem executar em paralelo.
6. Modelos puderem ser selecionados manual ou automaticamente.
7. Falhas recuperáveis acionarem modelos de reserva compatíveis.
8. Os resultados parciais forem preservados corretamente.
9. Houver controle efetivo de gastos, permissões e concorrência.
10. O chat mostrar estados e eventos reais.
11. Fluxos puderem ser criados, executados e acompanhados.
12. Os testes de recuperação e persistência forem aprovados.
13. A interface for responsiva e visualmente consistente.
14. O sistema não apresentar integrações simuladas como se fossem reais.
15. Houver documentação de instalação, configuração e operação.

Se não existirem credenciais de provedores, implemente a infraestrutura, disponibilize uma configuração de conexão e use mocks explicitamente identificados somente para testes. Não afirme que executou chamadas reais sem fazê-las.

## INSTRUÇÃO FINAL

**Não entregue apenas um documento, wireframe, telas estáticas ou código incompleto.**

Examine o repositório existente, planeje a arquitetura e desenvolva progressivamente os módulos.

Implemente um produto utilizável, com frontend premium, backend funcional, comunicação em tempo real, sistema de agentes, orquestrador inteligente, motor de fluxos e failover.

Adote o princípio:

**UM USUÁRIO → VÁRIOS TRABALHADORES → UM RESULTADO COORDENADO.**

A plataforma deve escolher a IA mais adequada, distribuir o trabalho, recuperar-se de falhas, preservar o progresso e mostrar tudo de forma clara em um chat moderno.

Priorize funcionamento real, confiabilidade, segurança, qualidade visual e facilidade de expansão.