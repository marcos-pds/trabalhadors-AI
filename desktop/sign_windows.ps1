param(
    [Parameter(Mandatory=$true)][string]$Path,
    [switch]$Sign,
    [switch]$RequirePublisher,
    [switch]$AuditOnly,
    [string]$Report,
    [string]$Thumbprint = $env:CENTRAL_SIGN_CERT_SHA1,
    [string]$TimestampUrl = 'https://timestamp.digicert.com'
)
$ErrorActionPreference = 'Stop'
if ($Sign -and $AuditOnly) { throw '-Sign e -AuditOnly sao modos mutuamente exclusivos.' }
if (($Sign -or $RequirePublisher) -and $Thumbprint -notmatch '^[a-fA-F0-9]{40}$') {
    throw 'Configure CENTRAL_SIGN_CERT_SHA1 com o certificado publico confiavel do editor.'
}
if ($Sign) {
    $timestamp = $null
    if (-not [Uri]::TryCreate($TimestampUrl, [UriKind]::Absolute, [ref]$timestamp) -or
        $timestamp.Scheme -ne 'https' -or $timestamp.UserInfo -or $timestamp.Fragment -or
        $TimestampUrl -match '\s') {
        throw 'TimestampUrl deve ser uma URL HTTPS absoluta sem credenciais ou fragmento.'
    }
}

function Assert-LocalItem([string]$Name) {
    # Check all existing ancestors, not just the leaf of a junction/symlink path.
    $item = Get-Item -LiteralPath $Name -Force
    if ($item.PSProvider.Name -ne 'FileSystem') { throw 'Destino deve pertencer ao sistema de arquivos.' }
    $current = $item
    while ($current) {
        if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Links simbolicos/juncoes nao sao permitidos na arvore de assinatura.'
        }
        $parent = [IO.Path]::GetDirectoryName($current.FullName.TrimEnd('\', '/'))
        if (-not $parent -or $parent -eq $current.FullName) { break }
        $current = Get-Item -LiteralPath $parent -Force
    }
    return $item
}

$target = Assert-LocalItem $Path
# Enumerate before signing anything. Never follow reparse directories, including
# hidden files and junctions which Get-ChildItem -Recurse may handle differently.
$files = New-Object 'System.Collections.Generic.List[System.IO.FileInfo]'
$pending = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
if ($target.PSIsContainer) { $pending.Push($target) } else { $files.Add($target) }
while ($pending.Count) {
    $directory = $pending.Pop()
    foreach ($item in Get-ChildItem -LiteralPath $directory.FullName -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Links simbolicos/juncoes nao sao permitidos na arvore de assinatura.'
        }
        if ($item.PSIsContainer) { $pending.Push($item) } else { $files.Add($item) }
    }
}

if ($Report) {
    $reportPath = [IO.Path]::GetFullPath($Report)
    if ([IO.Path]::GetExtension($reportPath) -ne '.json') { throw 'Relatorio deve usar a extensao .json.' }
    # Even a PE named *.json must not be overwritten by the report.
    foreach ($file in $files) {
        if ([string]::Equals($file.FullName, $reportPath, [StringComparison]::OrdinalIgnoreCase)) {
            $stream = [IO.File]::OpenRead($file.FullName)
            try { $nativeReport = $stream.ReadByte() -eq 77 -and $stream.ReadByte() -eq 90 }
            finally { $stream.Dispose() }
            if ($nativeReport) { throw 'Relatorio nao pode sobrescrever um binario de entrada.' }
        }
    }
    if (Test-Path -LiteralPath $reportPath) { $null = Assert-LocalItem $reportPath }
    else { $null = Assert-LocalItem ([IO.Path]::GetDirectoryName($reportPath)) }
}

if ($Sign) {
    $cert = Get-Item -LiteralPath "Cert:\CurrentUser\My\$Thumbprint"
    if (-not $cert.HasPrivateKey -or $cert.NotBefore -gt (Get-Date) -or $cert.NotAfter -le (Get-Date)) {
        throw 'Certificado sem chave privada, ainda nao valido ou expirado.'
    }
    if (-not ($cert.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.3')) { throw 'Certificado nao permite assinatura de codigo.' }
    $chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
    try {
        $chain.ChainPolicy.RevocationMode = 'Online'
        $chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(20)
        $null = $chain.ChainPolicy.ApplicationPolicy.Add((New-Object System.Security.Cryptography.Oid('1.3.6.1.5.5.7.3.3')))
        if (-not $chain.Build($cert)) { throw 'Cadeia do certificado nao confiavel ou revogacao nao verificavel.' }
    } finally { $chain.Dispose() }
    $signTool = (Get-Command signtool.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
$rows = @(
    foreach ($file in $files) {
        # Recheck immediately before opening each input; no path can be swapped
        # for a junction during a long signing batch without being rejected.
        $null = Assert-LocalItem $file.FullName
        $stream = [IO.File]::OpenRead($file.FullName)
        try { $native = $stream.ReadByte() -eq 77 -and $stream.ReadByte() -eq 90 } finally { $stream.Dispose() }
        if (-not $native) { continue }
        $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
        if ($Sign -and ($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate -or
            ($RequirePublisher -and $signature.SignerCertificate.Thumbprint -ne $Thumbprint))) {
            & $signTool sign /sha1 $Thumbprint /s My /fd SHA256 /tr $TimestampUrl /td SHA256 $file.FullName
            if ($LASTEXITCODE -ne 0) { throw "Falha ao assinar $($file.Name)" }
            $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
        }
        if ($RequirePublisher -and (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $Thumbprint)) {
            throw 'Editor da assinatura nao corresponde ao certificado configurado.'
        }
        [pscustomobject]@{
            Path = $file.FullName
            SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
            Status = [string]$signature.Status
            Publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
            Thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
            Timestamped = [bool]$signature.TimeStamperCertificate
        }
    }
)
if ($Report) { ConvertTo-Json -InputObject $rows -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8 }
$bad = @($rows | Where-Object { $_.Status -ne 'Valid' -or -not $_.Timestamped })
Write-Host "Binarios: $($rows.Count); validos com timestamp: $($rows.Count - $bad.Count); pendentes: $($bad.Count)"
if (-not $rows.Count) { throw 'Nenhum binario encontrado.' }
if ($bad.Count -and -not $AuditOnly) { throw 'Validacao de assinatura falhou. Consulte o relatorio.' }
