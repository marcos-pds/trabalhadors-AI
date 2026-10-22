# Central de Trabalhadores IA

**Versão 0.1.0 — MVP funcional, local e extensível.**

Plataforma multiagente em português: autenticação, chat com streaming SSE, agentes especializados, provedores com chaves criptografadas, roteamento por especialidade, execução paralela, dependências, modelos de reserva, retomada de checkpoints, fluxos persistidos e aprovação humana.

> **Importante:** o projeto implementa uma primeira versão **real**, mas **não** cumpre integralmente as 15 fases da especificação. Consulte a seção "Funcionalidades e limitações". O código não contém integrações falsas em produção. Para obter respostas de IA, você precisa conectar APIs com acesso válido. Os testes automatizados usam provedores simulados **somente nos testes**.

## Instalação no Windows (recomendado)

1. Extraia o ZIP em uma pasta de sua escolha, como `C:\Projetos\central-trabalhadores-ia`.
2. Instale **Python 3.11 ou mais recente** de https://www.python.org/downloads/ (marque *Add Python to PATH*).
3. Dê dois cliques em **`iniciar_windows.bat`** e permita a instalação das dependências na primeira execução.
4. Abra o navegador no endereço **http://127.0.0.1:8765**.
5. Crie uma conta local (senha de pelo menos 10 caracteres) e vá até **Provedores → Conectar provedor**.
6. Selecione seu provedor, informe o identificador **exato** de um modelo disponível em sua conta e a sua chave de API. Depois, clique em **Testar**.
7. Abra **Chat IA**, envie uma solicitação e acompanhe o processamento de cada trabalhador.

O arquivo `iniciar_windows.bat` usa um ambiente virtual (`.venv`), sem instalar pacotes globalmente. Não publique a aplicação diretamente na internet.

### Instalação manual (Windows PowerShell)

```powershell
cd C:\Projetos\central-trabalhadores-ia
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

### Linux / macOS

```bash
cd central-trabalhadores-ia
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Acesse `http://127.0.0.1:8765`. A aplicação utiliza somente a interface de loopback por padrão.

## Estrutura

```text
central-trabalhadores-ia/
├── central/
│   ├── main.py            # Rotas HTTP, autenticação e SSE
│   ├── engine.py          # DAG, especialidades, paralelismo, revisão, failover
│   ├── providers.py       # OpenAI-compatible, Anthropic e Gemini
│   ├── security.py        # Sessões e credenciais criptografadas
│   └── database.py        # SQLite persistente / eventos
├── static/
│   ├── index.html
│   ├── style.css          # UI premium responsiva, temas escuro/claro
│   └── app.js             # SPA sem build/dependências npm
├── tests/test_app.py      # Testes de integração controlados
├── run.py                 # Ponto de entrada local
├── iniciar_windows.bat    # Iniciador Windows
├── requirements.txt
└── ESPECIFICACAO.md       # Documento original fornecido
```

**Stack:** FastAPI / Python 3.11+, SQLite (WAL), httpx, Fernet, HTML/CSS/JS sem bundler. A escolha de frontend sem React reduz a quantidade de dependências e permite executar imediatamente via Python. Para escalar para uma equipe e milhões de tarefas, é necessário evoluir a arquitetura para filas externas e workers distribuídos.

## Provedores e modelos

| Tipo | API usada | Observações |
| --- | --- | --- |
| OpenAI | `/v1/chat/completions` SSE | Modelo configurado manualmente |
| Anthropic | `/v1/messages` SSE | Chave com permissão para o modelo |
| Google Gemini | `:streamGenerateContent?alt=sse` | Chave Gemini API |
| DeepSeek | Endpoint compatível com OpenAI | Modelo configurado manualmente |
| Grok / xAI | Endpoint compatível com OpenAI | Modelo configurado manualmente |
| Mistral | Endpoint compatível com OpenAI | Modelo configurado manualmente |
| Ollama | OpenAI-compatible local em `127.0.0.1:11434/v1` | Ollama deve estar rodando separadamente |
| Outros | API compatível com OpenAI | URL HTTPS configurada manualmente |

A aplicação **não procura preços ou disponibilidade em tempo real**; prioridades e modelos são configurados pelo usuário. `Testar` faz uma pequena chamada real e pode gerar custos no provedor. APIs podem mudar, e é necessário validar cada integração com credenciais reais antes de usá-la em produção.

### Como o sistema trabalha

