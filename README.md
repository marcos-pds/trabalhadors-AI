# Central de Trabalhadores IA

**Versão 0.1.0 — MVP funcional, local e extensível.**

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
