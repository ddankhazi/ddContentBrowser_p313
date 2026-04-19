@echo off
setlocal enabledelayedexpansion
REM DD Content Browser - Silent Standalone Launcher BAT (INTERNAL)
REM Finds Python 3.11 from multiple locations - NO CONSOLE WINDOW

REM Get script directory
set SCRIPT_DIR=%~dp0

REM Find Python 3.11 - try multiple locations
set "PYTHON_PATH="

REM 1. Try Windows py launcher - resolve actual exe path
where py >nul 2>nul && py -3.11 --version >nul 2>nul && (
    for /f "delims=" %%p in ('py -3.11 -c "import sys; print(sys.executable)"') do set "PYTHON_PATH=%%p"
)

REM 2. Company-wide install (prefer pythonw.exe for no console)
if "%PYTHON_PATH%"=="" if exist "C:\Python311\pythonw.exe" set "PYTHON_PATH=C:\Python311\pythonw.exe"
if "%PYTHON_PATH%"=="" if exist "C:\Python311\python.exe" set "PYTHON_PATH=C:\Python311\python.exe"

REM 3. User AppData install
if "%PYTHON_PATH%"=="" (
    set "_USER_PYW=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\pythonw.exe"
    if exist "!_USER_PYW!" set "PYTHON_PATH=!_USER_PYW!"
)
if "%PYTHON_PATH%"=="" (
    set "_USER_PY=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    if exist "!_USER_PY!" set "PYTHON_PATH=!_USER_PY!"
)

if "%PYTHON_PATH%"=="" exit /b 1

REM Run the launcher (silent - no console window)
start "" %PYTHON_PATH% "%SCRIPT_DIR%ddContentBrowser_internal.pyw"
