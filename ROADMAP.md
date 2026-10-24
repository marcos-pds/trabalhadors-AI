# Continuidade das fases 5–12

Implementação local, testes e homologação externa são etapas diferentes.
Nenhuma fase com as pendências abaixo está concluída para produção.

| Fase | Implementado | Ainda necessário |
| --- | --- | --- |
| 5 — dependências e prévia | npm/pip isolados; wheels; cache por subprojeto; offline por padrão; proxy HTTPS por domínios, DNS público fixado e rede interna isolada; prévia Vite no Docker sem rede por proxy HTTP em origem separada; limite de quatro prévias, expiração em 30 minutos | Homologar Docker Desktop; WebSocket/HMR e backends na prévia (Docker Linux validado no CI) |
| 6 — memória semântica | Embeddings Ollama com autorização por usuário/projeto; cache por hash; documentos privados/compartilhados; expiração e limpeza; fontes; fallback lexical; interface de ativação | Homologar modelo e corpus reais; medir qualidade/latência em coleções maiores |
| 7 — serviços | Seleção/templates em agent_registry; DAG em workflows; seleção/comparação em provider_manager; autorização em approval_engine; RunOrchestrator e WorkspaceExecutor injetáveis | Revisão de contratos de plugins (suíte assíncrona aprovada em Linux/Windows) |
| 8 — desenvolvimento | Git status/diff/log; diff/textconv/fsmonitor externos desativados; revisões/diffs paginados GitHub/GitLab; plano imutável e aprovação única para PR/MR em rascunho; tokens pessoais criptografados; UI; CLI operacional | Homologar gravação com contas reais; deploy com plano/aprovação e reconciliação de resultados remotos incertos |
| 9 — infraestrutura | Migrações SQLite com checksum; leases por tentativa; protótipo PostgreSQL isolado; notificações Redis Pub/Sub opt-in no protótipo, testadas em serviços reais | Aplicação ainda opera em SQLite; migração de dados, PostgreSQL integrado, consumidor Redis da aplicação, fencing de efeitos externos e tracing multihost NÃO implementados |
| 10 — segurança | Chave externa; configuração servidor exige HTTPS, Docker e chave; cadastro fechado nesse modo; convite de uso único por conta; backup criptografado e restore sem sobrescrita | SSO/OIDC, verificação de e-mail, rotação em secret manager, TLS implantado e auditoria externa |
| 11 — produto | Memória semântica, revisões Git, relatórios JSON/Markdown e comparação de preços configurados/latência observada | Editor com diff/aprovação; revisão visual, acessibilidade e fluxo ponta a ponta |
| 12 — homologação | CLI de verificações; ferramenta de carga do endpoint de saúde; testes de restauração e acesso | Carga real, pentest independente, recuperação fora da máquina, deploy/escalabilidade |

## Executor e dependências

Recrie a imagem depois de atualizar o Dockerfile:

    docker build -f sandbox/Dockerfile -t central-ai-executor:py311-node22 sandbox

API e worker precisam usar CENTRAL_COMMAND_RUNNER=docker e o mesmo executor
registrado no início de cada tarefa. Instalações exigem aprovação individual.
CENTRAL_DOCKER_INSTALL_NETWORK=none é o padrão. O novo modo proxy permite
somente HTTPS nos domínios de registro autorizados, através de um contêiner
separado e autenticado por tarefa. O instalador usa rede interna sem gateway
com modo isolated (Docker Engine >=28); não possui saída direta nem DNS externo.
A resolução do proxy rejeita IPs privados, locais e reservados e conecta ao IP
público validado. O modo bridge continua disponível apenas no perfil local e é
recusado no perfil servidor. Configuração: [sandbox/EGRESS.md](sandbox/EGRESS.md).

Python instala somente wheels em .central-python; o Python da Central não é
modificado. Online, baixa wheels em .central-wheels antes da instalação;
offline, usa somente esse diretório. Pacotes sem wheel compatível falham.
Builds, testes e prévias permanecem sem rede mesmo com downloads habilitados.
Ignore .central-npm-cache, .central-pip-cache, .central-wheels e .central-python
no Git dos projetos gerados. O timeout de 45 s pode limitar instalações grandes.

