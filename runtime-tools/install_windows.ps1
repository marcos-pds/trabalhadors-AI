param([string]$ToolsDir = (Join-Path $env:LOCALAPPDATA 'Central IA\runtime-tools'))
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($ToolsDir)
if (-not [IO.Path]::IsPathRooted($ToolsDir) -or $target.StartsWith('\\') -or
    $target.TrimEnd('\') -eq [IO.Path]::GetPathRoot($target).TrimEnd('\') -or
    $target.TrimEnd('\') -eq $env:USERPROFILE.TrimEnd('\') -or
    $target.TrimEnd('\') -eq (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')) {
    throw 'Escolha uma pasta local especifica para as ferramentas.'
}
$manifest = Join-Path $target 'package.json'
if (Test-Path -LiteralPath $manifest) {
    $existing = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    if ($existing.name -ne 'central-external-runtime-tools') { throw 'A pasta ja pertence a outra instalacao.' }
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
$current = Get-Item -LiteralPath $target
while ($current) {
    if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Links e juncoes nao sao permitidos.' }
    $current = $current.Parent
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'package.json') -Destination $target
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'package-lock.json') -Destination $target
Push-Location $target
try {
    & npm ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Instalacao dos runtimes falhou.' }
} finally { Pop-Location }
Write-Host "Ferramentas opcionais instaladas em $target. Nao foram feitos login ou inferencia."
