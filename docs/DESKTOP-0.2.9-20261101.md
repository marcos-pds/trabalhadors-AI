# Desktop 0.2.9 - barra de titulo branca

Janela Windows usa titleBarStyle hidden e titleBarOverlay branco, simbolos slate e 32px de altura. Accent color desativado somente nesta janela. Botões minimizar/maximizar/fechar continuam nativos; frame de redimensionamento preservado. Nao altera configuracoes de aparencia do Windows.

A superficie de arraste e o titulo sao renderizados quando navigator.windowControlsOverlay.visible esta ativo. O conteudo reserva 32px, incluindo menu e dialogos. Na web comum, sem overlay, a moldura nao aparece. Nao usa preload, Node no renderer ou novos canais IPC.

Validacao: 63 testes frontend/build; 15 testes bootstrap e 41 Node. Electron empacotado: 18 verificacoes aprovadas, incluindo fundo branco, regiao drag, geometria WCO e controles nativos habilitados; maximizar/restaurar foram executados realmente. Arraste por mouse fisico nao foi automatizado. Continua com testes de menu, catalogo, preview, persistencia e encerramento.

Arquivo: Central-IA-Setup-0.2.9.exe
Tamanho: 143483080 bytes
SHA256: a59e766618c40805d0f2b56acf4aa228ca33fdc561e337f3eb153e9f907d126c
Copia: Downloads/Central-IA-Desktop-0.2.9
Capturas: Interface-desktop.png e Barra-de-titulo.png. A captura DOM da barra nao representa os botoes nativos sobrepostos do sistema.

Pacote local sem assinatura digital, nao homologado em VM limpa. Nenhuma inferencia de IA foi feita nos testes visuais.
Referencia oficial: https://www.electronjs.org/docs/latest/tutorial/custom-title-bar
