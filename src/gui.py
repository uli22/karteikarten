"""Grafische Benutzeroberfläche für die Karteikartenerkennung."""

import csv
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from PIL import Image, ImageTk

from .config import get_config
from .database import KarteikartenDB
from .extraction_lists import (ANREDEN, ARTIKEL, BERUFE, BERUFS_EINLEITUNG,
                               IGNORIERE_WOERTER, KEINE_BERUFE,
                               MAENNLICHE_VORNAMEN, ORTS_PRAEPOSITIONEN,
                               PARTNER_STÄNDE, SOURCES, STAND_MAPPING,
                               STAND_PRAEFIXE, STAND_SYNONYME,
                               WEIBLICHE_VORNAMEN)
from .gedcom_exporter import GedcomExporter
from .ocr_engine import OCREngine


class KarteikartenGUI:
    def _standardize_p_nr_selected(self):
        """Standardisiert p./Nr.-Angaben NUR AM ANFANG des Feldes 'Erkannter Text' für die ausgewählten Einträge."""
        import re
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return

        count = len(selection)
        if not messagebox.askyesno(
            "p/Nr. standardisieren",
            f"Möchten Sie die Standardisierung auf {count} Einträge anwenden?\n\n"
            f"Varianten wie 'p. 95m. 24', 'p.118 n.1', 'Nr. .14' werden vereinheitlicht (nur am Anfang des Feldes).\n"
            f"Die alten Texte werden überschrieben."):
            return

        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        cursor = self.db.conn.cursor()
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            try:
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    new_text = original_text
                    # Nur den Anfang (z.B. die ersten 60 Zeichen oder bis zum ersten Punkt nach dem Jahr) ersetzen
                    # Suche typischen Anfang: ev. Kb. Wetzlar ... <Datum>. ...
                    # Wir nehmen die ersten 60 Zeichen oder bis zum ersten Leerzeichen nach dem Jahr
                    match = re.match(r"(.{0,60}?)([\s\S]*)", original_text)
                    if match:
                        prefix = match.group(1)
                        rest = match.group(2)
                        # Ersetzungen NUR im prefix
                        pfx = prefix
                        pfx = re.sub(r"p\.\s*(\d+)m\.\s*(\d+)", r"p. \1 Nr. \2", pfx)
                        pfx = re.sub(r"p\.?\s*(\d+)n\.\s*(\d+)", r"p. \1 Nr. \2", pfx)
                        pfx = re.sub(r"p\.?\s*(\d+)\.?n\.\s*(\d+)", r"p. \1 Nr. \2", pfx)
                        pfx = re.sub(r"(?<!Nr\.)n\.\s*(\d+)", r"Nr. \1", pfx)
                        pfx = re.sub(r"(?<!Nr\.)m\.\s*(\d+)", r"Nr. \1", pfx)
                        pfx = re.sub(r"Nr\.\s*\.\s*(\d+)", r"Nr. \1", pfx)
                        pfx = re.sub(r"p\.?\s*(\d+)\s*Nr\.?\s*(\d+)", r"p. \1 Nr. \2", pfx)
                        new_text = pfx + rest
                    if new_text == original_text:
                        keine_aenderung += 1
                        continue
                    self.db.save_karteikarte(
                        dateiname=dateiname,
                        dateipfad=dateipfad,
                        erkannter_text=new_text,
                        ocr_methode="standardize_p_nr"
                    )
                    erfolge += 1
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        self._refresh_db_list()
        messagebox.showinfo(
            "Fertig",
            f"Standardisierung abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )
    """GUI für die Anzeige und Erkennung von Karteikarten."""
    
    def __init__(self, root: tk.Tk, base_path: str, start_file: str):
        """
        Initialisiert die GUI.
        
        Args:
            root: Tkinter Root-Fenster
            base_path: Basispfad zu den Karteikarten
            start_file: Startdatei (z.B. "0008 Hb...")
        """
        self.root = root
        self.root.title("Wetzlar Karteikartenerkennung")
        self.root.geometry("1000x800")
        
        # Config laden
        self.config = get_config()
        
        configured_base_path = self.config.image_base_path.strip() if self.config.image_base_path else ""
        active_base_path = configured_base_path if configured_base_path else base_path
        self.base_path = Path(active_base_path)
        self.image_folder_var = tk.StringVar(value=str(active_base_path))
        if not configured_base_path:
            self.config.image_base_path = str(self.base_path)
        self.start_file = start_file
        self.current_index = 0
        self.image_files: List[Path] = []
        self.current_image = None
        self.photo_image = None
        
        # OCR Engine initialisieren (Standard: EasyOCR)
        self.ocr_engine = None
        self.ocr_method = 'easyocr'
        self.credentials_path = None
        
        # Datenbank initialisieren (konfigurierbarer Pfad mit robusten Fallbacks)
        db_path = self._resolve_initial_db_path()
        self.db = KarteikartenDB(str(db_path))
        self.active_db_path = str(Path(db_path).resolve())
        print(f"Aktive DB: {self.active_db_path}")
        if not (self.config.db_path or "").strip():
            self.config.db_path = self.active_db_path
        
        # Aktueller DB-Record (None = nicht gespeichert, ID = bereits in DB)
        self.current_db_record_id = None
        
        # Sortierrichtung pro Spalte (True = aufsteigend, False = absteigend)
        self.sort_reverse = {}
        
        # Zuletzt sortierte Spalte
        self._last_sorted_column = None
        
        # Progressbar für Batch-Operationen
        self.db_progress = None
        
        # Batch-Scan Abbruch-Flag
        self.batch_scan_cancelled = False
        
        # GUI aufbauen
        self._create_widgets()
        self._load_image_files()
        
        if self.image_files:
            self._display_current_card()

    def _resolve_initial_db_path(self) -> Path:
        """Ermittelt den initialen DB-Pfad mit Fallbacks für Dev- und EXE-Betrieb."""
        configured_path = (self.config.db_path or "").strip()
        if configured_path:
            configured = Path(configured_path).expanduser()
            if configured.exists():
                return configured
            # Wenn explizit konfiguriert, verwende ihn auch wenn die Datei noch nicht existiert.
            return configured

        db_name = "karteikarten.db"
        candidates: List[Path] = []

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend([
                exe_dir.parent / db_name,
                exe_dir / db_name,
                Path.cwd() / db_name,
            ])
        else:
            project_root = Path(__file__).resolve().parent.parent
            candidates.extend([
                project_root / db_name,
                Path.cwd() / db_name,
            ])

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0]

    def _switch_database(self, new_db_path: Path) -> None:
        """Schaltet die aktive Datenbank um und aktualisiert abhängige UI-Elemente."""
        new_db_path = new_db_path.expanduser().resolve()

        new_db = KarteikartenDB(str(new_db_path))

        old_conn = getattr(self.db, "conn", None)
        if old_conn:
            try:
                old_conn.close()
            except Exception:
                pass

        self.db = new_db
        self.active_db_path = str(new_db_path)
        self.current_db_record_id = None

        if hasattr(self, "db_path_info_label"):
            self.db_path_info_label.config(text=f"Aktive DB: {self.active_db_path}")

        if hasattr(self, "tree"):
            self._refresh_db_list()

        if self.current_image:
            self._check_db_status()

    def _extract_marriage_fields(self, text: str) -> dict:
        """
        Extrahiert Felder aus einem Heiratseintrag.
        
        Struktur:
        1. Zitation: ev. Kb. Wetzlar ∞ YYYY.MM.DD p. X Nr. Y
        2. Bräutigam: [Vorname] [Nachname] [Vater-Vorname] [Vater-Nachname]s, [Beruf des Vaters], [Ort], [Status]
        3. Trenner: "und", "undt", "mitt"
        4. Braut: [Anrede] [Vorname(n)], [Vater-Vorname] [Vater-Nachname]s [Beruf], [Ort], [Status]
        5. Ende: "hielten Hochzeit", "copulirt", etc.
        
        Returns:
            Dict mit extrahierten Feldern
        """
        import re
        
        result = {
            'vorname': None,  # Bräutigam Vorname
            'nachname': None,  # Bräutigam Nachname
            'partner': None,  # Braut Vorname(n)
            'beruf': None,
            'ort': None,  # Bräutigam Ort
            'stand': None,  # Braut Stand (z.B. "gewesene hausfrau" = Witwe)
            'braeutigam_stand': None,  # Bräutigam Stand
            'braeutigam_vater': None,
            'braut_vater': None,
            'braut_nachname': None,
            'braut_ort': None,
            'todestag': None,  # Hochzeitsdatum im Format YYYY.MM.DD (verwendet dasselbe Feld wie Todestag)
            'seite': None,
            'nummer': None,
        }
        
        # 1. Zitation extrahieren (verwendet das gleiche Pattern wie _format_citation_selected)
        # Pattern: (ev. Kb. Wetzlar)? ∞ YYYY.MM.DD p. Seite Nr. Nummer
        # Flexibel für verschiedene Schreibweisen (mit/ohne Punkte, mit/ohne Leerzeichen)
        # P oder p, mit optionalem Komma vor Nr.
        zitation_pattern = r"^\s*(ev\.?\s*Kb\.?\s*Wetzlar)\s*([⚰∞\u26B0])\s*(\d{4})[\.\s]*(\d{1,2})[\.\s]*(\d{1,2})\.?\s*[Pp]\.?\s*(\d+)\.?\s*,?\s*Nr\.?\s*(\d+)\.?\s*"
        
        # KEINE Stopwörter mehr - wir analysieren den gesamten Text und nutzen nur den Trenner
        # Die alte Stopword-Logik schnitt den Text zu früh ab (vor "mitt"/"und")
        
        # Extrahiere Zitation vom Anfang
        print(f"DEBUG Heirat: Eingabe-Text = {repr(text[:150])}")
        m = re.match(zitation_pattern, text, re.IGNORECASE)
        if m:
            # Nach der Zitation beginnt der relevante Text
            after_zitation = text[m.end():].strip()
            # Hochzeitsdatum extrahieren (Gruppen 3, 4, 5 = Jahr, Monat, Tag)
            jahr = m.group(3)
            monat = m.group(4).zfill(2)  # Führende 0 hinzufügen falls nötig
            tag = m.group(5).zfill(2)    # Führende 0 hinzufügen falls nötig
            result['todestag'] = f"{jahr}.{monat}.{tag}"  # Verwende todestag-Feld für Hochzeitsdatum
            # Seite extrahieren (Gruppe 6)
            if m.group(6):
                result['seite'] = int(m.group(6))
            # Nummer extrahieren (Gruppe 7)
            if m.group(7):
                result['nummer'] = int(m.group(7))
            print(f"DEBUG Heirat: Zitation erkannt bis Position {m.end()}")
            print(f"DEBUG Heirat: Zitation war: {repr(text[:m.end()])}")
            print(f"DEBUG Heirat: Hochzeitsdatum (in todestag) = {result['todestag']}")
            print(f"DEBUG Heirat: Seite = {result.get('seite')}, Nummer = {result.get('nummer')}")
            print(f"DEBUG Heirat: Text nach Zitation: {repr(after_zitation[:100])}")
        else:
            # Kein Match - versuche ohne Prefix
            after_zitation = text.strip()
            print(f"DEBUG Heirat: WARNUNG - Keine Zitation erkannt, verwende vollen Text")
        
        # Verwende den gesamten Text nach der Zitation (kein Stopword-Filter mehr)
        relevant_text = after_zitation
        
        print(f"DEBUG Heirat: relevant_text (nach Stopword-Filter) = {repr(relevant_text[:200])}")
        
        # Splitte in Wörter - ignoriere alle Satzzeichen (Punkte, Kommas, Semikolons etc.)
        # Ersetze alle Satzzeichen durch Leerzeichen
        text_clean = relevant_text
        for char in '.,;:!?()[]{}"\'-+':
            text_clean = text_clean.replace(char, ' ')
        
        # Splitte an Leerzeichen und filtere leere Strings
        words = [w.strip() for w in text_clean.split() if w.strip()]
        
        # Entferne Zitations-Wörter die versehentlich mit durch sind
        zitation_woerter = ['ev', 'Kb', 'kb', 'Wetzlar', 'p', 'Nr', 'nr', '∞']
        words = [w for w in words if w not in zitation_woerter and w.lower() not in [z.lower() for z in zitation_woerter]]
        
        # Entferne reine Zahlen am Anfang (Reste aus Zitation: Jahr, Monat, Tag, Seite, Nummer)
        # Filtere solange bis erstes Wort kein reines Zahlen-Wort ist
        while words and words[0].isdigit():
            print(f"DEBUG Heirat: Filtere Zitations-Zahl am Anfang: {words[0]}")
            words = words[1:]
        
        # Trunkiere words beim ersten "copul*"-Wort (copuliert/copulirt = Hochzeit vollzogen,
        # danach kommen keine relevanten Namensdaten mehr)
        copul_idx = next((i for i, w in enumerate(words) if w.lower().startswith('copul')), None)
        if copul_idx is not None:
            print(f"DEBUG Heirat: 'copul*' bei Position {copul_idx} ('{words[copul_idx]}') - trunkiere words")
            words = words[:copul_idx]
        
        print(f"DEBUG Heirat: words (nach Filter) = {words[:30]}")
        
        # Hilfsfunktion: Entferne Genitiv-Endungen
        def remove_genitiv_s(name):
            """Entfernt Genitiv-Endungen von Nachnamen (Zahns → Zahn, Baussen → Bauss)"""
            if not name or len(name) <= 2:
                return name
            # Genitiv-Endungen: -s, -en, -es
            if name.endswith('en') and len(name) > 3:
                # Baussen → Bauss
                return name[:-2]
            elif name.endswith('es') and len(name) > 3:
                # Schmidtes → Schmidt
                return name[:-2]
            elif name.endswith('s'):
                # Prüfe ob es wirklich Genitiv ist (nicht bei Namen wie "Peters", "Jonas")
                # Einfache Heuristik: Wenn vorletzter Buchstabe Konsonant, dann Genitiv
                if name[-2] not in 'aeiouäöü':
                    return name[:-1]
            return name
        
        # Listen laden
        weibliche_vornamen = WEIBLICHE_VORNAMEN
        maennliche_vornamen = MAENNLICHE_VORNAMEN
        anreden = ANREDEN
        ignoriere_woerter = IGNORIERE_WOERTER

        # OCR-robuste Namensnormalisierung fuer Vergleiche (z.B. Hanẞ vs Hanß)
        def norm_name_token(token: str) -> str:
            return str(token).strip().replace('ẞ', 'ß').lower()

        maennliche_vornamen_norm = {norm_name_token(v) for v in maennliche_vornamen}
        
        # Erweitere ignore-Liste um typische Füllwörter
        # NICHT Sohn/Tochter - das sind Stand-Angaben!
        ignore_extended = set(ignoriere_woerter) | {
            'gewesener', 'gewesenen', 'gewesene',
            'hinterlassener', 'hinterlassenen', 'hinterlassene', 'hinterl',
            'ehel', 'ehelicher', 'ehelichen', 'eheliche',
            'hielten', 'hilten', 'hilt', 'hochzeit'
        }
        
        # Suche Trenner-Position (und, undt, mitt)
        # Strategie: Finde das "und" VOR "Jungfr." oder einem weiblichen Vornamen
        # da "Wittwer und Bürger" Teil des Bräutigams ist
        trenner_pos = -1
        trenner_woerter = ['und', 'undt', 'mitt', 'mit', 'cum']
        
        # Suche zuerst nach "Jungfr.", "Jfr." o.ä. oder weiblichen Vornamen
        # Hinweis: Punkte wurden bereits entfernt, daher "Jfr." → "jfr" im words-Array
        braut_start_keywords = ['jungfr', 'jungfrau', 'jfr'] + [v.lower() for v in weibliche_vornamen]
        braut_indicator_pos = -1
        
        for i, w in enumerate(words):
            if w.lower() in braut_start_keywords:
                braut_indicator_pos = i
                print(f"DEBUG Heirat: Braut-Indikator '{w}' gefunden bei Position {i}")
                break
        
        # Wenn Braut-Indikator gefunden, suche rückwärts nach dem letzten Trenner davor
        if braut_indicator_pos != -1:
            for i in range(braut_indicator_pos - 1, -1, -1):
                if words[i].lower() in trenner_woerter:
                    trenner_pos = i
                    print(f"DEBUG Heirat: Trenner '{words[i]}' gefunden bei Position {i} (vor Braut-Indikator)")
                    break
        
        # Fallback: Suche einfach das erste "und"
        if trenner_pos == -1:
            for i, w in enumerate(words):
                if w.lower() in trenner_woerter:
                    trenner_pos = i
                    print(f"DEBUG Heirat: Trenner '{w}' gefunden bei Position {i} (Fallback)")
                    break
        
        # Spezialfall: "Son" oder "Sohn" + weiblicher Vorname = impliziter Trenner
        # Beispiel: "Hanssen Son Elsbeth" → Trenner vor "Elsbeth"
        if trenner_pos == -1 and braut_indicator_pos != -1:
            for i in range(braut_indicator_pos - 1, -1, -1):
                if words[i].lower() in ['son', 'sohn', 'stiffson']:
                    # Prüfe ob danach (bei i+1) ein weiblicher Vorname folgt
                    if i + 1 < len(words) and words[i + 1].lower() in braut_start_keywords:
                        trenner_pos = i + 1  # Trenne VOR dem weiblichen Vornamen
                        print(f"DEBUG Heirat: Impliziter Trenner nach '{words[i]}' bei Position {i+1} (Sohn-Stand + weiblicher Vorname)")
                        break
        
        # Letzter Fallback: Wenn immer noch kein Trenner gefunden, aber Braut-Indikator existiert
        # → Trenne direkt vor dem Braut-Indikator
        if trenner_pos == -1 and braut_indicator_pos != -1:
            trenner_pos = braut_indicator_pos
            print(f"DEBUG Heirat: Kein Trenner-Wort gefunden, trenne vor Braut-Indikator bei Position {braut_indicator_pos}")
        
        if trenner_pos == -1:
            print("DEBUG Heirat: KEIN Trenner gefunden und kein Braut-Indikator!")
            return result
        
        # Teil 1: Bräutigam (vor Trenner)
        brautigam_words = words[:trenner_pos]
        print(f"DEBUG Heirat: brautigam_words = {brautigam_words}")
        
        # Teil 2: Braut (nach Trenner)
        # Wenn trenner_pos auf einen Trenner zeigt (und, undt), überspringe ihn
        # Wenn trenner_pos auf den Braut-Indikator zeigt, starte dort (nicht überspringen)
        if trenner_pos < len(words) and words[trenner_pos].lower() in trenner_woerter:
            braut_words = words[trenner_pos + 1:]  # Trenner überspringen
        else:
            braut_words = words[trenner_pos:]  # Ab Braut-Indikator
        print(f"DEBUG Heirat: braut_words = {braut_words}")
        
        # === Bräutigam-Teil analysieren ===
        # Struktur: [Vorname(n)] [Nachname] [Vater-Vorname] [Vater-Nachname]s ...
        # Beispiel: Johann Peter verdrieß, Christoff verdriessen
        
        # ZUERST: Erkenne Berufe um zu vermeiden, dass Berufs-Wörter als Vater-Namen interpretiert werden
        beruf_word_indices = set()  # Speichere Indizes der Berufs-Wörter
        
        # Prüfe ob ein Beruf aus BERUFE vorhanden ist (auch mehrwortig wie "Not. Caes. publ.")
        brautigam_text = ' '.join(brautigam_words)
        for beruf_kandidat in BERUFE:
            if beruf_kandidat in brautigam_text:
                # Finde die Position und Wort-Indizes
                result['beruf'] = beruf_kandidat
                # Finde welche Wörter zu diesem Beruf gehören
                beruf_woerter = beruf_kandidat.split()
                for i in range(len(brautigam_words) - len(beruf_woerter) + 1):
                    if ' '.join(brautigam_words[i:i+len(beruf_woerter)]) == beruf_kandidat:
                        beruf_word_indices = set(range(i, i + len(beruf_woerter)))
                        print(f"DEBUG Heirat: Beruf = {result['beruf']} bei Indizes {list(beruf_word_indices)}")
                        break
                break
        
        idx = 0
        # Überspringe Anreden und Füllwörter
        while idx < len(brautigam_words) and (brautigam_words[idx].lower() in anreden or brautigam_words[idx] in ignore_extended):
            idx += 1
        
        # Sammle Bräutigam Vornamen (kann Doppelname sein: Johann Peter)
        vorname_parts = []
        while idx < len(brautigam_words) and brautigam_words[idx] in maennliche_vornamen:
            vorname_parts.append(brautigam_words[idx])
            idx += 1
        
        # Wenn keine bekannten Vornamen gefunden, nimm erstes Wort
        if not vorname_parts and idx < len(brautigam_words):
            vorname_parts.append(brautigam_words[idx])
            idx += 1
        
        if vorname_parts:
            result['vorname'] = ' '.join(vorname_parts)
            print(f"DEBUG Heirat: Bräutigam Vorname = {result['vorname']}")
        
        # Überspringe Füllwörter
        while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
            idx += 1
        
        # Nächstes Wort: Könnte Nachname oder Vater-Vorname sein
        if idx < len(brautigam_words):
            word_next = brautigam_words[idx]
            
            # Stand-Wörter für Bräutigam (zur Mustererkennung)
            brautigam_stand_woerter = ['sohn', 'söhnlein', 'sohnlein', 'son', 'wittwer', 'wittiber', 'witwer']
            
            # Prüfe ob es ein bekannter männlicher Vorname ist (dann ist es Vater-Vorname)
            if word_next in maennliche_vornamen:
                # Das ist der Vater-Vorname
                result['braeutigam_vater'] = word_next
                print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                idx += 1
                
                # Überspringe Füllwörter
                while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                    idx += 1
                
                # Nächstes Wort sollte Vater-Nachname (Genitiv) sein
                if idx < len(brautigam_words):
                    result['nachname'] = remove_genitiv_s(brautigam_words[idx])
                    print(f"DEBUG Heirat: Bräutigam Nachname (von Vater) = {result['nachname']}")
                    idx += 1
            else:
                # Prüfe Muster: [Nachname] [Vater-Vorname] [Vater-Nachname-Genitiv] [Stand]
                # z.B. "Jorg Henckel Donges Henkels Sohn"
                # Suche ob ein Stand-Wort irgendwo später im Bräutigam-Teil vorkommt
                stand_found = False
                for check_word in brautigam_words[idx:]:
                    if check_word.lower() in brautigam_stand_woerter:
                        stand_found = True
                        break
                
                # Wenn bereits ein Beruf erkannt wurde, überspringe die Vater-Logik
                if beruf_word_indices:
                    # Beruf wurde bereits erkannt, word_next ist der Nachname
                    result['nachname'] = word_next
                    print(f"DEBUG Heirat: Bräutigam Nachname = {result['nachname']} (Beruf bereits erkannt, keine Vater-Verarbeitung)")
                    idx += 1
                # Wenn Stand-Wort gefunden: Muster [Nachname] [Vater-Vorname] [Vater-Nachname-Genitiv] [Stand]
                elif stand_found:
                    # word_next = eigener Nachname
                    result['nachname'] = word_next
                    print(f"DEBUG Heirat: Bräutigam Nachname (eigen) = {result['nachname']}")
                    idx += 1
                    
                    # Überspringe Füllwörter
                    while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                        idx += 1
                    
                    # Nächstes Wort: Vater-Vorname
                    if idx < len(brautigam_words):
                        result['braeutigam_vater'] = brautigam_words[idx]
                        print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                        idx += 1
                        
                        # Überspringe Füllwörter
                        while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                            idx += 1
                        
                        # Nächstes Wort: Vater-Nachname (Genitiv) - ändert result['nachname'] NICHT
                        if idx < len(brautigam_words):
                            # Entferne Genitiv-s vom Vater-Nachname, aber behalte Bräutigam-Nachname
                            vater_nachname_genitiv = brautigam_words[idx]
                            print(f"DEBUG Heirat: Vater-Nachname (Genitiv) = {vater_nachname_genitiv}")
                            idx += 1
                else:
                    # Kein Stand-Wort gefunden: ursprüngliche Logik
                    # Prüfe ob nächstes Wort existiert
                    idx_peek = idx + 1
                    while idx_peek < len(brautigam_words) and brautigam_words[idx_peek] in ignore_extended:
                        idx_peek += 1
                    
                    # Wenn es ein weiteres Wort gibt
                    if idx_peek < len(brautigam_words):
                        word_after = brautigam_words[idx_peek]
                        
                        # Prüfe noch ein Wort weiter für komplexe Pattern wie "Fritz Andreae Fritzen"
                        idx_peek2 = idx_peek + 1
                        while idx_peek2 < len(brautigam_words) and brautigam_words[idx_peek2] in ignore_extended:
                            idx_peek2 += 1
                        
                        word_after2 = brautigam_words[idx_peek2] if idx_peek2 < len(brautigam_words) else None
                        
                        # Pattern: [Nachname] [VaterVorname] [VaterNachname]s
                        # z.B. Fritz Andreae Fritzen
                        if word_after2 and word_after2.endswith('s') and len(word_after2) > 2:
                            result['nachname'] = word_next  # Fritz
                            result['braeutigam_vater'] = word_after  # Andreae
                            result['nachname'] = remove_genitiv_s(word_after2)  # Fritzen -> Fritz (überschreibt)
                            print(f"DEBUG Heirat: Bräutigam Nachname = {word_next} -> Korrigiert zu {result['nachname']} (von Vater)")
                            print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                            idx = idx_peek2 + 1
                        # Wenn word_after ein männlicher Vorname ist: word_next = Nachname, word_after = Vater-Vorname
                        elif word_after in maennliche_vornamen:
                            result['nachname'] = word_next
                            print(f"DEBUG Heirat: Bräutigam Nachname = {result['nachname']}")
                            idx = idx_peek + 1
                            result['braeutigam_vater'] = word_after
                            print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                            
                            # Überspringe Füllwörter
                            while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                                idx += 1
                            
                            # Nächstes sollte Vater-Nachname (Genitiv) sein
                            if idx < len(brautigam_words):
                                result['nachname'] = remove_genitiv_s(brautigam_words[idx])
                                print(f"DEBUG Heirat: Bräutigam Nachname korrigiert (von Vater) = {result['nachname']}")
                                idx += 1
                        # Wenn word_after mit 's' endet (Genitiv): word_next = Vater-Vorname
                        elif word_after.endswith('s') and len(word_after) > 2:
                            result['braeutigam_vater'] = word_next
                            result['nachname'] = remove_genitiv_s(word_after)
                            print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                            print(f"DEBUG Heirat: Bräutigam Nachname (von Vater) = {result['nachname']}")
                            idx = idx_peek + 1
                        else:
                            # Fallback: word_next ist Nachname
                            result['nachname'] = word_next
                            print(f"DEBUG Heirat: Bräutigam Nachname (Fallback) = {result['nachname']}")
                            idx += 1
                    else:
                        # Nur ein Wort übrig: Das ist der Nachname
                        result['nachname'] = word_next
                        print(f"DEBUG Heirat: Bräutigam Nachname (nur 1 Wort) = {result['nachname']}")
                        idx += 1
        
        # Erkenne "Bürger" als Beruf im Bräutigam-Teil
        for i, w in enumerate(brautigam_words):
            if w.lower() == 'bürger' and not result['beruf']:
                result['beruf'] = 'Bürger'
                print(f"DEBUG Heirat: Beruf = Bürger")
                break
        
        # Suche "alhier" oder "alhie" für Ort im Bräutigam-Teil (bedeutet Wetzlar)
        # Auch Pattern: "Bürger [Beruf] alhier" -> Beruf extrahieren
        for i, w in enumerate(brautigam_words):
            if w.lower() in ['alhier', 'alhie']:
                result['ort'] = 'Wetzlar'
                print(f"DEBUG Heirat: Bräutigam Ort ({w}) = Wetzlar")
                # Prüfe ob davor ein Beruf steht (zwischen "Bürger" und "alhier")
                # Pattern: ... Bürger Müller alhier
                if i >= 2 and brautigam_words[i-2].lower() == 'bürger':
                    potential_beruf = brautigam_words[i-1]
                    # Prüfe ob es ein bekannter Beruf oder ein sinnvoller Beruf ist
                    if potential_beruf in BERUFE or potential_beruf[0].isupper():
                        result['beruf'] = potential_beruf
                        print(f"DEBUG Heirat: Beruf (vor alhier) = {result['beruf']}")
                elif i >= 1:
                    # Pattern: ... Bürger alhier (kein Beruf dazwischen)
                    if brautigam_words[i-1].lower() != 'bürger':
                        # Wort davor könnte Beruf sein
                        potential_beruf = brautigam_words[i-1]
                        if potential_beruf in BERUFE:
                            result['beruf'] = potential_beruf
                            print(f"DEBUG Heirat: Beruf (vor alhier, ohne Bürger) = {result['beruf']}")
                break
        
        # Suche "zu [Ort]" oder "von [Ort]" oder "in [Ort]" im Bräutigam-Teil
        # ABER: "in domo" ist Hochzeitsort, kein Wohnort!
        if not result['ort']:
            for i, w in enumerate(brautigam_words):
                if w.lower() in ['zu', 'von', 'in'] and i + 1 < len(brautigam_words):
                    next_word = brautigam_words[i + 1]
                    # Ignoriere "in domo" (Hochzeitsort, nicht Wohnort)
                    if w.lower() == 'in' and next_word.lower() == 'domo':
                        continue
                    result['ort'] = next_word
                    print(f"DEBUG Heirat: Bräutigam Ort ({w}) = {result['ort']}")
                    break
        
        # Berufserkennung wurde bereits oben durchgeführt (vor der Nachname/Vater-Logik)
        
        # Suche Stand-Angaben im Bräutigam-Teil (z.B. "Wittwer", "Sohn", "Stiefsohn")
        # Wichtig: Zuerst vollständige Wörter aus STAND_MAPPING prüfen (ganze Wörter), 
        # dann erst Teilstring-Suche als Fallback
        for word in brautigam_words:
            word_lower = word.lower()
            if word_lower in STAND_MAPPING:
                result['braeutigam_stand'] = STAND_MAPPING[word_lower]
                print(f"DEBUG Heirat: Bräutigam Stand = {result['braeutigam_stand']} (gefunden: '{word}')")
                break
        
        # Fallback: Teilstring-Suche (nur wenn noch kein Stand gefunden)
        if not result.get('braeutigam_stand'):
            brautigam_text_lower = ' '.join(brautigam_words).lower()
            braeutigam_stand_patterns = [
                ('wittwer', 'Wittwer'),
                ('wittiber', 'Wittwer'),
                ('witwer', 'Wittwer'),
                ('sohn', 'Sohn'),
                ('son', 'Sohn'),
            ]
            
            for pattern, normalized in braeutigam_stand_patterns:
                if pattern in brautigam_text_lower:
                    result['braeutigam_stand'] = normalized
                    print(f"DEBUG Heirat: Bräutigam Stand = {result['braeutigam_stand']} (gefunden: '{pattern}' - Fallback)")
                    break
        
        # === Braut-Teil analysieren ===
        # Struktur: [Anrede] [Vorname(n)] [Vater-Vorname] [Vater-Nachname]s ...
        idx = 0
        # Überspringe Anreden (Jungfr., Jfr., jung/r, jfr etc.) und Füllwörter
        # Jede Variante die mit "jung" beginnt ist eine Abkürzung für "Jungfrau" (OCR-robust)
        _anreden_lower = {a.lower() for a in anreden}
        while idx < len(braut_words) and (
            braut_words[idx].lower() in _anreden_lower or
            braut_words[idx].lower().startswith('jung') or
            braut_words[idx].lower() in ['jfr'] or
            braut_words[idx] in ignore_extended
        ):
            idx += 1
        
        # Sammle alle Vornamen bis zum nächsten männlichen Vornamen oder Füllwort
        # (Braut kann mehrere Vornamen haben: Christiana Anna Ottilie)
        partner_parts = []
        _weibliche_lower = {v.lower() for v in weibliche_vornamen}
        while idx < len(braut_words):
            word = braut_words[idx]
            # Stoppe bei Zahlen
            if word.isdigit():
                break
            # Stoppe bei Füllwörtern
            if word in ignore_extended:
                idx += 1
                continue
            # Stoppe bei bekannten maennlichen Vornamen (= Vater)
            if norm_name_token(word) in maennliche_vornamen_norm:
                break
            # Wörter auf "-in" (weibliche Berufsform/Nachname-Form, z.B. Weißgerberin, Verdriessin)
            # nach mind. einem gesammelten Vornamen = Braut-Nachname, nicht weiterer Vorname
            if (partner_parts
                    and word.lower().endswith('in')
                    and len(word) > 3
                    and word not in weibliche_vornamen
                    and word.lower() not in _weibliche_lower):
                result['braut_nachname'] = word
                print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} ('-in'-Endung erkannt)")
                idx += 1
                break

            # Stoppe bei Wörtern die wie Nachnamen aussehen (enden auf Genitiv: -s, -en, -es)
            # ABER: nur wenn danach noch ein Wort folgt (sonst ist es Teil des Nachnamens selbst)
            has_genitiv_ending = (
                (word.endswith('en') and len(word) > 3) or
                (word.endswith('es') and len(word) > 3) or
                (word.endswith('s') and len(word) > 2)
            ) and word not in weibliche_vornamen
            
            if has_genitiv_ending:
                # Prüfe ob danach noch mindestens ein Wort kommt (außer Stopwords)
                next_idx = idx + 1
                while next_idx < len(braut_words) and braut_words[next_idx] in ignore_extended:
                    next_idx += 1
                if next_idx < len(braut_words):
                    # Es folgt noch ein Wort → aktuelles Wort ist Genitiv-Nachname
                    break
                # Kein weiteres Wort → aktuelles Wort ist der Braut-Nachname selbst
            # Ansonsten: sammle als Teil des Braut-Vornamens
            partner_parts.append(word)
            idx += 1
        
        if partner_parts:
            partner_name = ' '.join(partner_parts)
            # Entferne Kommas und andere Satzzeichen am Ende
            partner_name = partner_name.rstrip(',.;:')
            
            # Prüfe ob letztes Wort ein Nachname sein könnte (kein bekannter Vorname und keine Zahl)
            # Beispiel: "Anna Güttin" → "Anna" = Partner, "Güttin" = Braut Nachname
            partner_words = partner_name.split()
            if (len(partner_words) > 1 
                and partner_words[-1] not in weibliche_vornamen 
                and not partner_words[-1].isdigit()):
                # Letztes Wort ist vermutlich der Nachname
                result['braut_nachname'] = partner_words[-1]
                result['partner'] = ' '.join(partner_words[:-1])
                print(f"DEBUG Heirat: Braut Vorname = {result['partner']}")
                print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (aus Partner extrahiert)")
            else:
                result['partner'] = partner_name
                print(f"DEBUG Heirat: Braut Vorname = {result['partner']}")
        
        # Überspringe Füllwörter
        while idx < len(braut_words) and braut_words[idx] in ignore_extended:
            idx += 1
        
        # Nach Vornamen: Unterscheide zwei Fälle
        # Fall A: [Vater-Vorname] [Vater-Nachname-Genitiv] - normale Struktur
        # Fall B: [Braut-Nachname-Genitiv] [Vater-Nachname-Genitiv] - bei Witwen ohne Vater-Vorname
        # 
        # Strategie: Prüfe ob nächstes Wort ein männlicher Vorname ist
        if idx < len(braut_words):
            current_word = braut_words[idx]
            
            # Fall A: Männlicher Vorname → Vater-Vorname
            if norm_name_token(current_word) in maennliche_vornamen_norm:
                # Sammle alle männlichen Vornamen als Vater-Vorname
                vater_vorname_parts = []
                while idx < len(braut_words) and norm_name_token(braut_words[idx]) in maennliche_vornamen_norm:
                    vater_vorname_parts.append(braut_words[idx])
                    idx += 1
                
                if vater_vorname_parts:
                    result['braut_vater'] = ' '.join(vater_vorname_parts)
                    print(f"DEBUG Heirat: Braut Vater = {result['braut_vater']}")
                
                # Überspringe Füllwörter
                while idx < len(braut_words) and braut_words[idx] in ignore_extended:
                    idx += 1
                
                # Nächstes Wort = Vater-Nachname (im Genitiv)
                # Nur setzen wenn nicht schon per -in-Endung belegt
                if idx < len(braut_words):
                    vater_nn = remove_genitiv_s(braut_words[idx])
                    if not result.get('braut_nachname'):
                        result['braut_nachname'] = vater_nn
                        print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (von Vater)")
                    else:
                        print(f"DEBUG Heirat: Vater-Nachname '{vater_nn}' ignoriert, braut_nachname bereits gesetzt ({result['braut_nachname']})")
                    idx += 1
            
            # Fall B: Kein männlicher Vorname → Könnte Braut-Nachname oder Vater-Nachname sein
            else:
                # Prüfe ob es zwei Wörter mit Genitiv-Endung gibt
                # Pattern: [Braut-Nachname-Genitiv] [Vater-Nachname-Genitiv]
                idx_peek = idx + 1
                while idx_peek < len(braut_words) and braut_words[idx_peek] in ignore_extended:
                    idx_peek += 1
                
                next_word = braut_words[idx_peek] if idx_peek < len(braut_words) else None
                
                # Wenn beide Wörter Genitiv-Endungen haben → Fall B (Witwe mit 2 Nachnamen)
                if next_word and (
                    (current_word.endswith('en') and len(current_word) > 3) or
                    (current_word.endswith('es') and len(current_word) > 3) or
                    (current_word.endswith('s') and len(current_word) > 2)
                ) and (
                    (next_word.endswith('en') and len(next_word) > 3) or
                    (next_word.endswith('es') and len(next_word) > 3) or
                    (next_word.endswith('s') and len(next_word) > 2)
                ):
                    # Beide haben Genitiv-Endungen → erstes ist Braut-Nachname, zweites ist Vater-Nachname
                    if not result['braut_nachname']:  # Nur wenn nicht schon aus Partner extrahiert
                        result['braut_nachname'] = remove_genitiv_s(current_word)
                        print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (Ehemann, Witwe)")
                    result['braut_vater'] = remove_genitiv_s(next_word)
                    print(f"DEBUG Heirat: Braut Vater = {result['braut_vater']} (nur Nachname)")
                    idx = idx_peek + 1
                else:
                    # Nur ein Genitiv-Wort → das ist Vater-Nachname (normale Struktur ohne Vater-Vorname)
                    # ABER: Keine reinen Zahlen als Nachname
                    if not current_word.isdigit():
                        if not result.get('braut_nachname'):
                            result['braut_nachname'] = remove_genitiv_s(current_word)
                            print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (von Vater, kein Vorname)")
                        else:
                            print(f"DEBUG Heirat: Vater-Nachname '{current_word}' ignoriert, braut_nachname bereits gesetzt ({result['braut_nachname']})")
                    idx += 1
        
        # Suche "zu [Ort]" oder "von [Ort]" oder "in [Ort]" für Braut-Ort
        # ABER: "in domo" ist Hochzeitsort, kein Wohnort!
        for i in range(len(braut_words) - 1):
            if braut_words[i].lower() in ['zu', 'von', 'in']:
                next_word = braut_words[i + 1]
                # Ignoriere "in domo" (Hochzeitsort, nicht Wohnort)
                if braut_words[i].lower() == 'in' and next_word.lower() == 'domo':
                    continue
                result['braut_ort'] = next_word
                print(f"DEBUG Heirat: Braut Ort = {result['braut_ort']}")
                break
        
        # "alhier" oder "alhie" bedeutet Wetzlar für Braut-Ort
        if not result['braut_ort']:
            for i, w in enumerate(braut_words):
                if w.lower() in ['alhier', 'alhie']:
                    result['braut_ort'] = 'Wetzlar'
                    print(f"DEBUG Heirat: Braut Ort ({w}) = Wetzlar")
                    break
                    break
        
        # Suche Stand-Angaben (z.B. "gewesene hausfrau", "Wittib", "hinterlassene Wittwe", "Tochter")
        # Kombinationen wie "gewesene hausfrau" erkennen
        braut_text_lower = ' '.join(braut_words).lower()
        
        # Verwende STAND_MAPPING für Stand-Erkennung
        # Sortiere nach Länge (längste zuerst), um spezifischere Matches zu bevorzugen
        for stand_key in sorted(STAND_MAPPING.keys(), key=len, reverse=True):
            if stand_key in braut_text_lower:
                result['stand'] = STAND_MAPPING[stand_key]
                print(f"DEBUG Heirat: Stand = {result['stand']} (gefunden: '{stand_key}')")
                break
        
        return result

    def _extract_burial_fields(self, text: str) -> dict:
        """
        Zentrale Funktion zur Extraktion von Feldern aus einem Begräbnis-Eintrag.
        
        Diese Funktion wird von beiden Tabs (OCR-Tab und Datenbank-Tab) verwendet,
        um eine konsistente Erkennung zu gewährleisten.
        
        Args:
            text: Der zu analysierende Text (nach Zitation)
            
        Returns:
            Dict mit extrahierten Feldern: vorname, nachname, partner, beruf, stand, todestag, ort, geb_jahr_gesch
        """
        import re
        
        result = {
            'vorname': None,
            'nachname': None,
            'partner': None,
            'beruf': None,
            'stand': None,
            'todestag': None,
            'ort': None,
            'geb_jahr_gesch': None,
            'seite': None,
            'nummer': None
        }
        
        # 1. Zitation-Pattern
        zitation_pattern = r"^(ev\.\s*Kb\.\s*Wetzlar)?[ .]*[⚰\u26B0]?[ .]*(\d{4}[ .]?\d{2}[ .]?\d{2})[ .]*p\.?[ .]?(\d+)[ .]*(Nr\.?|No\.?)[ .]?(\d+)[ .]*"
        stopwords = ["Text", "Tex", "Tex.", "begraben", "begr.", "begr ", "Begr.", "Begr "]
        
        # Suche das Ende der Zitation
        stop_idx = len(text)
        for sw in stopwords:
            idx = text.lower().find(sw.lower())
            if idx != -1 and idx < stop_idx:
                stop_idx = idx
        zitation_text = text[:stop_idx]
        
        # Zitation extrahieren
        m = re.match(zitation_pattern, zitation_text)
        
        if m:
            after_zitation = zitation_text[m.end():].strip()
            # Todestag extrahieren
            result['todestag'] = m.group(2).replace(" ", ".").replace(".", ".")
            # Seite extrahieren (Gruppe 3)
            if m.group(3):
                result['seite'] = int(m.group(3))
            # Nummer extrahieren (Gruppe 5)
            if m.group(5):
                result['nummer'] = int(m.group(5))
        else:
            after_zitation = zitation_text.strip()
        
        # 2. Wörter nach Zitation splitten
        # Satzzeichen entfernen (Kommata, Punkte, Semikolons etc.) bevor gesplittet wird
        bereinigte_zeile = re.sub(r"[,;.!?]", " ", after_zitation)
        words = re.split(r"\s+", bereinigte_zeile)
        words = [w for w in words if w]
        
        # Speichere die Original-Großschreibung für später
        words_original_case = words.copy()
        
        # WICHTIG: Normalisiere Großbuchstaben für Vornamen-Vergleiche
        # "jacob" → "Jacob", damit sie mit den Namen-Listen übereinstimmen
        words = [w[0].upper() + w[1:] if len(w) > 0 else w for w in words]
        
        if not words:
            return result
        
        # Verwende importierte Listen
        weibliche_vornamen = WEIBLICHE_VORNAMEN
        maennliche_vornamen = MAENNLICHE_VORNAMEN
        stand_synonyme = STAND_SYNONYME
        ort_prae = ORTS_PRAEPOSITIONEN
        beruf_einleitung = BERUFS_EINLEITUNG
        anreden = ANREDEN
        ignoriere_woerter = IGNORIERE_WOERTER
        
        # Hilfsfunktion für frau-Anrede
        def ist_frau_anrede(idx_aktuell):
            if idx_aktuell >= len(words) or words[idx_aktuell].lower() != "frau":
                return False
            if idx_aktuell + 1 < len(words):
                next_word = words[idx_aktuell + 1]
                if next_word in weibliche_vornamen or next_word in maennliche_vornamen:
                    return True
                if next_word.lower() not in stand_synonyme:
                    return True
            return False
        
        # Hilfsfunktion: Entferne Genitiv-Endungen
        def entferne_genitiv(wort):
            """Entfernt Genitiv-Endungen -s, -is, -en, -i, -ii, -tts von einem Wort."""
            # Namen die auf -s enden behalten: Hans, etc.
            if wort in maennliche_vornamen or wort in weibliche_vornamen:
                return wort  # Vorname, nicht ändern
            
            # Kurze Namen (2-3 Zeichen) auf -s: "Bos", "Has" etc. behalten
            if len(wort) <= 3 and wort.endswith('s'):
                return wort  # Wahrscheinlich echter Nachname
            
            # Lateinische Genitive wie "Petri" NICHT ändern (enden auf -tri, -pri, -ri)
            if wort.endswith(('tri', 'pri', 'ri')) and len(wort) > 3:
                return wort  # Lateinischer Name, nicht ändern
            
            # Namen auf -chen/-lein sind Diminutive, keine Genitive
            if wort.endswith(('chen', 'lein')):
                return wort  # Diminutiv, nicht ändern
            
            # Double-s am Ende
            if wort.endswith('ss') and len(wort) > 4:
                return wort[:-1]
            
            if wort.endswith('is'):
                return wort[:-2]
            elif wort.endswith('ii'):  # Doppel-i: "Kaulii" -> "Kauli"
                return wort[:-1]
            elif wort.endswith('i') and len(wort) > 2:  # Einfach-i: "Wilhelmi" -> "Wilhelm", "Theophili" -> "Theophil"
                return wort[:-1]
            elif wort.endswith('en') and len(wort) > 3:
                return wort[:-2]
            elif wort.endswith('s') and len(wort) > 2:
                return wort[:-1]
            return wort
        
        # 3. Extraktion
        idx = 0
        vorname_start_idx = -1
        vorname = None
        nachname = None
        partner = None
        beruf = None
        ist_weiblich = False  # Gender-Tracking für Partner-Erkennung
        stand = None
        ort = None
        
        # Vorname suchen
        while idx < len(words):
            w = words[idx]
            if w in weibliche_vornamen or w in maennliche_vornamen:
                vorname_start_idx = idx
                vorname = w
                ist_weiblich = w in weibliche_vornamen
                idx += 1
                # KEINE Doppelnamen sammeln beim ersten Durchlauf!
                # Doppelnamen werden später bei Partner-Erkennung korrekt zugeordnet:
                # - Unterschiedliche Geschlechter: Name 2 = Partner
                # - Gleiche Geschlechter + Partner-Stand (Sohn/Tochter): Name 2+ = Partner-Namen
                # - Gleiche Geschlechter + kein Stand: Name 2+ = Doppelname des Verstorbenen
                # Ignoriere-Wörter überspringen
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1
                break
            idx += 1

        # Wenn kein Vorname in den Listen gefunden wurde, Index zurücksetzen,
        # damit nachfolgende Fallbacks (z.B. Ort, Stand) trotzdem laufen.
        if not vorname:
            idx = 0
        
        # Nachname
        if vorname and vorname_start_idx > 0:
            # Prüfe ob words[0] nicht in IGNORIERE_WOERTER oder ANREDEN ist
            if words[0].lower() not in ignoriere_woerter and words[0].lower() not in anreden:
                nachname = words[0]

        # Fallback für unbekannte Namen (nicht in Vornamen-Listen):
        # Pattern: [Vorname] [Nachname] ...
        # Beispiel: "Clas Sprengel, ein Bürger in der Rosengassen ..."
        if not vorname and not nachname and len(words) >= 2:
            weibliche_stand_marker = {"witwe", "wittib", "wittwe", "witbe", "widwe", "hausfrau", "haußfrau"}
            has_weiblicher_stand = any(w.lower() in weibliche_stand_marker for w in words)

            # Nicht anwenden, wenn es ein Witwe/Hausfrau-Kontext ist –
            # dafür gibt es weiter unten eine spezialisierte Logik.
            if has_weiblicher_stand:
                pass
            else:
                first_word = words[0]
                second_word = words[1]

                if (
                    first_word.lower() not in ignoriere_woerter and
                    first_word.lower() not in anreden and
                    first_word.lower() not in stand_synonyme and
                    first_word.lower() not in ort_prae and
                    not first_word.isdigit() and
                    second_word.lower() not in ignoriere_woerter and
                    second_word.lower() not in anreden and
                    second_word.lower() not in stand_synonyme and
                    second_word.lower() not in ort_prae and
                    not second_word.isdigit()
                ):
                    vorname = first_word
                    nachname = entferne_genitiv(second_word)
                    vorname_start_idx = 0
        
        # === PARTNER + NACHNAME ERKENNUNG ===
        # Diese Logik läuft IMMER nach Vorname-Erkennung (nicht als elif!)
        if vorname:
            # **SCHRITT 1: Partner-Vorname**
            if idx < len(words):
                next_word = words[idx]
                
                # Weiblich → suche männlich oder anderes weiblich
                if ist_weiblich and next_word in maennliche_vornamen:
                    # Unterschiedliche Geschlechter: männlicher Name = Partner!
                    partner = next_word
                    idx += 1
                    # Sammle weitere männliche Vornamen beim Partner
                    while idx < len(words) and words[idx] in maennliche_vornamen:
                        partner += " " + words[idx]
                        idx += 1
                    # Ignoriere-Wörter überspringen
                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                        idx += 1
                
                elif ist_weiblich and next_word in weibliche_vornamen:
                    # Gleiche Geschlechter: Weitere weibliche Namen = Partner-Namen (nicht Doppelname!)
                    partner = next_word
                    idx += 1
                    # Sammle weitere weibliche Vornamen
                    while idx < len(words) and words[idx] in weibliche_vornamen:
                        partner += " " + words[idx]
                        idx += 1
                    # Ignoriere-Wörter überspringen
                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                        idx += 1
                
                # Männlich → suche weiblich oder anderes männlich
                elif not ist_weiblich and next_word in weibliche_vornamen:
                    # Unterschiedliche Geschlechter: weiblicher Name = Partner!
                    partner = next_word
                    idx += 1
                    # Sammle weitere weibliche Vornamen
                    while idx < len(words) and words[idx] in weibliche_vornamen:
                        partner += " " + words[idx]
                        idx += 1
                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                        idx += 1
                
                elif not ist_weiblich and next_word in maennliche_vornamen:
                    # Gleiche Geschlechter: Weitere männliche Namen = Partner-Namen
                    partner = next_word
                    idx += 1
                    # Sammle weitere männliche Vornamen
                    while idx < len(words) and words[idx] in maennliche_vornamen:
                        partner += " " + words[idx]
                        idx += 1
                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                        idx += 1
            
            # **SCHRITT 2: Nachname (kann Genitiv sein)**
            # Setze Nachname nur wenn er noch nicht gesetzt wurde
            if not nachname and idx < len(words):
                w = words[idx]
                
                if (w.lower() not in anreden and
                    w.lower() not in ignoriere_woerter and
                    w.lower() not in [s.lower() for s in stand_synonyme] and 
                    w.lower() not in ort_prae and 
                    w.lower() not in beruf_einleitung and
                    w not in weibliche_vornamen and 
                    w not in maennliche_vornamen and
                    not w.isdigit() and
                    w.lower() not in ARTIKEL):  # Artikel überspringen
                    
                    # Das ist der Nachname (möglicherweise im Genitiv)
                    nachname = entferne_genitiv(w)
                    idx += 1
                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                        idx += 1
        
        # SONDERFALL: Partner-Erkennung für uxor/Hausfrau ohne eigenen Vornamen
        # Wenn kein eigener Vorname, aber männliche Vornamen im Text vor Stand
        # NUR wenn Partner noch nicht gesetzt ist!
        if not vorname and not partner and idx < len(words):
            # Suche nach männlichen Vornamen für Partner
            temp_idx = 0
            partner_vornamen = []
            partner_vornamen_indices = []  # Speichere die Positionen der Partner-Vornamen
            while temp_idx < len(words):
                w = words[temp_idx]
                # Überspringe Anreden und ignoriere-Wörter
                if w.lower() in anreden or w.lower() in ignoriere_woerter:
                    temp_idx += 1
                    continue
                if w in maennliche_vornamen:
                    partner_vornamen.append(w)
                    partner_vornamen_indices.append(temp_idx)
                    temp_idx += 1
                    # Sammle weitere männliche Vornamen als Doppelname für Partner
                    while temp_idx < len(words) and words[temp_idx] in maennliche_vornamen:
                        partner_vornamen.append(words[temp_idx])
                        partner_vornamen_indices.append(temp_idx)
                        temp_idx += 1
                    # Überspringe Anreden/Ignoriere-Wörter
                    while temp_idx < len(words) and (words[temp_idx].lower() in anreden or words[temp_idx].lower() in ignoriere_woerter):
                        temp_idx += 1
                    # Weiter zum Stand suchen
                    continue
                elif w.lower() in stand_synonyme:
                    # Stand gefunden, Partner-Namen zusammensetzen
                    if partner_vornamen:
                        partner = " ".join(partner_vornamen)
                        # Nachname: Wort direkt nach den letzten Partner-Vornamen
                        if partner_vornamen_indices:
                            last_partner_idx = partner_vornamen_indices[-1]
                            search_idx = last_partner_idx + 1
                            
                            # Überspringe weitere Anreden/Ignoriere-Wörter nach Partner-Vornamen
                            while search_idx < len(words) and (words[search_idx].lower() in anreden or words[search_idx].lower() in ignoriere_woerter):
                                search_idx += 1
                            
                            if search_idx < len(words):
                                potential_nachname = words[search_idx]
                                if (potential_nachname.lower() not in stand_synonyme and
                                    potential_nachname.lower() not in anreden and
                                    potential_nachname not in maennliche_vornamen and
                                    potential_nachname not in weibliche_vornamen):
                                    nachname = entferne_genitiv(potential_nachname)
                    break
                else:
                    temp_idx += 1
        
        # Genitiv-Endungen von Nachnamen entfernen und Groß-/Kleinschreibung normalisieren
        if nachname:
            nachname = entferne_genitiv(nachname)
            # Normalisiere: Erster Buchstabe groß, Rest wie es ist
            if nachname:
                nachname = nachname[0].upper() + nachname[1:] if len(nachname) > 1 else nachname.upper()
        
        # === BERUF ZUERST ERKENNEN (vor Stand-Fallback) ===
        # 1. Sammle Berufe, aber NUR wenn sie in bestimmtem Kontext stehen:
        #    - Mit Artikel davor ("der Müller")
        #    - Mit "ein" davor ("ein Müller")
        #    - Mehrere Berufe hintereinander (z.B. "bürger u. becker")
        berufe_liste = []
        
        # 1a. Prüfe Artikel + Beruf
        for i in range(len(words)-1):
            if words[i].lower() in ARTIKEL:
                if words[i+1] in BERUFE or words[i+1].lower() in [b.lower() for b in BERUFE]:
                    if words[i+1].lower() == "becker":
                        berufe_liste.append("Bäcker")
                    elif words[i+1].lower() == "bürger":
                        berufe_liste.append("Bürger")
                    elif words[i+1].lower() == "schuemacher":
                        berufe_liste.append("Schuhmacher")
                    else:
                        berufe_liste.append(words[i+1])
        
        # 1b. Prüfe "ein" + Beruf
        for i in range(len(words)-1):
            if words[i].lower() in beruf_einleitung:
                next_word_lower = words[i+1].lower()
                if next_word_lower not in stand_synonyme and next_word_lower not in KEINE_BERUFE:
                    if words[i+1] in BERUFE or words[i+1].lower() in [b.lower() for b in BERUFE]:
                        if words[i+1].lower() == "becker":
                            berufe_liste.append("Bäcker")
                        elif words[i+1].lower() == "bürger":
                            berufe_liste.append("Bürger")
                        elif words[i+1].lower() == "schuemacher":
                            berufe_liste.append("Schuhmacher")
                        else:
                            berufe_liste.append(words[i+1])
                    else:
                        berufe_liste.append(words[i+1])
        
        # 1c. Prüfe auf mehrere Berufe (durch "u", "u." oder "und" getrennt)
        # Durchlaufe words und suche nach Muster: Beruf + Verbinder + Beruf
        i = 0
        while i < len(words):
            if words[i] in BERUFE or words[i].lower() in [b.lower() for b in BERUFE]:
                # Potenzieller Beruf gefunden
                if i + 2 < len(words) and words[i+1].lower() in ["u", "und", "undt"]:
                    # Prüfe ob nach Verbinder auch ein Beruf kommt
                    if words[i+2] in BERUFE or words[i+2].lower() in [b.lower() for b in BERUFE]:
                        # Mehrere Berufe! Sammle beide
                        if words[i].lower() == "becker":
                            berufe_liste.append("Bäcker")
                        elif words[i].lower() == "bürger":
                            berufe_liste.append("Bürger")
                        elif words[i].lower() == "schuemacher":
                            berufe_liste.append("Schuhmacher")
                        else:
                            berufe_liste.append(words[i])
                        
                        if words[i+2].lower() == "becker":
                            berufe_liste.append("Bäcker")
                        elif words[i+2].lower() == "bürger":
                            berufe_liste.append("Bürger")
                        elif words[i+2].lower() == "schuemacher":
                            berufe_liste.append("Schuhmacher")
                        else:
                            berufe_liste.append(words[i+2])
                        i += 3
                        continue
            i += 1
        
        # 1d. Prüfe auf akademische Titel und Berufsbezeichnungen nach Nachname
        # Pattern: Nachname, Titel und Beruf (z.B. "Seip, I.U.D. und Syndicus")
        # Suche nach Wörtern mit Punkten (I.U.D., M., H.M., etc.) die vor "und" stehen
        if nachname and not berufe_liste:
            for i in range(len(words)):
                w = words[i]
                # Prüfe ob Wort Punkte enthält (akademischer Titel) ODER es ist ein bekannter Titel
                # ODER es ist IUD (I.U.D. nach Punkt-Entfernung)
                is_title = ('.' in w or 
                           w in ['Magister', 'Doctor', 'Professor', 'Syndicus', 'Syndikus'] or
                           w.upper() in ['IUD', 'HM', 'MD'])  # Titel ohne Punkte
                
                if is_title:
                    # Sammle alle Wörter ab hier bis zu einem Stopp-Wort
                    beruf_parts = [w]
                    j = i + 1
                    while j < len(words):
                        next_w = words[j]
                        # Stoppe bei bekannten Stopp-Wörtern
                        if next_w.lower() in ['den', 'der', 'begraben', 'begr', 'starb', 'gestorben', 'anno', 'alters', 'alt']:
                            break
                        # Sammle "und"/"undt" und das folgende Wort
                        if next_w.lower() in ['und', 'u', 'undt']:
                            if j + 1 < len(words):
                                beruf_parts.append(next_w)
                                beruf_parts.append(words[j + 1])
                                j += 2
                            else:
                                break
                        else:
                            j += 1
                    
                    if len(beruf_parts) > 0:
                        berufe_liste.append(' '.join(beruf_parts))
                        break
        
        # Berufe zusammenführen
        beruf = " ".join(berufe_liste) if berufe_liste else None
        
        # SONDERFALL: Doppelname + Beruf → zweiter Name ist wahrscheinlich Nachname
        # Wenn: Vorname hat 2+ Wörter UND (kein Nachname ODER Nachname ist ein Beruf) UND Beruf vorhanden
        if vorname and ' ' in vorname and beruf:
            nachname_ist_beruf = nachname and (nachname in BERUFE or nachname.lower() in [b.lower() for b in BERUFE])
            if not nachname or nachname_ist_beruf:
                teile = vorname.split()
                if len(teile) == 2:
                    # Prüfe ob beide Teile Vornamen sind (gleicher Gender)
                    teil1_weiblich = teile[0] in weibliche_vornamen
                    teil1_maennlich = teile[0] in maennliche_vornamen
                    teil2_weiblich = teile[1] in weibliche_vornamen
                    teil2_maennlich = teile[1] in maennliche_vornamen
                    
                    if (teil1_weiblich and teil2_weiblich) or (teil1_maennlich and teil2_maennlich):
                        # Beide gleicher Gender → zweiter könnte Nachname sein
                        vorname = teile[0]
                        nachname = teile[1]
        
        # Stand
        # WICHTIG: Prüfe auch im Original-Text (before_zitation) für Varianten wie "haußfraw"
        # da die Bereinigung Kommas entfernt und die Struktur ändert
        for i in range(idx, len(words)):
            stand_prefix = ""
            if words[i].lower() in STAND_PRAEFIXE:
                stand_prefix = words[i] + " "
                j = i + 1
            elif words[i].lower() == "ein" and i + 1 < len(words) and words[i + 1].lower() in stand_synonyme:
                stand_prefix = ""
                j = i + 1
            else:
                j = i
            
            if j < len(words) and words[j].lower() in stand_synonyme:
                word_lower = words[j].lower()
                stand = STAND_MAPPING.get(word_lower, words[j].capitalize())
                if stand_prefix:
                    stand = stand_prefix + stand
                idx = j + 1
                break
        
        # Fallback: Suche im Original-Text nach Stand-Wörtern (inkl. Schreibvarianten)
        # Dies fängt Fälle wie "haußfraw" ab, die durch Komma-Entfernung verloren gehen könnten
        if not stand:
            text_lower = after_zitation.lower()
            for stand_key, stand_value in STAND_MAPPING.items():
                if stand_key in text_lower:
                    stand = stand_value
                    break
        
        # === GENDER-VALIDIERUNG DES STAND ===
        # WICHTIG: Weibliche Vornamen gehören zu weiblichen Ständen (Tochter, Wittwe)
        #          Männliche Vornamen gehören zu männlichen Ständen (Sohn, Vater, Witwer)
        # Wenn Stand und Vorname-Geschlecht nicht übereinstimmen, korrigiere Stand!
        if stand and vorname:
            stand_lower = stand.lower()
            
            # Definiere Gender-Paare für Stand-Korrektionen
            stand_gender_pairs = {
                # Weiblich ↔ Männlich
                "tochter": "sohn",
                "dochter": "sohn", 
                "tochterlein": "sohnlein",
                "töchterlein": "söhnlein",
                "döchterlein": "söhnlein",
                "witwe": "witwer",
                "wittib": "wittwer",
                "wittwe": "wittwer",
                "witbe": "witwer",
                "widwe": "witwer",
                "vidua": "witwer",
            }
            
            # Vertausche die Paare für Rückwärts-Lookup
            reverse_pairs = {v: k for k, v in stand_gender_pairs.items()}
            
            # Identifiziere Stand-Basis (z.B. "witwe", "sohn")
            stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
            
            # Bestimme das Geschlecht des erkannten Vornamens
            vorname_is_female = ist_weiblich
            
            # Bestimme das Geschlecht des aktuellen Stands
            stand_is_female = stand_base in [
                "tochter", "dochter", "tochterlein", "töchterlein", "döchterlein",
                "witwe", "wittib", "wittwe", "witbe", "widwe", "vidua", "hausfrau", "haußfrau"
            ]
            
            # Wenn Geschlechter nicht übereinstimmen, korrigiere Stand
            if vorname_is_female != stand_is_female:
                # Suche den korrekten Gender-Variant
                if stand_base in stand_gender_pairs:
                    # Weiblich detektiert, aber Stand männlich → nutze weiblichen Stand
                    if vorname_is_female:
                        # Halte weiblichen Stand, ändere nichts
                        pass
                    else:
                        # Männlicher Vorname, aber weiblicher Stand → ersetze mit männlichem Stand
                        correct_stand = stand_gender_pairs[stand_base]
                        stand = STAND_MAPPING.get(correct_stand, correct_stand.capitalize())
                
                elif stand_base in reverse_pairs:
                    # Männlich detektiert, aber Stand weiblich → nutze männlichen Stand
                    if vorname_is_female:
                        # Weiblicher Vorname, aber männlicher Stand → ersetze mit weiblichem Stand
                        correct_stand = reverse_pairs[stand_base]
                        stand = STAND_MAPPING.get(correct_stand, correct_stand.capitalize())
                    else:
                        # Halte männlichen Stand, ändere nichts
                        pass
        
        # Falls kein Stand: Setze Standard-Stand basierend auf Geschlecht
        # Männlicher Vorname ohne Stand → "Vater"
        # Weiblicher Vorname ohne Stand → bleibt leer (könnte ledige Person sein)
        if not stand:
            if vorname and not ist_weiblich:
                # Männlicher Vorname → Standard ist "Vater"
                stand = "Vater"
        
        # === PARTNER-STAND-LOGIK ===
        if stand:
            stand_lower = stand.lower()
            stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
            
            if stand_base in PARTNER_STÄNDE:
                # SONDERFALL: Bei Witwe/Witwer mit "weilandt/seel" im Text
                is_witwe_pattern = stand_base in ["witwe", "wittib", "wittwe", "witbe", "widwe", "witwer", "wittwer"]
                has_weilandt_pattern = any(w.lower() in ["weilandt", "weiland", "weyland", "seel", "seel.", "sel", "sel.", "seelig"] for w in words)
                
                if is_witwe_pattern and has_weilandt_pattern:
                    # Bei diesem Muster bleibt der Vorname erhalten (ist eigener Name)
                    # AUSNAHME: Wenn der erkannte Vorname männlich ist, ist er der Partner!
                    # Wenn Partner bereits erkannt wurde (z.B. durch frühe Partner-Erkennung),
                    # behalte ihn bei und suche nur nach Nachname
                    
                    # SONDERFALL: Männlicher Vorname bei Witwe/weiland → Partner!
                    if vorname and not ist_weiblich and not partner:
                        # Der erkannte "Vorname" ist eigentlich der Partner
                        partner = vorname
                        vorname = None
                    
                    # Suche die Position von weilandt/seel (immer, auch wenn partner schon gesetzt)
                    weilandt_idx = -1
                    for i, w in enumerate(words):
                        if w.lower() in ["weilandt", "weiland", "weyland", "seel", "seel.", "sel", "sel.", "seelig"]:
                            weilandt_idx = i
                            break
                    
                    if not partner and weilandt_idx >= 0:
                        # Suche NACH weilandt/seel nach Partner
                        j = weilandt_idx + 1
                        # Überspringe Anreden nach weilandt/seel
                        while j < len(words) and words[j].lower() in ["herrn", "hern", "herr", "h", "h."] + [w.lower() for w in ignoriere_woerter]:
                            j += 1
                        
                        # Partner-Vorname (evtl. in Genitiv)
                        if j < len(words) and words[j] in maennliche_vornamen:
                            partner_vorname = words[j]
                            # Entferne Genitiv-Endungen (-s, -is)
                            if partner_vorname.endswith('is') and len(partner_vorname) > 3:
                                partner_vorname = partner_vorname[:-2]
                            elif partner_vorname.endswith('s') and len(partner_vorname) > 2:
                                if partner_vorname[-2] not in 'aeiouäöü':
                                    partner_vorname = partner_vorname[:-1]
                            
                            # Partner-Nachname (auch in Genitiv)
                            if j + 1 < len(words):
                                partner_nachname = words[j + 1]
                                # Entferne Genitiv-Endungen
                                if partner_nachname.endswith('is') and len(partner_nachname) > 3:
                                    partner_nachname = partner_nachname[:-2]
                                    nachname = partner_nachname
                                elif partner_nachname.endswith('s') and len(partner_nachname) > 2:
                                    if partner_nachname[-2] not in 'aeiouäöü':
                                        partner_nachname = partner_nachname[:-1]
                                        nachname = partner_nachname
                                    else:
                                        nachname = partner_nachname
                                else:
                                    nachname = partner_nachname
                            
                            if not partner:  # NUR wenn Partner noch nicht gesetzt
                                partner = partner_vorname
                        else:
                            # ALTERNATIVE: Wenn nach weilandt/seel nichts gefunden, suche VOR weilandt/seel
                            # Dies ist der Fall bei "Catharina, Jost Diderichs selig verlassen Witwe"
                            # Gehe rückwärts von weilandt_idx und suche männlichen Vornamen
                            if not partner:  # NUR wenn Partner noch nicht gesetzt
                                for k in range(weilandt_idx - 1, -1, -1):
                                    if words[k] in maennliche_vornamen:
                                        partner = words[k]
                                        # Prüfe auf Nachname nach dem Partner-Vornamen
                                        if k + 1 < weilandt_idx:
                                            next_word = words[k + 1]
                                            if next_word.lower() not in [w.lower() for w in ignoriere_woerter]:
                                                nachname = entferne_genitiv(next_word)
                                        break
                else:
                    # NEUE LOGIK: Prüfe Geschlecht der Vornamen
                    # Bei Tochter mit weiblichen Vornamen = eigener Name (KEINE Partner-Logik!)
                    # Bei Tochter mit männlichen Vornamen = Vater-Name (Partner-Logik!)
                    # Bei Sohn generell = Vater-Name (Partner-Logik!), außer explizit anders markiert
                    is_tochter = stand_base in ["tochter", "dochter", "töchterlein", "döchterlein"]
                    is_sohn = stand_base in ["sohn", "son", "söhnlein", "sohnlein"]
                    
                    apply_partner_logic = True  # Standard: Partner-Logik
                    
                    if is_tochter and ist_weiblich:
                        # AUSNAHME: Tochter mit weiblichem Vornamen → Das ist die Tochter selbst!
                        apply_partner_logic = False
                    
                    if apply_partner_logic:
                        # SONDERFALL bei Sohn: Wenn bereits Vorname UND Nachname gesetzt sind,
                        # suche nach weiterem männlichen Vornamen (= Vater)
                        # Pattern: "Just Roder, Caspar Roders Sohn"
                        sohn_special_case = False  # Flag für Sohn-Sonderfall
                        if is_sohn and vorname and nachname and not partner:
                            # Suche nach männlichem Vornamen NACH dem bereits erkannten Vornamen
                            for i in range(len(words)):
                                w = words[i]
                                # Überspringe den bereits erkannten Vornamen
                                if w == vorname:
                                    continue
                                # Suche weiteren männlichen Vornamen
                                if w in maennliche_vornamen:
                                    partner = w
                                    sohn_special_case = True  # Merke dass Sohn-Sonderfall zutrifft
                                    # Suche nach Partner-Nachname im Genitiv nach dem Partner-Vornamen
                                    # Finde Position des Partners
                                    partner_idx = i
                                    if partner_idx + 1 < len(words):
                                        next_word = words[partner_idx + 1]
                                        # Prüfe ob es ein Nachname sein könnte (endet auf 's' = Genitiv)
                                        if (next_word.endswith('s') and 
                                            next_word.lower() not in stand_synonyme and
                                            next_word.lower() not in ignoriere_woerter and
                                            next_word not in maennliche_vornamen):
                                            # Entferne Genitiv-s vom Partner-Nachname
                                            partner_nachname = entferne_genitiv(next_word)
                                            # Verwende Partner-Nachname nur wenn er vom eigenen Nachname abweicht
                                            # oder überschreibe wenn eigener Nachname leer war
                                            if not nachname or nachname != partner_nachname:
                                                # Eigener Nachname bleibt, aber wir haben Info über Vater
                                                pass  # Nachname bleibt wie er ist
                                    break
                        
                        # Der erkannte Name gehört zum Partner/Vater/Mutter
                        # Bei ALLEN Partner-Ständen: Partner = nur Vorname(n)
                        # Nachname ist Familienname und bleibt erhalten
                        partner_bereits_gesetzt = bool(partner)  # Merke ob Partner bereits gesetzt war
                        
                        if not partner:  # NUR wenn Partner noch nicht gesetzt
                            if vorname:
                                partner = vorname
                            elif nachname:
                                partner = nachname
                        
                        # NUR Vorname löschen wenn Partner aus Vorname gesetzt wurde
                        # AUSNAHME: Bei Sohn-Sonderfall (eigener Vorname + Vater-Vorname) bleibt Vorname erhalten!
                        # Wenn Partner bereits durch frühe Partner-Erkennung gesetzt war, Vorname behalten!
                        if not partner_bereits_gesetzt and not sohn_special_case:
                            vorname = None
        
        # SONDERFALL: Hausfrau/Witwe mit männlichem Vornamen UND Genitiv-Namen
        # Pattern: [Frauen-Vorname] [Männer-Vorname] [Männer-Nachname-Genitiv] [Hausfrau]
        # Beispiel: "Barbara Herman Hunoltts Hausfraw"
        # → Erkennung: Barbara (Vorname), Herman (Partner), Hunoltt (Nachname)
        weibliche_stände = ["hausfrau", "haußfrau", "wittwe", "wittib", "wittwe", "witbe", "widwe"]
        
        if stand and stand.lower() in weibliche_stände and vorname and ist_weiblich:
            # Bei Hausfrau-Muster: Re-erkenne Partner und Nachname
            # WICHTIGES Muster: [Weiblicher Vorname] [Männlicher Vorname = Partner] [Nachname-Genitiv]
            
            # Starten nach dem Vorname
            search_start = vorname_start_idx + 1
            
            # Überspringe weitere weibliche Vornamen (falls Doppelname der Frau)
            while search_start < len(words) and words[search_start] in weibliche_vornamen:
                search_start += 1
            
            # Überspringe Ignoriere-Wörter
            while search_start < len(words) and words[search_start].lower() in ignoriere_woerter:
                search_start += 1
            
            # Nächstes Wort prüfen:
            if search_start < len(words):
                next_word = words[search_start]
                
                # FALL 1: Männlicher Vorname → Das ist der Partner (Ehemann)!
                if next_word in maennliche_vornamen:
                    partner = next_word
                    search_start += 1
                    
                    # Sammle weitere männliche Vornamen als Doppelname des Partners
                    while search_start < len(words) and words[search_start] in maennliche_vornamen:
                        partner += " " + words[search_start]
                        search_start += 1
                    
                    # Überspringe Ignoriere-Wörter
                    while search_start < len(words) and words[search_start].lower() in ignoriere_woerter:
                        search_start += 1
                    
                    # Nächstes Wort = Nachname (im Genitiv)
                    if search_start < len(words):
                        potential_nachname = words[search_start]
                        if (potential_nachname.lower() not in stand_synonyme and
                            potential_nachname.lower() not in anreden and
                            potential_nachname.lower() not in ort_prae and
                            not potential_nachname.isdigit()):
                            # Das ist der Nachname (im Genitiv)
                            nachname = entferne_genitiv(potential_nachname)
                
                # FALL 2: Kein männlicher Vorname, aber Genitiv-Name → Alter Logik (Nachname dann Partner)
                elif (next_word.lower() not in stand_synonyme and
                      next_word.lower() not in anreden and
                      next_word.lower() not in ort_prae and
                      not next_word.isdigit()):
                    # Das könnte Nachname sein
                    nachname = next_word
                    search_start += 1
                    
                    # Überspringe Ignoriere-Wörter
                    while search_start < len(words) and words[search_start].lower() in ignoriere_woerter:
                        search_start += 1
                    
                    # Nächstes Wort = Partner-Nachname (Genitiv)
                    if search_start < len(words):
                        potential_partner = words[search_start]
                        has_genitiv = (
                            (potential_partner.endswith('s') and len(potential_partner) > 2) or
                            (potential_partner.endswith('en') and len(potential_partner) > 3) or
                            (potential_partner.endswith('tts') and len(potential_partner) > 4)
                        )
                        
                        if has_genitiv and potential_partner.lower() not in stand_synonyme:
                            partner = potential_partner  # Wird später durch entferne_genitiv bearbeitet
        
        # FALLBACK: Wenn Hausfrau aber kein Partner gefunden, suche rückwärts
        if stand and stand.lower() in weibliche_stände and vorname and not partner:
            # idx wurde nach Stand-Erkennung gesetzt, also idx-1 ist der Index NACH dem Stand-Wort
            # Wir suchen von idx-2 rückwärts (den Stand-Wort überspringend)
            
            # Finde den Index des Stand-Wortes
            stand_idx = idx - 1  # idx wurde auf j+1 gesetzt nach Stand-Erkennung
            
            # Rückwärts-Suche: ONLY von Stand-Wort bis zum Anfang
            # (nicht über den Stand hinaus, wo andere Verben/Wörter stehen)
            for i in range(stand_idx - 1, -1, -1):
                w = words[i]
                # Prüfe ob es ein potenzieller Genitiv-Name ist (endet auf Genitiv-Endung)
                has_genitiv = (
                    (w.endswith('s') and len(w) > 2) or
                    (w.endswith('en') and len(w) > 3) or
                    (w.endswith('tts') and len(w) > 4)
                )
                
                if has_genitiv and w.lower() not in stand_synonyme and w not in anreden and w != nachname:
                    # Das könnte Partner-Nachname sein (wird später durch entferne_genitiv bearbeitet)
                    partner = w  # NICHT entferne_genitiv hier - wird am Ende einmal aufgerufen!
                    break
        
        # SONDERFALL: Vorname NACH dem Stand (z.B. "töchterlein ... Anna Maria" oder "Wittib Elisabetha")
        # Suche nach weiblichen Vornamen nach dem Stand für Tochter- und Witwe-Fälle
        if stand and not vorname:
            stand_lower = stand.lower()
            stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
            is_tochter = stand_base in ["tochter", "dochter", "tochterlein", "töchterlein", "döchterlein"]
            is_witwe = stand_base in ["witwe", "wittib", "wittwe", "witbe", "widwe"]
            
            if is_tochter or is_witwe:
                # Suche nach weiblichen Vornamen NACH dem Stand
                for i in range(len(words)):
                    if words[i].lower() in stand_synonyme:
                        # Stand gefunden, suche danach nach weiblichen Vornamen
                        j = i + 1
                        # Überspringe "von X. Jahren" etc.
                        while j < len(words) and (words[j].lower() in ["von", "von der"] or words[j].isdigit() or words[j].lower() in ["jahren", "jahr"]):
                            j += 1
                        
                        # Prüfe auf weibliche Vornamen
                        if j < len(words) and words[j] in weibliche_vornamen:
                            vorname = words[j]
                            j += 1
                            # Doppelname
                            if j < len(words) and words[j] in weibliche_vornamen:
                                vorname += " " + words[j]
                            break
        
        # FALLBACK: Witwe/Hausfrau OHNE erkannte Vornamen (nicht in Listen)
        # Pattern: [Name1] [Name2] [Nachname-Genitiv] [Präfix] [Witwe/Hausfrau]
        # Beispiel: "Eyda, Werner Scherers hinterlassene Wittwe"
        # → vorname: Eyda, partner: Werner, nachname: Scherer
        if stand and not vorname and not partner:
            stand_lower = stand.lower()
            stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
            is_witwe_hausfrau = stand_base in ["witwe", "wittib", "wittwe", "witbe", "widwe", "hausfrau", "haußfrau"]
            
            if is_witwe_hausfrau:
                # Finde Position des Stands in words
                stand_idx = -1
                for i in range(len(words)):
                    if words[i].lower() in stand_synonyme:
                        stand_idx = i
                        break
                
                if stand_idx >= 3:  # Brauchen mindestens 3 Wörter davor: [Name1] [Name2] [Genitiv]
                    # Gehe rückwärts vom Stand
                    # Überspringe Präfixe wie "hinterlassene", "verlassene"
                    check_idx = stand_idx - 1
                    while check_idx >= 0 and words[check_idx].lower() in STAND_PRAEFIXE:
                        check_idx -= 1
                    
                    # Jetzt sollte check_idx auf einem Genitiv-Namen zeigen
                    if check_idx >= 0:
                        potential_genitiv = words[check_idx]
                        has_genitiv = (
                            (potential_genitiv.endswith('s') and len(potential_genitiv) > 2) or
                            (potential_genitiv.endswith('en') and len(potential_genitiv) > 3) or
                            (potential_genitiv.endswith('tts') and len(potential_genitiv) > 4)
                        )
                        
                        if has_genitiv and potential_genitiv.lower() not in stand_synonyme:
                            # Das ist wahrscheinlich der Nachname (im Genitiv)
                            nachname = entferne_genitiv(potential_genitiv)
                            check_idx -= 1
                            
                            # Nächstes Wort rückwärts = Partner-Vorname
                            if check_idx >= 0:
                                partner = words[check_idx]
                                check_idx -= 1
                                
                                # Nächstes Wort rückwärts = Vorname der Witwe
                                if check_idx >= 0:
                                    vorname = words[check_idx]
                                    ist_weiblich = True  # Witwe ist immer weiblich
        
        # Ort
        for i in range(idx, len(words)):
            if i + 1 < len(words) and words[i].lower() == "in" and words[i+1].lower() == "der":
                if i + 2 < len(words):
                    ort = words[i+2]
                    idx = i + 3
                    break
            elif words[i].lower() in ort_prae:
                if i + 1 < len(words):
                    potential_ort = words[i+1]
                    # Prüfe ob es keine Zahl ist (z.B. "von 25 jahr")
                    if not potential_ort.isdigit():
                        ort = potential_ort
                        idx = i + 2
                    break
        
        # Genitiv-Endungen von Partner-Namen entfernen
        if partner:
            partner = entferne_genitiv(partner)
        
        # === RESTORE ORIGINAL CASE ===
        # Erstelle ein Mapping von kapitalisierter → Original-Case
        def restore_original_case(value, words_cap, words_orig):
            """Ersetze kapitalisierte Wörter mit ihrer Original-Schreibweise."""
            if not value:
                return value
            
            result_parts = []
            value_words = value.split()
            
            for vw in value_words:
                # Finde das Wort in der kapitalizierten Liste
                found = False
                for i, cw in enumerate(words_cap):
                    if cw == vw:
                        # Verwende die Original-Schreibweise
                        result_parts.append(words_orig[i])
                        words_cap = words_cap[:i] + words_cap[i+1:]
                        words_orig = words_orig[:i] + words_orig[i+1:]
                        found = True
                        break
                
                if not found:
                    # Nicht gefunden (z.B. nach Genitiv-Entfernung), verwende wie-es-ist
                    result_parts.append(vw)
            
            return " ".join(result_parts)
        
        # Wende Original-Case auf vorname, nachname, partner an
        if vorname:
            vorname = restore_original_case(vorname, words.copy(), words_original_case.copy())
        if nachname:
            nachname = restore_original_case(nachname, words.copy(), words_original_case.copy())
        if partner:
            partner = restore_original_case(partner, words.copy(), words_original_case.copy())

        # Ergebnisse in result-Dict speichern
        result['vorname'] = vorname
        result['nachname'] = nachname
        result['partner'] = partner
        result['beruf'] = beruf
        result['stand'] = stand
        result['ort'] = ort
        
        # === ALTERS-EXTRAKTION UND GEBURTSJAHR-BERECHNUNG ===
        # Pattern für Altersangaben: "aetat[is|isis]? \d+", "aet. \d+", "alt[er[s]]? \d+ jahr", "anno aetatis \d+"
        # Beispiele: "aetatis 1. jahr", "aet. 72", "aetatisis anno 74", "alt 29 ann", "alter 76 jahr", "alters 20 anni"
        # Flexibel: erlaubt "aetat", "aet.", "aetat anno", "anno aetatis", "aetatis", "aetatisis anno", "alt", "alter", "alters", etc.
        # Zeiteinheiten: jahr, ann/anni (Jahr), wochen, tag, monat, mens/mensis (Monat)
        alter_jahre = None
        geb_jahr_gesch = None
        
        alter_pattern = r'(?:aetat(?:is|isis)?|aet\.?|alters?)\s*(?:anno)?\s*(?:aetatis(?:is)?)?\s*[.:]*\s*(\d+)(?:[.,]?\s*(\d+)?)?\s*(?:jahr|ann(?:i)?|wochen|tag|monat|mens(?:is)?)?'
        
        # Suche im gesamten Text (nicht nur after_zitation)
        alter_match = re.search(alter_pattern, text, re.IGNORECASE)
        if alter_match:
            alter_jahre = int(alter_match.group(1))
            
            # Berechne geschätztes Geburtsjahr wenn Todesdatum vorhanden
            if result.get('todestag') and alter_jahre is not None:
                try:
                    # Extrahiere Jahr aus Todesdatum (Format: YYYY.MM.DD oder YYYY MM DD)
                    jahr_match = re.match(r'(\d{4})', result['todestag'])
                    if jahr_match:
                        todes_jahr = int(jahr_match.group(1))
                        geb_jahr_gesch = todes_jahr - alter_jahre
                except (ValueError, AttributeError):
                    pass
        
        result['geb_jahr_gesch'] = geb_jahr_gesch
        
        return result

    def _run_recognition_selected(self):
        """Führt die strukturierte Erkennung für die ausgewählten Datensätze im Datenbank-Tab durch (unterscheidet Typ Begräbnis/Hochzeit)."""
        import re
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie mindestens einen Eintrag aus der Liste aus.")
            return

        # Progressbar initialisieren
        total = len(selection)
        self.db_progress['maximum'] = total
        self.db_progress['value'] = 0

        errors = []
        updated = 0
        unrecognized_words = set()  # Sammlung aller nicht erkannten Wörter
        for idx, item in enumerate(selection):
            # Progressbar aktualisieren
            self.db_progress['value'] = idx
            self.root.update_idletasks()
            
            values = self.tree.item(item)['values']
            record_id = values[0]
            typ = values[4] if len(values) > 4 else None
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT erkannter_text FROM karteikarten WHERE id = ?", (record_id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                errors.append(f"ID {record_id}: Kein erkannter Text vorhanden.")
                continue
            text = row[0]

            # --- Begräbnis-Erkennung ---
            # Verwende zentrale Erkennungsfunktion für konsistente Ergebnisse
            if (typ and typ.lower().startswith("begr")) or '⚰' in text or '\u26B0' in text:
                # Nutze zentrale Begräbnis-Extraktion (gleiche Logik wie OCR-Tab)
                fields = self._extract_burial_fields(text)
                
                vorname = fields['vorname']
                nachname = fields['nachname']
                partner = fields['partner']
                beruf = fields['beruf']
                stand = fields['stand']
                todestag = fields['todestag']
                ort = fields['ort']
                geb_jahr_gesch = fields.get('geb_jahr_gesch')
                
                # Speichern
                try:
                    cursor.execute("""
                        UPDATE karteikarten SET
                            vorname = ?, nachname = ?, partner = ?, beruf = ?, stand = ?, todestag = ?, ort = ?, geb_jahr_gesch = ?, aktualisiert_am = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (vorname, nachname, partner, beruf, stand, todestag, ort, geb_jahr_gesch, record_id))
                    self.db.conn.commit()
                    updated += 1
                except Exception as e:
                    errors.append(f"ID {record_id}: Fehler beim Speichern: {e}")
            else:
                # --- Heirats-Erkennung ---
                if typ and (typ.lower().startswith('heirat') or '∞' in text):
                    # Nutze spezialisierte Heirats-Extraktion
                    fields = self._extract_marriage_fields(text)
                    
                    # Speichern
                    try:
                        cursor.execute("""
                            UPDATE karteikarten SET
                                vorname = ?, nachname = ?, partner = ?, beruf = ?, ort = ?, stand = ?,
                                braeutigam_stand = ?, braeutigam_vater = ?, braut_vater = ?, braut_nachname = ?, braut_ort = ?,
                                todestag = ?,
                                aktualisiert_am = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (
                            fields['vorname'], fields['nachname'], fields['partner'], 
                            fields['beruf'], fields['ort'], fields['stand'],
                            fields['braeutigam_stand'], fields['braeutigam_vater'], fields['braut_vater'], 
                            fields['braut_nachname'], fields['braut_ort'],
                            fields.get('todestag'),
                            record_id
                        ))
                        self.db.conn.commit()
                        updated += 1
                    except Exception as e:
                        errors.append(f"ID {record_id}: Fehler beim Speichern: {e}")
                else:
                    # Platzhalter für andere Typen
                    errors.append(f"ID {record_id}: Typ '{typ}' wird noch nicht unterstützt.")

        # Speichere nicht erkannte Wörter in Datei
        if unrecognized_words:
            import datetime
            output_file = Path("output/unrecognized_words.txt")
            output_file.parent.mkdir(exist_ok=True)
            
            # Sortiere alphabetisch
            sorted_words = sorted(unrecognized_words, key=str.lower)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Nicht erkannte Wörter ({len(sorted_words)} insgesamt)\n")
                f.write(f"# Generiert am: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Anzahl verarbeiteter Datensätze: {updated}\n\n")
                for word in sorted_words:
                    f.write(f"{word}\n")
            
            msg = f"{updated} Datensätze aktualisiert.\n\n"
            msg += f"{len(unrecognized_words)} nicht erkannte Wörter in {output_file} gespeichert."
        else:
            msg = f"{updated} Datensätze aktualisiert."
        
        if errors:
            msg += "\n\nFehler:\n" + "\n".join(errors)
        
        # Progressbar zurücksetzen
        self.db_progress['value'] = 0
        
        messagebox.showinfo("Feld-Extraktion abgeschlossen", msg)
        self._refresh_db_list()

    def _run_recognition_ocr_tab(self):
        """Führt die Feld-Erkennung auf dem aktuellen Text im OCR-Tab durch (erkennt Begräbnisse und Heiraten)."""
        import re

        # Hole den aktuellen Text
        text = self.text_display.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Kein Text", "Bitte zuerst Text erkennen oder eingeben.")
            return
        
        # Setze alle Felder zurück
        self._clear_ocr_field_labels()
        
        # Erkenne den Typ (Begräbnis ⚰ oder Heirat ∞)
        is_heirat = '∞' in text
        is_begraebnis = '⚰' in text or '\u26B0' in text
        
        # Falls beide Symbole oder keines vorhanden, versuche anhand Keywords zu erkennen
        if (is_heirat and is_begraebnis) or (not is_heirat and not is_begraebnis):
            if 'begraben' in text.lower() or 'begr' in text.lower():
                is_begraebnis = True
                is_heirat = False
            elif 'heirat' in text.lower() or 'getraut' in text.lower() or 'und' in text.lower():
                is_heirat = True
                is_begraebnis = False
        
        # --- HEIRAT-ERKENNUNG ---
        if is_heirat:
            result = self._extract_marriage_fields(text)
            
            # Update UI mit erkannten Feldern
            self._set_ocr_field_value('vorname', result.get('vorname'))
            self._set_ocr_field_value('nachname', result.get('nachname'))
            self._set_ocr_field_value('partner', result.get('partner'))
            self._set_ocr_field_value('braut stand', result.get('stand'))
            self._set_ocr_field_value('beruf', result.get('beruf'))
            self._set_ocr_field_value('ort', result.get('ort'))
            if 'seite' in self.ocr_field_labels and result.get('seite'):
                self._set_ocr_field_value('seite', str(result.get('seite')))
            if 'nummer' in self.ocr_field_labels and result.get('nummer'):
                self._set_ocr_field_value('nummer', str(result.get('nummer')))
            self._set_ocr_field_value('todestag', result.get('todestag'))
            
            # Heirat-spezifische Felder
            if 'bräutigam stand' in self.ocr_field_labels:
                self._set_ocr_field_value('bräutigam stand', result.get('braeutigam_stand'))
            if 'bräutigam vater' in self.ocr_field_labels:
                self._set_ocr_field_value('bräutigam vater', result.get('braeutigam_vater'))
            if 'braut vater' in self.ocr_field_labels:
                self._set_ocr_field_value('braut vater', result.get('braut_vater'))
            if 'braut nachname' in self.ocr_field_labels:
                self._set_ocr_field_value('braut nachname', result.get('braut_nachname'))
            if 'braut ort' in self.ocr_field_labels:
                self._set_ocr_field_value('braut ort', result.get('braut_ort'))
            
            # Speichere für spätere Nutzung
            self._last_recognized_fields = result
            
            # WICHTIG: Prüfe ob Braut-Vorname (partner) erkannt wurde
            if not result.get('partner'):
                # Statuszeile im OCR-Tab mit Warnung aktualisieren
                self.db_record_status.config(
                    text="⚠️ WARNUNG: Kein weiblicher Vorname (Braut) erkannt! Bitte Vornamenliste prüfen.",
                    foreground="red"
                )
                messagebox.showwarning(
                    "Heirat-Erkennung unvollständig", 
                    "Kein weiblicher Vorname (Braut) erkannt!\n\n"
                    "Mögliche Ursachen:\n"
                    "• Braut-Vorname nicht in Vornamenliste (extraction_lists.py)\n"
                    "• Kein Trenner-Wort zwischen Bräutigam und Braut\n"
                    "• OCR-Fehler im erkannten Text\n\n"
                    "Bitte Text und Vornamenliste überprüfen."
                )
            else:
                # Erfolgreiche Erkennung - Status zurücksetzen
                self.db_record_status.config(text="", foreground="blue")
                messagebox.showinfo("Erkennung", "Heirat-Felder erkannt.")
            return
        
        # --- BEGRÄBNIS-ERKENNUNG ---
        # Nutze zentrale Begräbnis-Extraktion (gleiche Logik wie Datenbank-Tab)
        fields = self._extract_burial_fields(text)
        
        # Update UI
        self._set_ocr_field_value('vorname', fields.get('vorname'))
        self._set_ocr_field_value('nachname', fields.get('nachname'))
        self._set_ocr_field_value('partner', fields.get('partner'))
        if 'stand' in self.ocr_field_labels:
            self._set_ocr_field_value('stand', fields.get('stand'))
        if 'braut stand' in self.ocr_field_labels:
            self._set_ocr_field_value('braut stand', None)
        self._set_ocr_field_value('beruf', fields.get('beruf'))
        self._set_ocr_field_value('ort', fields.get('ort'))
        if 'seite' in self.ocr_field_labels and fields.get('seite'):
            self._set_ocr_field_value('seite', str(fields.get('seite')))
        if 'nummer' in self.ocr_field_labels and fields.get('nummer'):
            self._set_ocr_field_value('nummer', str(fields.get('nummer')))
        if 'todestag' in self.ocr_field_labels:
            self._set_ocr_field_value('todestag', fields.get('todestag'))
        if 'geb.jahr (gesch.)' in self.ocr_field_labels:
            geb_jahr_text = str(fields.get('geb_jahr_gesch')) if fields.get('geb_jahr_gesch') else None
            self._set_ocr_field_value('geb.jahr (gesch.)', geb_jahr_text)
        # Neue Felder (nur für Heiraten, werden hier als leer angezeigt bei Begräbnissen)
        if 'bräutigam stand' in self.ocr_field_labels:
            self._set_ocr_field_value('bräutigam stand', None)
        if 'bräutigam vater' in self.ocr_field_labels:
            self._set_ocr_field_value('bräutigam vater', None)
        if 'braut vater' in self.ocr_field_labels:
            self._set_ocr_field_value('braut vater', None)
        if 'braut nachname' in self.ocr_field_labels:
            self._set_ocr_field_value('braut nachname', None)
        if 'braut ort' in self.ocr_field_labels:
            self._set_ocr_field_value('braut ort', None)
        
        # Speichere die erkannten Felder für spätere Nutzung
        self._last_recognized_fields = fields
        
        # Status zurücksetzen
        self.db_record_status.config(text="", foreground="blue")
        messagebox.showinfo("Erkennung", "Begräbnis-Felder erkannt.")
        # Status-Hinweis
        self.db_record_status.config(
            text="✓ Felder erkannt. Nutzen Sie 'DB aktualisieren', um die Änderungen zu speichern.",
            foreground="blue"
        )

    def _update_db_fields(self):
        """Aktualisiert die erkannten Felder in der Datenbank."""
        # Prüfe, ob Felder vorhanden sind
        if not hasattr(self, 'ocr_field_vars') and not hasattr(self, '_last_recognized_fields'):
            messagebox.showwarning("Keine Felder", "Bitte zuerst Felder erkennen ('🧠 Felder erkennen').")
            return
        
        # Prüfe, ob ein DB-Eintrag vorhanden ist
        if not self.current_db_record_id:
            messagebox.showwarning(
                "Kein DB-Eintrag", 
                "Diese Karteikarte ist noch nicht in der Datenbank.\n\n"
                "Nutzen Sie zuerst '💽 In DB speichern', um die Karteikarte zu speichern."
            )
            return
        
        try:
            fields = self._last_recognized_fields if hasattr(self, '_last_recognized_fields') else {}
            vorname = self._get_ocr_field_value('vorname') or fields.get('vorname')
            nachname = self._get_ocr_field_value('nachname') or fields.get('nachname')
            partner = self._get_ocr_field_value('partner') or fields.get('partner')
            beruf = self._get_ocr_field_value('beruf') or fields.get('beruf')
            ort = self._get_ocr_field_value('ort') or fields.get('ort')
            seite_value = self._get_ocr_field_value('seite') or fields.get('seite')
            seite = int(seite_value) if seite_value else None
            nummer_value = self._get_ocr_field_value('nummer') or fields.get('nummer')
            nummer = int(nummer_value) if nummer_value else None
            todestag = self._get_ocr_field_value('todestag') or fields.get('todestag')
            stand = self._get_ocr_field_value('stand') or fields.get('stand')
            braut_stand = self._get_ocr_field_value('braut stand') or fields.get('stand')
            braeutigam_stand = self._get_ocr_field_value('bräutigam stand') or fields.get('braeutigam_stand')
            braeutigam_vater = self._get_ocr_field_value('bräutigam vater') or fields.get('braeutigam_vater')
            braut_vater = self._get_ocr_field_value('braut vater') or fields.get('braut_vater')
            braut_nachname = self._get_ocr_field_value('braut nachname') or fields.get('braut_nachname')
            braut_ort = self._get_ocr_field_value('braut ort') or fields.get('braut_ort')
            kirchenbuchtext = self.kirchenbuch_text_display.get("1.0", tk.END).strip()
            kirchenbuchtext = kirchenbuchtext if kirchenbuchtext else None
            fid = self.fid_entry.get().strip()
            fid = fid if fid else None
            gramps = self.gramps_entry.get().strip()
            gramps = gramps if gramps else None
            geb_jahr_value = self._get_ocr_field_value('geb.jahr (gesch.)')
            if geb_jahr_value:
                try:
                    geb_jahr_gesch = int(geb_jahr_value)
                except ValueError:
                    geb_jahr_gesch = None
            else:
                geb_jahr_gesch = fields.get('geb_jahr_gesch')

            cursor = self.db.conn.cursor()
            cursor.execute("SELECT ereignis_typ FROM karteikarten WHERE id = ?", (self.current_db_record_id,))
            typ_row = cursor.fetchone()
            ereignis_typ = typ_row[0] if typ_row else None
            is_marriage = False
            if ereignis_typ:
                is_marriage = str(ereignis_typ).lower().startswith('heirat')
            if not is_marriage:
                is_marriage = any([
                    braeutigam_stand, braeutigam_vater, braut_vater, braut_nachname, braut_ort
                ])
            cursor = self.db.conn.cursor()
            
            # Prüfe ob es Heirats- oder Begräbnis-Felder sind
            if is_marriage:
                # Heirats-Update
                cursor.execute("""
                    UPDATE karteikarten SET
                        vorname = ?, nachname = ?, partner = ?, beruf = ?, stand = ?, ort = ?, seite = ?, nummer = ?,
                        braeutigam_stand = ?, braeutigam_vater = ?, braut_vater = ?, braut_nachname = ?, braut_ort = ?,
                        kirchenbuchtext = ?,
                        notiz = ?,
                        gramps = ?,
                        aktualisiert_am = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    vorname, nachname, partner,
                    beruf, braut_stand or stand, ort, seite, nummer,
                    braeutigam_stand, braeutigam_vater, braut_vater,
                    braut_nachname, braut_ort,
                    kirchenbuchtext,
                    fid,
                    gramps,
                    self.current_db_record_id
                ))
            else:
                # Begräbnis-Update
                cursor.execute("""
                    UPDATE karteikarten SET
                        vorname = ?, nachname = ?, partner = ?, beruf = ?, stand = ?, todestag = ?, ort = ?, seite = ?, nummer = ?, geb_jahr_gesch = ?,
                        kirchenbuchtext = ?,
                        notiz = ?,
                        gramps = ?,
                        aktualisiert_am = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    vorname, nachname, partner,
                    beruf, stand, todestag, ort, seite, nummer,
                    geb_jahr_gesch,
                    kirchenbuchtext,
                    fid,
                    gramps,
                    self.current_db_record_id
                ))
            
            self.db.conn.commit()
            
            # Update Status-Label
            self.db_record_status.config(
                text=f"✓ Felder in DB gespeichert (ID: {self.current_db_record_id})",
                foreground="green"
            )
            
            # Aktualisiere DB-Liste im Datenbank-Tab
            self._refresh_db_list()
            
            messagebox.showinfo(
                "Erfolg", 
                f"Felder erfolgreich in Datenbank gespeichert!\n\n"
                f"Datenbank-ID: {self.current_db_record_id}"
            )
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Speichern in DB:\n{e}")

    def _show_current_kirchenbuch(self):
        """Zeigt das Kirchenbuchbild für die aktuell im OCR-Tab angezeigte Karteikarte an."""
        # Extrahiere Typ, Jahr und Seite NUR aus dem erkannten Text
        text = self.text_display.get("1.0", tk.END).strip()
        
        if not text:
            messagebox.showwarning("Kein Text", "Bitte zuerst eine Karteikarte laden und Text erkennen.")
            return
        
        import re
        from pathlib import Path

        # Versuche Typ, Jahr und Seite aus dem erkannten Text zu extrahieren
        # Format: "ev. Kb. Wetzlar ⚰ 1687.05.13. p. 99 Nr. 1"
        typ = None
        jahr = None
        seite = None
        
        # Erkenne Typ aus Symbol im Text
        if "⚰" in text:
            typ = "Begräbnis"
        elif "∞" in text:
            typ = "Heirat"
        elif "Gb" in text or "gb" in text:
            typ = "Taufe"
        
        # Extrahiere Jahr (4-stellige Zahl am Anfang der Datumsangabe)
        jahr_match = re.search(r"(\d{4})\.\d{2}\.\d{2}", text)
        if jahr_match:
            jahr = int(jahr_match.group(1))
        
        # Extrahiere Seite (p. XX)
        seite_match = re.search(r"p\.?\s*(\d+)", text, re.IGNORECASE)
        if seite_match:
            seite = int(seite_match.group(1))
        
        if not all([typ, jahr, seite]):
            messagebox.showerror(
                "Fehlende Informationen",
                f"Konnte nicht alle benötigten Informationen extrahieren:\n\n"
                f"Typ: {typ or 'nicht gefunden'}\n"
                f"Jahr: {jahr or 'nicht gefunden'}\n"
                f"Seite: {seite or 'nicht gefunden'}\n\n"
                f"Bitte stellen Sie sicher, dass der Text die Zitation enthält,\n"
                f"z.B.: 'ev. Kb. Wetzlar ⚰ 1687.05.13. p. 99 Nr. 1'"
            )
            return
        
        # Finde passende Quelle aus SOURCES
        passende_quellen = []
        for source in SOURCES:
            if source.get("media_type") != "kirchenbuchseiten":
                continue
            if not source.get("media_ID") or not source.get("media_path"):
                continue
            
            # Extrahiere Jahresbereich aus source name
            source_name = source["source"]
            jahr_match = re.search(r"(\d{4})-(\d{4})", source_name)
            if jahr_match:
                jahr_von = int(jahr_match.group(1))
                jahr_bis = int(jahr_match.group(2))
                
                if jahr_von <= jahr <= jahr_bis:
                    # Bestimme Typ-Kürzel
                    typ_kuerzel = None
                    if typ == "Begräbnis":
                        typ_kuerzel = "Sb"
                    elif typ == "Heirat":
                        typ_kuerzel = "Hb"
                    elif typ == "Taufe":
                        typ_kuerzel = "Gb"
                    
                    media_id = source.get("media_ID", "")
                    if typ_kuerzel and media_id.endswith(f"_{typ_kuerzel}"):
                        passende_quellen.append(source)
        
        if not passende_quellen:
            kb_quellen = [s for s in SOURCES if s.get("media_type") == "kirchenbuchseiten"]
            quellen_info = "\n".join([f"  - {s['source']} (media_ID: {s.get('media_ID', 'N/A')})" for s in kb_quellen])
            
            # Bestimme gesuchtes Typ-Kürzel
            typ_kuerzel = None
            if typ == "Begräbnis":
                typ_kuerzel = "Sb"
            elif typ == "Heirat":
                typ_kuerzel = "Hb"
            elif typ == "Taufe" or typ == "Geburt":
                typ_kuerzel = "Gb"
            
            messagebox.showerror(
                "Keine Quelle gefunden",
                f"Keine passende Kirchenbuch-Quelle für:\n"
                f"Typ: {typ} (Suche nach: _{typ_kuerzel})\n"
                f"Jahr: {jahr}\n"
                f"Seite: {seite}\n\n"
                f"Verfügbare Kirchenbuch-Quellen:\n{quellen_info}\n\n"
                f"Hinweis: Jahr muss im Bereich der Quelle liegen\n"
                f"und media_ID muss mit _{typ_kuerzel} enden."
            )
            return
        
        # Verwende erste passende Quelle
        quelle = passende_quellen[0]
        media_id = quelle["media_ID"]
        ordner = Path(quelle["media_path"])
        
        if not ordner.exists():
            messagebox.showerror(
                "Ordner nicht gefunden",
                f"Der Suchpfad existiert nicht:\n\n"
                f"Quelle: {quelle['source']}\n"
                f"Pfad: {ordner}"
            )
            return
        
        # Baue Dateiname nach EKiR-Format
        media_id_prefix = media_id[:-3]  # Entferne "_Sb", "_Hb", "_Gb"
        
        # Unterstütze sowohl 3-stellige als auch 4-stellige Seitenzahlen
        seite_str_3 = f"{seite:03d}"  # 3-stellig: 88 -> "088"
        seite_str_4 = f"{seite:04d}"  # 4-stellig: 88 -> "0088"
        
        # Teste mehrere Patterns - für BEIDE Formate (3- und 4-stellig)
        # Wichtig: Patterns müssen spezifisch sein, damit z.B. "0002" nicht auch "0022" findet!
        patterns = [
            # 4-stellige Varianten - mit Trennzeichen um False Positives zu vermeiden
            f"{media_id_prefix}* S_{seite_str_4}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4} Sterbebuch.jpg",
            # 3-stellige Varianten - mit Trennzeichen um False Positives zu vermeiden
            f"{media_id_prefix}* S_{seite_str_3}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_3}.jpg",
            f"{media_id_prefix}*_{seite_str_3}.jpg",
        ]
        
        # Teste alle Patterns
        treffer = []
        for pattern in patterns:
            pattern_treffer = list(ordner.glob(pattern))
            if pattern_treffer:
                treffer.extend(pattern_treffer)
        
        # Duplikate entfernen (falls mehrere Patterns dieselbe Datei finden)
        treffer = list(set(treffer))
        
        if not treffer:
            # Zeige alle getesteten Patterns
            alle_jpgs = list(ordner.glob("*.jpg"))
            beispiel_dateien = "\n".join([f"  - {f.name}" for f in alle_jpgs[:10]])
            
            # Liste getestete Patterns
            pattern_liste = "\n".join([f"  - {p}" for p in patterns])
            
            messagebox.showerror(
                "Bild nicht gefunden",
                f"Kein Bild gefunden für:\n"
                f"Quelle: {quelle['source']}\n"
                f"Media-ID: {media_id}\n"
                f"Jahr: {jahr}\n"
                f"Seite: {seite}\n\n"
                f"Suchpfad: {ordner}\n\n"
                f"Getestete Patterns:\n{pattern_liste}\n\n"
                f"Beispiel-Dateien im Ordner ({len(alle_jpgs)} gesamt):\n{beispiel_dateien}"
            )
            return
        
        if len(treffer) > 1:
            messagebox.showwarning(
                "Mehrere Bilder gefunden",
                f"Mehrere Bilder gefunden. Es wird das erste angezeigt:\n" +
                "\n".join([t.name for t in treffer])
            )
        
        pfad = treffer[0]
        self._open_image_viewer(str(pfad))

    def _open_current_card_in_irfanview(self):
        """Öffnet die aktuell angezeigte Karteikarte in IrfanView."""
        import shutil
        import subprocess

        if not self.current_image:
            messagebox.showwarning("Keine Karteikarte", "Es ist aktuell keine Karteikarte geladen.")
            return

        image_path = Path(self.current_image)
        if not image_path.exists():
            messagebox.showerror("Datei nicht gefunden", f"Die Bilddatei wurde nicht gefunden:\n{image_path}")
            return

        candidates = []

        # 1) IrfanView aus PATH ermitteln
        for cmd in ("i_view64.exe", "i_view32.exe", "i_view64", "i_view32"):
            resolved = shutil.which(cmd)
            if resolved:
                candidates.append(Path(resolved))

        # 2) Typische Installationspfade prüfen
        for path in (
            Path(r"C:\Program Files\IrfanView\i_view64.exe"),
            Path(r"C:\Program Files (x86)\IrfanView\i_view32.exe"),
        ):
            if path.exists() and path not in candidates:
                candidates.append(path)

        if not candidates:
            messagebox.showerror(
                "IrfanView nicht gefunden",
                "IrfanView wurde nicht gefunden.\n\n"
                "Bitte installieren Sie IrfanView oder stellen Sie sicher, dass\n"
                "i_view64.exe / i_view32.exe im PATH verfügbar ist."
            )
            return

        try:
            subprocess.Popen([str(candidates[0]), str(image_path)], shell=False)
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte IrfanView nicht starten:\n{e}")

            
    def _create_widgets(self):
        """Erstellt alle GUI-Elemente."""
        # Notebook (Tab-System) erstellen
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        
        # Tab 1: OCR-Ansicht
        ocr_tab = ttk.Frame(self.notebook)
        self.ocr_tab = ocr_tab
        self.notebook.add(ocr_tab, text="📸 OCR-Erkennung")
        
        # Tab 2: Datenbank-Ansicht
        db_tab = ttk.Frame(self.notebook)
        self.notebook.add(db_tab, text="📊 Datenbank")
        
        # Tab 3: Einstellungen
        settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(settings_tab, text="⚙️ Einstellungen")
        
        # Erstelle OCR-Tab Inhalt
        self._create_ocr_tab(ocr_tab)
        
        # Erstelle DB-Tab Inhalt
        self._create_db_tab(db_tab)
        
        # Erstelle Einstellungen-Tab Inhalt
        self._create_settings_tab(settings_tab)

        # Tab-Wechsel überwachen
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)
    
    def _create_ocr_tab(self, parent):
        """Erstellt den OCR-Tab Inhalt."""
        # Hauptcontainer mit zwei Spalten
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # NEU: Verzeichnis-Auswahl am Anfang
        folder_frame = ttk.Frame(main_frame)
        folder_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(folder_frame, text="Bildverzeichnis:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        
        folder_entry = ttk.Entry(folder_frame, textvariable=self.image_folder_var, width=50)
        folder_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        folder_btn = ttk.Button(folder_frame, text="📁 Ändern", command=self._change_folder)
        folder_btn.pack(side=tk.LEFT, padx=5)
        
        reload_btn = ttk.Button(folder_frame, text="🔄 Neu laden", command=self._reload_images)
        reload_btn.pack(side=tk.LEFT, padx=2)
        
        # Linke Seite: Bildanzeige
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Label für Bildanzeige
        self.image_label = ttk.Label(left_frame, text="Karteikarte wird geladen...", 
                                     relief=tk.SUNKEN, anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # Navigationsbuttons - ZEILE 1: Bild-Navigation
        nav_frame_1 = ttk.Frame(left_frame)
        nav_frame_1.pack(fill=tk.X, pady=(10, 5))
        
        self.prev_btn = ttk.Button(nav_frame_1, text="◀ Vorherige", command=self._previous_card)
        self.prev_btn.pack(side=tk.LEFT, padx=5)
        
        self.next_btn = ttk.Button(nav_frame_1, text="Nächste ▶", command=self._next_card)
        self.next_btn.pack(side=tk.LEFT, padx=5)
        
        self.position_label = ttk.Label(nav_frame_1, text="Karte 0 von 0")
        self.position_label.pack(side=tk.LEFT, padx=20)
        
        # OCR-Einstellungen und Batch - ZEILE 2
        nav_frame_2 = ttk.Frame(left_frame)
        nav_frame_2.pack(fill=tk.X, pady=(5, 0))
        
        # Checkbox für Bildvorverarbeitung
        self.preprocess_var = tk.BooleanVar(value=True)
        preprocess_check = ttk.Checkbutton(nav_frame_2, text="Bildvorverarbeitung", 
                                          variable=self.preprocess_var)
        preprocess_check.pack(side=tk.LEFT, padx=5)
        
        # Checkbox für Text-Nachbearbeitung
        self.postprocess_var = tk.BooleanVar(value=True)
        postprocess_check = ttk.Checkbutton(nav_frame_2, text="Text-Korrektur", 
                                           variable=self.postprocess_var)
        postprocess_check.pack(side=tk.LEFT, padx=5)
        
        # Batch-Scan Frame (rechts)
        batch_frame = ttk.Frame(nav_frame_2)
        batch_frame.pack(side=tk.RIGHT, padx=5)
        
        # Bildtyp-Filter für Batch-Scan
        ttk.Label(batch_frame, text="Typ:").pack(side=tk.LEFT, padx=2)
        self.batch_type_var = tk.StringVar(value="Alle")
        batch_type_combo = ttk.Combobox(
            batch_frame, 
            textvariable=self.batch_type_var, 
            width=8,
            values=["Alle", "Hb", "Gb", "Sb"],
            state="readonly"
        )
        batch_type_combo.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(batch_frame, text="Anzahl:").pack(side=tk.LEFT, padx=(10, 2))
        self.batch_count_var = tk.StringVar(value="10")
        batch_count_entry = ttk.Entry(batch_frame, textvariable=self.batch_count_var, width=5)
        batch_count_entry.pack(side=tk.LEFT, padx=2)
        
        self.batch_btn = ttk.Button(batch_frame, text="⚡ Batch-Scan", command=self._batch_scan)
        self.batch_btn.pack(side=tk.LEFT, padx=2)
        
        self.ocr_btn = ttk.Button(nav_frame_2, text="🔍 Text erkennen", command=self._run_ocr)
        self.ocr_btn.pack(side=tk.RIGHT, padx=5)
        
        # OCR-Methode Auswahl - ZEILE 3
        ocr_frame = ttk.Frame(left_frame)
        ocr_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(ocr_frame, text="OCR-Methode:").pack(side=tk.LEFT, padx=5)
        
        self.ocr_method_var = tk.StringVar(value="easyocr")
        ocr_methods = [
            ("EasyOCR (lokal)", "easyocr"),
            ("Tesseract (lokal)", "tesseract"),
            ("Cloud Vision (Google)", "cloud_vision")
        ]
        
        for text, value in ocr_methods:
            ttk.Radiobutton(ocr_frame, text=text, variable=self.ocr_method_var, 
                          value=value, command=self._change_ocr_method).pack(side=tk.LEFT, padx=5)
        
        # Cloud Vision Credentials Button
        self.credentials_btn = ttk.Button(ocr_frame, text="📁 Credentials (optional)", 
                                         command=self._select_credentials)
        self.credentials_btn.pack(side=tk.LEFT, padx=5)
        self.credentials_btn.config(state=tk.DISABLED)
        
        # Info-Label für Cloud Vision
        self.cloud_info_label = ttk.Label(ocr_frame, text="", foreground="blue", font=("Arial", 8))
        self.cloud_info_label.pack(side=tk.LEFT, padx=5)
        
        # Rechte Seite: Dateiinfo und erkannter Text
        right_frame = ttk.Frame(main_frame, width=700)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
        right_frame.pack_propagate(False)
        
        # Dateiname
        filename_label = ttk.Label(right_frame, text="Dateiname:", font=("Arial", 10, "bold"))
        filename_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.filename_text = tk.Text(right_frame, height=3, wrap=tk.WORD, 
                                     font=("Arial", 9), relief=tk.SUNKEN)
        self.filename_text.pack(fill=tk.X, pady=(0, 20))
        self.filename_text.config(state=tk.DISABLED)
        
        # Erkannter Text
        text_label = ttk.Label(right_frame, text="Erkannter Text:", font=("Arial", 10, "bold"))
        text_label.pack(anchor=tk.W, pady=(0, 5))
        
        # Scrollbarer Textbereich - VERKLEINERT von 180 auf 120 für mehr Platz für erkannte Felder
        text_frame = ttk.Frame(right_frame, height=120)
        text_frame.pack(fill=tk.BOTH, expand=False)
        text_frame.pack_propagate(False)
        
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.text_display = tk.Text(text_frame, wrap=tk.WORD, font=("Arial", 14),
                                   yscrollcommand=scrollbar.set)
        self.text_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_display.yview)
        
        # Hilfsfunktion: ∞-Symbol einfügen
        def insert_infinity():
            self.text_display.insert(tk.INSERT, "∞")
            return "break"
        
        # Tastenkombination Strg+H für ∞-Symbol
        self.text_display.bind('<Control-h>', lambda e: insert_infinity())
        self.text_display.bind('<Control-H>', lambda e: insert_infinity())
        
        # Buttons-Frame
        buttons_frame = ttk.Frame(right_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        
        # DB-Status-Label
        self.db_record_status = ttk.Label(buttons_frame, text="", foreground="blue", font=("Arial", 9))
        self.db_record_status.pack(side=tk.TOP, anchor=tk.W, pady=(0, 5))
        
        # Button-Reihe für Sonderzeichen
        special_chars_frame = ttk.Frame(buttons_frame)
        special_chars_frame.pack(side=tk.TOP, anchor=tk.W, pady=(0, 5))
        
        ttk.Label(special_chars_frame, text="Schnelleingabe:").pack(side=tk.LEFT, padx=(0, 5))
        
        # Buttons in gewünschter Reihenfolge: ev. Kb. Wetzlar - ∞ Heirat - p. - Nr.
        kb_btn = ttk.Button(
            special_chars_frame,
            text="ev. Kb. Wetzlar",
            width=15,
            command=lambda: self.text_display.insert(tk.INSERT, "ev. Kb. Wetzlar ")
        )
        kb_btn.pack(side=tk.LEFT, padx=2)

        infinity_btn = ttk.Button(
            special_chars_frame, 
            text="∞ Heirat", 
            width=10,
            command=lambda: self.text_display.insert(tk.INSERT, "∞")
        )
        infinity_btn.pack(side=tk.LEFT, padx=2)

        coffin_btn = ttk.Button(
            special_chars_frame,
            text="⚰ Begraben",
            width=10,
            command=lambda: self.text_display.insert(tk.INSERT, "⚰")
        )
        coffin_btn.pack(side=tk.LEFT, padx=2)

        p_btn = ttk.Button(
            special_chars_frame,
            text="p.",
            width=5,
            command=lambda: self.text_display.insert(tk.INSERT, "p. ")
        )
        p_btn.pack(side=tk.LEFT, padx=2)

        nr_btn = ttk.Button(
            special_chars_frame,
            text="Nr.",
            width=5,
            command=lambda: self.text_display.insert(tk.INSERT, "Nr. ")
        )
        nr_btn.pack(side=tk.LEFT, padx=2)

        # Button "LÜCKE" in zweiter Reihe hinter "Nr."-Button
        luecke_btn = ttk.Button(
            special_chars_frame,
            text="LÜCKE",
            width=8,
            command=lambda: self.text_display.insert(tk.INSERT, "[LÜCKE] ")
        )
        luecke_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(special_chars_frame, text="(Strg+H für ∞)", font=("Arial", 8), foreground="gray").pack(side=tk.LEFT, padx=5)
        
        # NEU: Eingabefeld für Kirchenbuchtext (unter "Erkannter Text")
        kb_text_frame = ttk.LabelFrame(right_frame, text="Kirchenbuchtext (optional)", padding=5)
        kb_text_frame.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
        kb_text_frame.pack_propagate(False)
        kb_text_frame.config(height=100)
        
        kb_scrollbar = ttk.Scrollbar(kb_text_frame)
        kb_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.kirchenbuch_text_display = tk.Text(kb_text_frame, wrap=tk.WORD, font=("Arial", 11),
                                                yscrollcommand=kb_scrollbar.set)
        self.kirchenbuch_text_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        kb_scrollbar.config(command=self.kirchenbuch_text_display.yview)
        
        # Haupt-Buttons in zweiter Reihe
        action_buttons_frame = ttk.Frame(buttons_frame)
        action_buttons_frame.pack(side=tk.TOP, anchor=tk.W, pady=(5, 0))
       
        # Speichern-Buttons
        save_text_btn = ttk.Button(action_buttons_frame, text="💾 Text speichern", command=self._save_text)
        save_text_btn.pack(side=tk.LEFT, padx=5)
        
        self.save_db_btn = ttk.Button(action_buttons_frame, text="💽 In DB speichern", command=self._save_to_database)
        self.save_db_btn.pack(side=tk.LEFT, padx=5)
        
        # Erkennung-Button
        recognize_btn = ttk.Button(action_buttons_frame, text="🧠 Felder erkennen", command=self._run_recognition_ocr_tab)
        recognize_btn.pack(side=tk.LEFT, padx=5)
        
        # DB-Update-Button (für erkannte Felder)
        update_db_btn = ttk.Button(action_buttons_frame, text="📤 DB aktualisieren", command=self._update_db_fields)
        update_db_btn.pack(side=tk.LEFT, padx=5)
        
        # Dritte Reihe für Kirchenbuch-Button und F-ID Feld
        action_buttons_frame2 = ttk.Frame(buttons_frame)
        action_buttons_frame2.pack(side=tk.TOP, anchor=tk.W, pady=(5, 0))

        # Button zum Öffnen der aktuellen Karteikarte in IrfanView
        irfan_btn = ttk.Button(action_buttons_frame2, text="in Irfanview", command=self._open_current_card_in_irfanview)
        irfan_btn.pack(side=tk.LEFT, padx=5)
        
        # Button zum Anzeigen des Kirchenbuchs
        show_kb_btn = ttk.Button(action_buttons_frame2, text="📖 Kirchenbuch anzeigen", command=self._show_current_kirchenbuch)
        show_kb_btn.pack(side=tk.LEFT, padx=5)
        
        # Notiz-Feld (für beliebigen Text wie F-ID, Namen, etc.)
        ttk.Label(action_buttons_frame2, text="Notiz:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(20, 5))
        self.fid_entry = ttk.Entry(action_buttons_frame2, width=35, font=("Arial", 10))
        self.fid_entry.pack(side=tk.LEFT, padx=5)
        
        # Gramps-Feld
        ttk.Label(action_buttons_frame2, text="Gramps:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(15, 5))
        self.gramps_entry = ttk.Entry(action_buttons_frame2, width=15, font=("Arial", 10))
        self.gramps_entry.pack(side=tk.LEFT, padx=5)
        
        # Frame für erkannte Felder MIT SCROLLBAR
        fields_frame = ttk.LabelFrame(right_frame, text="Erkannte Felder", padding=0)
        fields_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # Canvas mit Scrollbar für das Feld-Grid
        fields_canvas = tk.Canvas(fields_frame, highlightthickness=0)
        fields_scrollbar = ttk.Scrollbar(fields_frame, orient="vertical", command=fields_canvas.yview)
        fields_canvas.configure(yscrollcommand=fields_scrollbar.set)
        
        # Platziere Canvas und Scrollbar
        fields_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fields_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Frame im Canvas für die Felder
        fields_inner = ttk.Frame(fields_canvas)
        fields_canvas_window = fields_canvas.create_window((0, 0), window=fields_inner, anchor="nw")
        
        # Binding für Scrollrad und Größenänderung
        def on_fields_canvas_configure(event=None):
            fields_canvas.configure(scrollregion=fields_canvas.bbox("all"))
            # Mache das innere Frame so breit wie der Canvas
            fields_canvas.itemconfig(fields_canvas_window, width=event.width if event else fields_canvas.winfo_width())
        
        fields_inner.bind("<Configure>", on_fields_canvas_configure)
        fields_canvas.bind("<Configure>", lambda e: fields_canvas.itemconfig(fields_canvas_window, width=e.width))
        
        # Mausrad-Scrolling
        def on_mousewheel(event):
            fields_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        fields_canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # 2-Spalten-Layout für erkannte Felder
        # Labels für Feldnamen (links) und editierbare Werte (rechts)
        field_names = ["Vorname:", "Nachname:", "Partner:", "Stand:", "Braut Stand:", "Beruf:", "Ort:", 
                      "Seite:", "Nummer:", "Todestag:", "Geb.Jahr (gesch.):", "Bräutigam Stand:", "Bräutigam Vater:", "Braut Vater:", "Braut Nachname:", "Braut Ort:"]
        self.ocr_field_labels = {}
        self.ocr_field_vars = {}
        
        for i, field_name in enumerate(field_names):
            # Label (links)
            label = ttk.Label(fields_inner, text=field_name, font=("Arial", 9, "bold"), anchor=tk.W, width=16)
            label.grid(row=i, column=0, sticky=tk.W, pady=2, padx=(0, 10))
            
            # Wert (rechts) - editierbar
            field_key = field_name.rstrip(':').lower()
            var = tk.StringVar(value="")
            
            # Spezialbehandlung für Geb.Jahr (gesch.): Zeige Feld + Editor-Button
            if field_key == 'geb.jahr (gesch.)':
                value_frame = ttk.Frame(fields_inner)
                value_frame.grid(row=i, column=1, sticky=tk.W, pady=2)
                
                value_entry = ttk.Entry(value_frame, textvariable=var, font=("Arial", 9), width=10, state='readonly')
                value_entry.pack(side=tk.LEFT, padx=(0, 5))
                
                edit_btn = ttk.Button(
                    value_frame, 
                    text="✏️ Alter eingeben", 
                    width=15,
                    command=self._edit_geb_jahr_gesch
                )
                edit_btn.pack(side=tk.LEFT)
            else:
                value_entry = ttk.Entry(fields_inner, textvariable=var, font=("Arial", 9), width=28)
                value_entry.grid(row=i, column=1, sticky=tk.W, pady=2)

            # Speichere Referenz für spätere Updates
            self.ocr_field_labels[field_key] = value_entry
            self.ocr_field_vars[field_key] = var
        
        # Grid-Spalte 1 soll expandieren
        fields_inner.columnconfigure(1, weight=1)
    
    def _create_db_tab(self, parent):
        """Erstellt den Datenbank-Tab mit Listing und Filter."""

        # Oberer Bereich: Filter und Suche (aufgeteilt in 3 Zeilen für bessere Sichtbarkeit)
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill=tk.X, padx=10, pady=10)

        # === ZEILE 1: FILTER ===
        filter_row1 = ttk.Frame(filter_frame)
        filter_row1.pack(fill=tk.X, pady=(0, 5))

        # ID-Filter
        ttk.Label(filter_row1, text="ID:").pack(side=tk.LEFT, padx=5)
        self.id_filter = ttk.Entry(filter_row1, width=8)
        self.id_filter.pack(side=tk.LEFT, padx=5)

        # Jahr-Filter
        ttk.Label(filter_row1, text="Jahr:").pack(side=tk.LEFT, padx=(10, 5))
        self.year_filter = ttk.Combobox(filter_row1, width=10, state='readonly')
        self.year_filter.pack(side=tk.LEFT, padx=5)
        self.year_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # Ereignistyp-Filter
        ttk.Label(filter_row1, text="Typ:").pack(side=tk.LEFT, padx=(10, 5))
        self.type_filter = ttk.Combobox(filter_row1, width=15, state='readonly')
        self.type_filter['values'] = ['Alle', 'Heirat', 'Taufe', 'Begräbnis', '(Leere)']
        self.type_filter.current(0)
        self.type_filter.pack(side=tk.LEFT, padx=5)
        self.type_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # Dateinamen-Filter
        ttk.Label(filter_row1, text="Datei:").pack(side=tk.LEFT, padx=(10, 5))
        self.filename_filter = ttk.Combobox(filter_row1, width=10, state='readonly')
        self.filename_filter['values'] = ['Alle', 'Sb', 'Hb', 'Gb']
        self.filename_filter.current(0)
        self.filename_filter.pack(side=tk.LEFT, padx=5)
        self.filename_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # Kirchenbuch-Filter (z.B. "Hb 1695-1718" aus Dateiname)
        ttk.Label(filter_row1, text="Kirchenbuch:").pack(side=tk.LEFT, padx=(10, 5))
        self.kirchenbuch_filter = ttk.Combobox(filter_row1, width=16, state='readonly')
        self.kirchenbuch_filter['values'] = ['Alle']
        self.kirchenbuch_filter.current(0)
        self.kirchenbuch_filter.pack(side=tk.LEFT, padx=5)
        self.kirchenbuch_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # === ZEILE 2: SUCHE & ERSETZEN ===
        filter_row2 = ttk.Frame(filter_frame)
        filter_row2.pack(fill=tk.X, pady=(0, 5))

        # Namenssuche
        ttk.Label(filter_row2, text="Name:").pack(side=tk.LEFT, padx=5)
        self.name_search = ttk.Entry(filter_row2, width=20)
        self.name_search.pack(side=tk.LEFT, padx=5)
        # Enter-Taste im Namens-Suchfeld löst Suche aus
        self.name_search.bind('<Return>', lambda e: self._refresh_db_list())

        # Checkbox für Regex-Suche
        self.regex_search_var = tk.BooleanVar(value=False)
        self.regex_search_cb = ttk.Checkbutton(filter_row2, text="Regex", variable=self.regex_search_var)
        self.regex_search_cb.pack(side=tk.LEFT, padx=5)

        search_btn = ttk.Button(filter_row2, text="🔍 Suchen", command=self._refresh_db_list)
        search_btn.pack(side=tk.LEFT, padx=5)

        # Trennlinie
        ttk.Separator(filter_row2, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Eingabefeld für Ersetzen-Text
        ttk.Label(filter_row2, text="Ersetzen:").pack(side=tk.LEFT, padx=(0, 5))
        self.replace_entry = ttk.Entry(filter_row2, width=20)
        self.replace_entry.pack(side=tk.LEFT, padx=5)
        self.replace_entry.insert(0, "Ersetzen Text")

        # Button für Ersetzen
        def replace_selected_text():
            search_text = self.name_search.get().strip()
            replace_text = self.replace_entry.get()  # NICHT strippen - Leerzeichen erlauben!
            use_regex = self.regex_search_var.get()
            selection = self.tree.selection()
            if not selection:
                messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
                return
            if not search_text:
                messagebox.showwarning("Kein Suchtext", "Bitte einen Suchtext eingeben.")
                return
            # Ersetzen-Text darf leer sein (zum Löschen von Textstellen)
            # Warnung nur wenn Platzhaltertext noch drin steht
            if replace_text == "Ersetzen Text":
                if not messagebox.askyesno("Platzhalter?", 
                    "Der Ersetzungstext ist noch der Platzhalter 'Ersetzen Text'.\n\n"
                    "Möchten Sie wirklich damit ersetzen?"):
                    return
            
            erfolge = 0
            fehler = 0
            keine_aenderung = 0
            cursor = self.db.conn.cursor()
            for item in selection:
                record_id = self.tree.item(item)['values'][0]
                try:
                    cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                    row = cursor.fetchone()
                    if row:
                        original_text = row[0]
                        if use_regex:
                            # Regex-Ersetzung
                            import re
                            try:
                                new_text = re.sub(search_text, replace_text, original_text, flags=re.IGNORECASE)
                            except re.error as e:
                                messagebox.showerror("Regex-Fehler", f"Ungültiger Regex-Ausdruck:\n{e}")
                                return
                        else:
                            # Normale String-Ersetzung
                            new_text = original_text.replace(search_text, replace_text)
                        
                        if new_text == original_text:
                            keine_aenderung += 1
                            continue
                        cursor.execute("UPDATE karteikarten SET erkannter_text = ?, aktualisiert_am = CURRENT_TIMESTAMP WHERE id = ?", (new_text, record_id))
                        erfolge += 1
                except Exception as e:
                    fehler += 1
                    print(f"Fehler bei ID {record_id}: {str(e)}")
            self.db.conn.commit()
            self._refresh_db_list()
            messagebox.showinfo(
                "Ersetzen abgeschlossen",
                f"Erfolgreich geändert: {erfolge}\nKeine Änderung nötig: {keine_aenderung}\nFehler: {fehler}"
            )

        replace_btn = ttk.Button(filter_row2, text="✓ Ersetzen", command=replace_selected_text)
        replace_btn.pack(side=tk.LEFT, padx=5)

        # === ZEILE 3: AKTIONEN ===
        filter_row3 = ttk.Frame(filter_frame)
        filter_row3.pack(fill=tk.X)

        clear_btn = ttk.Button(filter_row3, text="✕ Filter löschen", command=self._clear_filters)
        clear_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = ttk.Button(filter_row3, text="🔄 Aktualisieren", command=self._refresh_db_list)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        # Trennlinie
        ttk.Separator(filter_row3, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Button: Leere in sortierter Spalte auswählen
        select_empty_btn = ttk.Button(filter_row3, text="⛶ Leere auswählen", command=self._select_empty_in_sorted_column)
        select_empty_btn.pack(side=tk.LEFT, padx=5)
        
        # Button zum Sortieren nach Seite/Nummer
        sort_page_btn = ttk.Button(filter_row3, text="📑 Nach Seite/Nr.", command=self._sort_by_page_and_number)
        sort_page_btn.pack(side=tk.LEFT, padx=5)
        
        # Button zum Filtern ungültiger Zitationen
        invalid_citation_btn = ttk.Button(filter_row3, text="⚠ Ungültige Zitationen", command=self._filter_invalid_citations)
        invalid_citation_btn.pack(side=tk.LEFT, padx=5)

        # Statistik-Button wie im Reader direkt im oberen Aktionsbereich
        statistics_btn = ttk.Button(filter_row3, text="📊 Statistik", command=self._show_statistics)
        statistics_btn.pack(side=tk.LEFT, padx=5)
        
        # Treeview mit Scrollbar
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Treeview
        columns = (
            'ID', 'Jahr', 'Datum', 'ISO_datum', 'Typ', 'Seite', 'Nr', 'Gemeinde',
            'Vorname', 'Nachname', 'Partner', 'Beruf', 'Ort',
            'Bräutigam Vater', 'Braut Vater', 'Braut Nachname', 'Braut Ort',
            'Bräutigam Stand', 'Braut Stand', 'Todestag', 'Geb.Jahr (gesch.)',
            'Dateiname', 'Notiz', 'Gramps', 'Text')
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show='headings',
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode='extended')
        
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)
        
        # Spalten konfigurieren
        self.tree.heading('ID', text='ID', command=lambda: self._sort_column('ID'))
        self.tree.heading('Jahr', text='Jahr', command=lambda: self._sort_column('Jahr'))
        self.tree.heading('Datum', text='Datum', command=lambda: self._sort_column('Datum'))
        self.tree.heading('ISO_datum', text='ISO Datum', command=lambda: self._sort_column('ISO_datum'))
        self.tree.heading('Typ', text='Typ', command=lambda: self._sort_column('Typ'))
        self.tree.heading('Seite', text='Seite', command=lambda: self._sort_column('Seite'))
        self.tree.heading('Nr', text='Nr', command=lambda: self._sort_column('Nr'))
        self.tree.heading('Gemeinde', text='Gemeinde', command=lambda: self._sort_column('Gemeinde'))
        self.tree.heading('Vorname', text='Vorname', command=lambda: self._sort_column('Vorname'))
        self.tree.heading('Nachname', text='Nachname', command=lambda: self._sort_column('Nachname'))
        self.tree.heading('Partner', text='Partner', command=lambda: self._sort_column('Partner'))
        self.tree.heading('Beruf', text='Beruf', command=lambda: self._sort_column('Beruf'))
        self.tree.heading('Ort', text='Ort', command=lambda: self._sort_column('Ort'))
        self.tree.heading('Bräutigam Vater', text='Bräutigam Vater', command=lambda: self._sort_column('Bräutigam Vater'))
        self.tree.heading('Braut Vater', text='Braut Vater', command=lambda: self._sort_column('Braut Vater'))
        self.tree.heading('Braut Nachname', text='Braut Nachname', command=lambda: self._sort_column('Braut Nachname'))
        self.tree.heading('Braut Ort', text='Braut Ort', command=lambda: self._sort_column('Braut Ort'))
        self.tree.heading('Bräutigam Stand', text='Bräutigam Stand', command=lambda: self._sort_column('Bräutigam Stand'))
        self.tree.heading('Braut Stand', text='Braut Stand', command=lambda: self._sort_column('Braut Stand'))
        self.tree.heading('Todestag', text='Todestag', command=lambda: self._sort_column('Todestag'))
        self.tree.heading('Geb.Jahr (gesch.)', text='Geb.Jahr (gesch.)', command=lambda: self._sort_column('Geb.Jahr (gesch.)'))
        self.tree.heading('Dateiname', text='Dateiname', command=lambda: self._sort_column('Dateiname'))
        self.tree.heading('Notiz', text='F-ID', command=lambda: self._sort_column('Notiz'))
        self.tree.heading('Gramps', text='Gramps', command=lambda: self._sort_column('Gramps'))
        self.tree.heading('Text', text='Erkannter Text', command=lambda: self._sort_column('Text'))

        self.tree.column('ID', width=20, anchor='center')
        self.tree.column('Jahr', width=40, anchor='center')
        self.tree.column('Datum', width=40, anchor='center')
        self.tree.column('ISO_datum', width=40, anchor='center')
        self.tree.column('Typ', width=10, anchor='w')
        self.tree.column('Seite', width=20, anchor='center')
        self.tree.column('Nr', width=20, anchor='center')
        self.tree.column('Gemeinde', width=60, anchor='w')
        self.tree.column('Vorname', width=80, anchor='w')
        self.tree.column('Nachname', width=80, anchor='w')
        self.tree.column('Partner', width=100, anchor='w')
        self.tree.column('Beruf', width=80, anchor='w')
        self.tree.column('Ort', width=80, anchor='w')
        self.tree.column('Bräutigam Vater', width=100, anchor='w')
        self.tree.column('Braut Vater', width=100, anchor='w')
        self.tree.column('Braut Nachname', width=100, anchor='w')
        self.tree.column('Braut Ort', width=80, anchor='w')
        self.tree.column('Bräutigam Stand', width=60, anchor='w')
        self.tree.column('Braut Stand', width=60, anchor='w')
        self.tree.column('Todestag', width=80, anchor='w')
        self.tree.column('Geb.Jahr (gesch.)', width=60, anchor='center')
        self.tree.column('Dateiname', width=80, anchor='w')
        self.tree.column('Notiz', width=8, anchor='center')
        self.tree.column('Gramps', width=10, anchor='center')
        self.tree.column('Text', width=400, anchor='w')
        
        # Spaltenbreiten aus Config laden
        self._apply_column_widths()
        
        # Spaltenbreiten-Änderungen speichern
        self.tree.bind('<Button-1>', self._on_column_resize, add='+')
        
        # Style für mehrzeilige Darstellung
        style = ttk.Style()
        style.configure("Treeview", rowheight=30)
        
        # Tag für Zeilen mit Notiz (grün)
        self.tree.tag_configure('has_notiz', background='#d4edda')
        
        # Tag für Zeilen mit Kirchenbuchtext (hellgrün)
        self.tree.tag_configure('has_kirchenbuchtext', background='#c3f0ca')
        
        # Tag für Zeilen mit Gramps (blau)
        self.tree.tag_configure('has_gramps', background='#cfe2ff')
        
        # NEU: Tag für ungültige Datumswerte (roter Text)
        self.tree.tag_configure('invalid_date', foreground='#dc3545', font=('Arial', 9, 'bold'))
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # Doppelklick zum Öffnen der Karteikarte
        self.tree.bind('<Double-1>', self._on_tree_double_click)
        
        # Rechtsklick-Menü
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="Erkennen", command=self._run_recognition_selected)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Karteikarte anzeigen", command=self._show_selected_card)
        self.tree_menu.add_command(label="Kirchenbuch anzeigen", command=self._show_selected_image)
        self.tree_menu.add_command(label="Text anzeigen", command=self._show_selected_text)
        self.tree_menu.add_command(label="F-ID bearbeiten", command=self._edit_fid)
        self.tree_menu.add_command(label="Auswahl kopieren", command=self._copy_selected_rows_to_clipboard)
        self.tree_menu.add_command(label="GEDCOM exportieren (Auswahl)", command=self._export_gedcom_selected_from_context)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Datensatz(e) löschen", command=self._delete_selected)
        self.tree.bind('<Button-3>', self._show_tree_menu)
        
        # Statusleiste
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.db_status_label = ttk.Label(status_frame, text="Keine Daten geladen")
        self.db_status_label.pack(side=tk.LEFT)
        
        # Buttons unten - Aufgeteilt in mehrere Zeilen für bessere Sichtbarkeit
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # ZEILE 1: Haupt-Aktionen
        button_row1 = ttk.Frame(button_frame)
        button_row1.pack(fill=tk.X, pady=(0, 3))
        
        ttk.Button(button_row1, text="📂 Bild", command=self._show_selected_image).pack(side=tk.LEFT, padx=3)    
        ttk.Button(button_row1, text="📤 Export CSV", command=self._export_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="� Export GEDCOM", command=self._export_gedcom).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="�📥 Import CSV", command=self._import_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="📥 Import XLSX", command=self._import_xlsx).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="🔄 Abgleich families_ok", command=self._abgleich_families_ok).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="🧠 Erkennung (Auswahl)", command=self._run_recognition_selected).pack(side=tk.LEFT, padx=3)
        
        # ZEILE 2: Text-Korrektur
        button_row2 = ttk.Frame(button_frame)
        button_row2.pack(fill=tk.X, pady=(0, 3))
        
        ttk.Button(button_row2, text="🔄 Text-Korrektur (alle)", command=self._reprocess_all_texts).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row2, text="🔧 Text-Korrektur (Auswahl)", command=self._reprocess_selected_texts).pack(side=tk.LEFT, padx=3)
        
        # ZEILE 3: Spezial-Korrekturen (Teil 1)
        button_row3 = ttk.Frame(button_frame)
        button_row3.pack(fill=tk.X, pady=(0, 3))
        
        ttk.Button(button_row3, text="∞ Wetzlar 00→∞", command=self._fix_wetzlar_infinity_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row3, text="∞ 16.1→161", command=self._fix_infinity_year_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row3, text="+ ev. Kb. Wetzlar", command=self._fix_header_prefix_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row3, text="+ ⚰ Begräbnis", command=self._insert_burial_symbol_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row3, text="+ ∞ Hochzeit", command=self._insert_marriage_symbol_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row3, text="ev. Kb. □ 1 → ⚰ 1", command=self._replace_ev_kb_wetzlar_special_selected).pack(side=tk.LEFT, padx=3)
        
        # ZEILE 4: Spezial-Korrekturen (Teil 2)
        button_row4 = ttk.Frame(button_frame)
        button_row4.pack(fill=tk.X, pady=(0, 3))
        
        ttk.Button(button_row4, text="p(Zahl) → p. (Zahl)", command=self._fix_p_number_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row4, text="📋 p/Nr. standardisieren", command=self._standardize_p_nr_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row4, text="📋 Zitation formatieren", command=self._format_citation_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row4, text="🔢 ID-Counter zurücksetzen", command=self._reset_autoincrement).pack(side=tk.LEFT, padx=3)
        
        # ZEILE 5: Progressbar
        progress_row = ttk.Frame(button_frame)
        progress_row.pack(fill=tk.X)
        
        self.db_progress = ttk.Progressbar(progress_row, mode='determinate', length=400)
        self.db_progress.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
    
    def _create_settings_tab(self, parent):
        """Erstellt den Einstellungen-Tab Inhalt."""
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Überschrift
        title = ttk.Label(main_frame, text="⚙️ Einstellungen", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        # === Laufwerk-Konfiguration ===
        drive_frame = ttk.LabelFrame(main_frame, text="Kirchenbuch-Medien Pfade", padding=15)
        drive_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(drive_frame, text="Basis-Laufwerk für Kirchenbuch-Medien:").pack(anchor=tk.W, pady=(0, 5))
        
        # Info-Text
        info_text = ttk.Label(
            drive_frame, 
            text=f"Aktuell: {self.config.media_drive}\\...\\Kirchenbücher\\...",
            foreground="blue"
        )
        info_text.pack(anchor=tk.W, pady=(0, 10))
        
        # Eingabefeld und Button
        drive_input_frame = ttk.Frame(drive_frame)
        drive_input_frame.pack(fill=tk.X)
        
        ttk.Label(drive_input_frame, text="Laufwerk:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.drive_var = tk.StringVar(value=self.config.media_drive)
        drive_entry = ttk.Entry(drive_input_frame, textvariable=self.drive_var, width=10)
        drive_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            drive_input_frame, 
            text="📁 Verzeichnis wählen", 
            command=self._choose_media_drive
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            drive_input_frame, 
            text="💾 Speichern", 
            command=self._save_media_drive
        ).pack(side=tk.LEFT, padx=20)
        
        # Hilfetext
        help_text = ttk.Label(
            drive_frame,
            text="Wählen Sie das Basis-Laufwerk/Verzeichnis für die Kirchenbuch-Medien.\n"
                 "Beispiel: E: oder D:\\Dokumente\\Kirchenbücher",
            foreground="gray",
            font=("Arial", 9, "italic")
        )
        help_text.pack(anchor=tk.W, pady=(10, 0))

        # === Anwendungs-Pfade (Bildbasis + Datenbank) ===
        app_paths_frame = ttk.LabelFrame(main_frame, text="Anwendungs-Pfade", padding=15)
        app_paths_frame.pack(fill=tk.X, pady=(0, 20))

        # Bild-Basispfad
        ttk.Label(app_paths_frame, text="Bild-Basispfad (OCR-Tab):").pack(anchor=tk.W, pady=(0, 4))
        image_path_row = ttk.Frame(app_paths_frame)
        image_path_row.pack(fill=tk.X, pady=(0, 10))

        self.settings_image_base_var = tk.StringVar(value=str(self.base_path))
        ttk.Entry(image_path_row, textvariable=self.settings_image_base_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(image_path_row, text="📁 Wählen", command=self._choose_settings_image_base_path).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(image_path_row, text="✅ Übernehmen", command=self._apply_settings_image_base_path).pack(side=tk.LEFT)

        # Datenbankpfad
        ttk.Label(app_paths_frame, text="Datenbank-Datei (.db):").pack(anchor=tk.W, pady=(0, 4))
        db_path_row = ttk.Frame(app_paths_frame)
        db_path_row.pack(fill=tk.X, pady=(0, 6))

        self.settings_db_path_var = tk.StringVar(value=self.active_db_path)
        ttk.Entry(db_path_row, textvariable=self.settings_db_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(db_path_row, text="📁 Wählen", command=self._choose_settings_db_path).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(db_path_row, text="💾 DB laden", command=self._apply_settings_db_path).pack(side=tk.LEFT)

        self.db_path_info_label = ttk.Label(
            app_paths_frame,
            text=f"Aktive DB: {self.active_db_path}",
            foreground="blue"
        )
        self.db_path_info_label.pack(anchor=tk.W, pady=(4, 0))

        ttk.Label(
            app_paths_frame,
            text="Hinweis: Im EXE-Betrieb kann die DB an einem anderen Ort liegen."
                 " Hier können Sie die richtige DB-Datei dauerhaft auswählen.",
            foreground="gray",
            font=("Arial", 9, "italic")
        ).pack(anchor=tk.W, pady=(4, 0))
        
        # === Spaltenbreiten-Info ===
        column_frame = ttk.LabelFrame(main_frame, text="Datenbank-Ansicht", padding=15)
        column_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(
            column_frame,
            text="Die Spaltenbreiten der Datenbank-Tabelle werden automatisch\n"
                 "beim Ändern gespeichert und beim nächsten Start wiederhergestellt.",
            foreground="gray"
        ).pack(anchor=tk.W)
        
        ttk.Button(
            column_frame, 
            text="🔄 Spaltenbreiten zurücksetzen", 
            command=self._reset_column_widths
        ).pack(anchor=tk.W, pady=(10, 0))
        
        # === Weitere Einstellungen (Platzhalter für zukünftige Features) ===
        other_frame = ttk.LabelFrame(main_frame, text="Weitere Einstellungen", padding=15)
        other_frame.pack(fill=tk.X)
        
        ttk.Label(
            other_frame,
            text="Weitere Konfigurationsoptionen werden hier hinzugefügt.",
            foreground="gray"
        ).pack(anchor=tk.W)
    
    def _choose_media_drive(self):
        """Öffnet einen Dialog zur Auswahl des Medien-Basis-Verzeichnisses."""
        initial_dir = self.config.media_drive.rstrip(':') + ':\\'  if len(self.config.media_drive) == 2 else self.config.media_drive
        
        directory = filedialog.askdirectory(
            title="Basis-Verzeichnis für Kirchenbuch-Medien wählen",
            initialdir=initial_dir
        )
        
        if directory:
            # Extrahiere Laufwerksbuchstaben oder nutze ganzen Pfad
            from pathlib import Path
            path = Path(directory)
            
            # Wenn es ein Windows-Laufwerk ist (C:, D:, etc.)
            if path.drive:
                self.drive_var.set(path.drive)
            else:
                self.drive_var.set(directory)
    
    def _save_media_drive(self):
        """Speichert die Laufwerks-Einstellung."""
        new_drive = self.drive_var.get().strip()
        
        if not new_drive:
            messagebox.showwarning("Ungültige Eingabe", "Bitte geben Sie einen gültigen Pfad ein.")
            return
        
        self.config.media_drive = new_drive
        messagebox.showinfo(
            "Gespeichert", 
            f"Laufwerk wurde gespeichert: {self.config.media_drive}\n\n"
            "Die Änderung wird beim nächsten Laden von Medien wirksam."
        )

    def _choose_settings_image_base_path(self):
        """Öffnet einen Dialog zur Auswahl des Bild-Basispfads."""
        initial_dir = str(self.base_path) if self.base_path else str(Path.cwd())
        directory = filedialog.askdirectory(
            title="Bild-Basispfad wählen",
            initialdir=initial_dir
        )
        if directory:
            self.settings_image_base_var.set(directory)

    def _apply_settings_image_base_path(self):
        """Übernimmt den Bild-Basispfad in Config und lädt Bilder neu."""
        new_path = Path(self.settings_image_base_var.get().strip()).expanduser()
        if not new_path.exists() or not new_path.is_dir():
            messagebox.showwarning("Ungültiger Pfad", f"Der Bild-Basispfad ist ungültig:\n{new_path}")
            return

        self.base_path = new_path
        self.image_folder_var.set(str(new_path))
        self.config.image_base_path = str(new_path)
        self._reload_images()

    def _choose_settings_db_path(self):
        """Öffnet einen Dialog zur Auswahl der DB-Datei."""
        initial_dir = str(Path(self.settings_db_path_var.get()).parent) if self.settings_db_path_var.get().strip() else str(Path.cwd())
        selected = filedialog.askopenfilename(
            title="SQLite-Datenbank wählen",
            initialdir=initial_dir,
            filetypes=[("SQLite DB", "*.db *.sqlite *.db3"), ("Alle Dateien", "*.*")]
        )
        if selected:
            self.settings_db_path_var.set(selected)

    def _apply_settings_db_path(self):
        """Übernimmt den DB-Pfad, lädt die DB und speichert die Einstellung."""
        raw_path = self.settings_db_path_var.get().strip()
        if not raw_path:
            messagebox.showwarning("Ungültiger Pfad", "Bitte einen DB-Pfad angeben.")
            return

        new_db_path = Path(raw_path).expanduser()
        if not new_db_path.exists():
            create_new = messagebox.askyesno(
                "DB nicht gefunden",
                f"Die Datei existiert nicht:\n{new_db_path}\n\nNeue Datenbank anlegen?"
            )
            if not create_new:
                return

        try:
            self._switch_database(new_db_path)
            self.settings_db_path_var.set(self.active_db_path)
            self.config.db_path = self.active_db_path
            messagebox.showinfo("DB geladen", f"Datenbank aktiv:\n{self.active_db_path}")
        except Exception as e:
            messagebox.showerror("DB-Fehler", f"Datenbank konnte nicht geladen werden:\n{e}")
    
    def _reset_column_widths(self):
        """Setzt die Spaltenbreiten auf Standardwerte zurück."""
        if messagebox.askyesno(
            "Zurücksetzen",
            "Möchten Sie die Spaltenbreiten auf die Standardwerte zurücksetzen?"
        ):
            # Setze Config zurück
            self.config.set("column_widths", self.config.DEFAULT_CONFIG["column_widths"].copy())
            
            # Wende Standardbreiten an
            self._apply_column_widths()
            
            messagebox.showinfo("Fertig", "Spaltenbreiten wurden zurückgesetzt.")
    
    def _apply_column_widths(self):
        """Wendet gespeicherte Spaltenbreiten aus der Config an."""
        if not hasattr(self, 'tree'):
            return
        
        # Mapping von Spalten-IDs zu Config-Keys
        column_map = {
            'ID': 'id',
            'Dateiname': 'dateiname',
            'Text': 'erkannter_text',
            'Typ': 'typ',
            'Jahr': 'jahr',
            'Datum': 'datum',
            'ISO_datum': 'iso_datum',
            'Seite': 'seite',
            'Nr': 'nr',
            'Gemeinde': 'gemeinde',
            'Vorname': 'vorname',
            'Nachname': 'nachname',
            'Partner': 'partner',
            'Beruf': 'beruf',
            'Ort': 'ort',
            'Bräutigam Vater': 'brautigam_vater',
            'Braut Vater': 'braut_vater',
            'Braut Nachname': 'braut_nachname',
            'Braut Ort': 'braut_ort',
            'Bräutigam Stand': 'brautigam_stand',
            'Braut Stand': 'braut_stand',
            'Todestag': 'todestag',
            'Geb.Jahr (gesch.)': 'geb_jahr_gesch',
            'Notiz': 'notiz'
        }
        
        column_widths = self.config.get('column_widths', {})
        
        for col_id, config_key in column_map.items():
            width = column_widths.get(config_key)
            if width:
                try:
                    self.tree.column(col_id, width=width)
                except:
                    pass  # Spalte existiert möglicherweise nicht
    
    def _on_column_resize(self, event):
        """Speichert Spaltenbreiten wenn sie geändert werden."""
        # Verzögere das Speichern um 500ms nach der letzten Änderung
        if hasattr(self, '_resize_timer'):
            self.root.after_cancel(self._resize_timer)
        
        self._resize_timer = self.root.after(500, self._save_column_widths)
    
    def _save_column_widths(self):
        """Speichert aktuelle Spaltenbreiten in die Config."""
        if not hasattr(self, 'tree'):
            return
        
        # Mapping von Spalten-IDs zu Config-Keys (gleich wie in _apply_column_widths)
        column_map = {
            'ID': 'id',
            'Dateiname': 'dateiname',
            'Text': 'erkannter_text',
            'Typ': 'typ',
            'Jahr': 'jahr',
            'Datum': 'datum',
            'ISO_datum': 'iso_datum',
            'Seite': 'seite',
            'Nr': 'nr',
            'Gemeinde': 'gemeinde',
            'Vorname': 'vorname',
            'Nachname': 'nachname',
            'Partner': 'partner',
            'Beruf': 'beruf',
            'Ort': 'ort',
            'Bräutigam Vater': 'brautigam_vater',
            'Braut Vater': 'braut_vater',
            'Braut Nachname': 'braut_nachname',
            'Braut Ort': 'braut_ort',
            'Bräutigam Stand': 'brautigam_stand',
            'Braut Stand': 'braut_stand',
            'Todestag': 'todestag',
            'Geb.Jahr (gesch.)': 'geb_jahr_gesch',
            'Notiz': 'notiz'
        }
        
        widths = {}
        for col_id, config_key in column_map.items():
            try:
                width = self.tree.column(col_id, 'width')
                widths[config_key] = width
            except:
                pass
        
        self.config.set_all_column_widths(widths)
    
    def _standardize_p_nr_selected(self):
            """Standardisiert p./Nr.-Angaben im Feld 'Erkannter Text' für die ausgewählten Einträge."""
            import re
            selection = self.tree.selection()
            if not selection:
                messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
                return

            count = len(selection)
            if not messagebox.askyesno(
                "p/Nr. standardisieren",
                f"Möchten Sie die Standardisierung auf {count} Einträge anwenden?\n\n"
                f"Varianten wie 'p. 95m. 24', 'p.118 n.1', 'Nr. .14' werden vereinheitlicht.\n"
                f"Die alten Texte werden überschrieben."):
                return

            erfolge = 0
            fehler = 0
            keine_aenderung = 0
            cursor = self.db.conn.cursor()
            for item in selection:
                record_id = self.tree.item(item)['values'][0]
                try:
                    cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                    row = cursor.fetchone()
                    if row:
                        original_text = row[0]
                        dateiname = row[1]
                        dateipfad = row[2]
                        new_text = original_text
                        # 1. p. <Zahl>m. <Zahl> → p. <Zahl> Nr. <Zahl>
                        new_text = re.sub(r"p\.\s*(\d+)m\.\s*(\d+)", r"p. \1 Nr. \2", new_text)
                        # 2. p.?\s*(\d+)n\.\s*(\d+) → p. <Zahl> Nr. <Zahl>
                        new_text = re.sub(r"p\.?\s*(\d+)n\.\s*(\d+)", r"p. \1 Nr. \2", new_text)
                        # 3. p.?\s*(\d+)\.?n\.\s*(\d+) → p. <Zahl> Nr. <Zahl>
                        new_text = re.sub(r"p\.?\s*(\d+)\.?n\.\s*(\d+)", r"p. \1 Nr. \2", new_text)
                        # 4. n\.\s*(\d+) → Nr. <Zahl> (nur wenn nicht schon 'Nr.' davor)
                        new_text = re.sub(r"(?<!Nr\.)n\.\s*(\d+)", r"Nr. \1", new_text)
                        # 5. m\.\s*(\d+) → Nr. <Zahl> (nur wenn nicht schon 'Nr.' davor)
                        new_text = re.sub(r"(?<!Nr\.)m\.\s*(\d+)", r"Nr. \1", new_text)
                        # 6. Nr\.\s*\.\s*(\d+) → Nr. <Zahl>
                        new_text = re.sub(r"Nr\.\s*\.\s*(\d+)", r"Nr. \1", new_text)
                        # 7. p\.?\s*(\d+)\s*Nr\.?\s*(\d+) → p. <Zahl> Nr. <Zahl> (vereinheitlichen Leerzeichen/Punkte)
                        new_text = re.sub(r"p\.?\s*(\d+)\s*Nr\.?\s*(\d+)", r"p. \1 Nr. \2", new_text)
                        if new_text == original_text:
                            keine_aenderung += 1
                            continue
                        self.db.save_karteikarte(
                            dateiname=dateiname,
                            dateipfad=dateipfad,
                            erkannter_text=new_text,
                            ocr_methode="standardize_p_nr"
                        )
                        erfolge += 1
                except Exception as e:
                    fehler += 1
                    print(f"Fehler bei ID {record_id}: {str(e)}")
            self._refresh_db_list()
            messagebox.showinfo(
                "Fertig",
                f"Standardisierung abgeschlossen!\n\n"
                f"Erfolgreich geändert: {erfolge}\n"
                f"Keine Änderung nötig: {keine_aenderung}\n"
                f"Fehler: {fehler}"
            )
    
    def _format_citation_selected(self):
        """Formatiert die Zitation für ausgewählte Einträge in ein einheitliches Format."""
        import re
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return

        count = len(selection)
        if not messagebox.askyesno(
            "Zitation formatieren",
            f"Möchten Sie die Zitations-Formatierung auf {count} Einträge anwenden?\n\n"
            f"Format: 'ev. Kb. Wetzlar ⚰ YYYY.MM.DD. p. X Nr. Y '\n"
            f"Die alten Texte werden überschrieben."):
            return

        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        cursor = self.db.conn.cursor()
        
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            try:
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # Entferne optionalen Punkt nach "Wetzlar" (normalisiert "Wetzlar." → "Wetzlar")
                    text_normalized = re.sub(r'(ev\.?\s*Kb\.?\s*Wetzlar)\.', r'\1', original_text, flags=re.IGNORECASE)
                    
                    # Entferne Komma nach Datum (1694.09.19, → 1694.09.19.)
                    text_normalized = re.sub(r'(\d{4})\.(\d{1,2})\.(\d{1,2}),', r'\1.\2.\3.', text_normalized)
                    
                    # Korrigiere "pp." zu "p."
                    text_normalized = re.sub(r'\bpp\.', 'p.', text_normalized, flags=re.IGNORECASE)
                    
                    # Entferne doppelte Leerzeichen vor "Nr."
                    text_normalized = re.sub(r'Nr\.\s+(\d)', r'Nr. \1', text_normalized)
                    
                    # Regex-Pattern für Zitation (SEHR flexibel für verschiedene Formate)
                    # Sucht: (ev. Kb. Wetzlar)? (Symbol ODER kein Symbol) Datum (mit/ohne Junk) p./P. Seite Nr. Nummer
                    # Symbol ist optional (kann fehlen bei Hochzeiten)
                    # Zwischen Datum und p. können Junk-Zeichen sein (z.B. "9.   p.")
                    pattern = r"^\s*(ev\.?\s*Kb\.?\s*Wetzlar)?\s*([⚰∞\u26B0])?\s*(\d{4})[\.,\s]*(\d{1,2})[\.,\s]*(\d{1,2})[\.,\s]*[\d\.\s]*[Pp]{1,2}\.?\s*(\d+)[\.\s]*,?\s*Nr\.?\s*(\d+)\.?\s*"
                    
                    match = re.match(pattern, text_normalized, re.IGNORECASE)
                    if match:
                        # Extrahiere Komponenten
                        prefix = "ev. Kb. Wetzlar"
                        symbol = match.group(2) if match.group(2) else "∞"  # Fallback auf ∞ wenn Symbol fehlt
                        jahr = match.group(3)
                        monat = match.group(4).zfill(2)
                        tag = match.group(5).zfill(2)
                        seite = match.group(6)
                        nummer = match.group(7)
                        
                        # Rest des Textes nach der Zitation
                        rest = text_normalized[match.end():]
                        
                        # Formatierte Zitation erstellen
                        formatted = f"{prefix} {symbol} {jahr}.{monat}.{tag}. p. {seite} Nr. {nummer} {rest}"
                        
                        if formatted == original_text:
                            keine_aenderung += 1
                            continue
                        
                        self.db.save_karteikarte(
                            dateiname=dateiname,
                            dateipfad=dateipfad,
                            erkannter_text=formatted,
                            ocr_methode="format_citation"
                        )
                        erfolge += 1
                    else:
                        # Kein Match - könnte ohne "ev. Kb. Wetzlar" sein, probiere alternatives Pattern
                        # Akzeptiert P. oder p., normalisiert auf p.
                        pattern_alt = r"^\s*([⚰∞\u26B0])\s*(\d{4})[\.\s]*(\d{1,2})[\.\s]*(\d{1,2})\.?\s*[Pp]\.?\s*(\d+)\.?\s*,?\s*Nr\.?\s*(\d+)\.?\s*"
                        match_alt = re.match(pattern_alt, text_normalized)
                        if match_alt:
                            prefix = "ev. Kb. Wetzlar"
                            symbol = match_alt.group(1)
                            jahr = match_alt.group(2)
                            monat = match_alt.group(3).zfill(2)
                            tag = match_alt.group(4).zfill(2)
                            seite = match_alt.group(5)
                            nummer = match_alt.group(6)
                            rest = text_normalized[match_alt.end():]
                            
                            formatted = f"{prefix} {symbol} {jahr}.{monat}.{tag}. p. {seite} Nr. {nummer} {rest}"
                            
                            if formatted == original_text:
                                keine_aenderung += 1
                                continue
                            
                            self.db.save_karteikarte(
                                dateiname=dateiname,
                                dateipfad=dateipfad,
                                erkannter_text=formatted,
                                ocr_methode="format_citation"
                            )
                            erfolge += 1
                        else:
                            keine_aenderung += 1
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list()
        messagebox.showinfo(
            "Fertig",
            f"Zitations-Formatierung abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )

    def _fix_p_number_selected(self):
        """Ersetzt in den ausgewählten Einträgen im Feld 'Erkannter Text' alle 'p(Zahl)' oder 'p (Zahl)' oder 'P(Zahl)' durch 'p. (Zahl)' und speichert in der Datenbank."""
        import re
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return

        count = len(selection)
        if not messagebox.askyesno(
            "p(Zahl) → p. (Zahl) ersetzen",
            f"Möchten Sie die Ersetzung auf {count} Einträge anwenden?\n\n"
            f"Alle Vorkommen von 'p(Zahl)', 'p (Zahl)' oder 'P(Zahl)' werden durch 'p. (Zahl)' ersetzt.\n"
            f"Die alten Texte werden überschrieben."):
            return

        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        cursor = self.db.conn.cursor()
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            try:
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    # Ersetze sowohl "p" als auch "P" (case-insensitive)
                    new_text = re.sub(r"[Pp]\.?\s?(\d+)", r"p. \1", original_text)
                    if new_text == original_text:
                        keine_aenderung += 1
                        continue
                    self.db.save_karteikarte(
                        dateiname=dateiname,
                        dateipfad=dateipfad,
                        erkannter_text=new_text,
                        ocr_methode="fix_p_number"
                    )
                    erfolge += 1
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        self._refresh_db_list()
        messagebox.showinfo(
            "Fertig",
            f"p(Zahl)-Ersetzung abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )

        
        # Initial laden
        self._refresh_db_list()
        # Zuletzt sortierte Spalte merken
        self._last_sorted_column = None
    
    ##################
    def _show_selected_image(self):
        """Zeigt das zugehörige Kirchenbuchbild der ausgewählten Zeile an (nutzt SOURCES dict)."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie einen Eintrag aus der Liste aus.")
            return

        item = selection[0]
        values = self.tree.item(item)['values']
        typ = values[4]  # Typ
        jahr = values[1]  # Jahr
        seite = values[5]  # Seite

        from pathlib import Path

        # Konvertiere Jahr zu int
        try:
            jahr_int = int(jahr)
        except Exception as e:
            messagebox.showerror("Ungültiges Jahr", f"Das Jahr '{jahr}' ist ungültig.\nFehler: {e}")
            return
        
        # Konvertiere Seite zu int
        try:
            seite_int = int(seite)
        except Exception:
            messagebox.showerror("Ungültige Seite", f"Die Seite '{seite}' ist ungültig.")
            return

        # Finde passende Quelle aus SOURCES
        # Kriterien: media_type = "kirchenbuchseiten" und Jahr im Bereich der source
        passende_quellen = []
        for source in SOURCES:
            if source.get("media_type") != "kirchenbuchseiten":
                continue
            if not source.get("media_ID") or not source.get("media_path"):
                continue
            
            # Extrahiere Jahresbereich aus source name
            # Format: "WETZLAR KbSb 1613-1693 lutherisch"
            source_name = source["source"]
            import re
            jahr_match = re.search(r"(\d{4})-(\d{4})", source_name)
            if jahr_match:
                jahr_von = int(jahr_match.group(1))
                jahr_bis = int(jahr_match.group(2))
                
                # Prüfe ob Jahr im Bereich liegt
                if jahr_von <= jahr_int <= jahr_bis:
                    # Bestimme Typ-Kürzel aus Datenbank-Typ
                    typ_kuerzel = None
                    if typ == "Begräbnis":
                        typ_kuerzel = "Sb"
                    elif typ == "Heirat":
                        typ_kuerzel = "Hb"
                    elif typ == "Taufe" or typ == "Geburt":
                        typ_kuerzel = "Gb"
                    
                    # Prüfe media_ID: muss mit _<typ_kuerzel> enden (z.B. EKiR_408_021_Hb)
                    media_id = source.get("media_ID", "")
                    if typ_kuerzel and media_id.endswith(f"_{typ_kuerzel}"):
                        passende_quellen.append(source)
        
        if not passende_quellen:
            kb_quellen = [s for s in SOURCES if s.get("media_type") == "kirchenbuchseiten"]
            quellen_info = "\n".join([f"  - {s['source']} (media_ID: {s.get('media_ID', 'N/A')})" for s in kb_quellen])
            
            # Bestimme gesuchtes Typ-Kürzel
            typ_kuerzel = None
            if typ == "Begräbnis":
                typ_kuerzel = "Sb"
            elif typ == "Heirat":
                typ_kuerzel = "Hb"
            elif typ == "Taufe" or typ == "Geburt":
                typ_kuerzel = "Gb"
            
            messagebox.showerror(
                "Keine Quelle gefunden", 
                f"Keine passende Kirchenbuch-Quelle für:\n"
                f"Typ: {typ} (Suche nach: _{typ_kuerzel})\n"
                f"Jahr: {jahr_int}\n\n"
                f"Verfügbare Kirchenbuch-Quellen:\n{quellen_info}\n\n"
                f"Hinweis: Jahr muss im Bereich der Quelle liegen\n"
                f"und media_ID muss mit _{typ_kuerzel} enden."
            )
            return
        
        # Verwende erste passende Quelle
        quelle = passende_quellen[0]
        media_id = quelle["media_ID"]
        ordner = Path(quelle["media_path"])
        
        if not ordner.exists():
            messagebox.showerror(
                "Ordner nicht gefunden",
                f"Der Suchpfad existiert nicht:\n\n"
                f"Quelle: {quelle['source']}\n"
                f"Pfad: {ordner}"
            )
            return
        
        # Baue Dateiname nach EKiR-Format
        # Format: EKiR_408_021_107 S_0020-0021.jpg
        # - media_ID ohne letzten 3 Zeichen (entfernt _Gb/_Hb/_Sb): EKiR_408_021
        # - Jahr-Suffix: wird mit Wildcard * gesucht (beliebige Zeichen)
        # - S_: IMMER "S_" für Seite
        # - Seitenzahlen: gerade-ungerade
        
        # Entferne die letzten 3 Zeichen vom media_ID (z.B. "_Sb")
        media_id_prefix = media_id[:-3]  # "EKiR_408_021_Sb" -> "EKiR_408_021"
        
        # Unterstütze sowohl 3-stellige als auch 4-stellige Seitenzahlen
        seite_str_3 = f"{seite_int:03d}"  # 3-stellig: 88 -> "088"
        seite_str_4 = f"{seite_int:04d}"  # 4-stellig: 88 -> "0088"
        
        # DEBUG: Zeige Konstruktions-Details
        print(f"\n{'='*60}")
        print(f"DEBUG: _show_selected_image Pfad-Konstruktion")
        print(f"{'='*60}")
        print(f"Input:")
        print(f"  Typ:         {typ}")
        print(f"  Jahr:        {jahr_int}")
        print(f"  Seite:       {seite_int}")
        print(f"\nGefundene Quelle:")
        print(f"  Name:        {quelle['source']}")
        print(f"  Media-ID:    {media_id}")
        print(f"  Ordner:      {ordner}")
        print(f"\nPattern-Konstruktion:")
        print(f"  media_ID_prefix: {media_id_prefix}")
        print(f"  seite_str (3-stellig): {seite_str_3}")
        print(f"  seite_str (4-stellig): {seite_str_4}")
        print(f"  Gerade/Ungerade: {'gerade' if seite_int % 2 == 0 else 'ungerade'}")
        
        # Teste mehrere Patterns - für BEIDE Formate (3- und 4-stellig)
        # Wichtig: Patterns müssen spezifisch sein, damit z.B. "0002" nicht auch "0022" findet!
        patterns = [
            # 4-stellige Varianten - mit Trennzeichen um False Positives zu vermeiden
            f"{media_id_prefix}* S_{seite_str_4}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4} Sterbebuch.jpg",
            # 3-stellige Varianten - mit Trennzeichen um False Positives zu vermeiden
            f"{media_id_prefix}* S_{seite_str_3}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_3}.jpg",
            f"{media_id_prefix}*_{seite_str_3}.jpg",
        ]
        
        print(f"\nTeste Patterns:")
        treffer = []
        for pattern in patterns:
            pattern_treffer = list(ordner.glob(pattern))
            status = "✅" if pattern_treffer else "❌"
            print(f"  {status} {pattern} → {len(pattern_treffer)} Treffer")
            if pattern_treffer:
                treffer.extend(pattern_treffer)
        
        # Duplikate entfernen (falls mehrere Patterns dieselbe Datei finden)
        treffer = list(set(treffer))
        
        print(f"\nErgebnis:")
        print(f"  Treffer gesamt: {len(treffer)}")
        if treffer:
            print(f"  Gefundene Dateien:")
            for t in treffer[:5]:
                print(f"    - {t.name}")
        print(f"{'='*60}\n")
        
        if not treffer:
            # Zeige alle jpg-Dateien im Ordner zur Diagnose
            alle_jpgs = list(ordner.glob("*.jpg"))
            beispiel_dateien = "\n".join([f"  - {f.name}" for f in alle_jpgs[:10]])
            
            # Liste getestete Patterns
            pattern_liste = "\n".join([f"  - {p}" for p in patterns])
            
            messagebox.showerror(
                "Bild nicht gefunden", 
                f"Kein Bild gefunden für:\n"
                f"Quelle: {quelle['source']}\n"
                f"Media-ID: {media_id}\n"
                f"Jahr: {jahr_int}\n"
                f"Seite: {seite_int}\n\n"
                f"Suchpfad: {ordner}\n\n"
                f"Getestete Patterns:\n{pattern_liste}\n\n"
                f"Beispiel-Dateien im Ordner ({len(alle_jpgs)} gesamt):\n{beispiel_dateien}"
            )
            return
        
        if len(treffer) > 1:
            messagebox.showwarning(
                "Mehrere Bilder gefunden", 
                f"Mehrere Bilder gefunden:\n" + "\n".join([t.name for t in treffer]) + 
                f"\n\nEs wird das erste angezeigt."
            )
        
        pfad = treffer[0]
        self._open_image_viewer(str(pfad))


    def _open_image_viewer(self, pfad):
        """Öffnet ein Fenster zur Bildanzeige mit Navigation, Zoom und Verschieben."""
        from pathlib import Path

        import PIL.Image
        import PIL.ImageTk

        viewer = tk.Toplevel(self.root)
        viewer.title(f"Bildanzeige: {Path(pfad).name}")
        viewer.geometry("1200x900")

        img = PIL.Image.open(pfad)
        zoom = 1.0

        # Frame für Canvas + Scrollbars
        canvas_frame = ttk.Frame(viewer)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg="black")
        canvas.grid(row=0, column=0, sticky="nsew")

        hbar = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)
        hbar.grid(row=1, column=0, sticky="ew")
        vbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        vbar.grid(row=0, column=1, sticky="ns")
        canvas.config(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        tk_img = None
        img_id = None

        def show_img():
            nonlocal img, zoom, tk_img, img_id
            w, h = int(img.width * zoom), int(img.height * zoom)
            resized = img.resize((w, h), PIL.Image.LANCZOS)
            tk_img = PIL.ImageTk.PhotoImage(resized)
            canvas.delete("all")
            img_id = canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)
            canvas.config(scrollregion=(0, 0, w, h))

        def zoom_in():
            nonlocal zoom
            zoom *= 1.2
            show_img()

        def zoom_out():
            nonlocal zoom
            zoom /= 1.2
            show_img()

        show_img()

        btn_frame = ttk.Frame(viewer)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Zoom +", command=zoom_in).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Zoom -", command=zoom_out).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Schließen", command=viewer.destroy).pack(side=tk.RIGHT, padx=5)

        # Mausrad für Zoom
        def on_mousewheel(event):
            if event.delta > 0:
                zoom_in()
            else:
                zoom_out()
        canvas.bind("<MouseWheel>", on_mousewheel)

        # Panning (Verschieben per Maus)
        def start_pan(event):
            canvas.scan_mark(event.x, event.y)
        def do_pan(event):
            canvas.scan_dragto(event.x, event.y, gain=1)
        canvas.bind("<ButtonPress-1>", start_pan)
        canvas.bind("<B1-Motion>", do_pan)

    
    def _show_correction_settings(self):
        """Öffnet Einstellungs-Dialog für OCR-Korrekturen."""
        from text_postprocessor import TextPostProcessor

        # Erstelle Settings-Fenster - GRÖßER!
        settings_window = tk.Toplevel(self.root)
        settings_window.title("⚙️ Korrektur-Einstellungen bearbeiten")
        settings_window.geometry("1000x800")  # VERGRÖSSERT von 900x700
        
        # Info-Frame
        info_frame = ttk.Frame(settings_window)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(
            info_frame, 
            text="Hier können Sie eigene OCR-Korrekturen hinzufügen.\n"
                 "Die Änderungen werden sofort bei der nächsten Text-Korrektur angewendet.",
            font=("Arial", 9),
            foreground="blue"
        ).pack(anchor=tk.W)
        
        # Notebook für zwei Tabs
        settings_notebook = ttk.Notebook(settings_window)
        settings_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))  # WENIGER pady unten
        
        # Tab 1: Einfache Ersetzungen (common_ocr_errors)
        tab1 = ttk.Frame(settings_notebook)
        settings_notebook.add(tab1, text="🔧 Einfache Ersetzungen")
        
        # Tab 2: Wörterbuch (kirchenbuch_vocabulary)
        tab2 = ttk.Frame(settings_notebook)
        settings_notebook.add(tab2, text="📖 Wörterbuch")
        
        # === TAB 1: Einfache Ersetzungen ===
        ttk.Label(tab1, text="Fehler → Korrektur (z.B. 'w. Kb.' → 'ev. Kb.')", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10, pady=5)
        
        # Frame für Treeview + Scrollbar - MIT HEIGHT LIMIT
        tree_frame1 = ttk.Frame(tab1, height=500)  # MAX HEIGHT
        tree_frame1.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        tree_frame1.pack_propagate(False)  # Verhindert automatisches Wachsen
        
        vsb1 = ttk.Scrollbar(tree_frame1, orient="vertical")
        vsb1.pack(side=tk.RIGHT, fill=tk.Y)
        
        corrections_tree = ttk.Treeview(
            tree_frame1, 
            columns=('Fehler', 'Korrektur'), 
            show='headings',
            yscrollcommand=vsb1.set
        )
        vsb1.config(command=corrections_tree.yview)
        
        corrections_tree.heading('Fehler', text='Fehlerhafte Schreibweise')
        corrections_tree.heading('Korrektur', text='Korrekte Schreibweise')
        corrections_tree.column('Fehler', width=350)
        corrections_tree.column('Korrektur', width=350)
        corrections_tree.pack(fill=tk.BOTH, expand=True)
        
        # Lade aktuelle Werte
        processor = TextPostProcessor()
        for error, correction in sorted(processor.common_ocr_errors.items()):
            corrections_tree.insert('', tk.END, values=(error, correction))
        
        # Buttons für Tab 1
        btn_frame1 = ttk.Frame(tab1)
        btn_frame1.pack(fill=tk.X, padx=10, pady=5)
        
        def add_correction():
            """Fügt neue Ersetzung hinzu."""
            add_window = tk.Toplevel(settings_window)
            add_window.title("Neue Ersetzung hinzufügen")
            add_window.geometry("400x150")
            add_window.transient(settings_window)
            add_window.grab_set()
            
            ttk.Label(add_window, text="Fehlerhafte Schreibweise:", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
            error_entry = ttk.Entry(add_window, width=50)
            error_entry.pack(padx=10, pady=5)
            
            ttk.Label(add_window, text="Korrekte Schreibweise:", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
            correction_entry = ttk.Entry(add_window, width=50)
            correction_entry.pack(padx=10, pady=5)
            
            def save_new():
                error = error_entry.get().strip()
                correction = correction_entry.get().strip()
                
                if not error or not correction:
                    messagebox.showwarning("Warnung", "Bitte beide Felder ausfüllen!")
                    return
                
                corrections_tree.insert('', tk.END, values=(error, correction))
                add_window.destroy()
            
            ttk.Button(add_window, text="✅ Hinzufügen", command=save_new).pack(pady=10)
        
        def delete_correction():
            """Löscht ausgewählte Ersetzung."""
            selection = corrections_tree.selection()
            if not selection:
                messagebox.showwarning("Warnung", "Bitte einen Eintrag auswählen.")
                return
            
            for item in selection:
                corrections_tree.delete(item)
        
        ttk.Button(btn_frame1, text="➕ Neue Ersetzung", command=add_correction).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame1, text="➖ Löschen", command=delete_correction).pack(side=tk.LEFT, padx=5)
        
        # === TAB 2: Wörterbuch ===
        ttk.Label(tab2, text="Korrektes Wort + Varianten (z.B. 'Hochzeit' ← 'Rochzeit, Kochzeit')", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10, pady=5)
        
        tree_frame2 = ttk.Frame(tab2)
        tree_frame2.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        vsb2 = ttk.Scrollbar(tree_frame2, orient="vertical")
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        
        vocab_tree = ttk.Treeview(
            tree_frame2,
            columns=('Korrekt', 'Varianten'),
            show='headings',
            yscrollcommand=vsb2.set
        )
        vsb2.config(command=vocab_tree.yview)
        
        vocab_tree.heading('Korrekt', text='Korrekte Schreibweise')
        vocab_tree.heading('Varianten', text='Fehlerhafte Varianten (kommagetrennt)')
        vocab_tree.column('Korrekt', width=250)
        vocab_tree.column('Varianten', width=500)
        vocab_tree.pack(fill=tk.BOTH, expand=True)
        
        # Lade Wörterbuch
        for correct, variants in sorted(processor.kirchenbuch_vocabulary.items()):
            variants_str = ', '.join(variants)
            vocab_tree.insert('', tk.END, values=(correct, variants_str))
        
        # Buttons für Tab 2
        btn_frame2 = ttk.Frame(tab2)
        btn_frame2.pack(fill=tk.X, padx=10, pady=5)
        
        def add_vocab():
            """Fügt neues Wörterbuch-Wort hinzu."""
            add_window = tk.Toplevel(settings_window)
            add_window.title("Neues Wörterbuch-Wort hinzufügen")
            add_window.geometry("500x200")
            add_window.transient(settings_window)
            add_window.grab_set()
            
            ttk.Label(add_window, text="Korrekte Schreibweise:", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
            correct_entry = ttk.Entry(add_window, width=60)
            correct_entry.pack(padx=10, pady=5)
            
            ttk.Label(add_window, text="Fehlerhafte Varianten (kommagetrennt):", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
            ttk.Label(add_window, text="Beispiel: Rochzeit, Kochzeit, Hodzeit", font=("Arial", 8), foreground="gray").pack(anchor=tk.W, padx=10)
            variants_entry = ttk.Entry(add_window, width=60)
            variants_entry.pack(padx=10, pady=5)
            
            def save_new_vocab():
                correct = correct_entry.get().strip()
                variants_str = variants_entry.get().strip()
                
                if not correct or not variants_str:
                    messagebox.showwarning("Warnung", "Bitte beide Felder ausfüllen!")
                    return
                
                vocab_tree.insert('', tk.END, values=(correct, variants_str))
                add_window.destroy()
            
            ttk.Button(add_window, text="✅ Hinzufügen", command=save_new_vocab).pack(pady=10)
        
        def delete_vocab():
            """Löscht ausgewähltes Wörterbuch-Wort."""
            selection = vocab_tree.selection()
            if not selection:
                messagebox.showwarning("Warnung", "Bitte einen Eintrag auswählen.")
                return
            
            for item in selection:
                vocab_tree.delete(item)
        
        ttk.Button(btn_frame2, text="➕ Neues Wort", command=add_vocab).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame2, text="➖ Löschen", command=delete_vocab).pack(side=tk.LEFT, padx=5)
        
        # === Speichern-Button unten === NACH dem Notebook!
        save_frame = ttk.Frame(settings_window)
        save_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)  # WICHTIG: side=tk.BOTTOM
        
        def save_all_settings():
            """Speichert alle Änderungen in die text_postprocessor.py Datei."""
            # Sammle Daten aus Tab 1
            new_corrections = {}
            for item in corrections_tree.get_children():
                error, correction = corrections_tree.item(item)['values']
                new_corrections[error] = correction
            
            # Sammle Daten aus Tab 2
            new_vocab = {}
            for item in vocab_tree.get_children():
                correct, variants_str = vocab_tree.item(item)['values']
                variants = [v.strip() for v in variants_str.split(',') if v.strip()]
                new_vocab[correct] = variants
            
            # Schreibe in text_postprocessor.py
            try:
                config_file = Path(__file__).parent / "text_postprocessor.py"
                
                # Lese aktuelle Datei
                with open(config_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Finde und ersetze common_ocr_errors
                new_lines = []
                in_corrections = False
                in_vocab = False
                indent = ' ' * 12
                
                i = 0
                while i < len(lines):
                    line = lines[i]
                    
                    # Ersetze common_ocr_errors
                    if 'self.common_ocr_errors = {' in line:
                        new_lines.append(line)
                        in_corrections = True
                        
                        # Füge neue Werte ein
                        for error, correction in sorted(new_corrections.items()):
                            new_lines.append(f"{indent}'{error}': '{correction}',\n")
                        
                        # Überspringe alte Werte bis zur schließenden Klammer
                        i += 1
                        while i < len(lines) and '}' not in lines[i]:
                            i += 1
                        new_lines.append(f"{indent[:-4]}}}\n")  # Schließende Klammer
                        in_corrections = False
                    
                    # Ersetze kirchenbuch_vocabulary
                    elif 'self.kirchenbuch_vocabulary = {' in line:
                        new_lines.append(line)
                        in_vocab = True
                        
                        # Füge neue Werte ein
                        for correct, variants in sorted(new_vocab.items()):
                            variants_repr = repr(variants)
                            new_lines.append(f"{indent}'{correct}': {variants_repr},\n")
                        
                        # Überspringe alte Werte
                        i += 1
                        while i < len(lines) and '}' not in lines[i]:
                            i += 1
                        new_lines.append(f"{indent[:-4]}}}\n")
                        in_vocab = False
                    
                    elif not in_corrections and not in_vocab:
                        new_lines.append(line)
                    
                    i += 1
                
                # Schreibe zurück
                with open(config_file, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                
                settings_window.destroy()
                messagebox.showinfo(
                    "Erfolg",
                    f"Einstellungen gespeichert!\n\n"
                    f"Einfache Ersetzungen: {len(new_corrections)}\n"
                    f"Wörterbuch-Einträge: {len(new_vocab)}\n\n"
                    f"Die neuen Regeln werden bei der nächsten Text-Korrektur angewendet."
                )
                
            except Exception as e:
                messagebox.showerror("Fehler", f"Fehler beim Speichern:\n{str(e)}")
        
        ttk.Button(save_frame, text="💾 Alle Änderungen speichern", command=save_all_settings, style="Accent.TButton").pack(side=tk.LEFT, padx=5, ipadx=10, ipady=5)
        ttk.Button(save_frame, text="❌ Abbrechen", command=settings_window.destroy).pack(side=tk.RIGHT, padx=5)
        
        # Trennlinie über den Buttons
        separator = ttk.Separator(settings_window, orient='horizontal')
        separator.pack(fill=tk.X, padx=10, pady=(0, 10), side=tk.BOTTOM, before=save_frame)
    
    def _change_folder(self):
        """Ermöglicht die Auswahl eines neuen Bildverzeichnisses."""
        folder = filedialog.askdirectory(
            title="Bildverzeichnis auswählen",
            initialdir=self.base_path
        )
        if folder:
            self.image_folder_var.set(folder)
            self.base_path = Path(folder)
            self.config.image_base_path = str(self.base_path)
            if hasattr(self, "settings_image_base_var"):
                self.settings_image_base_var.set(str(self.base_path))
            self._reload_images()
    
    def _reload_images(self):
        """Lädt die Bilddateien aus dem aktuellen Verzeichnis neu."""
        new_path = Path(self.image_folder_var.get())
        if not new_path.exists():
            messagebox.showerror("Fehler", f"Verzeichnis existiert nicht:\n{new_path}")
            return
        
        self.base_path = new_path
        self.config.image_base_path = str(self.base_path)
        if hasattr(self, "settings_image_base_var"):
            self.settings_image_base_var.set(str(self.base_path))
        self.image_files = []
        self.current_index = 0
        self.current_db_record_id = None
        
        self._load_image_files()
        
        if self.image_files:
            self._display_current_card()
            messagebox.showinfo(
                "Erfolg",
                f"{len(self.image_files)} Karteikarten geladen aus:\n{self.base_path}"
            )
        else:
            messagebox.showwarning("Warnung", "Keine Bilddateien gefunden.")
    
    def _refresh_db_list(self):
        """Lädt und zeigt die Datenbank-Einträge."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        try:
            id_filter = self.id_filter.get().strip()
            year_filter = self.year_filter.get()
            type_filter = self.type_filter.get()
            filename_filter = self.filename_filter.get()
            kirchenbuch_filter = self.kirchenbuch_filter.get()
            name_search = self.name_search.get().strip()

            query = (
                "SELECT id, jahr, datum, iso_datum, ereignis_typ, seite, nummer, kirchengemeinde, "
                "vorname, nachname, partner, beruf, ort, "
                "braeutigam_vater, braut_vater, braut_nachname, braut_ort, "
                "braeutigam_stand, stand, todestag, geb_jahr_gesch, "
                "dateiname, notiz, erkannter_text, kirchenbuchtext, gramps "
                "FROM karteikarten WHERE 1=1"
            )
            params = []

            if id_filter:
                try:
                    id_int = int(id_filter)
                    query += " AND id = ?"
                    params.append(id_int)
                except ValueError:
                    messagebox.showwarning("Ungültige ID", "Bitte eine gültige Zahl für die ID eingeben.")
                    return

            if year_filter and year_filter != 'Alle':
                query += " AND jahr = ?"
                params.append(int(year_filter))

            if type_filter and type_filter != 'Alle':
                if type_filter == '(Leere)':
                    query += " AND (ereignis_typ IS NULL OR ereignis_typ = '')"
                else:
                    query += " AND ereignis_typ = ?"
                    params.append(type_filter)

            if filename_filter and filename_filter != 'Alle':
                # Suche nach Sb, Hb, Gb im Dateinamen (Groß-/Kleinschreibung egal)
                query += " AND LOWER(dateiname) LIKE ?"
                params.append(f'%{filename_filter.lower()}%')


            regex_mode = getattr(self, 'regex_search_var', None)
            if name_search:
                if regex_mode and regex_mode.get():
                    # Hole alle Datensätze, Filter erfolgt später per Regex
                    pass
                else:
                    query += " AND erkannter_text LIKE ?"
                    params.append(f'%{name_search}%')

            query += " ORDER BY jahr DESC, datum DESC, nummer"

            cursor = self.db.conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Regex-Filter anwenden, falls aktiviert
            if name_search and regex_mode and regex_mode.get():
                import re
                try:
                    pattern = re.compile(name_search)
                except re.error as e:
                    messagebox.showerror("Regex-Fehler", f"Ungültiger regulärer Ausdruck:\n{e}")
                    self.db_status_label.config(text="0 Datensätze gefunden (Regex-Fehler)")
                    return
                # Filtere rows, bei denen erkannter_text auf das Pattern matcht
                rows = [row for row in rows if pattern.search(str(row[23]))]  # Index 23 = erkannter_text

            if kirchenbuch_filter and kirchenbuch_filter != 'Alle':
                rows = [
                    row for row in rows
                    if self._extract_kirchenbuch_titel(row[21]) == kirchenbuch_filter
                ]

            for row in rows:
                # row: id, jahr, datum, iso_datum, ereignis_typ, seite, nummer, kirchengemeinde, 
                # vorname, nachname, partner, beruf, ort,
                # braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                # braeutigam_stand, stand, todestag, geb_jahr_gesch,
                # dateiname, notiz, erkannter_text, kirchenbuchtext, gramps
                def safe(idx):
                    try:
                        return row[idx] if row[idx] is not None else ''
                    except IndexError:
                        return ''

                values = (
                    safe(0),  # ID
                    safe(1),  # Jahr
                    safe(2),  # Datum
                    safe(3),  # ISO_datum
                    safe(4),  # Typ
                    safe(5),  # Seite
                    safe(6),  # Nr
                    safe(7),  # Gemeinde
                    safe(8),  # Vorname
                    safe(9),  # Nachname
                    safe(10), # Partner
                    safe(11), # Beruf
                    safe(12), # Ort
                    safe(13), # Bräutigam Vater
                    safe(14), # Braut Vater
                    safe(15), # Braut Nachname
                    safe(16), # Braut Ort
                    safe(17), # Bräutigam Stand
                    safe(18), # Braut Stand (ehemals 'stand')
                    safe(19), # Todestag
                    safe(20), # Geb.Jahr (gesch.)
                    safe(21), # Dateiname
                    safe(22), # Notiz
                    safe(25), # Gramps
                    safe(23), # Erkannter Text
                )

                # NEU: Prüfe ob Datum gültig ist
                jahr = safe(1)
                datum = safe(2)
                notiz = safe(22)
                kirchenbuchtext = safe(24)  # Index 24 = kirchenbuchtext
                gramps = safe(25)  # Index 25 = gramps
                is_valid_date = self._is_valid_date(datum, jahr)

                # Tags setzen
                tags = []
                if notiz:
                    tags.append('has_notiz')
                if kirchenbuchtext:
                    tags.append('has_kirchenbuchtext')
                if gramps:
                    tags.append('has_gramps')
                if not is_valid_date and datum:
                    tags.append('invalid_date')

                self.tree.insert('', tk.END, values=values, tags=tuple(tags))
            
            self.db_status_label.config(text=f"{len(rows)} Datensätze gefunden")
            
            years = self.db.get_all_years()
            self.year_filter['values'] = ['Alle'] + [str(y) for y in years]
            if not self.year_filter.get():
                self.year_filter.current(0)

            cursor.execute("SELECT DISTINCT dateiname FROM karteikarten WHERE dateiname IS NOT NULL AND dateiname != ''")
            kb_values = sorted({
                titel
                for (dateiname,) in cursor.fetchall()
                for titel in [self._extract_kirchenbuch_titel(dateiname)]
                if titel
            })
            current_kb = self.kirchenbuch_filter.get()
            self.kirchenbuch_filter['values'] = ['Alle'] + kb_values
            if current_kb in self.kirchenbuch_filter['values']:
                self.kirchenbuch_filter.set(current_kb)
            else:
                self.kirchenbuch_filter.current(0)
                
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Laden der Daten:\n{str(e)}")

    def _extract_kirchenbuch_titel(self, dateiname: str) -> str:
        """Extrahiert "Hb 1695-1718" aus Dateinamen wie "3282 Hb 1717 - 1695-1718 - F....jpg"."""
        if not dateiname:
            return ''
        match = re.search(r"\b([A-Z][a-z])\s+\d{4}\s+-\s*(\d{4}-\d{4})", str(dateiname))
        if not match:
            return ''
        return f"{match.group(1)} {match.group(2)}"
    
    def _is_valid_date(self, datum: str, jahr: Optional[int]) -> bool:
        """
        Prüft ob ein Datum gültig ist (Jahr zwischen 1500 und 1754).
        
        Args:
            datum: Datumsstring (z.B. "20.11.1564" oder "00.03.1616")
            jahr: Extrahiertes Jahr aus der Datenbank
            
        Returns:
            True wenn gültig, False wenn ungültig
        """
        if not datum:
            return True  # Leeres Datum ist "gültig" (keine Fehlermeldung)
        
        # Prüfe ob Jahr im gültigen Bereich (1500-1754)
        if jahr is not None:
            if jahr < 1500 or jahr > 1754:
                return False
        
        # Prüfe Datumsformat: dd.mm.yyyy oder 00.mm.yyyy
        import re
        match = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', datum)
        if not match:
            return False  # Ungültiges Format
        
        tag_str, monat_str, jahr_str = match.groups()
        
        try:
            tag = int(tag_str)
            monat = int(monat_str)
            jahr_aus_datum = int(jahr_str)
            
            # Jahr muss zwischen 1500 und 1754 liegen
            if jahr_aus_datum < 1500 or jahr_aus_datum > 1754:
                return False
            
            # Monat muss zwischen 1 und 12 liegen
            if monat < 1 or monat > 12:
                return False
            
            # Tag kann 00 sein (unbekannter Tag) oder zwischen 1 und 31
            if tag != 0 and (tag < 1 or tag > 31):
                return False
            
            return True
            
        except (ValueError, TypeError):
            return False
    
    def _sort_by_page_and_number(self):
        """Sortiert die Treeview nach Filmnummer, dann Seite, dann Nummer."""
        # Hole alle Items mit ihren Werten
        import re
        data = []
        for item in self.tree.get_children(''):
            values = self.tree.item(item)['values']
            # Korrekte Indizes: values[5] = Seite, values[6] = Nr, values[21] = Dateiname
            seite = values[5] if len(values) > 5 else ''
            nummer = values[6] if len(values) > 6 else ''
            dateiname = values[21] if len(values) > 21 else ''  # Index 21 = Dateiname
            
            # Filmnummer extrahieren (z.B. F102779699 aus "0012 Hb 1564 - 1564-1611 - F102779699_erf.jpg")
            filmnummer = ''
            m = re.search(r'(F\d{9,})', str(dateiname))
            if m:
                filmnummer = m.group(1)
            
            # Konvertiere zu Integer für numerische Sortierung
            try:
                seite_int = int(seite) if seite else 0
            except (ValueError, TypeError):
                seite_int = 0
            try:
                nummer_int = int(nummer) if nummer else 0
            except (ValueError, TypeError):
                nummer_int = 0
            
            data.append((filmnummer, seite_int, nummer_int, dateiname, item))
        
        # DEBUG: Zeige erste 10 Einträge vor Sortierung
        print(f"\nDEBUG: Sortierung nach Film/Seite/Nr.")
        print(f"Anzahl Einträge: {len(data)}")
        print(f"Erste 10 Einträge (vor Sortierung):")
        for i, (film, seite, nr, datei, _) in enumerate(data[:10]):
            print(f"  {i+1}. Film={film or '(keine)'}, Seite={seite}, Nr={nr}, Datei={datei}")
        
        # Sortiere nach Filmnummer, dann Seite, dann Nummer
        # Wichtig: Leere Filmnummern ans Ende
        data.sort(key=lambda x: (x[0] if x[0] else 'ZZZZZZ', x[1], x[2]))
        
        # DEBUG: Zeige erste 10 Einträge nach Sortierung
        print(f"\nErste 10 Einträge (nach Sortierung):")
        for i, (film, seite, nr, datei, _) in enumerate(data[:10]):
            print(f"  {i+1}. Film={film or '(keine)'}, Seite={seite}, Nr={nr}, Datei={datei}")
        print()
        
        # Reorganisiere die Items in der Treeview
        for index, (_, _, _, _, item) in enumerate(data):
            self.tree.move(item, '', index)
        # Zeige Sortierung in Spaltenüberschriften an
        for column in self.tree['columns']:
            current_heading = self.tree.heading(column)['text']
            clean_heading = current_heading.replace(' ▲', '').replace(' ▼', '')
            if column == 'Dateiname':
                self.tree.heading(column, text=clean_heading + ' ▲')
            elif column == 'Seite':
                self.tree.heading(column, text=clean_heading + ' ▲')
            elif column == 'Nr':
                self.tree.heading(column, text=clean_heading + ' ▲')
            else:
                self.tree.heading(column, text=clean_heading)
        # Update Status
        self.db_status_label.config(text=f"{len(data)} Datensätze - sortiert nach Film/Seite/Nr.")
    
    def _filter_invalid_citations(self):
        """Zeigt nur Datensätze an, die NICHT dem exakten formatierten Zitations-Muster entsprechen."""
        import re

        # STRIKTES Pattern für KORREKT formatierte Zitation
        # Format: "ev. Kb. Wetzlar [⚰∞] YYYY.MM.DD. p. X Nr. Y "
        # - Kleinbuchstaben "p." (nicht "P.")
        # - Genau ein Leerzeichen zwischen Elementen
        # - Kein Komma vor "Nr."
        # - Punkt nach "ev", "Kb", "DD", aber NICHT nach "Wetzlar"
        valid_pattern = r"^ev\. Kb\. Wetzlar [⚰∞\u26B0] \d{4}\.\d{2}\.\d{2}\. p\. \d+ Nr\. \d+ "
        
        # Sammle alle Items, die NICHT dem exakten Muster entsprechen
        invalid_items = []
        valid_count = 0
        
        for item in self.tree.get_children(''):
            values = self.tree.item(item)['values']
            # Index 21 = Text (erkannter_text)
            if len(values) > 21:
                text = str(values[21])
            else:
                continue
            
            # Prüfe: beginnt NICHT mit "inf" UND matched NICHT das strikte Pattern
            if not text.lower().startswith('inf'):
                match = re.match(valid_pattern, text)
                if not match:
                    invalid_items.append(item)
                    # Debug: Zeige erste 5 ungültige mit Fehleranalyse
                    if len(invalid_items) <= 5:
                        # Analysiere wo die Abweichung ist
                        abweichungen = []
                        
                        # Erwartetes Format: "ev. Kb. Wetzlar [⚰∞] YYYY.MM.DD. p. X Nr. Y "
                        if not text.startswith("ev. Kb. Wetzlar "):
                            if text.startswith("ev. Kb. Wetzlar."):
                                abweichungen.append("Punkt nach 'Wetzlar'")
                            elif "Wetzlar" in text[:30]:
                                idx = text.index("Wetzlar") + 7
                                abweichungen.append(f"Fehler nach Wetzlar: '{text[idx:idx+5]}'")
                            else:
                                abweichungen.append("Prefix fehlt/falsch")
                        
                        # Prüfe auf großes P
                        if re.search(r'\bP\.', text[:80]):
                            abweichungen.append("Großes 'P.' statt 'p.'")
                        
                        # Prüfe auf Komma vor Nr.
                        if re.search(r'p\.\s*\d+\s*,\s*Nr\.', text[:80]):
                            abweichungen.append("Komma vor 'Nr.'")
                        
                        # Prüfe auf pp. statt p.
                        if re.search(r'\bpp\.', text[:80], re.IGNORECASE):
                            abweichungen.append("'pp.' statt 'p.'")
                        
                        # Prüfe Datumsformat
                        datum_match = re.search(r'(\d{4})[\.,\s]+(\d{1,2})[\.,\s]+(\d{1,2})', text[:50])
                        if datum_match:
                            jahr, monat, tag = datum_match.groups()
                            if len(monat) == 1 or len(tag) == 1:
                                abweichungen.append(f"Datum ohne führende Null: {jahr}.{monat}.{tag}")
                            # Prüfe auf Komma im Datum
                            if ',' in datum_match.group(0):
                                abweichungen.append("Komma im Datum")
                        
                        fehler_text = ", ".join(abweichungen) if abweichungen else "Unbekannte Abweichung"
                        print(f"DEBUG UNGÜLTIG [{fehler_text}]: {repr(text[:100])}")
                else:
                    valid_count += 1
                    # Debug: Zeige erste 3 gültige an
                    if valid_count <= 3:
                        print(f"DEBUG GÜLTIG: {repr(text[:100])}")
        
        print(f"DEBUG: Gültige: {valid_count}, Ungültige: {len(invalid_items)}")
        
        # Deselektiere alles
        self.tree.selection_remove(*self.tree.get_children(''))
        
        # Selektiere nur die ungültigen Items
        if invalid_items:
            for item in invalid_items:
                self.tree.selection_add(item)
            # Scrolle zum ersten ungültigen Item
            self.tree.see(invalid_items[0])
            self.db_status_label.config(text=f"{len(invalid_items)} Datensätze mit ungültiger Formatierung ausgewählt")
            messagebox.showinfo(
                "Ungültige Zitationen gefunden",
                f"{len(invalid_items)} Datensätze haben KEINE korrekte Formatierung.\n"
                f"({valid_count} sind korrekt formatiert)\n\n"
                f"Korrektes Format:\n"
                f"'ev. Kb. Wetzlar ⚰ YYYY.MM.DD. p. X Nr. Y ...'\n\n"
                f"Häufige Fehler:\n"
                f"- Großbuchstaben 'P.' statt 'p.'\n"
                f"- Komma vor 'Nr.': 'p. 18, Nr. 3'\n"
                f"- Punkt nach 'Wetzlar': 'Wetzlar.'\n"
                f"- Falsche Leerzeichen\n\n"
                f"Tipp: Mit '📋 Zitation formatieren' korrigieren."
            )
        else:
            self.db_status_label.config(text="Alle Zitationen korrekt formatiert")
            messagebox.showinfo("Filter", "Alle Datensätze (außer 'inf'-Einträge) haben korrekt formatierte Zitationen!")
    
    def _clear_filters(self):
        """Löscht alle Filter."""
        self.id_filter.delete(0, tk.END)
        self.year_filter.set('Alle')
        self.type_filter.current(0)
        self.filename_filter.current(0)
        self.kirchenbuch_filter.current(0)
        self.name_search.delete(0, tk.END)
        self._refresh_db_list()
    
    def _sort_column(self, col):
        """Sortiert die Treeview-Spalte."""
        if col not in self.sort_reverse:
            self.sort_reverse[col] = False
        else:
            self.sort_reverse[col] = not self.sort_reverse[col]
        
        # Speichere die aktuell sortierte Spalte
        self._last_sorted_column = col
        
        reverse = self.sort_reverse[col]
        numeric_columns = ['ID', 'Jahr', 'Seite', 'Nr']
        data = [(self.tree.set(item, col), item) for item in self.tree.get_children('')]
        
        if col in numeric_columns:
            def numeric_key(val_item):
                val = val_item[0]
                try:
                    return int(val) if val else 0
                except (ValueError, TypeError):
                    return 0
            data.sort(key=numeric_key, reverse=reverse)
        elif col == 'Datum':
            def date_key(val_item):
                val = val_item[0]
                if not val:
                    return '0000-00-00'
                try:
                    parts = val.split('.')
                    if len(parts) == 3:
                        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                    return '0000-00-00'
                except:
                    return '0000-00-00'
            data.sort(key=date_key, reverse=reverse)
        else:
            data.sort(reverse=reverse)
        
        for index, (val, item) in enumerate(data):
            self.tree.move(item, '', index)
        
        for column in self.tree['columns']:
            current_heading = self.tree.heading(column)['text']
            clean_heading = current_heading.replace(' ▲', '').replace(' ▼', '')
            
            if column == col:
                arrow = ' ▲' if not reverse else ' ▼'
                self.tree.heading(column, text=clean_heading + arrow)
            else:
                self.tree.heading(column, text=clean_heading)

        # Merke zuletzt sortierte Spalte
        self._last_sorted_column = col

    def _select_empty_in_sorted_column(self):
        """Filtert die Tabelle so, dass nur Zeilen mit leerem Feld in der sortierten Spalte angezeigt werden."""
        col = self._last_sorted_column
        if not col:
            messagebox.showinfo("Hinweis", "Bitte zuerst eine Spalte sortieren.")
            return
        col_index = list(self.tree['columns']).index(col)
        # Alle Items durchgehen und nur die mit leerem Wert behalten
        items_to_keep = []
        for item in self.tree.get_children(''):
            values = self.tree.item(item)['values']
            if col_index < len(values) and (values[col_index] is None or str(values[col_index]).strip() == ""):
                items_to_keep.append((item, values))
        # Erst alle Zeilen entfernen
        for item in self.tree.get_children(''):
            self.tree.delete(item)
        # Dann nur die passenden wieder einfügen
        for item_id, values in items_to_keep:
            self.tree.insert('', 'end', iid=item_id, values=values)
        # Statuszeile aktualisieren
        self.db_status_label.config(text=f"{len(items_to_keep)} Datensätze gefunden")
        if not items_to_keep:
            messagebox.showinfo("Keine leeren Felder", f"Keine leeren Felder in der Spalte '{col}' gefunden.")
    
    def _on_tree_double_click(self, event):
        """Wird bei Doppelklick auf einen Eintrag aufgerufen."""
        self._show_selected_card()
    
    def _show_tree_menu(self, event):
        """Zeigt Kontextmenü an."""
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)

    def _copy_selected_rows_to_clipboard(self):
        """Kopiert die ausgewählten Zeilen als TSV in die Zwischenablage."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return

        columns = list(self.tree['columns'])
        header = "\t".join(columns)
        rows = []
        for item in selection:
            values = self.tree.item(item).get('values', [])
            row = ["" if value is None else str(value) for value in values]
            rows.append("\t".join(row))

        text = "\n".join([header] + rows)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
    
    def _clear_ocr_field_labels(self):
        """Löscht die erkannten Felder im OCR-Tab."""
        if hasattr(self, 'ocr_field_vars'):
            for field_key, var in self.ocr_field_vars.items():
                var.set("")
        else:
            for field in self.ocr_field_labels:
                self.ocr_field_labels[field].config(text="—", foreground="gray")
        
        # Lösche auch die gespeicherten erkannten Felder
        if hasattr(self, '_last_recognized_fields'):
            delattr(self, '_last_recognized_fields')
        
        # Setze Status zurück
        self.db_record_status.config(text="", foreground="blue")

    def _set_ocr_field_value(self, field_key: str, value):
        if not hasattr(self, 'ocr_field_vars'):
            return
        if field_key not in self.ocr_field_vars:
            return
        self.ocr_field_vars[field_key].set(value or "")

    def _get_ocr_field_value(self, field_key: str) -> Optional[str]:
        if not hasattr(self, 'ocr_field_vars'):
            return None
        var = self.ocr_field_vars.get(field_key)
        if not var:
            return None
        value = var.get().strip()
        return value if value else None

    def _load_ocr_fields_from_db(self, record_id: int):
        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT vorname, nachname, partner, stand, braeutigam_stand, beruf, ort, seite, nummer, todestag,
                   geb_jahr_gesch, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                   ereignis_typ
            FROM karteikarten WHERE id = ?
            """,
            (record_id,)
        )
        row = cursor.fetchone()
        if not row:
            return

        (vorname, nachname, partner, stand, braeutigam_stand, beruf, ort, seite, nummer, todestag,
         geb_jahr_gesch, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
         ereignis_typ) = row

        is_marriage = bool(ereignis_typ and str(ereignis_typ).lower().startswith('heirat'))

        self._set_ocr_field_value('vorname', vorname)
        self._set_ocr_field_value('nachname', nachname)
        self._set_ocr_field_value('partner', partner)
        self._set_ocr_field_value('beruf', beruf)
        self._set_ocr_field_value('ort', ort)
        self._set_ocr_field_value('seite', str(seite) if seite is not None else None)
        self._set_ocr_field_value('nummer', str(nummer) if nummer is not None else None)
        self._set_ocr_field_value('todestag', todestag)
        self._set_ocr_field_value('geb.jahr (gesch.)', str(geb_jahr_gesch) if geb_jahr_gesch is not None else None)
        self._set_ocr_field_value('bräutigam stand', braeutigam_stand)
        self._set_ocr_field_value('bräutigam vater', braeutigam_vater)
        self._set_ocr_field_value('braut vater', braut_vater)
        self._set_ocr_field_value('braut nachname', braut_nachname)
        self._set_ocr_field_value('braut ort', braut_ort)

        if is_marriage:
            self._set_ocr_field_value('braut stand', stand)
            self._set_ocr_field_value('stand', None)
        else:
            self._set_ocr_field_value('stand', stand)
            self._set_ocr_field_value('braut stand', None)

    def _on_tab_changed(self, event):
        selected = event.widget.select()
        if hasattr(self, 'ocr_tab') and selected == str(self.ocr_tab):
            if self.current_db_record_id:
                self._load_ocr_fields_from_db(self.current_db_record_id)
    
    def _show_selected_card(self):
        """Zeigt die ausgewählte Karteikarte im OCR-Tab."""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        record_id = self.tree.item(item)['values'][0]
        
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT dateipfad, erkannter_text, kirchenbuchtext FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        
        if row:
            dateipfad = Path(row[0])
            erkannter_text = row[1]
            kirchenbuchtext = row[2] if len(row) > 2 and row[2] else ""
            try:
                idx = self.image_files.index(dateipfad)
                self.current_index = idx
                self.current_db_record_id = record_id
                
                # Erkannte Felder im OCR-Tab zurücksetzen
                self._clear_ocr_field_labels()
                
                self._display_current_card()
                
                self.text_display.delete("1.0", tk.END)
                self.text_display.insert("1.0", erkannter_text)

                # OCR-Felder aus DB laden (editierbar)
                self._load_ocr_fields_from_db(record_id)
                
                # Kirchenbuchtext anzeigen
                self.kirchenbuch_text_display.delete("1.0", tk.END)
                if kirchenbuchtext:
                    self.kirchenbuch_text_display.insert("1.0", kirchenbuchtext)
                
                # F-ID und Gramps laden
                cursor = self.db.conn.cursor()
                cursor.execute("SELECT notiz, gramps FROM karteikarten WHERE id = ?", (record_id,))
                row_data = cursor.fetchone()
                self.fid_entry.delete(0, tk.END)
                self.gramps_entry.delete(0, tk.END)
                if row_data:
                    if row_data[0]:  # notiz
                        self.fid_entry.insert(0, row_data[0])
                    if row_data[1]:  # gramps
                        self.gramps_entry.insert(0, row_data[1])
                
                self.notebook.select(0)
            except ValueError:
                messagebox.showwarning("Warnung", "Bilddatei nicht in der aktuellen Liste gefunden.")
    
    def _show_selected_text(self):
        """Zeigt den erkannten Text in einem Fenster."""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        record_id = self.tree.item(item)['values'][0]
        
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT erkannter_text, dateiname FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        
        if row:
            text_window = tk.Toplevel(self.root)
            text_window.title(f"Text: {row[1]}")
            text_window.geometry("600x400")
            
            text_widget = tk.Text(text_window, wrap=tk.WORD, font=("Arial", 14))
            text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            text_widget.insert("1.0", row[0])
            text_widget.config(state=tk.DISABLED)
    
    def _edit_fid(self):
        """Öffnet Dialog zum Bearbeiten der F-ID (Notiz-Feld)."""
        selection = self.tree.selection()
        if not selection:
            return
        
        # Bei Mehrfachauswahl nur den ersten Eintrag bearbeiten
        item = selection[0]
        record_id = self.tree.item(item)['values'][0]
        
        # Aktuellen F-ID Wert aus DB holen
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT notiz, dateiname FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        
        if not row:
            return
        
        current_fid = row[0] if row[0] else ""
        dateiname = row[1]
        
        # Dialog erstellen
        dialog = tk.Toplevel(self.root)
        dialog.title(f"F-ID bearbeiten: {dateiname}")
        dialog.geometry("400x150")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Label
        label_frame = ttk.Frame(dialog)
        label_frame.pack(fill=tk.X, padx=20, pady=(20, 10))
        ttk.Label(label_frame, text="F-ID:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        
        # Eingabefeld
        entry_var = tk.StringVar(value=current_fid)
        entry = ttk.Entry(dialog, textvariable=entry_var, font=("Arial", 12), width=30)
        entry.pack(padx=20, pady=10)
        entry.focus()
        entry.select_range(0, tk.END)
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_fid():
            new_fid = entry_var.get().strip()
            
            # In Datenbank speichern
            cursor = self.db.conn.cursor()
            cursor.execute("UPDATE karteikarten SET notiz = ? WHERE id = ?", (new_fid, record_id))
            self.db.conn.commit()
            
            # TreeView aktualisieren
            values = list(self.tree.item(item)['values'])
            # Notiz ist Spalte 21 (0-basiert)
            values[21] = new_fid
            self.tree.item(item, values=values)
            
            # Tag aktualisieren (grün wenn F-ID gesetzt)
            current_tags = list(self.tree.item(item)['tags'])
            if new_fid:
                if 'has_notiz' not in current_tags:
                    current_tags.append('has_notiz')
            else:
                if 'has_notiz' in current_tags:
                    current_tags.remove('has_notiz')
            self.tree.item(item, tags=current_tags)
            
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Speichern", command=save_fid).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=cancel).pack(side=tk.LEFT, padx=5)
        
        # Enter-Taste zum Speichern
        entry.bind('<Return>', lambda e: save_fid())
        # Escape zum Abbrechen
        dialog.bind('<Escape>', lambda e: cancel())

    def _edit_geb_jahr_gesch(self):
        """Öffnet Dialog zum Bearbeiten des geschätzten Geburtsjahrs durch Eingabe des Alters."""
        # Hole aktuelles Todestag-Feld
        todestag = self._get_ocr_field_value('todestag')
        
        if not todestag:
            messagebox.showwarning(
                "Kein Todestag",
                "Bitte zuerst das Feld 'Todestag' ausfüllen.\n\n"
                "Das Geburtsjahr wird berechnet als: Todestag - Alter"
            )
            return
        
        # Extrahiere Jahr aus Todestag (Format: YYYY.MM.DD oder YYYY-MM-DD)
        import re
        jahr_match = re.match(r'(\d{4})', todestag)
        if not jahr_match:
            messagebox.showerror(
                "Ungültiges Datum",
                f"Das Todestag-Format ist ungültig: {todestag}\n\n"
                "Erwartet: YYYY.MM.DD oder YYYY-MM-DD"
            )
            return
        
        todes_jahr = int(jahr_match.group(1))
        
        # Hole aktuelles Geburtsjahr (falls bereits gesetzt)
        current_geb_jahr = self._get_ocr_field_value('geb.jahr (gesch.)')
        current_alter = None
        if current_geb_jahr and current_geb_jahr.isdigit():
            current_alter = todes_jahr - int(current_geb_jahr)
        
        # Dialog erstellen
        dialog = tk.Toplevel(self.root)
        dialog.title("Geschätztes Geburtsjahr berechnen")
        dialog.geometry("450x250")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Info-Frame
        info_frame = ttk.Frame(dialog)
        info_frame.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        ttk.Label(
            info_frame, 
            text=f"Todestag: {todestag} (Jahr: {todes_jahr})",
            font=("Arial", 10, "bold")
        ).pack(anchor=tk.W)
        
        ttk.Label(
            info_frame,
            text="Geben Sie das Alter in Jahren ein:",
            font=("Arial", 9)
        ).pack(anchor=tk.W, pady=(10, 0))
        
        # Eingabefeld für Alter
        entry_frame = ttk.Frame(dialog)
        entry_frame.pack(fill=tk.X, padx=20, pady=10)
        
        ttk.Label(entry_frame, text="Alter (Jahre):", font=("Arial", 10)).pack(side=tk.LEFT, padx=(0, 10))
        
        alter_var = tk.StringVar(value=str(current_alter) if current_alter else "")
        alter_entry = ttk.Entry(entry_frame, textvariable=alter_var, font=("Arial", 12), width=10)
        alter_entry.pack(side=tk.LEFT, padx=5)
        alter_entry.focus()
        alter_entry.select_range(0, tk.END)
        
        # Ergebnis-Label
        result_label = ttk.Label(
            dialog, 
            text="", 
            font=("Arial", 11, "bold"),
            foreground="blue"
        )
        result_label.pack(pady=10)
        
        # Berechne und zeige Vorschau
        def update_preview(*args):
            alter_str = alter_var.get().strip()
            if alter_str and alter_str.isdigit():
                alter = int(alter_str)
                geb_jahr = todes_jahr - alter
                result_label.config(
                    text=f"➜ Geschätztes Geburtsjahr: {geb_jahr}\n({todes_jahr} - {alter} = {geb_jahr})"
                )
            else:
                result_label.config(text="")
        
        alter_var.trace('w', update_preview)
        update_preview()  # Initiale Anzeige
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_geb_jahr():
            alter_str = alter_var.get().strip()
            if not alter_str or not alter_str.isdigit():
                messagebox.showwarning("Ungültige Eingabe", "Bitte eine gültige Zahl eingeben.")
                return
            
            alter = int(alter_str)
            geb_jahr = todes_jahr - alter
            
            # Setze Wert im Feld
            self._set_ocr_field_value('geb.jahr (gesch.)', str(geb_jahr))
            
            dialog.destroy()
            
            messagebox.showinfo(
                "Gespeichert",
                f"Geschätztes Geburtsjahr: {geb_jahr}\n\n"
                f"Berechnung: {todes_jahr} - {alter} = {geb_jahr}\n\n"
                "Nutzen Sie '📤 DB aktualisieren', um in die Datenbank zu speichern."
            )
        
        def cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="💾 Speichern", command=save_geb_jahr).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="❌ Abbrechen", command=cancel).pack(side=tk.LEFT, padx=5)
        
        # Enter-Taste zum Speichern
        alter_entry.bind('<Return>', lambda e: save_geb_jahr())
        # Escape zum Abbrechen
        dialog.bind('<Escape>', lambda e: cancel())

    def _delete_selected(self):
        """Löscht die ausgewählten Datensätze."""
        selection = self.tree.selection()
        if not selection:
            return
        
        record_ids = []
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            record_ids.append(record_id)
        
        count = len(record_ids)
        if count == 1:
            msg = f"Datensatz ID {record_ids[0]} wirklich löschen?"
        else:
            msg = f"{count} ausgewählte Datensätze wirklich löschen?\n\nIDs: {', '.join(map(str, record_ids[:10]))}"
            if count > 10:
                msg += f"... (+{count - 10} weitere)"
        
        if messagebox.askyesno("Löschen bestätigen", msg):
            cursor = self.db.conn.cursor()
            for record_id in record_ids:
                cursor.execute("DELETE FROM karteikarten WHERE id = ?", (record_id,))
            self.db.conn.commit()
            self._refresh_db_list()
            
            messagebox.showinfo("Erfolg", f"{count} Datensatz/Datensätze gelöscht.")
    
    def _save_to_database(self):
        """Speichert die aktuelle Karteikarte in der Datenbank."""
        if not self.current_image:
            messagebox.showwarning("Warnung", "Keine Karteikarte geladen.")
            return
        
        text = self.text_display.get("1.0", tk.END).strip()
        if not text or text == "Texterkennung läuft...":
            messagebox.showwarning("Warnung", "Bitte führen Sie zuerst die OCR-Texterkennung durch.")
            return
        
        if self.current_db_record_id is None:
            self._check_db_status()
        
        if self.current_db_record_id:
            antwort = messagebox.askyesno(
                "Überschreiben bestätigen",
                f"Diese Karteikarte ist bereits in der Datenbank gespeichert!\n\n"
                f"Datenbank-ID: {self.current_db_record_id}\n"
                f"Datei: {self.current_image.name}\n\n"
                f"Möchten Sie den bestehenden Eintrag wirklich überschreiben?\n\n"
                f"⚠️ Die alten Daten gehen dabei verloren!",
                icon='warning'
            )
            if not antwort:
                return
        
        try:
            dateiname = self.current_image.name
            dateipfad = str(self.current_image.absolute())
            ocr_methode = self.ocr_method if self.ocr_engine else 'unbekannt'
            
            # Hole Kirchenbuchtext
            kirchenbuchtext = self.kirchenbuch_text_display.get("1.0", tk.END).strip()
            kirchenbuchtext = kirchenbuchtext if kirchenbuchtext else None
            
            # Hole F-ID
            fid = self.fid_entry.get().strip()
            fid = fid if fid else None
            
            # Hole Gramps
            gramps = self.gramps_entry.get().strip()
            gramps = gramps if gramps else None
            
            record_id = self.db.save_karteikarte(
                dateiname=dateiname,
                dateipfad=dateipfad,
                erkannter_text=text,
                ocr_methode=ocr_methode,
                kirchenbuchtext=kirchenbuchtext
            )
            
            # Update F-ID und Gramps separat (da save_karteikarte es nicht unterstützt)
            if record_id:
                cursor = self.db.conn.cursor()
                cursor.execute("UPDATE karteikarten SET notiz = ?, gramps = ? WHERE id = ?", (fid, gramps, record_id))
                self.db.conn.commit()
            
            self.current_db_record_id = record_id;
            
            self._refresh_db_list()
            self._check_db_status()
            
            aktion = "aktualisiert" if self.current_db_record_id else "gespeichert"
            messagebox.showinfo(
                "Erfolg", 
                f"Karteikarte in Datenbank {aktion}!\n\n"
                f"ID: {record_id}\n"
                f"Datei: {dateiname}\n\n"
                f"Tipp: Wechseln Sie zum Tab '📊 Datenbank' um alle Einträge zu sehen."
            )
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Speichern in DB:\n{str(e)}")
    
    def _show_statistics(self):
        """Zeigt Statistiken über die Datenbank."""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM karteikarten")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT ereignis_typ, COUNT(*) FROM karteikarten GROUP BY ereignis_typ ORDER BY ereignis_typ")
            typ_stats = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) FROM karteikarten WHERE notiz IS NOT NULL AND notiz != ''")
            with_fid = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM karteikarten WHERE gramps IS NOT NULL AND gramps != ''")
            with_gramps = cursor.fetchone()[0]

            # Je Typ: KB-Titel (aus dateiname) mit Anzahl Eintraege + ISO-Datumsbereich
            cursor.execute(
                "SELECT ereignis_typ, dateiname, iso_datum FROM karteikarten ORDER BY ereignis_typ, dateiname"
            )
            kb_rows = cursor.fetchall()

            # dateiname-Muster: "NNNN Hb 1630 - 1611-1632 - F102779699_erf.jpg"
            # KB-Titel = Typ-Kuerzel + Jahresbereich, z.B. "Hb 1611-1632"
            kb_title_pattern = re.compile(r"\b([A-Z][a-z])\s+\d{4}\s+-\s*(\d{4}-\d{4})")

            from collections import defaultdict

            # {ereignis_typ -> {kb_titel -> {"count": int, "min_iso": str, "max_iso": str}}}
            kb_per_typ = defaultdict(lambda: defaultdict(lambda: {"count": 0, "min_iso": None, "max_iso": None}))
            for ereignis_typ, dateiname, iso_datum in kb_rows:
                typ_key = ereignis_typ or "(leer)"
                if dateiname:
                    match = kb_title_pattern.search(str(dateiname))
                    kb_titel = f"{match.group(1)} {match.group(2)}" if match else "(unbekannt)"
                else:
                    kb_titel = "(unbekannt)"

                entry = kb_per_typ[typ_key][kb_titel]
                entry["count"] += 1
                if iso_datum:
                    if entry["min_iso"] is None or iso_datum < entry["min_iso"]:
                        entry["min_iso"] = iso_datum
                    if entry["max_iso"] is None or iso_datum > entry["max_iso"]:
                        entry["max_iso"] = iso_datum

            lines = [
                f"Gesamt: {total} Datensaetze",
                f"Mit F-ID: {with_fid}",
                f"Mit Gramps: {with_gramps}",
                "",
                "Nach Ereignistyp:",
            ]

            for typ, count in typ_stats:
                typ_label = typ or "(leer)"
                lines.append(f"  {typ_label}: {count}")

            lines.append("")
            lines.append("Kirchenbuecher je Typ:")
            for typ, _count in typ_stats:
                typ_label = typ or "(leer)"
                lines.append(f"\n  [{typ_label}]")
                kb_map = kb_per_typ.get(typ_label, {})
                for kb_titel, data in sorted(kb_map.items()):
                    min_iso = data["min_iso"] or "?"
                    max_iso = data["max_iso"] or "?"
                    lines.append(f"    {kb_titel:<16}  {data['count']:>4}  {min_iso} - {max_iso}")

            win = tk.Toplevel(self.root)
            win.title("Statistik")
            win.geometry("540x520")

            txt = tk.Text(win, font=("Arial", 11), wrap=tk.WORD)
            txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            txt.insert("1.0", "\n".join(lines))
            txt.config(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Abrufen der Statistik:\n{str(e)}")
    
    def _export_csv(self):
        """Exportiert die Datenbank als CSV."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile="karteikarten_export.csv",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")]
        )
        
        if filepath:
            try:
                self.db.export_to_csv(filepath)
                messagebox.showinfo("Erfolg", f"Datenbank exportiert nach:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Fehler", f"Fehler beim Export:\n{str(e)}")
    
    def _export_gedcom(self):
        """Exportiert die Datenbank als GEDCOM-Datei (GRAMPS-Dialekt)."""
        # Prüfen ob Einträge ausgewählt sind
        selection = self.tree.selection()
        
        # Dialog: Alle oder nur Auswahl exportieren
        export_all = True
        if selection:
            result = messagebox.askyesnocancel(
                "Export-Auswahl",
                f"{len(selection)} Einträge sind ausgewählt.\n\n"
                f"Ja = Nur Auswahl exportieren\n"
                f"Nein = Alle Einträge exportieren\n"
                f"Abbrechen = Export abbrechen"
            )
            if result is None:  # Cancel
                return
            export_all = not result  # Nein -> True, Ja -> False
        
        # Datei-Dialog
        filepath = filedialog.asksaveasfilename(
            defaultextension=".ged",
            initialfile="karteikarten_export.ged",
            filetypes=[("GEDCOM-Dateien", "*.ged"), ("Alle Dateien", "*.*")]
        )
        
        if not filepath:
            return
        
        try:
            # Erstelle GedcomExporter
            exporter = GedcomExporter(self.db.conn)
            
            # Filter-Parameter vorbereiten
            filter_params = {}
            
            if not export_all and selection:
                # Nur ausgewählte IDs exportieren
                id_list = []
                for item in selection:
                    record_id = self.tree.item(item)['values'][0]
                    id_list.append(record_id)
                filter_params['id_list'] = id_list
            
            # Export durchführen
            exported_count = exporter.export_to_gedcom(filepath, filter_params)
            
            # Erfolgsmeldung
            messagebox.showinfo(
                "Erfolg",
                f"✅ GEDCOM-Export erfolgreich!\n\n"
                f"Datei: {Path(filepath).name}\n"
                f"Exportierte Datensätze: {exported_count}\n"
                f"Format: GRAMPS-Dialekt\n\n"
                f"Die Datei kann jetzt in GRAMPS oder andere\n"
                f"Genealogie-Programme importiert werden."
            )
            
        except ValueError as e:
            messagebox.showwarning("Keine Daten", str(e))
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim GEDCOM-Export:\n{str(e)}")

    def _export_gedcom_selected_from_context(self):
        """Exportiert per Kontextmenue nur die ausgewaehlten Datensaetze als GEDCOM."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte waehlen Sie mindestens einen Datensatz aus.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".ged",
            initialfile="karteikarten_export_auswahl.ged",
            filetypes=[("GEDCOM-Dateien", "*.ged"), ("Alle Dateien", "*.*")]
        )

        if not filepath:
            return

        try:
            exporter = GedcomExporter(self.db.conn)

            id_list = []
            for item in selection:
                record_id = self.tree.item(item)['values'][0]
                id_list.append(record_id)

            filter_params = {'id_list': id_list}
            exported_count = exporter.export_to_gedcom(filepath, filter_params)

            messagebox.showinfo(
                "Erfolg",
                f"✅ GEDCOM-Export erfolgreich!\n\n"
                f"Datei: {Path(filepath).name}\n"
                f"Exportierte Datensaetze (Auswahl): {exported_count}\n"
                f"Format: GRAMPS-Dialekt"
            )

        except ValueError as e:
            messagebox.showwarning("Keine Daten", str(e))
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim GEDCOM-Export:\n{str(e)}")

    
    def _import_csv(self):
        """Importiert Daten aus einer CSV-Datei in die Datenbank."""
        filepath = filedialog.askopenfilename(
            title="CSV-Datei zum Importieren auswählen",
            initialdir=Path.home() / "Desktop",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")]
        )
        
        if not filepath:
            return
        
        # Bestätigung mit Warnung
        if not messagebox.askyesno(
            "Import bestätigen",
            f"⚠️ ACHTUNG: Import aus CSV-Datei\n\n"
            f"Datei: {Path(filepath).name}\n\n"
            f"Die Daten aus der CSV-Datei werden in die Datenbank importiert.\n"
            f"Bereits vorhandene Einträge (gleicher Dateipfad) werden ÜBERSCHRIEBEN!\n\n"
            f"Möchten Sie fortfahren?",
            icon='warning'
        ):
            return
        
        try:
            # Nutze die neue DB-Methode, die IDs beibehält
            erfolge, aktualisiert, fehler = self.db.import_from_csv(
                csv_path=filepath,
                preserve_ids=True  # IDs aus CSV übernehmen
            )
            
            # Aktualisiere Anzeige
            self._refresh_db_list()
            
            # Erfolgsmeldung
            messagebox.showinfo(
                "Import abgeschlossen",
                f"✅ CSV-Import erfolgreich abgeschlossen!\n\n"
                f"Datei: {Path(filepath).name}\n\n"
                f"Neu importiert: {erfolge}\n"
                f"Aktualisiert: {aktualisiert}\n"
                f"Fehler: {fehler}\n\n"
                f"ℹ️ Die Original-IDs aus der CSV wurden übernommen."
            )
            
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Import:\n{str(e)}")

    def _import_xlsx(self):
        """Importiert Daten aus einer XLSX-Datei und aktualisiert vorhandene Datensätze."""
        try:
            import unicodedata

            from openpyxl import load_workbook
            from openpyxl.utils.datetime import from_excel
        except Exception:
            messagebox.showerror(
                "Fehlendes Paket",
                "Zum XLSX-Import wird das Paket 'openpyxl' benötigt.\n"
                "Bitte installieren und erneut versuchen."
            )
            return

        default_path = Path(
            r"D:\projects\Wetzlar_csv\input\Merge\00_KB_1571-1613_Taufen_EINGABE001_V6--zur Sicherheit mit Vornamen.xlsx"
        )
        filepath = filedialog.askopenfilename(
            title="XLSX-Datei zum Importieren auswählen",
            initialdir=default_path.parent if default_path.parent.exists() else Path.home(),
            initialfile=default_path.name,
            filetypes=[("Excel-Dateien", "*.xlsx"), ("Alle Dateien", "*.*")]
        )

        if not filepath:
            return

        if not messagebox.askyesno(
            "Import bestätigen",
            f"⚠️ ACHTUNG: Import aus XLSX-Datei\n\n"
            f"Datei: {Path(filepath).name}\n\n"
            f"Der Abgleich erfolgt über dateiname = XLSX:Karteikarte.\n"
            f"Gefundene Datensätze werden aktualisiert.\n\n"
            f"Möchten Sie fortfahren?",
            icon='warning'
        ):
            return

        def normalize_text(value):
            if value is None:
                return None
            text = str(value).strip()
            return text if text else None

        def normalize_number(value):
            if value is None:
                return None
            try:
                if isinstance(value, float) and value.is_integer():
                    return str(int(value))
                if isinstance(value, int):
                    return str(value)
            except Exception:
                pass
            return str(value).strip() if str(value).strip() else None

        def normalize_year(value):
            if value is None or str(value).strip() == "":
                return None
            try:
                return int(float(value))
            except Exception:
                return None

        def normalize_date(value, wb_epoch):
            if value is None or str(value).strip() == "":
                return None
            if hasattr(value, "strftime"):
                return value.strftime("%d.%m.%Y")
            if isinstance(value, (int, float)):
                try:
                    dt = from_excel(value, wb_epoch)
                    if hasattr(dt, "strftime"):
                        return dt.strftime("%d.%m.%Y")
                except Exception:
                    return None
            text = str(value).strip()
            match = re.match(r"^(\d{1,2})[\./-](\d{1,2})[\./-](\d{4})$", text)
            if match:
                day, month, year = match.groups()
                return f"{day.zfill(2)}.{month.zfill(2)}.{year}"
            match = re.match(r"^(\d{4})[\./-](\d{1,2})[\./-](\d{1,2})$", text)
            if match:
                year, month, day = match.groups()
                return f"{day.zfill(2)}.{month.zfill(2)}.{year}"
            return text

        def iso_from_datum(datum):
            if not datum:
                return None
            match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", datum)
            if not match:
                return None
            day, month, year = match.groups()
            return f"{year}-{month}-{day}"

        def stand_from_gender(value):
            if value is None:
                return None
            text = str(value).strip().lower()
            if text in {"m", "maennlich", "männlich", "male", "1"}:
                return "Sohn"
            if text in {"w", "weiblich", "female", "f", "2"}:
                return "Tochter"
            if "m" in text and "weib" not in text:
                return "Sohn"
            if "w" in text or "weib" in text:
                return "Tochter"
            return None

        def normalize_key(value):
            if value is None:
                return None
            text = str(value).strip()
            if not text:
                return None
            text = text.replace("\u00A0", " ")
            text = unicodedata.normalize("NFKC", text)
            text = re.sub(r"\s+", " ", text)
            return text.casefold()

        def build_match_keys(value):
            keys = set()
            if value is None:
                return keys
            raw = str(value).strip()
            if not raw:
                return keys
            raw = re.sub(r"_erf(?=\.(jpg|jpeg|png|tif|tiff)$)", "", raw, flags=re.IGNORECASE)
            base = re.sub(r"\.(jpg|jpeg|png|tif|tiff)$", "", raw, flags=re.IGNORECASE)
            base_no_inf = re.sub(r"_inf$", "", base, flags=re.IGNORECASE)
            base_no_erf = re.sub(r"_erf$", "", base, flags=re.IGNORECASE)
            base_no_inf_erf = re.sub(r"_erf$", "", base_no_inf, flags=re.IGNORECASE)
            for candidate in (raw, base, base_no_inf, base_no_erf, base_no_inf_erf):
                key = normalize_key(candidate)
                if key:
                    keys.add(key)
            return keys

        try:
            wb = load_workbook(filename=filepath, read_only=True, data_only=True)
            ws = wb.active

            header_row = None
            for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
                if row and any(cell is not None for cell in row):
                    header_row = row
                    break

            if not header_row:
                messagebox.showerror("Fehler", "Keine Header-Zeile in der XLSX-Datei gefunden.")
                return

            headers = {str(name).strip(): idx for idx, name in enumerate(header_row) if name is not None}

            required = [
                "Karteikarte", "Jahr", "Datum Taufe", "Datum Geburt", "Seite", "Nummer",
                "Karteikartentext", "Vorname Täufling", "Klarname", "Vorname Vater",
                "Geschlecht Täufling", "Kirchenbucheintrag"
            ]
            missing = [name for name in required if name not in headers]
            if missing:
                messagebox.showerror(
                    "Fehlende Spalten",
                    "In der XLSX-Datei fehlen folgende Spalten:\n" + "\n".join(missing)
                )
                return

            cursor = self.db.conn.cursor()
            cursor.execute(
                "SELECT id, dateiname FROM karteikarten WHERE dateiname IS NOT NULL AND dateiname <> ''"
            )
            key_to_ids = {}
            for record_id, name in cursor.fetchall():
                for key in build_match_keys(name):
                    key_to_ids.setdefault(key, []).append(record_id)

            updated = 0
            not_found = 0
            errors = 0

            total_rows = max(ws.max_row - 1, 0)
            self.db_progress['maximum'] = total_rows
            self.db_progress['value'] = 0

            created_at = "2026-01-16 00:00:00"
            for row_index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=1):
                self.db_progress['value'] = row_index
                self.root.update_idletasks()
                try:
                    dateiname = normalize_text(row[headers["Karteikarte"]])
                    if not dateiname:
                        continue

                    row_keys = build_match_keys(dateiname)
                    matched_ids = []
                    for key in row_keys:
                        if key in key_to_ids:
                            matched_ids.extend(key_to_ids[key])
                    matched_ids = list(dict.fromkeys(matched_ids))

                    if not matched_ids:
                        not_found += 1
                        continue

                    jahr = normalize_year(row[headers["Jahr"]])
                    datum_taufe = normalize_date(row[headers["Datum Taufe"]], wb.epoch)
                    datum_geburt = normalize_date(row[headers["Datum Geburt"]], wb.epoch)
                    datum = datum_taufe or datum_geburt
                    iso_datum = iso_from_datum(datum)
                    seite = normalize_number(row[headers["Seite"]])
                    nummer = normalize_number(row[headers["Nummer"]])
                    erkannter_text = normalize_text(row[headers["Karteikartentext"]])
                    vorname = normalize_text(row[headers["Vorname Täufling"]])
                    nachname = normalize_text(row[headers["Klarname"]])
                    partner = normalize_text(row[headers["Vorname Vater"]])
                    stand = stand_from_gender(row[headers["Geschlecht Täufling"]])
                    kirchenbuchtext = normalize_text(row[headers["Kirchenbucheintrag"]])

                    for record_id in matched_ids:
                        cursor.execute(
                            """
                            UPDATE karteikarten
                            SET kirchengemeinde = ?,
                                ereignis_typ = ?,
                                jahr = ?,
                                datum = ?,
                                seite = ?,
                                nummer = ?,
                                erkannter_text = ?,
                                ocr_methode = ?,
                                erstellt_am = ?,
                                aktualisiert_am = CURRENT_TIMESTAMP,
                                iso_datum = ?,
                                vorname = ?,
                                nachname = ?,
                                partner = ?,
                                todestag = ?,
                                ort = ?,
                                stand = ?,
                                kirchenbuchtext = ?,
                                geb_jahr_gesch = ?
                            WHERE id = ?
                            """,
                            (
                                "ev. Kb. Wetzlar",
                                "Taufe",
                                jahr,
                                datum,
                                seite,
                                nummer,
                                erkannter_text,
                                "Import",
                                created_at,
                                iso_datum,
                                vorname,
                                nachname,
                                partner,
                                datum,
                                "Wetzlar",
                                stand,
                                kirchenbuchtext,
                                jahr,
                                record_id
                            )
                        )
                    updated += len(matched_ids)
                except Exception:
                    errors += 1

            self.db.conn.commit()
            self._refresh_db_list()

            self.db_progress['value'] = 0
            messagebox.showinfo(
                "XLSX-Import abgeschlossen",
                f"✅ XLSX-Import abgeschlossen!\n\n"
                f"Aktualisiert: {updated}\n"
                f"Nicht gefunden (kein Match): {not_found}\n"
                f"Fehler: {errors}"
            )

        except Exception as e:
            self.db_progress['value'] = 0
            messagebox.showerror("Fehler", f"Fehler beim XLSX-Import:\n{str(e)}")
    
    def _load_image_files(self):
        """Lädt alle Bilddateien aus dem Verzeichnis."""
        if not self.base_path.exists():
            messagebox.showerror("Fehler", f"Pfad existiert nicht:\n{self.base_path}")
            return
        
        extensions = ['*.jpg', '*.jpeg', '*.png', '*.tif', '*.tiff']
        for ext in extensions:
            self.image_files.extend(self.base_path.glob(f"**/{ext}"))
        
        self.image_files.sort()
        
        if self.start_file:
            for idx, file in enumerate(self.image_files):
                if self.start_file in file.name:
                    self.current_index = idx
                    break
        
        print(f"Gefundene Karteikarten: {len(self.image_files)}")
    
    def _display_current_card(self):
        """Zeigt die aktuelle Karteikarte an."""
        if not self.image_files:
            return
        
        current_file = self.image_files[self.current_index]
        
        try:
            image = Image.open(current_file)
            
            display_width = 800
            aspect_ratio = image.height / image.width
            display_height = int(display_width * aspect_ratio)
            
            image_resized = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
            self.photo_image = ImageTk.PhotoImage(image_resized)
            
            self.image_label.configure(image=self.photo_image, text="")
            self.current_image = current_file
            
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Laden des Bildes:\n{str(e)}")
        
        self.filename_text.config(state=tk.NORMAL)
        self.filename_text.delete("1.0", tk.END)
        self.filename_text.insert("1.0", str(current_file))
        self.filename_text.config(state=tk.DISABLED)
        
        self.position_label.config(text=f"Karte {self.current_index + 1} von {len(self.image_files)}")
        
        self.prev_btn.config(state=tk.NORMAL if self.current_index > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if self.current_index < len(self.image_files) - 1 else tk.DISABLED)
        
        self._check_db_status()
    
    def _check_db_status(self):
        """Prüft ob die aktuelle Karteikarte bereits in der DB ist."""
        if not self.current_image:
            self.current_db_record_id = None
            self.db_record_status.config(text="")
            return
        
        dateipfad = str(self.current_image.absolute())
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id FROM karteikarten WHERE dateipfad = ?", (dateipfad,))
        row = cursor.fetchone()
        
        if row:
            self.current_db_record_id = row[0]
            self.db_record_status.config(
                text=f"✓ In Datenbank (ID: {row[0]})",
                foreground="green"
            )
            self.save_db_btn.config(text="💽 In DB aktualisieren")
        else:
            self.current_db_record_id = None
            self.db_record_status.config(text="○ Nicht gespeichert", foreground="orange")
            self.save_db_btn.config(text="💽 In DB speichern")
    
    def _next_card(self):
        """Zeigt die nächste Karteikarte."""
        if self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.current_db_record_id = None
            self._display_current_card()
    
    def _previous_card(self):
        """Zeigt die vorherige Karteikarte."""
        if self.current_index > 0:
            self.current_index -= 1
            self.current_db_record_id = None
            self._display_current_card()
    
    def _run_ocr(self):
        """Führt OCR auf der aktuellen Karte aus."""
        if not self.current_image:
            return
        
        current_method = self.ocr_method_var.get()
        if self.ocr_engine is None or current_method != self.ocr_method:
            self._change_ocr_method()
        
        if self.ocr_engine is None:
            messagebox.showerror("Fehler", "OCR Engine konnte nicht initialisiert werden.")
            return
        
        self.text_display.delete("1.0", tk.END)
        self.text_display.insert("1.0", "Texterkennung läuft...\nBitte warten...")
        self.root.update()
        
        use_preprocessing = self.preprocess_var.get()
        use_postprocessing = self.postprocess_var.get()
        
        print(f"[GUI] OCR starten - Preprocessing: {use_preprocessing}, Postprocessing: {use_postprocessing}")
        
        recognized_text = self.ocr_engine.recognize_text(
            self.current_image, 
            use_preprocessing=use_preprocessing,
            apply_postprocessing=use_postprocessing
        )
        
        self.text_display.delete("1.0", tk.END)
        self.text_display.insert("1.0", recognized_text)
    
    def _batch_scan(self):
        """Führt Batch-OCR auf mehreren Karten aus und speichert sie in der DB."""
        if not self.image_files:
            messagebox.showwarning("Warnung", "Keine Karteikarten geladen.")
            return
        
        try:
            count = int(self.batch_count_var.get())
            if count < 1:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Fehler", "Bitte geben Sie eine gültige Anzahl (>0) ein.")
            return
        
        current_method = self.ocr_method_var.get()
        if self.ocr_engine is None or current_method != self.ocr_method:
            self._change_ocr_method()
        
        if self.ocr_engine is None:
            messagebox.showerror("Fehler", "OCR Engine konnte nicht initialisiert werden.")
            return
        
        remaining = len(self.image_files) - self.current_index
        actual_count = min(count, remaining)
        
        start_file = self.image_files[self.current_index].name
        end_index = min(self.current_index + actual_count - 1, len(self.image_files) - 1)
        end_file = self.image_files[end_index].name
        
        # NEU: Filter-Information
        batch_type = self.batch_type_var.get()
        filter_info = f"\n\nBildtyp-Filter: {batch_type}"
        if batch_type != "Alle":
            filter_info += "\n(Nicht passende Bilder werden übersprungen)"
        
        antwort = messagebox.askyesno(
            "Batch-Scan bestätigen",
            f"Es werden bis zu {actual_count} Karteikarten gescannt und in die Datenbank gespeichert.\n\n"
            f"Start: Karte {self.current_index + 1}\n"
            f"       {start_file}\n\n"
            f"Ende: Karte {self.current_index + actual_count}\n"
            f"      {end_file}\n\n"
            f"OCR-Methode: {current_method}\n"
            f"Vorverarbeitung: {'Ja' if self.preprocess_var.get() else 'Nein'}\n"
            f"Text-Korrektur: {'Ja' if self.postprocess_var.get() else 'Nein'}"
            f"{filter_info}\n\n"
            f"Möchten Sie fortfahren?"
        )
        
        if not antwort:
            return
        
        # NEU: Abbruch-Flag
        self.batch_scan_cancelled = False
        
        # NEU: Abbrechen-Button hinzufügen
        self.cancel_batch_btn = ttk.Button(
            self.batch_btn.master,
            text="⏹ Abbrechen",
            command=self._cancel_batch_scan
        )
        self.cancel_batch_btn.pack(side=tk.LEFT, padx=2)
        
        # ESC-Taste zum Abbrechen
        def on_escape(event):
            self._cancel_batch_scan()
            return "break"
        self.root.bind('<Escape>', on_escape)
        
        self.batch_btn.config(state=tk.DISABLED)
        self.ocr_btn.config(state=tk.DISABLED)
        self.prev_btn.config(state=tk.DISABLED)
        self.next_btn.config(state=tk.DISABLED)
        
        use_preprocessing = self.preprocess_var.get()
        use_postprocessing = self.postprocess_var.get()
        
        print(f"[BATCH] Batch-Scan gestartet - Preprocessing: {use_preprocessing}, Postprocessing: {use_postprocessing}")
        
        erfolge = 0
        fehler = 0
        bereits_vorhanden = 0
        
        start_index = self.current_index
        
        for i in range(actual_count):
            # NEU: Abbruch prüfen
            if self.batch_scan_cancelled:
                break
            
            try:
                # NEU: Bildtyp-Filter anwenden
                current_filename = self.current_image.name if self.current_image else ""
                
                if batch_type != "Alle":
                    # Prüfe ob Bildtyp im Dateinamen vorkommt (z.B. "0364 Hb 1575")
                    if f" {batch_type} " not in current_filename:
                        # Überspringe dieses Bild und gehe weiter
                        if self.current_index < len(self.image_files) - 1:
                            self.current_index += 1
                            self.current_db_record_id = None
                            self._display_current_card()
                        continue
                
                # NEU: Fortschrittsanzeige mit Filter-Info
                self.text_display.delete("1.0", tk.END)
                self.text_display.insert(
                    "1.0",
                    f"⚡ Batch-Scan läuft...\n\n"
                    f"Filter: {batch_type}\n"
                    f"Fortschritt: {i + 1} / {actual_count}\n"
                    f"Erfolge: {erfolge}\n"
                    f"Bereits vorhanden: {bereits_vorhanden}\n"
                    f"Fehler: {fehler}\n\n"
                    f"Aktuell: {current_filename}\n\n"
                    f"⏹ ESC oder Button zum Abbrechen"
                )
                self.root.update()
                self._display_current_card()
                
                recognized_text = self.ocr_engine.recognize_text(
                    self.current_image,
                    use_preprocessing=use_preprocessing,
                    apply_postprocessing=use_postprocessing  # WICHTIG: Wird übergeben!
                )
                
                dateiname = self.current_image.name
                dateipfad = str(self.current_image.absolute())
                ocr_methode = self.ocr_method if self.ocr_engine else 'unbekannt'
                
                record_id = self.db.save_karteikarte(
                    dateiname=dateiname,
                    dateipfad=dateipfad,
                    erkannter_text=recognized_text,
                    ocr_methode=ocr_methode,
                    skip_if_exists=True  # NEU: Vorhandene Einträge nicht überschreiben
                )
                
                if record_id is None:
                    # Eintrag war bereits vorhanden und wurde übersprungen
                    bereits_vorhanden += 1
                else:
                    # Neuer Eintrag wurde erfolgreich gespeichert
                    erfolge += 1
                
                if self.current_index < len(self.image_files) - 1:
                    self.current_index += 1
                    self.current_db_record_id = None
                    self._display_current_card()
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei Karte {i + 1}: {str(e)}")
                if self.current_index < len(self.image_files) - 1:
                    self.current_index += 1
                    self.current_db_record_id = None
                    self._display_current_card()
        
        self.batch_btn.config(state=tk.NORMAL)
        self.ocr_btn.config(state=tk.NORMAL)
        self._check_db_status()
        
        # NEU: Abbrechen-Button entfernen
        self.cancel_batch_btn.destroy()
        
        # ESC-Binding entfernen
        self.root.unbind('<Escape>')
        
        self._refresh_db_list()
        
        # NEU: Abbruch-Info in Ergebnis
        abbruch_info = " (ABGEBROCHEN)" if self.batch_scan_cancelled else ""
        self.text_display.delete("1.0", tk.END)
        self.text_display.insert(
            "1.0",
            f"✅ Batch-Scan abgeschlossen{abbruch_info}!\n\n"
            f"Verarbeitet: {i + 1} von {actual_count} Karten\n"
            f"Erfolgreich gespeichert: {erfolge}\n"
            f"Bereits vorhanden: {bereits_vorhanden}\n"
            f"Fehler: {fehler}"
        )
        
        status_text = "abgebrochen" if self.batch_scan_cancelled else "erfolgreich abgeschlossen"
        messagebox.showinfo(
            f"Batch-Scan {status_text}",
            f"✅ Batch-Scan {status_text}!\n\n"
            f"Verarbeitet: {i + 1} von {actual_count} Karten\n"
            f"Erfolgreich gespeichert: {erfolge}\n"
            f"Bereits vorhanden: {bereits_vorhanden}\n"
            f"Fehler: {fehler}\n\n"
            f"Wechseln Sie zum Tab '📊 Datenbank' um die Einträge zu sehen."
        )
    
    # NEU: Funktion zum Abbrechen des Batch-Scans
    def _cancel_batch_scan(self):
        """Setzt Flag zum Abbrechen des Batch-Scans."""
        if messagebox.askyesno(
            "Batch-Scan abbrechen",
            "Möchten Sie den Batch-Scan wirklich abbrechen?\n\n"
            "Bereits verarbeitete Karten bleiben in der Datenbank."
        ):
            self.batch_scan_cancelled = True
    
    def _change_ocr_method(self):
        """Wechselt die OCR-Methode."""
        method = self.ocr_method_var.get()
        
        try:
            if method == 'cloud_vision':
                self.credentials_btn.config(state=tk.NORMAL)
                self.cloud_info_label.config(text="💡 Tipp: 'gcloud auth application-default login' ausführen")
                
                self.ocr_engine = OCREngine(
                    ocr_method='cloud_vision',
                    preprocess=True,
                    credentials_path=self.credentials_path
                )
            else:
                self.credentials_btn.config(state=tk.DISABLED)
                self.cloud_info_label.config(text="")
                
                self.ocr_engine = OCREngine(
                    ocr_method=method,
                    preprocess=True
                )
            
            self.ocr_method = method
            print(f"OCR-Methode gewechselt zu: {method}")
            
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Initialisieren der OCR Engine:\n{str(e)}")
            self.ocr_engine = None
    
    def _select_credentials(self):
       
        """Öffnet Dialog zur Auswahl der Google Cloud Credentials."""
        filepath = filedialog.askopenfilename(
            title="Google Cloud Credentials auswählen",
            filetypes=[("JSON-Dateien", "*.json"), ("Alle Dateien", "*.*")],
            initialdir=Path.cwd()
        )
        
        if filepath:
            self.credentials_path = filepath
            messagebox.showinfo("Erfolg", f"Credentials gesetzt:\n{filepath}\n\nSie können jetzt Cloud Vision verwenden.")
    
    def _save_text(self):
        """Speichert den erkannten Text in eine Datei."""
        text = self.text_display.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Warnung", "Kein Text zum Speichern vorhanden.")
            return
        
        default_name = self.current_image.stem + "_text.txt" if self.current_image else "karteikarte_text.txt"
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")]
        )
        
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(text)
                messagebox.showinfo("Erfolg", f"Text gespeichert in:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Fehler", f"Fehler beim Speichern:\n{str(e)}")
    
    def _reprocess_selected_texts(self):
        """Wendet Post-Processing auf ausgewählte DB-Einträge an."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return
        
        count = len(selection)
        
        if not messagebox.askyesno(
            "Text-Korrektur anwenden",
            f"Möchten Sie die Text-Korrektur auf {count} ausgewählte Einträge anwenden?\n\n"
            f"Die Texte werden mit den aktuellen Korrektur-Regeln neu verarbeitet.\n"
            f"Die alten Texte werden überschrieben."
        ):
            return
        
        from .text_postprocessor import TextPostProcessor
        processor = TextPostProcessor()
        
        # Progressbar initialisieren
        self.db_progress['maximum'] = count
        self.db_progress['value'] = 0
        
        erfolge = 0
        fehler = 0
        
        cursor = self.db.conn.cursor()
        
        for idx, item in enumerate(selection):
            # Progressbar aktualisieren
            self.db_progress['value'] = idx
            self.root.update_idletasks()
            
            record_id = self.tree.item(item)['values'][0]
            
            try:
                # Lade aktuellen Text
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # Wende Post-Processing an
                    corrected_text = processor.process(original_text, aggressive=False)
                    
                    # Speichere zurück
                    self.db.save_karteikarte(
                        dateiname=dateiname,
                        dateipfad=dateipfad,
                        erkannter_text=corrected_text,
                        ocr_methode="reprocessed"
                    )
                    
                    erfolge += 1
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        # Progressbar zurücksetzen
        self.db_progress['value'] = 0
        
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Fertig",
            f"Text-Korrektur abgeschlossen!\n\n"
            f"Erfolgreich: {erfolge}\n"
            f"Fehler: {fehler}"
        )
    
    def _reprocess_all_texts(self):
        """Wendet Post-Processing auf ALLE DB-Einträge an."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM karteikarten")
        total = cursor.fetchone()[0]
        
        if total == 0:
            messagebox.showinfo("Info", "Keine Einträge in der Datenbank.")
            return
        
        if not messagebox.askyesno(
            "Text-Korrektur anwenden (ALLE)",
            f"⚠️ ACHTUNG: Diese Aktion verarbeitet ALLE {total} Einträge in der Datenbank!\n\n"
            f"Alle Texte werden mit den aktuellen Korrektur-Regeln neu verarbeitet.\n"
            f"Die alten Texte werden überschrieben.\n\n"
            f"Dies kann einige Minuten dauern.\n\n"
            f"Möchten Sie fortfahren?",
            icon='warning'
        ):
            return
        
        from .text_postprocessor import TextPostProcessor
        processor = TextPostProcessor()
        
        erfolge = 0
        fehler = 0
        
        cursor.execute("SELECT id, erkannter_text, dateiname, dateipfad FROM karteikarten")
        rows = cursor.fetchall()
        
        for i, row in enumerate(rows, 1):
            record_id = row[0]
            original_text = row[1]
            dateiname = row[2]
            dateipfad = row[3]
            
            try:
                # Wende Post-Processing an
                corrected_text = processor.process(original_text, aggressive=False)
                
                # Speichere zurück
                self.db.save_karteikarte(
                    dateiname=dateiname,
                    dateipfad=dateipfad,
                    erkannter_text=corrected_text,
                    ocr_methode="reprocessed"
                )
                
                erfolge += 1
                
                # Fortschritt anzeigen (alle 10 Einträge)
                if i % 10 == 0:
                    self.db_status_label.config(text=f"Verarbeite {i}/{total}...")
                    self.root.update()
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list();
        
        messagebox.showinfo(
            "Fertig",
            f"Text-Korrektur für alle Einträge abgeschlossen!\n\n"
            f"Verarbeitet: {total}\n"
            f"Erfolgreich: {erfolge}\n"
            f"Fehler: {fehler}"
        )
    
    def _fix_wetzlar_infinity_selected(self):
        """Wendet NUR die Wetzlar 00 → ∞ Korrektur auf ausgewählte DB-Einträge an."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return
        
        count = len(selection)
        
        if not messagebox.askyesno(
            "Wetzlar ∞-Korrektur",
            f"Möchten Sie die 'Wetzlar 00 → ∞' Korrektur auf {count} Einträge anwenden?\n\n"
            f"Beispiel:\n"
            f"  'ev. Kb. Wetzlar 00' → 'ev. Kb. Wetzlar ∞'\n"
            f"  'Witzlar. 00161' → 'Wetzlar ∞ 1561'\n"
            f"  'Witalar: 0016/7,14,17' → 'Wetzlar ∞ 1617.14.17'\n\n"
            f"Die alten Texte werden überschrieben."
        ):
            return
        
        import re
        
        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        
        cursor = self.db.conn.cursor()
        
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            
            try:
                # Lade aktuellen Text
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # KORREKTUR 1a: Wetzlar/Witzlar/Witalar 0016/7,14,17 → Wetzlar ∞ 1617.14.17
                    # Matcht Varianten + optionale Punkte/Doppelte Punkte + "00" + 2-4 Ziffern + Trennzeichen
                    corrected_text = re.sub(
                        r'\b(Wetz|Wet|Web|Wef|Witz|Wit)[a-z]{2,5}[.,:\s]*00(1[0-9])[/,.]',
                        r'Wetzlar ∞ 16\2.',
                        original_text,
                        flags=re.IGNORECASE
                    )
                    
                    # KORREKTUR 1b: Wetzlar/Witzlar/Witalar 00XX → Wetzlar ∞ 16XX (für 1600-1699)
                    # Matcht alle Varianten + opt. Punkte/Doppelte Punkte + "00" + 2 Ziffern + Trennzeichen
                    corrected_text = re.sub(
                        r'\b(Wetz|Wet|Web|Wef|Witz|Wit)[a-z]{2,5}[.,:\s]*00(\d{2})[/,.]',
                        r'Wetzlar ∞ 16\2.',
                        corrected_text,
                        flags=re.IGNORECASE
                    )
                    
                    # KORREKTUR 1c: Wetzlar/Witzlar/Witalar 00 + weitere Ziffern (ohne Trennzeichen)
                    # z.B. "Witalar 00564" → "Wetzlar ∞ 1564"
                    corrected_text = re.sub(
                        r'\b(Wetz|Wet|Web|Wef|Witz|Wit)[a-z]{2,5}[.,:\s]*00(\d{3,4})\b',
                        r'Wetzlar ∞ 1\2',
                        corrected_text,
                        flags=re.IGNORECASE
                    )
                    
                    # KORREKTUR 2: Wetzlar/Witzlar/Witalar 00 (ohne Datum danach)
                    # Matcht alle Varianten + opt. Punkte/Doppelte Punkte + "00" + Wortgrenze
                    corrected_text = re.sub(
                        r'\b(Wetz|Wet|Web|Wef|Witz|Wit)[a-z]{2,5}[.,:\s]*00\b',
                        'Wetzlar ∞',
                        corrected_text,
                        flags=re.IGNORECASE
                    )
                    
                    # Prüfe ob Änderung stattgefunden hat
                    if corrected_text == original_text:
                        keine_aenderung += 1
                    else:
                        # Speichere zurück
                        self.db.save_karteikarte(
                            dateiname=dateiname,
                            dateipfad=dateipfad,
                            erkannter_text=corrected_text,
                            ocr_methode="wetzlar_infinity_fix"
                        )
                        erfolge += 1
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Fertig",
            f"Wetzlar ∞-Korrektur abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )
    
    
    def _insert_burial_symbol_selected(self):
        """Fügt Begräbniszeichen ⚰ nach 'ev. Kb. Wetzlar' ein, wenn danach direkt eine Ziffer folgt."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return
        
        count = len(selection)
        
        if not messagebox.askyesno(
            "Begräbniszeichen einfügen",
            f"Möchten Sie das Begräbniszeichen ⚰ in {count} Einträge einfügen?\n\n"
            f"Wenn nach 'ev. Kb. Wetzlar' direkt eine Ziffer folgt (nur Leerzeichen dazwischen):\n"
            f"  - Wird '⚰' vor der Ziffer eingefügt\n\n"
            f"Beispiel:\n"
            f"  'ev. Kb. Wetzlar 1674...' → 'ev. Kb. Wetzlar ⚰ 1674...'\n"
            f"  'ev. Kb. Wetzlar  1675' → 'ev. Kb. Wetzlar ⚰ 1675'\n\n"
            f"Die alten Texte werden überschrieben."
        ):
            return
        
        import re
        
        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        
        cursor = self.db.conn.cursor()
        
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            
            try:
                # Lade aktuellen Text
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # Prüfe ob Text mit "ev. Kb. Wetzlar" beginnt, gefolgt von Leerzeichen und Ziffer
                    # Muster: "ev. Kb. Wetzlar" + Leerzeichen + Ziffer (kein Symbol dazwischen)
                    match = re.match(r'^(ev\. Kb\. Wetzlar)\s+(\d)', original_text)
                    
                    if match:
                        # Ersetze: Füge ⚰ zwischen "ev. Kb. Wetzlar" und der Ziffer ein
                        corrected_text = re.sub(
                            r'^(ev\. Kb\. Wetzlar)\s+(\d)',
                            r'\1 ⚰ \2',
                            original_text
                        )
                        
                        if corrected_text != original_text:
                            # Speichere zurück
                            self.db.save_karteikarte(
                                dateiname=dateiname,
                                dateipfad=dateipfad,
                                erkannter_text=corrected_text,
                                ocr_methode="burial_symbol_inserted"
                            )
                            erfolge += 1
                        else:
                            keine_aenderung += 1
                    else:
                        # Kein Match - entweder beginnt nicht mit "ev. Kb. Wetzlar" oder hat bereits ein Symbol
                        keine_aenderung += 1
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Fertig",
            f"Begräbniszeichen-Einfügung abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )

    def _insert_marriage_symbol_selected(self):
        """Fügt Begräbniszeichen ∞ nach 'ev. Kb. Wetzlar' ein, wenn danach direkt eine Ziffer folgt."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return
        
        count = len(selection)
        
        if not messagebox.askyesno(
            "Hochzeitszeichen einfügen",
            f"Möchten Sie das Hochzeitszeichen ∞ in {count} Einträge einfügen?\n\n"
            f"Wenn nach 'ev. Kb. Wetzlar' direkt eine Ziffer folgt (nur Leerzeichen dazwischen):\n"
            f"  - Wird '∞' vor der Ziffer eingefügt\n\n"
            f"Beispiel:\n"
            f"  'ev. Kb. Wetzlar 1674...' → 'ev. Kb. Wetzlar ∞ 1674...'\n"
            f"  'ev. Kb. Wetzlar  1675' → 'ev. Kb. Wetzlar ∞ 1675'\n\n"
            f"Die alten Texte werden überschrieben."
        ):
            return
        
        import re
        
        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        
        cursor = self.db.conn.cursor()
        
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            
            try:
                # Lade aktuellen Text
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # Prüfe ob Text mit "ev. Kb. Wetzlar" beginnt, gefolgt von Leerzeichen und Ziffer
                    # Muster: "ev. Kb. Wetzlar" + Leerzeichen + Ziffer (kein Symbol dazwischen)
                    match = re.match(r'^(ev\. Kb\. Wetzlar)\s+(\d)', original_text)
                    
                    if match:
                        # Ersetze: Füge ⚰ zwischen "ev. Kb. Wetzlar" und der Ziffer ein
                        corrected_text = re.sub(
                            r'^(ev\. Kb\. Wetzlar)\s+(\d)',
                            r'\1 ∞ \2',
                            original_text
                        )
                        
                        if corrected_text != original_text:
                            # Speichere zurück
                            self.db.save_karteikarte(
                                dateiname=dateiname,
                                dateipfad=dateipfad,
                                erkannter_text=corrected_text,
                                ocr_methode="burial_symbol_inserted"
                            )
                            erfolge += 1
                        else:
                            keine_aenderung += 1
                    else:
                        # Kein Match - entweder beginnt nicht mit "ev. Kb. Wetzlar" oder hat bereits ein Symbol
                        keine_aenderung += 1
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Fertig",
            f"Begräbniszeichen-Einfügung abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )


    def _replace_ev_kb_wetzlar_special_selected(self):
        """Ersetzt in den markierten Datensätzen in der Spalte 'Erkannter Text' den Text 'ev. Kb. Wetzlar. □ 1' durch 'ev. Kb. Wetzlar. (Beerdigungszeichen= Sarg) 1'."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return

        count = len(selection)
        if not messagebox.askyesno(
            "ev. Kb. Wetzlar. □ 1 ersetzen",
            f"Möchten Sie die Ersetzung auf {count} Einträge anwenden?\n\n"
            f"Alle Vorkommen von 'ev. Kb. Wetzlar. □ 1' werden durch 'ev. Kb. Wetzlar. (Beerdigungszeichen= Sarg) 1' ersetzt.\n"
            f"Die alten Texte werden überschrieben."
        ):
            return

        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        cursor = self.db.conn.cursor()
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            try:
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    if "ev. Kb. Wetzlar. □ 1" not in original_text:
                        keine_aenderung += 1
                        continue
                    new_text = original_text.replace(
                        "ev. Kb. Wetzlar. □ 1",
                        "ev. Kb. Wetzlar. (Beerdigungszeichen= Sarg) 1"
                    )
                    self.db.save_karteikarte(
                        dateiname=dateiname,
                        dateipfad=dateipfad,
                        erkannter_text=new_text,
                        ocr_methode="ev_kb_wetzlar_special_replace"
                    )
                    erfolge += 1
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        self._refresh_db_list()
        messagebox.showinfo(
            "Fertig",
            f"Ersetzung abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )
    
    def _replace_ev_kb_wetzlar_special_selected(self):
        """Ersetzt in den markierten Datensätzen in der Spalte 'Erkannter Text' den Text 'ev. Kb. Wetzlar. □ 1' durch 'ev. Kb. Wetzlar. ⚰ 1'."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie mindestens einen Eintrag aus der Liste aus.")
            return
        import re
        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        cursor = self.db.conn.cursor()
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            try:
                # Lade aktuellen Text und weitere Felder
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    new_text = original_text.replace(
                        "ev. Kb. Wetzlar. □ 1",
                        "ev. Kb. Wetzlar ⚰ 1"
                    )
                    if new_text == original_text:
                        keine_aenderung += 1
                        continue
                    # Speichere zurück
                    self.db.save_karteikarte(
                        dateiname=dateiname,
                        dateipfad=dateipfad,
                        erkannter_text=new_text,
                        ocr_methode="ev_kb_wetzlar_special_fix"
                    )
                    erfolge += 1
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        self._refresh_db_list()
        messagebox.showinfo(
            "Fertig",
            f"ev. Kb. Wetzlar. □ 1 → ⚰ 1 abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )
    
    
    def _fix_header_prefix_selected(self):
        """Korrigiert den Anfang des Textes zu 'ev. Kb. Wetzlar' für ausgewählte Einträge."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return
        
        count = len(selection)
        
        if not messagebox.askyesno(
            "ev. Kb. Wetzlar Korrektur",
            f"Möchten Sie die 'ev. Kb. Wetzlar' Korrektur auf {count} Einträge anwenden?\n\n"
            f"Wenn der Text nicht mit 'ev. Kb. Wetzlar' beginnt:\n"
            f"  - Alles bis zur ersten Ziffer wird gelöscht\n"
            f"  - Wird ersetzt durch 'ev. Kb. Wetzlar '\n\n"
            f"Beispiel:\n"
            f"  'brinii ev. Kb. Wetzlar ∞ 1574...' → 'ev. Kb. Wetzlar ∞ 1574...'\n"
            f"  'r. Kb. Wetzlar 1574...' → 'ev. Kb. Wetzlar 1574...'\n\n"
            f"Die alten Texte werden überschrieben."
        ):
            return
        
        import re
        
        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        
        cursor = self.db.conn.cursor()
        
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            
            try:
                # Lade aktuellen Text
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # Prüfe ob Text bereits korrekt beginnt
                    if original_text.strip().startswith('ev. Kb. Wetzlar'):
                        keine_aenderung += 1
                        continue
                    
                    # Finde erste Ziffer im Text
                    match = re.search(r'\d', original_text)
                    
                    if match:
                        # Position der ersten Ziffer
                        first_digit_pos = match.start()
                        
                        # Extrahiere Text ab erster Ziffer
                        rest_text = original_text[first_digit_pos:]
                        
                        # Erstelle neuen Text
                        corrected_text = f"ev. Kb. Wetzlar {rest_text}"
                        
                        # Speichere zurück
                        self.db.save_karteikarte(
                            dateiname=dateiname,
                            dateipfad=dateipfad,
                            erkannter_text=corrected_text,
                            ocr_methode="header_prefix_fix"
                        )
                        erfolge += 1
                    else:
                        # Keine Ziffer gefunden - überspringe
                        keine_aenderung += 1
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Fertig",
            f"ev. Kb. Wetzlar Korrektur abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )
    
    def _fix_infinity_year_selected(self):
        """Korrigiert '∞16.1' → '∞161' Muster in ausgewählten DB-Einträgen."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warnung", "Bitte wählen Sie mindestens einen Eintrag aus.")
            return
        
        count = len(selection)
        
        if not messagebox.askyesno(
            "Jahr-Korrektur nach ∞",
            f"Möchten Sie die Jahr-Korrektur auf {count} Einträge anwenden?\n\n"
            f"Beispiel:\n"
            f"  'Wetzlar ∞16.1' → 'Wetzlar ∞161'\n"
            f"  '∞16.11.07.28' → '∞ 1611.07.28'\n\n"
            f"Die alten Texte werden überschrieben."
        ):
            return
        
        import re
        
        erfolge = 0
        fehler = 0
        keine_aenderung = 0
        
        cursor = self.db.conn.cursor()
        
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            
            try:
                # Lade aktuellen Text
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                
                if row:
                    original_text = row[0]
                    dateiname = row[1]
                    dateipfad = row[2]
                    
                    # KORREKTUR 1: ∞16.XX.XX.XX → ∞ 16XX.XX.XX
                    # Beispiel: "∞16.11.07.28" → "∞ 1611.07.28"
                    corrected_text = re.sub(
                        r'∞(\d{2})\.(\d{2})\.(\d{2})\.(\d{2})',
                        r'∞ 16\1.\2.\3',
                        original_text
                    )
                    
                    # KORREKTUR 2: ∞16.X (einzelne Ziffer nach Punkt)
                    # Beispiel: "∞16.1" → "∞161" oder "∞16.5" → "∞165"
                    corrected_text = re.sub(
                        r'∞16\.(\d)\b',
                        r'∞161\1',
                        corrected_text
                    )
                    
                    # KORREKTUR 3: ∞16.XX (zwei Ziffern nach Punkt)
                    # Beispiel: "∞16.11" → "∞1611"
                    corrected_text = re.sub(
                        r'∞16\.(\d{2})\b',
                        r'∞16\1',
                        corrected_text
                    )
                    
                    # Prüfe ob Änderung stattgefunden hat
                    if corrected_text == original_text:
                        keine_aenderung += 1
                    else:
                        # Speichere zurück
                        self.db.save_karteikarte(
                            dateiname=dateiname,
                            dateipfad=dateipfad,
                            erkannter_text=corrected_text,
                            ocr_methode="infinity_year_fix"
                        )
                        erfolge += 1
                
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {str(e)}")
        
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Fertig",
            f"Jahr-Korrektur nach ∞ abgeschlossen!\n\n"
            f"Erfolgreich geändert: {erfolge}\n"
            f"Keine Änderung nötig: {keine_aenderung}\n"
            f"Fehler: {fehler}"
        )
    
    def _abgleich_families_ok(self):
        """Gleicht Einträge mit families_ok.tsv ab und setzt F-ID."""
        # Lade TSV-Datei
        tsv_path = Path("input/families_ok.tsv")
        if not tsv_path.exists():
            messagebox.showerror(
                "Fehler",
                f"Datei nicht gefunden: {tsv_path}\n\n"
                "Bitte stellen Sie sicher, dass die Datei im Ordner 'input' liegt."
            )
            return
        
        try:
            with open(tsv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                families = list(reader)
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Lesen der TSV-Datei:\n{e}")
            return
        
        if not families:
            messagebox.showwarning("Warnung", "Die TSV-Datei enthält keine Daten.")
            return
        
        # Durchlaufe alle DB-Einträge
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT id, iso_datum, dateiname, notiz
            FROM karteikarten
            WHERE ereignis_typ = 'Heirat'
        """)
        
        db_entries = cursor.fetchall()
        matched = 0
        total = 0
        skipped = 0
        
        for entry in db_entries:
            db_id = entry[0]
            db_iso_datum = (entry[1] or '').strip()
            db_dateiname = (entry[2] or '').strip()
            db_notiz = (entry[3] or '').strip()
            
            if not db_iso_datum or not db_dateiname:
                continue
            
            total += 1
            
            # Überspringe wenn bereits F-ID vorhanden
            if db_notiz:
                skipped += 1
                continue
            
            # Suche passende Familie
            for family in families:
                # Prüfe Bedingungen: citedatetr (ISO) und path (Dateiname)
                tsv_iso_datum = (family.get('citedatetr', '') or '').strip()
                tsv_path = (family.get('path', '') or '').strip()
                
                # Match wenn beide Bedingungen erfüllt
                if tsv_iso_datum == db_iso_datum and tsv_path == db_dateiname:
                    # Setze F-ID in notiz-Feld
                    fid = (family.get('Familien-Kennung', '') or '').strip()
                    if fid:
                        cursor.execute(
                            "UPDATE karteikarten SET notiz = ? WHERE id = ?",
                            (fid, db_id)
                        )
                        matched += 1
                        break
        
        self.db.conn.commit()
        self._refresh_db_list()
        
        messagebox.showinfo(
            "Abgleich abgeschlossen",
            f"Abgleich mit families_ok.tsv abgeschlossen!\n\n"
            f"Geprüfte Heiratseinträge: {total}\n"
            f"Zugeordnete F-IDs: {matched}\n"
            f"Übersprungen (bereits F-ID): {skipped}"
        )
    
    def _reset_autoincrement(self):
        """Setzt AUTOINCREMENT auf höchste ID zurück."""
        if not messagebox.askyesno(
            "AUTOINCREMENT zurücksetzen",
            "Möchten Sie den ID-Counter auf die höchste vorhandene ID zurücksetzen?\n\n"
            "Dies verhindert, dass neue Scans zu hohe IDs bekommen.\n\n"
            "Beispiel:\n"
            "  Höchste ID: 150 → Nächste ID wird 151\n"
            "  (statt z.B. 1051 wenn vorher viele gelöscht wurden)\n\n"
            "Dies ist nützlich nach dem Löschen vieler Datensätze.",
            icon='question'
        ):
            return
        
        try:
            max_id = self.db.reset_autoincrement()
            self._refresh_db_list()
            
            messagebox.showinfo(
                "Erfolg",
                f"✅ ID-Counter wurde zurückgesetzt!\n\n"
                f"Höchste vorhandene ID: {max_id}\n"
                f"Nächste neue ID wird: {max_id + 1}\n\n"
                f"Neue Scans erhalten jetzt fortlaufende IDs."
            )
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Zurücksetzen:\n{str(e)}")


def run_gui(base_path: str = r"E:\Karteikarten\nextcloud", start_file: str = "0008 Hb"):
    """
    Startet die GUI-Anwendung.
    
    Args:
        base_path: Basispfad zu den Karteikarten
        start_file: Startdatei-Pattern
    """
    root = tk.Tk()
    app = KarteikartenGUI(root, base_path, start_file)
    root.mainloop()
