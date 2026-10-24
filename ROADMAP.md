# Continuidade das fases 5–12

Implementação local, testes e homologação externa são etapas diferentes.
Nenhuma fase com as pendências abaixo está concluída para produção.

| Fase | Implementado | Ainda necessário |
| --- | --- | --- |
| 5 — dependências e prévia | npm/pip isolados; wheels; cache por subprojeto; offline por padrão; prévia Vite no Docker sem rede por proxy HTTP em origem separada; limite de quatro prévias, expiração em 30 minutos | Docker real; proxy de saída por destinos; WebSocket/HMR e backends na prévia |
| 6 — memória semântica | Embeddings Ollama com autorização por usuário/projeto; cache por hash; fontes; fallback lexical; interface de ativação | Modelo e corpus reais; retenção; RAG de documentos além de conversas |
| 7 — serviços | Seleção/templates em agent_registry; DAG em workflows; seleção/comparação em provider_manager; autorização em approval_engine | Interfaces injetáveis completas de orquestração/execução; suíte assíncrona |
| 8 — desenvolvimento | Git status/diff/log; diff/textconv/fsmonitor externos desativados; revisões/diffs GitHub/GitLab com tokens pessoais criptografados; UI; CLI operacional | Contas reais; paginação; PR/MR gravável e deploy com aprovação de plano concreto |
| 9 — infraestrutura | Migrações SQLite ordenadas com checksum; índices; compatibilidade com bancos legados | PostgreSQL, Redis distribuído e tracing multihost NÃO implementados |
| 10 — segurança | Chave externa; configuração servidor exige HTTPS, Docker e chave; cadastro fechado nesse modo; convite de uso único por conta; backup criptografado e restore sem sobrescrita | SSO/OIDC, verificação de e-mail, rotação em secret manager, TLS implantado e auditoria externa |
| 11 — produto | Memória semântica, revisões Git, relatórios JSON/Markdown e comparação de preços configurados/latência observada | Editor com diff/aprovação; revisão visual, acessibilidade e fluxo ponta a ponta |
| 12 — homologação | CLI de verificações; ferramenta de carga do endpoint de saúde; testes de restauração e acesso | Carga real, pentest independente, recuperação fora da máquina, deploy/escalabilidade |

## Executor e dependências

Recrie a imagem depois de atualizar o Dockerfile:

    docker build -f sandbox/Dockerfile -t central-ai-executor:py311-node22 sandbox

API e worker precisam usar CENTRAL_COMMAND_RUNNER=docker e o mesmo executor
registrado no início de cada tarefa. Instalações exigem aprovação individual.
CENTRAL_DOCKER_INSTALL_NETWORK=none é o padrão. O operador pode habilitar bridge
para downloads, mas isso NÃO restringe domínios e pode alcançar a rede local do
daemon. Mantenha offline e prepare caches fora dos agentes quando uma política
de saída por destinos for obrigatória; o proxy de saída ainda está pendente.

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
