## All Black Premium — Central Desktop 0.3.8

A revisão foi feita **sobre o frontend existente**, sem reconstruir telas ou modificar rotas, integrações, APIs, histórico, modelos, backup ou lógica dos agentes.

### Escopo e breakpoint

- Aplicação: **somente Electron/Windows**, identificada exclusivamente pelo preload `centralDesktop.isDesktop`.
- Exibição: somente quando o **monitor tem largura de 1024 px ou mais**. A barra compacta do Electron mede menos de 1024 px mesmo em monitores desktop; por isso o breakpoint é calculado com `window.screen.width`, não `window.innerWidth`.
- O React aplica/removerá a classe `central-desktop-all-black` ao detectar mudanças de janela/orientação. Em telas menores, a folha de estilos não tem efeito e o tema anterior fica intacto.
- **Web, PWA, mobile e tablet não são alterados**. Nenhum seletor do novo tema é global, e o CSS é carregado apenas pelo Electron. As preferências `localStorage` da web são preservadas.

### Tokens de design

| Função | Token | Valor |
| --- | --- | --- |
| Fundo principal | `--desktop-black-bg` | `#000000` |
| Sidebar | `--desktop-black-sidebar` | `#050505` |
| Cards e painéis | `--desktop-black-panel` | `#0D0D0D` |
| Superfícies elevadas | `--desktop-black-raised` | `#141414` |
| Inputs | `--desktop-black-input` | `#101010` |
| Bordas | `--desktop-black-border` | `#242424` |
| Texto principal | `--desktop-black-copy` | `#F5F5F5` |
| Texto secundário | `--desktop-black-secondary` | `#A3A3A3` |
| Desabilitado | `--desktop-black-disabled` | `#666666` |
| Destaque | `--desktop-black-accent` | `#D7B4FA` (cor lilás original da Central) |

O novo `frontend/src/desktop-noir.css` **substitui integralmente** a antiga camada de overrides, evitando adicionar regras duplicadas. Mantemos `!important` apenas nos pontos em que as folhas existentes já impunham estilos com essa prioridade. A animação Slime rosa **não é estilizada** pela nova camada.

### Cobertura

Dock, navegação, dashboard, chat compacto e conversa, sidebar/histórico, formulários, modos Auto/Equipe/Individual, cartões, provedores, configurações, projetos, fluxos, tabelas e relatórios, prévia lateral sob demanda, menus, tooltips, notificações, login e animação de abertura.

- Tipografia de alto contraste, diferenciação por cinzas escuros, bordas discretas, ícones alinhados, scrollbars escuras e destaque lilás apenas em controles ativos.
- Hover e transições de **180 ms**, foco de teclado visível e fallback para movimento reduzido / alto contraste.
- Preservados a prévia sob demanda, o chat em três estados e o atualizador por GitHub Releases com consentimento do usuário.

### Validação

- `node --test frontend/src/desktopAllBlack.test.mjs` (1023/1024 px, dock compacto, web/PWA, paleta exata, cobertura, avatar e acessibilidade).
- `npm run build` e CI de frontend no Windows e Linux.
- `desktop/build_windows.ps1` para a versão **0.3.8**.
- Checklist de homologação visual no Windows: monitor de 800, 1024, 1366 e 1920 px; janela compacta e expandida; login, menus, dashboard, chat, prévia e configurações; escala de DPI 100%, 125% e 150%; teclado e movimento reduzido.

**Os testes estáticos não substituem a confirmação visual em um monitor real.** Não mesclar na `main` nem distribuir a versão 0.3.8 por GitHub Releases enquanto a revisão não estiver concluída.

---

## Tema Noir #000 — Central Desktop 0.3.7

Esta versão de teste aplica a identidade visual **preto verdadeiro** ao aplicativo **Electron/Windows somente**. A versão web/PWA não importa este tema e continua com a aparência anterior.

