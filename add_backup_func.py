#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

# Lese die Datei
with open(r'd:\projects\Wetzlar-Erkennung\src\database.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Finde die Zeile mit 'def import_from_csv'
insert_line = None
for i, line in enumerate(lines):
    if 'def import_from_csv' in line:
        insert_line = i
        break

if insert_line is None:
    print('import_from_csv nicht gefunden')
    sys.exit(1)

# Neue Funktion
new_func = '''    def export_full_backup(self, output_dir: str):
        """Exportiert Karteikarten + Sync-Queue als zwei separate CSV-Dateien."""
        import csv
        from datetime import datetime
        from pathlib import Path
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        karteikarten_path = str(Path(output_dir) / f'_backup_karteikarten_{timestamp}.csv')
        queue_path = str(Path(output_dir) / f'_backup_sync_queue_{timestamp}.csv')
        
        cursor = self.conn.cursor()
        
        # Export Karteikarten
        cursor.execute('SELECT * FROM karteikarten ORDER BY jahr, datum, nummer')
        rows = cursor.fetchall()
        with open(karteikarten_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([desc[0] for desc in cursor.description])
            writer.writerows(rows)
        
        # Export Sync-Queue
        cursor.execute('SELECT * FROM sync_queue ORDER BY id')
        queue_rows = cursor.fetchall()
        with open(queue_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if queue_rows:
                writer.writerow([desc[0] for desc in cursor.description])
                writer.writerows(queue_rows)
            else:
                writer.writerow(['id', 'global_id', 'op', 'source', 'payload', 'base_version', 'created_at', 'retries', 'last_error', 'sent_at'])
        
        return karteikarten_path, queue_path

'''

# Füge vor import_from_csv ein
lines.insert(insert_line, new_func)

# Schreibe zurück
with open(r'd:\projects\Wetzlar-Erkennung\src\database.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('export_full_backup wurde hinzugefügt')
