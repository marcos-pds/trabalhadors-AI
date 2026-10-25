# Skills, pacotes VSIX e configurações MCP

Esta entrega mantém o perfil local da Central. São três tipos distintos:

| Tipo | Implementado | Não implementado |
| --- | --- | --- |
| Skill | Importação por arquivo/pasta e repositório Git conectado, prévia, confirmação, gestão, ativação explícita, associações por usuário e contexto real nos modelos | Scripts, hooks, carregamento dinâmico de anexos e instalação de dependências |
| VSIX | Inspeção estática, armazenamento privado, busca consentida de metadados públicos do Marketplace, exportação e remoção da Central | Instalação/desinstalação no VS Code, download do Marketplace e ponte de ferramentas |
| MCP | Configuração declarativa, prévia das ferramentas/permissões declaradas, armazenamento inativo, revogação e exclusão | Conexão, descoberta de ferramentas, `stdio`, HTTP/SSE, chamada de ferramentas e credenciais de servidor |

Importação nunca ativa recursos. A inspeção não certifica segurança ou
autenticidade do autor. VSIX e MCP não oferecem ferramentas aos agentes.
O campo `runtime_enabled` só pode ser verdadeiro para uma Skill ativa.

## Arquitetura e decisões

A análise anterior à implementação confirmou autenticação por sessão e CSRF,
papéis em `organizations.py`, segredos Fernet em `security.py`, autorização
de pastas em `computer_access.py`, vínculo imutável de workspace, aprovações
no executor e Docker opcional. Esses componentes continuam responsáveis por
autorizar qualquer ferramenta. Nenhum comando foi acrescentado ao executor.

A migração SQLite **9**, aditiva e com checksum, cria `ai_resources` e
`skill_bindings`. Conteúdo e metadados são criptografados com a chave existente
da Central. Proprietário, organização, tipo, SHA-256, estado, tamanho, data e
origem genérica ficam no registro. Caminhos locais de importação não são
persistidos. A versão pertence aos metadados imutáveis; uma nova versão exige
uma nova importação e revisão.

Os módulos `addon_packages`, `addon_catalog` e `addon_api` separam inspeção,
permissões/persistência e HTTP. As rotas usam a autenticação existente, exigem
cliente local e validam CSRF e origem (incluindo porta) nas mutações.
Arquivos são enviados ao backend local, nunca a serviços de inspeção externos.
Não há extração de ZIP para o disco ou execução de hooks. Configurações MCP
nunca resolvem endpoints. As únicas leituras externas são pedidos explícitos
a uma conexão GitHub do usuário e buscas consentidas de metadados do Marketplace.

### Importação de Skill pelo Git

O importador usa uma conexão GitHub já salva pelo próprio usuário.
O link precisa corresponder exatamente ao provedor e repositório da conexão;
tokens não são aceitos em URLs. Links de repositório usam a branch padrão;
links `tree` podem apontar uma branch simples (sem `/`) e pasta. O importador precisa encontrar
exatamente um `SKILL.md`, limita o número e tamanho dos arquivos, rejeita
symlinks/submódulos e cria uma prévia que precisa de confirmação separada.
O hash do commit e a origem ficam associados ao recurso; o nome/caminho privado
do repositório só aparece ao proprietário. O importador não faz checkout e
não executa scripts, mesmo que a Skill contenha arquivos executáveis.

### Busca de extensões VS Code

Na aba VSIX, a busca só ocorre depois de marcar consentimento. Somente o texto
de busca é enviado ao endpoint fixo do Marketplace; são devolvidos no máximo
20 registros de metadados. O código não solicita arquivos/URLs de pacotes,
não baixa VSIX e não instala extensões. Uma extensão listada não está
instalada nem fornece ferramentas aos agentes. Importar um VSIX local continua
sendo uma ação separada com inspeção estática.

MCP pode expor ferramentas de Git quando um servidor MCP dedicado as implementa.
Esta Central não conecta nem executa esse servidor; sua configuração permanece
declarativa e inativa. A importação Git acima usa as conexões Git existentes,
sem alegar integração MCP funcional.

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

Seleção somente por associações explícitas. A ordem determinística é:
**execução → projeto da conversa → agente**, com IDs ordenados dentro de cada
grupo, deduplicação e no máximo quatro Skills. O corpo de cada Skill é
truncado em até 3.500 caracteres, com até 10.000 caracteres de corpos e limite
serializado de 11.000 caracteres; a mensagem adicional total fica abaixo de
12.000. Nem toda Skill associada cabe necessariamente no contexto.

