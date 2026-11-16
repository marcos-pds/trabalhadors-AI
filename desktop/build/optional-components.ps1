param([switch]$Voice,[switch]$Ollama,[switch]$Qwen,[switch]$Llama,[switch]$Docker)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$folder = Join-Path $env:LOCALAPPDATA 'Central'
New-Item -Path $folder -ItemType Directory -Force | Out-Null
$log = Join-Path $folder 'setup-components.log'
$temporary = Join-Path $env:TEMP ('central-opt-'+[guid]::NewGuid().ToString('n'))
New-Item -Path $temporary -ItemType Directory -Force | Out-Null
$failures = 0
$form = New-Object Windows.Forms.Form
$form.Text='Central - Componentes'
$form.Size=New-Object Drawing.Size(510,210)
$form.StartPosition='CenterScreen'
$form.FormBorderStyle='FixedDialog'
$form.ControlBox=$false
$form.BackColor=[Drawing.Color]::White
$form.Font=New-Object Drawing.Font('Segoe UI',10)
$title=New-Object Windows.Forms.Label
$title.Location=New-Object Drawing.Point(25,22)
$title.Size=New-Object Drawing.Size(430,33)
$title.Font=New-Object Drawing.Font('Segoe UI',15,[Drawing.FontStyle]::Bold)
$title.Text='Configurando componentes'
$form.Controls.Add($title)
$status=New-Object Windows.Forms.Label
$status.Location=New-Object Drawing.Point(25,76)
$status.Size=New-Object Drawing.Size(430,35)
$status.Text='Preparando...'
$form.Controls.Add($status)
$progress=New-Object Windows.Forms.ProgressBar
$progress.Location=New-Object Drawing.Point(25,122)
$progress.Size=New-Object Drawing.Size(430,9)
$progress.Style='Marquee'
$form.Controls.Add($progress)
$note=New-Object Windows.Forms.Label
$note.Location=New-Object Drawing.Point(25,143)
$note.Size=New-Object Drawing.Size(440,36)
$note.ForeColor=[Drawing.Color]::Gray
$note.Text='Instaladores oficiais podem solicitar autorizacao ou aceite de termos.'
$form.Controls.Add($note)

