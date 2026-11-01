# Execução de runtimes externos — 31/10/2026

Implementação local para web e desktop. Nenhum ensaio usa Codex como trabalhador.

## Instalação e uso

Na raiz do repositório, execute `.\runtime-tools\install_windows.ps1` no PowerShell. Requer Node.js/npm. Instala versões fixadas em `%LOCALAPPDATA%\Central IA\runtime-tools`, separadas do instalador principal, sem alterar PATH ou instalação global. `CENTRAL_RUNTIME_TOOLS_DIR` permite uma pasta absoluta administrada pelo operador. Outras versões são recusadas até validação.

Em **Provedores → Runtimes externos**, clique em **Verificar runtimes externos**, escolha o perfil, uma conexão API compatível (ou chave API) e o modelo. Conectar verifica a versão e cria implementador/revisor sem inferência. Não comprova saldo ou acesso ao modelo. O inventário não certifica contas ou modelos arbitrários.

Esta integração usa **chaves API**, suas cotas e cobrança, sem reutilizar login ou assinatura pessoal dos CLIs. Claude exige Anthropic; Gemini e ACP exigem Gemini; OpenCode usa `provedor/modelo` compatível com a conexão. ACP usa Gemini por padrão; outro backend explícito é recusado. Agentes ACP genéricos continuam apenas em diagnóstico.

| Perfil | Versão | Evidência real nesta máquina |
|---|---|---|
| Claude Code | 2.1.316 | Executável e versão verificados; inferência pendente de conexão Anthropic |
| Gemini CLI | 0.66.0 | Correção e revisão concluídas; revisão precisou de retomada explícita após falha |
| OpenCode | 1.19.5 | Correção e revisão concluídas com Google/Gemini; Groq falhou no ensaio completo |
| ACP v1 / Gemini | 0.66.0 | Initialize, autenticação API, sessão, prompt, correção e revisão concluídos |

## Controle e limites

Os CLIs devolvem texto/JSON de ações; a Central aplica permissões, leitura, alterações com SHA, validação e auditoria. Ferramentas nativas, MCP, hooks, plugins e descoberta do perfil pessoal são desativados ou negados. Configuração administrativa incompatível é recusada. Diretório e HOME descartáveis; chave apenas no ambiente do processo, sem argumento de linha de comando. Erros retornam códigos sem o corpo potencialmente sensível do CLI.

Há limites de entrada/saída, deadline, cancelamento e encerramento da árvore de processos pertencente à execução. O perfil **não constitui sandbox de sistema operacional**: os binários instalados são software confiável. Execução recusada no modo servidor. Caminhos arbitrários e versões não fixadas não são aceitos.

OpenCode usa agente dedicado de texto e ferramentas negadas. Groq/openai/gpt-oss-20b respondeu ao teste simples, mas no ciclo completo retornou erro de chamada de ferramenta com tool choice none. A negação foi preservada. Google/gemini-3.5-flash-lite concluiu o ciclo; isso não certifica outros modelos.

## Reprodução e evidências

```powershell
$env:PYTHONPATH = (Get-Location).Path
python examples/validate_external_runtime.py gemini C:\Labs\gemini-novo --source-data .\data
python examples/validate_external_runtime.py opencode C:\Labs\opencode-novo --source-data .\data --source-kind gemini
```

A pasta de destino deve ser nova. O harness lê uma conexão autorizada em modo somente leitura, mantém a chave em memória, injeta um defeito Python e executa implementador/revisor. `--resume` retoma sem reescrever arquivos. Não altera a base original. `report.json` e `attempts.jsonl` registram resultados; uma verificação funcional independente confirma a soma. Compilação sozinha não prova funcionalidade.

- Gemini `e614c93d-6f75-47f6-ad34-68ff72e26b24`: concluído após retomada explícita da revisão; compilação e verificação funcional independente passaram.
- ACP `948fa9b8-0b7b-4b2f-813f-5d9ef14b75df`: concluído; compilação e verificação funcional independente passaram.
- OpenCode/Google `0d0512ae-c3d4-48e5-8083-0a972b88c165`: concluído em 12 invocações CLI; pytest e verificação funcional independente passaram.
- OpenCode/Groq `406dea3d-8d1b-4cc3-85aa-a51fe8ce2711`: falhou antes de editar; registros preservados.

Os casos aprovados alteraram app.py pelas ferramentas da Central e passaram pela revisão, sem reparo manual no aplicativo. A retomada Gemini foi feita pelo operador; não comprova recuperação totalmente autônoma. OpenCode já inclui a correção da descoberta de testes Python na raiz.

São tarefas Python pequenas. Não substituem aceitação de projeto maior, QA visual ou homologação de todos os modelos. A etapa 11 continua pendente.

## Referências

- [Claude CLI](https://code.claude.com/docs/en/cli-reference)
- [Gemini configuração](https://geminicli.com/docs/reference/configuration/) e [políticas](https://geminicli.com/docs/reference/policy-engine/)
- [OpenCode CLI](https://opencode.ai/docs/cli/), [agentes](https://opencode.ai/docs/agents/) e [permissões](https://opencode.ai/docs/permissions/)
- [ACP v1](https://agentclientprotocol.com/protocol/v1/session-setup) e [segurança](https://agentclientprotocol.com/protocol/v1/security)
## Busca de modelos no painel

Desde o desktop 0.2.5 e a atualizacao web correspondente, colar a chave API ou selecionar uma conexao salva inicia a consulta automatica do catalogo. A lista considera a credencial atual; respostas antigas sao descartadas ao trocar a chave/runtime. Ha botao Atualizar modelos e entrada manual como alternativa. OpenCode permite selecionar o provedor da chave e aplica o prefixo correto ao modelo.

A consulta usa somente a listagem de modelos, sem executar CLI, gerar resposta ou criar trabalhadores. O acesso efetivo, as cotas e a compatibilidade final do modelo sao confirmados na execucao. Teste real do catalogo Gemini nesta maquina retornou 34 modelos de geracao; a chave nao foi exibida ou alterada.
