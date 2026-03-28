"""Leseanwendung (Reader) für die Wetzlar Karteikarten-Datenbank.

Zweite, eigenständige Anwendung - NUR LESEN, außer F-ID Bearbeitung per Kontextmenü.
Keine Änderungen an src/gui.py oder anderen bestehenden Dateien.
"""

import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from PIL import Image as PILImage
from PIL import ImageTk

from .config import get_config
from .database import KarteikartenDB
from .extraction_lists import get_sources_with_adjusted_paths
from .gedcom_exporter import GedcomExporter


class KarteikartenReader:
    """Leseanwendung: Zeigt die Datenbank an, erlaubt Suche/Filter.
    Schreibzugriff nur auf F-ID (Notiz-Feld) per Kontextmenü.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Wetzlar Karteikarten – Leser")
        self.root.geometry("1200x800")

        # Config (dieselbe wie Hauptanwendung)
        self.config = get_config()

        # Datenbank
        db_path = self._resolve_db_path()
        self.db = KarteikartenDB(str(db_path))
        self.active_db_path = str(Path(db_path).resolve())

        # Sortierzustand
        self.sort_reverse: dict = {}
        self._last_sorted_column: Optional[str] = None

        # GUI aufbauen
        self._create_widgets()

    # ------------------------------------------------------------------
    # DB-Pfad ermitteln
    # ------------------------------------------------------------------

    def _resolve_db_path(self) -> Path:
        """Ermittelt den DB-Pfad mit denselben Fallbacks wie KarteikartenGUI."""
        configured = (self.config.db_path or "").strip()
        if configured:
            p = Path(configured).expanduser()
            if p.exists():
                return p
            return p

        db_name = "karteikarten.db"
        candidates: List[Path] = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend([exe_dir.parent / db_name, exe_dir / db_name, Path.cwd() / db_name])
        else:
            project_root = Path(__file__).resolve().parent.parent
            candidates.extend([project_root / db_name, Path.cwd() / db_name])

        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    # ------------------------------------------------------------------
    # Widget-Aufbau
    # ------------------------------------------------------------------

    def _create_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        db_tab = ttk.Frame(self.notebook)
        self.notebook.add(db_tab, text="📊 Datenbank")

        settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(settings_tab, text="⚙️ Einstellungen")

        self._create_db_tab(db_tab)
        self._create_settings_tab(settings_tab)

    # ------------------------------------------------------------------
    # Datenbank-Tab
    # ------------------------------------------------------------------

    def _create_db_tab(self, parent):
        # === FILTERBEREICH ===
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill=tk.X, padx=10, pady=10)

        # Zeile 1: Einfache Filter
        filter_row1 = ttk.Frame(filter_frame)
        filter_row1.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(filter_row1, text="ID:").pack(side=tk.LEFT, padx=5)
        self.id_filter = ttk.Entry(filter_row1, width=8)
        self.id_filter.pack(side=tk.LEFT, padx=5)

        ttk.Label(filter_row1, text="Jahr:").pack(side=tk.LEFT, padx=(10, 5))
        self.year_filter = ttk.Combobox(filter_row1, width=10, state="readonly")
        self.year_filter.pack(side=tk.LEFT, padx=5)
        self.year_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_db_list())

        ttk.Label(filter_row1, text="Typ:").pack(side=tk.LEFT, padx=(10, 5))
        self.type_filter = ttk.Combobox(filter_row1, width=15, state="readonly")
        self.type_filter["values"] = ["Alle", "Heirat", "Taufe", "Begräbnis", "(Leere)"]
        self.type_filter.current(0)
        self.type_filter.pack(side=tk.LEFT, padx=5)
        self.type_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_db_list())

        ttk.Label(filter_row1, text="Datei:").pack(side=tk.LEFT, padx=(10, 5))
        self.filename_filter = ttk.Combobox(filter_row1, width=10, state="readonly")
        self.filename_filter["values"] = ["Alle", "Sb", "Hb", "Gb"]
        self.filename_filter.current(0)
        self.filename_filter.pack(side=tk.LEFT, padx=5)
        self.filename_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_db_list())

        ttk.Label(filter_row1, text="Kirchenbuch:").pack(side=tk.LEFT, padx=(10, 5))
        self.kirchenbuch_filter = ttk.Combobox(filter_row1, width=16, state="readonly")
        self.kirchenbuch_filter["values"] = ["Alle"]
        self.kirchenbuch_filter.current(0)
        self.kirchenbuch_filter.pack(side=tk.LEFT, padx=5)
        self.kirchenbuch_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_db_list())

        # Zeile 2: Textsuche
        filter_row2 = ttk.Frame(filter_frame)
        filter_row2.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(filter_row2, text="Name/Text:").pack(side=tk.LEFT, padx=5)
        self.name_search = ttk.Entry(filter_row2, width=30)
        self.name_search.pack(side=tk.LEFT, padx=5)
        self.name_search.bind("<Return>", lambda e: self._refresh_db_list())

        self.regex_search_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_row2, text="Regex", variable=self.regex_search_var).pack(side=tk.LEFT, padx=5)

        ttk.Button(filter_row2, text="🔍 Suchen", command=self._refresh_db_list).pack(side=tk.LEFT, padx=5)

        # Zeile 3: Aktions-Buttons
        filter_row3 = ttk.Frame(filter_frame)
        filter_row3.pack(fill=tk.X)

        ttk.Button(filter_row3, text="✕ Filter löschen", command=self._clear_filters).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_row3, text="🔄 Aktualisieren", command=self._refresh_db_list).pack(side=tk.LEFT, padx=5)

        ttk.Separator(filter_row3, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(filter_row3, text="⛶ Leere auswählen", command=self._select_empty_in_sorted_column).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_row3, text="📑 Nach Seite/Nr.", command=self._sort_by_page_and_number).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_row3, text="📊 Statistik", command=self._show_statistics).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_row3, text="💾 Backup CSV", command=self._backup_csv).pack(side=tk.LEFT, padx=5)

        # === TREEVIEW ===
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        columns = (
            "ID", "Jahr", "Datum", "ISO_datum", "Typ", "Seite", "Nr", "Gemeinde",
            "Vorname", "Nachname", "Partner", "Beruf", "Ort",
            "Bräutigam Vater", "Braut Vater", "Braut Nachname", "Braut Ort",
            "Bräutigam Stand", "Braut Stand", "Todestag", "Geb.Jahr (gesch.)",
            "Dateiname", "Notiz", "Gramps", "Text",
        )
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="extended",
        )
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self._sort_column(c))
        self.tree.heading("Notiz", text="F-ID", command=lambda: self._sort_column("Notiz"))
        self.tree.heading("Text", text="Erkannter Text", command=lambda: self._sort_column("Text"))
        self.tree.heading("ISO_datum", text="ISO Datum", command=lambda: self._sort_column("ISO_datum"))

        col_widths = {
            "ID": 20, "Jahr": 40, "Datum": 70, "ISO_datum": 70, "Typ": 60,
            "Seite": 40, "Nr": 40, "Gemeinde": 80,
            "Vorname": 80, "Nachname": 80, "Partner": 100, "Beruf": 80, "Ort": 80,
            "Bräutigam Vater": 100, "Braut Vater": 100, "Braut Nachname": 100, "Braut Ort": 80,
            "Bräutigam Stand": 70, "Braut Stand": 70,
            "Todestag": 80, "Geb.Jahr (gesch.)": 60,
            "Dateiname": 80, "Notiz": 50, "Gramps": 50, "Text": 400,
        }
        for col, w in col_widths.items():
            self.tree.column(col, width=w, anchor="w" if col not in ("ID", "Jahr", "Seite", "Nr", "Notiz", "ISO_datum", "Datum") else "center")

        self._apply_column_widths()

        style = ttk.Style()
        style.configure("Treeview", rowheight=30)
        self.tree.tag_configure("has_notiz", background="#d4edda")
        self.tree.tag_configure("has_kirchenbuchtext", background="#c3f0ca")
        self.tree.tag_configure("has_gramps", background="#cfe2ff")
        self.tree.tag_configure("invalid_date", foreground="#dc3545", font=("Arial", 9, "bold"))

        self.tree.pack(fill=tk.BOTH, expand=True)

        # Spaltenbreiten-Tracking
        self.tree.bind("<Button-1>", self._on_column_resize, add="+")

        # Kontextmenü
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="F-ID bearbeiten", command=self._edit_fid)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Karteikarte anzeigen", command=self._show_selected_card_image)
        self.tree_menu.add_command(label="Kirchenbuch anzeigen", command=self._show_selected_kirchenbuch)
        self.tree_menu.add_command(label="Text anzeigen", command=self._show_selected_text)
        self.tree_menu.add_command(label="GEDCOM exportieren (Auswahl)", command=self._export_gedcom_selected_from_context)
        self.tree_menu.add_command(label="Auswahl kopieren", command=self._copy_selected_rows_to_clipboard)
        self.tree.bind("<Button-3>", self._show_tree_menu)

        # Statusleiste
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        self.db_status_label = ttk.Label(status_frame, text="Keine Daten geladen")
        self.db_status_label.pack(side=tk.LEFT)

        # Initial laden
        self._refresh_db_list()

    # ------------------------------------------------------------------
    # Einstellungen-Tab
    # ------------------------------------------------------------------

    def _create_settings_tab(self, parent):
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(main_frame, text="⚙️ Einstellungen", font=("Arial", 16, "bold")).pack(pady=(0, 20))

        # === Laufwerk ===
        drive_frame = ttk.LabelFrame(main_frame, text="Kirchenbuch-Medien Pfade", padding=15)
        drive_frame.pack(fill=tk.X, pady=(0, 20))

        ttk.Label(drive_frame, text="Basis-Laufwerk für Kirchenbuch-Medien:").pack(anchor=tk.W, pady=(0, 5))
        ttk.Label(
            drive_frame,
            text=f"Aktuell: {self.config.media_drive}\\...\\Kirchenbücher\\...",
            foreground="blue",
        ).pack(anchor=tk.W, pady=(0, 10))

        drive_input_frame = ttk.Frame(drive_frame)
        drive_input_frame.pack(fill=tk.X)
        ttk.Label(drive_input_frame, text="Laufwerk:").pack(side=tk.LEFT, padx=(0, 5))
        self.drive_var = tk.StringVar(value=self.config.media_drive)
        ttk.Entry(drive_input_frame, textvariable=self.drive_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(drive_input_frame, text="📁 Verzeichnis wählen", command=self._choose_media_drive).pack(side=tk.LEFT, padx=5)
        ttk.Button(drive_input_frame, text="💾 Speichern", command=self._save_media_drive).pack(side=tk.LEFT, padx=20)

        ttk.Label(
            drive_frame,
            text="Wählen Sie das Basis-Laufwerk/Verzeichnis für die Kirchenbuch-Medien.\n"
                 "Beispiel: E: oder D:\\Dokumente\\Kirchenbücher",
            foreground="gray",
            font=("Arial", 9, "italic"),
        ).pack(anchor=tk.W, pady=(10, 0))

        ttk.Label(drive_frame, text="Kirchenbuch-Basisverzeichnis (für umgezogene Ordner):").pack(anchor=tk.W, pady=(12, 4))
        kb_base_row = ttk.Frame(drive_frame)
        kb_base_row.pack(fill=tk.X)

        self.kb_base_path_var = tk.StringVar(value=self.config.get("kirchenbuch_base_path", ""))
        ttk.Entry(kb_base_row, textvariable=self.kb_base_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(kb_base_row, text="📁 Wählen", command=self._choose_kb_base_path).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(kb_base_row, text="✅ Übernehmen", command=self._apply_kb_base_path).pack(side=tk.LEFT)

        ttk.Label(
            drive_frame,
            text="Wenn die Kirchenbuchseiten nicht mehr unter dem alten E:-Pfad liegen,"
                 " wird hiermit der gemeinsame neue Wurzelordner gesetzt.",
            foreground="gray",
            font=("Arial", 9, "italic"),
        ).pack(anchor=tk.W, pady=(4, 0))

        # === Karteikarten-Basisverzeichnis ===
        card_frame = ttk.LabelFrame(main_frame, text="Karteikarten-Bilder", padding=15)
        card_frame.pack(fill=tk.X, pady=(0, 20))

        ttk.Label(card_frame, text="Karteikarten-Basisverzeichnis:").pack(anchor=tk.W, pady=(0, 4))
        card_base_row = ttk.Frame(card_frame)
        card_base_row.pack(fill=tk.X)

        self.card_base_path_var = tk.StringVar(value=self.config.image_base_path)
        ttk.Entry(card_base_row, textvariable=self.card_base_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(card_base_row, text="📁 Wählen", command=self._choose_card_base_path).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(card_base_row, text="✅ Übernehmen", command=self._apply_card_base_path).pack(side=tk.LEFT)

        ttk.Label(
            card_frame,
            text="Der Reader versucht bei fehlenden dateipfad-Einträgen automatisch,"
                 " den gespeicherten Unterpfad unter diesem neuen Basisordner wiederzufinden.",
            foreground="gray",
            font=("Arial", 9, "italic"),
        ).pack(anchor=tk.W, pady=(4, 0))

        # === Datenbankpfad ===
        db_frame = ttk.LabelFrame(main_frame, text="Datenbankpfad", padding=15)
        db_frame.pack(fill=tk.X, pady=(0, 20))

        ttk.Label(db_frame, text="Datenbank-Datei (.db):").pack(anchor=tk.W, pady=(0, 4))
        db_path_row = ttk.Frame(db_frame)
        db_path_row.pack(fill=tk.X, pady=(0, 6))

        self.settings_db_path_var = tk.StringVar(value=self.active_db_path)
        ttk.Entry(db_path_row, textvariable=self.settings_db_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(db_path_row, text="📁 Wählen", command=self._choose_settings_db_path).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(db_path_row, text="💾 DB laden", command=self._apply_settings_db_path).pack(side=tk.LEFT)

        self.db_path_info_label = ttk.Label(db_frame, text=f"Aktive DB: {self.active_db_path}", foreground="blue")
        self.db_path_info_label.pack(anchor=tk.W, pady=(4, 0))

        ttk.Label(
            db_frame,
            text="Hinweis: Im EXE-Betrieb kann die DB an einem anderen Ort liegen."
                 " Hier können Sie die richtige DB-Datei dauerhaft auswählen.",
            foreground="gray",
            font=("Arial", 9, "italic"),
        ).pack(anchor=tk.W, pady=(4, 0))

        # === Spaltenbreiten ===
        column_frame = ttk.LabelFrame(main_frame, text="Datenbank-Ansicht", padding=15)
        column_frame.pack(fill=tk.X, pady=(0, 20))

        ttk.Label(
            column_frame,
            text="Die Spaltenbreiten der Datenbank-Tabelle werden automatisch\n"
                 "beim Ändern gespeichert und beim nächsten Start wiederhergestellt.",
            foreground="gray",
        ).pack(anchor=tk.W)

        ttk.Button(column_frame, text="🔄 Spaltenbreiten zurücksetzen", command=self._reset_column_widths).pack(
            anchor=tk.W, pady=(10, 0)
        )

    # ------------------------------------------------------------------
    # Daten laden & filtern
    # ------------------------------------------------------------------

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
                    query += " AND id = ?"
                    params.append(int(id_filter))
                except ValueError:
                    messagebox.showwarning("Ungültige ID", "Bitte eine gültige Zahl für die ID eingeben.")
                    return

            if year_filter and year_filter != "Alle":
                query += " AND jahr = ?"
                params.append(int(year_filter))

            if type_filter and type_filter != "Alle":
                if type_filter == "(Leere)":
                    query += " AND (ereignis_typ IS NULL OR ereignis_typ = '')"
                else:
                    query += " AND ereignis_typ = ?"
                    params.append(type_filter)

            if filename_filter and filename_filter != "Alle":
                query += " AND LOWER(dateiname) LIKE ?"
                params.append(f"%{filename_filter.lower()}%")

            regex_mode = getattr(self, "regex_search_var", None)
            if name_search:
                if regex_mode and regex_mode.get():
                    pass  # Regex-Filter später
                else:
                    query += " AND erkannter_text LIKE ?"
                    params.append(f"%{name_search}%")

            query += " ORDER BY jahr DESC, datum DESC, nummer"

            cursor = self.db.conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            if name_search and regex_mode and regex_mode.get():
                import re
                try:
                    pattern = re.compile(name_search)
                except re.error as e:
                    messagebox.showerror("Regex-Fehler", f"Ungültiger regulärer Ausdruck:\n{e}")
                    self.db_status_label.config(text="0 Datensätze gefunden (Regex-Fehler)")
                    return
                rows = [row for row in rows if pattern.search(str(row[23]))]

            if kirchenbuch_filter and kirchenbuch_filter != "Alle":
                rows = [
                    row for row in rows
                    if self._extract_kirchenbuch_titel(row[21]) == kirchenbuch_filter
                ]

            for row in rows:
                def safe(idx):
                    try:
                        return row[idx] if row[idx] is not None else ""
                    except IndexError:
                        return ""

                values = (
                    safe(0), safe(1), safe(2), safe(3), safe(4),
                    safe(5), safe(6), safe(7), safe(8), safe(9),
                    safe(10), safe(11), safe(12), safe(13), safe(14),
                    safe(15), safe(16), safe(17), safe(18), safe(19),
                    safe(20), safe(21), safe(22), safe(25), safe(23),
                )

                notiz = safe(22)
                kirchenbuchtext = safe(24)
                gramps = safe(25)
                jahr = safe(1)
                datum = safe(2)
                is_valid_date = self._is_valid_date(datum, jahr)

                tags = []
                if notiz:
                    tags.append("has_notiz")
                if kirchenbuchtext:
                    tags.append("has_kirchenbuchtext")
                if gramps:
                    tags.append("has_gramps")
                if not is_valid_date and datum:
                    tags.append("invalid_date")

                self.tree.insert("", tk.END, values=values, tags=tuple(tags))

            self.db_status_label.config(text=f"{len(rows)} Datensätze gefunden")

            years = self.db.get_all_years()
            self.year_filter["values"] = ["Alle"] + [str(y) for y in years]
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
            self.kirchenbuch_filter["values"] = ["Alle"] + kb_values
            if current_kb in self.kirchenbuch_filter["values"]:
                self.kirchenbuch_filter.set(current_kb)
            else:
                self.kirchenbuch_filter.current(0)

        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Laden der Daten:\n{str(e)}")

    def _is_valid_date(self, datum: str, jahr) -> bool:
        if not datum:
            return True
        if jahr is not None:
            try:
                if int(jahr) < 1500 or int(jahr) > 1754:
                    return False
            except (ValueError, TypeError):
                pass
        match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", str(datum))
        if not match:
            return False
        tag_str, monat_str, jahr_str = match.groups()
        try:
            tag = int(tag_str)
            monat = int(monat_str)
            j = int(jahr_str)
            if j < 1500 or j > 1754:
                return False
            if monat < 1 or monat > 12:
                return False
            if tag != 0 and (tag < 1 or tag > 31):
                return False
            return True
        except (ValueError, TypeError):
            return False

    def _extract_kirchenbuch_titel(self, dateiname: str) -> str:
        """Extrahiert 'Hb 1695-1718' aus Dateinamen wie '3282 Hb 1717 - 1695-1718 - F....jpg'."""
        if not dateiname:
            return ""
        match = re.search(r"\b([A-Z][a-z])\s+\d{4}\s+-\s*(\d{4}-\d{4})", str(dateiname))
        if not match:
            return ""
        return f"{match.group(1)} {match.group(2)}"

    # ------------------------------------------------------------------
    # Filter-Aktionen
    # ------------------------------------------------------------------

    def _clear_filters(self):
        self.id_filter.delete(0, tk.END)
        self.year_filter.set("Alle")
        self.type_filter.current(0)
        self.filename_filter.current(0)
        self.kirchenbuch_filter.current(0)
        self.name_search.delete(0, tk.END)
        self._refresh_db_list()

    # ------------------------------------------------------------------
    # Spalten sortieren
    # ------------------------------------------------------------------

    def _sort_column(self, col):
        self.sort_reverse[col] = not self.sort_reverse.get(col, False)
        self._last_sorted_column = col
        reverse = self.sort_reverse[col]
        numeric_columns = ["ID", "Jahr", "Seite", "Nr"]
        data = [(self.tree.set(item, col), item) for item in self.tree.get_children("")]

        if col in numeric_columns:
            def numeric_key(v):
                try:
                    return int(v[0]) if v[0] else 0
                except (ValueError, TypeError):
                    return 0
            data.sort(key=numeric_key, reverse=reverse)
        elif col == "Datum":
            def date_key(v):
                val = v[0]
                if not val:
                    return "0000-00-00"
                try:
                    parts = val.split(".")
                    if len(parts) == 3:
                        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    pass
                return "0000-00-00"
            data.sort(key=date_key, reverse=reverse)
        else:
            data.sort(reverse=reverse)

        for index, (_, item) in enumerate(data):
            self.tree.move(item, "", index)

        for column in self.tree["columns"]:
            heading_text = self.tree.heading(column)["text"]
            clean = heading_text.replace(" ▲", "").replace(" ▼", "")
            if column == col:
                self.tree.heading(column, text=clean + (" ▲" if not reverse else " ▼"))
            else:
                self.tree.heading(column, text=clean)

        self._last_sorted_column = col

    def _select_empty_in_sorted_column(self):
        col = self._last_sorted_column
        if not col:
            messagebox.showinfo("Hinweis", "Bitte zuerst eine Spalte sortieren.")
            return
        col_index = list(self.tree["columns"]).index(col)
        items_to_keep = []
        for item in self.tree.get_children(""):
            values = self.tree.item(item)["values"]
            if col_index < len(values) and (values[col_index] is None or str(values[col_index]).strip() == ""):
                items_to_keep.append((item, values))
        for item in self.tree.get_children(""):
            self.tree.delete(item)
        for item_id, values in items_to_keep:
            self.tree.insert("", "end", iid=item_id, values=values)
        self.db_status_label.config(text=f"{len(items_to_keep)} Datensätze gefunden")
        if not items_to_keep:
            messagebox.showinfo("Keine leeren Felder", f"Keine leeren Felder in der Spalte '{col}' gefunden.")

    def _sort_by_page_and_number(self):
        import re as _re
        data = []
        for item in self.tree.get_children(""):
            values = self.tree.item(item)["values"]
            seite = values[5] if len(values) > 5 else ""
            nummer = values[6] if len(values) > 6 else ""
            dateiname = values[21] if len(values) > 21 else ""
            filmnummer = ""
            m = _re.search(r"(F\d{9,})", str(dateiname))
            if m:
                filmnummer = m.group(1)
            try:
                seite_int = int(seite) if seite else 0
            except (ValueError, TypeError):
                seite_int = 0
            try:
                nummer_int = int(nummer) if nummer else 0
            except (ValueError, TypeError):
                nummer_int = 0
            data.append((filmnummer, seite_int, nummer_int, dateiname, item))
        data.sort(key=lambda x: (x[0] if x[0] else "ZZZZZZ", x[1], x[2]))
        for index, (_, _, _, _, item) in enumerate(data):
            self.tree.move(item, "", index)
        for column in self.tree["columns"]:
            clean = self.tree.heading(column)["text"].replace(" ▲", "").replace(" ▼", "")
            if column in ("Dateiname", "Seite", "Nr"):
                self.tree.heading(column, text=clean + " ▲")
            else:
                self.tree.heading(column, text=clean)
        self.db_status_label.config(text=f"{len(data)} Datensätze – sortiert nach Film/Seite/Nr.")

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def _backup_csv(self):
        """Exportiert die gesamte Datenbank als CSV mit Datum/Uhrzeit im Dateinamen."""
        import csv
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"karteikarten_reader_backup_{timestamp}.csv"

        filepath = filedialog.asksaveasfilename(
            title="Backup speichern",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")],
        )
        if not filepath:
            return

        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT * FROM karteikarten ORDER BY id")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]

            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(col_names)
                writer.writerows(rows)

            messagebox.showinfo(
                "Backup erstellt",
                f"{len(rows)} Datensätze exportiert nach:\n{filepath}",
            )
        except Exception as e:
            messagebox.showerror("Fehler", f"Backup fehlgeschlagen:\n{e}")

    # ------------------------------------------------------------------
    # Statistik
    # ------------------------------------------------------------------

    def _show_statistics(self):
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM karteikarten")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT ereignis_typ, COUNT(*) FROM karteikarten GROUP BY ereignis_typ ORDER BY ereignis_typ")
        typ_stats = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM karteikarten WHERE notiz IS NOT NULL AND notiz != ''")
        with_fid = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM karteikarten WHERE gramps IS NOT NULL AND gramps != ''")
        with_gramps = cursor.fetchone()[0]

        # Je Typ: KB-Titel (aus dateiname) mit Anzahl Einträge + ISO-Datumsbereich
        cursor.execute(
            "SELECT ereignis_typ, dateiname, iso_datum FROM karteikarten ORDER BY ereignis_typ, dateiname"
        )
        kb_rows = cursor.fetchall()

        # dateiname-Muster: "NNNN Hb 1630 - 1611-1632 - F102779699_erf.jpg"
        # KB-Titel = Typ-Kürzel + Jahresbereich, z.B. "Hb 1611-1632"
        _kb_title_pattern = re.compile(r"\b([A-Z][a-z])\s+\d{4}\s+-\s*(\d{4}-\d{4})")

        from collections import defaultdict

        # {ereignis_typ -> {kb_titel -> {"count": int, "min_iso": str, "max_iso": str}}}
        kb_per_typ: dict = defaultdict(lambda: defaultdict(lambda: {"count": 0, "min_iso": None, "max_iso": None}))
        for ereignis_typ, dateiname, iso_datum in kb_rows:
            typ_key = ereignis_typ or "(leer)"
            if dateiname:
                m = _kb_title_pattern.search(str(dateiname))
                kb_titel = f"{m.group(1)} {m.group(2)}" if m else "(unbekannt)"
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
            f"Gesamt: {total} Datensätze",
            f"Mit F-ID: {with_fid}",
            f"Mit Gramps: {with_gramps}",
            "",
            "Nach Ereignistyp:",
        ]
        for typ, count in typ_stats:
            typ_label = typ or "(leer)"
            lines.append(f"  {typ_label}: {count}")

        lines.append("")
        lines.append("Kirchenbücher je Typ:")
        for typ, count in typ_stats:
            typ_label = typ or "(leer)"
            lines.append(f"\n  [{typ_label}]")
            kb_map = kb_per_typ.get(typ_label, {})
            for kb_titel, data in sorted(kb_map.items()):
                min_iso = data["min_iso"] or "?"
                max_iso = data["max_iso"] or "?"
                lines.append(f"    {kb_titel:<16}  {data['count']:>4}  {min_iso} – {max_iso}")

        win = tk.Toplevel(self.root)
        win.title("Statistik")
        win.geometry("540x520")
        txt = tk.Text(win, font=("Arial", 11), wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        txt.insert("1.0", "\n".join(lines))
        txt.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Kontextmenü-Aktionen
    # ------------------------------------------------------------------

    def _show_tree_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)

    def _edit_fid(self):
        """Öffnet Dialog zum Bearbeiten der F-ID (Notiz-Feld) – einziger Schreibzugriff."""
        selection = self.tree.selection()
        if not selection:
            return

        item = selection[0]
        record_id = self.tree.item(item)["values"][0]

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT notiz, dateiname FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return

        current_fid = row[0] if row[0] else ""
        dateiname = row[1]

        dialog = tk.Toplevel(self.root)
        dialog.title(f"F-ID bearbeiten: {dateiname}")
        dialog.geometry("400x150")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="F-ID:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=20, pady=(20, 5))
        entry_var = tk.StringVar(value=current_fid)
        entry = ttk.Entry(dialog, textvariable=entry_var, font=("Arial", 12), width=30)
        entry.pack(padx=20, pady=5)
        entry.focus()
        entry.select_range(0, tk.END)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)

        def save_fid():
            new_fid = entry_var.get().strip()
            c = self.db.conn.cursor()
            c.execute("UPDATE karteikarten SET notiz = ? WHERE id = ?", (new_fid, record_id))
            self.db.conn.commit()
            values = list(self.tree.item(item)["values"])
            values[22] = new_fid  # Notiz-Spalte (Index 22)
            self.tree.item(item, values=values)
            current_tags = list(self.tree.item(item)["tags"])
            if new_fid:
                if "has_notiz" not in current_tags:
                    current_tags.append("has_notiz")
            else:
                if "has_notiz" in current_tags:
                    current_tags.remove("has_notiz")
            self.tree.item(item, tags=current_tags)
            dialog.destroy()

        ttk.Button(btn_frame, text="Speichern", command=save_fid).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Abbrechen", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        entry.bind("<Return>", lambda e: save_fid())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _show_selected_card_image(self):
        """Zeigt die Karteikarte (OCR-Bild) aus dem dateipfad-Feld der Datenbank."""
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        record_id = self.tree.item(item)["values"][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT dateipfad, dateiname FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            messagebox.showwarning("Kein Bild", "Für diesen Eintrag ist kein Karteikarten-Bild gespeichert.")
            return
        # Nutze zuerst den aktuell eingegebenen Wert aus den Einstellungen (falls vorhanden),
        # damit die Bildsuche sofort funktioniert, auch ohne explizites "Übernehmen".
        card_base_path = self.card_base_path_var.get().strip() if hasattr(self, "card_base_path_var") else ""
        pfad = self._resolve_relocated_path(Path(row[0]), card_base_path or self.config.image_base_path)
        if not pfad.exists():
            messagebox.showerror("Datei nicht gefunden", f"Karteikarte nicht gefunden:\n{pfad}")
            return
        self._open_image_viewer(str(pfad))

    def _show_selected_kirchenbuch(self):
        """Zeigt das zugehörige Kirchenbuchbild (nutzt SOURCES-Konfiguration)."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie einen Eintrag aus.")
            return

        item = selection[0]
        values = self.tree.item(item)["values"]
        typ = values[4]    # Typ
        jahr = values[1]   # Jahr
        seite = values[5]  # Seite

        try:
            jahr_int = int(jahr)
        except Exception:
            messagebox.showerror("Ungültiges Jahr", f"Das Jahr '{jahr}' ist ungültig.")
            return
        try:
            seite_int = int(seite)
        except Exception:
            messagebox.showerror("Ungültige Seite", f"Die Seite '{seite}' ist ungültig.")
            return

        # Typ-Kürzel ermitteln
        typ_kuerzel = None
        if typ == "Begräbnis":
            typ_kuerzel = "Sb"
        elif typ == "Heirat":
            typ_kuerzel = "Hb"
        elif typ in ("Taufe", "Geburt"):
            typ_kuerzel = "Gb"

        # Passende Quelle aus den aktuell konfigurierten Quellen suchen
        sources = get_sources_with_adjusted_paths()
        passende_quellen = []
        for source in sources:
            if source.get("media_type") != "kirchenbuchseiten":
                continue
            if not source.get("media_ID") or not source.get("media_path"):
                continue
            m = re.search(r"(\d{4})-(\d{4})", source.get("source", ""))
            if m:
                if int(m.group(1)) <= jahr_int <= int(m.group(2)):
                    media_id = source.get("media_ID", "")
                    if typ_kuerzel and media_id.endswith(f"_{typ_kuerzel}"):
                        passende_quellen.append(source)

        if not passende_quellen:
            messagebox.showerror(
                "Keine Quelle gefunden",
                f"Keine passende Kirchenbuch-Quelle für:\nTyp: {typ}, Jahr: {jahr_int}\n\n"
                f"Prüfen Sie die SOURCES-Konfiguration in extraction_lists.py.",
            )
            return

        quelle = passende_quellen[0]
        media_id = quelle["media_ID"]
        kb_base_path = (
            self.kb_base_path_var.get().strip()
            if hasattr(self, "kb_base_path_var") and self.kb_base_path_var.get().strip()
            else self.config.get("kirchenbuch_base_path", "")
        )
        ordner = self._resolve_relocated_path(Path(quelle["media_path"]), kb_base_path)

        if not ordner.exists():
            messagebox.showerror("Ordner nicht gefunden", f"Suchpfad existiert nicht:\n{ordner}")
            return

        media_id_prefix = media_id[:-3]  # z.B. "EKiR_408_021_Hb" → "EKiR_408_021"
        seite_str_3 = f"{seite_int:03d}"
        seite_str_4 = f"{seite_int:04d}"

        patterns = [
            f"{media_id_prefix}* S_{seite_str_4}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_4}.jpg",
            f"{media_id_prefix}* S_{seite_str_4}_*.jpg",
            f"{media_id_prefix}* S_*_{seite_str_4}.jpg",
            f"{media_id_prefix}*_{seite_str_4}.jpg",
            f"{media_id_prefix}* S_{seite_str_3}-*.jpg",
            f"{media_id_prefix}* S_*-{seite_str_3}.jpg",
            f"{media_id_prefix}* S_{seite_str_3}_*.jpg",
            f"{media_id_prefix}* S_*_{seite_str_3}.jpg",
            f"{media_id_prefix}*_{seite_str_3}.jpg",
        ]

        treffer = []
        for pattern in patterns:
            treffer.extend(ordner.glob(pattern))
        treffer = list(set(treffer))

        if not treffer:
            alle_jpgs = list(ordner.glob("*.jpg"))
            beispiele = "\n".join(f"  - {f.name}" for f in alle_jpgs[:10])
            messagebox.showerror(
                "Bild nicht gefunden",
                f"Kein Bild für Seite {seite_int} gefunden.\n"
                f"Quelle: {quelle['source']}\nSuchpfad: {ordner}\n\n"
                f"Beispieldateien im Ordner:\n{beispiele}",
            )
            return

        if len(treffer) > 1:
            messagebox.showwarning(
                "Mehrere Bilder gefunden",
                "Mehrere Bilder gefunden. Es wird das erste angezeigt:\n"
                + "\n".join(t.name for t in treffer),
            )

        self._open_image_viewer(str(treffer[0]))

    def _resolve_relocated_path(self, original_path: Path, base_path: str) -> Path:
        """Versucht einen gespeicherten Altpfad unter einem neuen Basisordner wiederzufinden."""
        if original_path.exists():
            return original_path

        configured_base = (base_path or "").strip()
        if not configured_base:
            return original_path

        base = Path(configured_base).expanduser()
        if not base.exists():
            return original_path

        parts = list(original_path.parts)
        for start_idx in range(1, len(parts)):
            candidate = base / Path(*parts[start_idx:])
            if candidate.exists():
                return candidate

        return base / original_path.name

    def _open_image_viewer(self, pfad: str):
        """Öffnet ein Fenster zur Bildanzeige mit Zoom und Panning."""
        viewer = tk.Toplevel(self.root)
        viewer.title(f"Bildanzeige: {Path(pfad).name}")
        viewer.geometry("1200x900")

        img = PILImage.open(pfad)
        zoom = 1.0

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

        _state = {"zoom": 1.0, "tk_img": None}

        def show_img():
            w = int(img.width * _state["zoom"])
            h = int(img.height * _state["zoom"])
            resized = img.resize((w, h), PILImage.LANCZOS)
            _state["tk_img"] = ImageTk.PhotoImage(resized)
            canvas.delete("all")
            canvas.create_image(0, 0, anchor=tk.NW, image=_state["tk_img"])
            canvas.config(scrollregion=(0, 0, w, h))

        def zoom_in():
            _state["zoom"] *= 1.2
            show_img()

        def zoom_out():
            _state["zoom"] /= 1.2
            show_img()

        show_img()

        btn_frame = ttk.Frame(viewer)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Zoom +", command=zoom_in).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Zoom -", command=zoom_out).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Schließen", command=viewer.destroy).pack(side=tk.RIGHT, padx=5)

        canvas.bind("<MouseWheel>", lambda e: zoom_in() if e.delta > 0 else zoom_out())
        canvas.bind("<ButtonPress-1>", lambda e: canvas.scan_mark(e.x, e.y))
        canvas.bind("<B1-Motion>", lambda e: canvas.scan_dragto(e.x, e.y, gain=1))

    def _show_selected_text(self):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        record_id = self.tree.item(item)["values"][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT erkannter_text, kirchenbuchtext, dateiname FROM karteikarten WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return

        erkannter_text = row[0] or ""
        kirchenbuchtext = row[1] or ""
        dateiname = row[2]

        win = tk.Toplevel(self.root)
        win.title(f"Text: {dateiname}")
        win.geometry("600x500")

        # Oberes Textfeld: Karteikarte
        ttk.Label(win, text="Karteikarte (erkannter Text):", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 2))
        txt_karte = tk.Text(win, wrap=tk.WORD, font=("Arial", 12), height=8)
        txt_karte.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        txt_karte.insert("1.0", erkannter_text)
        txt_karte.config(state=tk.DISABLED)

        ttk.Separator(win, orient="horizontal").pack(fill=tk.X, padx=10, pady=4)

        # Unteres Textfeld: Kirchenbuchtext
        ttk.Label(win, text="Kirchenbucheintrag:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10, pady=(2, 2))
        txt_kb = tk.Text(win, wrap=tk.WORD, font=("Arial", 12), height=8)
        txt_kb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        txt_kb.insert("1.0", kirchenbuchtext if kirchenbuchtext else "(kein Kirchenbucheintrag hinterlegt)")
        txt_kb.config(state=tk.DISABLED)

    def _export_gedcom_selected_from_context(self):
        """Exportiert die ausgewählten Datensätze aus dem Kontextmenü als GEDCOM."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte wählen Sie mindestens einen Datensatz aus.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".ged",
            initialfile="karteikarten_export_auswahl.ged",
            filetypes=[("GEDCOM-Dateien", "*.ged"), ("Alle Dateien", "*.*")],
        )
        if not filepath:
            return

        try:
            exporter = GedcomExporter(self.db.conn)
            id_list = []
            for item in selection:
                record_id = self.tree.item(item)["values"][0]
                id_list.append(record_id)

            exported_count = exporter.export_to_gedcom(filepath, {"id_list": id_list})

            messagebox.showinfo(
                "Erfolg",
                f"GEDCOM-Export erfolgreich!\n\n"
                f"Datei: {Path(filepath).name}\n"
                f"Exportierte Datensätze (Auswahl): {exported_count}\n"
                f"Format: GRAMPS-Dialekt",
            )
        except ValueError as e:
            messagebox.showwarning("Keine Daten", str(e))
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim GEDCOM-Export:\n{str(e)}")

    def _copy_selected_rows_to_clipboard(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl", "Bitte mindestens einen Eintrag auswählen.")
            return
        columns = list(self.tree["columns"])
        header = "\t".join(columns)
        rows = []
        for item in selection:
            values = self.tree.item(item).get("values", [])
            rows.append("\t".join("" if v is None else str(v) for v in values))
        text = "\n".join([header] + rows)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    # ------------------------------------------------------------------
    # Spaltenbreiten
    # ------------------------------------------------------------------

    def _apply_column_widths(self):
        if not hasattr(self, "tree"):
            return
        column_map = {
            "ID": "id", "Dateiname": "dateiname", "Text": "erkannter_text",
            "Typ": "typ", "Jahr": "jahr", "Datum": "datum", "ISO_datum": "iso_datum",
            "Seite": "seite", "Nr": "nr", "Gemeinde": "gemeinde",
            "Vorname": "vorname", "Nachname": "nachname", "Partner": "partner",
            "Beruf": "beruf", "Ort": "ort",
            "Bräutigam Vater": "brautigam_vater", "Braut Vater": "braut_vater",
            "Braut Nachname": "braut_nachname", "Braut Ort": "braut_ort",
            "Bräutigam Stand": "brautigam_stand", "Braut Stand": "braut_stand",
            "Todestag": "todestag", "Geb.Jahr (gesch.)": "geb_jahr_gesch",
            "Notiz": "notiz",
        }
        column_widths = self.config.get("column_widths", {})
        for col_id, config_key in column_map.items():
            width = column_widths.get(config_key)
            if width:
                try:
                    self.tree.column(col_id, width=width)
                except Exception:
                    pass

    def _on_column_resize(self, event):
        if hasattr(self, "_resize_timer"):
            self.root.after_cancel(self._resize_timer)
        self._resize_timer = self.root.after(500, self._save_column_widths)

    def _save_column_widths(self):
        if not hasattr(self, "tree"):
            return
        column_map = {
            "ID": "id", "Dateiname": "dateiname", "Text": "erkannter_text",
            "Typ": "typ", "Jahr": "jahr", "Datum": "datum", "ISO_datum": "iso_datum",
            "Seite": "seite", "Nr": "nr", "Gemeinde": "gemeinde",
            "Vorname": "vorname", "Nachname": "nachname", "Partner": "partner",
            "Beruf": "beruf", "Ort": "ort",
            "Bräutigam Vater": "brautigam_vater", "Braut Vater": "braut_vater",
            "Braut Nachname": "braut_nachname", "Braut Ort": "braut_ort",
            "Bräutigam Stand": "brautigam_stand", "Braut Stand": "braut_stand",
            "Todestag": "todestag", "Geb.Jahr (gesch.)": "geb_jahr_gesch",
            "Notiz": "notiz",
        }
        widths = {}
        for col_id, config_key in column_map.items():
            try:
                widths[config_key] = self.tree.column(col_id, "width")
            except Exception:
                pass
        self.config.set_all_column_widths(widths)

    def _reset_column_widths(self):
        if messagebox.askyesno("Zurücksetzen", "Möchten Sie die Spaltenbreiten zurücksetzen?"):
            self.config.set("column_widths", self.config.DEFAULT_CONFIG["column_widths"].copy())
            self._apply_column_widths()
            messagebox.showinfo("Fertig", "Spaltenbreiten wurden zurückgesetzt.")

    # ------------------------------------------------------------------
    # Einstellungen – Medien-Laufwerk
    # ------------------------------------------------------------------

    def _choose_media_drive(self):
        drive = self.config.media_drive
        initial = drive.rstrip(":") + ":\\" if len(drive) == 2 else drive
        directory = filedialog.askdirectory(title="Basis-Verzeichnis für Kirchenbuch-Medien wählen", initialdir=initial)
        if directory:
            p = Path(directory)
            self.drive_var.set(p.drive if p.drive else directory)

    def _save_media_drive(self):
        new_drive = self.drive_var.get().strip()
        if not new_drive:
            messagebox.showwarning("Ungültige Eingabe", "Bitte einen gültigen Pfad eingeben.")
            return
        self.config.media_drive = new_drive
        messagebox.showinfo("Gespeichert", f"Laufwerk gespeichert: {self.config.media_drive}")

    def _choose_kb_base_path(self):
        initial = self.kb_base_path_var.get().strip() or self.config.media_drive or str(Path.cwd())
        directory = filedialog.askdirectory(title="Kirchenbuch-Basisverzeichnis wählen", initialdir=initial)
        if directory:
            self.kb_base_path_var.set(directory)

    def _apply_kb_base_path(self):
        raw = self.kb_base_path_var.get().strip()
        if not raw:
            self.config.set("kirchenbuch_base_path", "")
            messagebox.showinfo("Gespeichert", "Kirchenbuch-Basisverzeichnis wurde geleert.")
            return

        new_path = Path(raw).expanduser()
        if not new_path.exists() or not new_path.is_dir():
            messagebox.showwarning("Ungültiger Pfad", f"Das Kirchenbuch-Basisverzeichnis ist ungültig:\n{new_path}")
            return

        self.config.set("kirchenbuch_base_path", str(new_path))
        self.kb_base_path_var.set(str(new_path))
        messagebox.showinfo("Gespeichert", f"Kirchenbuch-Basisverzeichnis gespeichert:\n{new_path}")

    def _choose_card_base_path(self):
        initial = self.card_base_path_var.get().strip() or self.config.image_base_path or str(Path.cwd())
        directory = filedialog.askdirectory(title="Karteikarten-Basisverzeichnis wählen", initialdir=initial)
        if directory:
            self.card_base_path_var.set(directory)

    def _apply_card_base_path(self):
        raw = self.card_base_path_var.get().strip()
        if not raw:
            self.config.image_base_path = ""
            messagebox.showinfo("Gespeichert", "Karteikarten-Basisverzeichnis wurde geleert.")
            return

        new_path = Path(raw).expanduser()
        if not new_path.exists() or not new_path.is_dir():
            messagebox.showwarning("Ungültiger Pfad", f"Das Karteikarten-Basisverzeichnis ist ungültig:\n{new_path}")
            return

        self.config.image_base_path = str(new_path)
        self.card_base_path_var.set(str(new_path))
        messagebox.showinfo("Gespeichert", f"Karteikarten-Basisverzeichnis gespeichert:\n{new_path}")

    # ------------------------------------------------------------------
    # Einstellungen – Datenbankpfad
    # ------------------------------------------------------------------

    def _choose_settings_db_path(self):
        initial = str(Path(self.settings_db_path_var.get()).parent) if self.settings_db_path_var.get().strip() else str(Path.cwd())
        selected = filedialog.askopenfilename(
            title="SQLite-Datenbank wählen",
            initialdir=initial,
            filetypes=[("SQLite DB", "*.db *.sqlite *.db3"), ("Alle Dateien", "*.*")],
        )
        if selected:
            self.settings_db_path_var.set(selected)

    def _apply_settings_db_path(self):
        raw = self.settings_db_path_var.get().strip()
        if not raw:
            messagebox.showwarning("Ungültiger Pfad", "Bitte einen DB-Pfad angeben.")
            return
        new_path = Path(raw).expanduser()
        if not new_path.exists():
            if not messagebox.askyesno("DB nicht gefunden", f"Datei nicht gefunden:\n{new_path}\n\nNeue Datenbank anlegen?"):
                return
        try:
            new_db = KarteikartenDB(str(new_path))
            old_conn = getattr(self.db, "conn", None)
            if old_conn:
                try:
                    old_conn.close()
                except Exception:
                    pass
            self.db = new_db
            self.active_db_path = str(new_path.resolve())
            self.config.db_path = self.active_db_path
            self.settings_db_path_var.set(self.active_db_path)
            if hasattr(self, "db_path_info_label"):
                self.db_path_info_label.config(text=f"Aktive DB: {self.active_db_path}")
            self._refresh_db_list()
            messagebox.showinfo("DB geladen", f"Datenbank aktiv:\n{self.active_db_path}")
        except Exception as e:
            messagebox.showerror("DB-Fehler", f"Datenbank konnte nicht geladen werden:\n{e}")


def run_reader():
    """Startet die Leseanwendung."""
    root = tk.Tk()
    KarteikartenReader(root)
    root.mainloop()
