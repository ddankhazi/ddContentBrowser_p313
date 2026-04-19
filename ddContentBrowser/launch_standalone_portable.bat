@echo off
setlocal enabledelayedexpansion
REM DD Content Browser - Standalone Launcher (PORTABLE version)
REM Tries to find Python 3.13 in PATH or common locations

echo Starting DD Content Browser (Standalone - PORTABLE)...

REM Try to find python 3.13 executable
set "PYTHON_CMD="

REM 1. Try Windows py launcher - resolve actual exe path
where py >nul 2>nul && py -3.13 --version >nul 2>nul && (
    for /f "delims=" %%p in ('py -3.13 -c "import sys; print(sys.executable)"') do set "PYTHON_CMD=%%p"
)

REM 2. Check if python313 is in PATH
if "%PYTHON_CMD%"=="" (
    where python313 >nul 2>nul && set "PYTHON_CMD=python313"
)

REM 3. If not found, check if python is in PATH and is version 3.13
if "%PYTHON_CMD%"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        for /f "tokens=2 delims=. " %%v in ('"%%i" --version 2^>nul') do (
            if "%%v"=="3" (
                for /f "tokens=3 delims=. " %%w in ('"%%i" --version 2^>nul') do (
                    if "%%w"=="13" set "PYTHON_CMD=%%i"
                )
            )
        )
    )
)

REM 4. If still not found, check common install locations
if "%PYTHON_CMD%"=="" (
    REM Check C:\Python313 first (common system-wide install)
    if exist "C:\Python313\python.exe" set "PYTHON_CMD=C:\Python313\python.exe"
)

if "%PYTHON_CMD%"=="" (
    REM Check user AppData location
    set COMMON_PYTHON=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe
    if exist "!COMMON_PYTHON!" (
        echo Found Python at !COMMON_PYTHON!
        set "PYTHON_CMD=!COMMON_PYTHON!"
    ) else (
        echo Checking Python installation in user directory...
        dir "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\" 2>nul
    )
)

REM 5. If still not found, prompt user
if "%PYTHON_CMD%"=="" (
    echo ERROR: Could not find Python 3.13 in PATH or common locations.
    echo Please install Python 3.13 and ensure it is in your PATH.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_CMD%

REM Check if PySide6 is installed
"%PYTHON_CMD%" -c "import PySide6" 2>nul
if errorlevel 1 (
    echo ERROR: PySide6 is not installed. Please install it manually.
    pause
    exit /b 1
)

echo Starting application...
"%PYTHON_CMD%" standalone_launcher_portable.py

pause