# Ciclo real de criação e correção — 29/10/2026

## Resultado comprovado

O motor da Central criou um site, usou Codex implementador e revisor, iniciou sua
própria prévia, testou os controles pelo Chrome DevTools MCP e concluiu a entrega.
Depois, um defeito foi introduzido pelo operador do ensaio. Com um único pedido
de correção, a equipe reproduziu o erro no navegador, observou a falha no console,
alterou o arquivo e repetiu as verificações. A aceitação independente em desktop
e celular passou. Nenhuma correção do código do aplicativo foi escrita pelo
operador; a injeção deliberada do defeito é a exceção documentada.

Aplicativo: **Laboratório Central**, contador com campo Nome, Contar e Zerar,
frontend HTML/CSS/JS e servidor Node sem dependências externas.

Demonstração deixada rodando para inspeção: http://127.0.0.1:8892/ . O operador
iniciou essa demonstração final depois de o ensaio encerrar suas próprias prévias.
Isso não é a evidência de início autônomo; os quatro pedidos `preview start`
registrados nos dois runs são a evidência de que os trabalhadores iniciaram a
aplicação durante o trabalho.

## Ambiente e rastreabilidade

- Mesmo `Engine`, gateway, contratos de entrega, checkpoints e adaptador Codex
  utilizados pela aplicação; execução direta do motor pelo harness de teste.
- Dados e workspace novos em
  `C:\Projetos\Central-IA\ciclo-autonomo-20261029-a`.
- Banco do ensaio: `data\central.sqlite3`, separado da produção.
- Modelo: `gpt-6.1-sol`, login ChatGPT gerenciado pelo CLI certificado.
- Criação: `4afa29c2-a147-4c37-80dd-eb2fa79fde13`.
- Correção: `dc4bcf28-b897-46d4-989c-b386e67d4593`.
- Projeto do banco isolado: `88a6e647-1059-4992-90af-2a9b229bec3c`.

O projeto existe no banco de homologação; não foi inserido artificialmente na
lista de projetos da instância de produção. A interface HTTP da Central não foi
o meio de envio deste ensaio: ele exercita diretamente seu motor real.

Pedido único enviado na fase de correção:

> Verifique o site deste projeto, teste os botões no navegador e corrija o que estiver quebrado.

O brief inicial da criação incluiu os critérios de aceite, IDs estáveis para a
avaliação independente e ausência de dependências externas. Portanto, a criação
não é um ensaio de compreensão de um pedido mínimo. A correção usa o pedido
curto acima, sem indicar ao trabalhador o arquivo ou a solução.

## Sequência observada

| Fase | Resultado registrado |
| --- | --- |
| Criação pela equipe | Arquivos criados, build e cinco testes Node aprovados, campo e botões exercitados, console limpo e Lighthouse desktop/mobile aprovados |
| Aceitação independente inicial | Desktop e celular: cinco cliques → 5; Zerar → 0; `/api/health` saudável; sem erro de console/rede ou overflow |
| Injeção controlada | O operador anexou ao `app.js` um handler defeituoso que mostra `Erro` e escreve uma falha no console ao clicar |
| Aceitação independente negativa | Desktop e celular reprovaram; contador mostrou `Erro` e o console registrou falhas |
| Reprodução pelo trabalhador | Iniciou prévia, abriu o site, clicou e consultou o console antes de editar |
| Correção pelo trabalhador | `replace` com SHA removeu o handler defeituoso de `app.js` |
| Reteste e revisão | Recarregamento, cliques, preenchimento, console, Lighthouse desktop/mobile, build/test e leitura pelo revisor |
| Aceitação independente final | Desktop e celular aprovados: 5, depois 0; saúde OK; zero erros de console/rede e sem overflow |

Ordenação no journal da correção: **seq 555**, console reprovado; **seq 562**,
alteração de `app.js`; **seq 667** e **830**, validações aprovadas; **seq 833**,
run concluído. O SHA-256 final do `app.js` corresponde ao arquivo original
anterior à injeção: a equipe restaurou o comportamento, sem o operador reverter
o defeito.

Ferramentas efetivamente usadas: list/read/write/replace, comandos de build e
teste, `preview start`, `list_pages`, `new_page`, `navigate_page`, `take_snapshot`,
`fill`, `click`, `list_console_messages` e `lighthouse_audit`. Houve também
comunicação entre os trabalhadores; isso não é teste de delegação dinâmica.

## Intervenções e limites

