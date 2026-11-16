$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

Write-Host '[1/5] Dependencias da interface'
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'npm ci falhou' }

Write-Host '[2/5] Compilando a Central'
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Build do frontend falhou' }

Write-Host '[3/5] Incluindo o servico local'
python -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependencias Python falharam' }
python -m pip install --disable-pip-version-check 'pyinstaller==6.16.0' 'pillow>=10,<12' 'mcp[cli]==1.30.0'
if ($LASTEXITCODE -ne 0) { throw 'Ferramentas de empacotamento falharam' }
$pyArgs = @('--noconfirm', '--clean', '--onedir', '--name', 'central-backend',
  '--paths', $root, '--distpath', "$root\dist\backend",
  '--workpath', "$root\dist\pyinstaller-work",
  '--specpath', "$root\dist\spec",
  '--add-data', "$root\static;static",
  '--collect-submodules', 'central', '--collect-all', 'mcp',
  '--collect-all', 'fastapi', '--collect-all', 'uvicorn',
  "$root\desktop\backend_entry.py")
python -m PyInstaller @pyArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou' }
$server = "$root\dist\backend\central-backend\central-backend.exe"
if (-not (Test-Path $server)) { throw "Backend ausente: $server" }

Write-Host '[4/5] Preparando visual limpo do instalador'
python "$root\desktop\generate_installer_assets.py"
if ($LASTEXITCODE -ne 0) { throw 'Falha na arte do instalador' }

Write-Host '[5/5] Criando instalador EXE'
Set-Location "$root\desktop"
npm install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Dependencias Electron falharam' }
npm run dist:win
if ($LASTEXITCODE -ne 0) { throw 'Geracao do instalador falhou' }
Get-ChildItem "$root\desktop\release\*.exe" | Select-Object Name,Length,FullName