`SkillContextClient` envolve o cliente no motor, incluindo o caminho autônomo.
Acrescenta contexto efêmero a cada chamada e revalida estado/permissões. Não
altera o transcript original ou o checkpoint, nem registra as instruções em
eventos de auditoria. Respostas do modelo seguem o fluxo normal de conversa e
podem mencionar o contexto; isso não representa cópia automática do pacote
para o histórico. O tamanho adicional entra na estimativa de orçamento.

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

**Remover pacote da Central não desinstala nada do VS Code.** Uma instalação
real exigiria escolha e validação do VS Code de destino, confirmação específica
e verificação dos riscos: extensões executam código com privilégios do usuário.
Uma ponte futura com agentes precisará de protocolo autenticado e autorização
de workspace separados. Não há download do Marketplace nesta entrega.

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

Transportes declarados: `stdio`, `streamable-http`, `sse`. Para `stdio`, omita
`endpoint`; não inclua `command`, `args` ou `env`. Para HTTP, o endpoint deve
ser URL HTTP(S) sem credenciais, query ou fragmento. Não há resolução DNS nem
conexão — inclusive URLs locais são apenas dados inativos, não endpoints
aprovados para uso futuro.

Ferramentas: até 100 nomes únicos, descrições até 1.000 caracteres e
`inputSchema` de objeto, com profundidade limitada e sem referências externas,
defaults ou examples. Permissões declaradas: `workspace.read`,
`workspace.write`, `network`, `external.write`. Declarar não concede nenhuma.
Esses dados são a descrição do importador; `tools_verified=false` indica que
não houve descoberta no servidor. Não é um formato universal de configuração
de clientes MCP; converta manifestos de outros clientes conscientemente.

Não são aceitos tokens, headers ou variáveis de ambiente de autenticação.
Nenhuma credencial MCP é usada ou necessária enquanto não houver transporte.
Não existe rota de conexão/chamada; a API rejeita ativação MCP. Portanto não
há SSRF de transporte, subprocesso ou contorno do Docker nesta entrega.
O transporte futuro exige proteção SSRF/DNS rebinding/redirects, consentimento,
allowlists por usuário/organização, timeouts, cancelamento, limites de resposta
e a mesma autorização de workspace. `stdio` exige configuração de executáveis
pelo operador, isolamento e encerramento confiável. Até lá, tudo fica inativo.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm test
npm run build
```

`tests/conftest.py` define uma pasta temporária antes de importar a aplicação,
para nunca aplicar migrações ao banco local do usuário durante pytest.
Os novos testes exercitam os parsers, RBAC, escopos, confirmações, expiração,
revogação, contexto nos dois caminhos do motor, limites e UI renderizada.
O CI inclui a suíte Python e os novos testes Node, além do build React.

Referências de formato: [manifesto VS Code](https://code.visualstudio.com/api/references/extension-manifest)
e [transportes MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
Essas referências não significam que a Central executa extensões ou MCP.

### Arquivos desta entrega

- Backend: `central/addon_packages.py`, `central/addon_catalog.py`,
  `central/addon_api.py`, `central/addon_git_import.py`,
  `central/addon_marketplace.py`, `central/addon_schema.py`, `central/migrations.py`,
  `central/main.py` e `central/engine.py`.
- Interface: `frontend/src/ResourcesPanel.jsx`, `frontend/src/resourceClient.mjs`
  e `frontend/src/App.jsx`.
- Testes: `tests/test_addon_resources.py`, `tests/conftest.py`,
  `tests/test_job_queue.py`, `tests/test_production_foundations.py` e
  `frontend/src/resources.test.mjs`.
- Execução dos testes: `package.json` e `.github/workflows/ci.yml`.
- Documentação: `README.md`, `ROADMAP.md` e este arquivo.

### Evidência local desta entrega

Em 25/10/2026, a seleção ampliada de 24 módulos aprovou **286 testes Python**,
com 25 ignorados (serviços opcionais/limitação de symlink do Windows) e sete
deselecionados por dependerem de sockets/asyncio. Os testes específicos desta
entrega aprovaram 63 casos, com um ignorado e um TestClient deselecionado.
**23 testes Node**, build React, compileall e `git diff --check` aprovados.

A suíte `pytest -q` integral foi iniciada e interrompida após 45 segundos:
o TestClient travou em `socket._fallback_socketpair`, antes de despachar a
requisição. Isso não é uma aprovação da suíte integral. O teste HTTP completo
permanece no CI; autorização HTTP, CSRF/origem e handlers de importação/exportação
também foram exercitados diretamente sem sockets. Não houve homologação visual
em navegador nem instalação VS Code ou execução de MCP.
