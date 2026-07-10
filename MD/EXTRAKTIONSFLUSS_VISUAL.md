# Erkennungsfluss: Heirat vs. Begräbnis (Visuell)

## Namenserkennung - Sequentieller Ablauf

### HEIRAT: 2-Phasen Modell

```
ZITATION EXTRAHIEREN
    ↓ (ev. Kb. Wetzlar ∞ YYYY.MM.DD p. Seite Nr. Nummer)
TEXTE NACH ZITATION
    ↓ (Split in Wörter, Satzzeichen entfernen)
TRENNER SUCHEN ("und", "undt", "mitt")
    ├─ Mit Braut-Indikator (Jungfr., weiblicher Vorname)
    └─ oder implizit ("Sohn" + weiblicher Vorname)
    ↓
    BRÄUTIGAM-TEIL          ||      BRAUT-TEIL
    (vor Trenner)           ||      (nach Trenner)
    ├─ Vorname suchen       ||      ├─ Anrede überspringen
    │  (männl. Vornamen)    ||      │  (Jungfr., Frau)
    ├─ Nachname suchen      ||      ├─ Vorname(n) sammeln
    │  (1-3 Wörter)         ||      │  (weib. Vornamen + Doppelnamen)
    ├─ Vater-Vorname        ||      ├─ Vater-Vorname suchen
    │  (männl. Name)        ||      │  (falls da)
    ├─ Vater-Nachname       ||      ├─ Nachname extrahieren
    │  (Genitiv)            ||      │  (Genitiv-bereinigt)
    ├─ Beruf erkennen       ||      ├─ Stand erkennen
    │  (BERUFE-Liste)       ||      │  (Witwe, Hausfrau, etc.)
    ├─ Ort erkennen         ||      ├─ Ort erkennen
    │  (zu, von, alhier)    ||      │  (zu, von, alhier)
    └─ Stand erkennen       ||      └─ (Alle Felder)
       (Wittwer, Sohn)      ||
    ↓
RESULT mit 13 Feldern zurückgeben
```

### BEGRÄBNIS: Sequentielle Extraktion

```
ZITATION EXTRAHIEREN
    ↓ (ev. Kb. Wetzlar ⚰ YYYY.MM.DD p. Seite Nr. Nummer)
TEXTE NACH ZITATION
    ↓ (Split in Wörter, Satzzeichen entfernen)
    ↓
SEQUENTIELLE ANALYSE (Wort für Wort):
    ├─ [0] Vorname suchen
    │   ├─ Weiblich? → ist_weiblich = true
    │   └─ Männlich? → ist_weiblich = false
    │
    ├─ [1] Doppelname? (Same gender only)
    │
    ├─ [2] Nachname/Partner?
    │   ├─ Wenn weiblich + nächst männlich: Partner!
    │   └─ Ansonsten: Nach-Vornamen-Nachname
    │
    ├─ [3] Stand erkennen
    │   ├─ Mit Präfix (gewesener, hinterlassene)
    │   └─ Fallback im Original-Text
    │
    ├─ [4] Stand-basierte Partner-Logik
    │   ├─ Partner ∈ {Sohn, Tochter, Witwe}?
    │   │  ├─ JA + männlich Vorname → Partner!
    │   │  ├─ JA + weiblich Vorname → Vorname bleibt
    │   │  └─ SONDER: Witwe + "weiland/seel" → Rückwärts-Suche!
    │   └─ Nachname bleibt Familienname
    │
    ├─ [5] Beruf (KONTEXTBASIERT!)
    │   ├─ Mit Artikel: "der Müller" ✅
    │   ├─ Mit Einleitung: "ein Müller" ✅
    │   ├─ Mehrere: "u und" Müller" ✅
    │   └─ Ohne Artikel: ❌ (zu fehleranfällig)
    │
    ├─ [6] Ort erkennen
    │   └─ (zu, von, in der)
    │
    ├─ [7] Genitiv-Entfernung
    │   ├─ Mit Ausnahmen: Vornamen, lateinische Namen, Diminutive
    │   └─ Erweiterte Logik!
    │
    └─ [8] Alter + Geburtsjahr (regex!)
        └─ aetatis/alter + Zahl → geb_jahr_gesch = todes_jahr - alter
```

---

## Feldvergleich: Was wird wo gefüllt?

