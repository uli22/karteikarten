@echo off
REM Batch-Datei zum Starten des Wetzlar Karteikarten-Readers (Leseanwendung)
REM Diese Datei kann auf den Desktop kopiert werden

echo ========================================
echo Wetzlar Karteikarten-Reader
echo ========================================
echo.

REM Wechsle ins Projektverzeichnis
cd /d "d:\projects\Wetzlar-Erkennung"

REM Prüfe ob reader_main.py existiert
if not exist "reader_main.py" (
    echo FEHLER: reader_main.py nicht gefunden!
    echo Bitte pruefen Sie den Pfad in der Batch-Datei.
    pause
    exit /b 1
)

echo Starte Reader...
echo.

REM Starte mit uv (empfohlen, wenn uv installiert ist)
uv run reader_main.py

REM Falls uv fehlschlägt, versuche Python direkt
if errorlevel 1 (
    echo.
    echo uv nicht verfuegbar, versuche Python direkt...
    python reader_main.py
)

REM Bei Fehler Fenster offen lassen
if errorlevel 1 (
    echo.
    echo ========================================
    echo FEHLER beim Starten!
    echo ========================================
    pause
)
