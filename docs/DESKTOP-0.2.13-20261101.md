# Desktop 0.2.13

Corrige os links Obter chave dos serviços do catálogo. O handler nativo bloqueava todos os links com target=_blank, inclusive os links oficiais. Agora as páginas HTTPS dos fornecedores reconhecidos são encaminhadas ao navegador padrão do Windows e a janela Electron continua bloqueada. A navegação OAuth existente permanece separada.

Os links usam noreferrer, portanto o handler aceita referrer vazio para os destinos oficiais. Quando informado, o referrer deve pertencer à Central. Protocolos locais, credenciais embutidas, portas alternativas e domínios não reconhecidos são recusados. Uma falha ao abrir o navegador apresenta uma mensagem ao usuário.

Validação: testes unitários verificam o handler e os destinos recusados; uma verificação cobre todas as páginas de chaves e condições presentes no catálogo do backend. A aceitação Electron clica no link real de Groq e observa o encaminhamento para shell.openExternal, substituindo apenas a abertura do navegador pelo sistema operacional. Nenhuma chave, conta ou chamada de inferência é necessária para o teste.

O frontend web já utiliza links normais para as páginas oficiais; esta correção é específica do shell desktop.

Resultado: 44 testes unitarios e 27 verificacoes Electron aprovados. SHA256: 568EFFB5E43731010C60CACF87130BE72BD2499741BB0BDC6CEEACCAAAEDED30