1. O primeiro início falhou porque o Codex confundiu o sandbox nativo read-only
   com o workspace controlado pela Central. O contrato de transporte foi
   esclarecido no adaptador, mantendo o sandbox nativo e o gateway. O mesmo run
   foi retomado do checkpoint. A falha original permanece no banco.
2. O harness precisou ser retomado após tentar consultar uma prévia depois do
   término do run. A revogação ao concluir permaneceu intacta. O operador
   reiniciou uma prévia separada **apenas para a aceitação independente inicial**.
   Essa intervenção está no evento `test_operator_preview_restarted` da criação.
   Não houve esse reinício na fase de correção.
3. As aprovações não foram removidas: o harness, como operador, respondeu a
   **46 aprovações**, 21 na criação e 25 na correção, com uma política fixa para
   prévia e navegador do projeto local. O modelo não recebeu poder para aprovar
   a si mesmo. Instalações e pesquisa externa seriam negadas. Isso comprova
   autonomia operacional dentro de autorização prévia, não acesso irrestrito.
4. A aceitação final usa Playwright independente. Os cliques, a reprodução e o
   reteste que fundamentam a autonomia também foram executados pelo próprio
   trabalhador via MCP, não apenas pelo avaliador externo.
5. É um caso simples e controlado. Não comprova recuperação de qualquer bug,
   paralelismo com worktrees, múltiplos runtimes ou uso geral de plugins/MCP.

## Melhorias na Central decorrentes do ensaio

- Ação estruturada `preview` com start/status/stop, aprovação ao iniciar,
  rechecagem de escopo e de política de comandos, propriedade por run e limpeza.
- Prévia host com criação serializada, ambiente reduzido, prazo de vida,
  cancelamento e log limitado em memória para diagnóstico de falhas de início.
- Sessão MCP mantida por uma task proprietária: contexto AnyIO aberto e fechado
  na mesma task, inclusive quando implementador, revisor e dispatcher diferem.
- Contrato do Codex distingue propor JSON de executar ferramentas nativas.
- Orientação geral de correção exige reproduzir uma falha de UI antes de editar
  quando o servidor consegue iniciar, e testar novamente depois.
- Harness reproduzível com journal, checkpoints, hashes e verificações positivas
  e negativas; nenhuma função do harness implementa a correção do aplicativo.

Documentação oficial consultada para o contrato do adaptador:
[Codex App Server](https://learn.chatgpt.com/docs/app-server).
Mantidas as referências arquiteturais de
[nightly-labs/OpenBot](https://github.com/nightly-labs/openbot/blob/main/docs/architecture/browser.md)
e [CopilotKit/OpenBot](https://github.com/CopilotKit/OpenBot/blob/main/docs/architecture.md).
Nenhum código OpenBot foi incorporado.

## Evidências e reprodução

Regressão final: **885 testes Python aprovados, 30 ignorados**, dois avisos
existentes; **18 verificações da interface** em desktop/celular aprovadas, dois
opt-ins de iniciar prévia ignorados; compilação Python e `git diff --check`
aprovados. Os ensaios positivos/negativos do aplicativo e suas auditorias MCP
reais são evidências adicionais, distintas dos testes de protocolo simulados.

Na pasta do ensaio: `state.json`, `summary.json`, `defect.json`,
`creation_run-events.json`, `repair_run-events.json`, os dois arquivos de
delivery evidence e relatórios/capturas nas pastas `baseline`, `broken` e
`repaired-2026-10-29T23-20-19.259018+00-00`.

Capturas publicáveis deste ensaio:

- [Defeito reproduzido](ciclo-autonomo-erro-20261029.png)
- [Corrigido em desktop](ciclo-autonomo-corrigido-20261029.png)
- [Corrigido em celular](ciclo-autonomo-mobile-20261029.png)

Para um novo ensaio, escolha uma pasta nova e use o kit Playwright instalado:

```powershell
.\.venv\Scripts\python.exe -m examples.validate_autonomous_cycle C:\Projetos\Central-IA\novo-ciclo --kit C:\Users\marco\Downloads\central-ia-testes\central-ia-testes
```

`--resume` retoma os checkpoints em caso de falha/interrupção. Inferências reais
consomem a cota da conta Codex conectada. Os limites ampliados de 96 ciclos e 90
ações usados no ensaio foram variáveis do processo de teste; o servidor principal
mantém seus limites normais.

A Central principal foi reiniciada sem tarefas ativas. Responde HTTP 200 em
`http://127.0.0.1:8765/`; integridade SQLite OK e contagens das tabelas originais
iguais às do backup verificado da revisão anterior. Não houve alteração das
permissões de computador da produção. Mudanças de código continuam locais,
sem novo commit ou push.
