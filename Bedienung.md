# Bedienungsanleitung - Wetzlar Karteikartenerkennung

## Übersicht

Diese Anwendung dient zur automatischen Texterkennung (OCR) von historischen Kirchenbuch-Karteikarten aus Wetzlar (1564-1611) und deren strukturierter Speicherung in einer Datenbank.

---

## 🚀 Programmstart

```bash
uv run main.py
```

Das Programm öffnet sich mit 1400x700 Pixel Fenstergröße und zeigt zwei Tabs:
- **📸 OCR-Erkennung** - Für die Bearbeitung einzelner Karten
- **📊 Datenbank** - Zur Verwaltung und Suche gespeicherter Einträge

---

## Tab 1: 📸 OCR-Erkennung

### Verzeichnis-Auswahl

**Bildverzeichnis ändern:**
- Eingabefeld zeigt aktuelles Verzeichnis
- **📁 Ändern** - Wählt neues Verzeichnis aus
- **🔄 Neu laden** - Lädt Bilder aus aktuellem Verzeichnis neu

### Navigation

| Button | Funktion |
|--------|----------|
| **◀ Vorherige** | Zeigt die vorherige Karteikarte |
| **Nächste ▶** | Zeigt die nächste Karteikarte |
| **Karte X von Y** | Zeigt aktuelle Position |

### OCR-Einstellungen

#### OCR-Methode wählen:
- **EasyOCR (lokal)** - Standardmethode, läuft auf Ihrem PC
- **Tesseract (lokal)** - Alternative lokale OCR-Engine
- **Cloud Vision (Google)** - Google Cloud Vision API (erfordert Authentifizierung)

#### Optionen:
- ☑ **Bildvorverarbeitung** - Verbessert Bildqualität (Kontrast, Schärfe, Binarisierung)
- ☑ **Text-Korrektur** - Korrigiert typische OCR-Fehler automatisch

### Einzelne Karte verarbeiten

1. **Bild betrachten** - Links wird die aktuelle Karteikarte angezeigt
2. **🔍 Text erkennen** - Startet OCR für die aktuelle Karte
3. Erkannter Text erscheint im rechten Textfeld
4. **💾 Text speichern** - Speichert Text als .txt-Datei
5. **💽 In DB speichern** - Speichert Karte mit strukturierten Daten in Datenbank

#### Statusanzeige:
- ○ Orange: **Nicht gespeichert** - Karte noch nicht in DB
- ✓ Grün: **In Datenbank (ID: XX)** - Karte bereits gespeichert

⚠️ **Warnung**: Wenn eine Karte bereits in der DB ist, erscheint beim Speichern eine Warnung vor Überschreiben.

### Batch-Scan ⚡

**Mehrere Karten automatisch verarbeiten:**

1. **Typ** wählen (Alle / Hb / Gb / Sb)
   - **Alle** - Scannt alle Karteikarten
   - **Hb** - Nur Heiraten (z.B. "0364 Hb 1575...")
   - **Gb** - Nur Begräbnisse (z.B. "0123 Gb 1580...")
   - **Sb** - Nur Taufen (z.B. "0456 Sb 1590...")
2. **Anzahl** eingeben (z.B. 10, 20, 50)
3. **⚡ Batch-Scan** klicken
4. Bestätigungsdialog prüfen:
   - Anzahl der Karten
   - Start- und End-Position
   - OCR-Einstellungen
   - **Bildtyp-Filter** (welche Karten verarbeitet werden)
5. Mit **Ja** bestätigen

**Während der Verarbeitung:**
- Fortschrittsanzeige im Textfeld
- Anzeige des aktiven Filters
- **⏹ Abbrechen** Button oder **ESC**-Taste zum Stoppen
- Buttons deaktiviert
- Bereits vorhandene Karten werden übersprungen
- **Nicht passende Karten werden übersprungen** (bei Filter ≠ Alle)

**Nach Abschluss:**
- Zusammenfassung der Ergebnisse
- Automatische Aktualisierung der Datenbank
- Wechsel zum Tab "📊 Datenbank" empfohlen

**Beispiel:**
- Filter "Hb" + Anzahl 20 → Verarbeitet nur Heiraten-Karten
- Dateinamen wie "0364 Hb 1575..." werden erkannt
- Andere Dateien werden übersprungen

