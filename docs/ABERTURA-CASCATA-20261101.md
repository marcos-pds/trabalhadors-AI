# Abertura Cascata de Vidro - 01/11/2026

Origem: central-ia-cascata-7s.zip fornecido pelo usuario. Foram incorporados apenas os arquivos src necessarios (motor, componente TSX, CSS, tipos e WAV), sem executar scripts ou copiar a pagina de demonstracao como aplicacao.

A abertura e montada uma vez por carregamento da pagina/janela, antes do login ou do chat ja autenticado, e nao reinicia ao navegar ou fazer login. Recarregar a pagina ou reabrir o desktop reproduz novamente. Duracao programada: 7000ms, incluindo saida. Botao Pular abertura e Escape liberam a interface antes desse prazo.

O tema inicial acompanha a preferencia da Central. Durante a abertura, root fica inerte e os atalhos do chat ignoram teclas; foco e interatividade sao restaurados ao sair. O desktop reserva os 32px da barra nativa branca. Audio original incluido localmente, volume 0.55; autoplay bloqueado oferece Ativar som, sem alterar politicas do navegador ou atrasar o termino. Audio, timers e observadores sao limpos ao sair/desmontar.

Validacao:

- 72 testes frontend aprovados: inclui os 9 testes fornecidos, com caminhos adaptados, para fronteira 6999/7000ms, pular, limpeza, autoplay bloqueado, movimento reduzido e duracao fisica do WAV.
- Build Vite inclui WAV separado, sem CDN ou dependencias novas.
- Chromium real/browser-act em base isolada: abertura, seis cartas, contagem e botoes; termino com zero overlays e root.inert=false; clique de som mudou o controle para Silenciar. Captura local intro-web.png.
- Electron empacotado: 22 verificacoes passaram, incluindo abertura unica, termino automatico, Pular, Escape, liberacao do root e exibicao apos reinicio. Os testes anteriores de caption, menu, catalogo, persistencia e preview continuam passando.

Os testes logicos usam DOM simulado e nao substituem as verificacoes reais acima. Nao houve chamada de IA ou uso de credenciais de producao. O servidor e a sessao de teste foram encerrados. Nao se afirma homologacao em todos os navegadores ou revisao auditiva humana da composicao.
