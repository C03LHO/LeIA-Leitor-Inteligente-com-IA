@echo off
setlocal
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"
set "APPDATA_LEIA=%APPDATA%\LeIA"
set "VENV=%APPDATA_LEIA%\venv"
set "SETUP_FLAG=%APPDATA_LEIA%\.setup_complete"

rem Primeira execucao: cria o ambiente e baixa as dependencias (janela propria).
if not exist "%SETUP_FLAG%" (
    "%APP_DIR%python\pythonw.exe" "%APP_DIR%first_run.py"
    if not exist "%SETUP_FLAG%" exit /b 1
)

rem Abre o app numa janela nativa (sem console).
start "" "%VENV%\Scripts\pythonw.exe" -m backend.main --window
endlocal
exit /b 0
