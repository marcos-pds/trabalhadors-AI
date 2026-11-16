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
start "Central IA Backend" /min cmd /c ".venv\Scripts\python.exe run.py"
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
