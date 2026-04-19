@echo off
setlocal enabledelayedexpansion
REM DD Content Browser - Standalone Launcher BAT
REM Finds Python 3.11 from multiple locations

REM Get script directory
set SCRIPT_DIR=%~dp0

REM Get version from __init__.py by parsing the file
for /f "tokens=2 delims='" %%i in ('findstr /C:"__version__ = " "%SCRIPT_DIR%__init__.py"') do set VERSION=%%i
if not defined VERSION set VERSION=Unknown

echo ============================================================
echo DD Content Browser v%VERSION% (Standalone)
echo ============================================================

REM Find Python 3.11 - try multiple locations
set "PYTHON_PATH="

REM 1. Try Windows py launcher - resolve actual exe path
where py >nul 2>nul && py -3.11 --version >nul 2>nul && (
    for /f "delims=" %%p in ('py -3.11 -c "import sys; print(sys.executable)"') do set "PYTHON_PATH=%%p"
)

REM 2. Company-wide install
if "%PYTHON_PATH%"=="" if exist "C:\Python311\python.exe" set "PYTHON_PATH=C:\Python311\python.exe"

REM 3. User AppData install
if "%PYTHON_PATH%"=="" (
    set "_USER_PY=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    if exist "!_USER_PY!" set "PYTHON_PATH=!_USER_PY!"
)

if "%PYTHON_PATH%"=="" (
    echo ERROR: Python 3.11 not found!
    echo Install Python 3.11 from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Using Python: %PYTHON_PATH%
echo.

REM Run the launcher
"%PYTHON_PATH%" "%SCRIPT_DIR%standalone_launcher.py"

REM If window closes immediately, keep console open
if errorlevel 1 (
    echo.
    echo ============================================================
    echo ERROR: Browser failed to start!
    echo ============================================================
    pause
)
