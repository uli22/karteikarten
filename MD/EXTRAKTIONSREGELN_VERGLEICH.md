# Namenserkennung: Heirat vs. Begräbnis – Detaillierte Regelübersicht

## 1. Zitationsmuster und Feldstruktur

### Heirat (`_extract_marriage_fields`)
```
Zitation: [ev. Kb. Wetzlar] ∞ YYYY.MM.DD p. Seite Nr. Nummer
Struktur: [Bräutigam-Teil] [Trenner] [Braut-Teil] [Hochzeits-Ende]
```

### Begräbnis (`_extract_burial_fields`)
```
Zitation: [ev. Kb. Wetzlar] ⚰ YYYY.MM.DD p. Seite Nr. Nummer
Struktur: [Sequenzielle Erkennung ohne Trenner]
```

---

## 2. Vornamen & Nachnamen – Erkennungsregeln

### 🔷 HEIRAT

#### **Bräutigam-Teil: Vorname**
1. Überspringe **Anreden** ("Herr", "H.") und Ignoriere-Wörter
2. Suche **männliche Vornamen** in MAENNLICHE_VORNAMEN-Liste
3. **Doppelnamen**: NUR wenn gleiches Geschlecht folgt
   - Beispiel: `"Johann Peter verdrieß"` → Vorname: "Johann Peter"
4. Falls kein Vorname erkannt: **nimm erstes Wort** als Fallback

#### **Bräutigam-Teil: Nachname**
Wird durch **komplexe Logik** bestimmt basierend auf nachfolgenden Elementen:

| Muster | Beispiel | Regel |
|--------|----------|-------|
| `[Nachname] [Vater-Vorname] [Vater-Nachname-Gen.]` | "Jorg Henckel Donges Henkels" | Erkannt wenn **Stand-Wort** später folgt |
| `[Nachname] [Vater-Vorname] [Vater-Nachname-Gen.] [Stand]` | "Jorg Henckel Donges Henkels Sohn" | Besitzt Bräutigam-Nachname + Vater-Info |
| `[Vater-Vorname] [Vater-Nachname-Gen.]` | "Peter Schäfers" | Nachname = Vater-Nachname nach Genitiv-Bereinigung |
| Bei Beruf erkannt | z.B. mit "Bäcker" | Kein Vater-Nachname-Parsing |

**Genitiv-Entfernung Regeln für Bräutigam:**
- `-en` am Ende (bei längerem Wort): "Baussen" → "Bauss"
- `-es` am Ende: "Schmidtes" → "Schmidt"
- `-s` am Ende (wenn Konsonant + s): "Zahns" → "Zahn"

---

#### **Braut-Teil: Vorname(n)**
1. **Überspringe** Anreden ("Jungfr.", "Frau") und Ignoriere-Wörter
2. Sammle **alle weiblichen Vornamen** hintereinander (Doppelnamen!)
   - Beispiel: `"Christiana Anna Ottilie"` → Vorname: "Christiana Anna Ottilie"
3. **Stoppe** bei: männlichem Vorname (= Vater), Zahlen, Genitiv-Wort
4. Wenn **letztes Wort kein bekannter Vorname**: Es ist der **Braut-Nachname**
   - Beispiel: `"Anna Güttin"` → Vorname: "Anna", Nachname: "Güttin"

#### **Braut-Teil: Nachname**
**Fall A: Mit Vater-Vorname**
```
[Anrede] [Vorname(n)] [Vater-Vorname] [Vater-Nachname-Gen.]
Beispiel: "jungfr Anna Johann Schmidts"
→ Vorname: Anna, Partner-Nachname: Schmidt (nach Genitiv-Bereinigung)
```

**Fall B: Ohne Vater-Vorname (Witwe)**
```
[Vater-Nachname-Gen.] [Ehemann-Nachname-Gen.]
Beispiel: "jungfr Anna Schmidts Müller[s]"
→ Vorname: Anna, Nachname-1: Schmidt, Nachname-2: Müller (nur als Fallback info)
```

---

### 🔷 BEGRÄBNIS