## Prévia

O proxy transporta HTTP GET por Docker exec para a porta interna fixa 4173.
Não publica portas do contêiner, encaminha cookies da Central ou segue redirects.
A origem do navegador é uma porta loopback separada. Cada prévia usa caminho com
token aleatório, quatro consultas simultâneas e respostas limitadas a 4 MB.
A pasta é revalidada a cada consulta. O iframe preserva sandbox e a atualização
é manual. WebSocket/HMR e aplicações com API própria continuam pendentes.
As prévias são temporárias, locais e não constituem hospedagem de produção.

## Memória semântica

Prepare Ollama e um modelo de embeddings no computador. A Central não baixa
modelos automaticamente. Padrão: nomic-embed-text em http://127.0.0.1:11434.
CENTRAL_EMBEDDING_MODEL e CENTRAL_EMBEDDING_URL são configuráveis pelo operador;
a URL só aceita origem HTTP loopback. Cada usuário ativa a busca por projeto
no painel Memória. Conversas de colegas não são recuperadas; notas compartilhadas
continuam sujeitas à autorização do projeto. Falha do Ollama mantém a busca lexical.

## Operação e recuperação

Defina CENTRAL_BACKUP_KEY com uma chave Fernet independente, guardada fora da
máquina/repositório. O CLI não gera nem imprime essa chave. Backups incluem um
snapshot consistente do SQLite e a chave das credenciais dentro do arquivo
autenticado e criptografado.

    python -m central.cli --data-dir data backup C:\Backups\central.enc
    python -m central.cli restore C:\Backups\central.enc C:\Recuperacao\Central-IA
    python -m central.cli --data-dir data doctor
    python -m central.cli --data-dir data release-check --probe-docker
    python -m central.load_probe --base-url http://127.0.0.1:8765 --requests 50 --workers 4

Os diretórios pais precisam existir. Restore exige destino novo e valida
integrity_check. Não substitui o banco ativo. O CLI não inicia serviços nem
publica nada. Doctor abre o banco com bootstrap/migrações da aplicação: faça
backup antes de diagnosticar um banco de versão diferente. Release-check retorna código 2 enquanto houver gates pendentes (1 para falhas),
e não concede aprovação de produção.

## Modo servidor

CENTRAL_DEPLOYMENT_MODE=server exige CENTRAL_PUBLIC_ORIGIN=https://...,
CENTRAL_COMMAND_RUNNER=docker e CENTRAL_SECRET_KEY externa. Isso não instala
TLS nem identidade enterprise. Chave externa diferente da secret.key existente
bloqueia a inicialização: rotação exige migração explícita. Cadastro público fica
fechado salvo CENTRAL_ALLOW_REGISTRATION=true. Provisione a primeira conta em
modo local antes de fechar o cadastro. Convites são vinculados a uma conta
existente por ID e não comprovam verificação de e-mail.

## Evidências e limites desta execução

Build React e compilação Python foram executados localmente. Testes sem sockets
cobrem comandos, memória, revisões Git, migrações, convites, exportação e backup.
A suíte completa tentou iniciar, mas a criação de sockets do asyncio no Python
3.15 deste ambiente travou em socket._fallback_socketpair. Ela não foi declarada
aprovada e seus testes foram preservados. O workflow continua executando a suíte
integral em Linux/Windows com Python 3.11; só contará como evidência após rodar.
Docker e Ollama reais não estavam disponíveis para homologação.

Validação local direcionada: 88 testes Python e 4 testes JavaScript aprovados; build React aprovado. A suíte integral não foi concluída neste ambiente.


### Continuação da Fase 5

Implementado proxy HTTPS por lista exata de domínios, autenticação por tarefa,
rede interna sem gateway e limpeza dos recursos na falha/cancelamento.
O CI agora possui um job específico com Docker real para npm online/offline,
wheels Python online/offline, restrição de rede e prévia HTTP com revogação.
Esses testes são opt-in localmente e não foram executados neste Windows sem
Docker instalado. O job Docker real do CI passou com quatro testes em Linux. A suíte integral
passou com 216 testes em cada sistema (Linux e Windows), no run 40117218111.


