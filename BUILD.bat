@echo off
echo ============================================
echo  Build: File Deleter v1.3
echo  Laboratorium Elektroniki
echo ============================================
echo.

pip install pyinstaller --quiet

pyinstaller ^
  --onefile ^
  --windowed ^
  --name "FileDeleter_v1.3" ^
  --uac-admin ^
  file_deleter_v1.3_EN.py

echo.
if exist dist\FileDeleter_v1.3.exe (
    echo [OK] EXE ready: dist\FileDeleter_v1.3.exe
) else (
    echo [ERROR] Build failed.
)
pause
