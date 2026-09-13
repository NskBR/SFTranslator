@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0lt.exe" (
    echo [ERRO] lt.exe nao foi encontrado nesta pasta.
    echo Use o conteudo de dist\UAT-Unity; Python nao deve ser necessario.
    echo.
    pause
    exit /b 2
)

"%~dp0lt.exe"
set "UAT_EXIT_CODE=%ERRORLEVEL%"

if not "%UAT_EXIT_CODE%"=="0" (
    echo.
    echo [ERRO] O UAT-Unity encerrou com o codigo %UAT_EXIT_CODE%.
    echo Consulte tambem a pasta Logs.
)

echo.
pause
exit /b %UAT_EXIT_CODE%