#### **Vorname (universell)**
1. Überspringe **Anreden** ("Frau", "Herr", "H.") und Ignoriere-Wörter
2. Suche **ERSTE** Vornamen (männlich ODER weiblich) in Listen
3. **Doppelnamen NUR mit gleichem Geschlecht**:
   ```python
   if ist_weiblich and words[idx] in weibliche_vornamen:
       vorname += " " + words[idx]
   elif not ist_weiblich and words[idx] in maennliche_vornamen:
       vorname += " " + words[idx]
   ```
4. Merke Gender: `ist_weiblich = True/False`

#### **Nachname (Seriell nach Vorname)**
1. Wenn kein Nachname am Anfang (vor Vorname):
   - Suche **direkt nach Vorname**, überspringe Ignoriere-Wörter
   - Ist das Wort kein Vorname, Stand, Beruf, Artikel, Präposition → **das ist Nachname**
2. Beispiel: `"Just Roder, Caspar Roders Sohn"`
   - Heureka: Nachname "Roder" VOR Vorname "Just" erkannt

#### **Partner-Erkennung (AUTOMATISCH durch Vorname-Kombination)**
- **Muster 1**: Weiblicher Vorname gefolgt von männlichem Vorname
  ```
  Catharina Johann → Catharina (vorname), Johann (partner)
  ```
- **Muster 2**: Nur männlicher Vorname (kein weiblicher) → Suche im ganzen Text nach Partner
  - Wenn **Stand = "Sohn"/"Tochter"/"Witwe"** → männlicher Vorname = Partner (Eltern/Ehegatte)

---

## 3. "Herr" / Anredebehandlung

### Heirat
- **Wird übersprungen** am Anfang von Bräutigam und Braut
- Wird in Wörter-Liste gelöscht, bevor Namen erkannt werden

### Begräbnis
- **Wird übersprungen** vor jedem Vornamen
- Spezialfall: "Herr" vor Genitiv-Namen (z.B. "Herr Johanns Sohn")
  - Wird nicht als Anrede erkannt, sondern ignoriert um Partner zu finden

---

## 4. Doppelnamen – Regeln

### Heirat

**Bräutigam:**
```python
# Sammle NUR männliche Vornamen
while words[idx] in maennliche_vornamen:
    vorname_parts.append(words[idx])
    idx += 1
```

**Braut:**
```python
# Sammle NUR weibliche Vornamen
while idx < len(braut_words) and words[idx] in weibliche_vornamen:
    # bis zu männlichem Vornamen (= Vater)
```

**Beispiele:**
- ✅ "Johann Peter verdrieß und jungfr Johanna Maria Schmidt"
  - Bräutigam: "Johann Peter", Braut: "Johanna Maria"
- ❌ "Johann Johanna verdrieß" → FALSCH (geschlechtsgemischt)
  - Hier wird nur "Johann" genommen, "Johanna" → nächster Schritt

### Begräbnis

```python
# Gleiche Regel: 
if ist_weiblich and next_vorname in weibliche_vornamen:
    vorname += " " + next_vorname
elif not ist_weiblich and next_vorname in maennliche_vornamen:
    vorname += " " + next_vorname
```

**Beispiele:**
- ✅ "Anna Maria Schmidt, Witwe" → Vorname: "Anna Maria"
- ✅ "Johann Peter Müller, Sohn" → Vorname: "Johann Peter"

---

## 5. Vater-Felder

### Heirat
- **`braeutigam_vater`**: Vater des Bräutigams (separates Feld!)
- **`braut_vater`**: Vater der Braut (separates Feld!)
- **Extraction Logik:**
  ```
  [Bräutigam-Nachname] [Vater-Vorname] [Vater-Nachname-Gen.]
  Jorg verdrieß, Henckels [Sohn]
  → Vater: Henckel (Vorname), Nachname: Verdrieß (korrigiert) oder Henckel (von Vater)
  ```

### Begräbnis
- **`partner`**: Kann auch Vater/Mutter sein (je nach Stand!)
- **Extraction über Stand-Logik:**
  ```
  "Anna Müller, Sohn Jakob"
  → Stand = Sohn → Partner = Jakob (Vater)
  ```

---

## 6. Genitiv-Entfernung – Detaillierte Logik

