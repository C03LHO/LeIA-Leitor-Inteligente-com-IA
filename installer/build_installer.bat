@echo off
REM Build do instalador LeIA (thin installer).
REM Requisitos:
REM   - Inno Setup 6 instalado (winget install JRSoftware.InnoSetup)
REM   - Conexao de internet (baixa o Python standalone relocavel)
REM   - Executado a partir do diretorio installer\
REM
REM Usa python-build-standalone (CPython completo e relocavel, COM venv/pip/
REM tkinter/ssl) em vez do Python "embeddable" — o embeddable nao tem venv nem
REM tkinter, entao o first_run.py nao rodaria nele.

setlocal enabledelayedexpansion
set "HERE=%~dp0"
set "ROOT=%HERE%.."
set "BUILD=%HERE%_build"

REM CPython 3.11 standalone (install_only). Atualize a tag/versao se quiser.
set "PY_TAG=20260623"
set "PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/%PY_TAG%/cpython-3.11.15%%2B%PY_TAG%-x86_64-pc-windows-msvc-install_only.tar.gz"

echo === Limpando build anterior ===
if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%BUILD%"

echo === Baixando Python standalone (%PY_TAG%) ===
curl.exe -sL -o "%BUILD%\python.tar.gz" "%PY_URL%" || goto :err
echo === Extraindo (cria %BUILD%\python) ===
tar.exe -xzf "%BUILD%\python.tar.gz" -C "%BUILD%" || goto :err
del "%BUILD%\python.tar.gz"
if not exist "%BUILD%\python\python.exe" goto :err

echo === Copiando codigo-fonte ===
robocopy "%ROOT%\backend"  "%BUILD%\backend"  /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP >nul
robocopy "%ROOT%\frontend" "%BUILD%\frontend" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if exist "%ROOT%\voices" robocopy "%ROOT%\voices" "%BUILD%\voices" /E /NFL /NDL /NJH /NJS /NP >nul

echo === Compilando instalador com Inno Setup ===
set "ISCC=iscc"
where %ISCC% >nul 2>nul
if errorlevel 1 set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
"%ISCC%" "%HERE%leia.iss" || goto :err

echo.
echo === OK: instalador gerado em %ROOT%\dist\ ===
exit /b 0

:err
echo *** Falha no build ***
exit /b 1
