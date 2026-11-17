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

### Publicação automática de todas as versões estáveis aprovadas

1. Uma mudança de Desktop só é elegível após aprovação, merge na `main` e atualização explícita do número em `desktop/package.json` (SemVer `X.Y.Z`). Builds de PR e branches de desenvolvimento **não são publicadas**.
2. A conclusão **bem-sucedida** do workflow `Central IA checks` em um **push confiável para `main`** inicia `.github/workflows/release-desktop.yml`. Ele não aceita a conclusão de CI de pull requests ou branches.
3. O workflow compara a versão com as publicadas: se já existe `vX.Y.Z`, não cria duplicata; se é menor ou igual à última estável, não publica downgrade. Detecta tags remotas existentes e não as sobrescreve.
4. A assinatura digital Windows é obrigatória. Configure os GitHub Actions secrets **`CENTRAL_WINDOWS_SIGNING_PFX_BASE64`** (certificado PFX em Base64) e **`CENTRAL_WINDOWS_SIGNING_PASSWORD`**. Se estiverem ausentes, a publicação **falha sem enviar um EXE**. O workflow verifica `Get-AuthenticodeSignature` do executável.
5. Compila o instalador e executa um smoke test do backend empacotado; verifica versão, nome e SHA-512 do instalador contra o `latest.yml` antes de publicar.
6. Só então cria uma tag `vX.Y.Z` no commit da `main` que passou nos testes, publica o **GitHub Release estável marcado como Latest** com EXE, `latest.yml` e `*.blockmap` (quando presente), e verifica se o Release contém os ativos essenciais.
7. Teste a atualização entre duas versões assinadas no Windows, incluindo tarefas ativas e dados SQLite WAL. O download e a instalação no desktop instalado continuam exigindo confirmação do usuário, com backup local.

**Importante:** este workflow precisa estar presente na **branch padrão `main`** para responder ao evento `workflow_run`; enquanto estiver apenas em PR ou branch de recurso, não publica nada. A suíte completa, inclusive os testes gerais do navegador, deve passar. Se a CI falhar ou não houver certificado de assinatura, não há Release — por segurança.

A workflow `build-desktop-installer.yml` gera somente **artefatos temporários de teste**, nunca uma versão pública.

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
