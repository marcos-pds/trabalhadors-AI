# Atualizações da Central Desktop por GitHub Releases

Primeira versão com atualizador integrado: **0.3.3**. Este mecanismo existe **somente no Windows/Electron**. A web e o PWA não recebem atualização nativa nem acesso aos IPCs.

## Fluxo com consentimento

1. O aplicativo instalado consulta a versão **estável** mais recente no GitHub Releases do repositório marcos-pds/trabalhadors-AI ao abrir e periodicamente. Builds de PR, branches, Actions artifacts e versões prerelease são ignorados.
2. Uma notificação discreta aparece no dock Liquid Glass. O download só ocorre ao clicar em "Baixar atualização".
3. O electron-updater confere os arquivos de atualização pelo manifesto latest.yml gerado junto ao instalador (SHA-512 e assinatura de publicador, quando configurada). O frontend não escolhe URL nem caminho de instalação.
4. "Instalar e reiniciar" pede uma segunda confirmação nativa. O processo Electron consulta o backend local por um endpoint privado com token aleatório, nunca transmitido ao React.
5. O backend **bloqueia novas gravações** e recusa a atualização se houver tarefas com status queued, running, awaiting_approval ou awaiting_integration.
6. Antes de instalar, o Electron encerra o backend que ele iniciou e aguarda a saída; em seguida copia userData/data para userData/backups/backup-..., incluindo SQLite/WAL, configurações e segredos, verificando cada arquivo por SHA-256 e tamanho. Conservar cinco backups.
7. Se o backup falhar, a atualização é abortada e o backend é reiniciado. O instalador só recebe autorização depois do backup.

Os backups ficam no computador, **não no GitHub**. Eles incluem material sensível e chaves. Não envie essas pastas a terceiros.

## Publicar versões estáveis

O atualizador NÃO usa automaticamente resultados temporários do GitHub Actions. Para que uma atualização seja encontrada, o maintainer deve publicar um GitHub Release estável com estes artefatos do **mesmo build assinado**:

- Central-Setup-X.Y.Z-x64.exe
- latest.yml (versão e hash SHA-512)
- *.blockmap, quando produzido

Etapas:

1. Revise e faça merge da implementação, com testes concluídos.
2. Configure secrets do repositório CENTRAL_WINDOWS_SIGNING_PFX_BASE64 (PFX de assinatura Windows, em Base64) e CENTRAL_WINDOWS_SIGNING_PASSWORD. O workflow de release falha se esses secrets estiverem ausentes ou se a assinatura Authenticode do instalador for inválida.
3. Garanta que a versão no desktop/package.json corresponda exatamente à tag estável.
4. Crie a tag vX.Y.Z no commit aprovado. A workflow .github/workflows/release-desktop.yml compila, assina, verifica o manifest e cria o GitHub Release.
5. Teste a atualização entre duas versões assinadas do aplicativo no Windows, inclusive com tarefas ativas e banco SQLite WAL.

A workflow build-desktop-installer.yml gera **artefatos de teste**, não lança versões públicas.

## Versões antigas e restauração

Versões 0.3.2 e anteriores não contêm este atualizador. Será necessária **uma instalação manual inicial** de uma versão assinada 0.3.3 (ou posterior). Depois disso, a Central poderá atualizar pelo próprio aplicativo.

Para restaurar, feche a Central, salve a pasta de dados atual como segurança, selecione um backup em userData/backups e copie a subpasta data dele para userData/data. Use o manifest.json para conferir o conteúdo. Caso uma versão nova tenha migrado o banco de forma incompatível, também será necessário reinstalar a versão antiga; **não existe rollback binário automático após falha no NSIS**.

O atualizador altera somente a Central Desktop, não modelos do Ollama/VoiceStudio, Docker ou provedores externos.

## Testes

- node --test desktop/tests/backup.test.cjs
- python -m pytest tests/test_desktop_updates.py -q
- node --check desktop/main.cjs
- node --check desktop/updater.cjs
- node --check desktop/preload.cjs
- npm run build; depois build Windows com latest.yml
- Validação manual gráfica: consentimento, avisos, download, recusa em tarefa ativa, backup completo e reinicialização.