```
┌──────────────┬──────────────────────────────┬──────────────────────────────┐
│    FELD      │         HEIRAT               │       BEGRÄBNIS              │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ vorname      │ Bräutigam-Vorname            │ Verstorbene Person           │
│              │ (männlich)                   │ (weiblich/männlich)          │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ nachname     │ Bräutigam-Nachname           │ (Verdorbene Person)          │
│              │ (ggf. von Vater korr.)       │ (können auch Ehegatte sein!) │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ partner      │ Braut-Vorname(n)             │ = Ehegatte/Vater/Mutter      │
│              │ (weiblich)                   │ (abhängig von Stand)         │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ braeutigam_s │ Bräutigam-Stand              │ ❌ NICHT VORHANDEN           │
│ tand         │ (Wittwer, Sohn)              │                              │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ braut_stand  │ Braut-Stand                  │ ❌ NICHT VORHANDEN           │
│              │ (Witwe, Hausfrau)            │                              │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ stand        │ ❌ NUR in braut_stand        │ Allgemeiner Stand            │
│              │                              │ (Witwe, Vater, Sohn)         │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ braeutigam_v │ Bräutigam-Vater (Vorname)    │ ❌ NICHT VORHANDEN           │
│     ater     │                              │                              │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ braut_vater  │ Braut-Vater (Vorname)        │ ❌ NICHT VORHANDEN           │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ braut_nachna │ Braut-Nachname               │ ❌ NICHT VORHANDEN           │
│      me      │                              │                              │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ braut_ort    │ Braut-Wohnort                │ ❌ NICHT VORHANDEN           │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ beruf        │ Bräutigam/Braut-Beruf        │ Berufs-Info (Müller, etc.)   │
│              │ (meist Bräutigam)            │ (KONTEXTBASIERT)             │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ ort          │ Wohnort (Bräutigam/Braut)    │ Wohnort (Verstorbener)       │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ todestag     │ Hochzeitsdatum               │ Sterbedatum                  │
│              │ (∞ Symbol)                   │ (⚰ Symbol)                   │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ seite        │ Seite im Kirchenbuch         │ Seite im Kirchenbuch         │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│ nummer       │ Nummer im Kirchenbuch        │ Nummer im Kirchenbuch        │
├──────────────┼──────────────────────────────┼──────────────────────────────┤
│geb_jahr_gesch│ ❌ NICHT VORHANDEN           │ Geschätztes Geburtsjahr      │
│              │                              │ (aus Alter berechnet)        │
└──────────────┴──────────────────────────────┴──────────────────────────────┘
```

---

## Beispiel-Durchläufe

### HEIRAT-Beispiel: "Johann Peter verdrieß, Christoff verdriessen und jungfr Anna Maria Schmidts"

```
Zitation erkannt: ✓
Text nach Zitation: "Johann Peter verdrieß, Christoff verdriessen und jungfr Anna Maria Schmidts"

=== BRÄUTIGAM-TEIL (vor "und") ===
Wörter: [Johann, Peter, verdrieß, Christoff, verdriessen]

Vorname-Suche:
  - "Johann" ∈ MAENNLICHE_VORNAMEN? ✓
  - Doppelname? "Peter" ∈ MAENNLICHE_VORNAMEN? ✓ → vorname = "Johann Peter"

Nachname-Suche:
  - Folgt Vater-Vorname nach "Peter"? "verdrieß" ∈ MAENNLICHE_VORNAMEN? ✗
  - Prüfe Pattern: "verdrieß" + "Christoff verdriessen" [Stand]
  - Stand "Sohn" später gefunden → nachname = "verdrieß"
  - Vater-Vorname: "Christoff" ✓
  - Vater-Nachname: "verdriessen" → "verdriessen" (Genitiv-s entfernt)

Ergebnis:
  vorname: Johann Peter
  nachname: verdrieß
  braeutigam_vater: Christoff
  (Partner-Nachname würde aus Vater-Nachname berechnet)

=== BRAUT-TEIL (nach "und") ===
Wörter: [jungfr, Anna, Maria, Schmidts]

Anrede überspringen: "jungfr" → idx = 1

Vorname-Suche:
  - "Anna" ∈ WEIBLICHE_VORNAMEN? ✓
  - Doppelname? "Maria" ∈ WEIBLICHE_VORNAMEN? ✓ → partner = "Anna Maria"

Nachname-Suche:
  - "Schmidts" (Genitiv) → braut_nachname = "Schmidt"

Final Result:
  ✓ vorname: Johann Peter
  ✓ nachname: verdrieß/verdriessen
  ✓ partner: Anna Maria
  ✓ braeutigam_vater: Christoff
  ✓ braut_nachname: Schmidt
```

---

### BEGRÄBNIS-Beispiel 1: "Anna Müller, Witwe Johann Schmidts sel verlassen"

