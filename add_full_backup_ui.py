#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

# === 1. Update reader_gui.py ===

with open(r'd:\projects\Wetzlar-Erkennung\src\reader_gui.py', 'r', encoding='utf-8') as f:
    reader_content = f.read()

# Button hinzufügen
old_button = '        ttk.Button(filter_row3, text="💾 Backup CSV", command=self._backup_csv).pack(side=tk.LEFT, padx=5)'
new_button = '''        ttk.Button(filter_row3, text="💾 Backup CSV", command=self._backup_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_row3, text="🔒 Full Backup", command=self._backup_full_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_row3, text="↩️ Restore", command=self._restore_full_backup).pack(side=tk.LEFT, padx=5)'''

reader_content = reader_content.replace(old_button, new_button)

# Methoden hinzufügen vor # Statistik
methods = '''    def _backup_full_csv(self):
        """Exportiert Karteikarten + Sync-Queue mit Datum im Dateinamen."""
        from pathlib import Path
        
        # Wähle Verzeichnis
        output_dir = filedialog.askdirectory(title="Verzeichnis für Full Backup wählen")
        if not output_dir:
            return

        try:
            karteikarten_path, queue_path = self.db.export_full_backup(output_dir)
            
            # Zähle Einträge
            import csv
            with open(karteikarten_path, 'r', encoding='utf-8') as f:
                rows_count = sum(1 for _ in csv.reader(f)) - 1
            
            with open(queue_path, 'r', encoding='utf-8') as f:
                queue_count = sum(1 for _ in csv.reader(f)) - 1
            
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

    def _restore_full_backup(self):
        """Importiert Karteikarten + Sync-Queue aus Backup-CSVs."""
        import csv
        import os
        
        # Ask for directory with backup files
        backup_dir = filedialog.askdirectory(title="Backup-Verzeichnis mit CSV-Dateien wählen")
        if not backup_dir:
            return

        # Find backup files
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

        # Warnung anzeigen
        if not messagebox.askyesno("Bestätigung", 
            "Aktuelle Daten werden mit dem Backup überschrieben!\\n\\nFortfahren?"):
            return

        try:
            self.db.restore_full_backup(karteikarten_file, queue_file)
            messagebox.showinfo("Erfolg", "Daten erfolgreich wiederhergestellt!\\n\\nBitte die Anwendung neu starten.")
        except Exception as e:
            messagebox.showerror("Fehler", f"Wiederherstellung fehlgeschlagen:\\n{e}")

'''

# Einfügen vor "# Statistik"
reader_content = reader_content.replace('    # ------------------------------------------------------------------\n    # Statistik', 
                                        methods + '    # ------------------------------------------------------------------\n    # Statistik')

with open(r'd:\projects\Wetzlar-Erkennung\src\reader_gui.py', 'w', encoding='utf-8') as f:
    f.write(reader_content)

print('✓ reader_gui.py aktualisiert')

# === 2. Update gui.py (Erkennung) ===

with open(r'd:\projects\Wetzlar-Erkennung\src\gui.py', 'r', encoding='utf-8') as f:
    gui_content = f.read()

# Button hinzufügen
old_button_gui = '        ttk.Button(button_row1, text="📤 Export CSV", command=self._export_csv).pack(side=tk.LEFT, padx=3)'
new_button_gui = '''        ttk.Button(button_row1, text="📤 Export CSV", command=self._export_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="🔒 Full Backup", command=self._export_full_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_row1, text="↩️ Restore", command=self._import_full_backup).pack(side=tk.LEFT, padx=3)'''

gui_content = gui_content.replace(old_button_gui, new_button_gui)

# Methoden in gui.py hinzufügen (nach _export_csv)
methods_gui = '''    def _export_full_csv(self):
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
                f"Full Backup erstellt:\\n\\n"
                f"Karteikarten: {rows_count} Datensätze\\n"
                f"Sync-Queue: {queue_count} Einträge\\n\\n"
                f"Speicherort: {output_dir}"
            )
            messagebox.showinfo("Full Backup erstellt", msg)
        except Exception as e:
            messagebox.showerror("Fehler", f"Full Backup fehlgeschlagen:\\n{e}")

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
            "Aktuelle Daten werden mit dem Backup überschrieben!\\n\\nFortfahren?"):
            return

        try:
            self.db.restore_full_backup(karteikarten_file, queue_file)
            messagebox.showinfo("Erfolg", "Daten erfolgreich wiederhergestellt!\\n\\nBitte die Anwendung neu starten.")
        except Exception as e:
            messagebox.showerror("Fehler", f"Wiederherstellung fehlgeschlagen:\\n{e}")

'''

# Einfügen nach _export_csv
export_csv_pos = gui_content.find('    def _export_csv(self):')
if export_csv_pos != -1:
    # Finde das Ende dieser Methode
    next_def_pos = gui_content.find('\n    def ', export_csv_pos + 10)
    if next_def_pos != -1:
        gui_content = gui_content[:next_def_pos] + '\n' + methods_gui + gui_content[next_def_pos:]

with open(r'd:\projects\Wetzlar-Erkennung\src\gui.py', 'w', encoding='utf-8') as f:
    f.write(gui_content)

print('✓ gui.py aktualisiert')

print('✓ Alle Buttons und Methoden hinzugefügt')
