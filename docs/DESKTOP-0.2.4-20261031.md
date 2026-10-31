# Desktop 0.2.4 - runtimes externos

Pacote local Windows x64, sem assinatura digital. Nao homologado em VM limpa.

- Implementacao da etapa 5 compartilhada com web: [runtimes e limites](RUNTIMES-EXECUCAO-20261031.md).
- React compilado, 15 testes do bootstrap e 41 testes Node aprovados.
- Backend PyInstaller iniciado e validado por HTTP.
- Electron empacotado: 10 verificacoes reais aprovadas, incluindo inventario dos quatro perfis, conexao Gemini com verificacao real de versao e SEM inferencia (chave ficticia de teste), preview interativo sem credenciais, encerramento e persistencia apos reinicio.
- Capturas locais em desktop/test-results; perfil descartavel, sem usar dados reais.
- A falha inicial do novo smoke foi um seletor ambiguo entre runtime e modelo; corrigido para correspondencia exata e ensaio repetido com sucesso.
- Nao houve chamada Codex como trabalhador. Claude ainda aguarda credencial Anthropic para inferencia.

Instalador: Central-IA-Setup-0.2.4.exe
Tamanho: 143467843 bytes
SHA256: 8f945fdddcbc8423f9d2af62f52e432938c958415f1121b9afa68d1dd7d7fbbb
Copia local: Downloads/Central-IA-Desktop-0.2.4

As ferramentas CLI opcionais sao instaladas separadamente pelo script runtime-tools/install_windows.ps1. O aplicativo principal abre sem elas. O processo CLI nao e sandbox de sistema operacional.
