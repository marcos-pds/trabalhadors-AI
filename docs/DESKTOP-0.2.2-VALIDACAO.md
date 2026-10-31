# Central IA Desktop 0.2.2 — 31/10/2026

Inclui reconciliacao de promocao/handoff, retomada de worktree apos cancelamento
e recuperacao limitada de contexto HTTP 413. As correcoes web foram incorporadas
ao desktop. O laboratorio com APIs configuradas permanece separado da producao.

## Artefato

- Instalador: `Central-IA-Setup-0.2.2.exe`.
- Tamanho: 143.445.605 bytes.
- SHA256: `5d802c18cd003693845440e29d6221abbf10256da1be6798fb50bf10b491d029`.
- Saida: `desktop/dist-installer`; copia em Downloads/Central-IA-Desktop-0.2.2.
- Sem assinatura; nenhum certificado foi adquirido ou utilizado.

## Verificacao

Build completo terminou com codigo zero: bootstrap Python, testes Node (41),
PyInstaller, prontidao HTTP do backend congelado, NSIS e oito verificacoes do
Electron empacotado. Os checks incluem cadastro, diagnostico Motion e recarga,
projeto autenticado, isolamento do renderer, previa interativa sem credenciais
da Central, fechamento das portas e persistencia depois de reiniciar.
`desktop/test-results/packaged.json`: passed=true, final_backend_closed=true
e final_preview_closed=true.

Na web, a regressao completa passou com 1.213 testes e 31 ignorados. Depois das
correcoes adicionais, passaram 131 testes de autonomia/delegacao/contexto, 11
de checkpoints, seis do adaptador de APIs e a regressao de retomada cancelada.
Nao se repetiu a suite integral apos essas ultimas alteracoes; os testes
direcionados e o build final exercitaram os caminhos alterados.

O [ensaio TaskLab sem Codex](TASKLAB-APIS-20261031.md) e real, mas **nao foi
aprovado**. Criacao de arquivos, failover e retomada nao equivalem a aceitacao
final do projeto. A execucao foi encerrada com checkpoints, sem worker restante.

O teste do pacote executa o payload win-unpacked, nao instala sobre os dados do
usuario. Atualizacao NSIS em VM limpa, OAuth real, assinatura e updater continuam
pendentes. O aplicativo instalado so recebe estas correcoes ao instalar a 0.2.2.
