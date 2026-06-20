@echo off
title LuaTools CLI Node
cd /d "%~dp0"

if exist "luatools_cli\luatools.py" (
    cd luatools_cli
)

if not exist ".installed" (
    echo [System] First run detected. Provisioning dependencies...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [!] Dependency provisioning failed. Please ensure Python and pip are installed.
        pause
        exit /b
    )
    echo. > .installed
    cls
)

python luatools.py
if errorlevel 1 pause
