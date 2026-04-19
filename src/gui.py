"""Grafische Benutzeroberfläche für die Karteikartenerkennung."""

import csv
import json
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

from PIL import Image, ImageTk

from .config import get_config
from .database import KarteikartenDB
from .extraction_lists import SOURCES
from .extractor import (extract_baptism_fields, extract_burial_fields,
                        extract_kirchenbuch_titel, extract_marriage_fields,
                        is_valid_date)
from .gedcom_exporter import GedcomExporter
from .ocr_engine import OCREngine
from .online_sync import OnlineSyncService
from .text_postprocessor import (fix_header_prefix, fix_infinity_year,
                                 fix_p_number, fix_wetzlar_infinity,
                                 format_citation, insert_burial_symbol,
                                 insert_marriage_symbol,
                                 replace_ev_kb_wetzlar_special,
                                 standardize_p_nr)
from .xlsx_importer import run_xlsx_import


class KarteikartenGUI:
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
        
        # Online-Sync Service
        self._sync_service = OnlineSyncService()
        self._sync_service.start_background(self.db)
        self._sync_status_var: tk.StringVar  # wird in _create_settings_content gesetzt

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

    def _run_recognition_selected(self):
        """Führt die strukturierte Erkennung für die ausgewählten Datensätze im Datenbank-Tab durch (unterscheidet Typ Begräbnis/Hochzeit)."""
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
                fields = extract_burial_fields(text)
                
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
                            vorname = ?, nachname = ?, partner = ?, beruf = ?, stand = ?, todestag = ?, ort = ?, geb_jahr_gesch = ?,
                            version = COALESCE(version, 1) + 1, sync_status = 'pending', updated_by = 'erkennung',
                            aktualisiert_am = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (vorname, nachname, partner, beruf, stand, todestag, ort, geb_jahr_gesch, record_id))
                    self.db.conn.commit()
                    self.db.mark_record_for_sync(record_id)
                    updated += 1
                except Exception as e:
                    errors.append(f"ID {record_id}: Fehler beim Speichern: {e}")
            else:
                # --- Taufe-Erkennung ---
                is_taufe = (
                    (typ and typ.lower() in ('taufe', 'geburt'))
                    or re.search(r'ev\.?\s*Kb\.?\s*\w+\s*\*\s*\d{4}', text) is not None
                )
                if is_taufe:
                    fields = extract_baptism_fields(text)
                    try:
                        cursor.execute("""
                            UPDATE karteikarten SET
                                vorname = ?, nachname = ?, partner = ?,
                                mutter_vorname = ?, datum_geburt = ?, todestag = ?,
                                seite = ?, nummer = ?,
                                version = COALESCE(version, 1) + 1, sync_status = 'pending', updated_by = 'erkennung',
                                aktualisiert_am = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (
                            fields['vorname'], fields['nachname'], fields['partner'],
                            fields['mutter_vorname'], fields['datum_geburt'], fields['todestag'],
                            fields.get('seite'), fields.get('nummer'),
                            record_id
                        ))
                        self.db.conn.commit()
                        self.db.mark_record_for_sync(record_id)
                        updated += 1
                    except Exception as e:
                        errors.append(f"ID {record_id}: Fehler beim Speichern: {e}")
                # --- Heirats-Erkennung ---
                elif typ and (typ.lower().startswith('heirat') or '∞' in text):
                    # Nutze spezialisierte Heirats-Extraktion
                    fields = extract_marriage_fields(text)
                    
                    # Speichern
                    try:
                        cursor.execute("""
                            UPDATE karteikarten SET
                                vorname = ?, nachname = ?, partner = ?, beruf = ?, ort = ?, stand = ?,
                                braeutigam_stand = ?, braeutigam_vater = ?, braut_vater = ?, braut_nachname = ?, braut_ort = ?,
                                todestag = ?,
                                version = COALESCE(version, 1) + 1, sync_status = 'pending', updated_by = 'erkennung',
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
                        self.db.mark_record_for_sync(record_id)
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

        # Hole den aktuellen Text
        text = self.text_display.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Kein Text", "Bitte zuerst Text erkennen oder eingeben.")
            return
        
        # Setze alle Felder zurück
        self._clear_ocr_field_labels()

        # --- Taufe-Erkennung: ev. Kb. Wetzlar * YYYY ---
        is_taufe = bool(re.search(r'ev\.?\s*Kb\.?\s*\w+\s*\*\s*\d{4}', text))

        # Erkenne den Typ (Begräbnis ⚰ oder Heirat ∞)
        is_heirat = '∞' in text
        is_begraebnis = '⚰' in text or '\u26B0' in text

        # Falls beide Symbole oder keines vorhanden, versuche anhand Keywords zu erkennen
        if not is_taufe and ((is_heirat and is_begraebnis) or (not is_heirat and not is_begraebnis)):
            if 'begraben' in text.lower() or 'begr' in text.lower():
                is_begraebnis = True
                is_heirat = False
            elif 'heirat' in text.lower() or 'getraut' in text.lower() or 'und' in text.lower():
                is_heirat = True
                is_begraebnis = False

        # --- TAUFE-ERKENNUNG ---
        if is_taufe:
            fields = extract_baptism_fields(text)

            self._set_ocr_field_value('vorname', fields.get('vorname'))
            self._set_ocr_field_value('nachname', fields.get('nachname'))
            self._set_ocr_field_value('partner', fields.get('partner'))
            if 'mutter vorname' in self.ocr_field_labels:
                self._set_ocr_field_value('mutter vorname', fields.get('mutter_vorname'))
            if 'datum geburt' in self.ocr_field_labels:
                self._set_ocr_field_value('datum geburt', fields.get('datum_geburt'))
            if 'todestag' in self.ocr_field_labels:
                self._set_ocr_field_value('todestag', fields.get('todestag'))
            if 'seite' in self.ocr_field_labels and fields.get('seite'):
                self._set_ocr_field_value('seite', str(fields.get('seite')))
            if 'nummer' in self.ocr_field_labels and fields.get('nummer'):
                self._set_ocr_field_value('nummer', str(fields.get('nummer')))

            self._last_recognized_fields = fields
            self.db_record_status.config(text="", foreground="blue")
            messagebox.showinfo("Erkennung", "Taufe-Felder erkannt.")
            return

        # --- HEIRAT-ERKENNUNG ---
        if is_heirat:
            result = extract_marriage_fields(text)
            
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
        fields = extract_burial_fields(text)
        
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

    def _fill_kb_text_from_ocr(self):
        """Kopiert den erkannten Text nach der Nr.-Zahl in das Kirchenbuchtext-Feld."""
        full_text = self.text_display.get("1.0", tk.END).strip()
        match = re.search(r'Nr\.\s*\d+\s*', full_text)
        remainder = full_text[match.end():].strip() if match else full_text
        self.kirchenbuch_text_display.delete("1.0", tk.END)
        self.kirchenbuch_text_display.insert("1.0", remainder)

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
            mutter_vorname = self._get_ocr_field_value('mutter vorname')
            datum_geburt = self._get_ocr_field_value('datum geburt')
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
                        mutter_vorname = ?, datum_geburt = ?,
                        kirchenbuchtext = ?,
                        notiz = ?,
                        gramps = ?,
                        version = COALESCE(version, 1) + 1, sync_status = 'pending', updated_by = 'erkennung',
                        aktualisiert_am = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    vorname, nachname, partner,
                    beruf, braut_stand or stand, ort, seite, nummer,
                    braeutigam_stand, braeutigam_vater, braut_vater,
                    braut_nachname, braut_ort,
                    mutter_vorname, datum_geburt,
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
                        mutter_vorname = ?, datum_geburt = ?,
                        kirchenbuchtext = ?,
                        notiz = ?,
                        gramps = ?,
                        version = COALESCE(version, 1) + 1, sync_status = 'pending', updated_by = 'erkennung',
                        aktualisiert_am = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    vorname, nachname, partner,
                    beruf, stand, todestag, ort, seite, nummer,
                    geb_jahr_gesch,
                    mutter_vorname, datum_geburt,
                    kirchenbuchtext,
                    fid,
                    gramps,
                    self.current_db_record_id
                ))
            
            self.db.conn.commit()
            self.db.mark_record_for_sync(self.current_db_record_id)
            
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
            f"{media_id_prefix}* S_{seite_str_4}_*.jpg",
            f"{media_id_prefix}* S_*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4} Sterbebuch.jpg",
            # 3-stellige Varianten - mit Trennzeichen um False Positives zu vermeiden
            f"{media_id_prefix}* S_{seite_str_3}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_3}.jpg",
            f"{media_id_prefix}* S_{seite_str_3}_*.jpg",
            f"{media_id_prefix}* S_*_{seite_str_3}.jpg",
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
        # Menüleiste
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Über…", command=self._show_about)
        menubar.add_cascade(label="Hilfe", menu=help_menu)
        self.root.config(menu=menubar)

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

    def _show_about(self):
        """Zeigt den 'Über'-Dialog mit Versionsnummer."""
        win = tk.Toplevel(self.root)
        win.title("Über Wetzlar Karteikartenerkennung")
        win.resizable(False, False)
        win.grab_set()
        tk.Label(win, text="Wetzlar Karteikartenerkennung",
                 font=("TkDefaultFont", 13, "bold")).pack(padx=30, pady=(20, 4))
        tk.Label(win, text="Version 0.4.1").pack(padx=30)
        tk.Label(win, text="© 2026 – Wetzlar Projekt",
                 foreground="gray").pack(padx=30, pady=(4, 16))
        tk.Button(win, text="OK", width=10,
                  command=win.destroy).pack(pady=(0, 20))
        win.bind("<Return>", lambda _e: win.destroy())
        win.bind("<Escape>", lambda _e: win.destroy())

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
        
        # Label für Bildanzeige – Höhe fest begrenzen, damit Buttons nicht herausgedrückt werden
        image_frame = ttk.Frame(left_frame, height=420)
        image_frame.pack(fill=tk.X, expand=False)
        image_frame.pack_propagate(False)

        self.image_label = ttk.Label(image_frame, text="Karteikarte wird geladen...",
                                     relief=tk.SUNKEN, anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # Navigationsbuttons - ZEILE 1: Bild-Navigation
        nav_frame_1 = ttk.Frame(left_frame)
        nav_frame_1.pack(fill=tk.X, pady=(10, 5))
        
        self.prev_btn = ttk.Button(nav_frame_1, text="◀ Vorherige", command=self._previous_card)
        self.prev_btn.pack(side=tk.LEFT, padx=5)

        # Sprung zu Karte Nr.
        ttk.Label(nav_frame_1, text="Nr:").pack(side=tk.LEFT, padx=(10, 2))
        self.jump_var = tk.StringVar()
        jump_entry = ttk.Entry(nav_frame_1, textvariable=self.jump_var, width=6)
        jump_entry.pack(side=tk.LEFT, padx=(0, 2))
        jump_entry.bind("<Return>", lambda e: self._jump_to_card())
        ttk.Button(nav_frame_1, text="→", width=3, command=self._jump_to_card).pack(side=tk.LEFT, padx=(0, 10))

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
        
        self.ocr_btn = ttk.Button(nav_frame_2, text="🔍 Text erkennen", command=self._run_ocr)
        self.ocr_btn.pack(side=tk.LEFT, padx=5)

        self.register_btn = ttk.Button(nav_frame_2, text="📋 Registrieren (ohne OCR)", command=self._batch_register_files)
        self.register_btn.pack(side=tk.LEFT, padx=2)

        # Batch-Scan Frame
        batch_frame = ttk.Frame(nav_frame_2)
        batch_frame.pack(side=tk.LEFT, padx=5)

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
        
        # Button zum Belegen des Kirchenbuchtext-Felds aus dem erkannten Text
        fill_kb_btn = ttk.Button(action_buttons_frame, text="Kb Text belegen", command=self._fill_kb_text_from_ocr)
        fill_kb_btn.pack(side=tk.LEFT, padx=5)

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
                      "Seite:", "Nummer:", "Todestag:", "Geb.Jahr (gesch.):", "Bräutigam Stand:", "Bräutigam Vater:", "Braut Vater:", "Braut Nachname:", "Braut Ort:",
                      "Mutter Vorname:", "Datum Geburt:"]
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
        ttk.Label(filter_row2, text="Text:").pack(side=tk.LEFT, padx=5)
        self.name_search = ttk.Entry(filter_row2, width=20)
        self.name_search.pack(side=tk.LEFT, padx=5)
        # Enter-Taste im Namens-Suchfeld löst Suche aus
        self.name_search.bind('<Return>', lambda e: self._refresh_db_list())

        ttk.Label(filter_row2, text="Partner Vorname:").pack(side=tk.LEFT, padx=(10, 5))
        self.partner_vorname_search = ttk.Entry(filter_row2, width=16)
        self.partner_vorname_search.pack(side=tk.LEFT, padx=5)
        self.partner_vorname_search.bind('<Return>', lambda e: self._refresh_db_list())

        ttk.Label(filter_row2, text="Nachname:").pack(side=tk.LEFT, padx=(10, 5))
        self.nachname_search = ttk.Entry(filter_row2, width=16)
        self.nachname_search.pack(side=tk.LEFT, padx=5)
        self.nachname_search.bind('<Return>', lambda e: self._refresh_db_list())

        ttk.Label(filter_row2, text="Braut Vorname:").pack(side=tk.LEFT, padx=(10, 5))
        self.braut_vorname_search = ttk.Entry(filter_row2, width=16)
        self.braut_vorname_search.pack(side=tk.LEFT, padx=5)
        self.braut_vorname_search.bind('<Return>', lambda e: self._refresh_db_list())

        ttk.Label(filter_row2, text="Braut Nachname:").pack(side=tk.LEFT, padx=(10, 5))
        self.braut_nachname_search = ttk.Entry(filter_row2, width=16)
        self.braut_nachname_search.pack(side=tk.LEFT, padx=5)
        self.braut_nachname_search.bind('<Return>', lambda e: self._refresh_db_list())

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
                        cursor.execute(
                            "UPDATE karteikarten SET erkannter_text = ?, "
                            "version = COALESCE(version, 1) + 1, sync_status = 'pending', updated_by = 'erkennung', "
                            "aktualisiert_am = CURRENT_TIMESTAMP WHERE id = ?",
                            (new_text, record_id))
                        erfolge += 1
                except Exception as e:
                    fehler += 1
                    print(f"Fehler bei ID {record_id}: {str(e)}")
            self.db.conn.commit()
            for item in self.tree.selection():
                rid = self.tree.item(item)["values"][0]
                try:
                    self.db.mark_record_for_sync(int(rid))
                except Exception:
                    pass
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
            'Bräutigam Stand', 'Braut Stand', 'Mutter Vorname', 'Datum Geburt', 'Todestag', 'Geb.Jahr (gesch.)',
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
        self.tree.heading('Mutter Vorname', text='Mutter Vorname', command=lambda: self._sort_column('Mutter Vorname'))
        self.tree.heading('Datum Geburt', text='Datum Geburt', command=lambda: self._sort_column('Datum Geburt'))
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
        self.tree.column('Mutter Vorname', width=100, anchor='w')
        self.tree.column('Datum Geburt', width=80, anchor='w')
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
        self.tree_menu.add_command(label="GEDCOM (GRAMPS) exportieren (Auswahl)", command=self._export_gedcom_selected_from_context)
        self.tree_menu.add_command(label="GEDCOM (TNG) exportieren (Auswahl)", command=self._export_gedcom_tng_selected_from_context)
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
        ttk.Button(button_row1, text="🔒 Full Backup", command=self._export_full_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="↩️ Restore", command=self._import_full_backup).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="🌳 GEDCOM (GRAMPS)", command=self._export_gedcom).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="🌐 GEDCOM (TNG)", command=self._export_gedcom_tng).pack(side=tk.LEFT, padx=3)
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
        """Erstellt den Einstellungen-Tab Inhalt (scrollbar)."""
        # Scrollbarer Container
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        main_frame = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=main_frame, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        main_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Innenabstand
        main_frame = ttk.Frame(main_frame, padding=(20, 20))
        main_frame.pack(fill=tk.BOTH, expand=True)

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
        
        # === Online-Sync Einstellungen ===
        sync_frame = ttk.LabelFrame(main_frame, text="🌐 Online-Synchronisation", padding=15)
        sync_frame.pack(fill=tk.X, pady=(0, 20))

        cfg = self.config.online_sync

        # Aktivieren/Deaktivieren
        self._sync_enabled_var = tk.BooleanVar(value=bool(cfg.get("enabled", False)))
        ttk.Checkbutton(
            sync_frame, text="Online-Sync aktivieren",
            variable=self._sync_enabled_var
        ).pack(anchor=tk.W, pady=(0, 8))

        # Quelle dieser Instanz
        src_row = ttk.Frame(sync_frame)
        src_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(src_row, text="Diese Instanz ist:", width=20).pack(side=tk.LEFT)
        self._sync_source_var = tk.StringVar(value=cfg.get("source", "erkennung"))
        ttk.Radiobutton(src_row, text="Erkennung", variable=self._sync_source_var, value="erkennung").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(src_row, text="Reader", variable=self._sync_source_var, value="reader").pack(side=tk.LEFT, padx=4)

        mode_row = ttk.Frame(sync_frame)
        mode_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(mode_row, text="Sync-Modus:", width=20).pack(side=tk.LEFT)
        self._sync_mode_var = tk.StringVar(value=cfg.get("mode", "mysql"))
        mode_box = ttk.Combobox(mode_row, textvariable=self._sync_mode_var, values=["mysql", "api"], width=15, state="readonly")
        mode_box.pack(side=tk.LEFT, padx=4)

        sync_style = ttk.Style(self.root)
        sync_style.configure("SyncInvalid.TEntry", foreground="#a00000", fieldbackground="#ffe6e6")

        # Verbindungs-Felder
        def _lbl_entry(parent, label, var, show="", hint=""):
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, width=22).pack(side=tk.LEFT)
            e = ttk.Entry(row, textvariable=var, show=show)
            e.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if hint:
                ttk.Label(row, text=hint, foreground="gray", font=("Arial", 8, "italic")).pack(side=tk.LEFT, padx=(6, 0))
            return e

        # --- MySQL-Felder (nur relevant im Modus "mysql") ---
        self._mysql_fields_frame = ttk.Frame(sync_frame)
        self._mysql_fields_frame.pack(fill=tk.X)
        ttk.Label(self._mysql_fields_frame,
                  text="▸ Modus mysql: direkte Verbindung (nur VPS / lokales Netz)",
                  foreground="#666", font=("Arial", 8, "italic")).pack(anchor=tk.W, pady=(6, 2))

        self._sync_host_var = tk.StringVar(value=cfg.get("db_host", ""))
        self._sync_port_var = tk.StringVar(value=str(cfg.get("db_port", 3306)))
        self._sync_user_var = tk.StringVar(value=cfg.get("db_user", ""))
        self._sync_pw_var = tk.StringVar(value=cfg.get("db_password", ""))
        self._sync_db_var = tk.StringVar(value=cfg.get("db_name", ""))

        _lbl_entry(self._mysql_fields_frame, "DB-Host:", self._sync_host_var,
                   hint="z.B. 192.168.1.10 (nur für mysql-Modus, nicht für Lima-City)")
        _lbl_entry(self._mysql_fields_frame, "DB-Port:", self._sync_port_var, hint="Standard: 3306")
        _lbl_entry(self._mysql_fields_frame, "DB-Benutzer:", self._sync_user_var)
        _lbl_entry(self._mysql_fields_frame, "DB-Passwort:", self._sync_pw_var, show="*")
        _lbl_entry(self._mysql_fields_frame, "DB-Name:", self._sync_db_var)

        # --- API-Felder (Modus "api", z.B. Lima-City) ---
        ttk.Label(sync_frame,
                  text="▸ Modus api: PHP-Datei auf Webspace (z.B. Lima-City) → URL unten eintragen",
                  foreground="#0055aa", font=("Arial", 8, "italic")).pack(anchor=tk.W, pady=(10, 2))

        self._sync_interval_var = tk.StringVar(value=str(cfg.get("sync_interval_seconds", 20)))
        self._sync_endpoint_var = tk.StringVar(value=cfg.get("endpoint_url", ""))
        self._sync_api_key_var = tk.StringVar(value=cfg.get("api_key", ""))

        self._sync_endpoint_entry = _lbl_entry(sync_frame, "API-Endpoint:", self._sync_endpoint_var,
                                               hint="https://deine-domain.de/sync/lima_sync_endpoint.php")
        self._sync_endpoint_hint_var = tk.StringVar(value="")
        ttk.Label(sync_frame, textvariable=self._sync_endpoint_hint_var,
                  foreground="#8a5a00", font=("Arial", 8, "italic")).pack(anchor=tk.W, padx=(160, 0), pady=(0, 2))
        _lbl_entry(sync_frame, "API-Key:", self._sync_api_key_var, show="*",
                   hint="wie in lima_sync_endpoint.php eingetragen")
        _lbl_entry(sync_frame, "Intervall (Sek):", self._sync_interval_var)

        def _validate_endpoint_field(*_):
            raw_url = self._sync_endpoint_var.get().strip()
            if not raw_url:
                self._sync_endpoint_entry.configure(style="TEntry")
                self._sync_endpoint_hint_var.set("")
                return

            normalized = self._normalize_endpoint_url(raw_url)
            parts = urlsplit(normalized)
            is_valid = bool(parts.netloc)

            if is_valid:
                self._sync_endpoint_entry.configure(style="TEntry")
                if normalized != raw_url:
                    self._sync_endpoint_hint_var.set(f"Wird als {normalized} gespeichert")
                else:
                    self._sync_endpoint_hint_var.set("")
            else:
                self._sync_endpoint_entry.configure(style="SyncInvalid.TEntry")
                self._sync_endpoint_hint_var.set("Ungültige URL. Beispiel: https://wze.de.cool/lima_sync_endpoint.php")

        def _on_mode_change(*_):
            if self._sync_mode_var.get() == "mysql":
                self._mysql_fields_frame.pack(fill=tk.X, after=mode_row)
            else:
                self._mysql_fields_frame.pack_forget()

        self._sync_mode_var.trace_add("write", _on_mode_change)
        self._sync_endpoint_var.trace_add("write", _validate_endpoint_field)
        # Initial-Sichtbarkeit setzen
        _on_mode_change()
        _validate_endpoint_field()

        # Status + Buttons
        btn_row = ttk.Frame(sync_frame)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="💾 Speichern", command=self._save_sync_settings).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="🔄 Jetzt synchronisieren", command=self._sync_now_clicked).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="🔌 Verbindung testen", command=self._test_sync_connection).pack(side=tk.LEFT)

        self._sync_status_var = tk.StringVar(value="–")
        ttk.Label(sync_frame, textvariable=self._sync_status_var, foreground="blue").pack(anchor=tk.W, pady=(6, 0))
        self._update_sync_status()
    
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
    
    # ------------------------------------------------------------------ #
    #  Online-Sync Hilfsmethoden                                          #
    # ------------------------------------------------------------------ #

    def _normalize_endpoint_url(self, raw_url: str) -> str:
        """Normalisiert typische URL-Eingabefehler fuer den API-Endpunkt."""
        url = (raw_url or "").strip()
        if not url:
            return ""

        if "://" not in url:
            url = "https://" + url

        # Hauefige Tippfehler bei doppeltem/verkuerztem Schema korrigieren.
        url = url.replace("https://https://", "https://")
        url = url.replace("http://http://", "http://")
        url = url.replace("https://https:/", "https://")
        url = url.replace("http://http:/", "http://")
        if url.startswith("https:/") and not url.startswith("https://"):
            url = "https://" + url[len("https:/"):]
        if url.startswith("http:/") and not url.startswith("http://"):
            url = "http://" + url[len("http:/"):]

        parts = urlsplit(url)
        if not parts.netloc and parts.path:
            path = parts.path.lstrip("/")
            if "/" in path:
                host, rest = path.split("/", 1)
                if "." in host:
                    parts = parts._replace(netloc=host, path="/" + rest)
            elif "." in path:
                parts = parts._replace(netloc=path, path="")

        scheme = parts.scheme or "https"
        return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))

    def _save_sync_settings(self):
        """Speichert die Online-Sync-Konfiguration und startet ggf. den Dienst neu."""
        try:
            port = int(self._sync_port_var.get().strip() or "3306")
            interval = int(self._sync_interval_var.get().strip() or "20")
        except ValueError:
            messagebox.showwarning("Eingabefehler", "Port und Intervall müssen ganze Zahlen sein.")
            return

        endpoint_url = self._normalize_endpoint_url(self._sync_endpoint_var.get())
        self._sync_endpoint_var.set(endpoint_url)

        new_cfg = {
            "enabled": self._sync_enabled_var.get(),
            "mode": self._sync_mode_var.get().strip() or "mysql",
            "db_host": self._sync_host_var.get().strip(),
            "db_port": port,
            "db_user": self._sync_user_var.get().strip(),
            "db_password": self._sync_pw_var.get(),
            "db_name": self._sync_db_var.get().strip(),
            "endpoint_url": endpoint_url,
            "api_key": self._sync_api_key_var.get(),
            "source": self._sync_source_var.get(),
            "sync_interval_seconds": interval,
            "batch_size": self.config.online_sync.get("batch_size", 100),
        }
        self.config.set_online_sync(new_cfg)

        # Dienst neu starten
        self._sync_service.stop_background()
        self._sync_service = OnlineSyncService()
        self._sync_service.start_background(self.db)

        self._update_sync_status()
        messagebox.showinfo("Gespeichert", "Online-Sync-Einstellungen wurden gespeichert.")

    def _update_sync_status(self):
        """Aktualisiert das Status-Label im Einstellungen-Tab."""
        if not hasattr(self, "_sync_status_var"):
            return
        try:
            stats = self._sync_service.get_status()
            enabled = self.config.online_sync.get("enabled", False)
            if not enabled:
                self._sync_status_var.set("Status: Deaktiviert")
            else:
                mode = stats.get("mode", self.config.online_sync.get("mode", "mysql"))
                pending = stats.get("pending", 0)
                last = stats.get("last_sync", "–")
                self._sync_status_var.set(f"Status: Aktiv ({mode}) | Warteschlange: {pending} | Letzter Sync: {last}")
        except Exception as exc:
            self._sync_status_var.set(f"Status: Fehler – {exc}")
        # alle 5 Sekunden aktualisieren
        self.root.after(5000, self._update_sync_status)

    def _sync_now_clicked(self):
        """Manueller Sync-Aufruf."""
        try:
            result = self._sync_service.sync_now(self.db)
            self._update_sync_status()
            if result.failed or result.errors:
                details = "\n".join(result.errors[:5]) if result.errors else "Unbekannter Fehler"
                if len(result.errors) > 5:
                    details += "\n..."
                messagebox.showerror(
                    "Sync-Fehler",
                    f"Synchronisation fehlgeschlagen.\n"
                    f"Gepusht: {result.pushed}, Gepullt: {result.pulled}, Fehler: {result.failed}\n\n"
                    f"Details:\n{details}"
                )
                return

            if result.pushed == 0 and result.pulled == 0:
                messagebox.showwarning(
                    "Kein Transfer",
                    "Synchronisation ohne Übertragung abgeschlossen.\n"
                    "Es wurden keine Datensätze übertragen."
                )
                return

            messagebox.showinfo(
                "Sync",
                f"Synchronisation abgeschlossen.\n"
                f"Gepusht: {result.pushed}, Gepullt: {result.pulled}, Fehler: {result.failed}"
            )
        except Exception as exc:
            messagebox.showerror("Sync-Fehler", str(exc))

    def _test_sync_connection(self):
        """Testet die Verbindung im aktuell gewählten Sync-Modus."""
        mode = (self._sync_mode_var.get() or "mysql").strip().lower()
        if mode == "api":
            url = self._normalize_endpoint_url(self._sync_endpoint_var.get())
            self._sync_endpoint_var.set(url)
            if not url:
                messagebox.showwarning("Kein Endpoint",
                    "Bitte zuerst die API-Endpoint-URL eintragen.\n\n"
                    "Beispiel: https://deine-domain.de/sync/lima_sync_endpoint.php\n\n"
                    "Hinweis: mysql.lima-city.de ist der DB-Host, kein API-Endpoint.")
                return
            if not urlsplit(url).netloc:
                messagebox.showwarning(
                    "Ungültige URL",
                    "Der API-Endpoint ist ungültig.\n"
                    "Bitte vollständige URL angeben, z.B.\n"
                    "https://wze.de.cool/lima_sync_endpoint.php"
                )
                return
            try:
                from urllib import error, request
                from urllib.parse import urlencode
                json_str = json.dumps({
                    "action": "ping",
                    "api_key": self._sync_api_key_var.get(),
                }, ensure_ascii=False)
                payload = urlencode({"payload": json_str}).encode("utf-8")
                req = request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("ok") is False:
                    raise RuntimeError(str(data.get("error") if isinstance(data, dict) else "Ungültige API-Antwort"))
                server_time = data.get("server_time", "?")
                messagebox.showinfo("Verbindung OK",
                    f"API-Endpunkt ist erreichbar.\nServer-Zeit: {server_time}")
            except error.URLError as exc:
                messagebox.showerror("Verbindungsfehler",
                    f"API nicht erreichbar: {exc}\n\n"
                    "Prüfen Sie:\n"
                    "• Ist die PHP-Datei hochgeladen?\n"
                    "• Stimmt die URL?\n"
                    "• Ist mysql.lima-city.de eingetragen? → Das ist kein Webserver!\n"
                    "  Benötigt wird die URL zur PHP-Datei auf Ihrem Webspace.")
            except Exception as exc:
                messagebox.showerror("Verbindungsfehler", str(exc))
            return

        try:
            import pymysql  # type: ignore
            port = int(self._sync_port_var.get().strip() or "3306")
            conn = pymysql.connect(
                host=self._sync_host_var.get().strip(),
                port=port,
                user=self._sync_user_var.get().strip(),
                password=self._sync_pw_var.get(),
                database=self._sync_db_var.get().strip(),
                connect_timeout=5,
            )
            conn.close()
            messagebox.showinfo("Verbindung OK", "MySQL-Verbindung erfolgreich hergestellt.")
        except ImportError:
            messagebox.showerror(
                "Fehlendes Paket",
                "pymysql ist nicht installiert.\nBitte ausführen:\n  pip install pymysql"
            )
        except Exception as exc:
            messagebox.showerror("Verbindungsfehler", str(exc))

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
    
    def _apply_text_transform_selected(self, fn, title, description, ocr_methode, confirm=True):
        """Wendet eine Texttransformation auf alle ausgewählten DB-Einträge an."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return
        count = len(selection)
        if confirm and not messagebox.askyesno(title,
                f"Möchten Sie die Korrektur auf {count} Einträge anwenden?\n\n{description}\n\nDie alten Texte werden überschrieben."):
            return
        erfolge = fehler = keine_aenderung = 0
        cursor = self.db.conn.cursor()
        for item in selection:
            record_id = self.tree.item(item)['values'][0]
            try:
                cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
                row = cursor.fetchone()
                if row:
                    original_text = row[0]
                    new_text = fn(original_text) if original_text else original_text
                    if new_text == original_text:
                        keine_aenderung += 1
                        continue
                    self.db.save_karteikarte(dateiname=row[1], dateipfad=row[2], erkannter_text=new_text, ocr_methode=ocr_methode)
                    erfolge += 1
            except Exception as e:
                fehler += 1
                print(f"Fehler bei ID {record_id}: {e}")
        self._refresh_db_list()
        messagebox.showinfo("Fertig", f"{title} abgeschlossen!\n\nErfolgreich geändert: {erfolge}\nKeine Änderung nötig: {keine_aenderung}\nFehler: {fehler}")

    def _standardize_p_nr_selected(self):
        self._apply_text_transform_selected(fn=standardize_p_nr, title="p/Nr. standardisieren",
            description="Varianten wie 'p. 95m. 24', 'p.118 n.1', 'Nr. .14' werden vereinheitlicht.",
            ocr_methode="standardize_p_nr")

    def _format_citation_selected(self):
        self._apply_text_transform_selected(fn=format_citation, title="Zitation formatieren",
            description="Format: 'ev. Kb. Wetzlar ⚰ YYYY.MM.DD. p. X Nr. Y'",
            ocr_methode="format_citation")

    def _fix_p_number_selected(self):
        self._apply_text_transform_selected(fn=fix_p_number, title="p(Zahl) → p. (Zahl) ersetzen",
            description="Alle 'p(Zahl)', 'p (Zahl)' oder 'P(Zahl)' werden durch 'p. (Zahl)' ersetzt.",
            ocr_methode="fix_p_number")

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
            f"{media_id_prefix}* S_{seite_str_4}_*.jpg",
            f"{media_id_prefix}* S_*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4} Sterbebuch.jpg",
            # 3-stellige Varianten - mit Trennzeichen um False Positives zu vermeiden
            f"{media_id_prefix}* S_{seite_str_3}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_3}.jpg",
            f"{media_id_prefix}* S_{seite_str_3}_*.jpg",
            f"{media_id_prefix}* S_*_{seite_str_3}.jpg",
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
        viewer.geometry("1200x800")

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
        from .text_postprocessor import TextPostProcessor

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
            partner_vorname_search = self.partner_vorname_search.get().strip()
            nachname_search = self.nachname_search.get().strip()
            braut_vorname_search = self.braut_vorname_search.get().strip()
            braut_nachname_search = self.braut_nachname_search.get().strip()

            query = (
                "SELECT id, jahr, datum, iso_datum, ereignis_typ, seite, nummer, kirchengemeinde, "
                "vorname, nachname, partner, beruf, ort, "
                "braeutigam_vater, braut_vater, braut_nachname, braut_ort, "
                "braeutigam_stand, stand, mutter_vorname, datum_geburt, todestag, geb_jahr_gesch, "
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

            if partner_vorname_search:
                query += " AND vorname LIKE ?"
                params.append(f'%{partner_vorname_search}%')

            if nachname_search:
                query += " AND nachname LIKE ?"
                params.append(f'%{nachname_search}%')

            if braut_vorname_search:
                query += " AND partner LIKE ?"
                params.append(f'%{braut_vorname_search}%')

            if braut_nachname_search:
                query += " AND braut_nachname LIKE ?"
                params.append(f'%{braut_nachname_search}%')


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
                try:
                    pattern = re.compile(name_search)
                except re.error as e:
                    messagebox.showerror("Regex-Fehler", f"Ungültiger regulärer Ausdruck:\n{e}")
                    self.db_status_label.config(text="0 Datensätze gefunden (Regex-Fehler)")
                    return
                # Filtere rows, bei denen erkannter_text auf das Pattern matcht
                rows = [row for row in rows if pattern.search(str(row[25]))]  # Index 25 = erkannter_text

            if kirchenbuch_filter and kirchenbuch_filter != 'Alle':
                rows = [
                    row for row in rows
                    if extract_kirchenbuch_titel(row[23]) == kirchenbuch_filter
                ]

            for row in rows:
                # row: id, jahr, datum, iso_datum, ereignis_typ, seite, nummer, kirchengemeinde, 
                # vorname, nachname, partner, beruf, ort,
                # braeutigam_vater, braut_vater, braut_nachname, braut_ort,
                # braeutigam_stand, stand, mutter_vorname, datum_geburt, todestag, geb_jahr_gesch,
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
                    safe(19), # Mutter Vorname
                    safe(20), # Datum Geburt
                    safe(21), # Todestag
                    safe(22), # Geb.Jahr (gesch.)
                    safe(23), # Dateiname
                    safe(24), # Notiz
                    safe(27), # Gramps
                    safe(25), # Erkannter Text
                )

                # NEU: Prüfe ob Datum gültig ist
                jahr = safe(1)
                datum = safe(2)
                notiz = safe(24)
                kirchenbuchtext = safe(26)  # Index 26 = kirchenbuchtext
                gramps = safe(27)  # Index 27 = gramps
                date_valid = is_valid_date(datum, jahr)

                # Tags setzen
                tags = []
                if notiz:
                    tags.append('has_notiz')
                if kirchenbuchtext:
                    tags.append('has_kirchenbuchtext')
                if gramps:
                    tags.append('has_gramps')
                if not date_valid and datum:
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
                for titel in [extract_kirchenbuch_titel(dateiname)]
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

    def _sort_by_page_and_number(self):
        """Sortiert die Treeview nach Filmnummer, dann Seite, dann Nummer."""
        # Hole alle Items mit ihren Werten
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
        self.nachname_search.delete(0, tk.END)
        self.braut_nachname_search.delete(0, tk.END)
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
                   ereignis_typ, mutter_vorname, datum_geburt
            FROM karteikarten WHERE id = ?
            """,
            (record_id,)
        )
        row = cursor.fetchone()
        if not row:
            return

        (vorname, nachname, partner, stand, braeutigam_stand, beruf, ort, seite, nummer, todestag,
         geb_jahr_gesch, braeutigam_vater, braut_vater, braut_nachname, braut_ort,
         ereignis_typ, mutter_vorname, datum_geburt) = row

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
        self._set_ocr_field_value('mutter vorname', mutter_vorname)
        self._set_ocr_field_value('datum geburt', datum_geburt)

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
    
    def _export_full_csv(self):
        """Exportiert Karteikarten + Sync-Queue als zwei CSVs."""
        from pathlib import Path
        
        output_dir = filedialog.askdirectory(title="Verzeichnis für Full Backup wählen")
        if not output_dir:
            return

        try:
            karteikarten_path, queue_path = self.db.export_full_backup(output_dir)
            
            import csv
            with open(karteikarten_path, 'r', encoding='utf-8') as f:
                rows_count = sum(1 for _ in csv.reader(f)) - 1
            
            with open(queue_path, 'r', encoding='utf-8') as f:
                queue_count = sum(1 for _ in csv.reader(f)) - 1
            
            msg = (
                f"Full Backup erstellt:\n\n"
                f"Karteikarten: {rows_count} Datensätze\n"
                f"Sync-Queue: {queue_count} Einträge\n\n"
                f"Speicherort: {output_dir}"
            )
            messagebox.showinfo("Full Backup erstellt", msg)
        except Exception as e:
            messagebox.showerror("Fehler", f"Full Backup fehlgeschlagen:\n{e}")

    def _import_full_backup(self):
        """Importiert Daten + Queue aus Backup-CSVs."""
        import csv
        import os
        
        backup_dir = filedialog.askdirectory(title="Backup-Verzeichnis mit CSV-Dateien")
        if not backup_dir:
            return

        karteikarten_file = None
        queue_file = None
        
        for file in os.listdir(backup_dir):
            if '_backup_karteikarten_' in file and file.endswith('.csv'):
                karteikarten_file = os.path.join(backup_dir, file)
            elif '_backup_sync_queue_' in file and file.endswith('.csv'):
                queue_file = os.path.join(backup_dir, file)
        
        if not karteikarten_file:
            messagebox.showwarning("Nicht gefunden", "Zur Wiederherstellung wird _backup_karteikarten_*.csv benötigt")
            return

        if not messagebox.askyesno("Bestätigung", 
            "Aktuelle Daten werden mit dem Backup überschrieben!\n\nFortfahren?"):
            return

        try:
            self.db.restore_full_backup(karteikarten_file, queue_file)
            messagebox.showinfo("Erfolg", "Daten erfolgreich wiederhergestellt!\n\nBitte die Anwendung neu starten.")
        except Exception as e:
            messagebox.showerror("Fehler", f"Wiederherstellung fehlgeschlagen:\n{e}")


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
        """Exportiert per Kontextmenue nur die ausgewaehlten Datensaetze als GEDCOM (GRAMPS)."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte waehlen Sie mindestens einen Datensatz aus.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".ged",
            initialfile="karteikarten_export_auswahl_gra.ged",
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

    def _export_gedcom_tng(self):
        """Exportiert die Datenbank als GEDCOM-Datei (TNG-Dialekt)."""
        selection = self.tree.selection()

        export_all = True
        if selection:
            result = messagebox.askyesnocancel(
                "Export-Auswahl",
                f"{len(selection)} Einträge sind ausgewählt.\n\n"
                f"Ja = Nur Auswahl exportieren\n"
                f"Nein = Alle Einträge exportieren\n"
                f"Abbrechen = Export abbrechen"
            )
            if result is None:
                return
            export_all = not result

        filepath = filedialog.asksaveasfilename(
            defaultextension=".ged",
            initialfile="karteikarten_export_tng.ged",
            filetypes=[("GEDCOM-Dateien", "*.ged"), ("Alle Dateien", "*.*")]
        )
        if not filepath:
            return

        try:
            exporter = GedcomExporter(self.db.conn, dialect='TNG')
            filter_params = {}
            if not export_all and selection:
                filter_params['id_list'] = [self.tree.item(item)['values'][0] for item in selection]

            exported_count = exporter.export_to_gedcom(filepath, filter_params)

            messagebox.showinfo(
                "Erfolg",
                f"✅ GEDCOM-Export erfolgreich!\n\n"
                f"Datei: {Path(filepath).name}\n"
                f"Exportierte Datensätze: {exported_count}\n"
                f"Format: TNG-Dialekt\n\n"
                f"Die Datei kann jetzt in The Next Generation (TNG)\n"
                f"importiert werden."
            )
        except ValueError as e:
            messagebox.showwarning("Keine Daten", str(e))
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim GEDCOM-Export (TNG):\n{str(e)}")

    def _export_gedcom_tng_selected_from_context(self):
        """Exportiert per Kontextmenü nur die ausgewählten Datensätze als GEDCOM (TNG)."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie mindestens einen Datensatz aus.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".ged",
            initialfile="karteikarten_export_auswahl_tng.ged",
            filetypes=[("GEDCOM-Dateien", "*.ged"), ("Alle Dateien", "*.*")]
        )
        if not filepath:
            return

        try:
            exporter = GedcomExporter(self.db.conn, dialect='TNG')
            id_list = [self.tree.item(item)['values'][0] for item in selection]
            exported_count = exporter.export_to_gedcom(filepath, {'id_list': id_list})

            messagebox.showinfo(
                "Erfolg",
                f"✅ GEDCOM-Export erfolgreich!\n\n"
                f"Datei: {Path(filepath).name}\n"
                f"Exportierte Datensätze (Auswahl): {exported_count}\n"
                f"Format: TNG-Dialekt"
            )
        except ValueError as e:
            messagebox.showwarning("Keine Daten", str(e))
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim GEDCOM-Export (TNG):\n{str(e)}")

    
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
            import openpyxl  # noqa: F401
        except ImportError:
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

        def _progress(current, total):
            self.db_progress['maximum'] = total
            self.db_progress['value'] = current
            self.root.update_idletasks()

        self.db_status_label.config(text="⏳ XLSX-Import läuft …")
        self.db_progress['value'] = 0
        self.root.update_idletasks()
        try:
            result = run_xlsx_import(self.db, filepath, row_progress_callback=_progress)

            self.db_progress.config(mode='indeterminate')
            self.db_progress.start(15)
            self.db_status_label.config(text="⏳ Datenbank-Ansicht wird aktualisiert …")
            self.root.update_idletasks()
            self._refresh_db_list()

            self.db_progress.stop()
            self.db_progress.config(mode='determinate')
            self.db_progress['value'] = 0
            messagebox.showinfo(
                "XLSX-Import abgeschlossen",
                f"✅ XLSX-Import abgeschlossen!\n\n"
                f"Aktualisiert: {result['updated']}\n"
                f"Nicht gefunden (kein Match): {result['not_found']}\n"
                f"Fehler: {result['errors']}"
            )

            # Nicht gefundene Namen in Datei speichern
            not_found_names = result.get("not_found_names", [])
            if not_found_names:
                import datetime
                out_path = Path("output/xlsx_not_found.txt")
                out_path.parent.mkdir(exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(f"# XLSX-Import: nicht gematchte Einträge ({len(not_found_names)})\n")
                    f.write(f"# Importdatei: {Path(filepath).name}\n")
                    f.write(f"# Zeitpunkt: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    for name in not_found_names:
                        f.write(f"{name}\n")
                if messagebox.askyesno(
                    "Nicht gefundene Einträge",
                    f"{len(not_found_names)} Einträge konnten nicht zugeordnet werden.\n\n"
                    f"Die Dateinamen wurden gespeichert in:\n{out_path}\n\n"
                    f"Datei jetzt öffnen?"
                ):
                    import os
                    os.startfile(out_path)
        except ValueError as e:
            self.db_progress['value'] = 0
            messagebox.showerror("Fehlende Spalten", str(e))
        except Exception as e:
            self.db_progress.stop()
            self.db_progress.config(mode='determinate')
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

            # Bild so skalieren, dass es in den verfügbaren Platz passt
            self.image_label.update_idletasks()
            max_w = max(self.image_label.winfo_width(), 400)
            max_h = max(self.image_label.winfo_height(), 300)

            # Skalierung auf Breite
            scale_w = max_w / image.width
            # Skalierung auf Höhe
            scale_h = max_h / image.height
            # Kleinerer Faktor bestimmt die Skalierung (Bild muss in beide Dimensionen passen)
            scale = min(scale_w, scale_h, 1.0)  # niemals vergrößern
            display_width = max(1, int(image.width * scale))
            display_height = max(1, int(image.height * scale))

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

    def _jump_to_card(self):
        """Springt zu einer bestimmten Kartennummer (1-basiert)."""
        if not self.image_files:
            return
        raw = self.jump_var.get().strip()
        if not raw:
            return
        try:
            nr = int(raw)
        except ValueError:
            messagebox.showwarning("Ungültige Eingabe", "Bitte eine gültige Kartennummer eingeben.")
            return
        idx = nr - 1  # 1-basiert → 0-basiert
        if idx < 0 or idx >= len(self.image_files):
            messagebox.showwarning(
                "Außerhalb des Bereichs",
                f"Bitte eine Zahl zwischen 1 und {len(self.image_files)} eingeben."
            )
            return
        self.current_index = idx
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
    
    def _batch_register_files(self):
        """Registriert alle Dateien des aktuellen Bildtyp-Filters in der DB ohne OCR.
        Bereits vorhandene Einträge werden übersprungen (skip_if_exists=True).
        Danach kann der XLSX-Import die Felder befüllen."""
        if not self.image_files:
            messagebox.showwarning("Warnung", "Keine Karteikarten geladen.")
            return

        batch_type = self.batch_type_var.get()

        # Dateien filtern
        if batch_type == "Alle":
            candidates = list(self.image_files)
        else:
            candidates = [f for f in self.image_files if f" {batch_type} " in f.name]

        if not candidates:
            messagebox.showwarning(
                "Keine Dateien",
                f"Keine Dateien mit Bildtyp '{batch_type}' in der geladenen Liste gefunden."
            )
            return

        antwort = messagebox.askyesno(
            "Registrieren bestätigen",
            f"{len(candidates)} Dateien werden in die Datenbank eingetragen (ohne OCR).\n\n"
            f"Bildtyp-Filter: {batch_type}\n"
            f"Bereits vorhandene Einträge werden übersprungen.\n\n"
            f"Möchten Sie fortfahren?"
        )
        if not antwort:
            return

        neu = 0
        uebersprungen = 0
        fehler = 0

        self.register_btn.config(state=tk.DISABLED)
        for idx, filepath in enumerate(candidates):
            self.text_display.delete("1.0", tk.END)
            self.text_display.insert(
                "1.0",
                f"📋 Registrierung läuft...\n\n"
                f"Fortschritt: {idx + 1} / {len(candidates)}\n"
                f"Neu: {neu}  Übersprungen: {uebersprungen}  Fehler: {fehler}\n\n"
                f"Aktuell: {filepath.name}"
            )
            self.root.update()
            try:
                result_id = self.db.save_karteikarte(
                    dateiname=filepath.name,
                    dateipfad=str(filepath),
                    erkannter_text="",
                    ocr_methode="Import",
                    skip_if_exists=True,
                )
                if result_id is None:
                    uebersprungen += 1
                else:
                    neu += 1
            except Exception as e:
                fehler += 1
                print(f"[REGISTER] Fehler bei {filepath.name}: {e}")

        self.register_btn.config(state=tk.NORMAL)
        self.text_display.delete("1.0", tk.END)
        messagebox.showinfo(
            "Registrierung abgeschlossen",
            f"Fertig.\n\n"
            f"Neu eingetragen:    {neu}\n"
            f"Bereits vorhanden:  {uebersprungen}\n"
            f"Fehler:             {fehler}\n\n"
            f"Die Einträge können jetzt per XLSX-Import befüllt werden."
        )
        if hasattr(self, "tree"):
            self._refresh_db_list()

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
        self._apply_text_transform_selected(fn=fix_wetzlar_infinity, title="Wetzlar ∞-Korrektur",
            description="'ev. Kb. Wetzlar 00' → 'ev. Kb. Wetzlar ∞'\n'Witzlar. 00161' → 'Wetzlar ∞ 1561'",
            ocr_methode="wetzlar_infinity_fix")
    
    
    def _insert_burial_symbol_selected(self):
        self._apply_text_transform_selected(fn=insert_burial_symbol, title="Begräbniszeichen einfügen",
            description="'ev. Kb. Wetzlar 1674...' → 'ev. Kb. Wetzlar ⚰ 1674...'",
            ocr_methode="burial_symbol_inserted")

    def _insert_marriage_symbol_selected(self):
        self._apply_text_transform_selected(fn=insert_marriage_symbol, title="Hochzeitszeichen einfügen",
            description="'ev. Kb. Wetzlar 1674...' → 'ev. Kb. Wetzlar ∞ 1674...'",
            ocr_methode="burial_symbol_inserted")


    def _replace_ev_kb_wetzlar_special_selected(self):
        self._apply_text_transform_selected(fn=replace_ev_kb_wetzlar_special,
            title="ev. Kb. Wetzlar. □ → ⚰",
            description="'ev. Kb. Wetzlar. □ 1' → 'ev. Kb. Wetzlar ⚰ 1'",
            ocr_methode="ev_kb_wetzlar_special_fix")
    
    
    def _fix_header_prefix_selected(self):
        self._apply_text_transform_selected(fn=fix_header_prefix, title="ev. Kb. Wetzlar Korrektur",
            description="Alles bis zur ersten Ziffer wird durch 'ev. Kb. Wetzlar' ersetzt.",
            ocr_methode="header_prefix_fix")
    
    def _fix_infinity_year_selected(self):
        self._apply_text_transform_selected(fn=fix_infinity_year, title="Jahr-Korrektur nach ∞",
            description="'∞16.11' → '∞1611', '∞16.1' → '∞161'",
            ocr_methode="infinity_year_fix")
    
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
