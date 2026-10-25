# Central de Trabalhadores IA

**Versão 0.2.0 - MVP funcional, local e extensível.**

A área **Skills e integrações** importa Skills como contexto selecionado de
agentes e mantém pacotes VSIX/configurações MCP separados e inativos. Consulte
[RESOURCES.md](RESOURCES.md) para formatos, confirmações, limites e permissões.
Importar VSIX não instala no VS Code; importar MCP não conecta servidores.

Plataforma multiagente em português: autenticação, chat com streaming SSE, agentes especializados, provedores com chaves criptografadas, roteamento por especialidade, execução paralela, dependências, modelos de reserva, retomada de checkpoints, fluxos persistidos e aprovação humana.

> **Importante:** o projeto implementa uma primeira versão **real**, mas **não** cumpre integralmente as 15 fases da especificação. Consulte a seção "Funcionalidades e limitações". O código não contém integrações falsas em produção. Para obter respostas de IA, você precisa conectar APIs com acesso válido. Os testes automatizados usam provedores simulados **somente nos testes**.

## Instalação no Windows (recomendado)

1. Extraia o ZIP em uma pasta de sua escolha, como `C:\Projetos\central-trabalhadores-ia`.
2. Instale **Python 3.11 ou mais recente** de https://www.python.org/downloads/ (marque *Add Python to PATH*) e **Node.js 20 ou mais recente** de https://nodejs.org/.
3. Dê dois cliques em **`iniciar_windows.bat`** e permita a instalação das dependências Python e npm na primeira execução. O iniciador compila a interface React antes de iniciar o servidor.
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
npm install
npm run build
.\.venv\Scripts\python.exe run.py
```

### Linux / macOS

Instale Python 3.11 ou mais recente e Node.js 20 ou mais recente. Depois, na raiz do projeto:

```bash
cd central-trabalhadores-ia
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
npm run build
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
│   └── build/             # Bundle gerado pelo Vite e servido pelo FastAPI
├── frontend/
│   ├── index.html
│   └── src/               # Componentes React e estilos Tailwind
├── tests/test_app.py      # Testes de integração controlados
├── run.py                 # Ponto de entrada local
├── iniciar_windows.bat    # Iniciador Windows
├── requirements.txt
├── package.json           # React, Vite e Tailwind CSS
└── ESPECIFICACAO.md       # Documento original fornecido
```

**Stack:** FastAPI / Python 3.11+, React, Vite, Tailwind CSS, SQLite (WAL), httpx e Fernet. O bundle estático do frontend fica em `static/build/`; durante o desenvolvimento, `npm run dev` inicia o Vite em `127.0.0.1:5173` e encaminha as chamadas de API ao FastAPI em `127.0.0.1:8765`. Para escalar para uma equipe e milhões de tarefas, é necessário evoluir a arquitetura para filas externas e workers distribuídos.

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

**Regras de falha:** HTTP 401/403 e falta de créditos desabilitam o provedor; 429, timeouts e respostas HTTP 5xx têm tentativas limitadas. Retries fazem backoff com pequeno jitter; o circuit breaker temporário existe por processo. Operações Git de criação de rascunhos exigem aprovação de um plano e não são repetidas automaticamente após uma resposta incerta.

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
| Preços e latência de provedores | Tarifas configuradas e latência observada; não consulta preços oficiais em tempo real |
| Agentes capazes de modificar repositórios e executar ferramentas | Pasta autorizada, ferramentas delimitadas e aprovações; executor host ou Docker |
| Editor avançado de nós condicionais, transformações, ferramentas, esperas | ❌ Não implementado |
| Busca semântica, embeddings e memória RAG | Ollama opt-in, documentos privados/compartilhados e retenção; homologação com modelo real pendente |
| Work queues externas, escalabilidade entre máquinas | PostgreSQL/Redis experimentais; aplicação continua usando SQLite |
| Logs distribuídos, métricas históricas e tracing | ❌ Não implementado |
| Sandboxing para execução de código e navegador remoto | Executor e prévia HTTP Docker; navegador remoto não implementado |
| Segurança de implantação multi-tenant na internet | ❌ Requer auditoria, rate limit, TLS e infraestrutura adequada |

### Avisos de segurança

- **Uso local:** não exponha o serviço em uma interface de rede pública, nem abra a porta 8765 no firewall. Caso precise implantar em produção, configure HTTPS/TLS, gestão centralizada de segredos, rate limiting, proteção de rede, backups, observabilidade e auditoria.
- A pasta `data/` guarda as contas, conversas, API keys criptografadas e a **chave mestre** `secret.key`. **Faça backup da pasta inteira e nunca publique-a no GitHub.** Se perder `secret.key`, não será possível descriptografar as chaves já armazenadas.
- O frontend não tem acesso às chaves de API; somente o backend realiza chamadas aos provedores.
- Nunca conceda ao aplicativo chaves com privilégios desnecessários. Conteúdos enviados no chat podem ser transmitidos aos provedores habilitados, inclusive durante failover.
- Agentes podem ler e editar arquivos e solicitar comandos delimitados na pasta autorizada. Builds e testes executam código do projeto; habilite essas permissões apenas para pastas confiáveis e consulte os limites do executor Docker abaixo.
- Custo apresentado na interface é **estimado pelo tamanho do texto** e pelas tarifas informadas por você. Não equivale a cobranças reais do provedor. Um orçamento estimado não oferece corte de gasto exato, sobretudo para tarefas paralelas.

## Testes

### Z.ai, ModelScope e SiliconFlow

Em **Provedores**, selecione o serviço, informe sua chave/token e salve. Use **Testar** para validar a conexão na sua conta. Todos usam streaming compatível com OpenAI; nenhuma chave é incluída no código.

| Provedor | URL base padrão | Modelo e condições |
| --- | --- | --- |
| Z.ai / GLM | `https://api.z.ai/api/paas/v4` | Preset `glm-4.7-flash`; alternativa `glm-4.5-flash`. Use uma chave API padrão, não o endpoint do Coding Plan. Só os modelos explicitamente gratuitos devem ser tratados como grátis; cotas podem mudar. |
| ModelScope | `https://api-inference.modelscope.cn/v1` | Informe o ID completo de um modelo com API-Inference e seu Access Token. Confirme requisitos de cadastro/vinculação e cotas no painel; não há modelo pago escolhido automaticamente. |
| SiliconFlow | `https://api.siliconflow.com/v1` | Informe o ID de um modelo de chat do catálogo da sua conta. Gratuidade não é garantida. Contas da China devem usar `https://api.siliconflow.cn/v1` e a chave correspondente. |