1. Recebe um pedido no chat e grava a conversa.
2. Classifica por palavras-chave e especialidades habilitadas; admite seleção manual.
3. Cria um grafo persistente de tarefas independentes.
4. Executa especialistas em paralelo com um limite global de 5 e limite por trabalhador.
5. Quando há mais de um especialista, adiciona automaticamente um **Revisor IA** dependente das entregas anteriores, se o agente estiver habilitado.
6. Cada tarefa tenta o provedor preferido e depois outros provedores ativados; registra eventos, tentativas e erros.
7. Se uma tarefa falhar, o usuário pode configurar outro modelo e clicar em **Histórico → Retomar**; os nós já concluídos são preservados.
8. Transmite eventos e tokens via SSE; o resultado consolidado aparece no histórico.

**Regras de falha:** HTTP 401/403 e falta de créditos desabilitam o provedor; 429, timeouts e respostas HTTP 5xx têm tentativas limitadas. Retries fazem backoff com pequeno jitter; o circuit breaker temporário existe por processo. Nenhuma ferramenta externa com efeitos irreversíveis é executada nesta versão.

## Funcionalidades e limitações

| Funcionalidade | Situação nesta versão |
| --- | --- |
| Cadastro, login e sessões por conta | ✅ Funcional |
| Armazenamento criptografado de chaves de IA | ✅ Funcional (Fernet) |
| Cadastro e edição de agentes | ✅ Funcional |
| 10 perfis iniciais especializados | ✅ Funcional |
| Chat com eventos e tokens progressivos | ✅ SSE funcional |
| Upload de texto/código, até 2 MB | ✅ Funcional; excertos enviados ao modelo |
| Seleção automática por especialidade | ✅ Heurística funcional, não LLM planner |
| Seleção manual, prioridade de provedores | ✅ Funcional |
| Múltiplos especialistas em paralelo e revisão dependente | ✅ Funcional |
| Failover e recuperação após falha | ✅ Funcional; substituição entre provedores e retomada manual |
| Persistência, checkpoints, eventos e retomada após reinício | ✅ Funcional para tarefas só de texto |
| Fluxos com grafo de agentes / aprovações | ✅ Funcional para os dois tipos de nó |
| Projetos para organizar conversas | ✅ Cadastro e associação básica |
| Histórico e painel de monitoramento | ✅ Funcional com medições locais |
| Orçamento por tarefa | ⚠ Verificação de estimativa, sem garantia de faturamento máximo |
| Precificação oficial, latência observada, health check periódico | ❌ Não implementado |
| Agentes capazes de modificar repositórios e executar ferramentas | ❌ Não implementado |
| Editor avançado de nós condicionais, transformações, ferramentas, esperas | ❌ Não implementado |
| Busca semântica, embeddings e memória RAG | ❌ Não implementado |
| Work queues externas, escalabilidade entre máquinas | ❌ Não implementado |
| Logs distribuídos, métricas históricas e tracing | ❌ Não implementado |
| Sandboxing para execução de código e navegador remoto | ❌ Não implementado |
| Segurança de implantação multi-tenant na internet | ❌ Requer auditoria, rate limit, TLS e infraestrutura adequada |

### Avisos de segurança

- **Uso local:** não exponha o serviço em uma interface de rede pública, nem abra a porta 8765 no firewall. Caso precise implantar em produção, configure HTTPS/TLS, gestão centralizada de segredos, rate limiting, proteção de rede, backups, observabilidade e auditoria.
- A pasta `data/` guarda as contas, conversas, API keys criptografadas e a **chave mestre** `secret.key`. **Faça backup da pasta inteira e nunca publique-a no GitHub.** Se perder `secret.key`, não será possível descriptografar as chaves já armazenadas.
- O frontend não tem acesso às chaves de API; somente o backend realiza chamadas aos provedores.
- Nunca conceda ao aplicativo chaves com privilégios desnecessários. Conteúdos enviados no chat podem ser transmitidos aos provedores habilitados, inclusive durante failover.
- O editor atual não executa scripts arbitrários nem comandos shell inseridos por agentes. Agentes apenas **geram texto**.
- Custo apresentado na interface é **estimado pelo tamanho do texto** e pelas tarifas informadas por você. Não equivale a cobranças reais do provedor. Um orçamento estimado não oferece corte de gasto exato, sobretudo para tarefas paralelas.

## Testes

```bash
python -m pytest -q tests/test_app.py
```

