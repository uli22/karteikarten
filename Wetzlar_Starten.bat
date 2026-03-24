@echo off
REM Batch-Datei zum Starten der Wetzlar Karteikartenerkennung
REM Diese Datei kann auf den Desktop kopiert werden

echo ========================================
echo Wetzlar Karteikartenerkennung
echo ========================================
echo.

REM Wechsle ins Projektverzeichnis
cd /d "d:\projects\Wetzlar-Erkennung"

REM Prüfe ob main.py existiert
if not exist "main.py" (
    echo FEHLER: main.py nicht gefunden!
    echo Bitte pruefen Sie den Pfad in der Batch-Datei.
    pause
    exit /b 1
)

echo Starte Anwendung...
echo.

REM Starte mit uv (empfohlen, wenn uv installiert ist)
uv run main.py

REM Falls uv fehlschlägt, versuche Python direkt
if errorlevel 1 (
    echo.
    echo uv nicht verfuegbar, versuche Python direkt...
    python main.py
)

REM Bei Fehler Fenster offen lassen
if errorlevel 1 (
    echo.
    echo ========================================
    echo FEHLER beim Starten!
    echo ========================================
    pause
)