---

## Tab 2: 📊 Datenbank

### Filter und Suche

| Filter | Funktion |
|--------|----------|
| **Jahr** | Filtert nach Jahreszahl (z.B. 1564) |
| **Typ** | Filtert nach Ereignistyp (Heirat, Taufe, Begräbnis) |
| **Name** | Volltextsuche im erkannten Text |
| **🔍 Suchen** | Wendet Filter an |
| **✕ Filter löschen** | Setzt alle Filter zurück |
| **🔄 Aktualisieren** | Lädt Liste neu |

### Tabelle

**Spalten:**
- **ID** - Datenbank-ID
- **Jahr** - Extrahiertes Jahr (z.B. 1564)
- **Datum** - Formatiert als dd.mm.yyyy
- **Typ** - Heirat / Taufe / Begräbnis (∞ = Heirat)
- **Seite** - Seitenzahl (nur Nummer)
- **Nr** - Kartennummer (nur Nummer)
- **Gemeinde** - Kirchengemeinde (z.B. ev. Kb. Wetzlar)
- **Dateiname** - Name der Bilddatei
- **Erkannter Text** - Vollständiger OCR-Text

**Sortierung:**
- Klick auf Spaltenüberschrift zum Sortieren
- Standard: Jahr absteigend, dann Datum, dann Nummer

### Aktionen

#### Doppelklick auf Eintrag:
→ Öffnet Karteikarte im OCR-Tab mit geladenem Text

#### Rechtsklick-Menü:
- **Karteikarte anzeigen** - Wechselt zum OCR-Tab und zeigt Bild
- **Text anzeigen** - Öffnet Pop-up mit Text in 14px Schriftgröße
- **Datensatz löschen** - Löscht Eintrag aus DB (mit Bestätigung)

### Export und Statistik

| Button | Funktion |
|--------|----------|
| **📊 Statistik** | Zeigt Zusammenfassung (Anzahl, Zeitraum, Typen) |
| **📤 Export CSV** | Exportiert alle Daten als CSV-Datei |

---

## 🔧 Automatische Text-Korrektur

### Kirchenbuch-Header Korrektur

Die App erkennt und korrigiert automatisch:

| Erkannt | Korrigiert |
|---------|------------|
| `0015.64.11.20` | `∞ 1564.11.20` |
| `0156.04.11.26` | `∞ 1564.11.26` |
| `1564 002` | `1564 ∞ 2` |
| `p.87./.2` | `p. 87. Nr. 2` |
| `p. 87.2.` | `p. 87. Nr. 2` |
| `M. 4` | `Nr. 4` |

### Wörterbuch-Korrekturen

**Häufige OCR-Fehler werden automatisch korrigiert:**

- Rochzeit → Hochzeit
- Kochzeit → Hochzeit
- Solin → Sohn
- Sofin → Sohn
- Iochter → Tochter
- Bock ter → Tochter
- Mauwe → Maurer
- thanges → Thunges
- ... und 40+ weitere Begriffe

### Format-Normalisierung

- **Datum**: Immer `dd.mm.yyyy` (z.B. 20.11.1564)
- **Seite**: Nur Nummer ohne "p." (wird beim Parsen erkannt)
- **Nummer**: Immer `Nr. X` Format

---

## 📋 Datenbank-Struktur

**Automatisch extrahierte Felder aus dem OCR-Text:**

| Feld | Beispiel | Quelle |
|------|----------|--------|
| Kirchengemeinde | ev. Kb. Wetzlar | Aus Header |
| Ereignis-Typ | Heirat | ∞-Symbol |
| Jahr | 1564 | Aus Datum |
| Datum | 20.11.1564 | Aus Header |
| Seite | 87 | Nach "p." |
| Nummer | 2 | Nach "Nr." |
| Erkannter Text | Volltext | OCR-Ergebnis |
| OCR-Methode | easyocr | Verwendete Engine |

**Parsing-Beispiel:**
```
Input:  ev. Kb. Wetzlar ∞ 1564.11.20 p. 87. Nr. 2 Jacob Mebess...
Output: Gemeinde=ev. Kb. Wetzlar, Typ=Heirat, Datum=20.11.1564, Seite=87, Nr=2
```