Os testes usam fakes apenas na suíte automatizada (zero chamadas a provedores externos), cobrindo autenticação/isolamento, paralelismo real, dependências de revisão, failover, aprovação, orçamento estimado, validação de grafos, sigilo das chaves e retomada após falha.

## Personalizações e extensões

- Altere os prompts de sistema em **Trabalhadores → Configurar**.
- Informe um provedor preferencial por agente ou deixe **Automático** para utilizar a prioridade global.
- Crie fluxos sequenciais ou paralelos em **Fluxos → Criar fluxo**, depois escolha **Usar no chat**.
- A API apresenta documentação Swagger em `http://127.0.0.1:8765/docs`.
- Um deployment público deve **não** reutilizar diretamente as credenciais e banco da instalação de desenvolvimento.

**Especificação original:** `ESPECIFICACAO.md`. Este pacote é o primeiro incremento concreto rumo ao produto completo descrito naquele documento.


## Pastas de projetos locais (PR: Estúdio de Arquivos)

### Criar um projeto DIRETAMENTE pelo Chat IA

Após configurar o caminho fixo no Windows, basta pedir no **Chat IA**:
"Crie a estrutura inicial de uma loja virtual com frontend React e backend FastAPI".
Ao identificar explicitamente uma solicitação de criação de projeto, a Central:
- cria automaticamente o registro de Projeto e a pasta isolada em `C:\Projetos\Central-IA\...`, vinculando a conversa;
- quando ambos **React** e **FastAPI** estiverem no pedido, cria automaticamente um **starter local funcional** (README, FastAPI de produtos mockados, React + Vite + TS, CSS e configs) mesmo se o modelo de IA retornar conteúdo truncado;
- solicita aos trabalhadores manifestos JSON `central-files` completos e aceita JSON direto quando válido;
- cria automaticamente **somente novos arquivos** gerados pelos trabalhadores com manifesto completo e validado; alterações/sobrescritas/exclusões continuam pendentes no painel Arquivos;
- informa diretamente no Chat IA a pasta criada, novos arquivos e erros de geração (por exemplo JSON incompleto).

**Atenção:** a criação automática do projeto é baseada em um pedido explícito (ex.: "crie projeto", "crie estrutura inicial", "desenvolva loja virtual"). Conversas explicativas comuns não recebem pastas automaticamente. O starter React+FastAPI é um template local de demonstração, não código produzido por um modelo; o chat multiagente pode acrescentar funcionalidades após gerar manifestos válidos.

O limite de saída por chamada de IA para projetos aumenta de 1400 para 4096 tokens (quando suportado pelo provedor). Se a geração exceder esse limite, solicite arquivos em etapas menores. **Nunca interpretamos JSON truncado como arquivo completo, nem executamos código automaticamente.**


A Central pode preparar uma subpasta privada para cada **Projeto** em `C:\Projetos\Central-IA` no Windows (sem permissões irrestritas a todo o disco). A raiz pode ser configurada **somente pelo administrador do processo** com a variável de ambiente `CENTRAL_WORKSPACE_ROOT`; isso também facilita testes em Linux. Reinicie o servidor após alterar a variável. Não selecione uma pasta sincronizada por terceiros ou compartilhada com usuários não confiáveis.

1. Abra **Projetos → Criar projeto → Arquivos** (ou o menu **Arquivos**) e clique em **Criar pasta autorizada**. A Central cria `C:\Projetos\Central-IA\<nome>-<id>`; uma pasta já existente não é assumida automaticamente.
2. Use **Novo arquivo**, **Abrir arquivo → Propor edição**, ou **Propor exclusão**. Todas as ações produzem **propostas**, sem alterar arquivos ainda.
3. Para **edições manuais, substituições e exclusões**, revise o **diff textual** em **Alterações aguardando revisão**. Para gravar, digite `APLICAR` e clique em **Aplicar arquivos**. **Arquivos novos** produzidos por chat com manifesto completo são criados automaticamente dentro do projeto autorizado. Se o arquivo mudar após a prévia, a aplicação manual é recusada e exige nova proposta.
4. Use **Trabalhar com agentes** para iniciar uma conversa **vinculada** ao projeto; no modo **Equipe**, especialistas podem trabalhar em paralelo e passar o resultado ao Revisor. Para gerar arquivos reais, solicite que entreguem os arquivos completos. O servidor extrai automaticamente blocos `central-files` válidos dos resultados concluídos, valida limites e prepara as propostas para sua revisão. **Arquivos novos e válidos são criados automaticamente; substituir ou excluir arquivos existentes exige sua aprovação explícita**.
5. Consulte as propostas no painel **Arquivos** após cada execução. Nem todas as respostas de modelos são JSON correto: se não surgir proposta, solicite novamente que o agente produza um bloco `central-files` válido (JSON), ou crie a proposta manualmente.

