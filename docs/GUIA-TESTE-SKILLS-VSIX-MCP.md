# Guia para testar Skills, VSIX e MCP

Este roteiro testa a versão local da Central em Windows. Skills fornecem contexto aos agentes; VSIX são instalados pelo próprio VS Code; a ponte Chrome DevTools MCP é separada, restrita a páginas locais e protegida por aprovação por chamada.

## 1. Preparar e iniciar a Central

1. Faça uma cópia de segurança habitual dos dados locais antes da primeira inicialização com este código. As migrações são aditivas; esta versão acrescenta a preferência de sessão do navegador por projeto.
2. Abra o PowerShell na pasta do repositório:

   ```powershell
   cd C:\Users\marco\Documents\Central-de-Trabalhadores-IA-MVP\central-trabalhadores-ia
   ```

3. Gere a interface atual e inicie o servidor:

   ```powershell
   npm install
   npm run build
   .\.venv\Scripts\python.exe run.py
   ```

   Se a pasta `.venv` não existir, siga a instalação do `README.md` antes de executar esses comandos.
4. Acesse `http://127.0.0.1:8765`, entre na sua conta local e abra **Skills e integrações**.
5. Para testar o uso de uma Skill pelo modelo, tenha pelo menos um provedor habilitado e um agente selecionável. Isso pode gerar uma chamada cobrada ao provedor configurado.

## 2. Testar a Skill de exemplo

O arquivo [SKILL.md de exemplo](../examples/skills/revisao-python-segura/SKILL.md) já usa o subconjunto de metadados aceito pela Central.

1. Na área **Skills e integrações**, selecione o tipo **Skill** e escolha esse arquivo.
2. Revise o nome, a descrição, a versão, o conteúdo e o hash apresentados na prévia.
3. Confirme a importação. Ela deve aparecer como importada/inativa; a importação não ativa a Skill.
4. Selecione o recurso importado e escolha **Ativar**; marque a confirmação separada e confirme.
5. Na seção de associações, selecione **Agente**, escolha um agente seu e revise/confirme a associação.
6. Abra uma nova conversa/tarefa usando esse agente. Peça uma revisão curta de um trecho Python e veja se a resposta segue o formato da Skill: resumo, achados com evidência e sugestões. Não é esperado que a Skill execute comandos ou altere arquivos.
7. Desative ou desassocie a Skill e confirme. Isso afeta chamadas seguintes; texto já enviado ao provedor não pode ser recuperado.
8. Opcional: use **Exportar** para conferir o conteúdo exportado. Excluir da Central remove o recurso e as associações, então faça isso somente se quiser removê-lo.

Para testar a importação em lote, cole `https://github.com/pbakaus/impeccable` e busque a prévia sem selecionar uma conexão. A Central deve encontrar as pastas `SKILL.md`, agrupar cópias byte a byte idênticas, e listar cada conteúdo distinto numa prévia revisável. Confirme uma vez e confira que cada Skill aparece como recurso separado, privado e inativo. Para importar somente uma delas, use o link direto `https://github.com/pbakaus/impeccable/tree/main/.agent/skills/impeccable`; a busca fica restrita a essa pasta. Se a prévia avisar que a árvore foi truncada, a lista pode estar incompleta. Para testar o Git privado, cole uma URL de repositório privado; a tela deve oferecer uma conexão salva compatível ou um campo para token fine-grained com leitura somente daquele repositório; após conectar, deve continuar a busca com a URL já digitada. Para validar a prévia de erro sem tocar nos dados da Skill válida, selecione um arquivo incompatível ou acima do limite e confira que a Central rejeita o upload sem criar um recurso. Não coloque segredos em arquivos de teste.

## 3. Testar instalação e desinstalação VSIX

A instalação real executa uma extensão com os privilégios da sua conta do Windows. Use somente um `.vsix` local que você confia e que não declare dependências ou um pacote de extensões. Não use uma extensão de produção como teste se não estiver disposto a instalá-la.

1. Confirme que o VS Code **estável** está instalado em um dos locais padrão mostrados na tela. Se a lista de destinos estiver vazia, a Central não encontrou um `Code.exe` validado nos locais suportados.
2. Selecione **VSIX**, escolha um arquivo `.vsix` local e revise publisher, nome, versão, compatibilidade, comandos e hash.
3. Confirme a importação inativa. Isso apenas armazena o pacote na Central; ainda não instala a extensão.
4. Abra o pacote importado. Escolha o destino VS Code listado e confira a versão e o estado das extensões.
5. Clique em **Revisar instalação**, leia o aviso de privilégios e marque a confirmação separada. Confirme a ação.
6. A Central chama o CLI do VS Code com argumentos fixos e verifica a versão instalada. Confira o estado atualizado na tela e, se quiser, no VS Code.
7. Clique em **Revisar desinstalação** e confirme separadamente. Verifique que o estado da extensão deixa de aparecer como instalada.
8. Remover o pacote da Central é outra ação: isso não instala nem desinstala a extensão no VS Code.

O fluxo não baixa VSIX do Marketplace, não instala dependências e recusa pacotes que declaram `extensionDependencies` ou `extensionPack`. A busca do Marketplace é somente de metadados e exige consentimento próprio. A execução real do instalador não foi homologada automaticamente por testes: os testes automatizados simulam o CLI.

## 4. Testar Chrome DevTools MCP e Skills oficiais

1. Em **Skills e integrações**, mantenha o repositório predefinido `https://github.com/ChromeDevTools/chrome-devtools-mcp` e busque a prévia. Revise as seis Skills encontradas; confirme o lote somente se quiser importá-las como recursos privados e inativos. Depois associe e ative individualmente cada Skill necessária.
2. Selecione **MCP** e importe o `server.json` desse mesmo repositório. A Central só permite ativar o manifesto oficial exato, npm `chrome-devtools-mcp@1.0.1`; importações de outros servidores permanecem inativas.
3. Leia o aviso e confirme a ativação. O primeiro uso pode baixar o pacote fixado do npm. Instale Node.js e Chrome estável no host da Central. O arquivo importado não fornece comando nem ambiente ao processo.
4. Autorize uma pasta em **Computador** e ative Autonomia. No painel **Memória e histórico** do projeto, selecione **Isolada por execução** (recomendado) ou **Persistente no projeto**. O perfil persistente é separado do Chrome pessoal e mantém cookies/storage somente para aquele projeto e usuário.
5. Peça ao trabalhador para inspecionar uma aplicação em `localhost`, `127.0.0.1` ou `[::1]`. A Central deve solicitar aprovação no chat antes de cada ferramenta. Teste primeiro `list_pages`, `new_page` com a URL local, `take_snapshot` e `lighthouse_audit`.
6. Confirme que URLs externas, `evaluate_script`, clicks, preenchimento de formulários, uploads e execução arbitrária são recusados. Abas não locais não devem aparecer nem ser selecionáveis. Cancelar/finalizar a tarefa deve encerrar o processo MCP.

O teste acima inicia o servidor e o Chrome. Faça-o somente se estiver de acordo com a instalação do pacote pinado e com a abertura das páginas locais indicadas. Não use credenciais ou conteúdo sensível no site de teste.

## 5. Verificações automatizadas

Na raiz do repositório, execute:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_addon_resources.py -q
npm test
npm run build
```

A suíte Python contém alguns testes que dependem de sockets; se o ambiente Windows os bloquear, isso não equivale a aprovação desses casos. Os testes VSIX usam um CLI simulado e não instalam extensões no seu VS Code. O pytest deve usar o banco isolado configurado em `tests/conftest.py`, sem abrir o banco local da aplicação.
