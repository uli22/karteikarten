# WetzlarReader – Änderungen zwischen v0.4.1 und v0.4.6

## Neue Features in v0.4.6

### 🌐 Online-Synchronisation
- Vollständiges Sync-System mit MySQL- und API-Modus
- Hintergrund-Sync-Thread mit konfigurierbarem Intervall
- "Vollabgleich erzwingen" und "DB löschen & neu laden"
- API-Endpoint-Validierung mit URL-Normalisierung
- Verbindungstest-Funktion

### 🔍 Erweiterte Suchfilter
- Partner-Vorname, Nachname, Braut-Vorname, Braut-Nachname (zusätzlich zur Textsuche)
- Regex-Unterstützung für alle Suchfelder
- "inf ausblenden" Checkbox

### 💾 Full Backup & Restore
- 🔒 Full Backup (Karteikarten + Sync-Queue)
- ↩️ Restore (Wiederherstellung aus Backup-CSVs)

### ✅ Kommentar- & Erledigt-System
- Kommentar-Feld mit eigenem Bearbeitungsdialog
- Erledigt-Checkbox mit visuellem Tagging (rot/grün)
- Farbliche Hervorhebung in der Treeview

### 🔎 Verbesserte Bildanzeige
- Zoom (Mausrad) und Pan (Drag)
- IrfanView-Integration
- Automatisches Scrollen zu rechter Seite bei ungeraden Seitenzahlen

### 📂 Kirchenbuch-Basisverzeichnis
- Einstellung für umgezogene Kirchenbuch-Ordner (kirchenbuch_base_path)
- Pfad-Relocation-Logik

### 📊 Erweiterte Statistik
- Kirchenbücher je Typ mit ISO-Datumsbereich
- F-ID-Statistik (F-/I-Präfix-Zählung)

### 📏 Spaltenbreiten-Persistenz
- Automatisches Speichern/Wiederherstellen von Spaltenbreiten
- Reset-Button

### 📄 GEDCOM-Export
- Zwei Dialekte: GRAMPS und TNG
- Export aus dem Kontextmenü

### 💾 Datenbank-Wechsel
- DB zur Laufzeit laden/wechseln ("💾 DB laden")

---

## Neuerungen im Reader v0.4.8

### 🔐 SSL/TLS auf certifi + requests umgestellt
- **requests** statt `urllib.request` für alle HTTP-API-Aufrufe (Sync & Verbindungstest)
- **certifi** als CA-Bundle: 118 Zertifikate statt 97 (Windows Store)
- Plattformunabhängig: funktioniert auch ohne Windows Certificate Store (Wine, Docker, Linux)
- Explizite SSL-Diagnose mit certifi-Pfad in der Verbindungstest-Anzeige
- `certifi` und `requests` als explizite Projekt-Dependencies in `pyproject.toml`

### 🛡️ Verbesserte SSL-Fehlerbehandlung
- Detaillierte Fehlermeldungen bei SSL/Certificate-Errors
- Unterscheidung zwischen `SSLError`, `ConnectionError`, `Timeout` und `HTTPError`
- Hinweis auf mögliche Ursachen (Antivirus, Proxy, veraltete Zertifikate)

### 🔧 Technische Verbesserungen
- `online_sync.py`: Imports von `certifi`/`requests` statt `urllib.error`/`urllib.request`
- `reader_gui.py`: Verbindungstest nutzt `requests.post()` mit `verify=certifi.where()`
- `pyproject.toml`: `certifi>=2025.0.0` und `requests>=2.32.0` als Abhängigkeiten
- Build-Größe: 34,6 MB

---

## Neuerungen im Reader v0.4.9

### 🎨 Verbesserte Farbmarkierung
- `has_kirchenbuchtext`: Farbe auf kontrastreiches Dunkelgelb (`#e6c300`) geändert
- `has_kirchenbuchtext` hat jetzt höchste Priorität (überschreibt alle anderen Tags)
- Bessere Unterscheidbarkeit zwischen F-ID (grün), Gramps (blau) und Kirchenbuchtext (gelb)

### 📖 Kirchenbuch-Quellen
- `Wetzlar KbHb 1608-1693 lutherisch` korrigiert (Jahresbereichsanpassung für Heiraten ab 1607)

---

## Neuerungen im Reader v0.4.10

### 🔍 Verbesserte Bildersuche bei umgezogenen Ordnern
- `_resolve_relocated_path()` erweitert: erkennt kurze Typ-Ordner (`Hb`, `Gb`, `Sb`) und ersetzt sie durch den langen Ordnernamen (`Wetzlar Kirchenbuchkartei Hb 1735-1746`)
- Parent-Jahresbereich wird automatisch aus dem Dateinamen korrigiert (falls in der DB falsch)
- Fallback-Suche: wenn alle Kandidaten fehlschlagen, wird nach dem Dateinamen im Basisordner gesucht
- Dadurch werden Karteikarten auch auf Rechnern mit anderer Ordnerstruktur gefunden

### 📖 Kirchenbuch-Quellen
- `Wetzlar KbHb 1608-1693 lutherisch` korrigiert (Jahresbereichsanpassung für Heiraten ab 1607)
