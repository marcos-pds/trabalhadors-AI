# Central IA Desktop 0.2.3 — 31/10/2026

Inclui o contrato opcional de delegacao obrigatoria e a pausa por limite global
de chamadas do laboratorio. O mesmo commit web `58fa3d8` foi incorporado ao
desktop. Nao ha controle novo de delegacao no editor visual; o campo e usado
na definicao JSON do fluxo e pelo harness de aceitacao.

## Artefato local

- `Central-IA-Setup-0.2.3.exe`, Windows x64, NSIS por usuario.
- Tamanho: 143.448.975 bytes; metadados ProductVersion: 0.2.3.
- SHA256: `7749514b66619bc48c74e06dbd4ca969b73939352c853710dfe500921984b379`.
- Copia: Downloads/Central-IA-Desktop-0.2.3.
- Continua sem assinatura. Nao houve instalacao automatica sobre dados do usuario.

## Validacao

Regressao web completa: 1.220 aprovados, 31 ignorados, dois avisos existentes.
Apos a ultima correcao de limite, 77 testes direcionados foram aprovados.
Build local desktop terminou com codigo zero: React, 15 testes de bootstrap,
41 testes Node, PyInstaller, backend congelado por HTTP e instalador NSIS.
O Electron empacotado passou nos oito checks de cadastro, diagnostico Motion,
projeto, seguranca, previa interativa, encerramento e persistencia.
O relatorio packaged.json confirma fechamento das portas finais.

O [ensaio real de delegacao sem Codex](DELEGACAO-OBRIGATORIA-20261031.md)
persistiu uma subtarefa criada pelo arquiteto e incluiu sua dependencia no
revisor. A retomada com uma chamada pausou em paused_limit com checkpoint.
O projeto maior **continua sem aceitacao final**, com backend e etapas
posteriores pendentes. Nao ficou trabalhador do ensaio em execucao.

Essas evidencias sao locais. Instalacao/atualizacao NSIS em VM limpa, OAuth
real, assinatura e atualizador automatico continuam pendentes. Nao se declara
CI remoto aprovado com base no build local. O instalador e evidencia local;
o push Git publica fontes, testes e documentacao, sem os binarios gerados.
