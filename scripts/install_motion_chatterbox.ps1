param(
    [string]$Python311 = '3.11'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $repo 'data\motion-studio\chatterbox-runtime'
$python = Join-Path $runtime 'Scripts\python.exe'

uv venv $runtime --python $Python311
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python 3.11.' }
uv pip install --python $python 'chatterbox-tts==0.1.7'
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar as dependências Chatterbox.' }
uv pip install --python $python --no-deps 'git+https://github.com/resemble-ai/chatterbox.git@5de7a54aa4e5e2baadb0182dde554908b48b85c2'
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar a revisão oficial Multilingual V3.' }
uv pip install --python $python --reinstall 'torch==2.6.0+cu124' 'torchaudio==2.6.0+cu124' --index-url 'https://download.pytorch.org/whl/cu124'
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar PyTorch CUDA.' }
uv pip install --python $python 'setuptools<81'
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar a dependência do marcador de áudio.' }
& $python -c 'import torch, perth; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; assert torch.cuda.is_available() and perth.PerthImplicitWatermarker is not None; print("Chatterbox V3 e CUDA prontos")'
if ($LASTEXITCODE -ne 0) { throw 'Chatterbox ou CUDA indisponível nesta máquina.' }
