#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

# Lese die Datei
with open(r'd:\projects\Wetzlar-Erkennung\src\reader_gui.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Finde die Zeile mit '# --\n    # Statistik'
insert_line = None
for i, line in enumerate(lines):
    if '# Statistik' in line:
        insert_line = i
        break

if insert_line is None:
    print('Statistik-Kommentar nicht gefunden')
    sys.exit(1)

# Neue Funktion
new_func = '''    def _backup_full_csv(self):
        """Exportiert Karteikarten + Sync-Queue als zwei separate CSV-Dateien mit Datum."""
        from datetime import datetime
        from pathlib import Path
        import tkinter.simpledialog as simpledialog

        # Wähle Verzeichnis statt Datei
        import tkinter.filedialog as filedialog
        output_dir = filedialog.askdirectory(title="Verzeichnis für Full Backup wählen")
        
        if not output_dir:
            return

        try:
            karteikarten_path, queue_path = self.db.export_full_backup(output_dir)
            
            # Lese anzahl Datensätze
            import csv
            with open(karteikarten_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows_count = sum(1 for _ in reader) - 1  # Abzug Header
            
            with open(queue_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                queue_count = sum(1 for _ in reader) - 1  # Abzug Header
            
            msg = (
                f"Full Backup erstellt:\\n\\n"
                f"Karteikarten: {rows_count} Datensätze\\n"
                f"  → {Path(karteikarten_path).name}\\n\\n"
                f"Sync-Queue: {queue_count} Einträge\\n"
                f"  → {Path(queue_path).name}\\n\\n"
                f"Speicherort: {output_dir}"
            )
            messagebox.showinfo("Full Backup erstellt", msg)
        except Exception as e:
            messagebox.showerror("Fehler", f"Full Backup fehlgeschlagen:\\n{e}")

'''

# Füge vor dem Statistik-Kommentar ein
lines.insert(insert_line, new_func)

# Schreibe zurück
with open(r'd:\projects\Wetzlar-Erkennung\src\reader_gui.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('_backup_full_csv wurde hinzugefügt')
