# Developer build only. Use -Signed for the separate certificate-required output.
# Does not run inside the installed app. Requires a trusted build machine.
param([switch]$SkipInstall, [switch]$SkipFrontend, [switch]$Signed)
$ErrorActionPreference = "Stop"
if ($Signed -and $env:CENTRAL_SIGN_CERT_SHA1 -notmatch '^[a-fA-F0-9]{40}$') { throw 'Build assinado exige CENTRAL_SIGN_CERT_SHA1. Consulte desktop/ASSINATURA.md.' }
$outputName = if ($Signed) { 'dist-signed' } else { 'dist-installer' }
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Crie primeiro .venv com Python 3.11+ na raiz do repositorio."
}
Push-Location $root
try {
    if (-not $SkipInstall) {
        & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-lock.txt')
        if ($LASTEXITCODE -ne 0) { throw "Falha nas dependencias Python." }
        & npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Falha nas dependencias React." }
    }
    if (-not $SkipFrontend) {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Build React falhou." }
    }
    & $python -m pytest -q tests/test_desktop_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "Testes do bootstrap falharam." }
    & node --check (Join-Path $PSScriptRoot "main.cjs")
    if ($LASTEXITCODE -ne 0) { throw "Sintaxe JavaScript invalida." }
    & node --test (Join-Path $PSScriptRoot "dependency_inventory.test.cjs")
    if ($LASTEXITCODE -ne 0) { throw "Teste de diagnostico de dependencias falhou." }
    & node --test (Join-Path $PSScriptRoot "process_lifecycle.test.cjs")
    if ($LASTEXITCODE -ne 0) { throw "Teste de encerramento do processo falhou." }
    & node --test (Join-Path $PSScriptRoot "setup_profiles.test.cjs")
    if ($LASTEXITCODE -ne 0) { throw "Teste de perfis opcionais falhou." }
    if (Test-Path (Join-Path $PSScriptRoot 'security_policy.test.cjs')) {
        & node --test (Join-Path $PSScriptRoot 'security_policy.test.cjs')
        if ($LASTEXITCODE -ne 0) { throw 'Teste de seguranca Electron falhou.' }
    }
    & node --test (Join-Path $PSScriptRoot 'main.test.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Teste do ciclo Electron falhou.' }
    $staticData = (Join-Path $root "static") + ";static"
    $pyiArgs = @(
        "--noconfirm", "--clean", "--onedir",
        "--name", "central-desktop-backend",
        "--paths", $root,
        "--distpath", (Join-Path $PSScriptRoot "dist"),
        "--workpath", (Join-Path $PSScriptRoot ".pyinstaller-build"),
        "--specpath", $PSScriptRoot,
        "--add-data", $staticData,
        (Join-Path $PSScriptRoot "backend_launcher.py")
    )
    & $python -m PyInstaller @pyiArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou." }
    $binary = Join-Path $PSScriptRoot "dist\central-desktop-backend\central-desktop-backend.exe"
    if (-not (Test-Path $binary)) { throw "Backend empacotado ausente." }
    & $python (Join-Path $PSScriptRoot 'smoke_backend.py') $binary
    if ($LASTEXITCODE -ne 0) { throw 'Backend empacotado nao passou na verificacao HTTP.' }
    Push-Location $PSScriptRoot
    try {
        if (-not $SkipInstall) {
            & npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "Dependencias de build Electron falharam." }
        }
        & npm test
        if ($LASTEXITCODE -ne 0) { throw 'Testes desktop falharam.' }
        if ($Signed) { & npx --no-install electron-builder --win nsis --config electron-builder.signed.cjs }
        else { & npm run dist:win }
        if ($LASTEXITCODE -ne 0) { throw "Criacao do instalador falhou." }
    } finally { Pop-Location }
    $outputDir = Join-Path $PSScriptRoot $outputName
    if ($Signed) {
        & (Join-Path $PSScriptRoot 'sign_windows.ps1') -Path $outputDir -Report (Join-Path $outputDir 'signatures.json')
    }
    $packaged = Join-Path $outputDir 'win-unpacked\Central IA.exe'
    if (-not (Test-Path -LiteralPath $packaged)) { throw 'Aplicativo desktop ausente.' }
    & node (Join-Path $PSScriptRoot 'smoke_ui.cjs') $packaged
    if ($LASTEXITCODE -ne 0) { throw 'A interface Electron empacotada falhou na aceitacao.' }
    $sums = Get-ChildItem $outputDir -Filter '*.exe' -File | ForEach-Object {
        $digest = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        '{0} *{1}' -f $digest, $_.Name
    }
    $sums | Set-Content (Join-Path $outputDir 'SHA256SUMS.txt') -Encoding ascii
    Write-Host "Instalador Windows em $outputDir; assinatura solicitada: $Signed."
} finally { Pop-Location }