### Continuação das Fases 6 e 7

A base de referências aceita texto/Markdown UTF-8 até 128 KB, sem buscar URLs,
abrir caminhos do computador ou executar conteúdo. Cada referência tem título,
visibilidade privada ou compartilhada no projeto e expiração de 1 a 3650 dias
(padrão 90), ou retenção até exclusão manual. A lista e a recuperação respeitam
as permissões atuais do projeto. Conversas privadas não são compartilhadas.

Os textos são divididos em trechos com sobreposição, recuperados por palavras
e, com autorização do usuário, embeddings locais. Até dois documentos entram
no contexto por chamada, com ID da fonte e trecho. A busca lexical considera
até 1200 trechos; a etapa semântica considera até 120 candidatos e gera até
16 embeddings novos por chamada. Esses limites devem ser avaliados em corpus
real antes de anunciar cobertura de grandes bases.

Expirados são excluídos durante consultas e por manutenção horária da API em
lotes de até 500 documentos. Chunks e embeddings são removidos por cascade.
Backups seguem a política de retenção do operador, separada da base ativa.

RunOrchestrator aceita registro de agentes, gerenciador de provedores, fila e
executor de workspace fornecidos pelo servidor. Engine continua como alias
compatível. O executor passa pelas mesmas verificações de escopo e aprovação
antes de chamar seu runner. Aprovações concorrentes têm apenas uma decisão
aceita; a segunda recebe conflito. Nenhum desses objetos é aceito do JSON da IA.

