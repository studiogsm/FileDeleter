@echo off
setlocal EnableExtensions
title File Deleter v1.6 - Builder

echo ============================================================
echo   Laboratorium Elektroniki - File Deleter v1.6
echo   EXE builder (PyInstaller)
echo ============================================================
echo.

REM --- Check Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo   Download: https://www.python.org/downloads/
    echo   During install, tick "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^&1') do echo [OK] Found: %%v
echo.

REM --- Check / install PyInstaller ---
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [INFO] PyInstaller not found. Installing...
    python -m pip install --upgrade pip
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo [ERROR] PyInstaller install failed.
        pause
        exit /b 1
    )
    echo.
) else (
    for /f "delims=" %%v in ('python -m PyInstaller --version 2^>^&1') do echo [OK] PyInstaller %%v
    echo.
)

REM --- Locate source file (v1.6 EN preferred, fallbacks for older versions) ---
set "SRC=%~dp0file_deleter_v1.6_EN.py"
if not exist "%SRC%" set "SRC=%~dp0file_deleter_v1.6.py"
if not exist "%SRC%" set "SRC=%~dp0file_deleter_v1.5.py"
if not exist "%SRC%" set "SRC=%~dp0file_deleter_v1.4.py"
if not exist "%SRC%" set "SRC=%~dp0file_deleter_v1.3_EN.py"
if not exist "%SRC%" (
    echo [ERROR] No source file found.
    echo Looked for file_deleter_v1.6_EN.py / v1.6.py / v1.5.py / v1.4.py / v1.3_EN.py
    echo in folder:
    echo   %~dp0
    pause
    exit /b 1
)
echo [OK] Source file: %SRC%

REM --- Optional icon ---
set "ICON_ARG="
if exist "%~dp0icon.ico" (
    set "ICON_ARG=--icon=%~dp0icon.ico"
    echo [OK] Using custom icon: icon.ico
)

echo.
echo [INFO] Building FileDeleter.exe...
echo        (this may take 1-3 minutes)
echo.

REM --- Build ---
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --uac-admin ^
    --name FileDeleter ^
    --distpath "%~dp0dist" ^
    --workpath "%~dp0build" ^
    --specpath "%~dp0build" ^
    %ICON_ARG% ^
    "%SRC%"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the log above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   DONE!
echo ============================================================
echo.
echo   File: %~dp0dist\FileDeleter.exe
echo.
echo   Step 1: copy FileDeleter.exe to a stable location
echo           (e.g. C:\Tools\FileDeleter\FileDeleter.exe)
echo   Step 2: run it once, click:
echo           - "Add" next to 'Context menu'  (right-click on folder)
echo           - "Add" next to 'Send To menu'  (for file selections)
echo   Step 3: For LARGE selections (thousands+): in Explorer
echo           Ctrl+C on selected files, then in the GUI:
echo           "Load from clipboard"
echo.

choice /c YN /n /m "Remove intermediate files (build, .spec)? [Y/N] "
if errorlevel 2 goto END
rmdir /s /q "%~dp0build" 2>nul
echo [OK] Intermediate files removed.

:END
echo.
pause
endlocal
