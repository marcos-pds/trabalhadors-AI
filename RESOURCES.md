# Skills, pacotes VSIX e configurações MCP

Esta entrega mantém o perfil local da Central. São três tipos distintos:

| Tipo | Implementado | Não implementado |
| --- | --- | --- |
| Skill | Importação por arquivo/pasta e URL GitHub pública; token de leitura é solicitado somente quando necessário, com prévia, confirmação, gestão, ativação, associações e contexto nos modelos | Scripts, hooks, carregamento dinâmico de anexos e instalação de dependências |
| VSIX | Inspeção estática, armazenamento privado, busca consentida de metadados públicos do Marketplace, exportação, instalação e desinstalação local com revisão separada | Download do Marketplace, dependências automáticas e ponte de ferramentas |
| MCP | Importação inativa; ativação do manifesto oficial Chrome DevTools MCP 1.0.1; cliente `stdio` fixo; inspeção local aprovada por chamada | Comandos/args/env importados, servidores MCP arbitrários, HTTP/SSE e navegação para sites externos |

Importação nunca ativa recursos. A inspeção não certifica segurança ou
autenticidade do autor. VSIX não oferece ferramentas aos agentes. Skills
precisam de associação explícita. O servidor MCP só é executado após ativação
separada, com pacote npm fixado e sem usar comandos declarados no arquivo.

## Arquitetura e decisões

A análise anterior à implementação confirmou autenticação por sessão e CSRF,
papéis em `organizations.py`, segredos Fernet em `security.py`, autorização
de pastas em `computer_access.py`, vínculo imutável de workspace, aprovações
no executor e Docker opcional. Esses componentes continuam responsáveis por
autorizar qualquer ferramenta. Nenhum comando foi acrescentado ao executor.

As migrações SQLite **9, 10 e 11**, aditivas e com checksum, criam `ai_resources`,
`skill_bindings` e o registro mínimo `resource_run_usage`. Conteúdo e metadados são criptografados com a chave existente
da Central. Proprietário, organização, tipo, SHA-256, estado, tamanho, data e
origem genérica ficam no registro. Caminhos locais de importação não são
persistidos. A versão pertence aos metadados imutáveis; uma nova versão exige
uma nova importação e revisão.

Os módulos `addon_packages`, `addon_catalog` e `addon_api` separam inspeção,
permissões/persistência e HTTP. As rotas usam a autenticação existente, exigem
cliente local e validam CSRF e origem (incluindo porta) nas mutações.
Arquivos são enviados ao backend local, nunca a serviços de inspeção externos.
Não há extração de ZIP para o disco ou execução de hooks. Configurações MCP
nunca resolvem endpoints. As leituras externas do importador Git acontecem somente após ação explícita do usuário; repositórios públicos são consultados sem credencial. Buscas de metadados do Marketplace exigem consentimento.

### Importação de Skill pelo Git

Cole uma URL HTTPS do GitHub. Repositórios públicos são consultados sem token; a URL da raiz usa a branch padrão. Links `tree` também podem especificar uma branch simples e uma pasta.

Na URL da raiz, a Central procura todas as pastas que contenham `SKILL.md` e mostra uma prévia em lote. Cada Skill distinta aparece separadamente; cópias byte a byte idênticas (mesmo SHA de blob) são agrupadas e importadas uma só vez, com seus caminhos exibidos. A confirmação cria todas como recursos privados e inativos em uma única transação; se uma delas falhar, nenhuma é salva. São aceitas até 50 Skills por lote e até 32 MiB no conjunto. O escaneamento da raiz é limitado a 50.000 entradas e a resposta da API a 8 MiB; quando o GitHub trunca a árvore, a prévia avisa que a lista pode estar incompleta. Um link `tree` para uma pasta continua limitando a busca à pasta indicada.

Na busca pela raiz, pastas `test`, `tests`, `__tests__` e `fixtures` são excluídas; links diretos continuam permitindo inspecioná-las. Se os anexos excederem os limites por arquivo, quantidade ou tamanho total, a prévia oferece somente `SKILL.md` e informa o número de arquivos omitidos antes da confirmação. Essa modalidade não instala o CLI, scripts ou referências auxiliares do pacote. O limite de 64 KiB do próprio `SKILL.md` permanece obrigatório. A versão também pode ser declarada em `metadata.version`, como nas variantes Codex. Campos `user-invocable`, `disable-model-invocation` e `argument-hint` são aceitos como metadados inertes, sem alterar permissões.

