# Dependências com saída de rede restrita

## Preparação

Requer Docker Engine 28 ou posterior com Linux containers. Prepare as duas
imagens antes de iniciar os agentes; a execução não faz pull automático:

    docker build -f sandbox/Dockerfile -t central-ai-executor:py311-node22 sandbox
    docker build -f sandbox/Dockerfile.egress -t central-ai-egress:py311-v1 sandbox

No PowerShell da API e do worker:

    $env:CENTRAL_COMMAND_RUNNER = 'docker'
    $env:CENTRAL_DOCKER_INSTALL_NETWORK = 'proxy'
    $env:CENTRAL_EGRESS_DOMAINS = 'registry.npmjs.org,pypi.org,files.pythonhosted.org'

Autorizações individuais continuam obrigatórias. Os agentes não podem definir
os domínios, imagens, modo de rede ou flags Docker. O padrão permanece none,
com instalação offline. Bridge é legado local e é recusado no modo servidor.

## Funcionamento

Cada instalação cria uma rede interna exclusiva com gateway_mode=isolated,
sem endereço de gateway no host. O instalador conecta somente nessa rede e
não tem rota pública. A configuração de DNS externo é desligada; o nome do
proxy é um alias interno do Docker. O proxy conecta à rede interna e à bridge
externa, sem encaminhamento IP, sem privilégios ou mounts do host.

O proxy aceita apenas CONNECT para a porta 443 em nomes DNS exatos da lista.
Não aceita IP literal, wildcard, HTTP sem TLS ou outros métodos. Resolve IPv4,
rejeita qualquer resposta privada/local/reservada/multicast e conecta ao IP
público já validado, sem uma segunda resolução. TLS é validado pelo npm/pip:
o proxy não descriptografa o tráfego. Redirect para outro domínio exige que
esse domínio também esteja explicitamente autorizado.

Cada tarefa recebe um token aleatório de proxy. Não são encaminhadas chaves
pessoais de provedores, cookies ou conteúdo de outros projetos. npm mantém
--ignore-scripts e pip aceita somente wheels. Cache, wheels e pacotes ficam
somente no subprojeto montado. Builds, testes e prévias usam --network none.

## Limites e falhas

Proxy: 128 MB, 0,25 CPU, 32 processos, 16 túneis simultâneos, 60 segundos e
32 MB por túnel, expiração do processo após 120 segundos. Preparação tem até
30 segundos; comando mantém o teto de 45 segundos. Não há shell arbitrário.

Falhas de criação, imagem ausente, Docker antigo, domínios inválidos ou
cancelamento interrompem a instalação; nunca há fallback para host/bridge.
O executor limpa o contêiner do job, proxy e rede no finally. Se o worker ou
daemon for encerrado abruptamente, podem restar recursos parados: possuem
nomes central-egress-* e label central.managed=dependency-egress para inspeção
pelo operador. A expiração do proxy limita sua vida mesmo sem cleanup do worker.

A política limita domínios, não caminhos dentro de um registro. Ela não torna
pacotes de terceiros confiáveis. Docker daemon, imagens e kernel continuam
parte da infraestrutura confiável do operador.

## Testes

No Linux com as imagens preparadas:

    CENTRAL_DOCKER_INTEGRATION=1 python -m pytest tests/test_docker_integration.py -v

No Windows, configure a mesma variável no PowerShell antes de executar pytest.
O job docker-isolation no CI constrói as imagens e verifica downloads npm e pip,
reuso offline, bloqueio de destino não listado, bloqueio de conexão direta e
prévia real sem rede do contêiner. Testes unitários adicionais simulam rebinding
DNS e respostas privadas/mistas sem acessar a rede.
