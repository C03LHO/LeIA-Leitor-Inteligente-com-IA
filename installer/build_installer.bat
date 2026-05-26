@echo off
REM Build do instalador LeIA.
REM Requisitos:
REM   - Inno Setup 6 instalado (iscc.exe no PATH ou em C:\Program Files (x86)\Inno Setup 6)
REM   - Conexão de internet (baixa Python embeddable e get-pip)
REM   - Executado a partir do diretório installer\

setlocal enabledelayedexpansion
set "HERE=%~dp0"
set "ROOT=%HERE%.."
set "BUILD=%HERE%_build"
set "PY_VERSION=3.11.9"
set "PY_ZIP=python-%PY_VERSION%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_ZIP%"
set "GETPIP_URL=https://bootstrap.pypa.io/get-pip.py"

echo === Limpando build anterior ===
if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%BUILD%"
mkdir "%BUILD%\python"

echo === Baixando Python embeddable %PY_VERSION% ===
powershell -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%BUILD%\python.zip'" || goto :err
powershell -Command "Expand-Archive -Path '%BUILD%\python.zip' -DestinationPath '%BUILD%\python' -Force" || goto :err
del "%BUILD%\python.zip"

echo === Habilitando site-packages no embeddable ===
for %%F in ("%BUILD%\python\python*._pth") do (
    powershell -Command "(Get-Content '%%F') -replace '#import site','import site' | Set-Content '%%F'"
)

echo === Baixando get-pip.py ===
powershell -Command "Invoke-WebRequest -Uri '%GETPIP_URL%' -OutFile '%BUILD%\python\get-pip.py'" || goto :err
"%BUILD%\python\python.exe" "%BUILD%\python\get-pip.py" --no-warn-script-location || goto :err
del "%BUILD%\python\get-pip.py"

echo === Copiando código-fonte ===
xcopy "%ROOT%\backend"  "%BUILD%\backend\"  /E /I /Y /Q  >nul
xcopy "%ROOT%\frontend" "%BUILD%\frontend\" /E /I /Y /Q  >nul
if exist "%ROOT%\voices" xcopy "%ROOT%\voices" "%BUILD%\voices\" /E /I /Y /Q >nul

echo === Compilando instalador com Inno Setup ===
set "ISCC=iscc"
where %ISCC% >nul 2>nul
if errorlevel 1 set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
"%ISCC%" "%HERE%leia.iss" || goto :err

echo.
echo === OK: instalador gerado em %ROOT%\dist\ ===
exit /b 0

:err
echo *** Falha no build ***
exit /b 1