- **Base:** `#000000` na área de trabalho, chat, histórico e demais telas principais; superfícies auxiliares em `#090909` e `#101010` para distinguir cartões, campos e controles sem recorrer a azul ou roxo.
- **Liquid Glass contido:** refração `rdev/liquid-glass-react` permanece no dock/campo, com opacidade reduzida. Sem molduras brilhantes nem sombras externas. Fora da barra compacta, a janela continua transparente para não criar um retângulo preto na área de trabalho.
- **Telas abrangidas:** dock, chat compacto e expandido, prévia opcional, dashboard, trabalhadores, projetos, workflows, históricos, provedores, monitoramento, uso de tokens, integrações, GitHub, configurações, menus, modais, notificações, login e animação de abertura.
- **Texto e acessibilidade:** branco/cinza legível, hover grafite, foco de teclado visível; cores de alerta, sucesso e erro permanecem para sinalizar estados.
- **Slime:** avatar 3D rosa original preservado sem filtros de vidro/preto.
- **Funcionalidade:** clique do avatar abre somente o compositor; após enviar uma mensagem válida aparece a conversa; prévia abre sob demanda; modos de execução, atualizador, banco e integrações não mudam.

O arquivo `frontend/src/desktop-noir.css` concentra as variáveis e os estilos. Ele é carregado **somente** se o preload Electron expuser `centralDesktop.isDesktop`: no dock depois do Liquid Glass existente e, na tela de login, por importação dinâmica protegida. Não há importação estática pelo frontend web.

### Validação

- `node --test frontend/src/desktopNoir.test.mjs` — preta real, páginas cobertas, web isolada, slime original e bordas discretas.
- `npm run build` — frontend React.
- `desktop/build_windows.ps1` — Setup EXE Windows 0.3.7 e testes do backend instalado.
- **Inspeção visual ainda necessária:** tela preta em 100%/125%/150% de escala, legibilidade dos campos, uso de CPU/GPU dos filtros e login. Não mesclar na main nem publicar GitHub Release sem confirmar essas verificações.

---

## Limpeza visual do chat — Desktop 0.3.6

Correção baseada na captura do usuário mostrando moldura de contorno em vermelho, seletor `Auto` com caixa em volta e sombra escura ao redor da janela:

- **Janela sem moldura visual**: remove bordas CSS, halos, sombras externas e linhas decorativas da janela principal, dock superior e barra de prompt. A janela Electron já utiliza `hasShadow: false`, `transparent: true` e fundo transparente.
- **Vidro sem contorno pesado**: mantém cores, reflexos, desfoque e a refração `rdev/liquid-glass-react`, porém com sombra e contorno ausentes nas superfícies externas.
- **`Auto` oculto**: o modo automático continua selecionado e funcional, mas nenhum texto `Auto` ou seletor com borda aparece por padrão. Um **ícone pequeno de ajustes** permite escolher Auto, Equipe ou Individual, sem bloquear digitação. Se selecionar Equipe ou Individual, o nome do modo aparece discretamente ao lado do ícone.
- **Menu acessível**: tecla Escape e clique fora fecham as opções; a abertura do menu não abre o chat inteiro. Na conversa expandida, as opções aparecem acima do campo de texto, sem sair da janela.
- **Web/PWA sem alterações**: o CSS está restrito ao `html.central-desktop-shell .central-desktop-mode`; o componente compacto é usado somente no Electron.

Arquivos: `frontend/src/DesktopChatPrompt.jsx`, `frontend/src/desktop-liquid-glass.css`, `frontend/src/desktopMinimalFrame.test.mjs`.
Validação automática: `node --test frontend/src/desktopMinimalFrame.test.mjs` e `npm run build`, com empacotamento Windows `desktop/build_windows.ps1`.
Ainda é necessária uma verificação visual na máquina Windows, principalmente em escalas de 100%, 125% e 150%.

---

## Correção visual do chat e prévia — Desktop 0.3.5

Correções motivadas por duas capturas da Central no Windows:

