# Wetzlar Karteikartenerkennung

Automatische Handschrifterkennung (OCR) für historische Kirchenbuchkarteien aus Wetzlar.

## Beschreibung

Dieses Projekt nutzt modernste OCR-Technologie (EasyOCR), um handgeschriebenen Text auf gescannten Karteikarten zu erkennen. Es wurde speziell für die Verarbeitung der Wetzlar Kirchenbuchkartei entwickelt.

### Features

- 📸 **Karteikarten-Viewer**: Anzeige von gescannten Karteikarten
- 🔍 **OCR-Engine**: Automatische Handschrifterkennung mit EasyOCR
- 🇩🇪 **Deutsche Sprache**: Optimiert für deutsche Handschrift
- 💾 **Export**: Speichern der erkannten Texte als TXT-Dateien
- ⌨️ **Navigation**: Einfaches Durchblättern durch die Karteikarten

## Installation

### Voraussetzungen

- Python 3.10 oder höher
- uv (Python Package Manager)

### Installation mit uv

1. Repository klonen oder öffnen
2. Dependencies installieren:

```bash
# uv installiert automatisch alle Abhängigkeiten
uv sync
```

### Tesseract OCR (optional)

Falls Sie Tesseract OCR statt EasyOCR nutzen möchten:

1. Tesseract herunterladen: https://github.com/UB-Mannheim/tesseract/wiki
2. Installieren und deutsche Sprachdaten auswählen
3. In `src/ocr_engine.py` den Parameter `use_easyocr=False` setzen

## Verwendung

### Anwendung starten

```bash
# Mit uv
uv run main.py

# Oder mit Python (nach aktivierung der venv)
python main.py
```

### Konfiguration

Die Pfade können in [main.py](main.py) angepasst werden:

```python
base_path = r"E:\Karteikarten\nextcloud"  # Pfad zu Ihren Karteikarten
start_file = "0008 Hb"  # Startdatei-Pattern
```

### Bedienung

1. **Navigation**: Nutzen Sie die "Vorherige" und "Nächste" Buttons
2. **OCR durchführen**: Klicken Sie auf "🔍 Text erkennen"
3. **Text bearbeiten**: Der erkannte Text kann im rechten Bereich bearbeitet werden
4. **Speichern**: Mit "💾 Text speichern" den Text exportieren

## Projektstruktur

```
wetzlar-karteikartenerkennung/
├── src/
│   ├── __init__.py          # Package Initialisierung
│   ├── gui.py               # Grafische Benutzeroberfläche
│   └── ocr_engine.py        # OCR-Engine (EasyOCR/Tesseract)
├── main.py                  # Haupteinstiegspunkt
├── pyproject.toml           # Projekt-Konfiguration
└── README.md                # Diese Datei
```

## Technologien

- **Python 3.13+**: Programmiersprache
- **uv**: Moderner Python Package Manager
- **EasyOCR**: Deep Learning basierte OCR für Handschrift
- **Tesseract**: Alternative OCR-Engine
- **Pillow**: Bildverarbeitung
- **tkinter**: GUI-Framework

## Hinweise

### EasyOCR

- Beim ersten Start lädt EasyOCR die deutschen Sprachmodelle herunter (~50 MB)
- Die Erkennung ist relativ langsam, aber präzise bei Handschrift
- Für bessere Performance kann GPU-Unterstützung aktiviert werden (siehe EasyOCR Dokumentation)

### Genauigkeit

Die OCR-Genauigkeit hängt ab von:
- Qualität der Scans
- Klarheit der Handschrift
- Kontrast und Beleuchtung
- Bildauflösung

Für historische Handschriften kann manuelle Nachbearbeitung erforderlich sein.

## Entwicklung

### Dependencies hinzufügen

```bash
uv add <package-name>
```

### Virtual Environment

```bash
# Aktivieren
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac
```

## Lizenz

Dieses Projekt wurde für die Verarbeitung historischer Kirchenbuchkarteien entwickelt.

## Kontakt

Für Fragen oder Probleme erstellen Sie bitte ein Issue im Repository.
