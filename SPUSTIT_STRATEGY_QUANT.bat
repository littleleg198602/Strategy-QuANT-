@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Strategy QuANT

echo.
echo ==========================================
echo   Strategy QuANT - Windows launcher
echo ==========================================
echo.

set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto install

echo [1/3] Vytvarim lokalni Python prostredi...

where py >nul 2>&1
if errorlevel 1 goto try_python

py -3.12 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv
    goto check_venv
)

py -3.11 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 (
    py -3.11 -m venv .venv
    goto check_venv
)

:try_python
where python >nul 2>&1
if errorlevel 1 goto no_python

python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto no_python
python -m venv .venv

:check_venv
if not exist "%VENV_PY%" goto venv_failed

:install
echo [2/3] Kontroluji a instaluji potrebne balicky...
"%VENV_PY%" -m pip install --disable-pip-version-check -e .
if errorlevel 1 goto install_failed

echo [3/3] Oteviram Strategy QuANT v prohlizeci...
echo.
echo MetaTrader 5 musi byt spusteny a prihlaseny.
echo Aplikaci ukoncis klavesami Ctrl+C v tomto okne.
echo.
"%VENV_PY%" -m streamlit run app.py --server.headless false
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Strategy QuANT skoncil s chybou %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%

:no_python
echo.
echo CHYBA: Nenasel jsem Python 3.11 nebo 3.12.
echo Nainstaluj Python z https://www.python.org/downloads/windows/
echo Pri instalaci zaskrtni "Add python.exe to PATH".
echo.
pause
endlocal & exit /b 1

:venv_failed
echo.
echo CHYBA: Nepodarilo se vytvorit slozku .venv.
echo Zkontroluj opravneni k teto slozce a volne misto na disku.
echo.
pause
endlocal & exit /b 1

:install_failed
echo.
echo CHYBA: Instalace zavislosti se nepodarila.
echo Zkontroluj pripojeni k internetu a chybovou zpravu vyse.
echo.
pause
endlocal & exit /b 1