---

## 🔐 Google Cloud Vision Setup (Optional)

Falls Sie Cloud Vision nutzen möchten:

### 1. Authentifizierung
```bash
gcloud auth application-default login
```

### 2. Im Programm
- OCR-Methode: **Cloud Vision (Google)** wählen
- Optional: **📁 Credentials** Button für Service Account Key

Siehe [CLOUD_VISION_SETUP.md](CLOUD_VISION_SETUP.md) für Details.

---

## 💾 Daten-Sicherung

**Datenbank-Datei:**
```
karteikarten.db
```

**Backup erstellen:**
1. Tab "📊 Datenbank" öffnen
2. **📤 Export CSV** klicken
3. Datei speichern (z.B. `backup_2026-01-09.csv`)

**Tipp**: Regelmäßig die `karteikarten.db` Datei sichern!

---

## ⚙️ Tipps und Best Practices

### Für beste OCR-Ergebnisse:

1. ✅ **Bildvorverarbeitung** aktiviert lassen
2. ✅ **Text-Korrektur** aktiviert lassen
3. 📸 Gute Bildqualität (mindestens 300 DPI)
4. 🔆 Gleichmäßige Beleuchtung

### Workflow-Empfehlung:

**Einzelne Karte prüfen:**
1. OCR durchführen
2. Text kontrollieren
3. Bei Bedarf manuell korrigieren
4. In DB speichern

**Große Mengen:**
1. **Verzeichnis** mit den gewünschten Karten auswählen
2. **Bildtyp-Filter** setzen (z.B. nur Hb-Karten)
3. Einstellungen testen mit 2-3 Karten
4. Batch-Scan mit 10-20 Karten starten
5. Ergebnisse in Datenbank prüfen
6. Bei guter Qualität: Größere Batches (50+)

**Verschiedene Bildtypen getrennt verarbeiten:**
1. Filter auf "Hb" → Batch-Scan → alle Heiraten
2. Filter auf "Gb" → Batch-Scan → alle Begräbnisse  
3. Filter auf "Sb" → Batch-Scan → alle Taufen

### Fehlerbehandlung:

**OCR-Text fehlerhaft?**
- Text manuell im Textfeld korrigieren
- Dann "💽 In DB speichern"
- Oder andere OCR-Methode probieren

**Karte bereits in DB?**
- Status-Anzeige beachten (✓ Grün)
- Bei Überschreiben: Warnung bestätigen
- Oder aus DB-Tab mit Rechtsklick löschen und neu scannen

---

## 🐛 Problemlösung

### OCR Engine startet nicht
→ Prüfen Sie die Installation mit `uv sync`

### Cloud Vision Fehler
→ `gcloud auth application-default login` erneut ausführen

### Batch-Scan bleibt hängen
→ Programm neu starten, bereits gespeicherte Karten werden übersprungen

### Datenbank-Fehler
→ Prüfen Sie ob `karteikarten.db` schreibgeschützt ist

---

## � XLSX-Import (Taufen-Karteikarten aus vorhandener Erfassung)

Mit dem XLSX-Import können bereits erfasste Kirchenbuch-Daten (z.B. aus einer Excel-Tabelle)
direkt in die Datenbank übernommen werden, ohne dass eine OCR-Erkennung notwendig ist.

### Voraussetzungen für die XLSX-Datei

Die Datei muss in der ersten Zeile folgende Spaltenköpfe enthalten (exakte Schreibweise):

| Spalte | Inhalt |
|--------|--------|
| `Karteikarte` | Dateiname des Karteikarten-Bildes (Schlüsselspalte!) |
| `Jahr` | Taufjahr |
| `Datum Taufe` | Taufdatum (DD.MM.YYYY) |
| `Datum Geburt` | Geburtsdatum (DD.MM.YYYY, optional wenn Taufdatum vorhanden) |
| `Seite` | Seitenzahl im Kirchenbuch |
| `Nummer` | Laufende Nummer auf der Seite |
| `Karteikartentext` | Inhalt der Karteikarte (OCR-Text) |
| `Vorname Täufling` | Vorname des Täuflings |
| `Klarname` | Nachname (= Vatersnachname) |
| `Vorname Vater` | Vorname des Vaters |
| `Geschlecht Täufling` | `m` oder `w` → wird zu `Sohn`/`Tochter` |
| `Kirchenbucheintrag` | Transkription des Kirchenbucheintrags |
| `Vorname Mutter` | Vorname der Mutter (optional) |

