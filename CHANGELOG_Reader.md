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
