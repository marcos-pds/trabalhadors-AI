# Runtimes externos: descoberta e limites — 29/10/2026

Esta etapa adiciona apenas `central/external_runtimes.py`,
`tests/test_external_runtimes.py` e este documento. Não conecta provedores à UI,
não altera migrations, gateway ou adaptador Codex e não habilita execução nativa.

## Evidência local real

Inventário pelo `shutil.which`, overrides administrativos e sondagens públicas,
executados no checkout principal em 29/10/2026:

| Runtime | Evidência local | Versão local | Estado de execução |
| --- | --- | --- | --- |
| Claude Code (`claude`) | Ausente do PATH; sem override | Indisponível | Bloqueada |
| Gemini CLI (`gemini`) | Ausente do PATH; sem override | Indisponível | Bloqueada |
| OpenCode (`opencode`) | Ausente do PATH; sem override | Indisponível | Bloqueada |
| ACP | Nenhum agente configurado | Indisponível | Bloqueada |
| Codex, integração anterior | `codex --version` executado | `0.164.0-alpha.11.1` | Fora deste sidecar |

Os três CLIs retornaram `not_found`; ACP retornou `not_configured`. A versão do
Codex é evidência de presença e versão, não uma nova prova de inferência. Nenhuma
inferência, instalação, atualização, login ou leitura de arquivo de credenciais
foi feita nesta etapa. Autenticação dos novos runtimes é desconhecida (`null`),
não autenticada por suposição e também não declarada ausente sem evidência.

## Documentação oficial consultada e bloqueios

