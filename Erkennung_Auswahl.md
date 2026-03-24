# Erkennung (Auswahl) – Begräbnis

Die folgenden Schritte werden bei der strukturierten Erkennung für den Typ "Begräbnis" durchgeführt. Für jeden Schritt gibt es ein Beispiel.

---

**1. Zitation erkennen**
- Die Zitation am Anfang des Textes wird per Regex extrahiert.
- Beispiel:  
  `ev. Kb. Wetzlar ⚰ 1698.02.04 p. 114 Nr. 6 Text ...`  
  → Zitation: „ev. Kb. Wetzlar ⚰ 1698.02.04 p. 114 Nr. 6“

**2. Stopwort finden**
- Der Text wird bis zum ersten Stopwort (z.B. „Text“, „begraben“, „begr.“) betrachtet.
- Beispiel:  
  `... Nr. 6 Anna Engel Müller Tochter in Wetzlar begraben ...`  
  → Stopwort: „begraben“

**3. Wörter nach Zitation splitten**
- Die Wörter nach der Zitation werden in eine Liste aufgeteilt.
- Beispiel:  
  `Anna Engel Müller Tochter in Wetzlar`  
  → Wörter: `[Anna, Engel, Müller, Tochter, in, Wetzlar]`

**4. Vorname erkennen**
- Das erste Wort (oder die ersten zwei) aus der Vornamenliste wird als Vorname erkannt.
- Beispiel:  
  `Anna Engel Müller ...`  
  → Vorname: „Anna Engel“

**5. Nachname erkennen**
- Das nächste Wort nach dem Vornamen, das kein Stand, Ort oder Beruf ist.
- Beispiel:  
  `Anna Engel Müller Tochter ...`  
  → Nachname: „Müller“

**6. Partner erkennen**
- Wenn nach einem weiblichen Vornamen ein männlicher folgt, ist das der Partner.
- Beispiel:  
  `Anna Engel Johann Peter ...`  
  → Partner: „Johann Peter“

**7. Stand erkennen**
- Das nächste Wort aus der Stand-Synonymliste.
- Beispiel:  
  `... Tochter ...`  
  → Stand: „Tochter“

**8. Ort erkennen**
- Nach Präpositionen wie „in“, „in der“, „von“, „zu“ folgt der Ort.
- Beispiel:  
  `... in Wetzlar ...`  
  → Ort: „Wetzlar“

**9. Beruf erkennen**
- Nach „ein <Beruf>“ wird der Beruf extrahiert.
- Beispiel:  
  `... ein Schuster ...`  
  → Beruf: „Schuster“

**10. Todestag erkennen**
- Das Datum aus der Zitation wird als Todestag übernommen.
- Beispiel:  
  `1698.02.04`  
  → Todestag: „1698.02.04“

---

Jeder Schritt prüft, ob das Feld bereits erkannt wurde, und geht dann zum nächsten. Die Extraktion ist robust gegenüber Reihenfolge und Synonymen.
