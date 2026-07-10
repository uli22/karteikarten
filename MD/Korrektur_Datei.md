# Korrektur von Dateinamen in der Datenbank

## Zweck

Wenn Karteikarten-Dateien umbenannt oder in andere Ordner verschoben wurden
(z.B. weil ein Kirchenbuch-Typ neu klassifiziert wurde: `Gb` -> `Sb`),
muessen die Pfade in der Datenbank (`karteikarten.db`) angepasst werden.

Das Skript `korrigieren_dateinamen.py` automatisiert diesen Vorgang.

## Funktionsweise

### Eingabe: `input/Korrekturen.csv`

Die CSV-Datei muss folgende Spalten enthalten:

| Spalte | Bedeutung |
|--------|-----------|
| `Neuer Pfad` | Vollstaendiger Pfad nach dem Umbennenen/Verschieben |
| `Alter Pfad` | (optional) Vollstaendiger Pfad vor dem Umbennenen |
| `Alter Ordner` | Altes Ordner-Kuerzel (z.B. `Gb`) |
| `Neuer Ordner` | Neues Ordner-Kuerzel (z.B. `Sb`) |
| `Neuer Dateiname` | Nur der Dateiname (ohne Pfad) |

**Wichtig**: Wenn `Alter Pfad` leer ist, wird er automatisch aus `Neuer Pfad`
konstruiert, indem `Neuer Ordner` durch `Alter Ordner` ersetzt wird (sowohl
im Ordnernamen als auch im Dateinamen).

### Beispiel

```
Neuer Pfad:  E:\...\Sb\1146 Sb 1738 - 1735-1746 - F102779705.jpg
Alter Pfad:  (leer)
Alter Ordner: Hb
Neuer Ordner: Sb
Neuer Dateiname: 1146 Sb 1738 - 1735-1746 - F102779705.jpg

-> Konstruierter alter Pfad: E:\...\Hb\1146 Hb 1738 - 1735-1746 - F102779705.jpg
-> Dieser Pfad wird in der DB gesucht
-> Gefunden -> UPDATE: dateiname + dateipfad werden auf die neuen Werte gesetzt
```

### Suchlogik

1. Aus `Neuer Pfad` + `Alter Ordner` + `Neuer Ordner` wird der alte Pfad konstruiert
2. Die DB wird nach diesem alten Pfad durchsucht (`WHERE dateipfad = ?`)
3. **Gefunden**: `UPDATE` mit neuem `dateiname` und `dateipfad`
4. **Nicht gefunden**: Der Eintrag wird uebersprungen (kein INSERT)

### Sync-Queue

Jedes UPDATE erstellt automatisch einen Eintrag in der `sync_queue`-Tabelle,
sodass die Aenderung bei der naechsten Online-Synchronisation uebertragen wird.

## Aufruf

```bash
# Blindlauf (Dry-Run) - zeigt was passieren wuerde, ohne zu aendern
uv run korrigieren_dateinamen.py

# Echte Ausfuehrung
uv run korrigieren_dateinamen.py --apply
```

## Ausgabe

- **Konsolenausgabe**: Jede Aenderung wird mit ID und altem/neuem Dateinamen gelistet
- **Ergebnis-CSV**: `output/korrektur_ergebnis.csv` mit allen Details
- **Zusammenfassung**: Anzahl UPDATEs, Uebersprungene, Fehler

## Beispielausgabe

```
======================================================================
KORREKTUREN-SCRIPT: dateiname/dateipfad in karteikarten.db aktualisieren
>>> BLINDLAUF (DRY-RUN) - es werden KEINE Aenderungen vorgenommen <<<
======================================================================

Korrekturen.csv: 187 gueltige Eintraege geladen.
  [168] UPDATE: ID=15887 | 1156 Hb 1738 ... -> 1156 Sb 1738 ...
  [169] UPDATE: ID=15868 | 1137 Hb 1738 ... -> 1137 Sb 1738 ...
  ...

======================================================================
ZUSAMMENFASSUNG
======================================================================
  Eintraege in CSV:            187
  UPDATE (in DB gefunden):     20
  UEBERSPRUNGEN (nicht in DB): 167
======================================================================
```

## Wichtige Hinweise

- **Nur UPDATEs**: Das Skript legt keine neuen Datensaetze an. Nicht gefundene
  Eintraege werden uebersprungen.
- **Vorher Backup**: Vor der Ausfuehrung mit `--apply` sollte ein Backup der
  Datenbank erstellt werden.
- **Erst Dry-Run**: Immer zuerst den Blindlauf ausfuehren und das Ergebnis pruefen.