### Segurança e limitações

- Somente caminhos **relativos ao diretório do projeto** são aceitos; `..`, caminhos absolutos, letras de unidade, caminhos especiais do Windows, links simbólicos, junções, hardlinks, `.env*`, chaves privadas, pastas como `.git` e arquivos binários não são permitidos.
- Conteúdo limitado a **160 KB por arquivo**, até **20 arquivos por proposta**, no máximo 1 MB por proposta. O explorador lista no máximo 300 arquivos, até 7 níveis. Propostas/decisões ficam persistidas no SQLite; credenciais de API não são incluídas.
- Na conversa vinculada, trechos **pequenos** de arquivos visíveis podem ser enviados ao provedor de IA conectado; **não coloque segredos** nos projetos autorizados. O painel mostra esse aviso.
- Visualização é um **diff textual**, não execução de HTML nem um navegador incorporado. **Não existe execução de shell, instalação de dependências, deploy, Git automático ou renderização do projeto** nesta fase. Isso requer ferramentas e autorizações separadas.
- A aplicação de um conjunto de arquivos faz uma pré-checagem de versões e tenta recuperar alterações anteriores em caso de erro. Sistemas de arquivos não são transacionais: faça backup/Git antes de aprovar mudanças importantes. A Central não permite escolher uma pasta arbitrária por mensagem, apenas subpastas autorizadas.
- Os provedores atuais possuem um limite de saída em tokens; projetos grandes devem ser desenvolvidos em etapas. A qualidade dos arquivos é responsabilidade dos agentes e da revisão humana, não garantida por esta integração.


## Skills UX/UI e delegação controlada ao Arquiteto IA

A aba **Skills UX/UI** permite ativar por projeto o guia interno **UI/UX Studio Pro**. Ele enriquece o contexto dos trabalhadores Frontend, Designer, Programador, Arquiteto e Revisor com práticas de UX, acessibilidade, design system, Tailwind 4, shadcn/ui, Lucide, Motion e testes visuais. É uma **skill local de instruções**, não um cliente MCP externo nem um instalador automático de shadcn/ui; não existem comandos arbitrários nem screenshots de Playwright nesta fase.

### Delegar autoridade via chat ou botão

Abra uma conversa **vinculada a um projeto com pasta preparada** e use o botão **Arquiteto: autorizar**, confirmando a permissão; ou envie, como uma mensagem isolada e literal, o seguinte comando:

    Autorizo o Arquiteto IA a aprovar alterações e instalar pacotes permitidos neste projeto.

A autorização fica persistida **somente naquela conversa/projeto**; outras conversas não herdam os poderes. Para revogar, clique novamente no botão ou envie:

    Revogo a autonomia do Arquiteto IA.

O backend interpreta somente essas declarações explícitas **do usuário autenticado**, não instruções embutidas em arquivos ou respostas de modelos.

Com a autorização ativa, as propostas de alteração de arquivos **comuns de código** criadas pelos agentes podem ser revisadas em uma chamada independente ao Arquiteto IA. Ele recebe o diff e deve responder JSON com decisão e justificativa. Se aprovar, o servidor compara a versão original, grava e registra o motivo da decisão no SQLite. Na dúvida, erro, ausência de provedor, diff grande, exclusão, arquivo de configuração sensível ou autorização revogada, **a proposta continua aguardando sua aprovação**.

### Instalação autorizada de bibliotecas

O Arquiteto pode solicitar pacotes **apenas de um catálogo estático** através do bloco de texto estruturado central-packages (JSON completo). Suporte atual: npm no diretório frontend (Tailwind CSS, Lucide, Motion, Radix, clsx, Playwright como biblioteca) e pip no virtualenv backend (httpx, pytest, SQLAlchemy, Pydantic, python-multipart). Limite de cinco pacotes por bloco e uma transação por execução.

