# Central IA Desktop 0.2.1 — 31/10/2026

Pacote local Windows x64 atualizado com o commit web `87c7ba8`, incorporado
na branch desktop como `7b92111`. Inclui o resolvedor de pedidos curtos,
recuperacao de limpeza ACP e painel Motion Studio presentes na web.
O painel e um diagnostico, sem executar jobs de midia.

## Artefato

`desktop/dist-installer/Central-IA-Setup-0.2.1.exe`

- Tamanho: 143.441.024 bytes.
- SHA256: `80af2489c7f4eb5468e96d0e8a9745091978d862940b186c4e7bf3ce3c1a7449`.
- Instalador NSIS por usuario; mesmo diretorio de dados do desktop 0.2.0.
- Continua sem assinatura. Build assinado e separado e exige certificado;
  nenhum certificado foi emitido nem assinatura real realizada.
- Dependencias de empacotamento travadas; CI Windows alinhado ao Python 3.15
  utilizado no build local. O workflow atualizado ainda nao rodou no GitHub.

## Verificacoes

- Web: 1.183 testes Python aprovados, 31 ignorados; 53 frontend e build aprovados.
- Contexto/contrato apos congelamento: 124 testes aprovados; corpus 56/56.
- Desktop: 31 testes Python de launcher, integracao HTTP e interpretador de
  projetos; 41 testes Node, incluindo nove da assinatura/validacao.
- Script de build terminou com codigo zero: build React, testes, PyInstaller,
  backend congelado via HTTP, NSIS e aceitacao Electron real.
- O teste do backend congelado restringe PATH para abrir a Central sem Python
  e Node externos. Projetos de usuarios ainda podem precisar dessas ferramentas.

Aceitacao do aplicativo empacotado com perfil descartavel, oito verificacoes:

1. Cadastro pela interface e sessao autenticada.
2. Inventario Motion real, quatro componentes, estado de execucao indisponivel
   e recarga pela interface, sem alertas.
3. Criacao de projeto pela API autenticada da janela.
4. Sandbox e context isolation ativos, Node desativado no renderer.
5. Previa real interativa, sem cookies ou autorizacao da Central no projeto.
6. Encerramento da previa fecha a porta.
7. Encerramento do Electron fecha seu backend.
8. Reabertura preserva login e projeto.

`desktop/test-results/packaged.json` confirma passed=true e fechamento das
portas finais. A captura [do painel Motion](motion-desktop-0.2.1.png) foi
inspecionada visualmente. Nenhuma conta ou banco de producao foi usado.

## Limites

O teste real executou `win-unpacked/Central IA.exe`; instalacao e atualizacao
NSIS de 0.2.0 para 0.2.1 em VM limpa continuam pendentes. A instalacao anterior
0.2.0 foi confirmada pelo usuario nesta maquina. Nao foi realizado login OAuth
real nem inferencia paga, execucao CLI/ACP certificada ou render de midia.
Nao existe atualizador automatico assinado. O ensaio TaskLab maior continua
pendente conforme a [matriz das 11 etapas](ETAPAS-AUTONOMIA-20261031.md).

O aplicativo instalado anteriormente so recebe estas alteracoes quando o novo
instalador for executado. Nao houve instalacao automatica sobre seus dados.
