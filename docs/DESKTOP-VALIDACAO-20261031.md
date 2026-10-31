# Desktop Windows — entrega local de 31/10/2026

## Aplicativo entregue

Central IA Desktop 0.2.0 para Windows x64, baseada no Electron 45.1.0 e backend
Python 3.15.0 congelado com PyInstaller 6.22.3. O instalador NSIS inclui a
interface React compilada, Python, dependências do servidor, ícone da Central,
metadados de versão e crédito de autoria. O usuário não precisa de Python/Node
externos para abrir a Central.

Fonte: branch `feat/desktop-finalizacao-20261031`, na cópia
`C:\Projetos\Central-IA\desktop-finalizacao-20261031`, derivada da branch desktop
`8812ee5`. A main web original permanece em `57ac02d`, com working tree limpo.
Não houve alteração ou cópia dos dados/credenciais da versão web.

Artefatos em `desktop/dist-installer`:

- `Central-IA-Setup-0.2.0.exe` — instalador Windows por usuário.
- `SHA256SUMS.txt` — integridade do instalador.
- `win-unpacked/Central IA.exe` — aplicativo empacotado usado na aceitação real.

O instalador final tem **143.436.454 bytes**. SHA-256:

```text
858f892db57f3d02d23ac90f56628d01ccb8c5bb281bb9fbec5070b689645d0f
```

## Correções concluídas

- Inicialização apenas em loopback e porta dinâmica, evitando a porta fixa da web.
- Confirmação de prontidão por HTTP, banco e assets, em vez de somente socket aberto.
- Dados e sessão Chromium persistentes exclusivos do desktop. Caminho padrão:
  `%APPDATA%\Central IA Desktop`; dados da Central na subpasta `data`.
- Override portátil `CENTRAL_DESKTOP_USER_DATA` validado e aplicado antes de
  abrir a sessão ou obter o lock de instância única.
- Encerramento cooperativo por canal autenticado, com fallback para a árvore
  do backend pertencente ao aplicativo. Tentativas simultâneas compartilham
  a mesma operação de limpeza.
- Renderer sem Node, com sandbox/context isolation e permissões negadas.
- Prévia permitida somente quando o backend confirma a autorização atual.
  Cookies e credenciais da Central não são enviados ao projeto; respostas de
  prévia não podem sobrescrever cookies da aplicação.
- OAuth externo limitado ao destino e callback conhecidos, mediante confirmação
  nativa. Não foi realizado login OAuth real durante este ensaio.
- Comandos de projetos Python deixam de usar o próprio executável congelado
  como interpretador. Preferem a `.venv` autorizada ou Python externo; se faltar,
  retornam uma explicação sem abrir outra instância do backend. A web e o modo
  Docker mantêm seus caminhos de execução existentes.
- Dependências de build com lockfiles, verificações do backend e da interface
  empacotados no script de build, checksum e dados preservados na desinstalação.

## Verificações reais

1. Backend congelado executado fora do ambiente de desenvolvimento, com diretório
   de dados temporário. Respondeu prontidão, HTML, JavaScript e CSS. Endpoints de
   projetos sem login retornaram 401. Encerramento cooperativo aprovado.
2. Repetição do teste com Python e Node externos removidos do PATH do subprocesso:
   prontidão, assets e autenticação continuaram funcionando.
3. Electron em desenvolvimento e **Electron empacotado real** exercitados com
   Playwright, cada um com dados exclusivos temporários:
   - criação de conta pela interface;
   - criação de projeto pela API autenticada da janela;
   - inspeção das preferências reais do renderer;
   - prévia autorizada carregada no painel e botão clicado;
   - requisição da prévia confirmando ausência de cookie/autorização;
   - encerramento da prévia e do backend, com portas fechadas;
   - reabertura preservando login e projeto.
4. Regressão completa: **1.169 testes Python aprovados, 31 ignorados**, dois
   avisos existentes. Frontend: **44 aprovados** e build Vite concluído.
   Desktop Node: **32 aprovados**. `git diff --check` aprovado.

Evidências reproduzíveis: `desktop/test-results/packaged.json`,
`development.json`, capturas correspondentes e
[captura da janela empacotada](desktop-windows-20261031.png).
Os testes usam contas fictícias e não enviam tarefas a modelos pagos.

## Reproduzir

```powershell
.\desktop\build_windows.ps1
```

Com as dependências e o frontend já preparados:

```powershell
.\desktop\build_windows.ps1 -SkipInstall -SkipFrontend
```

Aceitação do payload já construído:

```powershell
node .\desktop\smoke_ui.cjs '.\desktop\dist-installer\win-unpacked\Central IA.exe'
```

O script cria dados temporários próprios e não reutiliza contas da web. A
aceitação de UI exige os componentes opcionais Node/npm usados pela fixture
de prévia; o teste isolado do backend comprova o núcleo sem eles no PATH.

## Limites da entrega

Este é um pacote **local, sem assinatura digital**, validado neste Windows real.
Não foi realizado ensaio de instalação/desinstalação NSIS em VM Windows limpa.
O teste real executa o payload `win-unpacked` que também entra no instalador.
Não há atualização automática assinada nem distribuição pública nesta entrega.

Ferramentas e modelos externos continuam opcionais e sujeitos à configuração:
Codex, Ollama, Node para projetos JS, Python para projetos Python, Docker, MCP e
ferramentas de vídeo não são instalados silenciosamente. Presença no diagnóstico
não comprova versão, autenticação ou capacidade de inferência.

Documentação técnica conferida:
[segurança Electron](https://www.electronjs.org/docs/latest/tutorial/security),
[NSIS/electron-builder](https://www.electron.build/nsis/),
[PyInstaller](https://pyinstaller.org/en/stable/requirements.html).

As alterações e artefatos foram deixados locais, sem commit ou push novo.
