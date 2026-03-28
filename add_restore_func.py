#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

# Lese database.py
with open(r'd:\projects\Wetzlar-Erkennung\src\database.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Finde die Zeile mit "def import_from_csv"
insert_line = None
for i, line in enumerate(lines):
    if 'def import_from_csv' in line:
        insert_line = i
        break

if insert_line is None:
    print('import_from_csv nicht gefunden')
    sys.exit(1)

# Neue restore_full_backup Methode
new_method = '''    def restore_full_backup(self, karteikarten_csv: str, queue_csv: str = None):
        """Importiert Karteikarten und Sync-Queue aus Backup-CSVs.
        
        Args:
            karteikarten_csv: Pfad zur _backup_karteikarten_*.csv
            queue_csv: Pfad zur _backup_sync_queue_*.csv (optional)
        """
        import csv
        
        cursor = self.conn.cursor()
        
        # 1. Leere die existierenden Tabellen
        cursor.execute("DELETE FROM sync_queue")
        cursor.execute("DELETE FROM karteikarten")
        self.conn.commit()
        
        # 2. Importiere Karteikarten
        with open(karteikarten_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Extrahiere alle Spalten
                placeholders = ', '.join(['?' for _ in row.keys()])
                cols = ', '.join(row.keys())
                query = f"INSERT INTO karteikarten ({cols}) VALUES ({placeholders})"
                
                # Konvertiere Werte (ensure_ascii für JSON)
                values = list(row.values())
                cursor.execute(query, values)
        
        self.conn.commit()
        
        # 3. Importiere Sync-Queue falls vorhanden
        if queue_csv:
            try:
                with open(queue_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        placeholders = ', '.join(['?' for _ in row.keys()])
                        cols = ', '.join(row.keys())
                        query = f"INSERT INTO sync_queue ({cols}) VALUES ({placeholders})"
                        values = list(row.values())
                        cursor.execute(query, values)
                
                self.conn.commit()
            except Exception as e:
                print(f"Warnung: Sync-Queue konnte nicht importiert werden: {e}")

'''

# Füge vor import_from_csv ein
lines.insert(insert_line, new_method)

# Schreibe zurück
with open(r'd:\projects\Wetzlar-Erkennung\src\database.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('✓ restore_full_backup() hinzugefügt')