A Central interpreta apenas `SKILL.md` e arquivos auxiliares dentro da pasta escolhida. Não converte extensões VSIX, manifests MCP, comandos ou arquivos específicos de outras ferramentas em Skills; esses recursos continuam separados. Scripts e hooks nunca são executados.

A API acessada é fixa (`api.github.com`), sem seguir redirecionamentos e sem usar proxy do ambiente. Quando a consulta pública falha por acesso privado/inexistente, a tela oferece uma conexão Git salva correspondente ou permite cadastrar um token fine-grained de leitura. Se a URL for pública, não é necessário conectar uma conta. O token é cifrado pelo mecanismo existente e nunca é aceito dentro da URL. Respostas que indiquem limite temporário da API são exibidas como limite, não como falta de autenticação.

A prévia precisa de confirmação separada. O hash do commit e a origem ficam associados ao recurso; o nome/caminho privado do repositório só aparece ao proprietário. O importador limita o número e o tamanho dos arquivos, rejeita symlinks e submódulos, não faz checkout e não executa arquivos, mesmo que o pacote contenha arquivos executáveis.

### Busca de extensões VS Code

Na aba VSIX, a busca só ocorre depois de marcar consentimento. Somente o texto
de busca é enviado ao endpoint fixo do Marketplace; são devolvidos no máximo
20 registros de metadados. O código não solicita arquivos/URLs de pacotes nem
baixa VSIX. Uma extensão listada não está instalada nem fornece ferramentas aos
agentes. Importar um VSIX local continua sendo uma ação separada com inspeção
estática; a instalação só ocorre após revisão e confirmação na Central.

### Chrome DevTools MCP

Importe o `server.json` do registro oficial MCP, disponível no projeto em
`examples/chrome-devtools/server.json` (versão 1.0.1), e revise a prévia. A
Central aceita a ativação somente desse manifesto exato e inicia
`chrome-devtools-mcp@1.0.1` com `npx`; valores importados de `command`, `args`,
`env`, endpoints ou headers nunca são executados. O Python MCP SDK é uma
dependência da Central. O Node.js e um Chrome compatível precisam estar
instalados no host.

As ações disponibilizadas aos agentes são leitura de páginas, snapshot,
console, estilos, Lighthouse e abertura/navegação local. O agente não recebe
shell, execução de JavaScript na página, upload, digitação ou submissão de
formulários. O usuário aprova cada chamada no chat. Só são aceitos endereços
HTTP(S) em `localhost`, `127.0.0.1` ou `::1`; a allowlist de navegação também
bloqueia redirecionamentos externos. Abas não locais são ocultadas e não podem
ser selecionadas. A integração não conecta ao perfil pessoal do Chrome.

No painel **Memória e histórico** de cada projeto, escolha entre:

- **Isolada por execução** (padrão): perfil Chromium temporário e removido ao
  encerrar a execução.
- **Persistente no projeto**: perfil separado do Chrome pessoal, em diretório
  privado da Central, mantendo cookies e armazenamento local entre execuções
  daquele projeto. O perfil não é compartilhado entre contas.

O servidor MCP permanece aberto durante a execução e é encerrado ao finalizar,
falhar, pausar ou cancelar a tarefa. As seis Skills do repositório oficial são
importadas separadamente pelo preview GitHub como lote privado e inativo; a
Central não as ativa nem associa automaticamente.

### Pesquisa técnica e referências externas

Nas tarefas autônomas, o Pesquisador IA pode consultar documentação pública por
uma busca fixa no DuckDuckGo. Antes de cada requisição, a Central mostra a
consulta exata e aguarda aprovação; só o texto dessa consulta é enviado ao
serviço de busca. Não inclua nomes privados de projetos, trechos do workspace,
prompts completos ou segredos. A Central não abre nem baixa os resultados da
busca: registra título, URL e trecho retornados como referências externas não
confiáveis, que devem ser conferidas antes de orientar mudanças.

Tarefas que pedem explicitamente teste com Chrome DevTools MCP não começam se
a integração oficial estiver inativa. A conclusão também é bloqueada até que
snapshot, console e Lighthouse tenham sido executados depois da última mudança
de código. Cada chamada ainda depende da aprovação individual no chat e só
pode acessar endereços locais.

