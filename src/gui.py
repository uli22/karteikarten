"""Grafische Benutzeroberfläche für die Karteikartenerkennung."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from PIL import Image, ImageTk

from .database import KarteikartenDB
from .extraction_lists import (ANREDEN, ARTIKEL, BERUFE, BERUFS_EINLEITUNG,
                               IGNORIERE_WOERTER, KEINE_BERUFE,
                               MAENNLICHE_VORNAMEN, ORTS_PRAEPOSITIONEN,
                               SOURCES, STAND_MAPPING, STAND_PRAEFIXE,
                               STAND_SYNONYME, WEIBLICHE_VORNAMEN)
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
        
        self.base_path = Path(base_path)
        self.image_folder_var = tk.StringVar(value=str(base_path))  # NEU: Variable für Verzeichnis
        self.start_file = start_file
        self.current_index = 0
        self.image_files: List[Path] = []
        self.current_image = None
        self.photo_image = None
        
        # OCR Engine initialisieren (Standard: EasyOCR)
        self.ocr_engine = None
        self.ocr_method = 'easyocr'
        self.credentials_path = None
        
        # Datenbank initialisieren
        self.db = KarteikartenDB()
        
        # Aktueller DB-Record (None = nicht gespeichert, ID = bereits in DB)
        self.current_db_record_id = None
        
        # Sortierrichtung pro Spalte (True = aufsteigend, False = absteigend)
        self.sort_reverse = {}
        
        # Batch-Scan Abbruch-Flag
        self.batch_scan_cancelled = False
        
        # GUI aufbauen
        self._create_widgets()
        self._load_image_files()
        
        if self.image_files:
            self._display_current_card()

    def _run_recognition_selected(self):
        """Führt die strukturierte Erkennung für die ausgewählten Datensätze im Datenbank-Tab durch (unterscheidet Typ Begräbnis/Hochzeit)."""
        import re
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie mindestens einen Eintrag aus der Liste aus.")
            return

        errors = []
        updated = 0
        unrecognized_words = set()  # Sammlung aller nicht erkannten Wörter
        for item in selection:
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
            # DEBUG: Testfall Jonas Palleroths hinterl. Sohn ...
            if (
                text.strip().startswith("ev. Kb. Wetzlar ⚰ 1694.04.27 p. 1 Nr. 12 Jonas Palleroths hinterl. Sohn begr.a:23. Apr, alt 27ann. 1694 B21.5.57")
                or text.strip().startswith("Ann Engel Schülerin begraben d. 4. Febr.alters 58 jahr 71698 R")
                or (typ and typ.lower().startswith("begr"))
            ):
                # 1. Zitation am Anfang erkennen (ev. Kb. Wetzlar ⚰ 1698.02.04 p. 114 Nr. 6 ...)
                # Erlaubt: Punkte/Leerzeichen variabel, Zahlen unterschiedlich, Stopwörter: Text, begraben, begr., begr
                # Pattern erlaubt: p.2, p 2, p. 2, Nr.10, Nr 10, Nr. 10
                zitation_pattern = r"^(ev\.\s*Kb\.\s*Wetzlar)?[ .]*[⚰\u26B0]?[ .]*(\d{4}[ .]?\d{2}[ .]?\d{2})[ .]*p\.?[ .]?(\d+)[ .]*Nr\.?[ .]?(\d+)[ .]*"
                stopwords = ["Text", "begraben", "begr.", "begr ", "Begr.", "Begr "]
                # Suche das Ende der Zitation
                stop_idx = len(text)
                for sw in stopwords:
                    idx = text.lower().find(sw.lower())
                    if idx != -1 and idx < stop_idx:
                        stop_idx = idx
                zitation_text = text[:stop_idx]
                rest_text = text[stop_idx:]
                # Zitation extrahieren
                m = re.match(zitation_pattern, zitation_text)
                vorname = nachname = partner = beruf = stand = todestag = ort = None
                
                # DEBUG: Ausgabe für Debugging
                print(f"DEBUG: zitation_text = {repr(zitation_text[:100])}")
                print(f"DEBUG: Pattern matched = {m is not None}")
                
                if m:
                    # Zitation gefunden, restlicher Text nach Zitation
                    print(f"DEBUG: Match end position = {m.end()}")
                    print(f"DEBUG: Matched part = {repr(zitation_text[:m.end()])}")
                    after_zitation = zitation_text[m.end():].strip()
                else:
                    after_zitation = zitation_text.strip()
                
                print(f"DEBUG: after_zitation = {repr(after_zitation)}")

                # 2. Wörter nach Zitation in Liste splitten (bis zum Stopwort)
                words = re.split(r"[ ,.;\n\r]+", after_zitation)
                words = [w for w in words if w]
                print(f"DEBUG: words = {words}")

                # Verwende importierte Listen aus extraction_lists.py
                weibliche_vornamen = WEIBLICHE_VORNAMEN
                maennliche_vornamen = MAENNLICHE_VORNAMEN
                stand_synonyme = STAND_SYNONYME
                ort_prae = ORTS_PRAEPOSITIONEN
                beruf_einleitung = BERUFS_EINLEITUNG
                anreden = ANREDEN
                ignoriere_woerter = IGNORIERE_WOERTER
                
                # Hilfsfunktion: Prüfe ob "frau" als Anrede zu behandeln ist
                def ist_frau_anrede(idx_aktuell):
                    """Prüft ob 'frau' an aktueller Position eine Anrede ist (vor Namen)."""
                    if idx_aktuell >= len(words) or words[idx_aktuell].lower() != "frau":
                        return False
                    # 'frau' ist Anrede wenn danach ein Vorname oder potentieller Nachname folgt
                    if idx_aktuell + 1 < len(words):
                        next_word = words[idx_aktuell + 1]
                        # Ist nächstes Wort ein Vorname?
                        if next_word in weibliche_vornamen or next_word in maennliche_vornamen:
                            return True
                        # Ist nächstes Wort kein Stand-Wort? Dann vermutlich Nachname
                        if next_word.lower() not in stand_synonyme:
                            return True
                    return False
                
                # Extraktion
                idx = 0
                vorname_start_idx = -1  # Position wo Vorname gefunden wurde
                used_words = set()  # Tracke welche Wörter verwendet wurden
                
                # Sonderfall 1a: "Herr [männl. Vorname(n)] [Nachname] hinterlassene Wittib/Wittwe" = Witwe des genannten Mannes
                # Beispiel: "Herr Hans Conrad Verdriessen hinterlassene Wittib" → Partner: Hans Conrad, Nachname: Verdriessen, Stand: Wittwe
                idx_check = 0
                hinterlassene_wittwe_pattern = False
                if idx_check < len(words) and words[idx_check].lower() in anreden:
                    # Schaue voraus ob "hinterlassene" + Wittwe/Wittib im Text vorkommt (erweiterte Reichweite)
                    for k in range(idx_check + 1, min(len(words), idx_check + 8)):
                        if words[k].lower() in ["hinterlassene", "hinterlassen"]:
                            # Prüfe ob danach Wittwe/Wittib kommt
                            if k + 1 < len(words) and words[k + 1].lower() in ["wittib", "wittwe", "witwe", "witbe"]:
                                hinterlassene_wittwe_pattern = True
                                print(f"DEBUG 1a: hinterlassene_wittwe_pattern erkannt bei Position {k}")
                                break
                    
                    print(f"DEBUG 1a: Anrede '{words[idx_check]}' gefunden, hinterlassene_wittwe_pattern={hinterlassene_wittwe_pattern}")
                    
                    if hinterlassene_wittwe_pattern and idx_check + 1 < len(words):
                        print(f"DEBUG 1a: Nächstes Wort: '{words[idx_check + 1]}', ist männlicher Vorname: {words[idx_check + 1] in maennliche_vornamen}")
                        
                        if words[idx_check + 1] in maennliche_vornamen:
                            # Sammle männliche Vornamen (kann Doppelname sein: Hans Conrad)
                            partner_vornamen = []
                            j = idx_check + 1
                            while j < len(words) and words[j] in maennliche_vornamen:
                                partner_vornamen.append(words[j])
                                print(f"DEBUG 1a: Vorname hinzugefügt: '{words[j]}'")
                                j += 1
                            
                            # Nächstes Wort sollte Nachname sein
                            if j < len(words) and words[j] not in maennliche_vornamen + weibliche_vornamen and words[j].lower() not in stand_synonyme:
                                partner = " ".join(partner_vornamen)
                                nachname = words[j]
                                vorname = None  # Kein Vorname für die Witwe
                                vorname_start_idx = -1
                                idx = j + 1
                                print(f"DEBUG 1a: ERFOLG - Partner: '{partner}', Nachname: '{nachname}'")
                                # Überspringe "hinterlassene"
                                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                                    idx += 1
                
                # Sonderfall 1b: "Herrn [männl. Vorname] [Nachname] [Stand]" = Kind/Angehöriger
                # Beispiel: "Herrn Theophili Haupt tochterlein" → Partner: Theophilus, Nachname: Haupt, Stand: Töchterlein
                # Der männliche Vorname (oft im Genitiv) ist der Vater/Ehemann, nicht das Subjekt
                if not nachname:  # Nur wenn nicht bereits durch Sonderfall 1a behandelt
                    idx_check = 0
                    if idx_check < len(words) and words[idx_check].lower() in anreden:
                        if idx_check + 1 < len(words) and words[idx_check + 1] in maennliche_vornamen:
                            if idx_check + 2 < len(words):
                                # Prüfe ob danach ein Nachname (kein Vorname, kein Stand-Wort) kommt
                                potential_nachname = words[idx_check + 2]
                                if potential_nachname not in weibliche_vornamen + maennliche_vornamen and potential_nachname.lower() not in stand_synonyme:
                                    # Dies ist das Muster: Herrn [Vater] [Nachname] [Stand]
                                    partner_raw = words[idx_check + 1]
                                    # Entferne Genitiv-Endung (i, ii, is, us → us)
                                    if partner_raw.endswith("i") and partner_raw not in ["Antoni", "Antonii"]:
                                        # Theophili → Theophilus
                                        partner = partner_raw[:-1] + "us"
                                    elif partner_raw.endswith("ii"):
                                        partner = partner_raw[:-2] + "us"
                                    else:
                                        partner = partner_raw
                                    
                                    nachname = potential_nachname
                                    idx = idx_check + 3
                                    vorname = None  # Kein Vorname für das Kind/den Angehörigen
                                    vorname_start_idx = -1
                
                # Sonderfall 2: Vorname suchen (nur wenn nicht bereits durch Sonderfall 1 behandelt)
                if not nachname:  # Nur wenn noch kein Nachname gesetzt
                    idx = 0
                    # Vorname: erstes Wort, das in Vornamenlisten ist
                    while idx < len(words):
                        w = words[idx]
                        if w in weibliche_vornamen or w in maennliche_vornamen:
                            vorname_start_idx = idx  # Merke Position des Vornamens
                            vorname = w
                            used_words.add(idx)
                            idx += 1
                            # Prüfe auf Doppelnamen (z.B. Ann Engel, Hans George)
                            if idx < len(words) and words[idx] in weibliche_vornamen + maennliche_vornamen:
                                vorname += " " + words[idx]
                                used_words.add(idx)
                                idx += 1
                            # Überspringe zu ignorierende Wörter (seel, sel., etc.)
                            while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                                used_words.add(idx)
                                idx += 1
                            break
                        idx += 1
                
                # Sonderfall 3: Nachname steht VOR Vorname (z.B. "Müller Anna ein Medtgen")
                # Wenn Vorname nicht am Anfang steht (idx > 0), ist das erste Wort der Nachname
                # ABER: Nicht wenn das erste Wort Teil der Zitation ist (ev., Kb., p., Nr., etc.)
                zitation_woerter = ["ev", "ev.", "kb", "kb.", "wetzlar", "p", "p.", "nr", "nr.", "text"]
                if vorname and vorname_start_idx > 0:
                    first_word_lower = words[0].lower().rstrip('.')
                    # Nur als Nachname setzen wenn es KEIN Zitation-Wort ist
                    if first_word_lower not in zitation_woerter:
                        nachname = words[0]
                        used_words.add(0)
                    # Bereits Nachname gesetzt oder übersprungen, überspringe normale Nachname-Erkennung
                
                # Wenn noch kein Nachname gesetzt, normale Nachname-Erkennung
                if vorname and not nachname:
                    # Bei weiblichem Vornamen: Spezialbehandlung für Partner
                    if any(v in vorname for v in weibliche_vornamen):
                        # Suche nach "Herrn" oder "Herr"
                        if idx < len(words) and words[idx].lower() in anreden:
                            idx += 1  # Überspringe Anrede
                            # Nächstes Wort sollte männlicher Vorname sein
                            if idx < len(words) and words[idx] in maennliche_vornamen:
                                partner = words[idx]
                                idx += 1
                                # Nächstes Wort ist Nachname (evtl. Genitiv mit 's' am Ende)
                                if idx < len(words):
                                    nachname_raw = words[idx]
                                    # Entferne Genitiv-s wenn vorhanden
                                    if nachname_raw.endswith("s") and len(nachname_raw) > 2:
                                        nachname = nachname_raw[:-1]
                                    else:
                                        nachname = nachname_raw
                                    idx += 1
                            # Fahre mit Stand-Erkennung fort
                        else:
                            # Normaler Fall: Nachname nach Vorname
                            while idx < len(words):
                                w = words[idx]
                                # Überspringe Anreden und zu ignorierende Wörter
                                if w.lower() in anreden or w.lower() in ignoriere_woerter:
                                    idx += 1
                                    continue
                                # Artikel: Nur überspringen wenn KEIN Beruf folgt ("der Schreiner" = Beruf!)
                                if w.lower() in ARTIKEL:
                                    if idx + 1 < len(words) and words[idx + 1] in BERUFE:
                                        # "der Schreiner" -> kein Nachname, wird später als Beruf erkannt
                                        break
                                    else:
                                        # Normaler Artikel ohne Beruf -> überspringen
                                        idx += 1
                                        continue
                                # Spezialfall: "frau" nur überspringen wenn es Anrede ist (vor Namen)
                                if w.lower() == "frau" and ist_frau_anrede(idx):
                                    idx += 1
                                    continue
                                if w.lower() not in [s.lower() for s in stand_synonyme] and w.lower() not in ort_prae and w.lower() not in beruf_einleitung:
                                    nachname = w
                                    idx += 1
                                    # Überspringe zu ignorierende Wörter
                                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                                        idx += 1
                                    break
                                idx += 1
                            # Partner: falls nach weiblichem Vornamen ein männlicher Vorname folgt
                        if idx < len(words) and words[idx] in maennliche_vornamen:
                            partner = words[idx]
                            idx += 1
                            # Partner-Nachname
                            if idx < len(words):
                                partner += " " + words[idx]
                                idx += 1
                            # Überspringe zu ignorierende Wörter
                            while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                                idx += 1
                    else:
                        # Männlicher Vorname: normale Nachname-Erkennung
                        while idx < len(words):
                            w = words[idx]
                            # Überspringe Anreden
                            if w.lower() in anreden:
                                idx += 1
                                continue
                            # Artikel: Nur überspringen wenn KEIN Beruf folgt ("der Schreiner" = Beruf!)
                            if w.lower() in ARTIKEL:
                                if idx + 1 < len(words) and words[idx + 1] in BERUFE:
                                    # "der Schreiner" -> kein Nachname, wird später als Beruf erkannt
                                    break
                                else:
                                    # Normaler Artikel ohne Beruf -> überspringen
                                    idx += 1
                                    continue
                            # Spezialfall: "frau" nur überspringen wenn es Anrede ist (vor Namen)
                            if w.lower() == "frau" and ist_frau_anrede(idx):
                                idx += 1
                                continue
                            if w.lower() not in [s.lower() for s in stand_synonyme] and w.lower() not in ort_prae and w.lower() not in beruf_einleitung:
                                nachname = w
                                idx += 1
                                # Überspringe Wörter aus ignoriere_woerter Liste
                                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                                    idx += 1
                                break
                            idx += 1
                # Stand: nächstes Wort, das in Stand-Synonymen ist, ggf. mit Präfix davor
                # Präfixe: "hinterlassener", "ein" (bei "ein Medtgen", "ein Kind"), etc.
                for i in range(idx, len(words)):
                    # Prüfe auf Stand-Präfixe
                    stand_prefix = ""
                    if words[i].lower() in STAND_PRAEFIXE:
                        stand_prefix = words[i] + " "
                        j = i + 1
                    # Prüfe auf "ein" + Stand-Synonym (z.B. "ein Medtgen")
                    elif words[i].lower() == "ein" and i + 1 < len(words) and words[i + 1].lower() in stand_synonyme:
                        stand_prefix = ""  # "ein" nicht als Präfix übernehmen
                        j = i + 1
                    else:
                        j = i
                    # Stand-Synonym prüfen
                    if j < len(words) and words[j].lower() in stand_synonyme:
                        # Normalisiere Stand über STAND_MAPPING
                        word_lower = words[j].lower()
                        stand = STAND_MAPPING.get(word_lower, words[j].capitalize())
                        
                        # Füge Präfix hinzu wenn vorhanden
                        if stand_prefix:
                            stand = stand_prefix + stand
                        idx = j + 1
                        break
                
                # Falls kein Stand gefunden und "begraben" im Text, setze Stand auf "Vater"
                if not stand and ("begraben" in text.lower() or "begr" in text.lower()):
                    stand = "Vater"
                    
                # Beruf: nach "ein <Beruf>" oder "der/die/das <Beruf>" suchen
                # ABER: "ein Medtgen", "ein Kind" etc. sind Stand, kein Beruf!
                # AUCH: "ein sieches" (Adjektiv) ist kein Beruf!
                # WICHTIG: "der Schreiner" = Beruf, aber "Schreiner" ohne Artikel = Nachname
                # WICHTIG: Suche durch ALLE Wörter, nicht nur ab idx (der durch andere Erkennungen verschoben wurde)
                for i in range(len(words)-1):
                    # Fall 1: "ein <Beruf>"
                    if words[i].lower() in beruf_einleitung:
                        next_word_lower = words[i+1].lower()
                        # Prüfe ob das Wort nach "ein" ein Stand-Synonym ist
                        if next_word_lower not in stand_synonyme and next_word_lower not in KEINE_BERUFE:
                            beruf = words[i+1]
                        break
                    # Fall 2: "der/die/das <Beruf>" (Artikel + Wort aus BERUFE-Liste)
                    elif words[i].lower() in ARTIKEL:
                        if i + 1 < len(words) and words[i+1] in BERUFE:
                            beruf = words[i+1]
                            break
                    
                # Ort: nach Präpositionen suchen
                # Behandle "in der" als zusammenhängende Präposition
                for i in range(idx, len(words)):
                    # Prüfe auf zweiteilige Präposition "in der"
                    if i + 1 < len(words) and words[i].lower() == "in" and words[i+1].lower() == "der":
                        if i + 2 < len(words):
                            ort = words[i+2]
                            idx = i + 3
                            break
                    # Einteilige Präpositionen
                    elif words[i].lower() in ort_prae:
                        if i + 1 < len(words):
                            ort = words[i+1]
                            idx = i + 2
                            break
                
                # Todestag: aus Zitation extrahieren
                todestag = None
                m = re.match(zitation_pattern, zitation_text)
                if m:
                    todestag = m.group(2).replace(" ", ".").replace(".", ".")

                # Sammle nicht erkannte Wörter
                # Alle bekannten Listen zusammenführen
                all_known_words = set()
                all_known_words.update([w.lower() for w in weibliche_vornamen])
                all_known_words.update([w.lower() for w in maennliche_vornamen])
                all_known_words.update(stand_synonyme)
                all_known_words.update([w.lower() for w in ort_prae])
                all_known_words.update([w.lower() for w in beruf_einleitung])
                all_known_words.update(anreden)
                all_known_words.update(ignoriere_woerter)
                all_known_words.update(STAND_PRAEFIXE)
                all_known_words.update(KEINE_BERUFE)
                
                # Prüfe jedes Wort
                for word in words:
                    word_lower = word.lower()
                    # Ignoriere sehr kurze Wörter, Zahlen, Sonderzeichen
                    if len(word) < 2 or word.isdigit() or not word[0].isalpha():
                        continue
                    # Wenn nicht in bekannten Listen und nicht bereits zugeordnet
                    if word_lower not in all_known_words:
                        # Prüfe ob es in einem der extrahierten Felder vorkommt
                        in_extracted = False
                        for field in [vorname, nachname, partner, beruf, stand, ort]:
                            if field and word in str(field):
                                in_extracted = True
                                break
                        # Nur hinzufügen wenn nicht in extrahierten Feldern
                        if not in_extracted:
                            unrecognized_words.add(word)

                # Debug-Ausgabe für Testfall
                if text.strip().startswith("ev. Kb. Wetzlar ⚰ 1694.04.27 p. 1 Nr. 12 Jonas Palleroths hinterl. Sohn begr.a:23. Apr, alt 27ann. 1694 B21.5.57") or \
                   text.strip().startswith("Ann Engel Schülerin begraben d. 4. Febr.alters 58 jahr 71698 R"):
                    print("DEBUG-Extraktion für Testfall:")
                    print(f"Vorname: {vorname}")
                    print(f"Nachname: {nachname}")
                    print(f"Partner: {partner}")
                    print(f"Stand: {stand}")
                    print(f"Beruf: {beruf}")
                    print(f"Todestag: {todestag}")
                    print(f"Ort: {ort}")
                # Speichern
                try:
                    cursor.execute("""
                        UPDATE karteikarten SET
                            vorname = ?, nachname = ?, partner = ?, beruf = ?, stand = ?, todestag = ?, ort = ?, aktualisiert_am = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (vorname, nachname, partner, beruf, stand, todestag, ort, record_id))
                    self.db.conn.commit()
                    updated += 1
                except Exception as e:
                    errors.append(f"ID {record_id}: Fehler beim Speichern: {e}")
            else:
                # Platzhalter für andere Typen (z.B. Hochzeit)
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
        messagebox.showinfo("Feld-Extraktion abgeschlossen", msg)
        self._refresh_db_list()

    def _run_recognition_ocr_tab(self):
        """Führt die Feld-Erkennung auf dem aktuellen Text im OCR-Tab durch."""
        import re

        # Hole den aktuellen Text
        text = self.text_display.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Kein Text", "Bitte zuerst Text erkennen oder eingeben.")
            return
        
        # Setze alle Felder zurück
        for label in self.ocr_field_labels.values():
            label.config(text="—", foreground="gray")
        
        # Verwende die gleiche Erkennungslogik wie _run_recognition_selected
        # (Nur für Begräbnis-Typ, kann später erweitert werden)
        
        # Zitation-Pattern
        zitation_pattern = r"^(ev\.\s*Kb\.\s*Wetzlar)?[ .]*[⚰\u26B0]?[ .]*(\d{4}[ .]?\d{2}[ .]?\d{2})[ .]*p\.?[ .]?(\d+)[ .]*Nr\.?[ .]?(\d+)[ .]*"
        stopwords = ["Text", "begraben", "begr.", "begr ", "Begr.", "Begr "]
        
        # Suche das Ende der Zitation
        stop_idx = len(text)
        for sw in stopwords:
            idx = text.lower().find(sw.lower())
            if idx != -1 and idx < stop_idx:
                stop_idx = idx
        zitation_text = text[:stop_idx]
        
        # Zitation extrahieren
        m = re.match(zitation_pattern, zitation_text)
        vorname = nachname = partner = beruf = stand = todestag = ort = None
        
        if m:
            after_zitation = zitation_text[m.end():].strip()
        else:
            after_zitation = zitation_text.strip()
        
        # Wörter splitten
        words = re.split(r"[ ,.;\n\r]+", after_zitation)
        words = [w for w in words if w]
        
        if not words:
            messagebox.showinfo("Keine Daten", "Keine Wörter zur Erkennung gefunden.")
            return
        
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
        
        # Extraktion (vereinfachte Version)
        idx = 0
        vorname_start_idx = -1
        
        # Vorname suchen
        while idx < len(words):
            w = words[idx]
            if w in weibliche_vornamen or w in maennliche_vornamen:
                vorname_start_idx = idx
                vorname = w
                idx += 1
                # Doppelnamen
                if idx < len(words) and words[idx] in weibliche_vornamen + maennliche_vornamen:
                    vorname += " " + words[idx]
                    idx += 1
                # Ignoriere-Wörter überspringen
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1
                break
            idx += 1
        
        # Nachname
        if vorname and vorname_start_idx > 0:
            nachname = words[0]
        elif vorname:
            # Einfache Nachname-Suche
            while idx < len(words):
                w = words[idx]
                if w.lower() in anreden or w.lower() in ignoriere_woerter:
                    idx += 1
                    continue
                # Artikel: Nur überspringen wenn KEIN Beruf folgt ("der Schreiner" = Beruf!)
                if w.lower() in ARTIKEL:
                    if idx + 1 < len(words) and words[idx + 1] in BERUFE:
                        # "der Schreiner" -> kein Nachname, wird später als Beruf erkannt
                        break
                    else:
                        # Normaler Artikel ohne Beruf -> überspringen
                        idx += 1
                        continue
                if w.lower() == "frau" and ist_frau_anrede(idx):
                    idx += 1
                    continue
                if w.lower() not in [s.lower() for s in stand_synonyme] and w.lower() not in ort_prae and w.lower() not in beruf_einleitung:
                    nachname = w
                    idx += 1
                    while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                        idx += 1
                    break
                idx += 1
        
        # Stand
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
        
        # Falls kein Stand und "begraben" im Text
        if not stand and ("begraben" in text.lower() or "begr" in text.lower()):
            stand = "Vater"
        
        # Beruf: nach "ein <Beruf>" oder "der/die/das <Beruf>" suchen
        # WICHTIG: "der Schreiner" = Beruf, aber "Schreiner" ohne Artikel = Nachname
        # WICHTIG: Suche durch ALLE Wörter, nicht nur ab idx
        for i in range(len(words)-1):
            # Fall 1: "ein <Beruf>"
            if words[i].lower() in beruf_einleitung:
                next_word_lower = words[i+1].lower()
                if next_word_lower not in stand_synonyme and next_word_lower not in KEINE_BERUFE:
                    beruf = words[i+1]
                break
            # Fall 2: "der/die/das <Beruf>" (Artikel + Wort aus BERUFE-Liste)
            elif words[i].lower() in ARTIKEL:
                if i + 1 < len(words) and words[i+1] in BERUFE:
                    beruf = words[i+1]
                    break
        
        # Ort
        for i in range(idx, len(words)):
            if i + 1 < len(words) and words[i].lower() == "in" and words[i+1].lower() == "der":
                if i + 2 < len(words):
                    ort = words[i+2]
                    idx = i + 3
                    break
            elif words[i].lower() in ort_prae:
                if i + 1 < len(words):
                    ort = words[i+1]
                    idx = i + 2
                    break
        
        # Todestag aus Zitation
        if m:
            todestag = m.group(2).replace(" ", ".").replace(".", ".")
        
        # Update UI
        self.ocr_field_labels['vorname'].config(text=vorname or "—", foreground="blue" if vorname else "gray")
        self.ocr_field_labels['nachname'].config(text=nachname or "—", foreground="blue" if nachname else "gray")
        self.ocr_field_labels['partner'].config(text=partner or "—", foreground="blue" if partner else "gray")
        self.ocr_field_labels['stand'].config(text=stand or "—", foreground="blue" if stand else "gray")
        self.ocr_field_labels['beruf'].config(text=beruf or "—", foreground="blue" if beruf else "gray")
        self.ocr_field_labels['ort'].config(text=ort or "—", foreground="blue" if ort else "gray")
        self.ocr_field_labels['todestag'].config(text=todestag or "—", foreground="blue" if todestag else "gray")
        
        # Speichere die erkannten Felder für spätere Nutzung
        self._last_recognized_fields = {
            'vorname': vorname,
            'nachname': nachname,
            'partner': partner,
            'beruf': beruf,
            'stand': stand,
            'todestag': todestag,
            'ort': ort
        }
        
        # Status-Hinweis
        self.db_record_status.config(
            text="✓ Felder erkannt. Nutzen Sie 'DB aktualisieren', um die Änderungen zu speichern.",
            foreground="blue"
        )

    def _update_db_fields(self):
        """Aktualisiert die erkannten Felder in der Datenbank."""
        # Prüfe, ob Felder erkannt wurden
        if not hasattr(self, '_last_recognized_fields'):
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
            fields = self._last_recognized_fields
            cursor = self.db.conn.cursor()
            cursor.execute("""
                UPDATE karteikarten SET
                    vorname = ?, nachname = ?, partner = ?, beruf = ?, stand = ?, todestag = ?, ort = ?, 
                    aktualisiert_am = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                fields['vorname'], fields['nachname'], fields['partner'], 
                fields['beruf'], fields['stand'], fields['todestag'], fields['ort'], 
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

            
    def _create_widgets(self):
        """Erstellt alle GUI-Elemente."""
        # Notebook (Tab-System) erstellen
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        
        # Tab 1: OCR-Ansicht
        ocr_tab = ttk.Frame(self.notebook)
        self.notebook.add(ocr_tab, text="📸 OCR-Erkennung")
        
        # Tab 2: Datenbank-Ansicht
        db_tab = ttk.Frame(self.notebook)
        self.notebook.add(db_tab, text="📊 Datenbank")
        
        # Erstelle OCR-Tab Inhalt
        self._create_ocr_tab(ocr_tab)
        
        # Erstelle DB-Tab Inhalt
        self._create_db_tab(db_tab)
    
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
        right_frame = ttk.Frame(main_frame, width=500)
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
        
        # Scrollbarer Textbereich
        text_frame = ttk.Frame(right_frame, height=300)
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
        
       
        # Speichern-Buttons
        save_text_btn = ttk.Button(buttons_frame, text="💾 Text speichern", command=self._save_text)
        save_text_btn.pack(side=tk.LEFT, padx=5)
        
        self.save_db_btn = ttk.Button(buttons_frame, text="💽 In DB speichern", command=self._save_to_database)
        self.save_db_btn.pack(side=tk.LEFT, padx=5)
        
        # Erkennung-Button
        recognize_btn = ttk.Button(buttons_frame, text="🧠 Felder erkennen", command=self._run_recognition_ocr_tab)
        recognize_btn.pack(side=tk.LEFT, padx=5)
        
        # DB-Update-Button (für erkannte Felder)
        update_db_btn = ttk.Button(buttons_frame, text="📤 DB aktualisieren", command=self._update_db_fields)
        update_db_btn.pack(side=tk.LEFT, padx=5)
        
        # Frame für erkannte Felder
        fields_frame = ttk.LabelFrame(right_frame, text="Erkannte Felder", padding=10)
        fields_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # 2-Spalten-Layout für erkannte Felder
        # Labels für Feldnamen (links) und Werte (rechts)
        field_names = ["Vorname:", "Nachname:", "Partner:", "Stand:", "Beruf:", "Ort:", "Todestag:"]
        self.ocr_field_labels = {}
        
        for i, field_name in enumerate(field_names):
            # Label (links)
            label = ttk.Label(fields_frame, text=field_name, font=("Arial", 9, "bold"), anchor=tk.W, width=12)
            label.grid(row=i, column=0, sticky=tk.W, pady=2, padx=(0, 10))
            
            # Wert (rechts)
            value_label = ttk.Label(fields_frame, text="—", font=("Arial", 9), anchor=tk.W, foreground="blue")
            value_label.grid(row=i, column=1, sticky=tk.W, pady=2)
            
            # Speichere Referenz für spätere Updates
            field_key = field_name.rstrip(':').lower()
            self.ocr_field_labels[field_key] = value_label
        
        # Grid-Spalte 1 soll expandieren
        fields_frame.columnconfigure(1, weight=1)
    
    def _create_db_tab(self, parent):
        """Erstellt den Datenbank-Tab mit Listing und Filter."""

        # Oberer Bereich: Filter und Suche
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill=tk.X, padx=10, pady=10)

        # ID-Filter (vor Jahr-Filter)
        ttk.Label(filter_frame, text="ID:").pack(side=tk.LEFT, padx=5)
        self.id_filter = ttk.Entry(filter_frame, width=8)
        self.id_filter.pack(side=tk.LEFT, padx=5)

        # Jahr-Filter
        ttk.Label(filter_frame, text="Jahr:").pack(side=tk.LEFT, padx=5)
        self.year_filter = ttk.Combobox(filter_frame, width=10, state='readonly')
        self.year_filter.pack(side=tk.LEFT, padx=5)
        self.year_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # Ereignistyp-Filter
        ttk.Label(filter_frame, text="Typ:").pack(side=tk.LEFT, padx=(20, 5))
        self.type_filter = ttk.Combobox(filter_frame, width=15, state='readonly')
        self.type_filter['values'] = ['Alle', 'Heirat', 'Taufe', 'Begräbnis', '(Leere)']
        self.type_filter.current(0)
        self.type_filter.pack(side=tk.LEFT, padx=5)
        self.type_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # Dateinamen-Filter (nach Typ-Filter)
        ttk.Label(filter_frame, text="Dateiname:").pack(side=tk.LEFT, padx=(20, 5))
        self.filename_filter = ttk.Combobox(filter_frame, width=10, state='readonly')
        self.filename_filter['values'] = ['Alle', 'Sb', 'Hb', 'Gb']
        self.filename_filter.current(0)
        self.filename_filter.pack(side=tk.LEFT, padx=5)
        self.filename_filter.bind('<<ComboboxSelected>>', lambda e: self._refresh_db_list())

        # Namenssuche
        ttk.Label(filter_frame, text="Name:").pack(side=tk.LEFT, padx=(20, 5))
        self.name_search = ttk.Entry(filter_frame, width=20)
        self.name_search.pack(side=tk.LEFT, padx=5)

        # Checkbox für Regex-Suche
        self.regex_search_var = tk.BooleanVar(value=False)
        self.regex_search_cb = ttk.Checkbutton(filter_frame, text="Regex-Suche", variable=self.regex_search_var)
        self.regex_search_cb.pack(side=tk.LEFT, padx=5)


        search_btn = ttk.Button(filter_frame, text="🔍 Suchen", command=self._refresh_db_list)
        search_btn.pack(side=tk.LEFT, padx=5)

        # Eingabefeld für Ersetzen-Text
        self.replace_entry = ttk.Entry(filter_frame, width=20)
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

        replace_btn = ttk.Button(filter_frame, text="Ersetzen", command=replace_selected_text)
        replace_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = ttk.Button(filter_frame, text="✕ Filter löschen", command=self._clear_filters)
        clear_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = ttk.Button(filter_frame, text="🔄 Aktualisieren", command=self._refresh_db_list)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        # Button: Leere in sortierter Spalte auswählen
        select_empty_btn = ttk.Button(filter_frame, text="⛶ Leere in Spalte auswählen", command=self._select_empty_in_sorted_column)
        select_empty_btn.pack(side=tk.LEFT, padx=5)
        # NEU: Button zum Sortieren nach Seite/Nummer
        sort_page_btn = ttk.Button(filter_frame, text="📑 Nach Seite/Nr. sortieren", command=self._sort_by_page_and_number)
        sort_page_btn.pack(side=tk.LEFT, padx=5)
        
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
            'Vorname', 'Nachname', 'Partner', 'Beruf', 'Stand', 'Todestag', 'Ort',
            'Dateiname', 'Notiz', 'Text')
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
        self.tree.heading('Stand', text='Stand', command=lambda: self._sort_column('Stand'))
        self.tree.heading('Todestag', text='Todestag', command=lambda: self._sort_column('Todestag'))
        self.tree.heading('Ort', text='Ort', command=lambda: self._sort_column('Ort'))
        self.tree.heading('Dateiname', text='Dateiname', command=lambda: self._sort_column('Dateiname'))
        self.tree.heading('Notiz', text='F-ID', command=lambda: self._sort_column('Notiz'))
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
        self.tree.column('Stand', width=60, anchor='w')
        self.tree.column('Todestag', width=80, anchor='w')
        self.tree.column('Ort', width=80, anchor='w')
        self.tree.column('Dateiname', width=80, anchor='w')
        self.tree.column('Notiz', width=8, anchor='center')
        self.tree.column('Text', width=400, anchor='w')
        
        # Style für mehrzeilige Darstellung
        style = ttk.Style()
        style.configure("Treeview", rowheight=30)
        
        # Tag für Zeilen mit Notiz (grün)
        self.tree.tag_configure('has_notiz', background='#d4edda')
        
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
        self.tree_menu.add_command(label="Text bearbeiten & neu verarbeiten", command=self._edit_and_reprocess_text)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Datensatz(e) löschen", command=self._delete_selected)
        self.tree.bind('<Button-3>', self._show_tree_menu)
        
        # Statusleiste
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.db_status_label = ttk.Label(status_frame, text="Keine Daten geladen")
        self.db_status_label.pack(side=tk.LEFT)
        
        # Buttons unten - NEUE STRUKTUR: 2 Zeilen für bessere Sichtbarkeit
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # ZEILE 1: Haupt-Aktionen
        button_row1 = ttk.Frame(button_frame)
        button_row1.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(button_row1, text="📂 Bild anzeigen", command=self._show_selected_image).pack(side=tk.LEFT, padx=5)    
        ttk.Button(button_row1, text="📊 Statistik", command=self._show_statistics).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row1, text="📤 Export CSV", command=self._export_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row1, text="� Import CSV", command=self._import_csv).pack(side=tk.LEFT, padx=5)
        # NEU: Stapel-Erkennung für Auswahl
        ttk.Button(button_row1, text="🧠 Erkennung (Auswahl)", command=self._run_recognition_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row1, text="�🔄 Text-Korrektur (alle)", command=self._reprocess_all_texts).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row1, text="🔧 Text-Korrektur (Auswahl)", command=self._reprocess_selected_texts).pack(side=tk.LEFT, padx=5)
        
        # ZEILE 2: Spezial-Korrekturen
        button_row2 = ttk.Frame(button_frame)
        button_row2.pack(fill=tk.X)
        
        ttk.Button(button_row2, text="∞ Wetzlar 00→∞ (Auswahl)", command=self._fix_wetzlar_infinity_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row2, text="∞ 16.1→161 (Auswahl)", command=self._fix_infinity_year_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row2, text=" ev. Kb. Wetzlar (Auswahl)", command=self._fix_header_prefix_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row2, text=" Begräbnis (Auswahl)", command=self._insert_burial_symbol_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row2, text=" Hochzeit (Auswahl)", command=self._insert_marriage_symbol_selected).pack(side=tk.LEFT, padx=5)
        # NEU: Spezial-Ersetzung für ev. Kb. Wetzlar. □ 1
        ttk.Button(button_row2, text="ev. Kb. Wetzlar. □ 1 → ⚰ 1 (Auswahl)", command=self._replace_ev_kb_wetzlar_special_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_row2, text=" ID-Counter zurücksetzen", command=self._reset_autoincrement).pack(side=tk.LEFT, padx=5)
        # Button für p(Zahl)-Korrektur
        ttk.Button(button_row2, text="p(Zahl) → p. (Zahl) (Auswahl)", command=self._fix_p_number_selected).pack(side=tk.LEFT, padx=5)
        # Button für Standardisierung von p./Nr.-Angaben
        ttk.Button(button_row2, text="p/Nr. standardisieren (Auswahl)", command=self._standardize_p_nr_selected).pack(side=tk.LEFT, padx=5)
        # Button für Zitations-Formatierung
        ttk.Button(button_row2, text="📋 Zitation formatieren (Auswahl)", command=self._format_citation_selected).pack(side=tk.LEFT, padx=5)
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
                    
                    # Regex-Pattern für Zitation (flexibel für verschiedene Formate)
                    # Sucht: (ev. Kb. Wetzlar)? Symbol Datum p. Seite Nr. Nummer
                    pattern = r"^\s*(ev\.?\s*Kb\.?\s*Wetzlar)?\s*([⚰∞\u26B0])\s*(\d{4})[\.\s]*(\d{1,2})[\.\s]*(\d{1,2})\.?\s*p\.?\s*(\d+)\s*Nr\.?\s*(\d+)\s*"
                    
                    match = re.match(pattern, original_text, re.IGNORECASE)
                    if match:
                        # Extrahiere Komponenten
                        prefix = "ev. Kb. Wetzlar"
                        symbol = match.group(2)
                        jahr = match.group(3)
                        monat = match.group(4).zfill(2)
                        tag = match.group(5).zfill(2)
                        seite = match.group(6)
                        nummer = match.group(7)
                        
                        # Rest des Textes nach der Zitation
                        rest = original_text[match.end():]
                        
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
                        pattern_alt = r"^\s*([⚰∞\u26B0])\s*(\d{4})[\.\s]*(\d{1,2})[\.\s]*(\d{1,2})\.?\s*p\.?\s*(\d+)\s*Nr\.?\s*(\d+)\s*"
                        match_alt = re.match(pattern_alt, original_text)
                        if match_alt:
                            prefix = "ev. Kb. Wetzlar"
                            symbol = match_alt.group(1)
                            jahr = match_alt.group(2)
                            monat = match_alt.group(3).zfill(2)
                            tag = match_alt.group(4).zfill(2)
                            seite = match_alt.group(5)
                            nummer = match_alt.group(6)
                            rest = original_text[match_alt.end():]
                            
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
        """Ersetzt in den ausgewählten Einträgen im Feld 'Erkannter Text' alle 'p(Zahl)' oder 'p (Zahl)' durch 'p. (Zahl)' und speichert in der Datenbank."""
        import re
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return

        count = len(selection)
        if not messagebox.askyesno(
            "p(Zahl) → p. (Zahl) ersetzen",
            f"Möchten Sie die Ersetzung auf {count} Einträge anwenden?\n\n"
            f"Alle Vorkommen von 'p(Zahl)' oder 'p (Zahl)' werden durch 'p. (Zahl)' ersetzt.\n"
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
                    new_text = re.sub(r"p\s?(\d+)", r"p. \1", original_text)
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
        seite_str = f"{seite_int:04d}"  # 4-stellig: 20 -> 0020
        
        # Baue Pattern abhängig von gerader/ungerader Seite
        if seite_int % 2 == 0:
            # Gerade Seite: steht an erster Stelle (S_0020-*.jpg)
            pattern = f"{media_id_prefix}* S_{seite_str}-*.jpg"
            pattern = f"{media_id_prefix}*{seite_str}*.jpg"
        else:
            # Ungerade Seite: steht an zweiter Stelle (S_*-0021.jpg)
            pattern = f"{media_id_prefix}* S_*-{seite_str}.jpg"
            pattern = f"{media_id_prefix}*{seite_str}*.jpg"
        
        treffer = []
        treffer.extend(ordner.glob(pattern))
        
        if not treffer:
            # Zeige alle jpg-Dateien im Ordner zur Diagnose
            alle_jpgs = list(ordner.glob("*.jpg"))
            beispiel_dateien = "\n".join([f"  - {f.name}" for f in alle_jpgs[:10]])
            
            messagebox.showerror(
                "Bild nicht gefunden", 
                f"Kein Bild gefunden für:\n"
                f"Quelle: {quelle['source']}\n"
                f"Media-ID: {media_id}\n"
                f"Jahr: {jahr_int}\n"
                f"Seite: {seite_int} ({seite_str})\n\n"
                f"Suchpfad: {ordner}\n\n"
                f"Gesuchtes Pattern:\n"
                f"  - {pattern}\n\n"
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
            self._reload_images()
    
    def _reload_images(self):
        """Lädt die Bilddateien aus dem aktuellen Verzeichnis neu."""
        new_path = Path(self.image_folder_var.get())
        if not new_path.exists():
            messagebox.showerror("Fehler", f"Verzeichnis existiert nicht:\n{new_path}")
            return
        
        self.base_path = new_path
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
            name_search = self.name_search.get().strip()

            query = (
                "SELECT id, jahr, datum, iso_datum, ereignis_typ, seite, nummer, kirchengemeinde, "
                "vorname, nachname, partner, beruf, stand, todestag, ort, "
                "dateiname, notiz, erkannter_text "
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
                rows = [row for row in rows if pattern.search(str(row[17]))]

            for row in rows:
                # row: id, jahr, datum, iso_datum, ereignis_typ, seite, nummer, kirchengemeinde, vorname, nachname, partner, beruf, todestag, ort, dateiname, notiz, erkannter_text
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
                    safe(12), # Stand
                    safe(13), # Todestag
                    safe(14), # Ort
                    safe(15), # Dateiname
                    safe(16), # Notiz
                    safe(17), # Erkannter Text
                )

                # NEU: Prüfe ob Datum gültig ist
                jahr = safe(1)
                datum = safe(2)
                notiz = safe(10)
                is_valid_date = self._is_valid_date(datum, jahr)

                # Tags setzen
                tags = []
                if notiz:
                    tags.append('has_notiz')
                if not is_valid_date and datum:
                    tags.append('invalid_date')

                self.tree.insert('', tk.END, values=values, tags=tuple(tags))
            
            self.db_status_label.config(text=f"{len(rows)} Datensätze gefunden")
            
            years = self.db.get_all_years()
            self.year_filter['values'] = ['Alle'] + [str(y) for y in years]
            if not self.year_filter.get():
                self.year_filter.current(0)
                
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Laden der Daten:\n{str(e)}")
    
    def _is_valid_date(self, datum: str, jahr: Optional[int]) -> bool:
        """
        Prüft ob ein Datum gültig ist (Jahr zwischen 1500 und 1700).
        
        Args:
            datum: Datumsstring (z.B. "20.11.1564" oder "00.03.1616")
            jahr: Extrahiertes Jahr aus der Datenbank
            
        Returns:
            True wenn gültig, False wenn ungültig
        """
        if not datum:
            return True  # Leeres Datum ist "gültig" (keine Fehlermeldung)
        
        # Prüfe ob Jahr im gültigen Bereich (1500-1700)
        if jahr is not None:
            if jahr < 1500 or jahr > 1700:
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
            
            # Jahr muss zwischen 1500 und 1700 liegen
            if jahr_aus_datum < 1500 or jahr_aus_datum > 1700:
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
        """Sortiert die Treeview nach Seite und dann nach Nummer."""
        # Hole alle Items mit ihren Werten
        import re
        data = []
        for item in self.tree.get_children(''):
            values = self.tree.item(item)['values']
            # Korrekte Indizes: values[5] = Seite, values[6] = Nr, values[15] = Dateiname
            seite = values[5] if len(values) > 5 else ''
            nummer = values[6] if len(values) > 6 else ''
            dateiname = values[15] if len(values) > 15 else ''
            # Filmnummer extrahieren (z.B. F102779700)
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
            data.append((filmnummer, seite_int, nummer_int, item))
        # Sortiere nach Filmnummer (alphanum), dann Seite, dann Nummer
        data.sort(key=lambda x: (x[0], x[1], x[2]))
        # Reorganisiere die Items in der Treeview
        for index, (_, _, _, item) in enumerate(data):
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
    
    def _clear_filters(self):
        """Löscht alle Filter."""
        self.id_filter.delete(0, tk.END)
        self.year_filter.set('Alle')
        self.type_filter.current(0)
        self.filename_filter.current(0)
        self.name_search.delete(0, tk.END)
        self._refresh_db_list()
    
    def _sort_column(self, col):
        """Sortiert die Treeview-Spalte."""
        if col not in self.sort_reverse:
            self.sort_reverse[col] = False
        else:
            self.sort_reverse[col] = not self.sort_reverse[col]
        
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
    
    def _clear_ocr_field_labels(self):
        """Löscht die erkannten Felder im OCR-Tab."""
        for field in self.ocr_field_labels:
            self.ocr_field_labels[field].config(text="—", foreground="gray")
        
        # Lösche auch die gespeicherten erkannten Felder
        if hasattr(self, '_last_recognized_fields'):
            delattr(self, '_last_recognized_fields')
        
        # Setze Status zurück
        self.db_record_status.config(text="", foreground="blue")
    
    def _show_selected_card(self):
        """Zeigt die ausgewählte Karteikarte im OCR-Tab."""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        record_id = self.tree.item(item)['values'][0]
        
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT dateipfad, erkannter_text FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        
        if row:
            dateipfad = Path(row[0])
            erkannter_text = row[1]
            try:
                idx = self.image_files.index(dateipfad)
                self.current_index = idx
                self.current_db_record_id = record_id
                
                # Erkannte Felder im OCR-Tab zurücksetzen
                self._clear_ocr_field_labels()
                
                self._display_current_card()
                
                self.text_display.delete("1.0", tk.END)
                self.text_display.insert("1.0", erkannter_text)
                
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
    
    def _edit_and_reprocess_text(self):
        """Öffnet den Text zum Bearbeiten und verarbeitet ihn mit Post-Processing neu."""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        record_id = self.tree.item(item)['values'][0]
        
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT erkannter_text, dateiname, dateipfad FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        
        if not row:
            return
        
        original_text = row[0]
        dateiname = row[1]
        dateipfad = row[2]
        
        # Erstelle Bearbeitungsfenster - GRÖßER für Bild + Text
        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"Text bearbeiten: {dateiname}")
        edit_window.geometry("1400x800")  # Breit genug für Bild + Text
        
        # Hauptcontainer mit zwei Spalten
        main_frame = ttk.Frame(edit_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # === LINKE SPALTE: Bildanzeige ===
        left_frame = ttk.Frame(main_frame, width=650)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))
        left_frame.pack_propagate(False)
        
        # Info-Label
        ttk.Label(left_frame, text=f"Datenbank-ID: {record_id}", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(left_frame, text=f"Datei: {dateiname}", font=("Arial", 9)).pack(anchor=tk.W, pady=(0, 10))
        
        # Bild laden und anzeigen
        image_label = ttk.Label(left_frame, text="Bild wird geladen...", relief=tk.SUNKEN, anchor=tk.CENTER)
        image_label.pack(fill=tk.BOTH, expand=True)
        
        try:
            image = Image.open(dateipfad)
            
            # Skaliere Bild auf max 600px Breite
            display_width = 600
            aspect_ratio = image.height / image.width
            display_height = int(display_width * aspect_ratio)
            
            image_resized = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
            photo_image = ImageTk.PhotoImage(image_resized)
            
            image_label.configure(image=photo_image, text="")
            image_label.image = photo_image  # Referenz behalten
            
        except Exception as e:
            image_label.configure(text=f"❌ Fehler beim Laden:\n{str(e)}")
        
        # === RECHTE SPALTE: TEXTBEARBEITUNG ===
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Textfeld mit Original
        text_frame = ttk.Frame(right_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(text_frame, text="Erkannter Text (bearbeitbar):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        
        # Scrollbar + Textfeld
        text_container = ttk.Frame(text_frame)
        text_container.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        text_widget = tk.Text(text_container, wrap=tk.WORD, font=("Arial", 14), yscrollcommand=scrollbar.set)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=text_widget.yview)
        
        text_widget.insert("1.0", original_text)
        
        # === SCHNELLEINGABE-BUTTONS (wie im OCR-Tab) ===
        special_chars_frame = ttk.Frame(right_frame)
        special_chars_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(special_chars_frame, text="Schnelleingabe:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        # Buttons in gewünschter Reihenfolge: ev. Kb. Wetzlar - ∞ Heirat - p. - Nr.
        kb_btn = ttk.Button(
            special_chars_frame,
            text="ev. Kb. Wetzlar",
            width=15,
            command=lambda: text_widget.insert(tk.INSERT, "ev. Kb. Wetzlar ")
        )
        kb_btn.pack(side=tk.LEFT, padx=2)
        
        infinity_btn = ttk.Button(
            special_chars_frame, 
            text="∞ Heirat", 
            width=10,
            command=lambda: text_widget.insert(tk.INSERT, "∞")
        )
        infinity_btn.pack(side=tk.LEFT, padx=2)
        
        coffin_btn = ttk.Button(
            special_chars_frame,
            text="⚰ Begraben",
            width=10,
            command=lambda: text_widget.insert(tk.INSERT, "⚰")
        )
        coffin_btn.pack(side=tk.LEFT, padx=2)
        
        p_btn = ttk.Button(
            special_chars_frame,
            text="p.",
            width=5,
            command=lambda: text_widget.insert(tk.INSERT, "p. ")
        )
        p_btn.pack(side=tk.LEFT, padx=2)
        
        nr_btn = ttk.Button(
            special_chars_frame,
            text="Nr.",
            width=5,
            command=lambda: text_widget.insert(tk.INSERT, "Nr. ")
        )
        nr_btn.pack(side=tk.LEFT, padx=2)
        
        # Strg+H Tastenkombination für ∞
        def insert_infinity(event=None):
            text_widget.insert(tk.INSERT, "∞")
            return "break"
        
        text_widget.bind('<Control-h>', insert_infinity)
        text_widget.bind('<Control-H>', insert_infinity)
        
        # Buttons-Frame unten
        button_frame = ttk.Frame(right_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        def apply_postprocessing():
            """Wendet Post-Processing auf den aktuellen Text an."""
            current_text = text_widget.get("1.0", "end-1c")  # WICHTIG: "end-1c" statt tk.END
            
            # Post-Processing anwenden
            from .text_postprocessor import TextPostProcessor
            processor = TextPostProcessor()
            corrected_text = processor.process(current_text, aggressive=False)
            
            # Text ersetzen
            text_widget.delete("1.0", tk.END)
            text_widget.insert("1.0", corrected_text)
            
            # WICHTIG: Setze edit_window als parent, damit es nicht verschwindet!
            # Und verwende after() um das Fenster im Fokus zu halten
            edit_window.focus_force()  # Fokus zurück aufs Edit-Fenster
            
            # Info-Box mit edit_window als Parent
            info_dialog = tk.Toplevel(edit_window)
            info_dialog.title("Erfolg")
            info_dialog.geometry("400x150")
            info_dialog.transient(edit_window)  # Bleibt vor edit_window
            info_dialog.grab_set()  # Modal
            
            ttk.Label(
                info_dialog, 
                text="✅ Text-Korrektur wurde angewendet!\n\n"
                     "Sie können den Text jetzt noch manuell anpassen.\n\n"
                     "Klicken Sie 'Änderungen speichern' wenn Sie fertig sind.",
                font=("Arial", 10),
                justify=tk.LEFT,
                padding=20
            ).pack()
            
            ttk.Button(
                info_dialog, 
                text="OK", 
                command=lambda: [info_dialog.destroy(), edit_window.focus_force()]
            ).pack(pady=10)
            
            # Zentriere Dialog über edit_window
            info_dialog.update_idletasks()
            x = edit_window.winfo_x() + (edit_window.winfo_width() - info_dialog.winfo_width()) // 2
            y = edit_window.winfo_y() + (edit_window.winfo_height() - info_dialog.winfo_height()) // 2
            info_dialog.geometry(f"+{x}+{y}")
        
        def save_changes():
            """Speichert die Änderungen in der Datenbank."""
            new_text = text_widget.get("1.0", "end-1c")  # WICHTIG: "end-1c" für korrekten Vergleich
            
            # Vergleiche mit Original (beide getrimmt)
            if new_text.strip() == original_text.strip():
                if messagebox.askyesno("Keine Änderungen", "Der Text wurde nicht geändert.\n\nTrotzdem schließen?"):
                    edit_window.destroy()
                return
            
            # Bestätigung vor dem Speichern
            if not messagebox.askyesno(
                "Änderungen speichern",
                f"Möchten Sie die Änderungen wirklich in die Datenbank speichern?\n\n"
                f"Datenbank-ID: {record_id}\n"
                f"Datei: {dateiname}"
            ):
                return
            
            # Parse den neuen Text und speichere
            try:
                self.db.save_karteikarte(
                    dateiname=dateiname,
                    dateipfad=dateipfad,
                    erkannter_text=new_text,
                    ocr_methode="manual_edit"
                )
                
                self._refresh_db_list()
                
                # ERST Fenster schließen, DANN Erfolgsmeldung
                edit_window.destroy()
                
                messagebox.showinfo("Erfolg", f"Text wurde aktualisiert!\n\nDatenbank-ID: {record_id}")
                
            except Exception as e:
                messagebox.showerror("Fehler", f"Fehler beim Speichern:\n{str(e)}")
        
        ttk.Button(button_frame, text="🔧 Text-Korrektur anwenden", command=apply_postprocessing).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="💾 Änderungen speichern", command=save_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="❌ Abbrechen", command=edit_window.destroy).pack(side=tk.RIGHT, padx=5)
    
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
            
            record_id = self.db.save_karteikarte(
                dateiname=dateiname,
                dateipfad=dateipfad,
                erkannter_text=text,
                ocr_methode=ocr_methode
            )
            
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
            stats = self.db.get_statistics()
            
            msg = f"""Datenbank-Statistik:
            
Gesamtanzahl Karteikarten: {stats['gesamt']}
Zeitraum: {stats['zeitraum']}

Nach Ereignistyp:"""
            
            for typ, anzahl in stats.get('nach_typ', {}).items():
                typ_name = typ or 'Unbekannt'
                msg += f"\n  - {typ_name}: {anzahl}"
            
            messagebox.showinfo("Statistik", msg)
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
        
        erfolge = 0
        fehler = 0
        
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