```
Zitation erkannt: ✓
Text nach Zitation: "Anna Müller, Witwe Johann Schmidts sel verlassen"

Sequentielle Analyse:
Wörter: [Anna, Müller, Witwe, Johann, Schmidts, sel, verlassen]

[1] Vorname:
  - "Anna" ∈ WEIBLICHE_VORNAMEN? ✓
  - ist_weiblich = true
  - Doppelname? "Müller" ∈ WEIBLICHE_VORNAMEN? ✗ → STOP

[2] Nachname/Partner:
  - Weiblich + nächst männlich? "Müller" ∈ MAENNLICHE_VORNAMEN? ✗
  - Nach-Vornamen-Nachname: "Müller" → nachname = "Müller"

[3] Stand:
  - "Witwe" ∈ STAND_MAPPING? ✓ → stand = "Witwe"

[4] Partner-Logik:
  - stand ∈ PARTNER_STÄNDE (Witwe)? ✓
  - ist_weiblich (Anna) = true
  - Regel: Weiblich + Witwe → Einziger Name bleibt Vorname!
  - → Partner = bleibt LEER (nicht "Anna"!)

[5] Suchе nach "seel/weiland":
  - "sel" gefunden bei Index 5
  - Rückwärts vor "sel": "Johann" (MAENNLICHE_VORNAMEN) ✓
  - → partner = "Johann"
  - Nachname nach Johann: "Schmidts" → Genitiv-bereinigung → "Schmidt"
  - (Überschreibt nachname, da von Partner)

Final Result:
  ✓ vorname: Anna
  ✓ nachname: Müller (oder Schmidt je nach Logik)
  ✓ partner: Johann (der Ehegatte!)
  ✓ stand: Witwe
  ✓ geb_jahr_gesch: (nicht vorhanden, kein Alter)
```

---

### BEGRÄBNIS-Beispiel 2: "Johann Schmid, Sohn Jakob Peters"

```
Zitation erkannt: ✓
Text nach Zitation: "Johann Schmid, Sohn Jakob Peters"

Sequentielle Analyse:
Wörter: [Johann, Schmid, Sohn, Jakob, Peters]

[1] Vorname:
  - "Johann" ∈ MAENNLICHE_VORNAMEN? ✓
  - ist_weiblich = false

[2] Nachname:
  - Nach-Vornamen-Nachname: "Schmid" → nachname = "Schmid"

[3] Stand:
  - "Sohn" ∈ STAND_MAPPING? ✓ → stand = "Sohn"

[4] Partner-Logik:
  - stand ∈ PARTNER_STÄNDE (Sohn)? ✓
  - ist_weiblich = false (Johann ist männlicher Vorname)
  - Regel: Männlich + Sohn → Vater-Logik anwenden!
  - → partner = "Johann"
  - vorname = NULL

[5] Vater-Nachname suchen:
  - Nach Partner-Vornamen: "Peters" (Genitiv) → entferne_genitiv() → "Peter"
  - (Dies würde als Partner-Info genutzt)

Final Result:
  ✓ vorname: NULL (entfernt, weil Sohn!)
  ✓ nachname: Schmid
  ✓ partner: Johann (= Vater!)
  ✓ stand: Sohn
```

---

### BEGRÄBNIS-Beispiel 3: "Maria Schäfer, Sohn 12 Jahr alt"

```
Zitation erkannt: ✓
Text nach Zitation: "Maria Schäfer, Sohn 12 Jahr alt"

Sequentielle Analyse:
Wörter: [Maria, Schäfer, Sohn, 12, Jahr, alt]

[1] Vorname:
  - "Maria" ∈ WEIBLICHE_VORNAMEN? ✓
  - ist_weiblich = true

[2] Nachname:
  - Nach-Vornamen-Nachname: "Schäfer" → nachname = "Schäfer"

[3] Stand:
  - "Sohn" ∈ STAND_MAPPING? ✓ → stand = "Sohn"

[4] Partner-Logik:
  - stand ∈ PARTNER_STÄNDE (Sohn)? ✓
  - ist_weiblich = true (Maria ist weiblicher Vorname)
  - Regel: Weiblich + Sohn → Keine Partner-Logik!
  - → vorname = "Maria" bleiben!
  - → partner = bleibt LEER (Mutter!)

[5] Altersberechnung:
  - "10 Jahr" gefunden:
  - Alter = 12 Jahre
  - geb_jahr_gesch = 1620 - 12 = 1608

Final Result:
  ✓ vorname: Maria
  ✓ nachname: Schäfer
  ✓ partner: NULL (Mutter, nicht Partner!)
  ✓ stand: Sohn
  ✓ geb_jahr_gesch: 1608 (geschätzt!)
```

---

## Kritische Unterschiede (Zusammenfassung)

| Aspekt | Heirat | Begräbnis |
|--------|--------|-----------|
| **Trennung der Personen** | Expliziter Trenner ("und") | Sequentielle Analyse + Stand- abhängig |
| **Vater-Felder** | Separate Felder (braeutigam_vater, braut_vater) | Im "partner"-Feld kodiert |
| **Partner-Bestimmung** | Struktur: Braut = die weibliche Person | Stand-abhängig + Gender-abhängig |
| **Beruf-Kontext** | Einfach: Alle BERUFE-Treffer | Komplex: Nur mit Artikel/Einleitung |
| **Alter/Geburt** | Nicht berechnet | Aus Altersangabe extrapoliert |
| **Genitiv-Logik** | Einfach ("-s", "-en", "-es") | Erweitert (Vornamen-Ausnahmen, Latein) |
| **Robustheit** | Hoch (klare Trennung) | Niedrig (mehrdeutig, kontextabhängig) |

