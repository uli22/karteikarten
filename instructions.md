# 🛠️ Entwickler-Richtlinien für Wetzlar-Erkennung

## GUI-Design Prinzipien

### ✅ Button-Sichtbarkeit IMMER gewährleisten

**REGEL**: Alle Buttons müssen **immer sichtbar** sein - kein horizontales Scrollen erforderlich!

#### ❌ FALSCH - Buttons in einer langen Zeile:
```python
# NICHT SO! Buttons werden unsichtbar wenn zu viele
button_frame = ttk.Frame(parent)
button_frame.pack(fill=tk.X)

ttk.Button(button_frame, text="Button 1", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="Button 2", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="Button 3", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="Button 4", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="Button 5", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="Button 6", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="Button 7", ...).pack(side=tk.LEFT, padx=5)
# → Button 6 und 7 werden bei 1000px Fensterbreite NICHT sichtbar sein!
```

#### ✅ RICHTIG - Buttons in mehreren Zeilen:
```python
# SO IST ES GUT! Mehrere Zeilen für bessere Übersicht
button_frame = ttk.Frame(parent)
button_frame.pack(fill=tk.X)

# ZEILE 1: Haupt-Aktionen
button_row1 = ttk.Frame(button_frame)
button_row1.pack(fill=tk.X, pady=(0, 5))

ttk.Button(button_row1, text="Button 1", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_row1, text="Button 2", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_row1, text="Button 3", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_row1, text="Button 4", ...).pack(side=tk.LEFT, padx=5)

# ZEILE 2: Spezial-Aktionen
button_row2 = ttk.Frame(button_frame)
button_row2.pack(fill=tk.X)

ttk.Button(button_row2, text="Button 5", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_row2, text="Button 6", ...).pack(side=tk.LEFT, padx=5)
ttk.Button(button_row2, text="Button 7", ...).pack(side=tk.LEFT, padx=5)
# → Alle Buttons IMMER sichtbar!
```

### 📏 Maximale Anzahl Buttons pro Zeile

**Faustregel bei Standardfenster 1000px Breite:**

| Button-Textlänge | Max. Buttons/Zeile |
|------------------|-------------------|
| Kurz (5-10 Zeichen) | 8-10 Buttons |
| Mittel (10-20 Zeichen) | 5-6 Buttons |
| Lang (20-30 Zeichen) | 3-4 Buttons |

**Beispiel aus Datenbank-Tab:**
```python
# ZEILE 1: 4 mittellange Buttons (PASST)
"📊 Statistik", "📤 Export CSV", "🔄 Text-Korrektur (alle)", "🔧 Text-Korrektur (Auswahl)"

# ZEILE 2: 3 lange Buttons (PASST)
"∞ Wetzlar 00→∞ (Auswahl)", "∞ 16.1→161 (Auswahl)", "⚙️ Korrektur-Einstellungen"
```

### 🧪 Test-Checkliste vor Commit

- [ ] Fenster auf **Mindestgröße** (1000x800) setzen
- [ ] Alle Tabs öffnen und prüfen
- [ ] **Horizontales Scrollen** testen (sollte NICHT nötig sein)
- [ ] Buttons am **rechten Rand** sichtbar?
- [ ] Bei Fenstergröße 1400x800 ebenfalls testen

### 🎨 Button-Gruppierung

**Logische Gruppen** sollten in **eigenen Zeilen** stehen:

```python
# GRUPPE 1: Datenbank-Operationen
button_row1 = ttk.Frame(...)
ttk.Button(..., text="📊 Statistik", ...)
ttk.Button(..., text="📤 Export CSV", ...)

# GRUPPE 2: Text-Bearbeitung
button_row2 = ttk.Frame(...)
ttk.Button(..., text="🔄 Text-Korrektur", ...)
ttk.Button(..., text="⚙️ Einstellungen", ...)
```

---

## Weitere GUI-Richtlinien

### 🔤 Text-Korrektur Funktionen

**WICHTIG**: Alle Text-Korrektur-Buttons müssen mit `TextPostProcessor` arbeiten:

```python
from .text_postprocessor import TextPostProcessor
processor = TextPostProcessor()
corrected = processor.process(original_text, aggressive=False)
```

### 💾 Datenbank-Operationen

**Immer** `_refresh_db_list()` nach DB-Änderungen aufrufen:

```python
def _save_changes(self):
    # ... Speichern in DB ...
    self._refresh_db_list()  # WICHTIG: Liste aktualisieren!
```

### 🎯 Fenstergrößen

| Fenster | Minimalgröße | Standard |
|---------|-------------|----------|
| Hauptfenster | 1000x800 | 1400x900 |
| Settings-Dialog | 900x700 | 1000x800 |
| Edit-Dialog | 1200x700 | 1400x800 |

---

## Textextraktion und Feldverarbeitung

### 📝 Zitation-Format und Extraktionsbeginn

**WICHTIG**: Die Extraktion von Feldern (Vorname, Nachname, Stand, etc.) beginnt **IMMER erst NACH der Zitation**!

#### Zitation-Struktur

