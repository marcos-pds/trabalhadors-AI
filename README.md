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
