@echo off
setlocal
set "APP_DIR=%~dp0"
set "APPDATA_LEIA=%APPDATA%\LeIA"
set "VENV=%APPDATA_LEIA%\venv"
set "SETUP_FLAG=%APPDATA_LEIA%\.setup_complete"

if not exist "%SETUP_FLAG%" (
    echo [LeIA] Primeira execucao detectada. Iniciando configuracao...
    "%APP_DIR%python\python.exe" "%APP_DIR%first_run.py"
    if errorlevel 1 (
        echo [LeIA] Configuracao falhou. Veja os logs em %APPDATA_LEIA%\logs\
        pause
        exit /b 1
    )
)

start "" "%VENV%\Scripts\pythonw.exe" -m backend.main --window
endlocal
exit /b 0