### Heirat
```python
def remove_genitiv_s(name):
    if name.endswith('en') and len(name) > 3:
        return name[:-2]  # Baussen → Bauss
    elif name.endswith('es') and len(name) > 3:
        return name[:-2]  # Schmidtes → Schmidt
    elif name.endswith('s') and len(name[-2]) not in 'aeiouäöü':
        return name[:-1]  # Zahns → Zahn
    return name
```

### Begräbnis (ERWEITERT)
```python
def entferne_genitiv(wort):
    # Vornamen NICHT ändern!
    if wort in maennliche_vornamen or wort in weibliche_vornamen:
        return wort
    
    # Kurze Namen auf -s behalten (Hans, Bos)
    if len(wort) <= 3 and wort.endswith('s'):
        return wort
    
    # LATEINISCHE GENITIVE nicht ändern! (Petri, Wilhelmi)
    if wort.endswith(('tri', 'pri', 'ri')) and len(wort) > 3:
        return wort
    
    # Diminutive nicht ändern (Müller-chen, Müller-lein)
    if wort.endswith(('chen', 'lein')):
        return wort
    
    # Erst dann Genitiv-Behandlung:
    if wort.endswith('is'):
        return wort[:-2]  # Kaullis → Kaull
    elif wort.endswith('ii'):  # Besonderheit für Kaulii
        return wort[:-1]  # Kaulii → Kauli
    elif wort.endswith('i') and len(wort) > 2:
        return wort[:-1]  # Wilhelmi → Wilhelm
    elif wort.endswith('en') and len(wort) > 3:
        return wort[:-2]  # Schmidten → Schmidt
    elif wort.endswith('s') and len(wort) > 2:
        return wort[:-1]  # Schmids → Schmid
```

**Wichtiger Unterschied:** Begräbnis hat **Ausnahmen für lateinische Namen und Vornamen**, was für historische Daten wichtig ist!

---

## 7. Beruf-Erkennung

### Heirat
1. **Alle Berufe** aus BERUFE-Liste werden erkannt, wenn sie im Text vorkommen
2. Wird **VOR** Nachname/Vater-Logik erkannt
3. Besonderheiten:
   - "Bürger" wird mit "alhier" (Wetzlar) gepaart
   - "alhier" oder "alhie" = Ort Wetzlar
   - Pattern `[Bürger] [Beruf] [alhier]` wird analysiert

### Begräbnis (KONTEXTBASIERT!)
1. **Nur Berufe mit Artikel** sind verlässlich:
   ```
   "der Müller", "die Bäckerin", "die Schneiderin"
   ```
2. **Mit Berufs-Einleitung** ("ein", "eine"):
   ```
   "ein Müller", "eine Köchin"
   ```
3. **Mehrere Berufe** (durch "u", "und"):
   ```
   "Bürger u. Müller"
   ```
4. **KEINE Artikel + Beruf** (zählt nicht als Beruf!)
   - Grund: Kann mit Nachnamen verwechselt werden

---

## 8. Stand-Erkennung

### Heirat
**Bräutigam:**
- Suche in STAND_MAPPING: "Sohn", "Wittwer", "Bürger"
- Vollständige Wortsuche zuerst, dann Fallback (Substring-Suche)

**Braut:**
- Suche in STAND_MAPPING: "Witwe", "Witib", "gewesene Hausfrau" etc.
- Lange Matches zuerst (z.B. "gewesene hausfrau" vor "hausfrau")

### Begräbnis
**Mit Präfixen:**
```python
if words[i].lower() in STAND_PRAEFIXE:  # z.B. "gewesener"
    stand_prefix = words[i] + " "
    stand = STAND_MAPPING.get(words[i+1])
```

**Fallback im Original-Text:**
- Sucht STAND_MAPPING-Schlüssel im unverarbeiteten Text
- Ferner auch Schreibvarianten wie "haußfraw"

