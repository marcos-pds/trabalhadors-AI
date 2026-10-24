# Continuidade das fases 5–12

Implementação local, testes e homologação externa são etapas diferentes.
Nenhuma fase com as pendências abaixo está concluída para produção.

| Fase | Implementado | Ainda necessário |
| --- | --- | --- |
| 5 — dependências e prévia | npm/pip isolados; wheels; cache por subprojeto; offline por padrão; proxy HTTPS por domínios, DNS público fixado e rede interna isolada; prévia Vite no Docker sem rede por proxy HTTP em origem separada; limite de quatro prévias, expiração em 30 minutos | Homologar Docker Desktop; WebSocket/HMR e backends na prévia (Docker Linux validado no CI) |
| 6 — memória semântica | Embeddings Ollama com autorização por usuário/projeto; cache por hash; documentos privados/compartilhados; expiração e limpeza; fontes; fallback lexical; interface de ativação | Homologar modelo e corpus reais; medir qualidade/latência em coleções maiores |
| 7 — serviços | Seleção/templates em agent_registry; DAG em workflows; seleção/comparação em provider_manager; autorização em approval_engine; RunOrchestrator e WorkspaceExecutor injetáveis | Revisão de contratos de plugins (suíte assíncrona aprovada em Linux/Windows) |
| 8 — desenvolvimento | Git status/diff/log; diff/textconv/fsmonitor externos desativados; revisões/diffs paginados GitHub/GitLab; plano imutável e aprovação única para PR/MR em rascunho; tokens pessoais criptografados; UI; CLI operacional | Homologar gravação com contas reais; deploy com plano/aprovação e reconciliação de resultados remotos incertos |
| 9 — infraestrutura | Migrações SQLite ordenadas com checksum; índices; compatibilidade com bancos legados | PostgreSQL, Redis distribuído e tracing multihost NÃO implementados |
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
