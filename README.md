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
