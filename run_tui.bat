@echo off
rem ===========================================================================
rem  run_tui.bat — Windows launcher for pyElite TUI (Textual full-screen UI).
rem
rem  Usage:
rem      run_tui.bat                interactive TUI
rem      run_tui.bat --lang ru      TUI in Russian (en/ru/es)
rem
rem  Requirements: the 'textual' package:
rem      py -m pip install textual           (or)
rem      py -m pip install -e ".[tui]"
rem
rem  Recommended terminal: Windows Terminal (10/11). Double-click in Explorer
rem  opens conhost — it works too, but Windows Terminal handles colors/UTF-8
rem  better. All arguments (e.g. --lang en) are passed to elite_tui.py.
rem
rem  Uses .venv\Scripts\python.exe when present, otherwise py launcher /
rem  python from PATH. UTF-8 console mode is enabled automatically.
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

rem ---- Check that textual is installed -------------------------------------
%PY% -X utf8 -c "import textual" >nul 2>nul
if errorlevel 1 (
    echo Error: the 'textual' package is not installed.
    echo Install it with:
    echo     %PY% -m pip install textual
    echo or with the TUI extra:
    echo     %PY% -m pip install -e ".[tui]"
    pause
    exit /b 1
)

rem ---- Launch (all arguments, e.g. --lang es, are forwarded) --------------
%PY% -X utf8 elite_tui.py %*
exit /b %errorlevel%