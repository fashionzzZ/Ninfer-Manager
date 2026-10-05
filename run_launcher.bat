@echo off
setlocal
title Ninfer Manager Launcher
cd /d "%~dp0"

echo ============================================================
echo   Ninfer Model Launcher and Manager
echo   Starting Ninfer Web Console...
echo ============================================================

set "PORT=9099"

REM Try python in PATH
python -V >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PYTHON_EXE=python"
    goto :RUN
)

REM Try Python 3.14
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    goto :RUN
)

REM Try Python 3.12
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :RUN
)

REM Try Python 3.11
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :RUN
)

echo [ERROR] Python not found! Please make sure Python 3.10+ is installed.
pause
exit /b 1

:RUN
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo [INFO] Python executable: %PYTHON_EXE%
echo [INFO] Web UI will open automatically after server is ready (3 seconds delay)...
echo.

"%PYTHON_EXE%" "%~dp0server.py" %PORT% --open-browser

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Process exited with error code %ERRORLEVEL%.
    pause
)
