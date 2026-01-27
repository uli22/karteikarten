"""Text-Nachbearbeitungs-Modul für OCR-Ergebnisse."""

import re
from typing import Dict


class TextPostProcessor:
    """Verbessert OCR-Ergebnisse durch Post-Processing."""
    
    def __init__(self):
        """Initialisiert den Post-Processor mit Korrektur-Regeln."""
        # Typische OCR-Fehler bei historischen deutschen Texten
        self.common_ocr_errors = {
            ' and ': ' und ',
            '&': '8',
            '15.65': '1565',
            '16.16.': '1616.',
            '; 8}': ';',
            'A+': 'A.',
            'Aeete': 'Agnes',
            'Authonius': 'Anthonius',
            'Bectolffs': 'Bertolffs',
            'Bore': 'Sohn',
            'D 1': 'D.1',
            'Do ': 'Ao ',
            'Hb': 'Heiraten/Begräbnisse',
            'Keler': 'Keler',
            'Kun': 'Kurt',
            'Mauwe': 'Maurer',
            'Mezitat': 'Mechthild',
            'Mr': 'Nr.',
            'Qga8ae': 'Caspar',
            'RrQzetda': 'Prozesda',
            'Schriener': 'Schreiner',
            'Wetzlar 2015.': 'Wetzlar ∞ 15',
            'as ': 'ao ',
            'do ': 'Ao ',
            'er. Kb.': 'ev. Kb.',
            'er.Kb.': 'ev. Kb.',
            'ev.Kb.': 'ev. Kb.',
            'ev.Kh.': 'ev. Kb.',
            'i~': 'in',
            'w. Kb.': 'ev. Kb.',
            'w.Kb.': 'ev. Kb.',
            '15.65': '1565',
            '16.16.': '1616.',  # Ihre neue Korrektur
            
            # Abkürzungen und Begriffe
            'ev.Kb.': 'ev. Kb.',
            'er. Kb.': 'ev. Kb.',
            'er.Kb.': 'ev. Kb.',
            'ev.Kh.': 'ev. Kb.',
            'w. Kb.': 'ev. Kb.',
            'w.Kb.': 'ev. Kb.',
            'Hb': 'Heiraten/Begräbnisse',
            ' and ': ' und ',
            'Mr': 'Nr.',
            
            # Anno (Jahr) - häufig falsch erkannt
            'do ': 'Ao ',
            'Do ': 'Ao ',
            'as ': 'ao ',
        }
        
        # Wörterbuch für wiederkehrende Kirchenbuch-Begriffe
        self.kirchenbuch_vocabulary = {
            'Begräbnis': ['Begräbnis', 'Beqräbnis', 'Beyräbnis'],
            'Bäcker': ['Bäcker', 'Bäcker', 'Backer'],
            'Bürger': ['Bürger', 'Bürqer', 'Burger'],
            'Bürgermeister': ['Burgermeister', 'Bürgermeifter'],
            'Catharina': ['Catharina', 'Catlrarina', 'Katharina'],
            'Conrad': ['Comat'],
            'Dillheim': ['Kilheim'],
            'Elisabeth': ['Elisabeth', 'Elisabetli', 'Elifabeth'],
            'Henrich': ['Kenrich'],
            'Hochzeit': ['Hochzeit', 'Hodzeit', 'Rodzeit', 'Rochzeit', 'Kochzeit', 'Hachzeit', 'nochzeit'],
            'Johann': ['Johann', 'Iohann', 'Jolrann'],
            'Kirchenbuch': ['Kirchenbuch', 'Rirchenbuch', 'Kirchenöuch'],
            'Maria': ['Maria', 'Naria', 'Marla'],
            'Maurer': ['Maurer', 'Mauwe', 'Maurcr'],
            'Meister': ['Meister', 'Meifter', 'Meiiter'],
            'Mutter': ['Mutter', 'Mutter', 'Murter'],
            'Niederbiel': ['Mider Biel'],
            'Pfarrer': ['Pfarrer', 'Piarrer', 'Plarrer'],
            'Schmied': ['Schmied', 'Sclimied', 'Schmierl'],
            'Schneider': ['Schneider', 'Schnoider', 'Sehneider'],
            'Schuster': ['Schuster', 'Schuiter', 'Schuſter'],
            'Sohn': ['Sohn', 'Solin', 'Sofin'],
            'Taufe': ['Taufe', 'Iaute', 'Tauie'],
            'Thunges': ['thanges'],
            'Tochter': ['Bock ter', 'Sochter'],
            'Vater': ['Vater', 'Uater', 'Varer'],
            'Weber': ['Weber', 'VVeber', 'Weder'],
            'Wetzlar': ['Wetzlar', 'VVetzlar', 'Wetzlar'],
            'Witwe': ['Witwe', 'Witue', 'VVitwe'],
            'Zeuge': ['Zeuge', 'Zeuqe', 'Jeuge'],
            'begraben': ['begraben', 'beqraben', 'beyraben'],
            'getauft': ['getauft', 'qetauft', 'getault'],
            'getraut': ['getraut', 'qetraut', 'getraut'],
            'hielten': ['hielten', 'Rielten', 'nielten', 'hilter'],
            'verheiratet': ['verheiratel', 'verheirated', 'verheirathet'],
            'wurden': ['wurden', 'vurden', 'wurcen'],
        }
        
        # Muster für strukturierte Daten (Kirchenbuch-spezifisch)
        self.patterns = {
            # Datum: YYYY.MM.DD
            'date': re.compile(r'(\d{4})\.?(\d{1,2})\.?(\d{1,2})'),
            # Nummer: Nr: 123 oder Nr. 123
            'number': re.compile(r'Nr:?\s*(\d+)'),
        }
    
    def process(self, text: str, aggressive: bool = False) -> str:
        """
        Führt Post-Processing auf dem OCR-Text aus.
        
        Args:
            text: Der rohe OCR-Text
            aggressive: Wenn True, werden mehr Korrekturen angewendet
            
        Returns:
            Bereinigter Text
        """
        if not text or text.startswith("Fehler"):
            return text
        
        original_text = text
        corrections_count = 0
        
        # 0. ZUERST: Whitespace bereinigen
        text = self._clean_whitespace(text)
        
        # 1. Korrigiere Kirchenbuch-Header-Muster
        text_before = text
        text = self._fix_kirchenbuch_header(text)
        if text != text_before:
            corrections_count += 1
            print(f"[POST-PROCESS] Header korrigiert")
        
        # 2. Entferne doppelte Leerzeichen
        text = re.sub(r'\s+', ' ', text)
        
        # 3. Korrigiere bekannte OCR-Fehler
        for error, correction in self.common_ocr_errors.items():
            if error in text:
                text = text.replace(error, correction)
                corrections_count += 1
                print(f"[POST-PROCESS] '{error}' → '{correction}'")
        
        # 4. Wörterbuch-basierte Korrektur (wichtigste Verbesserung!)
        text_before = text
        text = self._apply_vocabulary_corrections(text)
        if text != text_before:
            corrections_count += 1
            print(f"[POST-PROCESS] Wörterbuch-Korrekturen angewendet")
        
        # 5. Normalisiere Datumsformat
        text = self._normalize_dates(text)
        
        # 6. Normalisiere Nummern
        text = self._normalize_numbers(text)
        
        if aggressive:
            # 7. Entferne unwahrscheinliche Zeichen
            text = self._remove_unlikely_chars(text)
            
            # 8. Korrigiere bekannte Wortmuster
            text = self._fix_word_patterns(text)
        
        # NOCHMAL am Ende: Finale Whitespace-Bereinigung
        text = self._clean_whitespace(text)
        
        if corrections_count > 0:
            print(f"[POST-PROCESS] Gesamt: {corrections_count} Korrekturen")
        else:
            print(f"[POST-PROCESS] Keine Korrekturen nötig")
        
        return text
    
    def _clean_whitespace(self, text: str) -> str:
        """
        Bereinigt Whitespace im Text.
        
        - Entfernt führende/nachfolgende Leerzeichen
        - Reduziert mehrfache Leerzeichen auf eins
        - Entfernt Leerzeichen vor Satzzeichen
        - Normalisiert Zeilenumbrüche
        """
        # 1. Führende und nachfolgende Leerzeichen entfernen
        text = text.strip()
        
        # 2. Mehrfache Leerzeichen durch einzelnes ersetzen
        text = re.sub(r' {2,}', ' ', text)
        
        # 3. Mehrfache Zeilenumbrüche auf maximal 2 reduzieren
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 4. Leerzeichen vor Satzzeichen entfernen
        text = re.sub(r'\s+([.,;:!?])', r'\1', text)
        
        # 5. Tabs durch Leerzeichen ersetzen
        text = text.replace('\t', ' ')
        
        # 6. Leerzeichen nach Satzzeichen sicherstellen (falls fehlend)
        text = re.sub(r'([.,;:!?])([A-ZÄÖÜ])', r'\1 \2', text)
        
        return text
    
    def _fix_kirchenbuch_header(self, text: str) -> str:
        """
        Korrigiert typische Fehler im Kirchenbuch-Header.
        Beispiel: "w. Kb. Wetular 0016.01.01. p.16.Nr..4" 
              → "ev. Kb. Wetzlar ∞ 1611.01.01 p. 16. Nr. 4"
        """
        # NEU: Korrigiere "wv.", "sv.", "2v.", "Lev.", "H wv." etc. → "ev."
        text = re.sub(
            r'\b[Hw2LS]?[wvs]v?\.\s*Kb\.',
            'ev. Kb.',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: Korrigiere "et. Kb.", "er. Kb.", "av. Kb." → "ev. Kb."
        text = re.sub(
            r'\b[ea][tvr]\.\s*Kb\.',
            'ev. Kb.',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: Korrigiere Varianten wie "P. 17. Nr.2." am Anfang
        # "P. 17. Nr.2. ev. Kb." → "ev. Kb. ... p. 17. Nr. 2"
        text = re.sub(
            r'^[Pp]\.\s*(\d+)\.\s*[NM][rh]\.\s*(\d+)\.\s*(ev\.\s*Kb\.)',
            r'\3',
            text
        )
        
        # NEU: Korrigiere "Wednlar", "Wetular", "Webular" etc. → "Wetzlar"
        # Korrigiere "Wednlar", "Wetular", "Webular" etc. → "Wetzlar", aber schließe Wittwe, wittib, witbe etc. explizit aus
        text = re.sub(
            r'\b(Wed|Wet|Web|Wef|Wit)(?!twe|tib|tbe)[a-z]{2,5}\b',
            'Wetzlar',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: REGEX für alle "Wetzlar"-Varianten mit Satzzeichen + "00"
        text = re.sub(
            r'\b(Wetz|Wet|Web|Wef|Wit)[a-z]{2,5}[.,:\s]+00\b',
            'Wetzlar ∞',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: Korrigiere "Wetzlar:" → "Wetzlar"
        text = re.sub(
            r'(ev\.\s*Kb\.\s*)Wetz[a-z]+:',
            r'\1Wetzlar',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: Korrigiere "∞16." → "∞ 1611." (Punkt zwischen Jahr und Monat)
        # Matcht: ∞16.11.07.28 → ∞ 1611.07.28
        text = re.sub(
            r'∞(\d{2})\.(\d{2})\.(\d{2})\.(\d{2})',
            r'∞ 16\1.\2.\3',
            text
        )
        
        # NEU: ∞ klebt am Jahr (z.B. "∞1615.04." → "∞ 1615.04.00")
        # ABER NUR wenn noch kein Tag vorhanden ist (nicht bei ∞1615.04.23)
        text = re.sub(
            r'∞(\d{4})\.(\d{2})\.\s',  # GEÄNDERT: Nur wenn Leerzeichen nach Punkt
            r'∞ \1.\2.00 ',
            text
        )
        
        # NEU: Korrigiere falsche Tageszahl-Verdoppelung (z.B. "1616.03.0003" → "1616.03.03")
        text = re.sub(
            r'\b(\d{4})\.(\d{2})\.00(\d{2})\b',
            r'\1.\2.\3',
            text
        )
        
        # NEU: Korrigiere "p. 21..5." → "p. 21. Nr. 5"
        text = re.sub(
            r'(p\.\s*\d+)\.\.(\d+)\.',
            r'\1. Nr. \2',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: Unvollständige Datumsangaben mit nur Monat (z.B. "1615.04." → "1615.04.00")
        text = re.sub(
            r'\b(\d{4})\.(\d{2})\.\s',
            r'\1.\2.00 ',
            text
        )
        
        # NEU: Korrigiere "78.412" → "p. 112" (OCR verwechselt p mit 78)
        text = re.sub(
            r'\b78\.(\d{2,3})\b',
            r'p. 1\1',
            text
        )
        
        # NEU: Korrigiere "10.105", "13.104", "12.103" → "p. 105", "p. 104", "p. 103"
        text = re.sub(
            r'\b1[0-9]\.(\d{3})\b',
            r'p. \1',
            text
        )
        
        # NEU: Korrigiere "p. 23 Mat" → "p. 23" (entferne "Mat", "Lev", etc.)
        text = re.sub(
            r'(p\.\s*\d+)\s+[A-Z][a-z]{1,3}\s+(Lev\.|ev\.)',
            r'\1 \2',
            text
        )
        
        # NEU: Korrigiere "Nr..4", "Nr.3", "Nx.4", "Mh.1", "th.9" → "Nr. X"
        text = re.sub(
            r'\b[NMT][xrh]h?\.\.?(\d+)',  # GEÄNDERT: h? macht 'h' optional
            r'Nr. \1',
            text,
            flags=re.IGNORECASE
        )
        
        # NEU: Korrigiere "0015.64.11.21" → "∞ 1564.11.21"
        # Pattern 0a: OCR-Fehler "00" statt "∞" (z.B. "1564 002" → "1564 ∞ 2")
        text = re.sub(
            r'(\d{4})\s+00(\d)\b',
            r'\1 ∞ \2',
            text
        )
        
        # Pattern 0b: OCR-Fehler "0" statt "∞" (z.B. "1564 02" → "1564 ∞ 2")
        text = re.sub(
            r'(\d{4})\s+0(\d)\b',
            r'\1 ∞ \2',
            text
        )
        
        # Pattern 1: Jahr-Korrektur für 1500-1599 (0015.64.11.21 → ∞ 1564.11.21)
        # Sucht nach 00XX.YY.MM.DD am Anfang (nach Wetzlar)
        text = re.sub(
            r'(ev\.\s*Kb\.\s*Wetzlar)\s+00(\d{2})\.(\d{2}\.\d{2}\.\d{2})',
            r'\1 ∞ 15\2.\3',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 1a: NEU - Jahr-Korrektur für 1600-1699 (0016.11.01. → ∞ 1611.11.01)
        # AUCH MIT PUNKT: 0016.11.01. wird zu ∞ 1611.11.01
        text = re.sub(
            r'(ev\.\s*Kb\.\s*Wetzlar)\s+00(1[0-9])\.(\d{2}\.\d{2})\.?',  # GEÄNDERT: \.? am Ende
            r'\1 ∞ 16\2.\3',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 1b: Jahr ohne Punkt für 1500-1599 (001564.11.27 → ∞ 1564.11.27)
        # OCR erkennt ∞ 1564 als "001564" (6 Ziffern zusammen)
        text = re.sub(
            r'(ev\.\s*Kb\.\s*Wetzlar)\s+00(15\d{2})\.(\d{2}\.\d{2})',
            r'\1 ∞ \2.\3',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 1b2: NEU - Jahr ohne Punkt für 1600-1699 (001611.01.01 → ∞ 1611.01.01)
        text = re.sub(
            r'(ev\.\s*Kb\.\s*Wetzlar)\s+00(16\d{2})\.(\d{2}\.\d{2})',
            r'\1 ∞ \2.\3',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 1c: Alternative OCR-Fehler (0156.04.11.26 → ∞ 1564.11.26)
        # Hier wird ∞ 1564 als "01" + "5" + "6" + ".0" + "4" erkannt
        text = re.sub(
            r'(ev\.\s*Kb\.\s*Wetzlar)\s+01(\d)(\d)\.0(\d)\.(\d{2}\.\d{2})',
            r'\1 ∞ 1\2\3\4.\5',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 1d: NEU - Füge ∞ ein wenn Jahreszahl direkt nach Wetzlar (ohne 00 Präfix)
        # Erweitert um 1600-1699: "ev. Kb. Wetzlar 1611.01.01" → "ev. Kb. Wetzlar ∞ 1611.01.01"
        text = re.sub(
            r'(ev\.\s*Kb\.\s*Wetzlar)\s+(1[456]\d{2}\.\d{2}\.\d{2})',
            r'\1 ∞ \2',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 2: Seiten-Korrektur (p.87./. → p. 87.)
        # Entfernt ./. nach der Seitenzahl
        text = re.sub(
            r'p\.(\d+)\.\s*/\s*\.',
            r'p. \1.',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 3: Leerzeichen nach p. hinzufügen falls fehlend
        text = re.sub(
            r'p\.(\d)',
            r'p. \1',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 4: Nummern-Korrektur (p. 87.2. → p. 87. Nr. 2, M. 4 → Nr. 4)
        # Sucht nach p. XX.Y. oder p.XX./.Y Muster
        text = re.sub(
            r'(p\.\s*\d+)\.(\d+)\.?',
            r'\1. Nr. \2',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 4a: NEU - Doppelpunkt-Korrektur (Nr..4 → Nr. 4)
        text = re.sub(
            r'Nr\.\.(\d+)',
            r'Nr. \1',
            text,
            flags=re.IGNORECASE
        )
        
        # Pattern 5: M. / ML. → Nr. (z.B. "M. 4" → "Nr. 4", "ML.15" → "Nr. 15")
        text = re.sub(
            r'\bML?\.\s*(\d+)',
            r'Nr. \1',
            text,
            flags=re.IGNORECASE
        )
        
        return text
    
    def _apply_vocabulary_corrections(self, text: str) -> str:
        """
        Wendet wörterbuch-basierte Korrekturen an.
        Korrigiert häufige Fehler bei wiederkehrenden Begriffen.
        """
        # Durchlaufe alle korrekten Wörter im Wörterbuch
        for correct_word, variants in self.kirchenbuch_vocabulary.items():
            # Prüfe jede Variante (fehlerhafte Schreibweise)
            for variant in variants:
                if variant != correct_word:  # Nur Fehler korrigieren
                    # Case-insensitive Ersetzung mit Wortgrenzen
                    # \b stellt sicher, dass nur ganze Wörter ersetzt werden
                    pattern = r'\b' + re.escape(variant) + r'\b'
                    text = re.sub(pattern, correct_word, text, flags=re.IGNORECASE)
        
        return text
    
    def _normalize_dates(self, text: str) -> str:
        """Normalisiert Datumsangaben."""
        def fix_date(match):
            year, month, day = match.groups()
            # Stelle sicher, dass Monat und Tag zweistellig sind
            month = month.zfill(2)
            day = day.zfill(2)
            return f"{year}.{month}.{day}"
        
        return self.patterns['date'].sub(fix_date, text)
    
    def _normalize_numbers(self, text: str) -> str:
        """Normalisiert Nummernangaben."""
        return self.patterns['number'].sub(r'Nr. \1', text)
    
    def _remove_unlikely_chars(self, text: str) -> str:
        """Entfernt unwahrscheinliche Sonderzeichen."""
        # Behalte nur deutsche Buchstaben, Zahlen, Leerzeichen und gängige Satzzeichen
        text = re.sub(r'[^\w\säöüÄÖÜß.,;:!?()\-/\']', '', text)
        return text
    
    def _fix_word_patterns(self, text: str) -> str:
        """Korrigiert bekannte Wortmuster in Kirchenbüchern."""
        # Typische Kirchenbuch-Begriffe
        replacements = {
            r'\bev\s*Kb\b': 'ev. Kb.',
            r'\bKirchenbuchkartei\b': 'Kirchenbuchkartei',
            r'\bWetzlar\b': 'Wetzlar',
        }
        
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        return text
    
    def add_custom_correction(self, error: str, correction: str):
        """
        Fügt eine benutzerdefinierte Korrektur hinzu.
        
        Args:
            error: Der fehlerhafte Text
            correction: Die Korrektur
        """
        self.common_ocr_errors[error] = correction
    
    def add_vocabulary_word(self, correct_word: str, variants: list):
        """
        Fügt ein neues Wort mit seinen Varianten zum Wörterbuch hinzu.
        
        Args:
            correct_word: Die korrekte Schreibweise
            variants: Liste der fehlerhaften Varianten
        """
        self.kirchenbuch_vocabulary[correct_word] = variants
    
    def get_corrections_dict(self) -> Dict[str, str]:
        """Gibt das aktuelle Korrektur-Dictionary zurück."""
        return self.common_ocr_errors.copy()
    
    def get_vocabulary(self) -> Dict[str, list]:
        """Gibt das aktuelle Wörterbuch zurück."""
        return self.kirchenbuch_vocabulary.copy()
