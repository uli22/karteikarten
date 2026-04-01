@echo off
REM ============================================
REM WetzlarReader - Build Script
REM ============================================
REM
REM Erstellt eine standalone EXE-Datei des Readers mit PyInstaller
REM Verwendet die saubere Build-Umgebung (.venv-build)
REM
REM ============================================

echo.
echo =====================================
echo  WetzlarReader Build
echo =====================================
echo.

REM Prüfe ob .venv-build existiert
if not exist ".venv-build\Scripts\python.exe" (
    echo FEHLER: .venv-build nicht gefunden!
    echo Bitte zuerst die Build-Umgebung erstellen:
    echo    uv venv .venv-build
    echo    uv pip install --python .venv-build\Scripts\python.exe -e . pyinstaller
    pause
    exit /b 1
)

REM Icon
set ICON_PATH=icon.ico
set ICON_PARAM=
if exist "%ICON_PATH%" (
    set ICON_PARAM=--icon=%ICON_PATH%
    echo Icon gefunden: %ICON_PATH%
) else (
    echo Hinweis: Kein Icon gefunden.
)

echo.
echo Starte Build-Prozess...
echo.

REM Fuehre PyInstaller mit onefile-Konfiguration aus (kein Konsolenfenster)
.venv-build\Scripts\python.exe -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name WetzlarReader ^
    %ICON_PARAM% ^
    reader_main.py

if errorlevel 1 (
    echo.
    echo =====================================
    echo  BUILD FEHLGESCHLAGEN!
    echo =====================================
    pause
    exit /b 1
)

echo.
echo =====================================
echo  BUILD ERFOLGREICH!
echo =====================================
echo.
echo Die EXE-Datei befindet sich in:
echo    dist\WetzlarReader.exe
echo.
pause
