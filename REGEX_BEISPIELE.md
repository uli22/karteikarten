# Regex-Ersetzung - Beispiele und Anleitung

## Wie verwende ich Regex-Ersetzung?

### Schritt-für-Schritt:

1. **Datenbank-Tab** öffnen
2. **Einträge auswählen** (die bearbeitet werden sollen)
3. **"Regex-Suche" Checkbox** aktivieren
4. **Suchfeld**: Regex-Pattern eingeben
5. **Ersetzen-Feld**: Ersetzungstext eingeben
6. **"Ersetzen" Button** klicken

---

## Beispiele

### 1. "aetatis" Varianten normalisieren

**Problem:** OCR erkennt "aetatis" (Alter) als verschiedene Varianten:
- actabis, actafis, actakes, actal, actalis, actat, actati, actatio, actatir, actatis, actativ, actator, actutis

**Lösung:**

**Suchfeld (Regex):**
```
act(abis|afis|akes|al|alis|at|ati|atio|atir|atis|ativ|ator|utis)
```

**Ersetzen-Feld:**
```
aetatis
```

**Ergebnis:**
- "alt 27ann. actatis" → "alt 27ann. aetatis"
- "actabis 30" → "aetatis 30"
- "actator 45" → "aetatis 45"

---

### 2. Weitere nützliche Regex-Patterns

#### Jahreszahlen normalisieren (Punkte entfernen)
**Suche:** `(\d{4})\.(\d{2})\.(\d{2})`  
**Ersetze:** `$1.$2.$3`  
Beispiel: `1694.04.27` bleibt `1694.04.27`

#### Mehrfache Leerzeichen entfernen
**Suche:** ` {2,}`  
**Ersetze:** ` ` (ein Leerzeichen)  
Beispiel: `Anna    Barbara` → `Anna Barbara`

#### "begr" zu "begraben" erweitern
**Suche:** `\bbegr\.?\b`  
**Ersetze:** `begraben`  
Beispiel: `Hans begr. d. 4. Mai` → `Hans begraben d. 4. Mai`

#### Genitiv-s bei Namen entfernen
**Suche:** `([A-Z][a-z]+)s\b`  
**Ersetze:** `$1`  
Beispiel: `Müllers Haus` → `Müller Haus`

---

## Regex-Syntax-Grundlagen

| Pattern | Bedeutung | Beispiel |
|---------|-----------|----------|
| `.` | Beliebiges Zeichen | `a.b` matched "aab", "abb", "acb" |
| `*` | 0 oder mehr | `ab*` matched "a", "ab", "abb" |
| `+` | 1 oder mehr | `ab+` matched "ab", "abb" (nicht "a") |
| `?` | 0 oder 1 | `ab?` matched "a", "ab" |
| `\|` | ODER | `(cat\|dog)` matched "cat" oder "dog" |
| `[]` | Zeichenklasse | `[abc]` matched "a", "b", oder "c" |
| `[^]` | NICHT in Klasse | `[^abc]` matched alles außer "a", "b", "c" |
| `\b` | Wortgrenze | `\bcat\b` matched "cat" (nicht "catch") |
| `\d` | Ziffer | `\d+` matched "123" |
| `\s` | Leerzeichen | `\s+` matched "   " |
| `()` | Gruppe (capture) | `(abc)` speichert "abc" für $1 |
| `$1, $2` | Gruppe einfügen | Ersetzung mit gespeicherten Gruppen |

---

## Tipps

1. **Testen Sie zuerst mit wenigen Einträgen!**
   - Wählen Sie nur 1-2 Einträge zum Testen aus
   - Prüfen Sie das Ergebnis
   - Dann auf mehr Einträge anwenden

2. **Regex-Fehler:**
   - Bei ungültigem Regex erscheint eine Fehlermeldung
   - Prüfen Sie die Syntax (siehe Tabelle oben)

3. **Case-Insensitive:**
   - Die Suche ignoriert Groß-/Kleinschreibung automatisch
   - "actatis" findet auch "ACTATIS" oder "Actatis"

4. **Backup:**
   - Exportieren Sie Ihre Daten regelmäßig (CSV Export)
   - So können Sie Änderungen rückgängig machen

---

## Häufige Anwendungsfälle

### OCR-Fehler korrigieren
```regex
Suche:  w\.Kb\.
Ersetze: ev. Kb.
```

### Datumsformat vereinheitlichen
```regex
Suche:  (\d{4})[ .](\d{2})[ .](\d{2})
Ersetze: $1.$2.$3
```

### Sonderzeichen normalisieren
```regex
Suche:  [⚰︎□⚱]
Ersetze: ⚰
```

### Abkürzungen auflösen
```regex
Suche:  \bp\.\s*(\d+)
Ersetze: p. $1
```

---

## Warnung

⚠️ **Regex-Ersetzungen sind irreversibel!**  
- Keine Undo-Funktion
- Backup empfohlen
- Erst an wenigen Einträgen testen
