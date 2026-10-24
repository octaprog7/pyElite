@echo off
rem ===========================================================================
rem  run_cli.bat — Windows launcher for pyElite CLI (text adventure / trading).
rem
rem  By default starts the interactive command loop (GameLoop.run()):
rem      run_cli.bat
rem
rem  Options:
rem      run_cli.bat --demo      run the demo scenario (game_loop.py __main__)
rem      run_cli.bat -h ^| --help  show this help
rem
rem  Uses .venv\Scripts\python.exe when a virtualenv is present next to this
rem  file, otherwise the py launcher / python from PATH. Logs:
rem  log\game_log.csv and elite_events.db.
rem  The game itself supports ru/en/es UI (command: lang). UTF-8 console mode
rem  is enabled automatically (chcp 65001 + python -X utf8).
rem ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

rem ---- Locate Python 3.10+ ------------------------------------------------
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

rem ---- UTF-8 console so ru/es text renders correctly -----------------------
chcp 65001 >nul

rem ---- Dispatch ------------------------------------------------------------
if /i "%~1"=="--demo" goto demo
if /i "%~1"=="-h"     goto help
if /i "%~1"=="--help" goto help
goto interactive

:demo
%PY% -X utf8 game_loop.py
exit /b %errorlevel%

:interactive
%PY% -X utf8 -c "from game_loop import GameLoop; GameLoop().run()"
exit /b %errorlevel%

:help
echo.
echo run_cli.bat - pyElite CLI launcher (Windows)
echo.
echo   run_cli.bat              interactive CLI
echo   run_cli.bat --demo       demo scenario, then exit
echo   run_cli.bat -h^|--help   this help
echo.
echo Logs: log\game_log.csv, elite_events.db
pause
exit /b 0