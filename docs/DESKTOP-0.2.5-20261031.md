# Desktop 0.2.5 - catalogo automatico de modelos

Ao colar uma chave ou selecionar uma conexao salva, o painel consulta os modelos e oferece selecao em lista. Ha atualizacao explicita e entrada manual alternativa. Trocas de credencial/runtime descartam respostas antigas. OpenCode inclui seletor do provedor da chave e prefixos corretos.

Validacao: 53 testes backend de catalogo/API, 53 testes frontend, 15 testes bootstrap e 41 testes Node aprovados. Teste real do catalogo Gemini retornou 34 modelos de geracao sem inferencia. A chave permaneceu em memoria, sem alteracao da base de origem.

Electron empacotado passou em 11 verificacoes reais. A listagem no smoke de UI usa catalogo simulado determinista, sem enviar a chave ficticia ao provedor. A consulta real de catalogo foi feita separadamente. A conexao sem inferencia verifica a versao real do CLI pelo backend congelado.

Instalador local, sem assinatura digital; nao homologado em VM limpa.
Arquivo: Central-IA-Setup-0.2.5.exe
Tamanho: 143469786 bytes
SHA256: 317f14e1ebc695589237c9df3c92219a6579c65e476681a96a7c5c4a3b5180a8
Copia: Downloads/Central-IA-Desktop-0.2.5