Prévias validadas ficam somente em memória por até dez minutos de validade,
com limite de duas por conta, 16 por processo e 64 MiB de conteúdo no processo.
A limpeza de expiradas ocorre nas operações de prévia/confirmação. Reiniciar
o backend invalida as prévias. Cancelar remove a cópia em memória. Confirmar
consome o token uma única vez e grava um recurso **privado e inativo**.
O conteúdo confirmado é o mesmo snapshot apresentado, mesmo se o arquivo
original mudar depois. Limite persistente: 50 recursos e 64 MiB originais por
proprietário. O SQLite cifrado tem overhead adicional. A listagem mostra até
200 recursos recentes acessíveis à conta.

### Isolamento e papéis

- Recursos pessoais só são acessíveis ao proprietário.
- Compartilhar é uma operação posterior e explícita do proprietário,
  exigindo que ele seja administrador da organização de destino.
- Membros podem inspecionar/exportar recursos compartilhados; administradores
  podem ativar, desativar, revogar ou excluir um recurso da organização.
  Somente o proprietário pode transferi-lo para outro escopo.
- Analistas não podem criar associações. Operadores/administradores podem
  associar Skills compartilhadas a seus agentes, projetos permitidos ou suas
  execuções, sem compartilhar seus chats ou credenciais pessoais.
- Associações pertencem ao usuário que as criou: uma associação de projeto
  não liga a Skill automaticamente às execuções dos colegas.
- Uma Skill organizacional só entra em execuções da mesma organização.
  Papéis e associação à organização são revalidados antes de cada chamada.
- Alterar o escopo desativa o recurso e remove associações. Revogar remove
  associações; excluir remove o conteúdo e as associações por cascade.
  Backups existentes têm retenção independente.

Auditoria registra somente IDs, ação e resultado, sem conteúdo, caminhos,
prompts, comandos ou segredos. Exportações são downloads como anexo com
`nosniff` e `no-store`, não páginas HTML executáveis.

## Como usar

1. Atualize o código, execute `npm run build` e reinicie a Central. A migração
   será aplicada pelo mecanismo existente. Mantenha seu backup habitual.
2. Faça login e abra **Skills e integrações** no menu.
3. Selecione o tipo, escolha o arquivo e revise metadados, conteúdo ou
   declarações, além do SHA-256. Confirme **importação inativa**.
4. Para uma Skill, revise e confirme sua ativação separadamente. Depois
   selecione agente, projeto ou execução e confirme a associação.
5. Desative, desassocie, revogue ou remova conforme necessário. Mudanças valem
   para próximas chamadas; dados já enviados ao provedor não são recuperáveis.

Skills selecionadas podem ser enviadas aos provedores de IA habilitados da
conta, inclusive durante failover. A ativação/associação informa isso na tela.
Não inclua segredos em instruções ou arquivos importados.

## Formato de Skill

Aceita arquivo **SKILL.md**, ZIP contendo esse arquivo na raiz (ou numa única
pasta superior) ou leitura explícita de uma pasta autorizada. Exemplo:

```markdown
---
name: revisao-python
description: Orientações de revisão para Python
version: 1.0.0
---
Revise clareza, tratamento de erros e testes. Explique as alterações propostas.
```

O cabeçalho aceita somente os escalares `name`, `description` e `version`.
Não há interpretador YAML: tags, aliases, objetos, hooks, campos desconhecidos
e blocos multilinha são recusados. `name` usa letras minúsculas ASCII, números
e hífens; descrição até 1.000 caracteres. A versão é semântica; se omitida,
é registrada como `1.0.0`. O corpo deve ser texto UTF-8 não vazio.
Esse subconjunto não importa automaticamente todos os formatos de Skills de
outros produtos; adapte os metadados ao formato acima.

Limites: upload/total descomprimido de 1 MiB, até 100 entradas (incluindo
diretórios), 256 KiB por arquivo, SKILL.md até 64 KiB e profundidade de caminho
até 12 componentes. Os arquivos anexos são preservados para exportação,
mas nunca executados ou carregados no contexto.

A importação por pasta recebe um **caminho relativo** à pasta já autorizada
em Computador e exige modo `full`. O modo `ask` não é convertido em permissão
de leitura recursiva: use SKILL.md/ZIP selecionado manualmente nesse caso.
Reutiliza as restrições de arquivos secretos, links e junções existentes.
Não selecione uma árvore alterada simultaneamente por processos não confiáveis;
as verificações locais não são isolamento de filesystem contra um atacante
com os mesmos privilégios no host.

