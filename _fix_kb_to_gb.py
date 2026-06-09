"""Ersetzt 1564-1597 → 1564-1611 in dateiname und dateipfad für die 48 Kb/Gb-Einträge.

ACHTUNG: Direkte DB-Modifikation! Backup vorhanden.
"""
import csv
import datetime
import os
import sqlite3

DB_PATH = r"D:\projects\Wetzlar-Erkennung\karteikarten.db"

backup_dir = os.path.join(os.path.dirname(DB_PATH), "output")
os.makedirs(backup_dir, exist_ok=True)
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# ============================================================
# 1) Backup der betroffenen Einträge
# ============================================================
c.execute("SELECT * FROM karteikarten WHERE dateiname LIKE '%1564-1597%' ORDER BY id")
rows = c.fetchall()
col_names = [desc[0] for desc in c.description]

backup_file = os.path.join(backup_dir, f"_backup_1564-1597_to_1564-1611_{ts}.csv")
with open(backup_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(col_names)
    writer.writerows(rows)
print(f"✅ Backup erstellt: {backup_file} ({len(rows)} Einträge)")

# ============================================================
# 2) 1564-1597 → 1564-1611 ersetzen
# ============================================================
c.execute("""
    UPDATE karteikarten SET
        dateiname = REPLACE(dateiname, '1564-1597', '1564-1611'),
        dateipfad = REPLACE(dateipfad, '1564-1597', '1564-1611'),
        version = COALESCE(version, 1) + 1,
        sync_status = 'pending',
        updated_by = 'range_fix',
        aktualisiert_am = CURRENT_TIMESTAMP
    WHERE dateiname LIKE '%1564-1597%'
""")
updated = c.rowcount

# ============================================================
# 3) Sync-Queue füllen
# ============================================================
c.execute("""
    SELECT id, global_id, version
    FROM karteikarten
    WHERE sync_status = 'pending' AND updated_by = 'range_fix'
""")
updated_rows = c.fetchall()
for rid, gid, ver in updated_rows:
    if gid:
        c.execute(
            "INSERT INTO sync_queue (global_id, op, source, base_version) VALUES (?, 'upsert', 'erkennung', ?)",
            (gid, int(ver or 1))
        )

conn.commit()
print(f"✅ {updated} Einträge aktualisiert (1564-1597 → 1564-1611)")
print(f"✅ {len(updated_rows)} Sync-Queue-Einträge hinzugefügt")

# ============================================================
# 4) Ergebnis prüfen
# ============================================================
c.execute("SELECT COUNT(*) FROM karteikarten WHERE dateiname LIKE '%1564-1597%'")
remaining = c.fetchone()[0]
if remaining:
    print(f"⚠️  Noch {remaining} Einträge mit 1564-1597 übrig")
else:
    print("✅ Keine '1564-1597'-Einträge mehr in der DB")

# Stichprobe
c.execute("""
    SELECT id, dateiname, dateipfad, sync_status, version, updated_by
    FROM karteikarten WHERE updated_by = 'range_fix'
    ORDER BY id LIMIT 3
""")
print("\n✅ Stichprobe:")
for r in c.fetchall():
    print(f"  ID {r[0]}: {r[1]}")
    print(f"         {r[2]}")
    print(f"         Sync: {r[3]}, Version: {r[4]}, By: {r[5]}")

conn.close()
print("\nFertig!")
