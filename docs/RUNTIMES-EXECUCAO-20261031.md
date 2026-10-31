# Execu??o de runtimes externos ? 31/10/2026

Implementa??o local para web e desktop. N?o executa Codex como trabalhador.

## Instala??o opcional

No PowerShell, na raiz do reposit?rio:

```powershell
.\runtime-tools\install_windows.ps1
```

Requer Node.js/npm. Instala pacotes fixados em `%LOCALAPPDATA%\Central IA\runtime-tools`, sem instala??o global nem altera??o do PATH. N?o inclui esses execut?veis no instalador principal. `CENTRAL_RUNTIME_TOOLS_DIR` permite uma pasta absoluta administrada pelo operador. N?o use atualiza??es autom?ticas nesses pacotes: outras vers?es s?o recusadas at? valida??o.

| Perfil | Vers?o | Evid?ncia real nesta m?quina |
|---|---|---|
| Claude Code | 2.1.316 | Execut?vel e vers?o verificados; infer?ncia pendente de conex?o Anthropic |
| Gemini CLI | 0.66.0 | Infer?ncia e corre??o/revis?o conclu?das; revis?o exigiu retomada expl?cita ap?s falha |
| OpenCode | 1.19.5 | Infer?ncia simples e teste de recusa de escrita nativa; homologa??o completa em investiga??o |
| ACP v1 / Gemini | 0.66.0 | Initialize, autentica??o API, sess?o, prompt e corre??o/revis?o conclu?dos |

Em **Provedores ? Runtimes externos**, clique em **Verificar runtimes externos**, escolha o perfil e uma conex?o API compat?vel j? cadastrada (ou informe uma chave API), selecione o modelo e conecte. S?o criados implementador e revisor. Conectar verifica a vers?o, n?o faz infer?ncia nem comprova saldo/acesso ao modelo. O campo `inference_homologated=false` no invent?rio n?o atesta contas ou modelos arbitr?rios.

Esta integra??o usa **chaves API**, cotas e cobran?a do provedor; n?o reutiliza login ou assinatura pessoal dos CLIs. Claude exige Anthropic; Gemini e ACP exigem Gemini; OpenCode usa modelo `provedor/modelo` compat?vel com a conex?o. ACP usa Gemini por padr?o; outro backend expl?cito ? recusado. Agentes ACP gen?ricos continuam apenas em diagn?stico.

## Controle e limites

Os CLIs recebem contexto e devolvem texto/JSON de a??es. A Central aplica permiss?es, leitura, altera??es com SHA, valida??o e auditoria. Ferramentas nativas, MCP, hooks, plugins e descoberta do perfil pessoal s?o desativados ou negados. Configura??o administrativa incompat?vel ? recusada. Diret?rio de execu??o e HOME descart?veis; chave apenas no ambiente do processo, sem argumento de linha de comando. Erros retornam c?digos, n?o o corpo potencialmente sens?vel do CLI.

H? limite de entrada/sa?da, deadline, cancelamento e encerramento da ?rvore de processos pertencente ? execu??o. O perfil **n?o constitui sandbox de sistema operacional**: os bin?rios instalados pelo operador s?o software confi?vel. Execu??o recusada no modo servidor. Vers?es n?o fixadas e caminhos arbitr?rios n?o s?o aceitos.

## Ensaios reproduz?veis

```powershell
$env:PYTHONPATH = (Get-Location).Path
python examples/validate_external_runtime.py gemini C:\Labs\gemini-novo --source-data .\data
```

A pasta de destino deve ser nova. O harness l? uma conex?o autorizada em modo somente leitura, mant?m a chave em mem?ria, injeta um defeito em uma fun??o Python e executa implementador e revisor. `--resume` retoma o mesmo laborat?rio sem reescrever os arquivos. N?o altera a base original. `report.json` e `attempts.jsonl` registram o resultado; uma verifica??o funcional independente confirma a soma. Compila??o sozinha n?o prova funcionalidade.

Evid?ncias locais: Gemini `e614c93d-6f75-47f6-ad34-68ff72e26b24` e ACP `948fa9b8-0b7b-4b2f-813f-5d9ef14b75df`. Ambos alteraram `app.py` pelas ferramentas da Central, passaram pela revis?o e pela verifica??o funcional independente. Nenhum reparo manual no aplicativo. A execu??o Gemini precisou de retomada pelo operador; n?o ? prova de recupera??o totalmente aut?noma. O primeiro OpenCode `406dea3d-8d1b-4cc3-85aa-a51fe8ce2711` falhou antes de editar e foi preservado.

Isso comprova uma tarefa Python pequena. N?o substitui a aceita??o de um projeto maior, QA visual ou homologa??o de todos os provedores/modelos. O roteiro de autonomia e a etapa 11 continuam com pend?ncias.

## Refer?ncias consultadas

- [Claude CLI](https://code.claude.com/docs/en/cli-reference)
- [Gemini configura??o](https://geminicli.com/docs/reference/configuration/) e [pol?ticas](https://geminicli.com/docs/reference/policy-engine/)
- [OpenCode CLI](https://opencode.ai/docs/cli/) e [permiss?es](https://opencode.ai/docs/permissions/)
- [ACP v1](https://agentclientprotocol.com/protocol/v1/session-setup) e [seguran?a](https://agentclientprotocol.com/protocol/v1/security)
