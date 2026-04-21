"""
GEDCOM Exporter für Wetzlar Karteikarten.

Exportiert Karteikarten-Daten aus der Datenbank als GEDCOM-Datei
im GRAMPS-Dialekt mit korrekter Citation- und Media-Struktur.

Features:
- Hochzeiten: Bräutigam, Braut und ggf. Eltern
- Begräbnisse: Verstorbene Person mit Begräbnis-Ereignis
- Korrekte Citation-Struktur: 2 SOUR -> 3 DATA, 3 PAGE, 3 QUAY, 3 NOTE, 3 OBJE
- NOTE und OBJE als separate Datensätze am Ende
- Wittwer-Erkennung: Kein Vater-Eintrag, stattdessen Note bei der Hochzeit
- SEX-Tags für alle Personen
- Vollständige SOUR-Records mit Quellenmetadaten
- FAMS und FAMC-Tags für Familie-Beziehungen
"""

import re
import sqlite3
import sys
from datetime import datetime
from io import StringIO
from itertools import count
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .extraction_lists import MAENNLICHE_VORNAMEN, SOURCES, WEIBLICHE_VORNAMEN
from .sources_lib import SOURCE_NAME_TO_ID, SOURCES_DATA


class GedcomExporter:
    """Exportiert Karteikarten-Daten als GEDCOM-Datei (GRAMPS- oder TNG-Dialekt)."""
    
    def __init__(self, db_connection: sqlite3.Connection, dialect: str = 'GRAMPS'):
        """
        Initialisiert den GEDCOM-Exporter.
        
        Args:
            db_connection: Aktive SQLite-Datenbankverbindung
            dialect: 'GRAMPS' (Standard) oder 'TNG'
        """
        self.conn = db_connection
        self._dialect = dialect.upper()
        
        # ID-Generatoren
        self._person_id = count(1)
        self._family_id = count(1)
        self._source_id = count(1)
        self._note_id = count(1)
        self._obje_id = count(1)
        
        # Cache für Personen (key: (vorname, nachname, typ))
        self._person_cache: Dict[Tuple[str, str, str], str] = {}
        
        # Cache für Personengeschlecht (key: person_id -> 'M' or 'F')
        self._person_sex_cache: Dict[str, str] = {}
        
        # Cache für Personen-Familie-Zuordnungen (key: person_id -> list of family_ids als HUSB/WIFE)
        self._person_families: Dict[str, List[str]] = {}
        
        # Cache für Personen-Kind-Familie (key: person_id -> family_id als Kind)
        self._person_child_families: Dict[str, str] = {}
        
        # Cache für Quellen (key: source_name)
        self._source_cache: Dict[str, str] = {}
        
        # Cache für Obje (key: file_path)
        self._obje_cache: Dict[str, str] = {}
        
        # Sammlungen für Einträge am Ende
        self._notes: Dict[str, str] = {}  # note_id -> text
        self._objes: Dict[str, Tuple[str, str]] = {}  # obje_id -> (file_path, form)
        self._sources: Dict[str, str] = {}  # source_id -> source_name
        self._missing_source_warnings: Set[str] = set()  # deduplizierte Warnungen

        # Puffer für strikt geordnete Ausgabe (INDI vor FAM)
        self._pending_persons: Dict[str, Tuple[str, str]] = {}  # person_id -> (vorname, nachname)
        self._pending_person_events: Dict[str, List[str]] = {}  # person_id -> [event blocks]
        self._pending_family_records: List[Tuple[str, str]] = []  # [(family_id, fam block)]
        
        # Source-to-Media-Path Mapping
        self._source_to_media_path = {
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 Gb Hb Sb 1613-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831": "S1",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611": "Gb 1564-1611",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632": "Gb 1611-1632",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670": "Gb 1633-1670",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695": "Gb 1671-1695",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718": "Gb 1695-1718",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734": "Gb 1718-1734",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746": "Gb 1735-1746",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761": "Gb 1746-1761",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780": "Gb 1761-1780",
            "Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798": "Gb 1780-1798",
            "WETZLAR KbGb 1571-1613 lutherisch": "KbGb 1571-1613",
            "Wetzlar KbHb 1564-1590 lutherisch": "KbHb 1564-1590",
            "Wetzlar KbSb 1613-1693 lutherisch": "KbSb 1613-1693",
            "WETZLAR KbGb 1614-1687 lutherisch": "KbGb 1614-1687",
            "WETZLAR KbGb 1688-1744 lutherisch": "KbGb 1688-1744",
            "WETZLAR KbGb 1745-1810 lutherisch": "KbGb 1745-1810",
            "WETZLAR KbGb 1811-1820 lutherisch": "KbGb 1811-1820",
        }
    
    def _clean(self, value) -> str:
        """Bereinigt Werte für GEDCOM."""
        if value is None or value == '':
            return ''
        return str(value).strip()
    
    def _determine_sex_from_vorname(self, vorname: str) -> Optional[str]:
        """Bestimmt Geschlecht basierend auf dem Vornamen.
        
        Ignoriert Suffixe wie '(~)', '(*)' oder andere Klammerausdrücke.
        """
        if not vorname:
            return None

        # Nur den ersten Namensteil verwenden, Klammern/Sonderzeichen abschneiden
        # z.B. "Balthasar (~)" -> "balthasar", "Gertrud (~)" -> "gertrud"
        clean = re.sub(r'\s*[\(\[].*', '', vorname).strip()
        vorname_lower = clean.lower() if clean else vorname.lower().strip()

        # Prüfe gegen die Namenslisten aus extraction_lists
        if any(v.lower() == vorname_lower for v in MAENNLICHE_VORNAMEN):
            return 'M'

        if any(v.lower() == vorname_lower for v in WEIBLICHE_VORNAMEN):
            return 'F'

        # Fallback: Einfache Endungs-Heuristik
        if vorname_lower.endswith(('a', 'e', 'i', 'h', 'n')):
            return 'F'

        return None
    
    def _escape_gedcom_text(self, text: str) -> str:
        """Escaped spezielle Zeichen für GEDCOM."""
        if not text:
            return ""
        # Ersetze Zeilenumbrüche
        text = text.replace('\n', ' ').replace('\r', '')
        # Entferne mehrfache Leerzeichen
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _get_person_id(self, vorname: str, nachname: str, person_typ: str = "", sex: Optional[str] = None) -> Optional[str]:
        """
        Holt oder erstellt eine Person-ID.
        
        Verwendet Caching um Duplikate zu vermeiden.
        
        Args:
            vorname: Vorname der Person
            nachname: Nachname der Person
            person_typ: Typ (z.B. "Bräutigam", "Braut", "Vater")
            sex: Geschlecht ('M' oder 'F'), optional
        
        Returns:
            Person-ID im Format @I1@, @I2@, etc. oder None
        """
        key = (self._clean(vorname), self._clean(nachname), person_typ)
        
        # Leere Namen überspringen
        if not key[0] and not key[1]:
            return None
        
        if key not in self._person_cache:
            person_id = f"@I{next(self._person_id)}@"
            self._person_cache[key] = person_id
            # Speichere Geschlecht wenn angegeben
            if sex in ('M', 'F'):
                self._person_sex_cache[person_id] = sex
        
        return self._person_cache[key]
    
    def _get_family_id(self) -> str:
        """Erstellt eine neue Familien-ID."""
        return f"@F{next(self._family_id)}@"
    
    def _get_source_id(self, source_name: str) -> str:
        """Holt oder erstellt eine Quellen-ID."""
        if source_name not in self._source_cache:
            mapped = SOURCE_NAME_TO_ID.get(source_name)
            if mapped:
                source_id = f"@{mapped}@"
            else:
                # Fallback für unbekannte Quellen, kollisionsfrei außerhalb der definierten S-IDs.
                source_id = f"@S{1000 + next(self._source_id)}@"
            self._source_cache[source_name] = source_id
            self._sources[source_id] = source_name
        
        return self._source_cache[source_name]

    def _warn_missing_source(self, name_hint: str):
        """Gibt eine deduplizierte Warnung für unbekannte Quellen aus."""
        hint = self._normalize_missing_source_hint(name_hint)
        if hint in self._missing_source_warnings:
            return
        self._missing_source_warnings.add(hint)
        print(f"Quelle nicht vorhanden [{hint}]", file=sys.stderr)

    def _normalize_missing_source_hint(self, name_hint: str) -> str:
        """Normalisiert Dateinamen zu gruppierten Quellen-Hinweisen."""
        cleaned = self._clean(name_hint)
        if not cleaned:
            return "unbekannt"

        match = re.search(r'(\d{4})-(\d{4})', cleaned)
        if match:
            start_year, end_year = match.groups()
            name_lower = cleaned.lower()
            typ = None
            if 'gb' in name_lower:
                typ = 'Gb'
            elif 'hb' in name_lower:
                typ = 'Hb'
            elif 'sb' in name_lower:
                typ = 'Sb'

            if typ:
                return f"{typ} {start_year}-{end_year}"

            return f"Jahresbereich {start_year}-{end_year}"

        name_lower = cleaned.lower()
        if 'geburt' in name_lower or 'taufe' in name_lower:
            return 'Geburten/Taufen (ohne Jahresbereich)'
        if 'heirat' in name_lower or 'trau' in name_lower:
            return 'Heiraten (ohne Jahresbereich)'
        if 'sterb' in name_lower or 'begrab' in name_lower:
            return 'Sterbefaelle/Begrabnisse (ohne Jahresbereich)'

        return cleaned
    
    def _get_note_id(self) -> str:
        """Erstellt eine neue Note-ID."""
        n = next(self._note_id)
        if self._dialect == 'TNG':
            return f"@N{n}@"
        return f"@N{n:06d}@"
    
    def _get_obje_id(self) -> str:
        """Erstellt eine neue OBJE-ID."""
        n = next(self._obje_id)
        if self._dialect == 'TNG':
            return f"@{200999 + n}@"  # TNG: @201000@, @201001@, ...
        return f"@O{n:06d}@"
    
    def _add_note(self, title: str, text: str) -> str:
        """
        Fügt eine Note hinzu und gibt die ID zurück.
        
        Args:
            title: Titel (z.B. "Abschrift Karteikarte")
            text: Note-Text
        
        Returns:
            Note-ID
        """
        note_id = self._get_note_id()
        escaped_text = self._escape_gedcom_text(text)
        # Vorhandene führende/abschließende Anführungszeichen aus der DB entfernen,
        # damit das später hinzugefügte Wrapper-Paar keine Dopplung erzeugt.
        escaped_text = escaped_text.strip('"')
        formatted_text = f"|{title}| \"{escaped_text}\""
        self._notes[note_id] = formatted_text
        
        return note_id
    
    def _add_obje(self, file_path: str) -> str:
        """
        Fügt ein Media-Objekt hinzu und gibt die ID zurück.
        
        Args:
            file_path: Vollständiger Pfad zur Datei
        
        Returns:
            OBJE-ID
        """
        if file_path in self._obje_cache:
            return self._obje_cache[file_path]
        
        obje_id = self._get_obje_id()
        form = "JPG"
        if file_path.lower().endswith('.png'):
            form = "PNG"
        elif file_path.lower().endswith('.tiff') or file_path.lower().endswith('.tif'):
            form = "TIFF"
        
        self._objes[obje_id] = (file_path, form)
        self._obje_cache[file_path] = obje_id
        
        return obje_id
    
    def _is_wittwer(self, name_text: str) -> bool:
        """Prüft ob der Name 'Wittwer' oder 'Witwe' enthält."""
        if not name_text:
            return False
        name_lower = name_text.lower()
        return 'wittwer' in name_lower or 'witwe' in name_lower
    
    def _detect_source_from_filename(self, dateiname: str) -> Optional[str]:
        """Ermittelt die Quelle aus dem Dateinamen."""
        if not dateiname:
            return None
        
        # Versuche zu matchen gegen Namensmuster
        for source_name in SOURCE_NAME_TO_ID.keys():
            if source_name in dateiname or dateiname in source_name:
                return source_name
        
        # Fallback: Versuche Jahresbereich zu extrahieren
        match = re.search(r'(\d{4})-(\d{4})', dateiname)
        if match:
            start_year = match.group(1)
            end_year = match.group(2)
            pattern = None
            
            # Versuche zu matchen gegen Dateityp und Jahresbereich
            if 'Gb' in dateiname or 'gb' in dateiname.lower():
                pattern = f"Gb {start_year}-{end_year}"
            elif 'Hb' in dateiname or 'hb' in dateiname.lower():
                pattern = f"Hb {start_year}-{end_year}"
            elif 'Sb' in dateiname or 'sb' in dateiname.lower():
                pattern = f"Sb {start_year}-{end_year}"

            if pattern:
                for source_name in SOURCE_NAME_TO_ID.keys():
                    if pattern in source_name:
                        return source_name
        
        return None

    def _extract_year_from_iso_date(self, iso_datum: str) -> Optional[int]:
        """Extrahiert ein plausibles Jahr aus ISO-Datum (YYYY-MM-DD)."""
        if not iso_datum:
            return None
        match = re.match(r"(\d{4})", self._clean(iso_datum))
        if not match:
            return None
        year = int(match.group(1))
        return year if year > 0 else None

    def _detect_source_from_year(self, year: int) -> Optional[str]:
        """Ermittelt die passendste Kirchenbuchkartei-Quelle anhand des Jahres.

        Bei mehreren Treffern wird der engste Jahresbereich gewählt (z.B. S5 statt S1).
        """
        candidates: List[Tuple[int, str]] = []  # (span, source_name)

        for source_name in SOURCE_NAME_TO_ID.keys():
            if "Kirchenbuchkartei" not in source_name:
                continue

            for match in re.finditer(r"(\d{4})-(\d{4})", source_name):
                start_year = int(match.group(1))
                end_year = int(match.group(2))
                if start_year <= year <= end_year:
                    candidates.append((end_year - start_year, source_name))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _resolve_source_name(self, dateiname: str, iso_datum: str) -> str:
        """Bestimmt den Quellnamen über Dateiname, danach über Jahr, sonst unbekannt."""
        source_name = self._detect_source_from_filename(dateiname)
        if source_name:
            return source_name

        year = self._extract_year_from_iso_date(iso_datum)
        if year is not None:
            source_name = self._detect_source_from_year(year)
            if source_name:
                return source_name

        self._warn_missing_source(dateiname)
        return "Wetzlar Kirchenbuchkartei (unbekannt)"
    
    def _find_kirchenbuch_source(self, ereignis_typ: str, jahr: int, seite: str) -> Optional[str]:
        """Findet die passende Kirchenbuch-Quelle basierend auf Typ, Jahr und Seite.
        
        Args:
            ereignis_typ: z.B. "Heirat", "Begräbnis", "Taufe"
            jahr: Jahr des Ereignisses
            seite: Seitennummer im Kirchenbuch
            
        Returns:
            Source-Name oder None wenn keine passende Quelle gefunden wurde
        """
        if not jahr or not seite:
            return None
        
        try:
            seite_int = int(seite)
        except (ValueError, TypeError):
            return None
        
        # Ermittle Typ-Kürzel für Kirchenbuch
        typ_kuerzel = None
        ereignis_lower = ereignis_typ.lower() if ereignis_typ else ""
        if "heirat" in ereignis_lower or "∞" in ereignis_lower:
            typ_kuerzel = "Hb"
        elif "begr" in ereignis_lower or "sterb" in ereignis_lower or "⚰" in ereignis_lower or "sb" in ereignis_lower:
            typ_kuerzel = "Sb"
        elif "tauf" in ereignis_lower or "geburt" in ereignis_lower or "gb" in ereignis_lower:
            typ_kuerzel = "Gb"
        
        if not typ_kuerzel:
            return None
        
        # Finde passende Quelle aus SOURCES
        passende_quellen = []
        for source in SOURCES:
            if source.get("media_type") != "kirchenbuchseiten":
                continue
            if not source.get("media_ID") or not source.get("source"):
                continue
            
            source_name = source["source"]
            
            # Prüfe ob Typ passt (z.B. "KbHb" für Heiraten)
            if f"Kb{typ_kuerzel}" not in source_name:
                continue
            
            # Extrahiere Jahresbereich aus source name
            jahr_match = re.search(r"(\d{4})-(\d{4})", source_name)
            if jahr_match:
                start_jahr = int(jahr_match.group(1))
                end_jahr = int(jahr_match.group(2))
                
                if start_jahr <= jahr <= end_jahr:
                    # Berechne Jahresspanne für Priorisierung
                    spanne = end_jahr - start_jahr
                    passende_quellen.append((spanne, source_name))
        
        if not passende_quellen:
            return None
        
        # Wähle die Quelle mit der kleinsten Spanne (genaueste Eingrenzung)
        passende_quellen.sort(key=lambda x: x[0])
        return passende_quellen[0][1]
    
    def _format_page_number(self, dateiname: str) -> str:
        """Formatiert die Seitennummer."""
        if not dateiname:
            return ""
        
        # Versuche erste 4-5 Ziffern zu extrahieren (Seitennummer)
        match = re.search(r'^(\d+)', dateiname)
        if match:
            page = match.group(1)
            return f"Nr. {page}"
        
        return ""

    def _format_second_page_info(self, seite: str, nummer: Optional[str], image_path: Optional[str]) -> str:
        """Erstellt den PAGE-Inhalt für die Kirchenbuch-Citation.
        
        Format: Seite X; Nr. Y; Bild <Dateinamen-Stamm>
        """
        parts = [f"Seite {seite}"]
        if nummer:
            parts.append(f"Nr. {nummer}")
        if image_path:
            parts.append(f"Bild {Path(image_path).stem}")
        return '; '.join(parts)
    
    def _extract_nummer_from_text(self, erkannter_text: str) -> Optional[str]:
        """Extrahiert die Nummer aus dem erkannten Text (z.B. 'Nr. 38')."""
        if not erkannter_text:
            return None
        
        # Suche nach "Nr. {zahl}" Pattern
        match = re.search(r'Nr\.?\s*(\d+)', erkannter_text, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    
    def _clean_note_text(self, erkannter_text: str) -> str:
        """Entfernt den Präfix aus dem erkannten Text für NOTE-Feld.
        
        Entfernt Teile wie: "ev. Kb. Wetzlar ⚰ 1694.07.22. p. 2 Nr. 5"
        So dass nur der eigentliche Text bleibt.
        """
        if not erkannter_text:
            return ""
        
        # Pattern: Starttext + Symbol + Datum + "p. X Nr. Y" + Rest
        # Beispiel: "ev. Kb. Wetzlar ⚰ 1694.07.22. p. 2 Nr. 5 Actual text here"
        # Regex erklärt:
        # ^.*? = alles am Anfang (non-greedy), z.B. "ev. Kb. Wetzlar ⚰"
        # \d{4}\.\d{1,2}\.\d{1,2}\. = Datum im Format YYYY.MM.DD.
        # p\.\s*\d+\s+Nr\.\s*\d+ = "p. X Nr. Y"
        # \s+ = mindestens ein Leerzeichen danach
        
        match = re.search(
            r'^.*?\d{4}\.\d{1,2}\.\d{1,2}\.?\s+p\.\s*\d+\s+Nr\.\s*[\d]+\.?\s+(.*)$',
            erkannter_text, re.DOTALL
        )
        if match:
            # Whitespace und Zeilenumbrüche im verbleibenden Text bereinigen
            cleaned = match.group(1).strip()
            cleaned = re.sub(r'[\r\n]+', ' ', cleaned)
            cleaned = re.sub(r'\s{2,}', ' ', cleaned)
            return cleaned

        # Kein Zitationsmuster gefunden: nur Whitespace bereinigen
        result = re.sub(r'[\r\n]+', ' ', erkannter_text)
        result = re.sub(r'\s{2,}', ' ', result)
        return result.strip()
    
    def _get_kirchenbuch_image_path(self, source_name: str, seite: str) -> Optional[str]:
        """Sucht den Bildpfad für ein Kirchenbuch mit robusten Wildcard-Patterns (wie GUI)."""
        if not source_name or not seite:
            return None
        
        # Finde die Source in SOURCES
        for source in SOURCES:
            if source.get("source") == source_name and source.get("media_type") == "kirchenbuchseiten":
                media_path = source.get("media_path")
                media_id = source.get("media_ID")
                
                if not media_path or not media_id:
                    continue
                
                try:
                    seite_int = int(seite)
                except (ValueError, TypeError):
                    return None
                
                ordner = Path(media_path)
                if not ordner.exists():
                    return None
                
                # Entferne die letzten 3 Zeichen vom media_ID (z.B. "_Sb", "_Hb", "_Gb")
                media_id_prefix = media_id[:-3]
                
                # Formate für 3- und 4-stellige Seitenzahlen
                seite_str_3 = f"{seite_int:03d}"
                seite_str_4 = f"{seite_int:04d}"
                
                # Liste der Suchpatterns (in dieser Reihenfolge wie in GUI)
                patterns = [
                    # 4-stellige Varianten
                    f"{media_id_prefix}* S_{seite_str_4}-*.jpg",
                    f"{media_id_prefix}* S_*-{seite_str_4}.jpg",
                    f"{media_id_prefix}*_{seite_str_4}.jpg",
                    f"{media_id_prefix}*_{seite_str_4} Sterbebuch.jpg",
                    # 3-stellige Varianten
                    f"{media_id_prefix}* S_{seite_str_3}-*.jpg",
                    f"{media_id_prefix}* S_*-{seite_str_3}.jpg",
                    f"{media_id_prefix}*_{seite_str_3}.jpg",
                ]
                
                # Teste alle Patterns und sammle Treffer
                treffer = []
                for pattern in patterns:
                    pattern_treffer = list(ordner.glob(pattern))
                    treffer.extend(pattern_treffer)
                
                # Duplikate entfernen
                treffer = list(set(treffer))
                
                if treffer:
                    # Gib das erste gefundene Bild zurück
                    return str(treffer[0])
        
        return None
    
    def _format_gedcom_date(self, datum: str) -> str:
        """Konvertiert ein Datum beliebigen Formats in gültiges GEDCOM-Format (D MON YYYY).

        Unterstützte Eingangsformate:
            YYYY-MM-DD  (ISO mit Bindestrich)
            DD.MM.YYYY  (deutsches Format mit Punkten)
            YYYY.MM.DD  (älteres ISO-Format mit Punkten)
        Platzhalterwert 00 für Tag oder Monat wird korrekt behandelt.
        """
        if not datum:
            return ""

        months = ["", "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

        try:
            datum = datum.strip()
            if '-' in datum:
                # YYYY-MM-DD
                parts = datum.split('-')
                if len(parts) != 3:
                    return ""
                jahr = parts[0].strip()
                monat = int(parts[1])
                tag = int(parts[2])
            elif '.' in datum:
                parts = [p.strip() for p in datum.split('.')]
                if len(parts) != 3:
                    return ""
                # Erkennung: erstes Teil 4-stellig und ≥ 1000 → YYYY.MM.DD
                if len(parts[0]) == 4 and parts[0].isdigit() and int(parts[0]) >= 1000:
                    jahr = parts[0]
                    monat = int(parts[1])
                    tag = int(parts[2])
                else:
                    # DD.MM.YYYY
                    tag = int(parts[0])
                    monat = int(parts[1])
                    jahr = parts[2]
            else:
                # Nur Jahreszahl?
                return datum if datum.isdigit() and len(datum) == 4 else ""

            if tag == 0 and monat == 0:
                return jahr
            if tag == 0:
                return f"{months[monat]} {jahr}" if 1 <= monat <= 12 else jahr
            if monat == 0:
                return f"{tag} {jahr}"
            if 1 <= monat <= 12:
                return f"{tag} {months[monat]} {jahr}"
            return f"{tag} {jahr}"

        except (ValueError, IndexError):
            return ""
    
    def _format_gedcom_date_with_before(self, iso_datum: str) -> str:
        """Konvertiert ISO-Datum zu GEDCOM-Format mit 'BEF' (BEFORE) Prefix."""
        base_date = self._format_gedcom_date(iso_datum)
        if base_date:
            return f"BEF {base_date}"
        return ""

    def _format_estimated_birth_year(self, birth_year) -> str:
        """Formatiert ein geschätztes Geburtsjahr als GEDCOM-Datum (ABT YYYY)."""
        year_text = self._clean(birth_year)
        if not year_text:
            return ""

        match = re.match(r"^(\d{4})$", year_text)
        if not match:
            return ""

        year = int(match.group(1))
        if year <= 0:
            return ""

        return f"ABT {year}"
    
    def _write_header(self, f):
        """Schreibt GEDCOM-Header."""
        now = datetime.now()
        date_str = now.strftime("%d %b %Y").upper()
        time_str = now.strftime("%H:%M:%S")
        
        f.write("0 HEAD\n")
        f.write("1 SOUR Wetzlar Karteikarten Erkennung\n")
        f.write(f"2 VERS 1.0\n")
        f.write(f"2 NAME Wetzlar Karteikarten Erkennung\n")
        dest = 'TNG' if self._dialect == 'TNG' else 'GRAMPS'
        f.write(f"1 DEST {dest}\n")
        f.write(f"1 DATE {date_str}\n")
        f.write(f"2 TIME {time_str}\n")
        f.write("1 GEDC\n")
        f.write("2 VERS 5.5.1\n")
        f.write("2 FORM LINEAGE-LINKED\n")
        f.write("1 CHAR UTF-8\n")
        f.write("0 @SUBM@ SUBM\n")
        f.write("1 NAME Karteikartenerkennung\n")
    
    def _write_inline_note(self, f, note_id: str, level: int = 2) -> None:
        """Schreibt Notiztext direkt inline als NOTE-Tag (TNG-Stil).
        
        Zeilenlänge: max 80 Zeichen Inhalt + 7 Zeichen Tag-Prefix = 87 gesamt.
        Längere Texte werden durch CONC-Zeilen aufgeteilt.
        """
        if not note_id or note_id not in self._notes:
            return
        text = self._notes[note_id]
        max_len = 80
        if len(text) <= max_len:
            f.write(f"{level} NOTE {text}\n")
        else:
            chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
            f.write(f"{level} NOTE {chunks[0]}\n")
            for chunk in chunks[1:]:
                f.write(f"{level + 1} CONC {chunk}\n")

    def _write_all_sources(self, f):
        """Schreibt alle verwendeten SOUR-Records."""
        for source_id in sorted(self._source_cache.values(), key=lambda x: int(x[2:-1]) if x[2:-1].isdigit() else 999):
            # source_id hat das Format @S1@, in SOURCES_DATA ist der Key S1
            source_key = source_id[1:-1]
            f.write(f"0 {source_id} SOUR\n")

            if source_key not in SOURCES_DATA:
                # Fallback für unbekannte/heuristisch erkannte Quellen.
                source_name = self._sources.get(source_id, "Wetzlar Kirchenbuchkartei (unbekannt)")
                f.write(f"1 TITL {source_name}\n")
                f.write(f"1 ABBR {source_name}\n")
                continue

            data = SOURCES_DATA[source_key]

            if 'titl' in data:
                f.write(f"1 TITL {data['titl']}\n")
            if 'abbr' in data:
                f.write(f"1 ABBR {data['abbr']}\n")
            if 'auth' in data:
                f.write(f"1 AUTH {data['auth']}\n")
            if 'publ' in data:
                f.write(f"1 PUBL {data['publ']}\n")
            if 'repo' in data:
                f.write(f"1 REPO @{data['repo']}@\n")
                if 'caln' in data:
                    f.write(f"2 CALN {data['caln']}\n")
            if 'text' in data:
                f.write(f"1 TEXT {data['text']}\n")
        
    def _write_notes_and_objes(self, f):
        """Schreibt alle gesammelten NOTE und OBJE Einträge am Ende."""
        # NOTE-Records: nur für GRAMPS (TNG schreibt Notizen inline)
        if self._dialect == 'GRAMPS':
            max_len = 80

            def _word_wrap(text: str, width: int):
                """Zerlegt Text in Segmente ≤ width Zeichen, bricht an Wortgrenzen um."""
                segments = []
                while len(text) > width:
                    cut = text.rfind(' ', 0, width)
                    if cut <= 0:
                        cut = width  # kein Leerzeichen gefunden → hart schneiden
                    segments.append(text[:cut])
                    text = text[cut:].lstrip(' ')
                if text:
                    segments.append(text)
                return segments

            for note_id in sorted(self._notes.keys()):
                note_text = self._notes[note_id]
                f.write(f"0 {note_id} NOTE")
                if len(note_text) > max_len:
                    segments = _word_wrap(note_text, max_len)
                    f.write(f" {segments[0]}\n")
                    for seg in segments[1:]:
                        f.write(f"1 CONC {seg}\n")
                else:
                    f.write(f" {note_text}\n")
    
        # OBJE-Records: für beide Dialekte
        for obje_id in sorted(self._objes.keys()):
            file_path, form = self._objes[obje_id]
            f.write(f"0 {obje_id} OBJE\n")
            f.write(f"1 FORM {form}\n")
            f.write(f"1 FILE {file_path}\n")
    
    def _write_person(self, f, person_id: Optional[str], vorname: str, nachname: str):
        """Schreibt eine GEDCOM-Person."""
        if not person_id:
            return
        
        f.write(f"0 {person_id} INDI\n")
        
        vorname_clean = self._clean(vorname)
        nachname_clean = self._clean(nachname)
        # TNG-Dialekt: Nachname immer groß
        surn_display = nachname_clean.upper() if self._dialect == 'TNG' and nachname_clean else nachname_clean
        
        if vorname_clean or nachname_clean:
            f.write(f"1 NAME {vorname_clean} /{surn_display}/\n")
            if vorname_clean:
                f.write(f"2 GIVN {vorname_clean}\n")
            if surn_display:
                f.write(f"2 SURN {surn_display}\n")
        
        # Schreibe Geschlecht wenn gespeichert
        if person_id in self._person_sex_cache:
            sex = self._person_sex_cache[person_id]
            f.write(f"1 SEX {sex}\n")
        
        # Schreibe Familie-Zuordnungen (als Kind)
        if person_id in self._person_child_families:
            family_id = self._person_child_families[person_id]
            f.write(f"1 FAMC {family_id}\n")
        
        # Schreibe Familie-Zuordnungen (als Ehemann/Ehefrau)
        if person_id in self._person_families:
            for family_id in self._person_families[person_id]:
                f.write(f"1 FAMS {family_id}\n")

    def _register_person(self, person_id: Optional[str], vorname: str, nachname: str):
        """Merkt sich Personendaten für die spätere INDI-Ausgabe."""
        if not person_id:
            return
        if person_id not in self._pending_persons:
            self._pending_persons[person_id] = (vorname, nachname)

    def _add_person_event(self, person_id: Optional[str], event_block: str):
        """Hängt einen Event-Block an eine Person für spätere INDI-Ausgabe an."""
        if not person_id or not event_block:
            return
        self._pending_person_events.setdefault(person_id, []).append(event_block)

    def _person_has_event(self, person_id: Optional[str], event_tag: str) -> bool:
        """Prüft, ob ein Event-Tag (z.B. BIRT, BURI) bereits für die Person existiert."""
        if not person_id or not event_tag:
            return False

        event_prefix = f"1 {event_tag}\n"
        return any(event.startswith(event_prefix) for event in self._pending_person_events.get(person_id, []))

    def _add_family_record(self, family_id: str, family_block: str):
        """Merkt sich einen FAM-Block für spätere Ausgabe."""
        self._pending_family_records.append((family_id, family_block))

    def _write_all_individuals(self, f):
        """Schreibt alle INDI-Blöcke (inkl. personbezogener Events) sortiert."""
        for person_id, (vorname, nachname) in sorted(
            self._pending_persons.items(),
            key=lambda item: int(item[0][2:-1]) if item[0][2:-1].isdigit() else 0,
        ):
            self._write_person(f, person_id, vorname, nachname)
            for event_block in self._pending_person_events.get(person_id, []):
                f.write(event_block)

    def _write_all_families(self, f):
        """Schreibt alle FAM-Blöcke sortiert."""
        for _, family_block in sorted(
            self._pending_family_records,
            key=lambda item: int(item[0][2:-1]) if item[0][2:-1].isdigit() else 0,
        ):
            f.write(family_block)
    
    def _write_marriage_event(self, f, date: str, place: str, 
                             source_id: str, note_id: Optional[str], obje_ids: List[str], 
                             page_info: str, citation_note: str,
                             second_source_id: Optional[str] = None, second_page_info: Optional[str] = None,
                             second_note_id: Optional[str] = None, second_obje_ids: Optional[List[str]] = None):
        """Schreibt Heirats-Event mit vollständiger Citation (inkl. optionaler zweiter Quelle)."""
        f.write("1 MARR\n")
        
        gedcom_date = self._format_gedcom_date(date) if date else ""
        if gedcom_date:
            f.write(f"2 DATE {gedcom_date}\n")
        
        if place:
            f.write(f"2 PLAC {self._clean(place)}\n")
        
        # Erste Citation mit SOURCE (Karteikarte)
        if self._dialect == 'TNG' and note_id:
            self._write_inline_note(f, note_id, level=2)
        f.write(f"2 SOUR {source_id}\n")
        f.write("3 DATA\n")
        if gedcom_date:
            f.write(f"4 DATE {gedcom_date}\n")
        if page_info:
            f.write(f"3 PAGE {page_info}\n")
        f.write("3 QUAY 3\n")
        if self._dialect == 'GRAMPS':
            if note_id:
                f.write(f"3 NOTE {note_id}\n")
            for obje_id in obje_ids:
                f.write(f"3 OBJE {obje_id}\n")
        if self._dialect == 'TNG':
            for obje_id in obje_ids:
                f.write(f"2 OBJE {obje_id}\n")
        
        # Zweite Citation mit SOURCE (Kirchenbuch, falls vorhanden)
        if second_source_id:
            if self._dialect == 'TNG' and second_note_id:
                self._write_inline_note(f, second_note_id, level=2)
            f.write(f"2 SOUR {second_source_id}\n")
            f.write("3 DATA\n")
            if gedcom_date:
                f.write(f"4 DATE {gedcom_date}\n")
            if second_page_info:
                f.write(f"3 PAGE {second_page_info}\n")
            f.write("3 QUAY 3\n")
            if self._dialect == 'GRAMPS':
                if second_note_id:
                    f.write(f"3 NOTE {second_note_id}\n")
                for obje_id in (second_obje_ids or []):
                    f.write(f"3 OBJE {obje_id}\n")
            if self._dialect == 'TNG':
                for obje_id in (second_obje_ids or []):
                    f.write(f"2 OBJE {obje_id}\n")
    
    def _write_burial_event(self, f, date: str, place: str,
                           source_id: str, note_id: Optional[str], obje_ids: List[str],
                           page_info: str,
                           second_source_id: Optional[str] = None, second_page_info: Optional[str] = None,
                           second_note_id: Optional[str] = None, second_obje_ids: Optional[List[str]] = None):
        """Schreibt Begräbnis-Event mit Citation (inkl. optionaler zweiter Quelle)."""
        f.write("1 BURI\n")
        
        gedcom_date = self._format_gedcom_date(date) if date else ""
        if gedcom_date:
            f.write(f"2 DATE {gedcom_date}\n")
        
        if place:
            f.write(f"2 PLAC {self._clean(place)}\n")
        
        # Erste Citation mit SOURCE (Karteikarte)
        if self._dialect == 'TNG' and note_id:
            self._write_inline_note(f, note_id, level=2)
        f.write(f"2 SOUR {source_id}\n")
        f.write("3 DATA\n")
        if gedcom_date:
            f.write(f"4 DATE {gedcom_date}\n")
        if page_info:
            f.write(f"3 PAGE {page_info}\n")
        f.write("3 QUAY 3\n")
        if self._dialect == 'GRAMPS':
            if note_id:
                f.write(f"3 NOTE {note_id}\n")
            for obje_id in obje_ids:
                f.write(f"3 OBJE {obje_id}\n")
        if self._dialect == 'TNG':
            for obje_id in obje_ids:
                f.write(f"2 OBJE {obje_id}\n")
        
        # Zweite Citation mit SOURCE (Kirchenbuch, falls vorhanden)
        if second_source_id:
            if self._dialect == 'TNG' and second_note_id:
                self._write_inline_note(f, second_note_id, level=2)
            f.write(f"2 SOUR {second_source_id}\n")
            f.write("3 DATA\n")
            if gedcom_date:
                f.write(f"4 DATE {gedcom_date}\n")
            if second_page_info:
                f.write(f"3 PAGE {second_page_info}\n")
            f.write("3 QUAY 3\n")
            if self._dialect == 'GRAMPS':
                if second_note_id:
                    f.write(f"3 NOTE {second_note_id}\n")
                for obje_id in (second_obje_ids or []):
                    f.write(f"3 OBJE {obje_id}\n")
            if self._dialect == 'TNG':
                for obje_id in (second_obje_ids or []):
                    f.write(f"2 OBJE {obje_id}\n")
    
    def _write_birth_event(self, f, date: str):
        """Schreibt Geburts-Event (BIRT) mit bereits formatiertem GEDCOM-Datum."""
        f.write("1 BIRT\n")
        if date:
            f.write(f"2 DATE {date}\n")

    def _format_ddmmyyyy_to_gedcom(self, datum: str) -> str:
        """Delegiert an _format_gedcom_date (erkennt DD.MM.YYYY, YYYY.MM.DD und YYYY-MM-DD)."""
        return self._format_gedcom_date(datum)

    def _write_chr_event(self, f, tauf_date_gedcom: str, place: str,
                         source_id: str, note_id: Optional[str], obje_ids: List[str],
                         page_info: str,
                         second_source_id: Optional[str] = None, second_page_info: Optional[str] = None,
                         second_note_id: Optional[str] = None, second_obje_ids: Optional[List[str]] = None):
        """Schreibt Tauf-Event (CHR) mit Citation."""
        f.write("1 CHR\n")
        if tauf_date_gedcom:
            f.write(f"2 DATE {tauf_date_gedcom}\n")
        if place:
            f.write(f"2 PLAC {self._clean(place)}\n")

        if self._dialect == 'TNG' and note_id:
            self._write_inline_note(f, note_id, level=2)
        f.write(f"2 SOUR {source_id}\n")
        f.write("3 DATA\n")
        if tauf_date_gedcom:
            f.write(f"4 DATE {tauf_date_gedcom}\n")
        if page_info:
            f.write(f"3 PAGE {page_info}\n")
        f.write("3 QUAY 3\n")
        if self._dialect == 'GRAMPS':
            if note_id:
                f.write(f"3 NOTE {note_id}\n")
            for obje_id in obje_ids:
                f.write(f"3 OBJE {obje_id}\n")
        if self._dialect == 'TNG':
            for obje_id in obje_ids:
                f.write(f"2 OBJE {obje_id}\n")

        if second_source_id:
            if self._dialect == 'TNG' and second_note_id:
                self._write_inline_note(f, second_note_id, level=2)
            f.write(f"2 SOUR {second_source_id}\n")
            f.write("3 DATA\n")
            if tauf_date_gedcom:
                f.write(f"4 DATE {tauf_date_gedcom}\n")
            if second_page_info:
                f.write(f"3 PAGE {second_page_info}\n")
            f.write("3 QUAY 3\n")
            if self._dialect == 'GRAMPS':
                if second_note_id:
                    f.write(f"3 NOTE {second_note_id}\n")
                for obje_id in (second_obje_ids or []):
                    f.write(f"3 OBJE {obje_id}\n")
            if self._dialect == 'TNG':
                for obje_id in (second_obje_ids or []):
                    f.write(f"2 OBJE {obje_id}\n")

    def _write_occupation_event(self, f, occupation: str, date: str, place: str,
                               source_id: str, note_id: Optional[str], obje_ids: List[str],
                               page_info: str,
                              second_source_id: Optional[str] = None, second_page_info: Optional[str] = None,
                              second_note_id: Optional[str] = None, second_obje_ids: Optional[List[str]] = None):
        """Schreibt Berufs-Event mit Citation (inkl. optionaler zweiter Quelle)."""
        f.write(f"1 OCCU {self._clean(occupation)}\n")
        
        gedcom_date = self._format_gedcom_date(date) if date else ""
        if gedcom_date:
            f.write(f"2 DATE {gedcom_date}\n")
        
        if place:
            f.write(f"2 PLAC {self._clean(place)}\n")
        
        # Erste Citation mit SOURCE (Karteikarte)
        if self._dialect == 'TNG' and note_id:
            self._write_inline_note(f, note_id, level=2)
        f.write(f"2 SOUR {source_id}\n")
        f.write("3 DATA\n")
        if gedcom_date:
            f.write(f"4 DATE {gedcom_date}\n")
        if page_info:
            f.write(f"3 PAGE {page_info}\n")
        f.write("3 QUAY 3\n")
        if self._dialect == 'GRAMPS':
            if note_id:
                f.write(f"3 NOTE {note_id}\n")
            for obje_id in obje_ids:
                f.write(f"3 OBJE {obje_id}\n")
        if self._dialect == 'TNG':
            for obje_id in obje_ids:
                f.write(f"2 OBJE {obje_id}\n")
        
        # Zweite Citation mit SOURCE (Kirchenbuch, falls vorhanden)
        if second_source_id:
            if self._dialect == 'TNG' and second_note_id:
                self._write_inline_note(f, second_note_id, level=2)
            f.write(f"2 SOUR {second_source_id}\n")
            f.write("3 DATA\n")
            if gedcom_date:
                f.write(f"4 DATE {gedcom_date}\n")
            if second_page_info:
                f.write(f"3 PAGE {second_page_info}\n")
            f.write("3 QUAY 3\n")
            if self._dialect == 'GRAMPS':
                if second_note_id:
                    f.write(f"3 NOTE {second_note_id}\n")
                for obje_id in (second_obje_ids or []):
                    f.write(f"3 OBJE {obje_id}\n")
            if self._dialect == 'TNG':
                for obje_id in (second_obje_ids or []):
                    f.write(f"2 OBJE {obje_id}\n")
    
    def _write_residence_event(self, f, date: str, place: str,
                              source_id: str, note_id: Optional[str], obje_ids: List[str],
                              page_info: str,
                              second_source_id: Optional[str] = None, second_page_info: Optional[str] = None,
                              second_note_id: Optional[str] = None, second_obje_ids: Optional[List[str]] = None):
        """Schreibt Wohnort-Event mit Citation (inkl. optionaler zweiter Quelle)."""
        f.write("1 RESI\n")
        
        if place:
            f.write(f"2 PLAC {self._clean(place)}\n")
        
        gedcom_date = self._format_gedcom_date(date) if date else ""
        if gedcom_date:
            f.write(f"2 DATE {gedcom_date}\n")
        
        # Erste Citation mit SOURCE (Karteikarte)
        if self._dialect == 'TNG' and note_id:
            self._write_inline_note(f, note_id, level=2)
        f.write(f"2 SOUR {source_id}\n")
        f.write("3 DATA\n")
        if gedcom_date:
            f.write(f"4 DATE {gedcom_date}\n")
        if page_info:
            f.write(f"3 PAGE {page_info}\n")
        f.write("3 QUAY 3\n")
        if self._dialect == 'GRAMPS':
            if note_id:
                f.write(f"3 NOTE {note_id}\n")
            for obje_id in obje_ids:
                f.write(f"3 OBJE {obje_id}\n")
        if self._dialect == 'TNG':
            for obje_id in obje_ids:
                f.write(f"2 OBJE {obje_id}\n")
        
        # Zweite Citation mit SOURCE (Kirchenbuch, falls vorhanden)
        if second_source_id:
            if self._dialect == 'TNG' and second_note_id:
                self._write_inline_note(f, second_note_id, level=2)
            f.write(f"2 SOUR {second_source_id}\n")
            f.write("3 DATA\n")
            if gedcom_date:
                f.write(f"4 DATE {gedcom_date}\n")
            if second_page_info:
                f.write(f"3 PAGE {second_page_info}\n")
            f.write("3 QUAY 3\n")
            if self._dialect == 'GRAMPS':
                if second_note_id:
                    f.write(f"3 NOTE {second_note_id}\n")
                for obje_id in (second_obje_ids or []):
                    f.write(f"3 OBJE {obje_id}\n")
            if self._dialect == 'TNG':
                for obje_id in (second_obje_ids or []):
                    f.write(f"2 OBJE {obje_id}\n")
    
    def _process_marriage_record(self, record: dict) -> List[str]:
        """Verarbeitet einen Hochzeits-Datensatz."""
        # Extrahiere Felder
        braeutigam_vorname = self._clean(record.get('vorname', ''))
        braeutigam_nachname = self._clean(record.get('nachname', ''))
        braut_vorname = self._clean(record.get('partner', ''))
        braut_nachname = self._clean(record.get('braut_nachname', ''))
        braeutigam_vater_vorname = self._clean(record.get('braeutigam_vater', ''))
        braut_vater_vorname = self._clean(record.get('braut_vater', ''))
        beruf = self._clean(record.get('beruf', ''))
        heiratsdatum = self._clean(record.get('iso_datum', ''))
        
        # Heirat ist immer in Wetzlar
        heiratsort = "Wetzlar"
        
        # Der Ort aus der Datenbank wird für Beruf und Wohnort verwendet
        beruf_ort = self._clean(record.get('ort', ''))
        braut_ort = self._clean(record.get('braut_ort', ''))  # nicht verwendet, aber ggf. in Daten
        
        # Citation-Daten
        erkannter_text = self._clean(record.get('erkannter_text', ''))
        dateiname = self._clean(record.get('dateiname', ''))
        dateipfad = self._clean(record.get('dateipfad', ''))
        
        # Quelle ermitteln
        source_name = self._resolve_source_name(dateiname, heiratsdatum)
        
        # IDs erstellen
        source_id = self._get_source_id(source_name)

        # Zweite Quelle (Kirchenbuch) ermitteln
        ereignis_typ = self._clean(record.get('ereignis_typ', ''))
        jahr = record.get('jahr')
        seite = self._clean(record.get('seite', ''))
        kirchenbuchtext = self._clean(record.get('kirchenbuchtext', ''))
        nummer = self._extract_nummer_from_text(erkannter_text)
        second_source_name = None
        second_source_id = None
        second_page_info = None
        second_note_id = None
        second_obje_ids = []
        kirchenbuch_image_path = None
        
        if jahr and seite:
            second_source_name = self._find_kirchenbuch_source(ereignis_typ, jahr, seite)
            if second_source_name:
                second_source_id = self._get_source_id(second_source_name)
                kirchenbuch_image_path = self._get_kirchenbuch_image_path(second_source_name, seite)
                second_page_info = self._format_second_page_info(seite, nummer, kirchenbuch_image_path)
                
                # Erstelle NOTE für Kirchenbuchtext, falls vorhanden
                if kirchenbuchtext:
                    second_note_id = self._add_note("Kirchenbuchabschrift", kirchenbuchtext)
                
                # Erstelle OBJE für Kirchenbuch-Bild
                if kirchenbuch_image_path:
                    second_obje_id = self._add_obje(kirchenbuch_image_path)
                    second_obje_ids.append(second_obje_id)

        # PAGE für Karteikarte: Seite/Nr./Bild-Format (Kirchenbuch-Referenz)
        page_info = self._format_second_page_info(seite, nummer, dateipfad) if seite else self._format_page_number(dateiname)
        
        # Obje hinzufügen
        obje_ids = []
        if dateipfad:
            obje_id = self._add_obje(dateipfad)
            obje_ids.append(obje_id)
        
        # Note hinzufügen
        note_id = None
        if erkannter_text:
            note_id = self._add_note("Abschrift Karteikarte", self._clean_note_text(erkannter_text))
        
        # Prüfe auf Wittwer
        is_braeutigam_wittwer = self._is_wittwer(braeutigam_vater_vorname)
        is_braut_wittwer = self._is_wittwer(braut_vater_vorname)
        
        marriage_note = None
        if is_braeutigam_wittwer:
            marriage_note = "Bräutigam ist Wittwer"
        elif is_braut_wittwer:
            marriage_note = "Braut ist Witwe"
        
        # Personen erstellen
        person_ids = []
        
        # Bräutigam (männlich)
        braeutigam_id = self._get_person_id(braeutigam_vorname, braeutigam_nachname, "Bräutigam", sex='M')
        
        # Braut (weiblich)
        braut_id = self._get_person_id(braut_vorname, braut_nachname, "Braut", sex='F')
        
        # Bräutigam Vater (nur wenn nicht Wittwer) - männlich
        braeutigam_vater_id = None
        if braeutigam_vater_vorname and not is_braeutigam_wittwer:
            braeutigam_vater_id = self._get_person_id(braeutigam_vater_vorname, braeutigam_nachname, "Vater", sex='M')
        
        # Braut Vater (nur wenn nicht Witwe) - männlich
        braut_vater_id = None
        if braut_vater_vorname and not is_braut_wittwer:
            braut_vater_id = self._get_person_id(braut_vater_vorname, braut_nachname, "Vater", sex='M')
        
        # Familien erstellen
        haupt_familie_id = self._get_family_id()
        braeutigam_eltern_familie_id = None
        braut_eltern_familie_id = None
        
        if braeutigam_vater_id:
            braeutigam_eltern_familie_id = self._get_family_id()
        
        if braut_vater_id:
            braut_eltern_familie_id = self._get_family_id()

        # Familie-Zuordnungen VOR dem Schreiben der Personen setzen,
        # damit FAMS/FAMC im INDI-Block direkt ausgegeben werden.
        if braeutigam_id:
            self._person_families.setdefault(braeutigam_id, []).append(haupt_familie_id)
        if braut_id:
            self._person_families.setdefault(braut_id, []).append(haupt_familie_id)

        if braeutigam_eltern_familie_id and braeutigam_vater_id and braeutigam_id:
            self._person_families.setdefault(braeutigam_vater_id, []).append(braeutigam_eltern_familie_id)
            self._person_child_families[braeutigam_id] = braeutigam_eltern_familie_id

        if braut_eltern_familie_id and braut_vater_id and braut_id:
            self._person_families.setdefault(braut_vater_id, []).append(braut_eltern_familie_id)
            self._person_child_families[braut_id] = braut_eltern_familie_id

        # Personen für spätere INDI-Ausgabe vormerken
        if braeutigam_id:
            self._register_person(braeutigam_id, braeutigam_vorname, braeutigam_nachname)
            person_ids.append(braeutigam_id)

        if braut_id:
            self._register_person(braut_id, braut_vorname, braut_nachname)
            person_ids.append(braut_id)

        if braeutigam_vater_id:
            self._register_person(braeutigam_vater_id, braeutigam_vater_vorname, braeutigam_nachname)
            person_ids.append(braeutigam_vater_id)

        if braut_vater_id:
            self._register_person(braut_vater_id, braut_vater_vorname, braut_nachname)
            person_ids.append(braut_vater_id)

        # Haupt-Familie mit Heirats-Event puffern
        haupt_fam = StringIO()
        haupt_fam.write(f"0 {haupt_familie_id} FAM\n")
        if braeutigam_id:
            haupt_fam.write(f"1 HUSB {braeutigam_id}\n")
        
        if braut_id:
            haupt_fam.write(f"1 WIFE {braut_id}\n")
        
        # Heirats-Event mit Citation
        self._write_marriage_event(haupt_fam, heiratsdatum, heiratsort, 
                                   source_id, note_id, obje_ids, page_info, erkannter_text,
                                   second_source_id, second_page_info, second_note_id, second_obje_ids)
        
        # Wenn Wittwer/Witwe, füge Note zur Familie hinzu
        if marriage_note:
            marriage_note_id = self._add_note("Hochzeit", marriage_note)
            haupt_fam.write(f"1 NOTE {marriage_note_id}\n")

        self._add_family_record(haupt_familie_id, haupt_fam.getvalue())
        
        # Bräutigam Eltern-Familie puffern
        if braeutigam_eltern_familie_id and braeutigam_vater_id and braeutigam_id:
            braeutigam_eltern_fam = StringIO()
            braeutigam_eltern_fam.write(f"0 {braeutigam_eltern_familie_id} FAM\n")
            braeutigam_eltern_fam.write(f"1 HUSB {braeutigam_vater_id}\n")
            braeutigam_eltern_fam.write(f"1 CHIL {braeutigam_id}\n")
            self._add_family_record(braeutigam_eltern_familie_id, braeutigam_eltern_fam.getvalue())
        
        # Braut Eltern-Familie puffern
        if braut_eltern_familie_id and braut_vater_id and braut_id:
            braut_eltern_fam = StringIO()
            braut_eltern_fam.write(f"0 {braut_eltern_familie_id} FAM\n")
            braut_eltern_fam.write(f"1 HUSB {braut_vater_id}\n")
            braut_eltern_fam.write(f"1 CHIL {braut_id}\n")
            self._add_family_record(braut_eltern_familie_id, braut_eltern_fam.getvalue())
        
        # Wenn Beruf vorhanden: OCCU und RESI Events zum Bräutigam hinzufügen
        if beruf and braeutigam_id:
            # OCCU Event
            occu_event = StringIO()
            self._write_occupation_event(occu_event, beruf, heiratsdatum, beruf_ort,
                                        source_id, note_id, obje_ids, page_info,
                                        second_source_id, second_page_info, second_note_id, second_obje_ids)
            self._add_person_event(braeutigam_id, occu_event.getvalue())
            
            # RESI Event für Beruf-Ort (nur wenn beruf vorhanden)
            resi_event = StringIO()
            self._write_residence_event(resi_event, heiratsdatum, beruf_ort,
                                       source_id, note_id, obje_ids, page_info,
                                       second_source_id, second_page_info, second_note_id, second_obje_ids)
            self._add_person_event(braeutigam_id, resi_event.getvalue())
        elif beruf_ort and braeutigam_id:
            # Wenn nur Ort vorhanden (ohne Beruf): RESI für Bräutigam
            resi_event = StringIO()
            self._write_residence_event(resi_event, heiratsdatum, beruf_ort,
                                       source_id, note_id, obje_ids, page_info,
                                       second_source_id, second_page_info, second_note_id, second_obje_ids)
            self._add_person_event(braeutigam_id, resi_event.getvalue())
        
        # Wenn Ort vorhanden: RESI Event für Bräutigamsvater hinzufügen
        if beruf_ort and braeutigam_vater_id:
            vater_resi_event = StringIO()
            self._write_residence_event(vater_resi_event, heiratsdatum, beruf_ort,
                                       source_id, note_id, obje_ids, page_info,
                                       second_source_id, second_page_info, second_note_id, second_obje_ids)
            self._add_person_event(braeutigam_vater_id, vater_resi_event.getvalue())
        
        # Wenn Braut-Ort vorhanden: RESI Events für Braut und Brautvater hinzufügen
        if braut_ort and braut_id:
            # Braut RESI mit "vor (Heiratsdatum)"
            braut_resi_event = StringIO()
            braut_resi_event.write("1 RESI\n")
            braut_resi_event.write(f"2 PLAC {self._clean(braut_ort)}\n")
            
            gedcom_date_before = self._format_gedcom_date_with_before(heiratsdatum)
            if gedcom_date_before:
                braut_resi_event.write(f"2 DATE {gedcom_date_before}\n")
            
            # Citation mit SOURCE
            braut_resi_event.write(f"2 SOUR {source_id}\n")
            braut_resi_event.write("3 DATA\n")
            
            if heiratsdatum:
                gedcom_date = self._format_gedcom_date(heiratsdatum)
                if gedcom_date:
                    braut_resi_event.write(f"4 DATE {gedcom_date}\n")
            
            if page_info:
                braut_resi_event.write(f"3 PAGE {page_info}\n")
            
            braut_resi_event.write("3 QUAY 3\n")
            
            if note_id:
                braut_resi_event.write(f"3 NOTE {note_id}\n")
            
            for obje_id in obje_ids:
                braut_resi_event.write(f"3 OBJE {obje_id}\n")
            
            # Zweite Citation mit SOURCE (Kirchenbuch, falls vorhanden)
            if second_source_id:
                braut_resi_event.write(f"2 SOUR {second_source_id}\n")
                braut_resi_event.write("3 DATA\n")
                
                if heiratsdatum:
                    gedcom_date = self._format_gedcom_date(heiratsdatum)
                    if gedcom_date:
                        braut_resi_event.write(f"4 DATE {gedcom_date}\n")
                
                if second_page_info:
                    braut_resi_event.write(f"3 PAGE {second_page_info}\n")
                
                braut_resi_event.write("3 QUAY 3\n")
                
                # NOTE und OBJE für Kirchenbuch-Citation
                if second_note_id:
                    braut_resi_event.write(f"3 NOTE {second_note_id}\n")
                
                if second_obje_ids:
                    for obje_id in second_obje_ids:
                        braut_resi_event.write(f"3 OBJE {obje_id}\n")
            
            self._add_person_event(braut_id, braut_resi_event.getvalue())
        
        # Wenn Braut-Ort und Brautvater vorhanden: RESI Event für Brautvater
        if braut_ort and braut_vater_id:
            # Brautvater RESI mit Heiratsdatum (ohne "vor")
            vater_resi_event = StringIO()
            vater_resi_event.write("1 RESI\n")
            vater_resi_event.write(f"2 PLAC {self._clean(braut_ort)}\n")
            
            if heiratsdatum:
                gedcom_date = self._format_gedcom_date(heiratsdatum)
                if gedcom_date:
                    vater_resi_event.write(f"2 DATE {gedcom_date}\n")
            
            # Citation mit SOURCE
            vater_resi_event.write(f"2 SOUR {source_id}\n")
            vater_resi_event.write("3 DATA\n")
            
            if heiratsdatum:
                gedcom_date = self._format_gedcom_date(heiratsdatum)
                if gedcom_date:
                    vater_resi_event.write(f"4 DATE {gedcom_date}\n")
            
            if page_info:
                vater_resi_event.write(f"3 PAGE {page_info}\n")
            
            vater_resi_event.write("3 QUAY 3\n")
            
            if note_id:
                vater_resi_event.write(f"3 NOTE {note_id}\n")
            
            for obje_id in obje_ids:
                vater_resi_event.write(f"3 OBJE {obje_id}\n")
            
            # Zweite Citation mit SOURCE (Kirchenbuch, falls vorhanden)
            if second_source_id:
                vater_resi_event.write(f"2 SOUR {second_source_id}\n")
                vater_resi_event.write("3 DATA\n")
                
                if heiratsdatum:
                    gedcom_date = self._format_gedcom_date(heiratsdatum)
                    if gedcom_date:
                        vater_resi_event.write(f"4 DATE {gedcom_date}\n")
                
                if second_page_info:
                    vater_resi_event.write(f"3 PAGE {second_page_info}\n")
                
                vater_resi_event.write("3 QUAY 3\n")
                
                # NOTE und OBJE für Kirchenbuch-Citation
                if second_note_id:
                    vater_resi_event.write(f"3 NOTE {second_note_id}\n")
                
                if second_obje_ids:
                    for obje_id in second_obje_ids:
                        vater_resi_event.write(f"3 OBJE {obje_id}\n")
            
            self._add_person_event(braut_vater_id, vater_resi_event.getvalue())
        
        return person_ids
    
    def _process_burial_record(self, record: dict) -> List[str]:
        """Verarbeitet einen Begräbnis-Datensatz."""
        # Extrahiere Felder
        vorname = self._clean(record.get('vorname', ''))
        nachname = self._clean(record.get('nachname', ''))
        todesdatum = self._clean(record.get('iso_datum', ''))
        todesort = self._clean(record.get('ort', ''))
        geb_jahr_gesch = record.get('geb_jahr_gesch')
        
        # Sterbeort: Wetzlar als Standard, wenn kein anderer Ort angegeben
        if not todesort:
            todesort = "Wetzlar"
        
        # Citation-Daten
        erkannter_text = self._clean(record.get('erkannter_text', ''))
        dateiname = self._clean(record.get('dateiname', ''))
        dateipfad = self._clean(record.get('dateipfad', ''))
        
        # Quelle ermitteln
        source_name = self._resolve_source_name(dateiname, todesdatum)
        
        # IDs erstellen
        source_id = self._get_source_id(source_name)

        # Zweite Quelle (Kirchenbuch) ermitteln
        ereignis_typ = self._clean(record.get('ereignis_typ', ''))
        jahr = record.get('jahr')
        seite = self._clean(record.get('seite', ''))
        kirchenbuchtext = self._clean(record.get('kirchenbuchtext', ''))
        nummer = self._extract_nummer_from_text(erkannter_text)
        second_source_name = None
        second_source_id = None
        second_page_info = None
        second_note_id = None
        second_obje_ids = []
        kirchenbuch_image_path = None
        
        if jahr and seite:
            second_source_name = self._find_kirchenbuch_source(ereignis_typ, jahr, seite)
            if second_source_name:
                second_source_id = self._get_source_id(second_source_name)
                kirchenbuch_image_path = self._get_kirchenbuch_image_path(second_source_name, seite)
                second_page_info = self._format_second_page_info(seite, nummer, kirchenbuch_image_path)
                
                # Erstelle NOTE für Kirchenbuchtext, falls vorhanden
                if kirchenbuchtext:
                    second_note_id = self._add_note("Kirchenbuchabschrift", kirchenbuchtext)
                
                # Erstelle OBJE für Kirchenbuch-Bild
                if kirchenbuch_image_path:
                    second_obje_id = self._add_obje(kirchenbuch_image_path)
                    second_obje_ids.append(second_obje_id)

        # PAGE für Karteikarte: Seite/Nr./Bild-Format (Kirchenbuch-Referenz)
        page_info = self._format_second_page_info(seite, nummer, dateipfad) if seite else self._format_page_number(dateiname)
        
        # Obje hinzufügen
        obje_ids = []
        if dateipfad:
            obje_id = self._add_obje(dateipfad)
            obje_ids.append(obje_id)
        
        # Note hinzufügen - mit bereinigtem Text
        note_id = None
        if erkannter_text:
            # Entferne den Präfix (z.B. "ev. Kb. Wetzlar ⚰ 1694.07.22. p. 2 Nr. 5")
            cleaned_text = self._clean_note_text(erkannter_text)
            note_id = self._add_note("Abschrift Karteikarte", cleaned_text)
        
        # Geschlecht erkennen
        sex = self._determine_sex_from_vorname(vorname)
        
        # Person erstellen
        person_id = self._get_person_id(vorname, nachname, "Verstorben", sex=sex)
        
        if not person_id:
            return []

        self._register_person(person_id, vorname, nachname)

        # Falls ein geschätztes Geburtsjahr vorhanden ist, ergänze einmalig ein BIRT-Event.
        estimated_birth_date = self._format_estimated_birth_year(geb_jahr_gesch)
        if estimated_birth_date and not self._person_has_event(person_id, "BIRT"):
            birth_event_buffer = StringIO()
            self._write_birth_event(birth_event_buffer, estimated_birth_date)
            self._add_person_event(person_id, birth_event_buffer.getvalue())

        # Begräbnis-Event als INDI-Event puffern
        burial_event_buffer = StringIO()
        self._write_burial_event(burial_event_buffer, todesdatum, todesort,
                                 source_id, note_id, obje_ids, page_info,
                                 second_source_id, second_page_info, second_note_id, second_obje_ids)
        self._add_person_event(person_id, burial_event_buffer.getvalue())
        
        return [person_id]

    def _process_baptism_record(self, record: dict) -> List[str]:
        """Verarbeitet einen Taufeintrag.

        Feld-Mapping:
            vorname        → Täufling-Vorname
            nachname       → Familienname (Vater-Nachname)
            partner        → Vater-Vorname
            mutter_vorname → Mutter-Vorname
            datum_geburt   → Geburtsdatum   (YYYY.MM.DD)
            todestag       → Taufdatum      (YYYY.MM.DD)
            ort            → Tauf- und Geburtsort
            stand          → Geschlecht des Täuflings ('M'/'F'), Fallback via Vorname
        """
        taeufl_vorname = self._clean(record.get('vorname', ''))
        nachname = self._clean(record.get('nachname', ''))
        vater_vorname = self._clean(record.get('partner', ''))
        mutter_vorname = self._clean(record.get('mutter_vorname', ''))
        datum_geburt_raw = self._clean(record.get('datum_geburt', ''))
        taufdatum_raw = self._clean(record.get('todestag', ''))
        ort = self._clean(record.get('ort', '')) or 'Wetzlar'

        # Geschlecht: zuerst aus 'stand' (Braut Stand), dann aus Vorname
        sex_raw = self._clean(record.get('stand', '') or record.get('braeutigam_stand', ''))
        if sex_raw.upper() in ('M', 'F'):
            sex = sex_raw.upper()
        else:
            sex = self._determine_sex_from_vorname(taeufl_vorname)

        # Datumsformate (DD.MM.YYYY oder YYYY.MM.DD) → GEDCOM
        geb_gedcom = self._format_gedcom_date(datum_geburt_raw)
        tauf_gedcom = self._format_gedcom_date(taufdatum_raw)

        # Citation-Daten
        erkannter_text = self._clean(record.get('erkannter_text', ''))
        dateiname = self._clean(record.get('dateiname', ''))
        dateipfad = self._clean(record.get('dateipfad', ''))
        ereignis_typ = self._clean(record.get('ereignis_typ', ''))
        jahr = record.get('jahr')
        seite = self._clean(record.get('seite', ''))
        kirchenbuchtext = self._clean(record.get('kirchenbuchtext', ''))

        # Primärquelle (Karteikarte)
        source_name = self._resolve_source_name(dateiname, record.get('iso_datum', ''))
        source_id = self._get_source_id(source_name)

        # Zweite Quelle (Kirchenbuch)
        nummer = self._extract_nummer_from_text(erkannter_text)
        second_source_id = None
        second_page_info = None
        second_note_id = None
        second_obje_ids = []
        kb_image = None
        if jahr and seite:
            second_source_name = self._find_kirchenbuch_source(ereignis_typ, jahr, seite)
            if second_source_name:
                second_source_id = self._get_source_id(second_source_name)
                kb_image = self._get_kirchenbuch_image_path(second_source_name, seite)
                second_page_info = self._format_second_page_info(seite, nummer, kb_image)
                if kirchenbuchtext:
                    second_note_id = self._add_note("Kirchenbuchabschrift", kirchenbuchtext)
                if kb_image:
                    second_obje_ids.append(self._add_obje(kb_image))

        # PAGE für Karteikarte: Seite/Nr./Bild-Format (Kirchenbuch-Referenz)
        page_info = self._format_second_page_info(seite, nummer, dateipfad) if seite else self._format_page_number(dateiname)

        obje_ids = []
        if dateipfad:
            obje_ids.append(self._add_obje(dateipfad))

        note_id = None
        if erkannter_text:
            note_id = self._add_note("Abschrift Karteikarte", self._clean_note_text(erkannter_text))

        # --- Personen anlegen ---
        # Täufling
        kind_id = self._get_person_id(taeufl_vorname, nachname, "Täufling", sex=sex)
        # Vater
        vater_id = self._get_person_id(vater_vorname, nachname, "Vater", sex='M') if vater_vorname else None
        # Mutter (Nachname unbekannt → leer lassen)
        mutter_id = self._get_person_id(mutter_vorname, '', "Mutter", sex='F') if mutter_vorname else None

        if not kind_id:
            return []

        # Eltern-Familie anlegen
        eltern_familie_id = None
        if vater_id or mutter_id:
            eltern_familie_id = self._get_family_id()
            if vater_id:
                self._person_families.setdefault(vater_id, []).append(eltern_familie_id)
            if mutter_id:
                self._person_families.setdefault(mutter_id, []).append(eltern_familie_id)
            self._person_child_families[kind_id] = eltern_familie_id

        # Personen registrieren
        self._register_person(kind_id, taeufl_vorname, nachname)
        if vater_id:
            self._register_person(vater_id, vater_vorname, nachname)
        if mutter_id:
            self._register_person(mutter_id, mutter_vorname, '')

        # BIRT-Event für Täufling
        if geb_gedcom:
            birt_buf = StringIO()
            birt_buf.write("1 BIRT\n")
            birt_buf.write(f"2 DATE {geb_gedcom}\n")
            if ort:
                birt_buf.write(f"2 PLAC {ort}\n")
            # TNG: NOTE vor SOUR
            if self._dialect == 'TNG' and note_id:
                self._write_inline_note(birt_buf, note_id, level=2)
            birt_buf.write(f"2 SOUR {source_id}\n")
            birt_buf.write("3 DATA\n")
            birt_buf.write(f"4 DATE {geb_gedcom}\n")
            if page_info:
                birt_buf.write(f"3 PAGE {page_info}\n")
            birt_buf.write("3 QUAY 3\n")
            if self._dialect == 'GRAMPS':
                if note_id:
                    birt_buf.write(f"3 NOTE {note_id}\n")
                for oid in obje_ids:
                    birt_buf.write(f"3 OBJE {oid}\n")
            if self._dialect == 'TNG':
                for oid in obje_ids:
                    birt_buf.write(f"2 OBJE {oid}\n")
            if second_source_id:
                if self._dialect == 'TNG' and second_note_id:
                    self._write_inline_note(birt_buf, second_note_id, level=2)
                birt_buf.write(f"2 SOUR {second_source_id}\n")
                birt_buf.write("3 DATA\n")
                birt_buf.write(f"4 DATE {geb_gedcom}\n")
                if second_page_info:
                    birt_buf.write(f"3 PAGE {second_page_info}\n")
                birt_buf.write("3 QUAY 3\n")
                if self._dialect == 'GRAMPS':
                    if second_note_id:
                        birt_buf.write(f"3 NOTE {second_note_id}\n")
                    for oid in second_obje_ids:
                        birt_buf.write(f"3 OBJE {oid}\n")
                if self._dialect == 'TNG':
                    for oid in second_obje_ids:
                        birt_buf.write(f"2 OBJE {oid}\n")
            self._add_person_event(kind_id, birt_buf.getvalue())

        # TNG: Approximiertes BIRT aus Taufdatum, falls kein Geburtsdatum vorhanden
        if self._dialect == 'TNG' and not geb_gedcom and tauf_gedcom:
            approx_birt_buf = StringIO()
            approx_birt_buf.write("1 BIRT\n")
            approx_birt_buf.write(f"2 DATE ABT {tauf_gedcom}\n")
            approx_birt_buf.write(f"2 PLAC {ort}\n")
            approx_birt_buf.write("2 NOTE Geschätzt aus Taufdatum\n")
            self._add_person_event(kind_id, approx_birt_buf.getvalue())

        # CHR-Event für Täufling
        if tauf_gedcom:
            chr_buf = StringIO()
            self._write_chr_event(chr_buf, tauf_gedcom, ort,
                                  source_id, note_id, obje_ids, page_info,
                                  second_source_id, second_page_info, second_note_id, second_obje_ids)
            self._add_person_event(kind_id, chr_buf.getvalue())

        # Eltern-FAM-Block
        if eltern_familie_id:
            fam_buf = StringIO()
            fam_buf.write(f"0 {eltern_familie_id} FAM\n")
            if vater_id:
                fam_buf.write(f"1 HUSB {vater_id}\n")
            if mutter_id:
                fam_buf.write(f"1 WIFE {mutter_id}\n")
            fam_buf.write(f"1 CHIL {kind_id}\n")
            self._add_family_record(eltern_familie_id, fam_buf.getvalue())

        return [kind_id] + ([vater_id] if vater_id else []) + ([mutter_id] if mutter_id else [])

    def export_to_gedcom(self, output_file: str, filter_params: Optional[dict] = None) -> int:
        """
        Exportiert die Datenbank als GEDCOM-Datei.
        
        Args:
            output_file: Pfad zur Ausgabedatei
            filter_params: Optional dict mit Filterparametern
        
        Returns:
            Anzahl exportierter Datensätze
        """
        # SQL-Query aufbauen
        where_clauses = []
        params = []
        
        if filter_params:
            if 'year' in filter_params and filter_params['year']:
                where_clauses.append("jahr = ?")
                params.append(filter_params['year'])
            
            if 'event_type' in filter_params and filter_params['event_type']:
                where_clauses.append("ereignis_typ = ?")
                params.append(filter_params['event_type'])
            
            if 'id_list' in filter_params and filter_params['id_list']:
                placeholders = ','.join('?' * len(filter_params['id_list']))
                where_clauses.append(f"id IN ({placeholders})")
                params.extend(filter_params['id_list'])
        
        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        query = f"""
            SELECT * FROM karteikarten 
            WHERE {where_clause}
            ORDER BY jahr, iso_datum, id
        """
        
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        
        # Hole alle Datensätze
        columns = [col[0] for col in cursor.description]
        records = []
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            records.append(record)
        
        if not records:
            raise ValueError("Keine Datensätze zum Exportieren gefunden.")

        # Laufzeit-Puffer für geordnete Ausgabe zurücksetzen
        self._pending_persons.clear()
        self._pending_person_events.clear()
        self._pending_family_records.clear()
        self._missing_source_warnings.clear()
        
        # Phase 1: Sammle alle Quellen-IDs
        for record in records:
            dateiname = self._clean(record.get('dateiname', ''))
            iso_datum = self._clean(record.get('iso_datum', ''))
            
            # Registriere Quellen-ID
            source_name = self._resolve_source_name(dateiname, iso_datum)
            _ = self._get_source_id(source_name)  # Nur zum Registrieren
        
        # Phase 2: Schreibe Datei mit korrekter Reihenfolge
        with open(output_file, 'w', encoding='utf-8') as f:
            # 1. Header
            self._write_header(f)
            
            # 2. Verarbeite Datensätze und puffern (INDI/FAM getrennt)
            exported_count = 0
            for record in records:
                ereignis_typ = self._clean(record.get('ereignis_typ', ''))

                if 'heirat' in ereignis_typ.lower() or '∞' in ereignis_typ:
                    self._process_marriage_record(record)
                    exported_count += 1
                elif 'begr' in ereignis_typ.lower() or 'sb' in ereignis_typ.lower():
                    self._process_burial_record(record)
                    exported_count += 1
                elif 'tauf' in ereignis_typ.lower() or 'gb' in ereignis_typ.lower():
                    self._process_baptism_record(record)
                    exported_count += 1

            # 3. Strikte Reihenfolge: erst alle INDI, dann alle FAM
            self._write_all_individuals(f)
            self._write_all_families(f)
            
            # 4. Alle SOUR-Records (nach FAM, vor NOTE)
            self._write_all_sources(f)
            
            # 5. Schreibe NOTE und OBJE Einträge
            self._write_notes_and_objes(f)
            
            # 6. Trailer
            f.write("0 TRLR\n")
        
        return exported_count
