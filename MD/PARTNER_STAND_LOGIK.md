# Partner-Stand-Logik - Änderungen

## Problem
Bei Begräbnis-Einträgen für Kinder (Tochter/Sohn) oder Witwen wurde der Name des Vaters bzw. verstorbenen Ehepartners fälschlicherweise als Vorname/Nachname der verstorbenen Person erkannt.

**Beispiel:**
```
ev. Kb. Wetzlar ⚰ 1672.00.00. p. 60 Nr. 6 Johan Eberhard Frinck ein Töchterlein begraben laßen den 18. ten, Julii, aetatis 1. jahr, 14 wochen 1672
```

**Falsch erkannt:**
- Vorname: Johan
- Nachname: Eberhard
- Stand: Tochter

**Erwartet:**
- Vorname: (leer)
- Nachname: Frinck
- Partner: Johan Eberhard
- Stand: Tochter

## Lösung

### 1. Neue Liste in `extraction_lists.py`

Hinzugefügt: `PARTNER_STÄNDE` - Liste der Stände, bei denen der erkannte Name zum Partner gehört:

```python
PARTNER_STÄNDE = [
    "tochter", "dochter", "töchterlein", "döchterlein",
    "sohn", "sohnlein", "söhnlein", "son",
    "witwe", "wittib", "wittwe", "witbe", "widwe",
    "witwer", "wittwer"
]
```

### 2. Angepasste Logik in `gui.py`

Nach der Stand-Erkennung wird geprüft, ob es sich um einen "Partner-Stand" handelt:

```python
# === PARTNER-STAND-LOGIK ===
if stand:
    stand_lower = stand.lower()
    # Entferne Präfixe (z.B. "gewesene Witwe" -> "witwe")
    stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
    
    if stand_base in PARTNER_STÄNDE:
        # Der erkannte Vorname+Nachname gehört zum Partner/Vater
        if vorname and nachname:
            partner = f"{vorname} {nachname}"
        elif vorname:
            partner = vorname
        elif nachname:
            partner = nachname
        
        # Vorname der verstorbenen Person ist leer
        vorname = None
        
        # Nachname bleibt erhalten (vom Partner übernommen)
```

### 3. Betroffene Funktionen

Die Logik wurde implementiert in:
1. `_recognize_fields_ocr()` - Zeile ~1520: Für einzelne OCR-Erkennungen im OCR-Tab
2. `_run_recognition_selected()` - Zeile ~1175: Für Batch-Verarbeitung im Datenbank-Tab

## Regeln

1. **Bei Stand = Tochter/Sohn:**
   - Erkannter Name → Partner (= Vater)
   - Vorname → leer (außer explizit genannt)
   - Nachname → vom Partner übernommen

2. **Bei Stand = Witwe/Witwer:**
   - Erkannter Name → Partner (= verstorbener Ehegatte)
   - Vorname → leer (außer explizit genannt)
   - Nachname → vom Partner übernommen

3. **Bei anderen Ständen (Hausfrau, Vater, etc.):**
   - Keine Änderung, Name bleibt bei Vorname/Nachname

## Beispiele

### Beispiel 1: Tochter
```
Text: Johan Eberhard Frinck ein Töchterlein begraben laßen
Ergebnis:
- Vorname: (leer)
- Nachname: Frinck
- Partner: Johan Eberhard Frinck
- Stand: Tochter
```

### Beispiel 2: Sohn
```
Text: Heinrich Müller Sohn begraben
Ergebnis:
- Vorname: (leer)
- Nachname: Müller
- Partner: Heinrich Müller
- Stand: Sohn
```

### Beispiel 3: Witwe
```
Text: Hans Schmidt hinterlassene Wittwe
Ergebnis:
- Vorname: (leer)
- Nachname: Schmidt
- Partner: Hans Schmidt
- Stand: Wittwe
```

### Beispiel 4: Normaler Fall (keine Änderung)
```
Text: Maria Schneider Hausfrau
Ergebnis:
- Vorname: Maria
- Nachname: Schneider
- Partner: (leer)
- Stand: Hausfrau
```

## Hinweise

- Die Logik funktioniert auch bei Präfixen wie "gewesene Witwe", "hinterlassener Sohn"
- Wenn der eigene Name des Kindes explizit genannt wird (z.B. "Anna, Tochter des Hans Müller"), muss dies manuell korrigiert werden
- Die automatische Erkennung setzt den Vorname immer auf leer bei Partner-Ständen