**Partner-Stand-Logik (SPEZIFIKUM!):**
Wenn Stand ∈ PARTNER_STÄNDE ("Sohn", "Tochter", "Witwe"):
- Erkannter **Vorname wird zu Partner**
- **Nachname bleibt Familienname**
- Beispiel:
  ```
  "Maria Schäfer, Witwe" 
  → Vorname: Maria, Nachname: Schäfer, Partner: LEER
  (da weiblich + Witwe = Mutter, nicht Partner!)
  ```
  
  ```
  "Johann Schäfer, Witwe"
  → Vorname: (NULL), Partner: Johann, Nachname: Schäfer  
  (da männlich + Witwe = Ehegatte!)
  ```

---

## 9. Sonder-Logik: Witwe mit "weiland"/"seel"

### Heirat
- Nicht implementiert

### Begräbnis (ERWEITERT!)
```
Muster: "Catharina, Jost Diderichs seel verlassen Witwe"
Logik:
  1. Erkenne "Witwe" als Stand
  2. Suche nach "weiland"/"seel"
  3. NACH "seel/weiland": Suche männlichen Vornamen (= Ehegatte)
  4. ODER VOR "weiland": Rückwärts-Suche nach männlichem Vorname
  5. Entferne Genitiv-Endungen vom Partner-Namen
```

**Beispiele:**
- ✅ `"Catharina, Jost Diderichs seel verlassen Witwe"` 
  - Vorname: Catharina, Partner: Jost, Nachname: Diderich
- ✅ `"Witwe Elisabetha Johann Schmidts seelig"`
  - Vorname: Elisabetha, Partner: Johann, Nachname: Schmidt

---

## 10. Altersberechnung (NUR Begräbnis)

### Muster
```regex
(?:aetat(?:is)?|aet\.?|alters?)\s*(?:anno)?\s*(\d+)\s*(?:jahr|ann(?:i)?)?
```

**Beispiele erkannter Varianten:**
- "aetatis 72" → Alter: 72
- "alter 45 jahr" → Alter: 45
- "alters 19 anni" → Alter: 19
- "aetatisis anno 28" → Alter: 28

**Geburtsjahr-Berechnung:**
```
geb_jahr_gesch = todes_jahr - alter
z.B.: 1620 - 72 = 1548
```

---

## 11. Zusammenfassung: Warum bei Begräbnis Verbesserungen Schwieriger

| Problem | Grund | Lösungsansatz |
|---------|-------|---------------|
| **Keine klare Trennung** | Kein Trenner wie "und" → Sequentielle Analyse mühsam | Bessere Heuristiken für Bruch-Punkte (Stand, Ort) |
| **Partner mehrdeutig** | Kann Vater, Mutter, Ehegatte sein (abhängig von Stand + Gender) | Stand-abhängige Logik ist bereits implementiert |
| **Vornamen kontextabhängig** | "Vorname" kann Ehegatte sein (bei Witwe) oder Eltern (bei Sohn) | Partner-Stand-Logik ist vorhanden, aber komplex |
| **Genitiv-Varianten** | Lateinische Namen, Diminutive, Ausnahmen | Erweiterte entferne_genitiv() ist besser, aber Heurismen bleiben schwach |
| **Berufserkennung fehland** | Nur mit Artikel verlässlich, sonst Verwechslung mit Namen | Kontextbasis ist richtig, aber Artikel oft fehlend in OCR |
| **OCR-Fehler** | "Haus frau" statt "Hausfrau", "anno" statt "anno" | Robuste Pattern-Suche (StringSplitting-Fehler) |

---

## 🔍 Konkrete Verbesserungsideen für Begräbnis

1. **Nach-Vornamen-Heuristic**: Wenn mehrere Wörter nach Vorname follow, prüfe:
   - Ist es ein bekannter Nachname? (Länge, Groß-/Kleinschrift)
   - Oder ein Prädikat/Stand/Ortsangabe?

2. **Robust Genitiv-Erkennung**: 
   - Nutze volle `entferne_genitiv()`-Logik aus Begräbnis auch in Heirat?

3. **Partner-Vater-Unterscheidung**:
   - Wenn männlicher Vorname nach weiblichem Vornamen: Immer Partner?
   - Aber auch Heuristik: Name nach "Sohn" = Vater (schon implementiert)

4. **OCR-Fehler-Robuust machen**:
   - Fuzz-Matching für Vornamen (z.B. "Jhoann" → "Johann")?
   - Multi-Word-Substring-Matching für Berufe?