- **Claude Code:** a [referência oficial do CLI](https://code.claude.com/docs/en/cli-reference)
  documenta `--tools ""` para ferramentas internas, `--disallowedTools "mcp__*"`
  para MCP e `--strict-mcp-config`. Também descreve `--safe-mode` para desativar
  customizações. Existem controles documentados; falta um executável local para
  inspecionar a versão, confirmar sua superfície efetiva de ferramentas, impedir
  hooks/plugins/MCP de inicialização e validar autenticação sem extrair segredos.
  Uma flag documentada isoladamente não certifica o conjunto.
- **Gemini CLI:** o [motor oficial de políticas](https://geminicli.com/docs/reference/policy-engine/)
  documenta negação por wildcard e precedência de políticas. A página alerta
  que políticas no workspace não estão funcionais e recomenda User/Admin.
  É necessário verificar a versão real e a política efetiva, incluindo MCP,
  extensões e subagentes. Modo headless ou plan não prova ausência de ferramentas.
- **OpenCode:** [permissões V1](https://opencode.ai/docs/permissions/) usam
  `permission`; [permissões V2](https://opencode.ai/v2/docs/permissions) usam
  `permissions` com nomes de ações diferentes. Sem versão instalada e teste da
  configuração efetiva, não se pode escolher um formato e prometer bloqueio de
  todas as ferramentas, plugins e MCP. Não há faixa de versões presumida segura.
- **ACP:** a [inicialização v1](https://agentclientprotocol.com/protocol/v1/initialization)
  negocia versão e capacidades; o [transporte stdio](https://agentclientprotocol.com/protocol/v1/transports)
  usa JSON-RPC 2.0 UTF-8 delimitado por newline.
  As [considerações de segurança](https://agentclientprotocol.com/protocol/v1/security)
  devem orientar a integração futura. Inferência de arquitetura: negar métodos
  do cliente não demonstra que o agente externo abandonou suas próprias
  ferramentas. Portanto, sucesso em `initialize` não autoriza `session/new`,
  `session/prompt`, autenticação ou execução.

Nenhuma versão de Claude/Gemini/OpenCode/agente ACP foi certificada. O registro
mantém `certified_versions: []`, `tools_disable_certified: false`,
`text_stream: false`, `action_planner: false` e `gateway_binding: false`.
Isso é um bloqueio explícito, não um adaptador que simula respostas de modelo.

## Interfaces para integração posterior

```python
from central.external_runtimes import (
    RuntimeBlocked, inventory, probe, registry, stream,
)

capabilities = registry()              # cópia independente, sem iniciar processo
presence = inventory()                # somente presença/configuração; sem caminhos
discovery = probe('claude', timeout=5) # síncrono; adequado a rota FastAPI sync
acp = probe('acp', timeout=5)          # somente initialize, se configurado

try:
    for text in stream('claude', 'model-id', 'system', []):
        pass
except RuntimeBlocked as exc:
    status = str(exc)                 # código fixo; nunca stderr/erro bruto
```

Identificadores do registro: `claude`, `gemini`, `opencode`, `acp`. Codex continua
nas interfaces existentes; não é reimplementado aqui. Não há endpoint novo nem
mudança em `providers.py`. O iterador `stream` é síncrono; um futuro consumidor
async deve respeitar esse contrato e não bloquear o event loop com sondagens.

`inventory()` não executa binários. Os overrides administrativos são
`CENTRAL_CLAUDE_EXECUTABLE`, `CENTRAL_GEMINI_EXECUTABLE`,
`CENTRAL_OPENCODE_EXECUTABLE` e `CENTRAL_ACP_EXECUTABLE`.
Exigem arquivo existente com caminho absoluto e permissão de execução; no
Windows, exclusivamente `.exe`. Wrappers `.cmd`/`.bat` não são executados.
Override inválido não cai silenciosamente no PATH.

ACP não possui um executável universal chamado `acp`: requer override explícito.
`CENTRAL_ACP_ARGS` é um array JSON administrativo opcional, por exemplo `["acp"]`
para um binário confiável que forneça esse subcomando. Há limite de 16 argumentos,
256 caracteres por argumento e recusa de caracteres de controle. Nunca se usa
shell, concatenação de comandos, `npx` ou instalador. Esses valores não devem ser
expostos como configuração arbitrária de navegador/provedor.

`probe()` executa apenas `--version` para os CLIs conhecidos ou `initialize`
ACP v1. Uma versão sintaticamente válida retorna `unsupported_version`, com o
número preservado para diagnóstico. ACP retorna `transport_ready` somente após
resposta válida de v1; isso não comprova autenticação nem capacidade de modelo.
Não envia uma notificação `initialized` de outro protocolo, não abre sessão e
não chama ferramentas. Versões v2/diferentes são recusadas nesta implementação.

`stream()` recusa a chamada antes de iniciar processo ou inspecionar o prompt:
`not_found`, `not_configured`, `invalid_executable` ou
`native_tools_uncertified`, conforme o caso. Não existe override ambiental para
certificação, fallback automático para API ou resposta fictícia. Autenticação
desconhecida/ausente nunca concede execução. O gateway existente deve validar e
executar qualquer ação planejada quando houver adaptador certificado; texto do
modelo e solicitações ACP nunca viram comandos diretamente.

## Limites e segurança do processo

- Apenas modo `local`; server e valores desconhecidos retornam
  `server_mode_refused` antes de consultar/iniciar executáveis. Inventário de
  presença continua disponível sem acessar conta local.
- Diretório de trabalho e HOME/config/cache temporários e descartáveis;
  ambiente com allowlist mínima, sem chaves de provedores, tokens, proxies,
  preloads Node/Python ou configurações de runtime herdadas. Não carrega o
  projeto do usuário como cwd.
- Timeout total de IO entre 0 e 60 segundos, padrão 5; aceita
  `cancel_event=threading.Event()`. Inclui leitura, escrita e espera da versão.
  Limpeza usa esperas limitadas adicionais: processo até 1 s e dois workers
  de pipe até 0,5 s cada, além da remoção do diretório temporário.
- stdout limitado a 512 KiB por processo, linha até 64 KiB e 128 mensagens;
  versão até 1 KiB. Filas de leitura/escrita de 16 itens. Escritas parciais são
  tratadas; fila cheia, excesso, JSON malformado, chaves duplicadas, NaN,
  UTF-8 inválido, IDs incompatíveis e profundidade excessiva falham fechados.
- stderr vai diretamente para `DEVNULL`. Retornos públicos contêm somente
  estados/capacidades, versão validada e autenticação desconhecida; nunca
  caminhos, emails, respostas de erro, authMethods ou informações brutas do agente.
- Capacidade de filesystem explicitamente falsa, terminal falso e nenhuma
  capacidade de autenticação interativa anunciada. Todos os pedidos recebidos
  do servidor são respondidos com erro JSON-RPC `-32601`, inclusive permissões,
  arquivos, terminal e autenticação. Não há callback genérico de execução.
- Windows usa Job Object com kill-on-close para conter o ciclo de vida dos
  descendentes; falha em associar o processo recusa a sondagem. POSIX usa sessão
  e grupo de processos próprios. O processo é encerrado, aguardado e seus pipes
  e workers são fechados inclusive em erro, timeout e cancelamento.

Essas medidas limitam o cliente e o ciclo de vida. Não constituem sandbox para
um executável hostil: arquivos de PATH/overrides são software administrativo
confiável, e ACP configurado pode executar código próprio ao iniciar. A integração
de execução exige certificação adicional; não se transforma um agente arbitrário
em seguro apenas negando suas solicitações RPC.

## Validação reproduzível

```powershell
.venv/Scripts/python.exe -m pytest tests/test_external_runtimes.py -q
.venv/Scripts/python.exe -c "from central.external_runtimes import inventory,probe; import json; print(json.dumps({'inventory':inventory(),'probes':{n:probe(n) for n in ('claude','gemini','opencode','acp')}},indent=2))"
```

Os testes usam processos Python locais reais como **fixtures de protocolo**:
banner de versão, handshake, recusa de pedidos, stderr volumoso, limites de
linha/total/mensagens, saída malformada, cancelamento, timeout, bloqueio de escrita,
limpeza de descendentes e recusa de execução sem certificação. As versões
`2.1.300`, `0.40.0` e `1.2.3` dentro dos testes são dados artificiais, não versões
instaladas nem certificadas. Nenhum desses testes comprova inferência real.

Para desbloquear um runtime em outra etapa: disponibilizar executável autorizado,
inspecionar a versão exata, verificar isolamento de configuração e superfície
efetiva vazia de ferramentas (incluindo hooks/MCP/plugins/subagentes), implementar
sondagem segura de autenticação e o adaptador de texto/envelope de ação, validar
o contrato do gateway e só então realizar uma inferência real autorizada. Testes
com fixture continuam separados da evidência real. Nada foi instalado ou
autenticado automaticamente para contornar esses requisitos.