A integração atual envia texto. Modelos visuais não recebem imagens por estes conectores. O botão Testar realiza uma chamada real, que pode consumir cota ou saldo. Só habilite um modelo depois de conferir sua tarifa; provedores habilitados podem participar do failover.

Referências: [Z.ai](https://docs.z.ai/guides/overview/quick-start), [preços Z.ai](https://docs.z.ai/guides/overview/pricing), [ModelScope](https://modelscope.cn/docs/model-service/API-Inference/intro), [SiliconFlow](https://docs.siliconflow.com/en/userguide/quickstart).

Testes dos novos conectores, com transporte HTTP simulado e sem chamadas externas:

```bash
python -m pytest -q tests/test_provider_integrations.py
```

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

## Configuração gratuita e um provedor local

O catálogo sugere somente **Ollama** como provedor local. Use o modelo
`qwen2.5-coder:3b` para programação; o modelo precisa estar instalado:

```powershell
ollama pull qwen2.5-coder:3b
ollama serve
```

Se o aplicativo Ollama já estiver rodando, não execute outro `ollama serve`.
Conecte em `http://127.0.0.1:11434/v1`, sem chave API, e clique em Testar.
Mantenha somente uma conexão local habilitada; conexões antigas podem ser
editadas ou desabilitadas sem excluir seu histórico.

Opções online com faixa gratuita: Groq, Gemini, OpenRouter (`openrouter/free`),
Mistral (Studio em **Free mode**), Cloudflare Workers AI e modelos Flash
explicitamente gratuitos da Z.ai. Cada serviço exige sua própria conta e chave;
a existência do conector não significa que a conta já esteja conectada.
ModelScope, SiliconFlow e créditos promocionais exigem conferir as condições
individuais e não são garantia de uso gratuito. O filtro Grátis não inclui
créditos promocionais. Não habilite modelos pagos no fallback para uso gratuito.

Referências: [Groq](https://console.groq.com/docs/rate-limits),
[Gemini](https://ai.google.dev/gemini-api/docs/pricing),
[OpenRouter](https://openrouter.ai/collections/free-models),
[Mistral Free mode](https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key).

## Instalação local desta máquina

Para abrir o repositório correto no VS Code, abra `../Central-IA.code-workspace`.
A pasta acima contém outro repositório vazio; execute comandos Git dentro de
`central-trabalhadores-ia` ou use `git -C central-trabalhadores-ia status` na pasta acima.

Para habilitar somente o Ollama em todas as contas já cadastradas:

```powershell
.\.venv\Scripts\python.exe configurar_local.py
```

O comando usa `qwen2.5-coder:3b`; passe `--model llama3.2` para escolher outro
modelo instalado. Ele desabilita as demais conexões, preserva seus cadastros e
credenciais e direciona os agentes ao Ollama, removendo modelos específicos
antigos dos agentes. Execute com as tarefas paradas e reinicie a Central depois.
O modelo precisa estar instalado no Ollama; o comando não baixa modelos.

## Conexão automática e catálogo pesquisado (23/10/2026)

Na tela **Provedores**, selecione um serviço, cole a chave e clique em
**Conectar automaticamente**. Uma chave já salva pode ser reutilizada deixando o
campo em branco. A Central busca os modelos, seleciona um candidato elegível,
testa uma resposta e só então salva a conexão com a chave criptografada.
Nome, URL e identificador são preenchidos automaticamente. O painel opcional
permite buscar nomes/IDs e escolher um modelo. São testadas até três opções;
falhas de autenticação ou créditos encerram a tentativa imediatamente.
Nenhuma conexão online é ativada apenas por aparecer na lista.

| Serviço | Oferta / requisito | Conexão com chave |
| --- | --- | --- |
| Groq | Free Plan com limites por modelo | Automática |
| OpenRouter | Modelos com preços de entrada, saída e demais campos publicados iguais a zero | Automática |
| Gemini / AI Studio | Projeto no plano gratuito; somente IDs revisados e presentes no catálogo | Automática |
| Mistral | Organização em Free mode; a chave herda o plano | Automática |
| SambaNova | Free Tier para contas sem método de pagamento | Automática |
| Z.ai | Somente GLM-4.7-Flash e GLM-4.5-Flash | Automática |
| Cloudflare Workers AI | Cota diária; exige Account ID e token; há modelos exclusivos do plano pago | Manual |
| Hugging Face | Pequena cota mensal em créditos, sujeita a alteração | Manual |
| Cohere | Chave de avaliação; não destinada a produção/comércio | Manual |
| NVIDIA NIM | Acesso de desenvolvimento/avaliação sujeito às condições do catálogo | Manual |
| Cerebras | Página atual oferece crédito promocional único, com cartão e prazo | Manual |
| ModelScope | Verificar elegibilidade, região e regras de API-Inference | Manual |
| SiliconFlow | Verificar região, preços por modelo e condições da conta | Manual |
| Ollama | Modelos instalados neste computador; sem chave | Automática |

As condições oficiais estão vinculadas em cada cartão, junto à data da revisão.
O catálogo de serviços é uma lista revisada, não uma busca de toda a internet.
A lista de modelos é consultada na API durante a conexão. Se o endpoint `/models`
da Z.ai não existir, usamos os dois IDs da documentação oficial e sinalizamos
essa origem; a disponibilidade só é confirmada no teste de resposta.

Uma API de modelos geralmente não informa se a conta está no plano gratuito ou
com faturamento habilitado. Não confunda uma resposta válida com comprovação de
preço zero: para Groq, Gemini, Mistral e SambaNova, mantenha a conta no plano
gratuito no painel do serviço. Modelos novos do Gemini precisam ser revisados
antes de entrarem na seleção automática; nome contendo Flash não basta.
Ollama é o único serviço local sugerido, e conectar um novo modelo local
pausa outras conexões Ollama da mesma conta.

GitHub Models foi excluído da seleção: o serviço foi encerrado em 30/07/2026,
segundo [a documentação oficial](https://docs.github.com/en/github-models).
Chutes também não entra como gratuito: sua [página de preços](https://www.chutes.ai/pricing)
informa que não oferece faixa gratuita atualmente.

A conexão automática usa `GET /api/provider-catalog`,
`POST /api/provider-catalog/models` e `POST /api/provider-catalog/connect`, todos
com autenticação. Os POSTs exigem proteção CSRF. A chave é enviada no corpo da
requisição local e no cabeçalho de autenticação do provedor, nunca na URL.
O servidor usa somente endpoints fixos do registro na conexão rápida.

Validação sem rede: `.\.venv\Scripts\python.exe -m pytest tests/test_catalog.py -q`.

### Validação de modelos repetidos

O cadastro bloqueia duplicatas do mesmo identificador (sem espaços nas pontas)
no mesmo provedor e conta, inclusive quando a conexão existente está pausada.
A regra vale para conexão rápida, cadastro manual e edição. A edição da própria
conexão continua permitida. O mesmo ID em provedores ou contas diferentes pode
ser cadastrado. Duplicatas retornam HTTP 409 e não sobrescrevem chaves ou dados.
No modo automático, modelos já cadastrados são ignorados antes dos testes;
o catálogo mostra **Já cadastrado** e desabilita essas opções. A gravação faz
nova verificação dentro da transação para impedir duplicatas simultâneas.
Cadastros antigos não são removidos automaticamente.


## Memória de conversas e projetos

A Central salva o histórico completo das conversas no SQLite; os limites abaixo
controlam apenas o contexto encaminhado aos modelos a cada execução (não excluem mensagens).

- **Conversa avulsa:** até 6 mensagens recentes, num total de até 2.600 caracteres.
  Nunca recupera automaticamente conteúdo de outra conversa.
- **Conversa vinculada a projeto:** até 32 mensagens recentes, num total de até
  15.000 caracteres, mais a descrição do projeto, notas fixadas (até 8.000
  caracteres) e até 6 trechos relevantes (máximo de 5.000 caracteres) de
  outras conversas **do mesmo projeto e da mesma conta**.
- **Outro projeto ou conversas avulsas:** não entram no contexto automático de
  um projeto. A busca opcional "Todas as minhas conversas" serve apenas para
  consulta manual na interface e nunca mistura resultados nos prompts.
- **Busca de lembranças:** local e lexical (palavras relevantes normalizadas),
  não usa embeddings nem sumarização por outro modelo. Pode não recuperar
  conversas semanticamente similares com vocabulário totalmente diferente.
- **Notas do projeto:** fixadas e editadas pela pessoa. São mais confiáveis
  para registrar decisões, requisitos, tecnologias e pendências importantes.
  O conteúdo histórico é apresentado aos agentes como referência e não como instrução.
- **Custo:** contextos maiores consomem mais tokens da API conectada. O custo
  não é um plano de assinatura, e o cálculo local continua estimativo.

No **Chat IA**, abra **Memória** para vincular/desvincular a conversa a um projeto,
fixar notas e buscar conversas anteriores. Na área de **Projetos**, o botão
**Memória** gerencia as notas daquele projeto. A barra lateral organiza as
conversas em grupos e a busca permite abrir registros mais antigos. Mudanças de
projeto em uma conversa existente são explícitas e bloqueadas durante execuções
ativas, para evitar misturar contextos acidentalmente.


## Permissões locais pelo botão "Computador" do chat

O compositor do chat exibe **Computador**, próximo de **Anexar**. O painel gerencia
permissões **para uma pasta local explicitamente escolhida pela pessoa** e
nunca concede acesso geral ao Windows, a unidades inteiras ou à pasta de
usuário inteira. As permissões são configuradas por conta na instalação
local (não são exclusivas de uma única conversa).

- **Bloqueado** (padrão): nenhuma operação em arquivo local é permitida.
  Selecionar este modo também remove a pasta autorizada e invalida solicitações.
- **Solicitar permissão**: cada operação suportada gera uma solicitação com
  identificação da pasta/arquivo e requer aprovação explícita na interface,
  válida para uma única operação e com expiração após 5 minutos.
- **Acesso total à pasta autorizada**: permite operações suportadas pelo backend
  **somente dentro daquela pasta** sem perguntar novamente. É necessário
  indicar o caminho completo manualmente e confirmar a alteração.

**Limites atuais:** a única capacidade de filesystem conectada a essa tela
é listar diretórios e ler arquivos de texto/código UTF-8 com até 64 KB.
Arquivos ocultos sensíveis (por exemplo, .env e secret.key), links
simbólicos/junções e caminhos fora da pasta são bloqueados. O usuário pode
anexar um arquivo visualizado ao chat, mas nada é enviado a provedores
externos até essa ação e o envio de uma mensagem.

**Não é controle remoto irrestrito:** a exploração manual continua limitada
a pastas e arquivos de texto. Agentes somente poderão criar pastas, editar
código e executar a lista restrita de tarefas de desenvolvimento se o
usuário ativar também a opção Autonomia no chat. Mouse, janelas, exclusões
e comandos de shell arbitrários continuam fora do escopo. As operações
dos agentes também são verificadas no servidor.

O backend restringe essas rotas a acesso local, login e proteção contra
requisições indevidas. O painel guarda somente a pasta autorizada, o modo
e os registros temporários de aprovação; não copia a pasta para o banco.


## Trabalhadores autônomos: escrita de código, execução e recuperação de erros

A partir da versão atual, **Computador** define o escopo local e **Autonomia**
(no compositor do Chat IA) ativa o uso dessas ferramentas **para uma execução**.
O modo está desligado por padrão. O servidor também exige login, origem local
e uma pasta explicitamente autorizada antes de aceitar qualquer execução autônoma.

**Três modos de permissão:**
- Bloqueado: nenhuma ação local pode ocorrer.
- Solicitar permissão: cada leitura, escrita, criação de pasta ou comando dos
  agentes requer uma autorização exclusiva; o chat mostra um resumo e um diff
  de alterações; aprovação expira em 10 minutos.
- Acesso total à pasta: trabalhadores podem usar apenas as ferramentas
  permitidas dentro da pasta escolhida, sem aprovação por ação.
  Não é acesso irrestrito ao Windows.

**Fluxo padrão:** Arquiteto IA -> Programador IA -> Revisor IA, em sequência,
com resultados das etapas anteriores repassados às seguintes. As respostas
dos modelos contêm pedidos de ferramenta em JSON: listar, ler, criar pasta,
criar arquivo UTF-8, substituir um trecho exato e executar um comando de
desenvolvimento permitido. Cada acesso passa novamente pela política da pasta.

**Comandos permitidos:** npm run build, npm test, npm ci --ignore-scripts,
npm install --ignore-scripts PACOTE, python -m pytest -q,
python -m compileall -q ., python -m venv .venv, pip install -r
requirements.txt, pip install PACOTE e git status --short. Nomes de pacotes e
pastas são validados. O pip só pode instalar no ambiente .venv localizado
dentro do workspace. Não há terminal shell arbitrário nem comandos gerais
de PowerShell ou cmd.exe, git push/deploy nem exclusão de arquivos.
Nomes de comandos no protocolo do agente:
npm_build, npm_test, npm_ci, npm_install, python_test, python_compile,
venv_create, pip_requirements, pip_package e git_status.

**Validação final:** os agentes de implementação e revisão executam
automaticamente build e/ou testes quando finalizam. Falhas são repassadas
ao modelo com logs, permitindo até 2 ciclos extras de correção. A execução
tem limites de 12 rodadas e 18 ações por agente, tempo máximo de 45 segundos
por comando e saída de comando limitada a 9 KB por operação. Se falhar,
a execução é marcada como falha: nenhuma afirmação de teste aprovado é
inventada. Arquivos já alterados não são revertidos automaticamente.
A barra de conversa apresenta eventos de ferramentas, erros e pedidos
de aprovação; resultados de executores ficam no diário de eventos da tarefa.

**Importante:** npm scripts, testes e instaladores podem executar código
do projeto ou de dependências. Embora os arquivos enviados pelos modelos
sejam limitados à pasta autorizada, executar esse código **não é uma sandbox
do sistema operacional**: scripts podem ter acesso aos privilégios do
usuário do Windows. Use somente em projetos/dependências confiáveis, sem
executar a Central com privilégios de administrador. Recomenda-se backup/Git
antes de habilitar o modo de acesso total. Nenhum acesso ocorre se a pessoa
não ativar Autonomia para o chat. O modo de permissão pode ser revogado
pelo botão Computador a qualquer momento; novos pedidos deixam de ser aceitos.

Teste local:
- npm run build
- python -m pytest tests/test_agent_autonomy.py tests/test_computer_access.py tests/test_app.py -q

## Painel de execução, prévia local e ajustes durante uma tarefa

No Chat IA, **Atividade / Prévia** abre um painel ao lado da conversa.
O botão **Parar** também aparece no cabeçalho do chat enquanto a tarefa executa.

- **Atividade:** consulta eventos reais da execução a cada três segundos.
  Mostra etapa, horário, ferramenta e status. Os modelos enviam sinais de
  atividade periódicos; mais de 45 segundos sem eventos gera um aviso de
  possível inatividade, não uma afirmação de travamento.
- **Parar:** cancela a tarefa e encerra a árvore de processos de comandos
  associados àquela execução no Windows. Bloqueia ajustes e aprovações
  pendentes imediatamente. Arquivos já modificados não são revertidos.
- **Conversar durante execução:** envie um ajuste pelo painel ou caixa de
  mensagem principal. Ele é salvo na tarefa e entregue ao trabalhador na
  próxima rodada, sem interromper operações já iniciadas.
- **Prévia ao vivo:** escolha um subprojeto autorizado com package.json
  e script dev. A inicialização exige confirmação e executa npm run dev
  com host 127.0.0.1 em porta local, usando um iframe restrito ao lado
  do chat. Há botão para abrir em nova janela se o iframe não renderizar.
  Projetos com HMR podem atualizar automaticamente; há Atualizar manual.
- **Parar prévia:** encerra só o servidor local de desenvolvimento.
  Sair da conta, mudar a permissão da pasta ou encerrar a Central também
  encerra essa prévia.

A prévia é do aplicativo web, não do desktop Windows. Não fornece
controle remoto de mouse, teclado ou janelas. Scripts npm de projetos
e dependências executam código real com os privilégios de sua conta;
não são uma sandbox de segurança. Use apenas projetos confiáveis.

Verificação: npm run build; python -m pytest -q.

## Checkpoints duráveis e continuação de tarefas longas

Uma etapa autônoma pode precisar de mais de 12 interações com o provedor de IA.
A Central salva um checkpoint SQLite a cada rodada, inclusive após leitura,
edição, comando de ferramenta e resultado de validação. A fase Arquiteto
tem limite menor (até 6 rodadas). Próximo ao limite, os trabalhadores
recebem um aviso para terminar uma parte verificável.

**Pausado por limite** NÃO significa falha no projeto: os arquivos já
modificados permanecem no workspace, a etapa incompleta vira
`paused_limit` e as etapas seguintes (como Revisor IA) ficam na fila.
No Chat -> Atividade / Prévia, veja a última ação, os arquivos alterados,
o resultado do último teste e **Continuar execução**. O mesmo botão aparece
em Histórico. A retomada é explicitamente autorizada pela pessoa e
recupera o histórico recente de ferramentas; não reexecuta o Arquiteto
nem repete propositalmente a última alteração já confirmada.

**Falhou por erro** indica problemas reais de ferramenta, permissão,
provedor ou validação que não puderam ser corrigidos na execução.
É possível tentar retomá-la quando ainda há trabalhador pendente.
**Concluído** só é permitido para uma implementação com alteração real
e build/teste aprovado depois da última alteração. Logs de execução e
checkpoints permanecem disponíveis por tarefa.

Os checkpoints são restritos à conta e à pasta originalmente autorizada.
O histórico textual persistido é limitado em tamanho e fica no SQLite
local (faça backup de `data/`); nenhuma chave de provedor entra nele
deliberadamente. A aplicação limita continuações do mesmo trabalhador a
8 retomadas explícitas, mantendo as 12 rodadas por segmento. Cada
continuação usa tokens da API conectada e pode gerar cobrança.

Em tarefas criadas antes dessa versão, é possível retomar a tarefa antiga:
a Central reconstrói um resumo limitado das ferramentas registradas e
verifica o estado atual dos arquivos antes de editar. Como esse histórico
não inclui todo o contexto do modelo, a recuperação é menos detalhada.

**Monorepos e landing pages:** verificações finais localizam o
`package.json` aplicável aos arquivos modificados (inclusive dentro de
subpastas) e executam o build/teste real do aplicativo. Uma compilação
Python vazia não pode validar falsamente um projeto JavaScript.

Esses checkpoints não criam snapshots Git nem backups automáticos de
arquivos; um comando que tenha executado antes da gravação do checkpoint
pode precisar ser conferido manualmente após falha elétrica. Use Git
ou backup do workspace antes de permitir alterações amplas.

Verificação: `npm run build` e `python -m pytest -q`.

## Fase operacional 1 — observabilidade e governança local

Sem alterar o modo local de execução, a Central agora possui:

- Logs estruturados JSON no stdout do processo (`central/observability.py`),
  com `X-Request-ID` em cada resposta HTTP. Identificadores válidos
  enviados pelo cliente são preservados para correlação; entradas
  inválidas recebem um ID novo. Os logs usam apenas metadados permitidos
  (rota normalizada, duração, status, IDs de run/step e categoria).
  Não registram corpo HTTP, prompt, senhas, cookies, API keys ou conteúdo de arquivos.
- Evento `task_classified` por run, com política explícita versionada
  (`central/run_policy.py`). Tipos: `code`, `inspection` e `conversation`;
  critérios de entrega real permanecem em `central/task_contract.py`.
- Métricas operacionais por usuário em `GET /api/operations/overview`:
  contagem de estados, execuções/falhas/pausas em 24h, latência média das
  tentativas por provedor, taxa de sucesso, categorias de falhas, custo
  **estimado** e duração terminal média. Alertas indicam falhas frequentes,
  pausas por limite e provedores com erros consecutivos.
- Auditoria persistente (`ops_audit`) com registro de criação/retomada/
  cancelamento de tarefas, alterações nas permissões locais e decisões
  humanas sobre ações e etapas. `GET /api/operations/audit?limit=50`
  mostra apenas as ações do usuário autenticado. Sem conteúdo de comandos.
- Checagem de prontidão `GET /api/health/ready`, que confirma a conexão
  com o banco. Ela informa expressamente que a fila ainda roda
  **dentro do processo** e não testa a disponibilidade dos provedores.
- Painel **Monitoramento** com os novos indicadores e auditoria, sem
  substituir o histórico detalhado e a saúde dos provedores existentes.

Notas operacionais: as métricas dependem dos eventos/medições reais
armazenados no SQLite. O custo estimado não é uma fatura nem limite
de cobrança garantido. O monitoramento não constitui uma solução
de multi-tenancy organizacional, observabilidade distribuída ou
tracing OpenTelemetry. Em produção hospedada ainda serão necessários
fila de jobs persistente com leases, isolamento de workspace por
usuário/organização, autenticação/roles, migrações controladas, TLS
via proxy reverso, rate limiting e armazenamento seguro de segredos.

Verificação: `npm run build` e `python -m pytest -q`.

## Fila persistente e worker separado (MVP local)

A Central agora grava cada execução em `job_queue` (SQLite) ANTES de iniciar
o motor. A fila usa reserva atômica (`BEGIN IMMEDIATE`), lease temporário
renovado enquanto o job trabalha, registro de tentativas, limites básicos
de concorrência por usuário e recuperação de jobs com lease expirado.
O estado do run e a fila são coisas distintas: `paused_limit`, `failed` e
`completed` continuam sendo determinados pelo motor e seus testes.

**Opção A — execução local integrada (padrão, recomendada para começar)**

    # Terminal único, sem variáveis extras:
    python -m uvicorn central.main:app --host 127.0.0.1 --port 8765

`CENTRAL_JOB_MODE=embedded` é o padrão. O FastAPI despacha a fila localmente
e os jobs reaparecem no banco após interrupção do processo.

**Opção B — API e worker em terminais separados (Windows PowerShell):**

Terminal 1 — FastAPI, sem executar os jobs:

    $env:CENTRAL_JOB_MODE = 'api'
    python -m uvicorn central.main:app --host 127.0.0.1 --port 8765

Terminal 2 — executa a fila com acesso à mesma pasta de dados:

    python -m central.worker_service

Se definir `CENTRAL_DATA_DIR`, defina **o mesmo caminho absoluto em ambos
os terminais**. Cada processo deve usar o mesmo ambiente Python e a mesma
pasta no mesmo computador. Para voltar ao modo integrado, remova a
variável antes de iniciar o servidor (`Remove-Item Env:CENTRAL_JOB_MODE`).
**Não execute um worker separado simultaneamente ao modo integrado**;
embora o lease evite a maioria das execuções duplicadas, scripts npm e
edições externas não são transacionais.

O endpoint `GET /api/health/ready` informa o modo ativo da API e se a fila
persistente está habilitada; `GET /api/runs/{id}` inclui a reserva atual,
e Monitoramento mostra os estados da fila da conta autenticada.

**Limitações importantes:** esta é uma fila SQLite para processos no
mesmo host, não Celery/Redis nem uma arquitetura multi-host escalável.
Se o worker morrer, um lease pode levar até 90 segundos para expirar;
o novo worker revalida autorizações, hashes e checkpoints antes de
continuar, mas operações externas não são exatamente-once.
Não hospede em múltiplos servidores ou com workspaces compartilhados
sem isolamento de contêiner e mecanismo de fencing transacional.

Diagnóstico:

    npm run build
    python -m pytest tests/test_job_queue.py -q
    python -m pytest -q

## Proteções operacionais iniciais por conta

- O login bloqueia temporariamente uma identidade após seis senhas inválidas
  em uma janela de quinze minutos (`central/auth_limits.py`). As tentativas
  ficam no SQLite como hash do e-mail normalizado (nunca senha/texto puro).
  A API retorna HTTP 429 com `Retry-After`. Esse mecanismo é uma defesa
  inicial por conta, não um WAF/rate limit distribuído por IP.
- Cada conta tem limite configurável por servidor de tarefas novas nas
  últimas 24 horas e de runs ativos (`central/quotas.py`). Os limites
  são verificados numa transação SQLite com o run e seu DAG, evitando
  ultrapassagens por corrida entre processos locais.
- Ajuste antes de iniciar a API com `CENTRAL_MAX_RUNS_PER_DAY` (padrão
  100) e `CENTRAL_MAX_ACTIVE_RUNS` (padrão 4). Ultrapassar retorna HTTP
  429. As cotas não substituem o orçamento estimado por run e não limitam
  com precisão a fatura real de tokens dos provedores.
- O painel Monitoramento mostra o consumo e limite dessas cotas
  por usuário autenticado. Permissões empresariais e limites por empresa
  ainda dependem de introduzir organizações e roles.

Testes:

    python -m pytest tests/test_auth_limits.py tests/test_quotas.py -q

## Fase 2 — organizações e permissões por papel

A Central oferece uma primeira camada de multi-tenancy em torno de
**organizações e projetos**. São criadas apenas tabelas adicionais;
não ocorre recriação nem exclusão dos projetos ou conversas existentes.
Na primeira atualização de um banco antigo, cada conta ganha uma
organização pessoal e seus projetos/runs históricos recebem vínculos
privados idempotentes. Faça backup da pasta `data/` antes da atualização.

Na tela **Projetos → Organizações e permissões**, um usuário pode criar
uma organização, adicionar outra conta já cadastrada por e-mail, definir
papéis e configurar cotas de tarefas por dia, simultâneas e um teto de
**custo estimado** registrado. Projetos selecionam a organização onde
serão criados, inclusive quando a equipe tem mais de um membro.

Regras de acesso:

- `admin`: cria projetos, edita notas, inicia tarefas e administra membros
  e limites da organização; não pode remover o último administrador.
- `operator`: cria projetos e conversas do projeto compartilhado,
  atualiza notas e inicia tarefas; não administra membros nem limites.
- `analyst`: visualiza projetos e notas; não cria tarefas nem modifica
  memórias ou permissões.
- Um membro só pode acessar projetos de organizações às quais pertence.
  Revogar sua associação bloqueia o acesso aos projetos e aos runs desse
  tenant, inclusive históricos; tarefas ativas precisam terminar ou
  ser canceladas antes de remover o membro ou rebaixá-lo para analista.

**Privacidade intencional:** agentes, chaves de API, permissões de acesso
ao computador, conversas e mensagens continuam pessoais. Membros da mesma
organização veem o projeto e suas notas, mas NÃO recebem o histórico de
chat de colegas nem seus segredos. Buscar memórias continua limitado às
conversas do próprio usuário, dentro do mesmo projeto autorizado.

Limites organizacionais são verificados junto com a criação do run em
uma transação SQLite. O teto de custo usa valores estimados registrados
e não impede cobrança inesperada do provedor durante chamadas já em curso.
Ele não deve ser divulgado como um hard cap financeiro. Autonomia ainda
depende das permissões locais de cada operador e usa os próprios agentes
e provedores. A organização não concede acesso ao Windows de outro membro.

Essa base **não transforma a Central em um serviço SaaS de produção**:
faltam convites com verificação, SSO, isolamento de processos/containers
por tenant, armazenamento de segredos gerenciado, políticas de retenção,
backup criptografado, testes de carga e revisão de segurança externa.

Teste recomendado:

    npm run build
    python -m pytest tests/test_organizations.py -q
    python -m pytest -q

## Fase 3 — proteção de workspace por tarefa e execução local assistida

**Vínculo durável de workspace:** toda nova tarefa autônoma cria
`run_workspace_bindings` no SQLite dentro da mesma transação da DAG,
registrando o proprietário, organização, pasta local autorizada e modo
de permissão no início. Os trabalhadores revalidam esse vínculo
antes das ferramentas e depois de cada aprovação. Trocar/revogar a
pasta durante o trabalho interrompe as ferramentas pendentes. Retomar
uma tarefa autônoma antiga (sem vínculo) exige autorização explícita
da pasta atual; tarefas novas não podem ser transferidas a outra pasta.

**Isolamento lógico entre organizações:** uma pasta associada a uma
organização não pode ser vinculada a outra quando seus caminhos são
iguais, antepassados ou descendentes — inclusive entre runs históricas.
Escolha uma pasta local separada para cada empresa/organização. Não
altere vínculos do banco manualmente para reutilizar uma pasta.

**Aprovação humana para comandos sensíveis:** instalações npm/pip,
criação de .venv e npm ci requerem aprovação individual mesmo no
modo Computador → Acesso total. Em organizações de equipe, TODOS
os comandos de build, teste e instalação requerem aprovação por ação.
Aprovações são pontuais, expiram e são invalidadas por mudança
de pasta, alteração de papel ou cancelamento da tarefa.

**Scripts de equipes desligados por padrão:** abrir a organização em
Projetos → Organizações e permissões mostra uma nova configuração
de execução local. Somente o administrador, usando conexão local
autenticada, pode habilitar a opção digitando
`AUTORIZO EXECUCAO LOCAL`. Desabilite imediatamente caso passe a
utilizar fontes de código desconhecidas. Isso permite aos membros
autorizados executar comandos de teste/build aprovados individualmente.
Se a execução estiver bloqueada, os agentes poderão trabalhar nos
arquivos autorizados, mas não declarar entrega verificada por build.

**Limites de processos:** comandos locais têm até 45 segundos de
execução, apenas 2 processos simultâneos por processo de worker,
uma execução de comando por run e log de saída limitado a 9 KB.
Saídas muito grandes são drenadas sem ficar inteiras na RAM da Central.

**ATENÇÃO: não é uma sandbox de sistema operacional.** O isolamento
de pastas implementado protege as chamadas das ferramentas da
Central, mas scripts executados via npm/pip/pytest podem ler ou
modificar outros diretórios acessíveis à conta do Windows/Linux.
Não há ainda limite rígido de CPU/RAM nem identidade de SO por
tenant. Não permita executar código de projetos não confiáveis.
Para hospedagem multiusuário, ainda precisamos de container/VM
isolado por tenant ou run, usuário do SO sem privilégios, sistema
de arquivos montado sob política, rede restrita, limites de
CPU/RAM e gerenciamento separado de chaves e credenciais.

Verificação:

    npm run build
    python -m pytest tests/test_workspace_isolation.py -q
    python -m pytest -q

## Fase 4 — executor Docker opcional para comandos dos agentes

O modo padrao continua host para preservar a operacao local ja existente.
Um administrador pode habilitar o modo Docker em um terminal PowerShell:

    # Docker Desktop iniciado e configurado com Linux containers
    docker build -f sandbox/Dockerfile -t central-ai-executor:py311-node22 sandbox
    $env:CENTRAL_COMMAND_RUNNER = 'docker'
    python -m uvicorn central.main:app --host 127.0.0.1 --port 8765

Quando API e worker sao processos separados, configure a mesma variavel
tambem no terminal do worker. A API nao determina a configuracao real de
um worker separado. Reinicie ambos apos atualizar as configuracoes.
Para voltar ao modo local: Remove-Item Env:CENTRAL_COMMAND_RUNNER

**Protecoes implementadas no Docker**

- Os comandos sao predefinidos: npm build, npm test, pytest, compileall,
  git status. Nao ha shell arbitrario nem flags Docker controladas pelo agente.
- --network none, --read-only, --cap-drop ALL, no-new-privileges,
  --pids-limit 128, --memory 512m, --cpus 1, UID/GID sem privilegios,
  tmpfs /tmp de 64 MB e container efemero com --rm.
- Bind mount gravavel apenas do subprojeto validado pelo usuario
  (e nao a home nem a pasta inteira de outros projetos).
- Tempo maximo de 45 s, saida de ate 9 KB, dois comandos simultaneos
  por worker e limpeza best effort do container no cancelamento.
- Organizacoes continuam exigindo aprovacao humana por comando.
  A autorizacao de scripts no host deixa de ser necessaria no Docker.
- Dependencias npm/Python possuem instalacao isolada com aprovacao e
  cache por projeto; veja ROADMAP.md para rede e homologacao pendente.
- A previa Vite agora executa no conteiner sem rede por proxy HTTP local
  separado; veja limites e homologacao pendente em ROADMAP.md.
- Falta de Docker, erro de imagem ou daemon parado nao provocam
  fallback automatico para execucao no Windows.

**Limites e avisos**

O executor Docker isola os subprocessos de build/teste, nao todas as
ferramentas de leitura e escrita da Central nem a API. Docker daemon,
imagem escolhida e kernel continuam recursos confiaveis do operador.
O mount de codigo e gravavel e um script pode ler todos os arquivos
nesse mount; evite colocar credenciais, arquivos .env ou tokens nele.
Projetos que possuem node_modules compilado para Windows podem falhar
ao rodar testes numa imagem Linux. Prepare dependencias previamente
em ambiente confiavel e compativel. O GitHub Actions combina testes simulados
com um job de Docker real em Linux; isso nao homologa Docker Desktop no Windows.
Esse passo nao equivale a uma sandbox SaaS multitenant auditada.

Diagnostico:

    npm run build
    python -m pytest tests/test_sandbox_executor.py -q
    python -m pytest -q

### Etapas com implementação parcial

O [ROADMAP.md](ROADMAP.md) registra as entregas e os critérios restantes por fase.
Entre as pendências estão Docker Desktop e Ollama reais, deploy aprovado,
migração de produção para PostgreSQL, workers distribuídos, SSO/TLS, revisão
visual, carga, pentest e recuperação externa. Os protótipos PostgreSQL/Redis
não substituem o armazenamento e a fila SQLite da aplicação.

Nenhuma das fases futuras deve ser apresentada como concluida antes
de implementacao, testes e validacao em ambiente real.

### Executor por tarefa: modo imutavel

Novas tarefas autonomas persistem o modo host/docker no vinculo de
workspace. O worker valida o mesmo modo antes de executar ferramentas.
Se a API criar uma tarefa em Docker mas o worker estiver em host, a
execucao e bloqueada, sem fallback. Para continuar, reinicie API e
worker com CENTRAL_COMMAND_RUNNER igual ao modo autorizado na tarefa.
Para uma tarefa ja vinculada, alternar o modo exige uma nova tarefa;
isso evita enfraquecer acidentalmente as politicas de uma execucao.


## Fases 5 a 12: implementação e homologação

### Ensaio local de recuperação de backup

Com `CENTRAL_BACKUP_KEY` configurada fora do repositório, execute:

```powershell
.\.venv\Scripts\python.exe -m central.cli recovery-drill C:\Backups\central.enc
```

O comando restaura em uma pasta temporária, verifica o registro atual de
migrações e testa a descriptografia das chaves de provedores e tokens Git com
a chave incluída no backup. Remove a cópia ao terminar e apresenta apenas
contagens e resultados. Não abre o banco ativo, aplica migrações, inicia
workers ou chama provedores. Código de saída: `0` para ensaio aprovado e `1`
para falha. Uma base sem credenciais é identificada como tal.

Backups antigos precisam de um plano separado de compatibilidade; o ensaio
exige o registro de migrações da versão atual. Esta verificação não testa
validade das credenciais nos provedores nem substitui recuperação fora da
máquina. O resultado não autoriza produção.

O status atualizado, comandos e critérios pendentes estão em [ROADMAP.md](ROADMAP.md).
A implementação local inclui dependências npm/Python, prévia HTTP Docker,
memória semântica opcional, serviços separados, revisões GitHub/GitLab,
exportação, migrações SQLite, convites e backup criptografado.
Há protótipos isolados de fila PostgreSQL, sinais Redis e ensaio de migração de
metadados. A integração deles na aplicação, SSO e homologação de produção
continuam pendentes.