- **npm**: comando interno com argumentos fixos, diretório fixo, registry oficial, sem shell, audit nem lifecycle scripts (--ignore-scripts). Instalação altera package.json/package-lock.json; é uma alteração autorizada especificamente pelo usuário ao delegar pacotes.
- **pip**: requer um virtualenv backend/.venv existente, instala apenas pacotes wheel do PyPI oficial, sem entrada interativa e sem shell.
- Instalar dependências **envolve riscos** mesmo sem scripts, pode consumir rede/disco e instalar código de terceiros. Faça backup ou crie commits Git antes. No ambiente de produção, prefira versões travadas e revisões de dependências.
- O Arquiteto **não pode executar npm run, pip install de nome arbitrário, npx shadcn, comandos PowerShell, scripts pós-instalação, exclusões automáticas ou acessar fora do projeto**.
- O histórico das instalações fica na aba **Skills UX/UI**; as decisões de aprovação do Arquiteto ficam registradas na tabela architect_approval_log.
- A delegação é válida na conversa, não globalmente. Revogue a qualquer momento; uma instalação já em andamento não é cancelada automaticamente ao revogar.

Os agentes continuam necessitando de provedores reais conectados. A revisão automática não substitui testes no navegador ou inspeção humana de alterações importantes.


### Selecionar projetos e Skills diretamente no Chat IA

No topo da conversa, a barra de contexto **Projeto / Skills do projeto** permite:

- Selecionar **Loja Virtual**, qualquer outro projeto cadastrado, ou **Sem projeto** antes de enviar um pedido. A conversa é vinculada ao ID do projeto selecionado, e a pasta continua restrita ao workspace autorizado.
- Ativar ou desativar as Skills disponíveis (por exemplo, **UI/UX Studio Pro**) sem acessar outra página. As Skills são persistidas **por projeto**, portanto aparecem ativas em todas as conversas vinculadas ao mesmo projeto.
- Criar uma conversa nova ao trocar de projeto depois de já haver mensagens ou execuções, **mantendo a conversa anterior intacta**. Rascunhos vazios podem ser reatribuídos pelo endpoint autenticado \`POST /api/conversations/{cid}/project\`; a troca revoga qualquer permissão de Arquiteto antiga antes de salvar a nova vinculação.
- Uma seleção de projeto **não autoriza** o Arquiteto automaticamente. A delegação para revisão de código/instalação de pacotes continua explícita, limitada à conversa e pode ser revogada.
- Durante uma execução, os controles de alteração ficam bloqueados na interface; o backend também impede mover conversas que já contêm histórico/execuções para outro projeto.
- Caso o usuário ainda não tenha criado um projeto, escolha **Sem projeto** para conversas comuns ou cadastre um projeto na aba **Projetos**.

O controle de Skills no chat é uma interface para o catálogo local atualmente disponível. Não significa que as CLIs ou servidores MCP externos listados nas orientações da Skill tenham sido instalados.


### Compatibilidade de especialidades em Trabalhadores

Os cartões da aba Trabalhadores mostram agora o papel reconhecido pelo orquestrador. O campo editável Especialidade aceita descrições personalizadas; para os nomes padrão exatos Arquiteto IA, Frontend IA e Designer IA, o roteamento pode recuperar o papel mesmo quando essa especialidade foi personalizada.

Os códigos canônicos continuam sendo architecture, frontend e design. Um código canônico explícito sempre tem prioridade sobre o nome mostrado: um trabalhador chamado Arquiteto IA com especialidade backend não se torna Arquiteto na execução e não recebe automaticamente poderes privilegiados.

Não há alteração automática de registros de trabalhadores nem mudanças nas permissões do usuário. Para trabalhadores com nomes personalizados, configure a especialidade com seu código canônico em Trabalhadores -> Configurar.


### Revisor IA: somente leitura, sem geração de arquivos

Nos fluxos de múltiplos trabalhadores, o Revisor IA é executado depois das etapas de código de Frontend/Backend e recebe um contexto específico de auditoria (possíveis conflitos de imports, endpoints, requisitos e limitações). O contexto do Revisor não pede manifestos de criação de arquivos. A Central ignora qualquer JSON `files` enviado pelo Revisor, completo ou incompleto: seu parecer é consultivo e **não substitui** aprovação humana ou a revisão independente do Arquiteto quando explicitamente delegada.

Se o Revisor ainda responder com um manifesto de arquivos em vez de um parecer, a conclusão distingue `resposta ignorada` de `revisão concluída`, sem descartar propostas válidas dos trabalhadores de código. Os resultados antigos e as propostas pendentes permanecem intactos; a correção só afeta novas execuções.

Para projetos já existentes, pedidos de estrutura inicial que propõem substituir arquivos ou misturam novas estruturas de backend são mantidos como alterações pendentes. Antes de aplicar, confira o entrypoint `backend/main.py`, módulos auxiliares e o endpoint `/api/products`, bem como imports e props dos componentes React. A existência de propostas não comprova que o projeto compila ou funciona.


## Executar e visualizar projetos diretamente no Chat IA

No Chat IA, após selecionar um projeto, aparecem quatro controles: **Autorizar execução**, **Iniciar**, **Prévia** e **Parar**. A autorização é concedida pelo usuário autenticado com confirmação explícita e fica registrada apenas para a conversa e o projeto vinculados. Revogar a autorização encerra os processos que a Central iniciou. Mudar de projeto em um rascunho também interrompe os servidores e elimina a autorização anterior. Autorizar o Arquiteto IA não equivale a autorizar execução local.

**Iniciar** abre dois processos locais com comandos predefinidos (sem shell e sem comandos gerados por modelos):
- FastAPI: usa `backend/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000` no Windows.
- React/Vite: chama diretamente o executável do Vite `frontend/node_modules/vite/bin/vite.js` usando Node.js na porta fixa 5173, sem `npm run`, `npx` ou scripts de instalação.
- Dependências e ambientes virtuais precisam estar previamente preparados em `frontend/node_modules` e `backend/.venv`. A Central **não instala dependências, altera arquivos de projeto, faz build ou publica o site** ao apertar Iniciar.
- O frontend deve conversar com o FastAPI via `http://127.0.0.1:8000/api/products` conforme seu código. Se a porta 5173 ou 8000 estiver ocupada por servidores iniciados manualmente, a Central recusa o início e pede que sejam parados ou que sejam visualizados separadamente. Por segurança não assume a posse de servidores desconhecidos.
- **Prévia** abre a aplicação React realmente servida pelo Vite em um iframe com sandbox, com opção **Nova aba**. A prévia é do código já aplicado no disco: propostas pendentes de aprovação não aparecem.
- **Parar** encerra os processos iniciados por esta instância da Central. Eles também são encerrados no desligamento normal da Central. Permissões persistidas não iniciam servidores automaticamente após reiniciar o programa.

