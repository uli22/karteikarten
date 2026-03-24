"""Datenbank-Modul für Karteikarten-Verwaltung."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class KarteikartenDB:
    """Datenbank für die Verwaltung von erkannten Karteikarten."""
    
    def __init__(self, db_path: str = "karteikarten.db"):
        """
        Initialisiert die Datenbank.
        
        Args:
            db_path: Pfad zur SQLite-Datenbankdatei
        """
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Stellt Verbindung zur Datenbank her."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Ermöglicht Zugriff per Spaltenname
    
    def _create_tables(self):
        """Erstellt die Datenbanktabellen falls nicht vorhanden."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS karteikarten (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dateiname TEXT NOT NULL,
                dateipfad TEXT NOT NULL UNIQUE,
                
                -- Metadaten
                kirchengemeinde TEXT,
                ereignis_typ TEXT,  -- z.B. Heirat (∞), Taufe, Begräbnis
                
                -- Datum
                jahr INTEGER,
                datum TEXT,  -- DD.MM.YYYY Format (z.B. "20.11.1564" oder "00.03.1616")
                iso_datum TEXT,  -- YYYY-MM-DD Format (z.B. "1564-11-20" oder "1616-03-00")
                
                -- Referenz im Kirchenbuch
                seite TEXT,  -- z.B. "p. 87"
                nummer TEXT,  -- z.B. "Nr. 1"
                
                -- OCR-Daten
                erkannter_text TEXT,
                ocr_methode TEXT,  -- easyocr, tesseract, cloud_vision
                kirchenbuchtext TEXT,  -- Manuell eingegebener Kirchenbuchtext
                
                -- Extrahierte Felder
                vorname TEXT,
                nachname TEXT,
                partner TEXT,
                beruf TEXT,
                todestag TEXT,
                ort TEXT,
                geb_jahr_gesch INTEGER,  -- Geschätztes Geburtsjahr (berechnet aus Todesdatum - Alter)
                
                -- Neue Felder für Heiraten
                braeutigam_vater TEXT,
                braut_vater TEXT,
                braut_nachname TEXT,
                braut_ort TEXT,
                
                -- Notiz (kurzer Text bis 10 Zeichen)
                notiz TEXT,
                
                -- Gramps ID (10 Zeichen)
                gramps TEXT,
                
                -- Timestamps
                erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                aktualisiert_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration: Füge notiz-Spalte hinzu falls nicht vorhanden
        cursor.execute("PRAGMA table_info(karteikarten)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'notiz' not in columns:
            cursor.execute("ALTER TABLE karteikarten ADD COLUMN notiz TEXT")
        
        # Migration: Füge iso_datum-Spalte hinzu falls nicht vorhanden
        if 'iso_datum' not in columns:
            cursor.execute("ALTER TABLE karteikarten ADD COLUMN iso_datum TEXT")
            # Konvertiere bestehende Datumswerte
            cursor.execute("SELECT id, datum FROM karteikarten WHERE datum IS NOT NULL")
            rows = cursor.fetchall()
            for row_id, datum in rows:
                iso_datum = self._convert_to_iso_date(datum)
                if iso_datum:
                    cursor.execute("UPDATE karteikarten SET iso_datum = ? WHERE id = ?", (iso_datum, row_id))

        # Migration: Füge neue Felder für Extraktion hinzu
        new_fields = [
            ('vorname', 'TEXT'),
            ('nachname', 'TEXT'),
            ('partner', 'TEXT'),
            ('beruf', 'TEXT'),
            ('todestag', 'TEXT'),
            ('ort', 'TEXT'),
            ('geb_jahr_gesch', 'INTEGER'),
            ('stand', 'TEXT'),
            ('braeutigam_stand', 'TEXT'),
            ('braeutigam_vater', 'TEXT'),
            ('braut_vater', 'TEXT'),
            ('braut_nachname', 'TEXT'),
            ('braut_ort', 'TEXT'),
            ('kirchenbuchtext', 'TEXT'),
            ('fid', 'TEXT'),  # Familien-ID aus families_ok.tsv
            ('gramps', 'TEXT'),  # Gramps ID
        ]
        for field, ftype in new_fields:
            if field not in columns:
                cursor.execute(f"ALTER TABLE karteikarten ADD COLUMN {field} {ftype}")
        
        # Index für schnelle Suche (nach Migration, damit iso_datum bereits existiert)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jahr ON karteikarten(jahr)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_datum ON karteikarten(datum)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_iso_datum ON karteikarten(iso_datum)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kirchengemeinde ON karteikarten(kirchengemeinde)
        """)
        
        self.conn.commit()
    
    def reset_autoincrement(self):
        """
        Setzt den AUTOINCREMENT Counter auf die höchste vorhandene ID zurück.
        Verhindert, dass neue Einträge zu hohe IDs bekommen.
        """
        cursor = self.conn.cursor()
        
        # Hole die höchste ID aus der Tabelle
        cursor.execute("SELECT MAX(id) FROM karteikarten")
        max_id = cursor.fetchone()[0]
        
        if max_id is not None:
            # Aktualisiere sqlite_sequence (interner Counter)
            cursor.execute("""
                UPDATE sqlite_sequence 
                SET seq = ? 
                WHERE name = 'karteikarten'
            """, (max_id,))
            self.conn.commit()
            print(f"[DB] AUTOINCREMENT zurückgesetzt auf {max_id}")
            return max_id
        else:
            # Keine Einträge vorhanden - setze auf 0
            cursor.execute("""
                INSERT OR REPLACE INTO sqlite_sequence (name, seq) 
                VALUES ('karteikarten', 0)
            """)
            self.conn.commit()
            print("[DB] AUTOINCREMENT zurückgesetzt auf 0 (keine Einträge)")
            return 0
    
    def _convert_to_iso_date(self, datum: str) -> Optional[str]:
        """
        Konvertiert ein Datum von DD.MM.YYYY zu YYYY-MM-DD Format.
        
        Args:
            datum: Datum im Format "DD.MM.YYYY" (z.B. "20.11.1564" oder "00.03.1616")
        
        Returns:
            Datum im ISO-Format "YYYY-MM-DD" (z.B. "1564-11-20" oder "1616-03-00")
            oder None bei ungültigem Format
        """
        if not datum:
            return None
        
        # Parse DD.MM.YYYY Format
        match = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', datum)
        if match:
            tag, monat, jahr = match.groups()
            return f"{jahr}-{monat}-{tag}"
        
        return None
    
    def parse_header(self, text: str) -> Dict[str, Optional[str]]:
        """
        Parst den Header einer Karteikarte.
        
        Beispiel: "ev. Kb. Wetzlar ∞ 1564.11.20 p. 87. Nr. 1"
        
        Returns:
            Dictionary mit geparsten Feldern
        """
        result = {
            'kirchengemeinde': None,
            'ereignis_typ': None,
            'jahr': None,
            'datum': None,
            'iso_datum': None,
            'seite': None,
            'nummer': None
        }
        
        # Kirchengemeinde (z.B. "ev. Kb. Wetzlar")
        kb_match = re.search(r'(ev\.\s*Kb\.\s*\w+)', text, re.IGNORECASE)
        if kb_match:
            result['kirchengemeinde'] = kb_match.group(1).strip()
        
        # Ereignistyp (∞ = Heirat, ⚰/† = Begräbnis, etc.)
        if '∞' in text or 'Heirat' in text or 'hielten Hochzeit' in text:
            result['ereignis_typ'] = 'Heirat'
        elif '⚰' in text or '†' in text or 'Begräbnis' in text or 'begraben' in text:
            result['ereignis_typ'] = 'Begräbnis'
        elif '~' in text or 'Taufe' in text or 'getauft' in text:
            result['ereignis_typ'] = 'Taufe'
        
        # Datum (YYYY.MM.DD oder YYYY-MM-DD)
        date_match = re.search(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', text)
        if date_match:
            year, month, day = date_match.groups()
            result['jahr'] = int(year)
            
            # NEU: Wenn Tag = 00, dann nur Monat bekannt
            if day == '00':
                result['datum'] = f"00.{month.zfill(2)}.{year}"
                result['iso_datum'] = f"{year}-{month.zfill(2)}-00"
            else:
                result['datum'] = f"{day.zfill(2)}.{month.zfill(2)}.{year}"
                result['iso_datum'] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        else:
            # Nur Jahr - erweitert um 1600-1699
            year_match = re.search(r'\b(1[456]\d{2})\b', text)
            if year_match:
                result['jahr'] = int(year_match.group(1))
        
        # Seite (z.B. "p. 87" oder "S. 87")
        page_match = re.search(r'[pPS]\.\s*(\d+)', text)
        if page_match:
            result['seite'] = page_match.group(1)
        
        # Nummer (z.B. "Nr. 1" oder "No. 1")
        num_match = re.search(r'(?:Nr|No)\.\s*(\d+)', text, re.IGNORECASE)
        if num_match:
            result['nummer'] = num_match.group(1)
        
        return result
    
    def save_karteikarte(self, dateiname: str, dateipfad: str, erkannter_text: str,
                        ocr_methode: str = 'cloud_vision', skip_if_exists: bool = False,
                        vorname: str = None, nachname: str = None, partner: str = None, beruf: str = None, todestag: str = None, ort: str = None,
                        geb_jahr_gesch: int = None,
                        braeutigam_vater: str = None, braut_vater: str = None, braut_nachname: str = None, braut_ort: str = None,
                        kirchenbuchtext: str = None) -> int:
        """
        Speichert eine Karteikarte in der Datenbank.
        
        Args:
            dateiname: Name der Bilddatei
            dateipfad: Vollständiger Pfad zur Datei
            erkannter_text: Der von OCR erkannte Text
            ocr_methode: Verwendete OCR-Methode
            skip_if_exists: Wenn True, wird nichts getan wenn Eintrag bereits existiert (kein Update)
            vorname, nachname, partner, beruf, todestag, ort: Extrahierte Felder
            braeutigam_vater, braut_vater, braut_nachname, braut_ort: Zusätzliche Felder für Heiraten
        Returns:
            ID des eingefügten/aktualisierten Datensatzes, oder None wenn übersprungen
        """
        # Parse den Header
        parsed = self.parse_header(erkannter_text)
        cursor = self.conn.cursor()
        # Prüfe ob bereits vorhanden (Update statt Insert)
        cursor.execute("SELECT id FROM karteikarten WHERE dateipfad = ?", (dateipfad,))
        existing = cursor.fetchone()
        if existing:
            if skip_if_exists:
                return None
            cursor.execute("""
                UPDATE karteikarten SET
                    dateiname = ?,
                    kirchengemeinde = ?,
                    ereignis_typ = ?,
                    jahr = ?,
                    datum = ?,
                    iso_datum = ?,
                    seite = ?,
                    nummer = ?,
                    erkannter_text = ?,
                    ocr_methode = ?,
                    vorname = ?,
                    nachname = ?,
                    partner = ?,
                    beruf = ?,
                    todestag = ?,
                    ort = ?,
                    geb_jahr_gesch = ?,
                    braeutigam_vater = ?,
                    braut_vater = ?,
                    braut_nachname = ?,
                    braut_ort = ?,
                    kirchenbuchtext = ?,
                    aktualisiert_am = CURRENT_TIMESTAMP
                WHERE dateipfad = ?
            """, (
                dateiname, parsed['kirchengemeinde'], parsed['ereignis_typ'],
                parsed['jahr'], parsed['datum'], parsed['iso_datum'], parsed['seite'], parsed['nummer'],
                erkannter_text, ocr_methode,
                vorname, nachname, partner, beruf, todestag, ort,
                geb_jahr_gesch,
                braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                kirchenbuchtext,
                dateipfad
            ))
            # Hinweis: notiz und gramps werden absichtlich NICHT überschrieben bei Updates
            self.conn.commit()
            return existing[0]
        else:
            cursor.execute("""
                INSERT INTO karteikarten (
                    dateiname, dateipfad, kirchengemeinde, ereignis_typ,
                    jahr, datum, iso_datum, seite, nummer, erkannter_text, ocr_methode,
                    vorname, nachname, partner, beruf, todestag, ort,
                    geb_jahr_gesch,
                    braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                    kirchenbuchtext
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dateiname, dateipfad, parsed['kirchengemeinde'], parsed['ereignis_typ'],
                parsed['jahr'], parsed['datum'], parsed['iso_datum'], parsed['seite'], parsed['nummer'],
                erkannter_text, ocr_methode,
                vorname, nachname, partner, beruf, todestag, ort,
                geb_jahr_gesch,
                braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                kirchenbuchtext
            ))
            self.conn.commit()
            return cursor.lastrowid
    
    def search_by_year(self, year: int) -> List[Dict]:
        """Sucht Karteikarten nach Jahr."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM karteikarten 
            WHERE jahr = ? 
            ORDER BY datum, nummer
        """, (year,))
        return [dict(row) for row in cursor.fetchall()]
    
    def search_by_name(self, name: str) -> List[Dict]:
        """Sucht Karteikarten nach Namen im Text."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM karteikarten 
            WHERE erkannter_text LIKE ? 
            ORDER BY jahr, datum
        """, (f'%{name}%',))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_all_years(self) -> List[int]:
        """Gibt alle vorhandenen Jahre zurück."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT jahr FROM karteikarten 
            WHERE jahr IS NOT NULL 
            ORDER BY jahr
        """)
        return [row[0] for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict:
        """Gibt Statistiken über die Datenbank zurück."""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Gesamtanzahl
        cursor.execute("SELECT COUNT(*) FROM karteikarten")
        stats['gesamt'] = cursor.fetchone()[0]
        
        # Nach Ereignistyp
        cursor.execute("""
            SELECT ereignis_typ, COUNT(*) 
            FROM karteikarten 
            GROUP BY ereignis_typ
        """)
        stats['nach_typ'] = dict(cursor.fetchall())
        
        # Jahresspanne
        cursor.execute("""
            SELECT MIN(jahr), MAX(jahr) 
            FROM karteikarten 
            WHERE jahr IS NOT NULL
        """)
        min_jahr, max_jahr = cursor.fetchone()
        stats['zeitraum'] = f"{min_jahr or '?'} - {max_jahr or '?'}"
        
        return stats
    
    def export_to_csv(self, output_path: str):
        """Exportiert alle Karteikarten als CSV."""
        import csv
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM karteikarten ORDER BY jahr, datum, nummer")
        rows = cursor.fetchall()
        
        if not rows:
            return
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Header
            writer.writerow([description[0] for description in cursor.description])
            # Daten
            writer.writerows(rows)
    
    def import_from_csv(self, csv_path: str, preserve_ids: bool = True) -> Tuple[int, int, int]:
        """
        Importiert Karteikarten aus einer CSV-Datei.
        
        Args:
            csv_path: Pfad zur CSV-Datei
            preserve_ids: Wenn True, werden Original-IDs aus CSV übernommen
            
        Returns:
            Tuple (erfolge, aktualisiert, fehler)
        """
        import csv
        
        erfolge = 0
        aktualisiert = 0
        fehler = 0
        
        cursor = self.conn.cursor()
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                try:
                    # Extrahiere Werte
                    original_id = row.get('id')
                    dateiname = row.get('dateiname', '')
                    dateipfad = row.get('dateipfad', '')
                    kirchengemeinde = row.get('kirchengemeinde')
                    ereignis_typ = row.get('ereignis_typ')
                    jahr = row.get('jahr')
                    datum = row.get('datum')
                    iso_datum = row.get('iso_datum')
                    seite = row.get('seite')
                    nummer = row.get('nummer')
                    erkannter_text = row.get('erkannter_text', '')
                    ocr_methode = row.get('ocr_methode', 'imported')
                    notiz = row.get('notiz')
                    
                    # Extrahierte Felder
                    vorname = row.get('vorname')
                    nachname = row.get('nachname')
                    partner = row.get('partner')
                    stand = row.get('stand')
                    beruf = row.get('beruf')
                    todestag = row.get('todestag')
                    ort = row.get('ort')
                    geb_jahr_gesch = row.get('geb_jahr_gesch')
                    
                    # Heiratsfelder
                    braeutigam_stand = row.get('braeutigam_stand')
                    braeutigam_vater = row.get('braeutigam_vater')
                    braut_vater = row.get('braut_vater')
                    braut_nachname = row.get('braut_nachname')
                    braut_ort = row.get('braut_ort')
                    
                    # Kirchenbuchtext
                    kirchenbuchtext = row.get('kirchenbuchtext')
                    
                    if not dateipfad or not erkannter_text:
                        fehler += 1
                        continue
                    
                    # Konvertiere Jahr zu int falls möglich
                    jahr_int = int(jahr) if jahr and jahr != '' else None
                    
                    # Prüfe ob bereits vorhanden (nach dateipfad)
                    cursor.execute("SELECT id FROM karteikarten WHERE dateipfad = ?", (dateipfad,))
                    existing = cursor.fetchone()
                    
                    if existing:
                        # Update bestehender Eintrag
                        cursor.execute("""
                            UPDATE karteikarten SET
                                dateiname = ?,
                                kirchengemeinde = ?,
                                ereignis_typ = ?,
                                jahr = ?,
                                datum = ?,
                                iso_datum = ?,
                                seite = ?,
                                nummer = ?,
                                erkannter_text = ?,
                                ocr_methode = ?,
                                notiz = ?,
                                gramps = ?,
                                vorname = ?,
                                nachname = ?,
                                partner = ?,
                                stand = ?,
                                beruf = ?,
                                todestag = ?,
                                ort = ?,
                                geb_jahr_gesch = ?,
                                braeutigam_stand = ?,
                                braeutigam_vater = ?,
                                braut_vater = ?,
                                braut_nachname = ?,
                                braut_ort = ?,
                                kirchenbuchtext = ?,
                                aktualisiert_am = CURRENT_TIMESTAMP
                            WHERE dateipfad = ?
                        """, (dateiname, kirchengemeinde, ereignis_typ, jahr_int, datum, iso_datum,
                              seite, nummer, erkannter_text, ocr_methode, notiz, row.get('gramps'),
                              vorname, nachname, partner, stand, beruf, todestag, ort,
                              geb_jahr_gesch,
                              braeutigam_stand, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                              kirchenbuchtext,
                              dateipfad))
                        aktualisiert += 1
                    else:
                        # Neuer Eintrag
                        if preserve_ids and original_id:
                            # Mit spezifischer ID einfügen
                            cursor.execute("""
                                INSERT INTO karteikarten (
                                    id, dateiname, dateipfad, kirchengemeinde, ereignis_typ,
                                    jahr, datum, iso_datum, seite, nummer, erkannter_text, ocr_methode, notiz, gramps,
                                    vorname, nachname, partner, stand, beruf, todestag, ort, geb_jahr_gesch,
                                    braeutigam_stand, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                                    kirchenbuchtext
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (int(original_id), dateiname, dateipfad, kirchengemeinde, ereignis_typ,
                                  jahr_int, datum, iso_datum, seite, nummer, erkannter_text, ocr_methode, notiz, row.get('gramps'),
                                  vorname, nachname, partner, stand, beruf, todestag, ort, geb_jahr_gesch,
                                  braeutigam_stand, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                                  kirchenbuchtext))
                        else:
                            # Automatische ID-Vergabe
                            cursor.execute("""
                                INSERT INTO karteikarten (
                                    dateiname, dateipfad, kirchengemeinde, ereignis_typ,
                                    jahr, datum, iso_datum, seite, nummer, erkannter_text, ocr_methode, notiz, gramps,
                                    vorname, nachname, partner, stand, beruf, todestag, ort, geb_jahr_gesch,
                                    braeutigam_stand, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                                    kirchenbuchtext
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (dateiname, dateipfad, kirchengemeinde, ereignis_typ,
                                  jahr_int, datum, iso_datum, seite, nummer, erkannter_text, ocr_methode, notiz, row.get('gramps'),
                                  vorname, nachname, partner, stand, beruf, todestag, ort, geb_jahr_gesch,
                                  braeutigam_stand, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                                  kirchenbuchtext))
                        erfolge += 1
                        
                except Exception as e:
                    fehler += 1
                    print(f"Fehler bei Zeile (dateipfad: {row.get('dateipfad', '?')}): {str(e)}")
        
        self.conn.commit()
        return (erfolge, aktualisiert, fehler)
    
    def close(self):
        """Schließt die Datenbankverbindung."""
        if self.conn:
            self.conn.close()
    
    def __del__(self):
        """Destruktor - schließt die Verbindung."""
        self.close()