### Schritt 1 – Karteikarten ohne OCR in die Datenbank registrieren

Bevor der XLSX-Import laufen kann, müssen die Bilddateien der Karteikarten in der Datenbank
bekannt sein. Falls sie noch nicht per Batch-Scan erfasst wurden:

1. Im Tab **📸 OCR-Erkennung** den Ordner mit den Karteikarten-Bildern öffnen
   (**📁 Ändern** → Ordner wählen → **🔄 Neu laden**).
2. Bildtyp-Filter setzen (z.B. **Gb** für Taufbuch-Karteikarten).
3. **📋 Registrieren (ohne OCR)** klicken.
4. Bestätigen – alle passenden Dateien werden als leere Einträge in die DB eingetragen.
   Bereits vorhandene Einträge werden automatisch übersprungen.
5. Am Ende erscheint eine Zusammenfassung: *Neu eingetragen / Bereits vorhanden / Fehler*.

> **Hinweis:** Dieser Schritt ist nur einmalig nötig. Bei einem erneuten Import werden
> bereits registrierte Dateien übersprungen (kein Überschreiben).

### Schritt 2 – XLSX importieren

1. Im Tab **📊 Datenbank** auf **📥 Import XLSX** klicken.
2. XLSX-Datei auswählen und Bestätigung bestätigen.
3. Der Abgleich erfolgt ausschließlich über den Dateinamen:  
   XLSX-Spalte `Karteikarte` ↔ DB-Feld `dateiname`.  
   Varianten wie `_erf.jpg`, `_erf` (ohne Endung) oder ohne Suffix werden automatisch
   als gleich erkannt.
4. Nach dem Import erscheint eine Zusammenfassung:
   - **Aktualisiert** – Datensätze, bei denen ein Match gefunden wurde
   - **Nicht gefunden** – Einträge ohne passenden DB-Datensatz
   - **Fehler** – technische Verarbeitungsfehler

### Nicht gefundene Einträge analysieren

Falls Einträge nicht zugeordnet werden konnten, erscheint ein Dialog mit dem Angebot,
die Liste der nicht gematchten Dateinamen zu öffnen. Sie wird zusätzlich gespeichert unter:

```
output/xlsx_not_found.txt
```

Typische Ursachen:
- Bilddatei liegt im falschen Ordner oder wurde noch nicht registriert (→ Schritt 1 wiederholen)
- Dateiname in der XLSX weicht deutlich ab (andere Nummerierung, anderes Trennzeichen)
- Datei existiert physisch nicht auf dem Rechner

### Was wird beim Import übernommen?

Beim XLSX-Import werden alle Felder vollständig **überschrieben** (außer `notiz`/F-ID und `gramps`):

| DB-Feld | Quelle |
|---------|--------|
| `kirchengemeinde` | Fest: `ev. Kb. Wetzlar` |
| `ereignis_typ` | Fest: `Taufe` |
| `vorname` | `Vorname Täufling` |
| `nachname` | `Klarname` |
| `partner` | `Vorname Vater` |
| `mutter_vorname` | `Vorname Mutter` |
| `stand` | `Sohn`/`Tochter` aus `Geschlecht Täufling` |
| `todestag` | Taufdatum (YYYY.MM.DD) |
| `datum_geburt` | Taufdatum, sonst Geburtsdatum |
| `kirchenbuchtext` | `Kirchenbucheintrag` |
| `erkannter_text` | `Karteikartentext` |

---

## �📞 Weitere Informationen

- **Projekt-Dokumentation**: [README.md](README.md)
- **Cloud Vision Setup**: [CLOUD_VISION_SETUP.md](CLOUD_VISION_SETUP.md)
- **Python-Umgebung**: Verwaltet mit `uv`

---

**Version**: 1.0  
**Datum**: Januar 2026  
**Projekt**: Wetzlar Kirchenbuch-Kartei Digitalisierung (1564-1611)