Die Zitation ist der **Beginn jedes Eintrags** und folgt diesem Format:

```
ev. Kb. Wetzlar ∞ 1566.06.04 ܂p. 98 Nr. 101
```

**Bestandteile**:
1. `ev. Kb. Wetzlar` - Kirchenbuch-Quelle
2. `∞` - Symbol für Heirat (oder `†` für Bestattung, `*` für Geburt)
3. `1566.06.04` - Datum (Jahr.Monat.Tag)
4. `܂p. 98` - Seitennummer
5. `Nr. 101` - Eintragsnummer

#### ⚠️ Häufiger Fehler

**FALSCH**: Zitations-Elemente werden als Personendaten interpretiert
```python
# ❌ PROBLEM: Datum wird als Vorname erkannt
DEBUG: Bräutigam Vorname = 1566
DEBUG: Bräutigam Nachname = 06
```

**RICHTIG**: Zitation muss vor der Feldextraktion entfernt werden
```python
# ✅ LÖSUNG: Entferne Zitation zuerst
text = remove_citation(text)  # Entfernt alles bis nach "Nr. XXX"
# Jetzt erst Felder extrahieren
vorname = extract_vorname(text)
```

#### Implementierung

Die Zitation wird bereits in der GUI korrekt extrahiert und in der DB gespeichert:
- **Feld**: `zitation` (z.B. "ev. Kb. Wetzlar ∞ 1566.06.04 ܂p. 98 Nr. 101")
- **Funktion**: `_extract_zitation()` in `gui.py`

Der verbleibende Text nach der Zitation ist der **erkannte Text** für die Feldextraktion.

---

## Code-Stil

### Python-Umgebung (verbindlich)

**REGEL**: Python-Kommandos immer in der lokalen Projekt-Umgebung `.venv` ausführen.

```powershell
D:/projects/Wetzlar-Erkennung/.venv/Scripts/python.exe <skript_oder_optionen>
```

Beispiele:

```powershell
D:/projects/Wetzlar-Erkennung/.venv/Scripts/python.exe -m py_compile src/gedcom_exporter.py
D:/projects/Wetzlar-Erkennung/.venv/Scripts/python.exe main.py
```

**Nicht verwenden**: globales `python` ohne expliziten `.venv`-Pfad.

### Import-Reihenfolge
1. Standard Library (os, sys, ...)
2. Third-Party (PIL, tkinter, ...)
3. Eigene Module (.database, .ocr_engine, ...)

### Kommentare
- **Wichtige Änderungen**: `# NEU:` oder `# GEÄNDERT:`
- **Temporäre Lösungen**: `# TODO:` oder `# FIXME:`
- **Erklärungen**: Deutsch bevorzugt

---

## Versionierung

**Vor großen Änderungen**:
1. Aktuelle `karteikarten.db` sichern
2. CSV-Export erstellen
3. Git-Commit mit aussagekräftiger Message

### GitHub (.gitignore)

Für GitHub sollen diese Ordner ignoriert werden:
- `output/`
- `test/`

### Ablage von Test- und Debug-Dateien

Künftig sollen alle neuen Test-, Debug- und Check-Dateien im Ordner `test/` angelegt werden.
Dateien mit Mustern wie `test_*.*`, `debug_*.*` und `check_*.*` gehören nicht in den Projektstamm.

---

## Reader-Anwendung (zweite, eigenständige App)

### 📖 Zweck

Eine zweite Anwendung für das reine Lesen und Durchsuchen der Datenbank.
**Kein Schreibzugriff** außer F-ID-Bearbeitung per Kontextmenü.

### 📁 Dateien

| Datei | Beschreibung |
|-------|-------------|
| `src/reader_gui.py` | `KarteikartenReader`-Klasse + `run_reader()` |
| `reader_main.py` | Einstiegspunkt (`uv run reader_main.py`) |
| `Reader_Starten.bat` | Desktop-Verknüpfung zum Starten |

### 🚫 Wichtige Regeln

- **Keine Änderungen** an `src/gui.py`, `main.py` oder anderen bestehenden Dateien.
- Der Reader ist **vollständig eigenständig** in `src/reader_gui.py`.
- Verwendet dieselbe `config.json` und `KarteikartenDB` wie Hauptanwendung.

### 🗂️ Tabs

1. **📊 Datenbank** – alle Filter/Suche aus dem Hauptprogramm-DB-Tab,  
   aber **keine** Bearbeitungs-Buttons (Text-Korrektur, Import, Export, OCR etc.)
2. **⚙️ Einstellungen** – Kirchenbuch-Laufwerk, DB-Pfad, Spaltenbreiten zurücksetzen

### 🖱️ Kontextmenü (Rechtsklick)

Nur diese Aktionen erlaubt:
- `F-ID bearbeiten` – einziger Schreibzugriff
- `Text anzeigen` – nur Lesen
- `Auswahl kopieren` – in Zwischenablage

### ▶️ Starten

```powershell
uv run reader_main.py
# oder
Reader_Starten.bat
```

---

*Letzte Aktualisierung: März 2026*
