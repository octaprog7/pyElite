@echo off
rem ===========================================================================
rem  bot_autopilot.bat — Windows launcher for the pyElite autopilot bot.
rem  Restarts the bot after every exit forever (death counter).
rem  Stop: Ctrl-C (answer Y to "Terminate batch job").
rem ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PY=py -3"
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Error: Python 3.10+ not found.
            echo Install Python from https://python.org or create a virtualenv:
            echo     python -m venv .venv
            pause
            exit /b 1
        )
        set "PY=python"
    )
)

chcp 65001 >nul

set /a DEATHS=0

:loop
%PY% -X utf8 elite_autopilot.py
set /a DEATHS+=1
echo.
echo ================================
echo   Bot deaths: %DEATHS%
echo   Restarting in 1s... (Ctrl-C to stop)
echo ================================
timeout /t 1 /nobreak >nul
goto loop