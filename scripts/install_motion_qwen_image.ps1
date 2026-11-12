param(
    [string]$ComfyRoot = (Join-Path $env:LOCALAPPDATA 'Central-IA\motion-studio\ComfyUI')
)

$ErrorActionPreference = 'Stop'
$models = @(
    @{ Folder = 'diffusion_models'; Name = 'qwen_image_2.1_turbo_int8_convrot.safetensors'; Bytes = 7256787829L },
    @{ Folder = 'text_encoders'; Name = 'qwen3vl_8b_int8_convrot.safetensors'; Bytes = 9350798360L },
    @{ Folder = 'vae'; Name = 'qwen_image_2.1_vae_bf16.safetensors'; Bytes = 675509688L }
)

if (-not (Test-Path -LiteralPath (Join-Path $ComfyRoot 'main.py') -PathType Leaf)) {
    throw 'Instalação do ComfyUI da Central não encontrada.'
}
Write-Host 'Qwen Image 2.1 Turbo: licença de pesquisa/avaliação não comercial. Uso comercial exige licença separada.'
Write-Host 'https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/LICENSE'

foreach ($model in $models) {
    $directory = Join-Path (Join-Path $ComfyRoot 'models') $model.Folder
    $path = Join-Path $directory $model.Name
    if ((Test-Path -LiteralPath $path -PathType Leaf) -and (Get-Item -LiteralPath $path).Length -eq $model.Bytes) {
        Write-Host "Já instalado: $($model.Name)"
        continue
    }
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $url = "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/$($model.Folder)/$($model.Name)"
    & curl.exe -fL -C - --retry 3 --retry-delay 5 -o $path $url
    if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $path).Length -ne $model.Bytes) {
        throw "Download incompleto: $($model.Name). Execute o script novamente para retomar."
    }
    Write-Host "Instalado: $($model.Name)"
}
