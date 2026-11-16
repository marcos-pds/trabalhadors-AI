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
