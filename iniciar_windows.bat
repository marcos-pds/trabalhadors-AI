@echo off
setlocal
cd /d "%~dp0"
echo.
echo =============================================
echo    CENTRAL DE TRABALHADORES IA - INICIANDO
 echo =============================================
echo.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Python nao encontrado. Instale Python 3.11+ em python.org.
        pause
        exit /b 1
    )
    set "PY=python"
)
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    %PY% -m venv .venv
    if errorlevel 1 goto error
)
echo Verificando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo Acesse: http://127.0.0.1:8765
echo Pressione Ctrl+C para encerrar a Central.
echo.
".venv\Scripts\python.exe" run.py
if errorlevel 1 goto error
goto end
:error
echo Houve um erro. Verifique a instalacao e a porta 8765.
pause
:end
endlocal
