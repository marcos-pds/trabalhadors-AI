# Assinatura Windows

Estado em 31/10/2026: infraestrutura preparada para certificado Authenticode
no repositorio CurrentUser/My. Nenhum certificado do editor foi encontrado;
nenhum instalador assinado foi produzido. Azure Artifact Signing ainda exige
conta, validacao de identidade e adaptador de assinatura especifico.

## Auditoria do pacote atual

Foram encontrados 46 arquivos com cabecalho MZ no instalador e na arvore
win-unpacked: 28 com assinatura valida e timestamp e 18 sem assinatura.
Os pendentes incluem instalador, Central IA.exe, backend, elevate.exe,
bibliotecas Electron e extensoes nativas Python (.pyd).
Relatorio completo local: desktop/test-results/signatures-unsigned.json.
Esta auditoria verifica Authenticode; nao substitui analise de malware nem
teste de instalacao em Windows limpo com Smart App Control ativo.

## Preparacao do editor

Obter certificado de assinatura de codigo publicamente confiavel de uma CA,
com identidade do editor validada. O fornecedor deve orientar o uso da chave
em token/HSM. Certificado TLS de site nao serve. Nao criar raiz autoassinada
nem adicionar excecoes locais para simular confianca publica.
Instalar SignTool do Windows SDK e disponibiliza-lo no PATH. Este adaptador
usa certificado acessivel em Cert:\CurrentUser\My; nao recebe senha nem PFX.
O thumbprint e identificador publico, nao chave privada.

```powershell
$env:CENTRAL_SIGN_CERT_SHA1 = 'THUMBPRINT_DE_40_CARACTERES_DO_CERTIFICADO'
.\desktop\build_windows.ps1 -Signed
```

O build assinado escreve somente em desktop/dist-signed. O hook afterPack
assina binarios internos que ainda nao possuem assinatura valida com timestamp.
O electron-builder assina executaveis apos editar recursos, incluindo o
instalador e o desinstalador NSIS gerado. O callback exige o certificado
configurado para esses arquivos. SignTool usa SHA256 e timestamp RFC3161.
Uma validacao final exige assinatura valida e timestamp para todos os arquivos
nativos encontrados na saida e grava signatures.json. Falhas interrompem
o processo; nunca ha fallback automatico para build sem assinatura.
Certificados de terceiros validos com timestamp sao preservados pelo hook.
A confianca da cadeia e checada pelo Windows desta maquina; confirmar tambem
em maquina limpa, sem raizes privadas instaladas.

```powershell
.\desktop\sign_windows.ps1 -Path .\desktop\dist-signed -Report .\desktop\dist-signed\signatures.json
```

O desinstalador fica comprimido no NSIS e nao e enumerado no relatorio da
arvore: apos instalar em VM limpa, verificar tambem sua assinatura com
Get-AuthenticodeSignature antes de considerar a distribuicao aceita.
Reexecutar a aceitacao Electron e validar instalacao/desinstalacao, preservacao
dos dados e Smart App Control. O build ja executa a aceitacao Electron.

## Referencias

- Microsoft: https://learn.microsoft.com/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control
- electron-builder v26: https://www.electron.build/v26/docs/win/

Microsoft recomenda Artifact Signing como opcao de assinatura. A escolha
exige confirmar elegibilidade do editor, disponibilidade e custo; nao foram
criados recursos pagos nem enviada identidade neste trabalho.
