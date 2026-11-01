# Desktop 0.2.12

Corrige a rolagem do chat: atualizações de mensagens e etapas só acompanham o final quando o usuário está próximo dele. Ao subir para ler o histórico, a posição é preservada. Trocar de conversa inicia novamente o acompanhamento.

O menu Ferramentas e permissões fecha ao clicar fora ou pressionar Escape. Clicar dentro preserva os controles; Escape retorna o foco ao botão de abertura. Os listeners são removidos ao desmontar o chat.

A mesma correção está na versão web. A aceitação Electron usa histórico e atualizações controlados, sem chamadas a modelos, para conferir a preservação da posição e a retomada do acompanhamento no final, além dos cliques internos/externos e Escape.

Distribuição local: `C:\Users\marco\Downloads\Central-IA-Desktop-0.2.12`. O instalador não é executado automaticamente.

SHA256 de `Central-IA-Setup-0.2.12.exe`: `5A1447AAF8195380A39135D5FD54AD74A29A6DC557D85045A84C06D5115F8AFB`.