### Seleção e contexto real

Busca somente entre Skills **ativas e explicitamente associadas** à execução,
ao projeto da conversa ou ao agente. Não há busca fora desse escopo. A Central
monta um catálogo factual limitado às primeiras 20 Skills (com indicação de
truncamento), compara termos do pedido com nome, descrição e instruções e
seleciona até quatro correspondências. Nome e descrição têm maior peso; texto
de instruções desempata/reforça correspondências. O ranqueamento é lexical,
não semântico: termos sem correspondência textual podem não encontrar a Skill.
Em caso de empate, prevalece a ordem **execução → projeto → agente**, com IDs
ordenados dentro de cada grupo e deduplicação. Cada corpo selecionado tem até
3.500 caracteres e 10.000 caracteres totais. Quando o `SKILL.md` é maior, o
contexto mantém seu início e prioriza blocos com termos relevantes ao pedido,
sem incluir anexos ou referências não importadas. Regras fora dos trechos ainda
podem ficar indisponíveis. O limite serializado é de 11.000 caracteres. O catálogo factual enviado junto do contexto
inclui nomes, descrições resumidas e escopo; a aplicação registra na atividade
quais Skills estavam disponíveis e quais foram selecionadas para a chamada.

`SkillContextClient` envolve o cliente no motor, incluindo o caminho autônomo.
Acrescenta contexto efêmero a cada chamada e revalida estado/permissões. Não
altera o transcript original ou o checkpoint, nem registra as instruções em
eventos de auditoria. Respostas factuais sobre disponibilidade devem usar o
catálogo enviado, e o modelo é instruído a não alegar uso de Skills que não
estejam na lista selecionada. Como a resposta ainda é gerada por um modelo,
isso melhora a fundamentação e a rastreabilidade, mas não garante obediência
perfeita. O contexto da Skill é enviado antes do pedido atual, que permanece
como última mensagem, e o modelo recebe instruções para seguir a Skill pertinente
sem inventar conteúdo ausente. O papel de planejamento restrito só é aplicado
a trabalhadores de planejamento quando a tarefa pede uma implementação.
Respostas seguem o fluxo normal de conversa e podem mencionar o
contexto; isso não representa cópia automática do pacote para o histórico. O
catálogo e o contexto adicional entram na estimativa de orçamento.

O conteúdo é identificado como não confiável. Não substitui a solicitação do
usuário, não modifica política, não cria ferramentas e não concede acesso à
pasta. As verificações de workspace, aprovações e sandbox continuam no backend.

## Pacotes VSIX

Upload local `.vsix`: até 8 MiB comprimidos, 32 MiB descomprimidos, 1.000
entradas e 8 MiB por entrada. O manifesto `extension/package.json` tem limite
de 256 KiB. A inspeção mostra nome, publisher, versão, descrição, faixa de
compatibilidade `engines.vscode`, dependências de extensões e comandos
declarados. Campos de localização, scripts e código não são executados.
`minimum_vscode` é informado para versões/faixas simples; em expressões
compostas, a faixa original é exibida sem inventar um limite mínimo.

ZIPs com traversal, caminhos absolutos/Windows ambíguos, symlinks, tipos
especiais, reparse points, duplicatas (incluindo diferenças de caixa/Unicode),
colisões arquivo/diretório, criptografia ou proporção de compressão excessiva
são rejeitados. Validação estrutural não equivale a antivírus ou assinatura.

**Remover pacote da Central não desinstala nada do VS Code.** Para instalar, selecione o VS Code estável encontrado nos caminhos padrão do Windows e confirme a ação separadamente após revisar o risco: extensões executam código com privilégios do usuário. O instalador só aceita VSIX pessoal, recusa dependências/pacotes de extensão, escreve temporariamente o arquivo já revisado e chama o `Code.exe` validado com argumentos fixos. A Central verifica a versão instalada antes de informar sucesso. Não usa `--force`, não baixa do Marketplace e não instala dependências.

A desinstalação também requer confirmação separada e identifica a extensão pelo publisher/nome do VSIX importado. Ela desinstala do destino VS Code selecionado, mas não remove o pacote da Central. Somente instalações estáveis localizadas em `%LOCALAPPDATA%\Programs\Microsoft VS Code`, `%PROGRAMFILES%\Microsoft VS Code` ou `%PROGRAMFILES(X86)%\Microsoft VS Code` são listadas. Extensões com dependências declaradas precisam ser tratadas manualmente no VS Code. Uma ponte futura com agentes precisará de protocolo autenticado e autorização de workspace separados. Não há download do Marketplace nesta entrega.

