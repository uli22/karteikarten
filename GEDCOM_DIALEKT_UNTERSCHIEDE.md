# GEDCOM Dialekt-Unterschiede: GRAMPS vs. TNG

Basierend auf der Analyse von `d:\projects\Wetzlar_csv\gw.py` (TNGPlugin / GrampsPlugin).

---

## 1. Taufe-Tag

| | GRAMPS | TNG |
|---|---|---|
| Tag | `CHR` | `CHR` (beide gleich in diesem Projekt) |

---

## 2. ID-Formatierung

| Typ | GRAMPS | TNG |
|---|---|---|
| Person | `@I1@` | `@I1@` (gleich) |
| Familie | `@F1@` | `@F1@` (gleich) |
| Note | `@N000001@` (6-stellig, nullgefüllt) | Keine separaten NOTE-Records |
| Media | `@O000001@` (O-Präfix, 6-stellig) | `@201000@` (numerisch, kein Präfix) |

---

## 3. Notizen — zentraler Unterschied

| Aspekt | GRAMPS | TNG |
|---|---|---|
| `handle_notes()` | deferred (gesammelt) | inline |
| Speicherung | Gesammelt in `_notes`-Dict (mit Dedup via ID) | Gleicher Mechanismus, aber kein separater Record |
| Ausgabe | Am Dateiende als `0 @N000001@ NOTE text` + `1 CONC ...` | Direkt beim Event als `2 NOTE text` / `3 CONC ...` |
| Referenz im Event | `3 NOTE @N000001@` (Verweis innerhalb Citation, Ebene 3) | `2 NOTE text` (Volltext direkt, Ebene 2) |
| Separate NOTE-Records am Ende | Ja | Nein |
| Notiz-Format | `\|Abschrift Karteikarte\| "text"` | gleich |

---

## 4. Quellen-Citation (SOUR)

| Aspekt | GRAMPS | TNG |
|---|---|---|
| Struktur | `2 SOUR @Sx@` → `3 DATA` → `4 DATE` → `3 PAGE` → `3 QUAY` | `2 SOUR @Sx@` → `3 PAGE` → `3 QUAY` (kein DATA-Block) |
| NOTE/OBJE in Citation | `3 NOTE @Nxxx@` + `3 OBJE @Oxxx@` (Ebene 3) | Nicht in Citation — danach als `2 NOTE text` + `2 OBJE @mid@` |

---

## 5. Media / OBJE

| Aspekt | GRAMPS | TNG |
|---|---|---|
| OBJE-Ebene im Event | `3 OBJE @O000001@` (innerhalb Citation, Ebene 3) | `2 OBJE @201000@` (direkt nach Citations, Ebene 2) |
| OBJE-ID-Format | `@O000001@` (O-Präfix, 6-stellig nullgefüllt) | `@201000@` (numerisch ab 201000) |
| OBJE-Records am Ende | Beide schreiben `0 @xxx@ OBJE` mit `1 FORM` und `1 FILE` |

---

## 6. Approximiertes BIRT (nur TNG)

TNG: Falls kein BIRT-Event, aber CHR vorhanden → BIRT mit `ABT {Taufdatum}`, Ort aus Eintrag, Note `Geschätzt aus Taufdatum`.  
GRAMPS: Kein äquivalentes Verhalten.

---

## 7. Datei-Reihenfolge

```
         GRAMPS                    TNG
         ──────                    ───
HEAD (DEST GRAMPS)            HEAD (DEST TNG)
INDI (alle)                   INDI (alle)
FAM  (alle)                   FAM  (alle)
SOUR (Block)                  SOUR (Block)
NOTE (Block, @N000001@)        [keine NOTE-Records]
OBJE (Block, @O000001@)       OBJE (Block, @201000@)
TRLR                          TRLR
```

---

## 8. Implementierung in gedcom_exporter.py

`GedcomExporter(db_connection, dialect='GRAMPS')` — Standardwert GRAMPS.  
`GedcomExporter(db_connection, dialect='TNG')` — TNG-Dialekt.

Unterschiede im Code je nach `self._dialect`:

- `_get_note_id()`: GRAMPS → `@N000001@`, TNG → `@N1@` (aber keine separaten Records)
- `_get_obje_id()`: GRAMPS → `@O000001@`, TNG → `@201000@`
- `_write_header()`: `1 DEST GRAMPS` vs. `1 DEST TNG`
- Alle Event-Methoden: DATA-Block nur bei GRAMPS; NOTE/OBJE nach Citations nur bei TNG inline
- `_write_notes_and_objes()`: NOTE-Records nur bei GRAMPS
- `_process_baptism_record()`: Approximiertes BIRT nur bei TNG