function Notify([string]$message,[int]$value=-1) {
  $status.Text=$message
  if($value -ge 0) { $progress.Style='Continuous'; $progress.Value=[Math]::Min(100,$value) }
  else { $progress.Style='Marquee' }
  [Windows.Forms.Application]::DoEvents()
}
function Log([string]$message) {
  [IO.File]::AppendAllText($log,((Get-Date).ToString('u')+' '+$message+[Environment]::NewLine))
}
function Step([string]$message,[scriptblock]$action) {
  Notify $message
  Log ('INICIO '+$message)
  try { & $action; Log ('OK '+$message) }
  catch { $script:failures++;Log ('ERRO '+$message+': '+$_.Exception.Message) }
}
function Download([string]$url,[string]$destination) {
  $uri=[Uri]$url
  if($uri.Scheme -ne 'https' -or $uri.Host -notin @('github.com','desktop.docker.com','ollama.com')) {
    throw 'Origem de download nao autorizada.'
  }
  $handler=[Net.Http.HttpClientHandler]::new()
  $client=[Net.Http.HttpClient]::new($handler)
  $client.Timeout=[TimeSpan]::FromMinutes(90)
  try {
    $response=$client.GetAsync($uri,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    $response.EnsureSuccessStatusCode()|Out-Null
    $total=$response.Content.Headers.ContentLength
    $inputStream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    $file=[IO.File]::Create($destination)
    try {
      $buffer=New-Object byte[] 131072
      [long]$size=0
      while(($n=$inputStream.Read($buffer,0,$buffer.Length)) -gt 0) {
        $file.Write($buffer,0,$n)
        $size+=$n
        $percent=if($total -gt 0){[int]($size*100/$total)}else{-1}
        Notify ('Baixando: {0:N1} MB' -f ($size/1MB)) $percent
      }
    }finally{$file.Dispose();$inputStream.Dispose()}
    if((Get-Item $destination).Length -lt 1000){throw 'Arquivo incompleto.'}
  }finally{$client.Dispose();$handler.Dispose()}
}
function Run-Setup([string]$exe,[string[]]$args) {
  Notify 'Executando instalador oficial...'
  $p=Start-Process -FilePath $exe -ArgumentList $args -PassThru
  while(-not $p.HasExited){[Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 180;$p.Refresh()}
  if($p.ExitCode -notin @(0,3010)){throw ('Instalador falhou: '+$p.ExitCode)}
}
function CommandPath([string]$command,[string]$fallback) {
  $cmd=Get-Command $command -ErrorAction SilentlyContinue
  if($cmd){return $cmd.Source}
  if(Test-Path $fallback){return $fallback}
  return $null
}
function Has-RegistryApp([string]$prefix) {
  foreach($root in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
    $found=Get-ItemProperty $root -ErrorAction SilentlyContinue|Where-Object {$_.DisplayName -like ($prefix+'*')}|Select-Object -First 1
    if($found){return $true}
  }
  return $false
}
function OllamaExe {
  return CommandPath 'ollama' (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe')
}
function EnsureOllama {
  if(OllamaExe){Log 'Reutilizando Ollama existente';return}
  $exe=Join-Path $temporary 'OllamaSetup.exe'
  Download 'https://ollama.com/download/OllamaSetup.exe' $exe
  Run-Setup $exe @('/S')
  if(-not (OllamaExe)){throw 'Ollama nao foi detectado apos a instalacao.'}
}
function PullModel([string]$model) {
  $ollama=OllamaExe
  if(-not $ollama){throw 'Ollama indisponivel.'}
  try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null }
  catch {
    Log 'Iniciando o servidor Ollama local'
    Start-Process -FilePath $ollama -ArgumentList @('serve') -WindowStyle Hidden | Out-Null
    $ready=$false
    for($try=0;$try -lt 30;$try++){
      try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null; $ready=$true; break }
      catch { [Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 700 }
    }
    if(-not $ready){throw 'O servidor Ollama nao iniciou.'}
  }
  $installed=(& $ollama list 2>&1|Out-String)
  if($installed.Contains($model)){Log ('Modelo ja presente: '+$model);return}
  Notify ('Baixando modelo '+$model+' (acompanhe no Ollama)...')
  $out=Join-Path $temporary 'model.stdout'
  $err=Join-Path $temporary 'model.stderr'
  $p=Start-Process -FilePath $ollama -ArgumentList @('pull',$model) -PassThru -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
  while(-not $p.HasExited){[Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 250;$p.Refresh()}
  if($p.ExitCode -ne 0){throw ('Erro no download de '+$model+': '+(Get-Content $err -Tail 4|Out-String))}
}
function EnsureVoice {
  $existing=CommandPath 'voicestudio' (Join-Path $env:LOCALAPPDATA 'Programs\VoiceStudio\voicestudio.exe')
  if(-not $existing -and -not (Has-RegistryApp 'VoiceStudio')) {
    $release=Invoke-RestMethod 'https://api.github.com/repos/debpalash/VoiceStudio/releases/latest' -Headers @{'User-Agent'='Central-Setup'}
    $asset=$release.assets|Where-Object {$_.name -match '^VoiceStudio-.*-win-x64\.exe$'}|Select-Object -First 1
    $sums=$release.assets|Where-Object {$_.name -eq 'SHA256SUMS.txt'}|Select-Object -First 1
    if(-not $asset -or -not $sums){throw 'Release oficial sem EXE ou SHA256SUMS.'}
    if($asset.browser_download_url -notlike 'https://github.com/debpalash/VoiceStudio/releases/download/*'){throw 'URL nao oficial.'}
    $exe=Join-Path $temporary $asset.name
    $sumFile=Join-Path $temporary 'SHA256SUMS.txt'
    Download $asset.browser_download_url $exe
    Download $sums.browser_download_url $sumFile
    $line=Get-Content $sumFile|Where-Object {$_.EndsWith($asset.name)}|Select-Object -First 1
    if(-not $line){throw 'Hash oficial nao encontrado.'}
    if(((Get-FileHash $exe -Algorithm SHA256).Hash) -ine (($line -split '\s+')[0])){throw 'SHA256 nao confere.'}
    Run-Setup $exe @('/S')
  }else{Log 'Reutilizando VoiceStudio existente'}
  $cli=CommandPath 'voicestudio' (Join-Path $env:LOCALAPPDATA 'Programs\VoiceStudio\voicestudio.exe')
  if(-not $cli){throw 'VoiceStudio instalado; abra-o para configurar o OmniVoice.'}
  # Model licences (OmniVoice and Higgs tokenizer) must be accepted inside VoiceStudio.
  $reply=(& $cli models install 'k2-fsa/OmniVoice' 2>&1|Out-String)
  if($LASTEXITCODE -ne 0){Log $reply;throw 'Confirme a licenca no VoiceStudio para concluir o modelo.'}
  Log ('Instalacao OmniVoice solicitada: '+$reply)
}
function EnsureDocker {
  if(Has-RegistryApp 'Docker Desktop'){Log 'Docker ja presente';return}
  $exe=Join-Path $temporary 'DockerDesktopInstaller.exe'
  Download 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' $exe
  Run-Setup $exe @('install','--user')
  if(-not (Has-RegistryApp 'Docker Desktop')){throw 'Docker pode precisar de reinicializacao ou WSL2.'}
  Log 'Docker instalado. Configuracao WSL2/termos podem ser pedidos no primeiro uso.'
}
try {
  $form.Show()
  [Windows.Forms.Application]::DoEvents()
  if($Voice){Step 'VoiceStudio + OmniVoice' {EnsureVoice}}
  if($Ollama -or $Qwen -or $Llama){Step 'Ollama' {EnsureOllama}}
  if($Qwen){Step 'Qwen 2.5 Coder 3B' {PullModel 'qwen2.5-coder:3b'}}
  if($Llama){Step 'Llama 3.2 3B' {PullModel 'llama3.2:3b'}}
  if($Docker){Step 'Docker Desktop' {EnsureDocker}}
  Notify ('Concluido. Pendencias: '+$failures) 100
  $note.Text='Detalhes: '+$log
  Start-Sleep -Seconds 2
}finally{
  $form.Close();$form.Dispose()
  Remove-Item $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
if($failures){exit 1}
exit 0
