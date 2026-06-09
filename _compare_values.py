"""Vergleicht den DB-dateiname mit dem XLSX-Wert aus Zeile 1971.
Liest beide aus den Originalquellen und zeigt Unterschiede."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "src")

# 1) DB-Wert lesen (read-only + WAL, falls GUI locked)
db_path = "karteikarten.db"
try:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA query_only = 1")
    conn.execute("PRAGMA journal_mode = WAL")
    cur = conn.cursor()
    cur.execute("SELECT id, dateiname FROM karteikarten WHERE dateiname LIKE '%3470 Gb%'")
    rows = cur.fetchall()
    if rows:
        db_val = rows[0]["dateiname"] if hasattr(rows[0], "dateiname") else rows[0][1]
        db_id = rows[0]["id"] if hasattr(rows[0], "id") else rows[0][0]
        print(f"DB (ID={db_id}): {db_val!r}")
        print(f"  Länge: {len(db_val)} Zeichen")
        print(f"  Bytes: {db_val.encode('utf-8').hex()}")
    else:
        print("Kein DB-Eintrag mit '3470 Gb' gefunden.")
        db_val = None
    conn.close()
except sqlite3.OperationalError as e:
    print(f"DB gesperrt: {e}")
    db_val = None

print()

# 2) XLSX-Wert lesen - Frage den Benutzer nach dem Pfad
# Suche nach kürzlich verwendeten XLSX-Dateien
xlsx_candidates = []
for p in Path("D:/projects/Wetzlar_csv/input/Merge").rglob("*.xlsx"):
    xlsx_candidates.append(p)
for p in Path(".").rglob("*.xlsx"):
    xlsx_candidates.append(p)

print("Gefundene XLSX-Dateien:")
for i, p in enumerate(xlsx_candidates):
    print(f"  [{i}] {p}")

# Für den Test: hartcodierte Liste
xlsx_files = [
    r"D:\projects\Wetzlar_csv\input\Merge\00_KB_1571-1613_Taufen_EINGABE001_V6--zur Sicherheit mit Vornamen.xlsx",
    r"D:\projects\Wetzlar_csv\input\Merge\Karteikarten Wetzlar ERFASSUNG TAUFEN 1671-1695 ab 1688 KB 408-3.diehl.xlsx",
]