### Segurança e limitações

Executar um projeto local implica executar o código e as dependências que já estiverem nos diretórios autorizados. Mesmo sem comandos arbitrários, código de projeto ou bibliotecas comprometidas podem agir com os privilégios do usuário Windows. Autorize apenas projetos e dependências confiáveis; faça backup ou commit Git antes de testar propostas não revisadas. O instalador de pacotes autorizado ao Arquiteto é separado desta função.

O executor só reconhece estrutura de desenvolvimento React/Vite + FastAPI, vincula-se a **127.0.0.1**, verifica caminhos críticos contra links/junções/hardlinks, recusa execução em portas ocupadas e limita a um projeto ativo por instância. Não permite comandos livres por chat, execução no servidor de produção, compartilhamento pela rede ou pré-visualização de outros processos no sistema. O teste de CI usa processos simulados; ainda é necessária a validação manual com o Python e Node.js instalados no Windows.


### Diagnóstico de inicialização da prévia

O botão Iniciar agora só confirma sucesso depois que FastAPI (porta 8000) e Vite (resposta HTTP local na porta 5173) estiverem ativos. Aguarda até 8 segundos e interrompe os processos lançados caso ocorra erro ou tempo limite. Não executa instalação de dependências nem corrige arquivos automaticamente.

Se o Python ou o Vite encerrar rapidamente, a Central retorna um erro HTTP 422 com o nome do processo, código de saída e trecho limitado das mensagens do servidor. O Chat IA mostra o diagnóstico em uma mensagem, mantém a opção Iniciar para nova tentativa e oferece **Diagnóstico** para reabrir/copiar a mensagem após recarregar a conversa (durante a mesma sessão do servidor). Enquanto o serviço não estiver saudável, **Prévia** fica desabilitada. Se um servidor encerrar depois de iniciar, a próxima consulta de status invalida a prévia e guarda a falha. O stdout dos processos é consumido continuamente com buffer limitado para não bloquear subprocessos.

Causas comuns: Vite sem dependências de `node_modules`, backend com importação inválida, pacote uvicorn ausente no virtualenv ou incompatibilidade de código proposta anteriormente. Corrija somente após ler o diagnóstico; as alterações pendentes permanecem na revisão e nenhuma instalação é iniciada automaticamente.
