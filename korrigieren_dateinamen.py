"""
Korrekturen-Script: Aktualisiert dateiname & dateipfad in karteikarten.db
basierend auf Korrekturen.csv und erstellt Sync-Queue-Eintraege.

Nur UPDATE: Datensaetze, die nicht in der DB gefunden werden, werden
UEBERSPRUNGEN (kein INSERT). In der Statistik werden sie aufgelistet.

Aufruf:
  uv run korrektur_script.py            # Blindlauf (Dry-Run)
  uv run korrektur_script.py --apply    # Echte Aenderungen durchfuehren
"""

import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# --- Konfiguration ---
DB_PATH = Path(r"d:\projects\Wetzlar-Erkennung\karteikarten.db")
CSV_PATH = Path(r"d:\projects\Wetzlar-Erkennung\input\Korrekturen.csv")
OUTPUT_CSV = Path(r"d:\projects\Wetzlar-Erkennung\output\korrektur_ergebnis.csv")

DRY_RUN = "--apply" not in sys.argv

BS = chr(92)  # Backslash


def build_alter_dateipfad(neuer_pfad: str, alter_ordner: str, neuer_ordner: str) -> str:
    """Konstruiert den alten Pfad: NeuerOrdner -> AlterOrdner
    sowohl im Ordnernamen als auch im Dateinamen."""
    return (
        neuer_pfad
        .replace(f"{BS}{neuer_ordner}{BS}", f"{BS}{alter_ordner}{BS}")
        .replace(f" {neuer_ordner} ", f" {alter_ordner} ")
    )


def find_by_dateipfad(cursor, dateipfad: str):
    """Sucht Datensatz anhand dateipfad."""
    cursor.execute(
        "SELECT id, global_id, version, dateiname, dateipfad FROM karteikarten WHERE dateipfad = ?",
        (dateipfad,),
    )
    return cursor.fetchone()


def main():
    print("=" * 70)
    print("KORREKTUREN-SCRIPT: dateiname/dateipfad in karteikarten.db aktualisieren")
    if DRY_RUN:
        print(">>> BLINDLAUF (DRY-RUN) - es werden KEINE Aenderungen vorgenommen <<<")
    else:
        print(">>> ECHTE AENDERUNGEN - Datenbank wird modifiziert <<<")
    print("=" * 70)

    # --- CSV einlesen ---
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        korrekturen = [
            row for row in reader
            if row["Alter Ordner"].strip() and row["Neuer Ordner"].strip()
        ]

    print(f"\nKorrekturen.csv: {len(korrekturen)} gueltige Eintraege geladen.")

    # --- DB verbinden ---
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ergebnisse = []
    gefunden = 0
    nicht_gefunden = 0
    aktualisiert = 0
    fehler = 0

    for idx, row in enumerate(korrekturen, 1):
        neuer_pfad = row["Neuer Pfad"].strip()
        neuer_dateiname = row["Neuer Dateiname"].strip()
        alter_ordner = row["Alter Ordner"].strip()
        neuer_ordner = row["Neuer Ordner"].strip()

        alter_dateipfad = build_alter_dateipfad(neuer_pfad, alter_ordner, neuer_ordner)
        alter_dateiname = Path(alter_dateipfad).name

        rec = find_by_dateipfad(cur, alter_dateipfad)

        ergebnis = {
            "Nr": idx,
            "Alter Pfad": alter_dateipfad,
            "Neuer Pfad": neuer_pfad,
            "Alter Dateiname": alter_dateiname,
            "Neuer Dateiname": neuer_dateiname,
            "DB-ID": None,
            "global_id": None,
            "Status": "",
            "Details": "",
        }

        if rec is None:
            # Nicht in DB -> ueberspringen
            nicht_gefunden += 1
            ergebnis["Status"] = "NICHT IN DB (uebersprungen)"
            ergebnis["Details"] = f"Kein DB-Eintrag fuer '{alter_dateipfad}'"
            ergebnisse.append(ergebnis)
            continue

        # --- UPDATE ---
        gefunden += 1
        db_id, global_id, old_version, db_dateiname, db_dateipfad = rec

        ergebnis["DB-ID"] = db_id
        ergebnis["global_id"] = global_id

        if DRY_RUN:
            ergebnis["Status"] = "DRY-RUN (wuerde aktualisiert)"
            ergebnis["Details"] = f"ID={db_id}, v{old_version}"
            ergebnisse.append(ergebnis)
            print(f"  [{idx:3d}] UPDATE: ID={db_id} | {alter_dateiname} -> {neuer_dateiname}")
            continue

        try:
            new_version = (old_version or 1) + 1
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cur.execute(
                """UPDATE karteikarten
                   SET dateiname = ?, dateipfad = ?,
                       version = ?, sync_status = 'pending',
                       updated_by = 'korrektur_script', aktualisiert_am = ?
                   WHERE id = ?""",
                (neuer_dateiname, neuer_pfad, new_version, now, db_id),
            )

            cur.execute(
                """INSERT INTO sync_queue (global_id, op, source, base_version, created_at)
                   VALUES (?, 'upsert', 'erkennung', ?, ?)""",
                (global_id, new_version, now),
            )

            aktualisiert += 1
            ergebnis["Status"] = "AKTUALISIERT"
            ergebnis["Details"] = f"Version {old_version}->{new_version}, Sync-Queue erstellt"
            ergebnisse.append(ergebnis)
            print(f"  [{idx:3d}] UPDATE: ID={db_id} | {alter_dateiname} -> {neuer_dateiname}")

        except Exception as e:
            fehler += 1
            ergebnis["Status"] = "FEHLER"
            ergebnis["Details"] = str(e)
            ergebnisse.append(ergebnis)
            print(f"  [{idx:3d}] FEHLER: {e}")

    # --- Commit ---
    if not DRY_RUN:
        conn.commit()
        print("\nAenderungen committet.")
    conn.close()

    # --- Ergebnis-CSV ---
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Nr", "DB-ID", "global_id", "Status", "Details",
            "Alter Pfad", "Neuer Pfad", "Alter Dateiname", "Neuer Dateiname",
        ])
        writer.writeheader()
        writer.writerows(ergebnisse)

    # --- Zusammenfassung ---
    print("\n" + "=" * 70)
    print("ZUSAMMENFASSUNG")
    print("=" * 70)
    print(f"  Eintraege in CSV:            {len(korrekturen)}")
    print(f"  UPDATE (in DB gefunden):     {gefunden}")
    print(f"  UEBERSPRUNGEN (nicht in DB): {nicht_gefunden}")
    if DRY_RUN:
        print(f"\n  >>> Blindlauf - keine Aenderungen vorgenommen <<<")
        print(f"  Zum Ausfuehren: uv run korrektur_script.py --apply")
    else:
        print(f"  Erfolgreich aktualisiert:    {aktualisiert}")
        print(f"  Fehler:                      {fehler}")
    print(f"\n  Ergebnis-CSV: {OUTPUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    main()