- **Barra de digitação pouco visível:** um único efeito `rdev/liquid-glass-react`, com superfície grafite escura de contraste definido e borda brilhante discreta. O `textarea` não desenha um segundo retângulo: não há fundo, borda ou sombra interna.
- **Chat antigo depois do envio:** o desktop agora renderiza `DesktopConversation.jsx`, componente nativo com cabeçalho compacto, mensagens legíveis, atividades e aprovações, usando o mesmo prompt e a mesma API da Central. O `ChatPage` web continua original e é renderizado exclusivamente no navegador.
- **Prévia cobrindo/quebrando a tela:** encerramos a abertura automática ao iniciar tarefa, retomá-la ou selecionar histórico. O botão **Prévia** é uma ação explícita. O painel aparece como um drawer à direita, com largura limitada (até 530 px), sem bloqueio de interação com o chat e com botão fechar; a conversa não é espremida e o iframe fica restrito ao drawer. O atalho `/previa` também conta como abertura solicitada.
- **Envio de arquivo:** o chat compacto usa o mesmo helper de API autenticada do chat web, evitando requisições sem CSRF.
- **Preservação:** Slime rosa, transição avatar → campo → conversa, tema dos outros recursos e versão web/PWA não foram alterados.

Referências consideradas: [shadcn AI Elements Prompt Input](https://ui.shadcn.com/docs/ai-elements/aria/prompt-input) para o layout do campo compacto, [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog) para contenção de painéis e [rdev/liquid-glass-react](https://github.com/rdev/liquid-glass-react) para a refração real.

### Validação

- `node --test frontend/src/desktopChatLayout.test.mjs frontend/src/desktopChatGlass.test.mjs`
- `npm ci && npm run build`
- `desktop/build_windows.ps1`, com smoke test de backend + validação do manifesto do atualizador
- Inspecionar visualmente no Windows: transparência do campo, mensagens no novo painel, alternar prévia sem alterar dimensões do chat, fechamento com Escape e exibição de anexos.

**Estado:** branch de revisão, ainda não publicada como Release e não distribuída via autoatualização. Homologar as duas capturas em uma máquina Windows antes do merge.

---

## Novo chat compacto — Desktop 0.3.4

**Este ajuste não altera a experiência web.** A reformulação do chat desktop está isolada no Electron:

1. Ao iniciar, fica apenas o dock Liquid Glass fixo no topo, com o Slime rosa original.
2. Clicar no Slime mostra **somente a barra de digitação** diretamente abaixo do dock. Não aparece o histórico, o painel de execução nem a antiga órbita branca com satélites. O Electron muda para um retângulo transparente compacto, sem uma janela grande invisível por trás.
3. A barra segue a referência enviada pelo usuário: campo horizontal arredondado, anexo (+), entrada de texto, modo Auto/Equipe/Individual, ditado quando suportado pelo Electron e botão de enviar. O componente usa a refração real do pacote `rdev/liquid-glass-react` e o reflexo do tema existente. Anexos e seleção de trabalhador são compartilhados com a conversa completa.
4. **Somente quando o backend aceitar o envio da mensagem**, a Central expande a janela e mostra o histórico e o painel de execução. Uma falha no envio mantém a barra aberta para tentar novamente.
5. Um segundo clique no Slime (ou Escape no campo) recolhe tudo ao dock. Os ícones de outras funcionalidades no topo continuam abrindo suas próprias telas, independentemente do chat.
6. O núcleo branco e as órbitas marcados em vermelho nos exemplos foram removidos **somente do chat desktop**. Na versão web, o componente `ChatWelcome` permanece inalterado.

Arquivos relevantes: `frontend/src/DesktopChatPrompt.jsx`, `frontend/src/desktopChatLayout.mjs`, `frontend/src/App.jsx`, `frontend/src/desktop-liquid-glass.css`, `desktop/main.cjs` e `desktop/preload.cjs`.

### Verificações

- `node --test frontend/src/desktopChatLayout.test.mjs` testa os estados dock/compose/full e a regra de envio; inclui testes de isolamento da web e de ausência de órbita na interface nativa.
- `npm run build` e `desktop/build_windows.ps1` validam o frontend e o instalador NSIS.
- **Ainda é obrigatório** verificar visualmente no Windows 10/11 as transições, o dimensionamento e o microfone opcional antes de liberar uma versão estável.

---

## Atualização automática pelo GitHub — Desktop 0.3.3

A Central Desktop instalada agora poderá verificar novas versões estáveis no GitHub Releases. **O download e a instalação exigem confirmação separada.** Antes de instalar, a Central bloqueia novas gravações, verifica tarefas ativas e cria um backup local verificado. A interface web/PWA não recebe essa funcionalidade.

Veja [UPDATES.md](UPDATES.md) para a política de segurança, publicação de versões assinadas, requisitos de GitHub Releases, testes e restauração de backups.

---

## Liquid Glass completo — versão desktop 0.3.2

O modo Windows/Electron usa o projeto [rdev/liquid-glass-react](https://github.com/rdev/liquid-glass-react) (MIT) para **refração SVG real nas bordas** da área de trabalho e usa o sistema de vidro do projeto para aplicar a mesma estética em toda a Central: chat, menus, provedores, trabalhadores, fluxos, projetos, histórico, relatórios, tokens, Git, configurações, modais, formulários, tabelas e notificações.

- **Somente desktop:** o CSS é importado pelo `DesktopDock.jsx`, que só é carregado na janela Electron. Todos os seletores visuais exigem `html.central-desktop-shell`; a web e o PWA não recebem essa classe nem essa renderização.
- **Slime rosa preservado:** o avatar 3D original não recebe vidro nem filtros, continua pequeno e animado e controla sozinho a abertura/fechamento do chat.
- **Performance:** a refração real só é montada na área de trabalho quando aberta; cartões menores usam bordas, reflexos, saturação e desfoque CSS, em vez de um filtro SVG para cada elemento.
- **Acessibilidade:** campos e textos conservam contraste adequado, menus permitem navegação por teclado, preferências de movimento reduzido e modo de alto contraste continuam respeitados.
- **Login:** o assistente de login/registro do executável também usa a identidade visual escura de vidro. O navegador mantém seu tema atual.

Verificações em `npm test` conferem que o tema só pode ser ligado pelo preload desktop, que a dependência de refração é carregada de forma lazy e que o Slime original está isento. Os testes não substituem a inspeção gráfica do Electron em um PC Windows.

---

## Correções do avatar e da barra — Desktop 0.3.1

Esta atualização **não altera a versão web**. A barra branca exibida atrás do dock foi tratada em duas etapas: o preload Electron agora cria a superfície transparente antes do React ser exibido, e o CSS desktop impede que a cor clara herdada da web apareça no fundo ou no cabeçalho.

O Slime do desktop deixou de utilizar a aproximação preta. Seu desenho 3D é uma adaptação direta do arquivo de referência fornecido pelo usuário, `avatares_3d_interativos 3.html`, incluindo:

- **Pink Slime original:** cúpula `#ffa6c1`, corpo `#f2577b`, base `#be1e45` e olhos texturizados
- **96×96 segmentos:** mesma malha de gelatina de alta densidade e física de squash/stretch
- **Superamostragem:** render interno de pelo menos 192×192 px mesmo no avatar compacto de aproximadamente 52 px
- **Reações reais:** respiração, piscadas, bocejos, olhos acompanhando ponteiro, clique com pulo feliz, arrasto elástico e expressão surpresa
- **Estados da Central:** digitação e execução fazem o Slime prestar atenção; sucesso após uma execução provoca uma reação alegre; falhas exibem expressão de surpresa
- **Chat:** abre/fecha apenas no clique no Slime, sem abrir quando o avatar é arrastado

O avatar continua sem fundo próprio ou vidro e não requer novos arquivos de textura externos. A interface Liquid Glass escura aplica-se exclusivamente ao dock e aos painéis.

### Verificar no Windows

1. Instale o `Central-Setup-0.3.1-x64.exe` da build associada a esta branch.
2. Com o chat recolhido, confirme que não há barra branca por trás do dock.
3. Observe o Slime piscando, respirando e bocejando. Mova o mouse sobre ele para verificar os olhos.
4. Clique no Slime: ele deve pular e abrir a conversa. Clique novamente para recolher.
5. Arraste o Slime: ele deve balançar como gelatina **sem abrir o chat**.
6. Abra a Central no navegador comum e verifique que o layout web continua igual.

Verificações automáticas: `npm test` inclui teste de cores, malha e reações, e `npm run build` compila o frontend. A inspeção visual do Windows continua obrigatória antes de liberar um release estável.

---

## Componentes opcionais durante a instalação (Setup 0.3.0)

O instalador apresenta, **antes de copiar os arquivos**, uma tela limpa para escolher VoiceStudio + OmniVoice, Ollama, Qwen 2.5 Coder 3B, Llama 3.2 3B e Docker Desktop. Nenhuma opção vem marcada por padrão.

- **VoiceStudio:** identifica instalação existente e, se necessário, baixa o instalador Windows do release oficial `debpalash/VoiceStudio`, validando `SHA256SUMS.txt`. O catálogo de modelos exige aceite das licenças OmniVoice e Higgs tokenizer. O instalador **não aceita licenças silenciosamente**: se ainda não estiverem aprovadas ou o runtime não tiver sido configurado, a conclusão do modelo ficará pendente no VoiceStudio. Em uma instalação existente com OmniVoice funcional, os arquivos são reutilizados.
- **Ollama:** instala pelo distribuidor oficial, se ainda não houver Ollama. Se você marcar apenas um modelo, o instalador também providencia Ollama. As opções de modelos são `qwen2.5-coder:3b` e `llama3.2:3b`, instaladas por `ollama pull`; modelos já registrados não são baixados novamente.
- **Docker:** utiliza o instalador oficial Windows no modo `--user`. A configuração de WSL2, termos de uso e eventual reinicialização continuam sob controle do Windows/Docker. Não tenta habilitar automaticamente recursos privilegiados do sistema.

As fontes de downloads são HTTPS de `github.com`, `ollama.com` e `desktop.docker.com`. O progresso de transferência usa **bytes efetivamente recebidos**; a instalação de modelos de terceiros pode exibir apenas andamento por etapa quando o comando não publica porcentagem. O registro fica em `%LOCALAPPDATA%\Central\setup-components.log`.

**Importante:** componentes opcionais não devem bloquear a instalação do aplicativo principal. Se algum deles falhar, a Central continuará funcionando e o instalador exibirá uma pendência. Para um teste controlado, compile no Windows com `desktop/build_windows.ps1` e confira a tela do Setup e a primeira abertura do programa. O instalador 0.3.0 ainda exige avaliação manual de instalações limpas e do fluxo de licenças para confirmar cada componente.

---

## Instalador EXE (versão recomendada)

O instalador Windows é gerado pela pipeline [Build Central Windows installer](../.github/workflows/build-desktop-installer.yml). A aparência é propositalmente **clean**: fundo claro, marca neutra, tipografia simples e **progresso nativo real do Windows**, sem animações que simulem downloads ou mensagens de "IA instalando".

O arquivo de distribuição chama-se `Central-Setup-0.2.0-x64.exe`. Depois de um build bem-sucedido, baixe o artefato **Central-Setup-Windows-x64** em GitHub Actions. Descompacte o ZIP e execute o Setup.

- Instalação assistida em português, com escolha de pasta e atalhos.
- A instalação inclui o frontend React, Electron e o backend FastAPI executável empacotado por PyInstaller.
- Ao abrir o atalho, o aplicativo inicia seu **próprio servidor local** na interface 127.0.0.1 em porta livre e abre a barra Liquid Glass. Não é necessário instalar Python/Node, executar CMD ou abrir o browser.
- Conversas, credenciais e demais dados ficam no diretório de usuário do aplicativo (Electron `userData/data`) e não em `Program Files`, de modo que atualizações não apaguem automaticamente os dados.
- O aplicativo encerra seu servidor local ao fechar.
- **A versão web permanece intacta**, inclusive quando o serviço local também é aberto pelo navegador. O modo desktop é ativado somente pelo preload seguro da janela instalada.

### Produzir um instalador localmente

Em um Windows 10 ou 11 com Python 3.11, Node 22 e Git:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop\build_windows.ps1
```

O Setup será criado em `desktop\release\`. O pipeline GitHub Actions executa ainda um teste que inicia o backend empacotado, acessa `http://127.0.0.1:18887/` e verifica se a página React retorna corretamente.

**Limitações:** este é um instalador de teste **não assinado digitalmente**, então o Windows SmartScreen pode apresentar um aviso. Ele não instala automaticamente os modelos grandes do VoiceStudio/OmniVoice ou outras ferramentas externas opcionais. Para distribuir amplamente, precisamos testar a instalação num Windows limpo e providenciar assinatura de código antes de publicar um release estável.

---

# Central IA Desktop — Liquid Glass + Slime preto

Esta é uma **interface Windows opcional** e separada do navegador. A versão web mantém suas telas, cabeçalho, barra lateral e chat atuais sem alteração visual. O invólucro Electron usa o mesmo backend FastAPI e a mesma aplicação React, mas fornece um canal desktop autenticado pelo preload, ativando um layout específico **somente na janela Electron**.

## Recursos

- Slime 3D de material preto/grafite, sobre **fundo transparente**, sem cartão ou moldura.
- Barra de notificações Liquid Glass fixa na parte superior, com menus da Central em ícones pequenos e com nomes acessíveis ao passar o mouse.
- Chat recolhido na inicialização; **só o clique no avatar** abre/fecha a conversa. Ícones abrem suas próprias seções, como Projetos, Provedores e Configurações.
- Ao expandir, uma janela transparente do Electron cresce e exibe o chat completo e as ferramentas reais da Central. Ao recolher, volta a ocupar apenas a região da barra, com transição suave do painel.
- O vidro usa os componentes já existentes do projeto (liquid-glass-web-react) e CSS; não é aplicado à malha do avatar.
- Web em Chrome/Edge em uma aba normal: interface **inalterada**.

## Primeira instalação — Windows 10 ou 11

1. Configure a Central normalmente usando o [guia de instalação](../GUIA-INSTALACAO-WINDOWS.md), incluindo `npm ci`, `npm run build` e instalação do Python.
2. A partir da pasta raiz, compile a nova interface: `npm ci && npm run build`.
3. Execute `desktop\iniciar_desktop.bat`. O script inicia o backend em `127.0.0.1:8765` se necessário, instala o Electron no diretório `desktop` quando ainda não existir e abre a barra compacta.
4. Se for o primeiro login, a janela se amplia para permitir autenticação; depois volta à barra pequena.
5. **Clique no Slime preto** para abrir o chat. Clique novamente para fechar, ou use o botão de recolher. Use Alt+F4 para fechar o aplicativo quando estiver em foco.

Alternativa se o servidor já estiver funcionando em outra porta:

```bat
cd desktop
npm install --no-audit --no-fund
set "CENTRAL_DESKTOP_URL=http://127.0.0.1:8876/"
npm start
```

Se estiver usando uma cópia de testes diferente da raiz, compile essa cópia antes de abrir Electron.

## Segurança e isolamento

A janela desktop usa `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, `webSecurity: true` e URL local restrita a `http://localhost`/`http://127.0.0.1`. O preload expõe apenas `{isDesktop, setExpanded(boolean)}`, sem acesso direto a Node, disco ou credenciais. O processo principal só aceita IPC do frame principal da janela, na origem local aprovada.

A barra é **sempre no topo** da área de trabalho Windows; não modifica a barra do Windows nem instala serviços do sistema. Janelas de alguns aplicativos em tela cheia exclusiva podem ficar acima dela. Para manter o conteúdo da tela subjacente visível, a janela usa transparência do Electron, não o CSS de uma aba do navegador.

**Observação:** o Windows pode solicitar permissões ao instalar Electron, e programas de captura ou proteção podem afetar a transparência. A instalação não gera instalador .exe assinado nesta fase; `npm start` executa o aplicativo local. Não publique o backend em interfaces de rede externas.

## Testes

- `npm ci && npm run build` na raiz.
- `npm test` (testes do projeto).
- `node --check desktop/main.cjs && node --check desktop/preload.cjs`.
- Teste manual no Windows: abrir dock, clicar no avatar, trocar para Projetos e voltar ao chat, minimizar, verificar que o browser em `http://127.0.0.1:8765` mantém a UI antiga, testar Alt+F4 e modo de alta DPI.

O CI do GitHub valida a compilação React e sintaxe do processo Electron. A verificação visual de transparência, posição de janela, redimensionamento e GPU/WebGL precisa acontecer em Windows com interface gráfica.
