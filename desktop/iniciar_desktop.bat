@echo off
setlocal
cd /d "%~dp0.."
echo ============================================
echo  CENTRAL IA - DESKTOP LIQUID GLASS
echo ============================================
where npm >nul 2>nul
if errorlevel 1 (
  echo Instale Node.js 20+ para executar o desktop.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Instale primeiro as dependencias da Central com iniciar_windows.bat.
  pause
  exit /b 1
)
if not exist "static\build\index.html" (
  echo Compilando interface...
  if not exist "node_modules" call npm ci
  if errorlevel 1 goto error
  call npm run build
  if errorlevel 1 goto error
)
set "CENTRAL_HOST=127.0.0.1"
set "CENTRAL_PORT=8765"
powershell -NoProfile -Command "try { $null=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo Iniciando backend da Central na porta 8765...
  start "Central IA Backend" /min cmd /c ".venv\Scripts\python.exe run.py"
) else (
  echo Servidor ja ativo na porta 8765.
  echo Verifique se ele usa o codigo e o build desta copia da Central.
)
if not defined CENTRAL_DESKTOP_URL set "CENTRAL_DESKTOP_URL=http://127.0.0.1:8765/"
cd /d "%~dp0"
if not exist "node_modules\electron" (
  echo Preparando aplicativo desktop...
  call npm install --no-audit --no-fund
  if errorlevel 1 goto error
)
call npm start
goto end
:error
echo Falha ao iniciar desktop.
pause
:end
endlocal
