# Struktur von Heiratseinträgen

## Allgemeine Struktur

Heiratseinträge folgen einer spezifischen Struktur, die sich von Sterbeeinträgen unterscheidet:

1. **Zitation** (Kirchenbuch-Referenz)
2. **Bräutigam-Informationen**
3. **Trenner** ("mitt", "undt", "und")
4. **Braut-Informationen**
5. **Abschluss** ("hielten Hochzeit", "copulirt", etc.)

## Detaillierte Struktur

### 1. Zitation
```
ev. Kb. Wetzlar ∞ YYYY.MM.DD p. [Seite] Nr. [Nummer]
```

### 2. Bräutigam-Informationen

```
[Vorname] [Nachname] [Vater-Vorname] [Vater-Nachname]s, [Beruf/Status des Vaters], [Ort-Info], [Status] Sohn
```

**Komponenten:**
- **Vorname des Bräutigams** (z.B. "Wilhelm")
- **Nachname des Bräutigams** (z.B. "Zahn")
  - Der Nachname kann auch aus dem Genitiv des Vaternamens abgeleitet werden
- **Vorname des Vaters** (z.B. "Christoff")
- **Nachname des Vaters** im Genitiv (z.B. "Zahns")
  - Endet oft auf "s" (Genitiv-Form)
  - Grundform: "Zahn" → Genitiv: "Zahns"
- **Beruf des Vaters** (optional, z.B. "gewesenen Bürgers")
- **Ort-Angabe** (z.B. "alhier" = am selben Ort, "zu Wetzlar")
  - "alhier" bedeutet "Wetzlar" (der Kirchenort)
- **Status** (z.B. "hinterlassener ehel. Sohn")

### 3. Trenner

Typische Trennwörter zwischen Bräutigam und Braut:
- "und"
- "undt"
- "mitt"
- "mit"

### 4. Braut-Informationen

```
[Anrede] [Vorname(n)] [Vater-Vorname] [Vater-Nachname]s [Beruf des Vaters] [Ort], [Status] Tochter
```

**Komponenten:**
- **Anrede** (z.B. "Jungfr.", "Jungfrau")
- **Vorname(n) der Braut** (z.B. "Christiana Anna Ottilie")
  - Kann mehrere Namen sein
- **Vorname des Brautvaters** (z.B. "Peter")
- **Nachname des Brautvaters** im Genitiv (z.B. "Brenigs")
  - Grundform: "Brenig" → Genitiv: "Brenigs"
- **Beruf des Brautvaters** (optional, z.B. "gewesener Hoffgärtner")
- **Ort der Braut** (z.B. "zu Weilburg")
  - Oft mit "zu" eingeleitet
- **Status** (z.B. "hinterlassene ehel. Tochter")

### 5. Abschluss

Typische Abschlussformulierungen (nicht mehr zu erkennen):
- "hielten Hochzeit"
- "copulirt"
- "copulirt in Musaeo meo"
- mit Datum-Wiederholung (z.B. "∞ 25. Febr.")

## Beispiel mit Feldextraktion

**Originaltext:**
```
ev. Kb. Wetzlar ∞ 1694.02.25. p. 1 Nr. 5 Wilhelm Zahn Christoff Zahns, gewesenen Bürgers alhier, hinterlassener ehel. Sohn, und Jungfr. Christiana Anna Ottilie, Peter Brenigs gewesener Hoffgärtner zu Weilburg, hinterlassene ehel. tochter copulirt in Musaeo meo ∞ 25. Febr.(43-2.453.3)
```

**Extrahierte Felder:**

| Feld | Wert | Bemerkung |
|------|------|-----------|
| Vorname | Wilhelm | Vorname des Bräutigams |
| Nachname | Zahn | Nachname des Bräutigams (aus "Zahns" → "Zahn") |
| Partner | Christiana Anna Ottilie | Vorname(n) der Braut |
| Beruf | (gewesenen Bürgers) | Beruf des Bräutigam-Vaters |
| Ort | Wetzlar | "alhier" = am Kirchenort |
| Bräutigams Vater | Christoff | Vorname des Vaters des Bräutigams |
| Braut Vater | Peter | Vorname des Brautvaters |
| Braut Nachname | Brenig | Nachname der Braut (aus "Brenigs" → "Brenig") |
| Braut Ort | Weilburg | "zu Weilburg" |

## Besonderheiten bei der Erkennung

### Genitiv-Formen
- Nachnamen erscheinen oft im Genitiv (mit "s" am Ende)
- **Zahns** → Grundform: **Zahn**
- **Brenigs** → Grundform: **Brenig**
- **Peters** → Grundform: **Peter**

### Orts-Angaben
- **"alhier"** = am Ort der Kirche (hier: Wetzlar)
- **"zu [Ort]"** = Herkunftsort (z.B. "zu Weilburg")
- **"von [Ort]"** = Herkunftsort

### Stopwörter (Ende der Erkennung)
- "hielten Hochzeit"
- "copulirt"
- "copuliret"
- "getraut"
- Wiederholung des Heiratssymbols: "∞"

### Statusangaben (zu ignorieren bei Erkennung)
- "ehel." / "ehelich" / "ehelicher"
- "hinterlassen" / "hinterlassener" / "hinterlassene"
- "Sohn" / "Tochter"
- "gewesen" / "gewesener" / "gewesene"

## Erkennungsalgorithmus (Pseudocode)

```
1. Zitation extrahieren (bis zu einem Stopwort oder Satzzeichen)
2. Rest-Text aufteilen in Wörter
3. Ersten Vornamen finden → Bräutigam Vorname
4. Nächstes Wort → Bräutigam Nachname (eventuell Genitiv-Form)
5. Nächstes Wort (wenn Genitiv) → Vater Vorname
6. Ort suchen ("alhier", "zu X")
7. Trenner finden ("und", "mitt", "undt")
8. Nach Trenner: Vornamen sammeln → Braut Vorname(n)
9. Nach Komma: Vater-Vorname + Nachname (Genitiv)
10. Braut-Ort suchen ("zu X")
11. Bei Stopwörtern abbrechen
```

## Änderungshistorie

- **27.01.2026**: Initiale Dokumentation basierend auf Beispiel-Eintrag