Os 26 arquivos das Fases 5–7 foram publicados após autorização explícita.
O run [40117218111](https://github.com/marcos-pds/trabalhadors-AI/actions/runs/40117218111)
aprovou 216 testes em Linux e Windows, mais os quatro testes com Docker real.
Ollama com modelo real e avaliação de relevância continuam pendentes.

### Continuação da Fase 8

Consultas de revisões e diffs agora recebem páginas de 1 a 100, com botões
anterior/próxima e indicação de truncamento. A paginação usa apenas números
validados; links remotos nunca são seguidos com credenciais.

Criar um PR/MR exige preparar e aprovar um plano de rascunho. O plano identifica
serviço, repositório, origem/destino, commits, título e descrição. Expira em
15 minutos. A aprovação é de uso único e revalida os commits antes do POST.
Mudar token/conexão ou branches invalida o plano; duas aprovações simultâneas
não criam duas revisões. O plano não faz push, merge ou deploy.

Respostas perdidas, malformadas, redirects inesperados ou erros 5xx após o POST
ficam com resultado incerto, sem repetição automática. A interface orienta
conferir o serviço antes de preparar outro plano. Uma queda abrupta durante a
operação pode deixar o plano em executing; também exige conferência manual.
O ID do plano é incluído como comentário Markdown na descrição para correlação.

O serviço pode receber uma atualização de branch entre a última conferência e
a criação da revisão. O retorno verifica os commits confirmados pelo provedor;
se diferirem ou não forem informados, exige revisão no serviço. PR/MR é mutável
por natureza e nunca é mesclado automaticamente pela Central.

Tokens de leitura continuam suficientes para consultas. Criar rascunhos exige
permissão adequada no provedor. A implementação foi testada com transportes
simulados; a homologação em contas reais e o deploy aprovado seguem pendentes.

Validação local da Fase 8: 142 testes Python direcionados aprovados, 4 testes JavaScript aprovados e build React aprovado. Integrações de gravação foram simuladas; nenhuma revisão remota foi criada pelos testes.


### Continuação incremental — Fases 8 e 12 (PR #8)

**Reconciliação de operações Git com resultado incerto (Fase 8).**
A Central agora consulta revisões existentes em GitHub/GitLab por um marcador
imutável associado ao plano de publicação. A busca é paginada (até cinco
páginas de 100 registros), não segue URLs de paginação externas e não
executa nenhum POST/retry. Uma única correspondência encontrada em uma
varredura completa pode ser registrada como concluída. Desvios de branch,
commit ou condição de rascunho obrigam conferência humana. Marcadores
duplicados, paginação truncada, falhas e ausência de resultados permanecem
incertos, sem serem interpretados como prova de não criação.

A interface Git mostra os 15 planos mais recentes de cada conexão e
permite consultar os planos incertos mesmo após atualizar a página.
Confirmações originais não são recuperadas do histórico; um plano que perdeu
a confirmação não recebe um botão de aprovação automática. A leitura
não substitui validação em contas reais ou reconciliação após alterações
manuais e não autoriza merge/deploy.

**Verificação de backup sem restauração (Fase 12).**
Um backup criptografado pode ser inspecionado sem modificar o banco ativo,
validando chave, membros do arquivo, formato e integridade SQLite:

    python -m central.cli verify-backup C:\Backups\central.enc
    python -m central.cli --data-dir data release-check --backup-file C:\Backups\central.enc

O comando de verificação não exige uma pasta de dados ativa. Release-check
marca a validação como passada, falha ou não checada; ele continua retornando
código 2 enquanto os gates externos não forem homologados. A confirmação
de integridade local não substitui teste de recuperação fora da máquina nem
backup offsite.

A documentação descreve a implementação parcial: homologação em contas Git
reais, deploy aprovado, PostgreSQL/Redis, SSO e testes de recuperação externa
permanecem pendentes.

### Fase 9 - workers SQLite: controle de retomadas e observabilidade

Esta entrega prepara a fila existente para uma futura migracao de infraestrutura.
PostgreSQL e Redis nao estao implementados nem habilitados nesta entrega.

- CENTRAL_MAX_JOB_ATTEMPTS permite de 1 a 20 tentativas por tarefa
  (padrao 5). Quando leases expirados consomem o limite, o run e o job
  recebem falha no mesmo commit SQLite e um evento queue_attempts_exhausted.
  So uma retomada explicitamente autorizada reinicia o contador.
- Heartbeat e confirmacao nao podem renovar ou finalizar um lease vencido,
  mesmo antes de outro processo reclamar a tarefa. E necessario fencing
  por ferramenta antes de habilitar processos totalmente distribuidos.
- Migracao checksummed 7 cria worker_liveness. Dispatchers atualizam
  heartbeat a cada 5 segundos. Um worker sem sinal ha 20 segundos
  deixa de contar como ativo, mesmo que o processo tenha caido.
- O painel de Monitoramento mostra contagem agregada de workers ativos
  e obsoletos, tarefas ativas e limite de novas tentativas por lease.
- O release-check em CENTRAL_JOB_MODE=api falha quando nao ha worker
  ativo anunciado na mesma base SQLite. O heartbeat nao e prova
  de capacidade real de executar um job.

Para atualizar e verificar no Windows:

    git pull --ff-only origin feat/isolated-preview-semantic-memory
    .\.venv\Scripts\python.exe -m pytest tests/test_job_queue.py tests/test_release_checks.py -q
    .\.venv\Scripts\python.exe -m central.cli --data-dir data release-check

IMPORTANTE: API e worker continuam compartilhando o mesmo arquivo SQLite
local e o mesmo workspace. Isso NAO e uma fila distribuida multihost.
Os proximos passos da fase exigem adapter PostgreSQL transacional,
migraçao e rollback reais, transporte Redis resiliente, fencing de
ferramentas e testes com servicos reais antes de permitir multiplos hosts.
Nao use SQLite em compartilhamento de rede para escalar workers.


### Fase 9 — Lease por tentativa (migração SQLite 8)

Cada claim de tarefa gera `lease_token` aleatório e distinto. O worker deve
apresentar esse token junto ao ID do worker para renovar o lease ou confirmar a
conclusão; chamadas sem token falham fechadas. Recuperações por outro worker,
recuperações pelo **mesmo** ID de worker e retomadas após cancelamento invalidam
tokens anteriores. O token não aparece em detalhes públicos da fila.

A migração com checksum adiciona a coluna sem recriar filas nem apagar dados.
Leases antigos sem token não podem mais ser confirmados pela API nova; após
expirarem, poderão ser retomados em uma nova tentativa, dentro do limite de
retries. Em atualização de processos, interrompa os workers antigos antes de
subir o código novo, evitando períodos com protocolos misturados.

**Limite essencial:** isso protege o estado da fila, não impede que um processo
obsoleto faça alterações externas durante a execução. A operação de ferramentas
precisa receber e validar um fencing token transacional antes de se habilitar
execução distribuída. PostgreSQL/Redis seguem desabilitados e não homologados.

Verificação recomendada: `python -m pytest tests/test_job_queue.py tests/test_release_checks.py -q`.


### Fase 9 — Protótipo PostgreSQL independente

`central/postgres_queue.py` implementa uma fila **experimental** isolada no
schema `central_jobs` do PostgreSQL. **Nenhuma rota da API, worker em produção ou
dados SQLite usam esse módulo**; a aplicação continua exclusivamente SQLite.
O `requirements-postgres.txt` é opcional e não altera a instalação normal.

O protótipo possui migrações transacionais verificadas por checksum, `claim`
serializado por bloqueio transacional global, limite de tarefas simultâneas por
usuário, tentativas máximas e lease renovável associado a token de uso exclusivo
por tentativa. `cancel`, `finish` e `heartbeat` invalidam/rejeitam tokens
obsoletos. O armazenamento usa o relógio do PostgreSQL, não o relógio do worker.

O job `postgres-prototype` do CI sobe PostgreSQL 16 com credenciais de teste
descartáveis e executa `tests/test_postgres_queue.py` com instâncias concorrentes.
Para testar manualmente, forneça `CENTRAL_PG_TEST_DSN` apontando **somente
para um banco descartável** e execute:

    python -m pip install -r requirements-postgres.txt
    python -m pytest tests/test_postgres_queue.py -v

O teste limpa a tabela `central_jobs.queue` no banco indicado; **não use
credenciais de produção**. O DSN jamais deve ser registrado no código ou no Git.

**Gates restantes antes da integração:** modelar e migrar as demais entidades
com PostgreSQL, transações de estados de negócio e fila no mesmo banco, resgate
e rollback de dados existentes, execução autorizada de ferramentas com fencing
atômico, transporte Redis resiliente, observabilidade e homologação de falhas.
O protótipo não é um substituto plug-and-play para `central.job_queue.JobQueue`
nem autoriza múltiplas máquinas a executarem tarefas reais.


### Fase 9 — Sinalização Redis opcional para o protótipo PostgreSQL

`central/redis_signals.py` acrescenta um transporte de **notificações
best-effort**, não uma fila de execução. O canal fixo
`central:experimental-queue:ready:v1` recebe apenas a palavra `ready`.
Não transmite conteúdo de tarefas, dados de usuários, tokens nem permissões.

O protótipo `PostgresJobQueue` recebe um `signals=RedisQueueSignals(url)`
opcional e publica após a transação de enqueue. Se Redis estiver indisponível,
o enqueue permanece concluído em PostgreSQL; é obrigatório continuar
consultando periodicamente o banco para detectar eventos perdidos. Um subscriber
só recebe mensagens enquanto estiver conectado. Nenhum worker de produção usa
esse módulo; a Central segue em SQLite.

Redis plaintext `redis://` só é aceito para localhost. Servidores remotos
precisam de `rediss://` (TLS), sem parâmetros na URL que enfraqueçam a
verificação. Defina as credenciais de Redis e PostgreSQL fora do código e dos
logs. Instale apenas no laboratório:

    python -m pip install -r requirements-postgres.txt -r requirements-redis.txt

`tests/test_redis_signals.py` exercita PostgreSQL + Redis reais no CI com os
envs `CENTRAL_PG_TEST_DSN` e `CENTRAL_REDIS_TEST_URL`. Os testes limpam a tabela
`central_jobs.queue` no banco fornecido: use somente um banco descartável.

**Pendente:** adaptador de persistência transacional das entidades de negócio,
migração e rollback verificados, worker consumidor de notificações que mantenha
polling, autenticação/TLS do Redis de produção, fencing atômico por ferramenta,
resiliência sob falhas de rede e operação multihost. O protótipo não é
deploy ou aprovação para produção.