## Configuração declarativa MCP da Central

JSON até 128 KiB, sem campos desconhecidos ou chaves JSON duplicadas:

```json
{
  "name": "documentos",
  "version": "1.0.0",
  "transport": "streamable-http",
  "endpoint": "https://mcp.example.org/mcp",
  "permissions": ["workspace.read"],
  "tools": [
    {
      "name": "buscar",
      "description": "Descrição declarada pelo autor, não verificada",
      "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}}
      }
    }
  ]
}
```

Configurações declarativas de outros servidores podem ser importadas e
exportadas, mas não ativadas. O importador só ativa o manifesto exato do
Chrome DevTools MCP 1.0.1, sem aceitar executáveis, argumentos, variáveis de
ambiente, endpoints ou credenciais do arquivo. A execução passa pela política
de workspace e por uma aprovação humana de cada ferramenta; veja a seção
**Chrome DevTools MCP** acima. Endpoints declarativos, inclusive URLs locais,
continuam sem conexão.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm test
npm run build
```

`tests/conftest.py` define uma pasta temporária antes de importar a aplicação,
para nunca aplicar migrações ao banco local do usuário durante pytest.
Os testes exercitam os parsers, RBAC, escopos, confirmações, expiração,
revogação, estados distintos, disponibilidade por execução, registro idempotente
de Skills oferecidas ao modelo, limites e UI renderizada.
O CI inclui a suíte Python e os novos testes Node, além do build React.

Referências de formato: [manifesto VS Code](https://code.visualstudio.com/api/references/extension-manifest)
e [transportes MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
Essas referências não significam suporte a extensões arbitrárias ou a servidores
MCP fora do Chrome DevTools oficial, pinado e aprovado.

### Arquivos desta entrega

- Backend: `central/addon_packages.py`, `central/addon_catalog.py`,
  `central/addon_api.py`, `central/vscode_install.py`, `central/addon_git_import.py`,
  `central/addon_marketplace.py`, `central/addon_schema.py`,
  `central/browser_mcp.py`, `central/migrations.py`, `central/main.py` e
  `central/engine.py`.
- Interface: `frontend/src/ResourcesPanel.jsx`, `frontend/src/resourceClient.mjs`
  `frontend/src/ConversationMemoryPanel.jsx` e `frontend/src/App.jsx`.
- Testes: `tests/test_addon_resources.py`, `tests/test_browser_mcp.py`,
  `tests/test_app.py`, `tests/test_agent_autonomy.py` e
  `frontend/src/resources.test.mjs`.
- Histórico seguro das operações VS Code: migração 11 em `central/migrations.py`.
- Preferência e perfil de navegador por projeto: migração 14 em `central/migrations.py`.
- Execução dos testes: `package.json` e `.github/workflows/ci.yml`.
- Documentação: `README.md`, `ROADMAP.md` e este arquivo.

### Evidência local desta etapa

Nesta alteração, a suíte Python completa aprovou **457 testes, com 26 ignorados**;
`npm test` aprovou **31 testes**, `npm run build`, `compileall` e
`git diff --check` também passaram. Os testes cobrem importação/ativação estrita
do manifesto, restrição a loopback, filtro de páginas, aprovação por ferramenta,
preferência do navegador por projeto e remoção explícita do perfil. O teste
automatizado não iniciou o pacote npm nem o Chrome real: a conexão real só deve
ser iniciada em modo headless após o usuário ativar o recurso e aprovar uma chamada
no chat.

### Compatibilidade de metadados externos

Skills aceitam também `license` e `allowed-tools` (texto ou lista simples de até 32 itens). Esses campos são apenas declarativos: não liberam ferramentas, comandos, permissões ou execução. Outros formatos YAML continuam sujeitos à validação restrita.

O teste `test_real_impeccable_metadata_and_private_import` usa um snapshot real obtido em 25/10/2026 de https://github.com/pbakaus/impeccable/blob/main/.agent/skills/impeccable/SKILL.md (Apache 2.0). Verifica validação, confirmação, gravação privada e estado inativo. Não equivale a um teste de download do repositório inteiro nem da interface em execução.