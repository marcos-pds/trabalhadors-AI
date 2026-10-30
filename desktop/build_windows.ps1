# Developer build only. Generates an UNSIGNED Windows pilot installer.
# Does not run inside the installed app. Requires a trusted build machine.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Crie primeiro .venv com Python 3.11+ na raiz do repositorio."
}
Push-Location $root
try {
    & $python -m pip install -r requirements.txt "pyinstaller==6.22.3"
    if ($LASTEXITCODE -ne 0) { throw "Falha nas dependencias Python." }
    & npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Falha nas dependencias React." }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "Build React falhou." }
    & $python -m pytest -q tests/test_desktop_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "Testes do bootstrap falharam." }
    & node --check (Join-Path $PSScriptRoot "main.cjs")
    if ($LASTEXITCODE -ne 0) { throw "Sintaxe JavaScript invalida." }
    & node --test (Join-Path $PSScriptRoot "dependency_inventory.test.cjs")
    if ($LASTEXITCODE -ne 0) { throw "Teste de diagnostico de dependencias falhou." }
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
    Push-Location $PSScriptRoot
    try {
        & npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Dependencias de build Electron falharam." }
        & npm run dist:win
        if ($LASTEXITCODE -ne 0) { throw "Criacao do instalador falhou." }
    } finally { Pop-Location }
    Write-Host "Instalador piloto UNSIGNED em desktop/dist-installer."
} finally { Pop-Location }
