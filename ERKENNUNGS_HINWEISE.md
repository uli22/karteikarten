# Hinweise zur Feld-Erkennung

## Zitation
**WICHTIG**: Die Zitation gehört NICHT zum zu analysierenden Text!

### Zitations-Format
```
ev. Kb. Wetzlar ∞ YYYY.MM.DD p. X Nr. Y
```

### Ablauf der Erkennung
1. **Zitation extrahieren**: Das Zitations-Pattern wird vom Anfang des Textes erkannt und entfernt
2. **Relevanten Text bestimmen**: Der Text NACH der Zitation wird analysiert
3. **Stopwords beachten**: Der relevante Text endet VOR Stopwords wie "hielten", "hilt", "hochzeit", "copulirt", etc.
4. **Felder extrahieren**: Nur der bereinigte Text wird für die Feld-Erkennung verwendet

### Beispiel
```
Eingabe: ev. Kb. Wetzlar ∞ 1599.11.22 p. 18 Nr. 1 Jorg Henckel Donges Henkels Sohn hilt hochzeit mitt Catharein hanß selbergs selig Tochter von Kirchfers

Zitation (wird entfernt): ev. Kb. Wetzlar ∞ 1599.11.22 p. 18 Nr. 1
Nach Zitation: Jorg Henckel Donges Henkels Sohn hilt hochzeit mitt Catharein hanß selbergs selig Tochter von Kirchfers
Stopword-Position: "hilt" bei Position X
Relevanter Text: Jorg Henckel Donges Henkels Sohn [STOPP vor "hilt"]
Trenner: "mitt" (zwischen Bräutigam und Braut)
```

## Heirats-Erkennung

### Trenner-Wörter
Die folgenden Wörter trennen Bräutigam- und Braut-Teil:
- "und", "undt"
- "mitt", "mit"

### Stopwords (Textendemarkierungen)
Diese Wörter markieren das Ende des zu analysierenden Textes:
- "hielten", "hilten", "hilt"
- "hochzeit"
- "copulirt", "copuliret", "copulati"
- "getraut", "getrauet"

### Struktur Bräutigam-Teil
```
[Vorname] [Nachname] [Vater-Vorname] [Vater-Nachname-Genitiv] [Stand]
Beispiel: Jorg Henckel Donges Henkels Sohn
→ Vorname: Jorg
→ Nachname: Henckel (eigener)
→ Bräutigam Vater: Donges
→ Bräutigam Stand: Sohn
```

### Struktur Braut-Teil
```
[Vorname] [Vater-Vorname] [Vater-Nachname-Genitiv] [ignoriere] [Stand] [Ort-Präposition] [Ort]
Beispiel: Catharein hanß selbergs selig Tochter von Kirchfers
→ Partner: Catharein
→ Braut Vater: hanß
→ Braut Nachname: selberg (von "selbergs")
→ Stand: Tochter
→ Braut Ort: Kirchfers
```

## Zu ignorierende Wörter
Diese Wörter werden beim Parsing übersprungen:
- "selig", "seel", "sel", "sel."
- "weiland", "weilandt", "weyland"
- "hinterlassene", "hinterlassen"
- "gewesener", "gewesenen", "gewesene"
- "ehel", "ehelicher", "ehelichen"
- etc.
