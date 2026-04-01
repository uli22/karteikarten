"""Extraktions-Logik für Kirchenbuch-Einträge (Heirat und Begräbnis).

Diese Funktionen sind GUI-unabhängig und können direkt aufgerufen werden.
"""

import re
from typing import Optional

from .extraction_lists import (ANREDEN, ARTIKEL, BERUFE, BERUFS_EINLEITUNG,
                               IGNORIERE_WOERTER, KEINE_BERUFE,
                               MAENNLICHE_VORNAMEN, ORTS_PRAEPOSITIONEN,
                               PARTNER_STÄNDE, STAND_MAPPING, STAND_PRAEFIXE,
                               STAND_SYNONYME, WEIBLICHE_VORNAMEN)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def name_token_key(token: str) -> str:
    """Normalisiert ein Namens-Token für robuste Vergleiche."""
    cleaned = re.sub(r"[^A-Za-zÄÖÜäöüßẞ]", "", str(token or ""))
    return cleaned.replace('ẞ', 'ß').lower()


def expand_abbreviated_first_names(value: Optional[str], gender: str = 'unknown') -> Optional[str]:
    """Ersetzt erkannte Vornamen-Kurzformen durch Vollformen (z.B. Joh -> Johann/Johannes, Elis -> Elisabeth)."""
    if not value:
        return value

    male_abbrev = {
        'andr': 'Andreas',
        'balt': 'Balthasar',
        'christ': 'Christian',
        'conr': 'Conrad',
        'eberh': 'Eberhard',
        'frid': 'Friedrich',
        'fried': 'Friedrich',
        'geo': 'Georg',
        'heinr': 'Heinrich',
        'henr': 'Henrich',
        'mart': 'Martin',
        'matth': 'Matthias',
        'nic': 'Nicolas',
        'pet': 'Peter',
        'petr': 'Peter',
        'phil': 'Philipp',
        'seb': 'Sebastian',
        'theoph': 'Theophil',
        'wilh': 'Wilhelm',
    }
    female_abbrev = {
        'appol': 'Appolonia',
        'barb': 'Barbara',
        'cath': 'Catharina',
        'dor': 'Dorothea',
        'elis': 'Elisabeth',
        'gertr': 'Gertraut',
        'jul': 'Juliana',
        'kath': 'Katharina',
        'marg': 'Margaretha',
        'reg': 'Regina',
        'sus': 'Susanna',
    }

    male_keys = {name_token_key(v) for v in MAENNLICHE_VORNAMEN if name_token_key(v)}

    def is_male_token(token: str) -> bool:
        key = name_token_key(token)
        return key in male_keys or key in male_abbrev or key == 'joh'

    tokens = [t for t in str(value).split() if t]
    expanded_tokens = []

    for idx, token in enumerate(tokens):
        key = name_token_key(token)
        expanded = None

        if gender in ('male', 'unknown'):
            if key == 'joh':
                has_following_male_name = idx + 1 < len(tokens) and is_male_token(tokens[idx + 1])
                expanded = 'Johann' if has_following_male_name else 'Johannes'
            elif key in male_abbrev:
                expanded = male_abbrev[key]

        if expanded is None and gender in ('female', 'unknown'):
            if key in female_abbrev:
                expanded = female_abbrev[key]

        expanded_tokens.append(expanded if expanded is not None else token.rstrip(',.;:'))

    return ' '.join(expanded_tokens)


def extract_kirchenbuch_titel(dateiname: str) -> str:
    """Extrahiert "Hb 1695-1718" aus Dateinamen wie "3282 Hb 1717 - 1695-1718 - F....jpg"."""
    if not dateiname:
        return ''
    match = re.search(r"\b([A-Z][a-z])\s+\d{4}\s+-\s*(\d{4}-\d{4})", str(dateiname))
    if not match:
        return ''
    return f"{match.group(1)} {match.group(2)}"


def is_valid_date(datum: str, jahr: Optional[int]) -> bool:
    """
    Prüft ob ein Datum gültig ist (Jahr zwischen 1500 und 1754).

    Args:
        datum: Datumsstring (z.B. "20.11.1564" oder "00.03.1616")
        jahr: Extrahiertes Jahr aus der Datenbank

    Returns:
        True wenn gültig, False wenn ungültig
    """
    if not datum:
        return True  # Leeres Datum ist "gültig" (keine Fehlermeldung)

    # Prüfe ob Jahr im gültigen Bereich (1500-1754)
    if jahr is not None:
        if jahr < 1500 or jahr > 1754:
            return False

    match = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', datum)
    if not match:
        return False  # Ungültiges Format

    tag_str, monat_str, jahr_str = match.groups()

    try:
        tag = int(tag_str)
        monat = int(monat_str)
        jahr_aus_datum = int(jahr_str)

        if jahr_aus_datum < 1500 or jahr_aus_datum > 1754:
            return False
        if monat < 0 or monat > 12:
            return False
        if tag != 0 and (tag < 1 or tag > 31):
            return False

        return True

    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Haupt-Extraktionsfunktionen
# ---------------------------------------------------------------------------

def extract_marriage_fields(text: str) -> dict:
    """
    Extrahiert Felder aus einem Heiratseintrag.

    Struktur:
    1. Zitation: ev. Kb. Wetzlar ∞ YYYY.MM.DD p. X Nr. Y
    2. Bräutigam: [Vorname] [Nachname] [Vater-Vorname] [Vater-Nachname]s, [Beruf des Vaters], [Ort], [Status]
    3. Trenner: "und", "undt", "mitt"
    4. Braut: [Anrede] [Vorname(n)], [Vater-Vorname] [Vater-Nachname]s [Beruf], [Ort], [Status]
    5. Ende: "hielten Hochzeit", "copulirt", etc.

    Returns:
        Dict mit extrahierten Feldern
    """
    result = {
        'vorname': None,
        'nachname': None,
        'partner': None,
        'beruf': None,
        'ort': None,
        'stand': None,
        'braeutigam_stand': None,
        'braeutigam_vater': None,
        'braut_vater': None,
        'braut_nachname': None,
        'braut_ort': None,
        'todestag': None,
        'seite': None,
        'nummer': None,
    }

    zitation_pattern = r"^\s*(ev\.?\s*Kb\.?\s*Wetzlar)\s*([⚰∞\u26B0])\s*(\d{4})[\.\s]*(\d{1,2})[\.\s]*(\d{1,2})\.?\s*[Pp]\.?\s*(\d+)\.?\s*,?\s*Nr\.?\s*(\d+)\.?\s*"

    print(f"DEBUG Heirat: Eingabe-Text = {repr(text[:150])}")
    m = re.match(zitation_pattern, text, re.IGNORECASE)
    if m:
        after_zitation = text[m.end():].strip()
        jahr = m.group(3)
        monat = m.group(4).zfill(2)
        tag = m.group(5).zfill(2)
        result['todestag'] = f"{jahr}.{monat}.{tag}"
        if m.group(6):
            result['seite'] = int(m.group(6))
        if m.group(7):
            result['nummer'] = int(m.group(7))
        print(f"DEBUG Heirat: Zitation erkannt bis Position {m.end()}")
        print(f"DEBUG Heirat: Hochzeitsdatum (in todestag) = {result['todestag']}")
        print(f"DEBUG Heirat: Seite = {result.get('seite')}, Nummer = {result.get('nummer')}")
        print(f"DEBUG Heirat: Text nach Zitation: {repr(after_zitation[:100])}")
    else:
        after_zitation = text.strip()
        print(f"DEBUG Heirat: WARNUNG - Keine Zitation erkannt, verwende vollen Text")

    relevant_text = after_zitation
    print(f"DEBUG Heirat: relevant_text = {repr(relevant_text[:200])}")

    text_clean = relevant_text
    for char in '.,;:!?()[]{}"\'-+':
        text_clean = text_clean.replace(char, ' ')

    words = [w.strip() for w in text_clean.split() if w.strip()]

    zitation_woerter = ['ev', 'Kb', 'kb', 'Wetzlar', 'p', 'Nr', 'nr', '∞']
    words = [w for w in words if w not in zitation_woerter and w.lower() not in [z.lower() for z in zitation_woerter]]

    while words and words[0].isdigit():
        print(f"DEBUG Heirat: Filtere Zitations-Zahl am Anfang: {words[0]}")
        words = words[1:]

    copul_idx = next((i for i, w in enumerate(words) if w.lower().startswith('copul')), None)
    if copul_idx is not None:
        print(f"DEBUG Heirat: 'copul*' bei Position {copul_idx} ('{words[copul_idx]}') - trunkiere words")
        words = words[:copul_idx]

    print(f"DEBUG Heirat: words (nach Filter) = {words[:30]}")

    def remove_genitiv_s(name):
        if not name or len(name) <= 2:
            return name
        if name.endswith('en') and len(name) > 3:
            return name[:-2]
        elif name.endswith('es') and len(name) > 3:
            return name[:-2]
        elif name.endswith('s'):
            if name[-2] not in 'aeiouäöü':
                return name[:-1]
        return name

    weibliche_vornamen = WEIBLICHE_VORNAMEN
    maennliche_vornamen = MAENNLICHE_VORNAMEN
    anreden = ANREDEN
    ignoriere_woerter = IGNORIERE_WOERTER

    def norm_name_token(token: str) -> str:
        return str(token).strip().replace('ẞ', 'ß').lower()

    maennliche_vornamen_norm = {norm_name_token(v) for v in maennliche_vornamen}

    ignore_extended = set(ignoriere_woerter) | {
        'gewesener', 'gewesenen', 'gewesene',
        'hinterlassener', 'hinterlassenen', 'hinterlassene', 'hinterl',
        'ehel', 'ehelicher', 'ehelichen', 'eheliche',
        'hielten', 'hilten', 'hilt', 'hochzeit'
    }

    trenner_pos = -1
    trenner_woerter = ['und', 'undt', 'mitt', 'mit', 'cum']

    braut_start_keywords = ['jungfr', 'jungfrau', 'jfr'] + [v.lower() for v in weibliche_vornamen]
    braut_indicator_pos = -1

    for i, w in enumerate(words):
        if w.lower() in braut_start_keywords:
            braut_indicator_pos = i
            print(f"DEBUG Heirat: Braut-Indikator '{w}' gefunden bei Position {i}")
            break

    if braut_indicator_pos > 0:
        prev_word = words[braut_indicator_pos - 1].lower()
        if prev_word in ['mit', 'mitt', 'cum']:
            trenner_pos = braut_indicator_pos - 1
            print(
                f"DEBUG Heirat: Spezial-Trenner '{words[trenner_pos]} {words[braut_indicator_pos]}' "
                f"gefunden bei Position {trenner_pos}"
            )

    if braut_indicator_pos != -1 and trenner_pos == -1:
        for i in range(braut_indicator_pos - 1, -1, -1):
            if words[i].lower() in trenner_woerter:
                trenner_pos = i
                print(f"DEBUG Heirat: Trenner '{words[i]}' gefunden bei Position {i} (vor Braut-Indikator)")
                break

    if trenner_pos == -1:
        for i, w in enumerate(words):
            if w.lower() in trenner_woerter:
                trenner_pos = i
                print(f"DEBUG Heirat: Trenner '{w}' gefunden bei Position {i} (Fallback)")
                break

    if trenner_pos == -1 and braut_indicator_pos != -1:
        for i in range(braut_indicator_pos - 1, -1, -1):
            if words[i].lower() in ['son', 'sohn', 'stiffson']:
                if i + 1 < len(words) and words[i + 1].lower() in braut_start_keywords:
                    trenner_pos = i + 1
                    print(f"DEBUG Heirat: Impliziter Trenner nach '{words[i]}' bei Position {i+1}")
                    break

    if trenner_pos == -1 and braut_indicator_pos != -1:
        trenner_pos = braut_indicator_pos
        print(f"DEBUG Heirat: Kein Trenner-Wort gefunden, trenne vor Braut-Indikator bei Position {braut_indicator_pos}")

    if trenner_pos == -1:
        print("DEBUG Heirat: KEIN Trenner gefunden und kein Braut-Indikator!")
        return result

    brautigam_words = words[:trenner_pos]
    print(f"DEBUG Heirat: brautigam_words = {brautigam_words}")

    if trenner_pos < len(words) and words[trenner_pos].lower() in trenner_woerter:
        braut_words = words[trenner_pos + 1:]
    else:
        braut_words = words[trenner_pos:]
    print(f"DEBUG Heirat: braut_words = {braut_words}")

    # === Bräutigam: Beruf-Vorer-kennung ===
    beruf_word_indices = set()
    brautigam_text = ' '.join(brautigam_words)
    for beruf_kandidat in BERUFE:
        if beruf_kandidat in brautigam_text:
            result['beruf'] = beruf_kandidat
            beruf_woerter = beruf_kandidat.split()
            for i in range(len(brautigam_words) - len(beruf_woerter) + 1):
                if ' '.join(brautigam_words[i:i+len(beruf_woerter)]) == beruf_kandidat:
                    beruf_word_indices = set(range(i, i + len(beruf_woerter)))
                    print(f"DEBUG Heirat: Beruf = {result['beruf']} bei Indizes {list(beruf_word_indices)}")
                    break
            break

    idx = 0
    while idx < len(brautigam_words) and (brautigam_words[idx].lower() in anreden or brautigam_words[idx] in ignore_extended):
        idx += 1

    vorname_parts = []
    while idx < len(brautigam_words) and brautigam_words[idx] in maennliche_vornamen:
        vorname_parts.append(brautigam_words[idx])
        idx += 1

    if not vorname_parts and idx < len(brautigam_words):
        vorname_parts.append(brautigam_words[idx])
        idx += 1

    if vorname_parts:
        result['vorname'] = ' '.join(vorname_parts)
        print(f"DEBUG Heirat: Bräutigam Vorname = {result['vorname']}")

    while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
        idx += 1

    if idx < len(brautigam_words):
        word_next = brautigam_words[idx]
        brautigam_stand_woerter = ['sohn', 'söhnlein', 'sohnlein', 'son', 'wittwer', 'wittiber', 'witwer']

        if word_next in maennliche_vornamen:
            result['braeutigam_vater'] = word_next
            print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
            idx += 1
            while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                idx += 1
            if idx < len(brautigam_words):
                result['nachname'] = remove_genitiv_s(brautigam_words[idx])
                print(f"DEBUG Heirat: Bräutigam Nachname (von Vater) = {result['nachname']}")
                idx += 1
        else:
            stand_found = any(w.lower() in brautigam_stand_woerter for w in brautigam_words[idx:])

            if beruf_word_indices:
                result['nachname'] = word_next
                print(f"DEBUG Heirat: Bräutigam Nachname = {result['nachname']} (Beruf bereits erkannt)")
                idx += 1
            elif stand_found:
                result['nachname'] = word_next
                print(f"DEBUG Heirat: Bräutigam Nachname (eigen) = {result['nachname']}")
                idx += 1
                while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                    idx += 1
                if idx < len(brautigam_words):
                    result['braeutigam_vater'] = brautigam_words[idx]
                    print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                    idx += 1
                    while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                        idx += 1
                    if idx < len(brautigam_words):
                        vater_nachname_genitiv = brautigam_words[idx]
                        print(f"DEBUG Heirat: Vater-Nachname (Genitiv) = {vater_nachname_genitiv}")
                        idx += 1
            else:
                idx_peek = idx + 1
                while idx_peek < len(brautigam_words) and brautigam_words[idx_peek] in ignore_extended:
                    idx_peek += 1

                if idx_peek < len(brautigam_words):
                    word_after = brautigam_words[idx_peek]
                    idx_peek2 = idx_peek + 1
                    while idx_peek2 < len(brautigam_words) and brautigam_words[idx_peek2] in ignore_extended:
                        idx_peek2 += 1
                    word_after2 = brautigam_words[idx_peek2] if idx_peek2 < len(brautigam_words) else None

                    if word_after2 and word_after2.endswith('s') and len(word_after2) > 2:
                        result['nachname'] = word_next
                        result['braeutigam_vater'] = word_after
                        result['nachname'] = remove_genitiv_s(word_after2)
                        print(f"DEBUG Heirat: Bräutigam Nachname korrigiert = {result['nachname']}")
                        print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                        idx = idx_peek2 + 1
                    elif word_after in maennliche_vornamen:
                        result['nachname'] = word_next
                        print(f"DEBUG Heirat: Bräutigam Nachname = {result['nachname']}")
                        idx = idx_peek + 1
                        result['braeutigam_vater'] = word_after
                        print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                        while idx < len(brautigam_words) and brautigam_words[idx] in ignore_extended:
                            idx += 1
                        if idx < len(brautigam_words):
                            result['nachname'] = remove_genitiv_s(brautigam_words[idx])
                            print(f"DEBUG Heirat: Bräutigam Nachname korrigiert (von Vater) = {result['nachname']}")
                            idx += 1
                    elif word_after.endswith('s') and len(word_after) > 2:
                        result['braeutigam_vater'] = word_next
                        result['nachname'] = remove_genitiv_s(word_after)
                        print(f"DEBUG Heirat: Bräutigam Vater = {result['braeutigam_vater']}")
                        print(f"DEBUG Heirat: Bräutigam Nachname (von Vater) = {result['nachname']}")
                        idx = idx_peek + 1
                    else:
                        result['nachname'] = word_next
                        print(f"DEBUG Heirat: Bräutigam Nachname (Fallback) = {result['nachname']}")
                        idx += 1
                else:
                    result['nachname'] = word_next
                    print(f"DEBUG Heirat: Bräutigam Nachname (nur 1 Wort) = {result['nachname']}")
                    idx += 1

    for i, w in enumerate(brautigam_words):
        if w.lower() == 'bürger' and not result['beruf']:
            result['beruf'] = 'Bürger'
            print(f"DEBUG Heirat: Beruf = Bürger")
            break

    for i, w in enumerate(brautigam_words):
        if w.lower() in ['alhier', 'alhie']:
            result['ort'] = 'Wetzlar'
            print(f"DEBUG Heirat: Bräutigam Ort ({w}) = Wetzlar")
            if i >= 2 and brautigam_words[i-2].lower() == 'bürger':
                potential_beruf = brautigam_words[i-1]
                if potential_beruf in BERUFE or potential_beruf[0].isupper():
                    result['beruf'] = potential_beruf
                    print(f"DEBUG Heirat: Beruf (vor alhier) = {result['beruf']}")
            elif i >= 1:
                if brautigam_words[i-1].lower() != 'bürger':
                    potential_beruf = brautigam_words[i-1]
                    if potential_beruf in BERUFE:
                        result['beruf'] = potential_beruf
                        print(f"DEBUG Heirat: Beruf (vor alhier, ohne Bürger) = {result['beruf']}")
            break

    if not result['ort']:
        for i, w in enumerate(brautigam_words):
            if w.lower() in ['zu', 'von', 'in'] and i + 1 < len(brautigam_words):
                next_word = brautigam_words[i + 1]
                if w.lower() == 'in' and next_word.lower() == 'domo':
                    continue
                result['ort'] = next_word
                print(f"DEBUG Heirat: Bräutigam Ort ({w}) = {result['ort']}")
                break

    for word in brautigam_words:
        word_lower = word.lower()
        if word_lower in STAND_MAPPING:
            result['braeutigam_stand'] = STAND_MAPPING[word_lower]
            print(f"DEBUG Heirat: Bräutigam Stand = {result['braeutigam_stand']} (gefunden: '{word}')")
            break

    if not result.get('braeutigam_stand'):
        brautigam_text_lower = ' '.join(brautigam_words).lower()
        braeutigam_stand_patterns = [
            ('wittwer', 'Wittwer'), ('wittiber', 'Wittwer'), ('witwer', 'Wittwer'),
            ('sohn', 'Sohn'), ('son', 'Sohn'),
        ]
        for pattern, normalized in braeutigam_stand_patterns:
            if pattern in brautigam_text_lower:
                result['braeutigam_stand'] = normalized
                print(f"DEBUG Heirat: Bräutigam Stand = {result['braeutigam_stand']} (Fallback)")
                break

    # === Braut-Teil analysieren ===
    idx = 0
    _anreden_lower = {a.lower() for a in anreden}
    while idx < len(braut_words) and (
        braut_words[idx].lower() in _anreden_lower or
        braut_words[idx].lower().startswith('jung') or
        braut_words[idx].lower() in ['jfr'] or
        braut_words[idx] in ignore_extended
    ):
        idx += 1

    partner_parts = []
    _weibliche_lower = {v.lower() for v in weibliche_vornamen}
    while idx < len(braut_words):
        word = braut_words[idx]
        if word.isdigit():
            break
        if word in ignore_extended:
            idx += 1
            continue
        if norm_name_token(word) in maennliche_vornamen_norm:
            break
        if (partner_parts
                and word.lower().endswith('in')
                and len(word) > 3
                and word not in weibliche_vornamen
                and word.lower() not in _weibliche_lower):
            result['braut_nachname'] = word
            print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} ('-in'-Endung erkannt)")
            idx += 1
            break

        has_genitiv_ending = (
            (word.endswith('en') and len(word) > 3) or
            (word.endswith('es') and len(word) > 3) or
            (word.endswith('s') and len(word) > 2)
        ) and word not in weibliche_vornamen

        if has_genitiv_ending:
            next_idx = idx + 1
            while next_idx < len(braut_words) and braut_words[next_idx] in ignore_extended:
                next_idx += 1
            if next_idx < len(braut_words):
                break

        partner_parts.append(word)
        idx += 1

    if partner_parts:
        partner_name = ' '.join(partner_parts).rstrip(',.;:')
        partner_words = partner_name.split()
        if (not result.get('braut_nachname')
                and len(partner_words) > 1
                and partner_words[-1] not in weibliche_vornamen
                and not partner_words[-1].isdigit()):
            result['braut_nachname'] = partner_words[-1]
            result['partner'] = ' '.join(partner_words[:-1])
            print(f"DEBUG Heirat: Braut Vorname = {result['partner']}")
            print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (aus Partner extrahiert)")
        else:
            result['partner'] = partner_name
            print(f"DEBUG Heirat: Braut Vorname = {result['partner']}")

    while idx < len(braut_words) and (
        braut_words[idx] in ignore_extended or
        braut_words[idx].lower() in _anreden_lower
    ):
        idx += 1

    if idx < len(braut_words):
        current_word = braut_words[idx]

        if norm_name_token(current_word) in maennliche_vornamen_norm:
            vater_vorname_parts = []
            while idx < len(braut_words) and norm_name_token(braut_words[idx]) in maennliche_vornamen_norm:
                vater_vorname_parts.append(braut_words[idx])
                idx += 1
            if vater_vorname_parts:
                result['braut_vater'] = ' '.join(vater_vorname_parts)
                print(f"DEBUG Heirat: Braut Vater = {result['braut_vater']}")
            while idx < len(braut_words) and braut_words[idx] in ignore_extended:
                idx += 1
            if idx < len(braut_words):
                vater_nn = remove_genitiv_s(braut_words[idx])
                if not result.get('braut_nachname'):
                    result['braut_nachname'] = vater_nn
                    print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (von Vater)")
                idx += 1
        else:
            idx_peek = idx + 1
            while idx_peek < len(braut_words) and braut_words[idx_peek] in ignore_extended:
                idx_peek += 1
            next_word = braut_words[idx_peek] if idx_peek < len(braut_words) else None

            def _has_gen(w):
                return ((w.endswith('en') and len(w) > 3) or
                        (w.endswith('es') and len(w) > 3) or
                        (w.endswith('s') and len(w) > 2))

            if next_word and _has_gen(current_word) and _has_gen(next_word):
                if not result['braut_nachname']:
                    result['braut_nachname'] = remove_genitiv_s(current_word)
                    print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (Ehemann, Witwe)")
                result['braut_vater'] = remove_genitiv_s(next_word)
                print(f"DEBUG Heirat: Braut Vater = {result['braut_vater']} (nur Nachname)")
                idx = idx_peek + 1
            else:
                if not current_word.isdigit():
                    if not result.get('braut_nachname'):
                        result['braut_nachname'] = remove_genitiv_s(current_word)
                        print(f"DEBUG Heirat: Braut Nachname = {result['braut_nachname']} (von Vater, kein Vorname)")
                idx += 1

    for i in range(len(braut_words) - 1):
        if braut_words[i].lower() in ['zu', 'von', 'in']:
            next_word = braut_words[i + 1]
            if braut_words[i].lower() == 'in' and next_word.lower() == 'domo':
                continue
            result['braut_ort'] = next_word
            print(f"DEBUG Heirat: Braut Ort = {result['braut_ort']}")
            break

    if not result['braut_ort']:
        for i, w in enumerate(braut_words):
            if w.lower() in ['alhier', 'alhie']:
                result['braut_ort'] = 'Wetzlar'
                print(f"DEBUG Heirat: Braut Ort ({w}) = Wetzlar")
                break

    braut_text_lower = ' '.join(braut_words).lower()
    braut_text_lower = re.sub(r'\bhinterl\b', 'hinterlassene', braut_text_lower)
    for stand_key in sorted(STAND_MAPPING.keys(), key=len, reverse=True):
        if stand_key in braut_text_lower:
            result['stand'] = STAND_MAPPING[stand_key]
            print(f"DEBUG Heirat: Stand = {result['stand']} (gefunden: '{stand_key}')")
            break

    result['vorname'] = expand_abbreviated_first_names(result.get('vorname'), gender='male')
    result['partner'] = expand_abbreviated_first_names(result.get('partner'), gender='female')
    result['braeutigam_vater'] = expand_abbreviated_first_names(result.get('braeutigam_vater'), gender='male')
    result['braut_vater'] = expand_abbreviated_first_names(result.get('braut_vater'), gender='male')

    return result


def extract_burial_fields(text: str) -> dict:
    """
    Zentrale Funktion zur Extraktion von Feldern aus einem Begräbnis-Eintrag.

    Diese Funktion wird von beiden Tabs (OCR-Tab und Datenbank-Tab) verwendet,
    um eine konsistente Erkennung zu gewährleisten.

    Args:
        text: Der zu analysierende Text (nach Zitation)

    Returns:
        Dict mit extrahierten Feldern: vorname, nachname, partner, beruf, stand, todestag, ort, geb_jahr_gesch
    """
    result = {
        'vorname': None,
        'nachname': None,
        'partner': None,
        'beruf': None,
        'stand': None,
        'todestag': None,
        'ort': None,
        'geb_jahr_gesch': None,
        'seite': None,
        'nummer': None
    }

    zitation_pattern = r"^(ev\.\s*Kb\.\s*Wetzlar)?[ .]*[⚰\u26B0]?[ .]*(\d{4}[ .]?\d{2}[ .]?\d{2})[ .]*p\.?[ .]?(\d+)[ .]*(Nr\.?|No\.?)[ .]?(\d+)[ .]*"
    stopwords = ["Text", "Tex", "Tex.", "begraben", "begr.", "begr ", "Begr.", "Begr "]

    stop_idx = len(text)
    for sw in stopwords:
        idx = text.lower().find(sw.lower())
        if idx != -1 and idx < stop_idx:
            stop_idx = idx
    zitation_text = text[:stop_idx]

    m = re.match(zitation_pattern, zitation_text)

    if m:
        after_zitation = zitation_text[m.end():].strip()
        result['todestag'] = m.group(2).replace(" ", ".").replace(".", ".")
        if m.group(3):
            result['seite'] = int(m.group(3))
        if m.group(5):
            result['nummer'] = int(m.group(5))
    else:
        after_zitation = zitation_text.strip()

    bereinigte_zeile = re.sub(r"[,;.!?]", " ", after_zitation)
    words = re.split(r"\s+", bereinigte_zeile)
    words = [w for w in words if w]

    words_original_case = words.copy()
    words = [w[0].upper() + w[1:] if len(w) > 0 else w for w in words]

    if not words:
        return result

    weibliche_vornamen = WEIBLICHE_VORNAMEN
    maennliche_vornamen = MAENNLICHE_VORNAMEN
    stand_synonyme = STAND_SYNONYME
    ort_prae = ORTS_PRAEPOSITIONEN
    beruf_einleitung = BERUFS_EINLEITUNG
    anreden = ANREDEN
    ignoriere_woerter = IGNORIERE_WOERTER

    def ist_frau_anrede(idx_aktuell):
        if idx_aktuell >= len(words) or words[idx_aktuell].lower() != "frau":
            return False
        if idx_aktuell + 1 < len(words):
            next_word = words[idx_aktuell + 1]
            if next_word in weibliche_vornamen or next_word in maennliche_vornamen:
                return True
            if next_word.lower() not in stand_synonyme:
                return True
        return False

    def entferne_genitiv(wort):
        if wort in maennliche_vornamen or wort in weibliche_vornamen:
            return wort
        if len(wort) <= 3 and wort.endswith('s'):
            return wort
        if wort.endswith(('tri', 'pri', 'ri')) and len(wort) > 3:
            return wort
        if wort.endswith(('chen', 'lein')):
            return wort
        if wort.endswith('ss') and len(wort) > 4:
            return wort[:-1]
        if wort.endswith('is'):
            return wort[:-2]
        elif wort.endswith('ii'):
            return wort[:-1]
        elif wort.endswith('i') and len(wort) > 2:
            return wort[:-1]
        elif wort.endswith('en') and len(wort) > 3:
            return wort[:-2]
        elif wort.endswith('s') and len(wort) > 2:
            return wort[:-1]
        return wort

    idx = 0
    vorname_start_idx = -1
    vorname = None
    nachname = None
    partner = None
    beruf = None
    ist_weiblich = False
    stand = None
    ort = None

    while idx < len(words):
        w = words[idx]
        if w in weibliche_vornamen or w in maennliche_vornamen:
            vorname_start_idx = idx
            vorname = w
            ist_weiblich = w in weibliche_vornamen
            idx += 1
            while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                idx += 1
            break
        idx += 1

    if not vorname:
        idx = 0

    if vorname and vorname_start_idx > 0:
        if words[0].lower() not in ignoriere_woerter and words[0].lower() not in anreden:
            nachname = words[0]

    if not vorname and not nachname and len(words) >= 2:
        weibliche_stand_marker = {"witwe", "wittib", "wittwe", "witbe", "widwe", "hausfrau", "haußfrau"}
        has_weiblicher_stand = any(w.lower() in weibliche_stand_marker for w in words)

        if not has_weiblicher_stand:
            first_word = words[0]
            second_word = words[1]

            if (
                first_word.lower() not in ignoriere_woerter and
                first_word.lower() not in anreden and
                first_word.lower() not in stand_synonyme and
                first_word.lower() not in ort_prae and
                not first_word.isdigit() and
                second_word.lower() not in ignoriere_woerter and
                second_word.lower() not in anreden and
                second_word.lower() not in stand_synonyme and
                second_word.lower() not in ort_prae and
                not second_word.isdigit()
            ):
                vorname = first_word
                nachname = entferne_genitiv(second_word)
                vorname_start_idx = 0

    if vorname:
        if idx < len(words):
            next_word = words[idx]

            if ist_weiblich and next_word in maennliche_vornamen:
                partner = next_word
                idx += 1
                while idx < len(words) and words[idx] in maennliche_vornamen:
                    partner += " " + words[idx]
                    idx += 1
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1

            elif ist_weiblich and next_word in weibliche_vornamen:
                partner = next_word
                idx += 1
                while idx < len(words) and words[idx] in weibliche_vornamen:
                    partner += " " + words[idx]
                    idx += 1
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1

            elif not ist_weiblich and next_word in weibliche_vornamen:
                partner = next_word
                idx += 1
                while idx < len(words) and words[idx] in weibliche_vornamen:
                    partner += " " + words[idx]
                    idx += 1
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1

            elif not ist_weiblich and next_word in maennliche_vornamen:
                partner = next_word
                idx += 1
                while idx < len(words) and words[idx] in maennliche_vornamen:
                    partner += " " + words[idx]
                    idx += 1
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1

        if not nachname and idx < len(words):
            w = words[idx]
            if (w.lower() not in anreden and
                w.lower() not in ignoriere_woerter and
                w.lower() not in [s.lower() for s in stand_synonyme] and
                w.lower() not in ort_prae and
                w.lower() not in beruf_einleitung and
                w not in weibliche_vornamen and
                w not in maennliche_vornamen and
                not w.isdigit() and
                w.lower() not in ARTIKEL):
                nachname = entferne_genitiv(w)
                idx += 1
                while idx < len(words) and words[idx].lower() in ignoriere_woerter:
                    idx += 1

    if not vorname and not partner and idx < len(words):
        temp_idx = 0
        partner_vornamen = []
        partner_vornamen_indices = []
        while temp_idx < len(words):
            w = words[temp_idx]
            if w.lower() in anreden or w.lower() in ignoriere_woerter:
                temp_idx += 1
                continue
            if w in maennliche_vornamen:
                partner_vornamen.append(w)
                partner_vornamen_indices.append(temp_idx)
                temp_idx += 1
                while temp_idx < len(words) and words[temp_idx] in maennliche_vornamen:
                    partner_vornamen.append(words[temp_idx])
                    partner_vornamen_indices.append(temp_idx)
                    temp_idx += 1
                while temp_idx < len(words) and (words[temp_idx].lower() in anreden or words[temp_idx].lower() in ignoriere_woerter):
                    temp_idx += 1
                continue
            elif w.lower() in stand_synonyme:
                if partner_vornamen:
                    partner = " ".join(partner_vornamen)
                    if partner_vornamen_indices:
                        last_partner_idx = partner_vornamen_indices[-1]
                        search_idx = last_partner_idx + 1
                        while search_idx < len(words) and (words[search_idx].lower() in anreden or words[search_idx].lower() in ignoriere_woerter):
                            search_idx += 1
                        if search_idx < len(words):
                            potential_nachname = words[search_idx]
                            if (potential_nachname.lower() not in stand_synonyme and
                                potential_nachname.lower() not in anreden and
                                potential_nachname not in maennliche_vornamen and
                                potential_nachname not in weibliche_vornamen):
                                nachname = entferne_genitiv(potential_nachname)
                break
            else:
                temp_idx += 1

    if nachname:
        nachname = entferne_genitiv(nachname)
        if nachname:
            nachname = nachname[0].upper() + nachname[1:] if len(nachname) > 1 else nachname.upper()

    # === Beruf-Erkennung ===
    berufe_liste = []

    for i in range(len(words)-1):
        if words[i].lower() in ARTIKEL:
            if words[i+1] in BERUFE or words[i+1].lower() in [b.lower() for b in BERUFE]:
                if words[i+1].lower() == "becker":
                    berufe_liste.append("Bäcker")
                elif words[i+1].lower() == "bürger":
                    berufe_liste.append("Bürger")
                elif words[i+1].lower() == "schuemacher":
                    berufe_liste.append("Schuhmacher")
                else:
                    berufe_liste.append(words[i+1])

    for i in range(len(words)-1):
        if words[i].lower() in beruf_einleitung:
            next_word_lower = words[i+1].lower()
            if next_word_lower not in stand_synonyme and next_word_lower not in KEINE_BERUFE:
                if words[i+1] in BERUFE or words[i+1].lower() in [b.lower() for b in BERUFE]:
                    if words[i+1].lower() == "becker":
                        berufe_liste.append("Bäcker")
                    elif words[i+1].lower() == "bürger":
                        berufe_liste.append("Bürger")
                    elif words[i+1].lower() == "schuemacher":
                        berufe_liste.append("Schuhmacher")
                    else:
                        berufe_liste.append(words[i+1])
                else:
                    berufe_liste.append(words[i+1])

    i = 0
    while i < len(words):
        if words[i] in BERUFE or words[i].lower() in [b.lower() for b in BERUFE]:
            if i + 2 < len(words) and words[i+1].lower() in ["u", "und", "undt"]:
                if words[i+2] in BERUFE or words[i+2].lower() in [b.lower() for b in BERUFE]:
                    for w_idx, w_val in [(i, words[i]), (i+2, words[i+2])]:
                        if w_val.lower() == "becker":
                            berufe_liste.append("Bäcker")
                        elif w_val.lower() == "bürger":
                            berufe_liste.append("Bürger")
                        elif w_val.lower() == "schuemacher":
                            berufe_liste.append("Schuhmacher")
                        else:
                            berufe_liste.append(w_val)
                    i += 3
                    continue
        i += 1

    if nachname and not berufe_liste:
        for i in range(len(words)):
            w = words[i]
            is_title = ('.' in w or
                        w in ['Magister', 'Doctor', 'Professor', 'Syndicus', 'Syndikus'] or
                        w.upper() in ['IUD', 'HM', 'MD'])
            if is_title:
                beruf_parts = [w]
                j = i + 1
                while j < len(words):
                    next_w = words[j]
                    if next_w.lower() in ['den', 'der', 'begraben', 'begr', 'starb', 'gestorben', 'anno', 'alters', 'alt']:
                        break
                    if next_w.lower() in ['und', 'u', 'undt']:
                        if j + 1 < len(words):
                            beruf_parts.append(next_w)
                            beruf_parts.append(words[j + 1])
                            j += 2
                        else:
                            break
                    else:
                        j += 1
                if len(beruf_parts) > 0:
                    berufe_liste.append(' '.join(beruf_parts))
                    break

    beruf = " ".join(berufe_liste) if berufe_liste else None

    if vorname and ' ' in vorname and beruf:
        nachname_ist_beruf = nachname and (nachname in BERUFE or nachname.lower() in [b.lower() for b in BERUFE])
        if not nachname or nachname_ist_beruf:
            teile = vorname.split()
            if len(teile) == 2:
                teil1_weiblich = teile[0] in weibliche_vornamen
                teil1_maennlich = teile[0] in maennliche_vornamen
                teil2_weiblich = teile[1] in weibliche_vornamen
                teil2_maennlich = teile[1] in maennliche_vornamen
                if (teil1_weiblich and teil2_weiblich) or (teil1_maennlich and teil2_maennlich):
                    vorname = teile[0]
                    nachname = teile[1]

    # === Stand-Erkennung ===
    for i in range(idx, len(words)):
        stand_prefix = ""
        if words[i].lower() in STAND_PRAEFIXE:
            stand_prefix = words[i] + " "
            j = i + 1
        elif words[i].lower() == "ein" and i + 1 < len(words) and words[i + 1].lower() in stand_synonyme:
            stand_prefix = ""
            j = i + 1
        else:
            j = i

        if j < len(words) and words[j].lower() in stand_synonyme:
            word_lower = words[j].lower()
            stand = STAND_MAPPING.get(word_lower, words[j].capitalize())
            if stand_prefix:
                stand = stand_prefix + stand
            idx = j + 1
            break

    if not stand:
        text_lower = after_zitation.lower()
        for stand_key, stand_value in STAND_MAPPING.items():
            if stand_key in text_lower:
                stand = stand_value
                break

    # === Gender-Validierung des Stand ===
    if stand and vorname:
        stand_lower = stand.lower()
        stand_gender_pairs = {
            "tochter": "sohn", "dochter": "sohn", "tochterlein": "sohnlein",
            "töchterlein": "söhnlein", "döchterlein": "söhnlein",
            "witwe": "witwer", "wittib": "wittwer", "wittwe": "wittwer",
            "witbe": "witwer", "widwe": "witwer", "vidua": "witwer",
        }
        reverse_pairs = {v: k for k, v in stand_gender_pairs.items()}
        stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
        vorname_is_female = ist_weiblich
        stand_is_female = stand_base in [
            "tochter", "dochter", "tochterlein", "töchterlein", "döchterlein",
            "witwe", "wittib", "wittwe", "witbe", "widwe", "vidua", "hausfrau", "haußfrau"
        ]

        if vorname_is_female != stand_is_female:
            if stand_base in stand_gender_pairs:
                if not vorname_is_female:
                    correct_stand = stand_gender_pairs[stand_base]
                    stand = STAND_MAPPING.get(correct_stand, correct_stand.capitalize())
            elif stand_base in reverse_pairs:
                if vorname_is_female:
                    correct_stand = reverse_pairs[stand_base]
                    stand = STAND_MAPPING.get(correct_stand, correct_stand.capitalize())

    if not stand:
        if vorname and not ist_weiblich:
            stand = "Vater"

    # === Partner-Stand-Logik ===
    if stand:
        stand_lower = stand.lower()
        stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower

        if stand_base in PARTNER_STÄNDE:
            is_witwe_pattern = stand_base in ["witwe", "wittib", "wittwe", "witbe", "widwe", "witwer", "wittwer"]
            has_weilandt_pattern = any(w.lower() in ["weilandt", "weiland", "weyland", "seel", "seel.", "sel", "sel.", "seelig"] for w in words)

            if is_witwe_pattern and has_weilandt_pattern:
                if vorname and not ist_weiblich and not partner:
                    partner = vorname
                    vorname = None

                weilandt_idx = -1
                for i, w in enumerate(words):
                    if w.lower() in ["weilandt", "weiland", "weyland", "seel", "seel.", "sel", "sel.", "seelig"]:
                        weilandt_idx = i
                        break

                if not partner and weilandt_idx >= 0:
                    j = weilandt_idx + 1
                    while j < len(words) and words[j].lower() in ["herrn", "hern", "herr", "h", "h."] + [w.lower() for w in ignoriere_woerter]:
                        j += 1
                    if j < len(words) and words[j] in maennliche_vornamen:
                        partner_vorname = words[j]
                        if partner_vorname.endswith('is') and len(partner_vorname) > 3:
                            partner_vorname = partner_vorname[:-2]
                        elif partner_vorname.endswith('s') and len(partner_vorname) > 2:
                            if partner_vorname[-2] not in 'aeiouäöü':
                                partner_vorname = partner_vorname[:-1]
                        if j + 1 < len(words):
                            partner_nachname = words[j + 1]
                            if partner_nachname.endswith('is') and len(partner_nachname) > 3:
                                partner_nachname = partner_nachname[:-2]
                                nachname = partner_nachname
                            elif partner_nachname.endswith('s') and len(partner_nachname) > 2:
                                if partner_nachname[-2] not in 'aeiouäöü':
                                    partner_nachname = partner_nachname[:-1]
                                    nachname = partner_nachname
                                else:
                                    nachname = partner_nachname
                            else:
                                nachname = partner_nachname
                        if not partner:
                            partner = partner_vorname
                    else:
                        if not partner:
                            for k in range(weilandt_idx - 1, -1, -1):
                                if words[k] in maennliche_vornamen:
                                    partner = words[k]
                                    if k + 1 < weilandt_idx:
                                        next_word = words[k + 1]
                                        if next_word.lower() not in [w.lower() for w in ignoriere_woerter]:
                                            nachname = entferne_genitiv(next_word)
                                    break
            else:
                is_tochter = stand_base in ["tochter", "dochter", "töchterlein", "döchterlein"]
                is_sohn = stand_base in ["sohn", "son", "söhnlein", "sohnlein"]

                apply_partner_logic = True
                if is_tochter and ist_weiblich:
                    apply_partner_logic = False

                if apply_partner_logic:
                    sohn_special_case = False
                    if is_sohn and vorname and nachname and not partner:
                        for i in range(len(words)):
                            w = words[i]
                            if w == vorname:
                                continue
                            if w in maennliche_vornamen:
                                partner = w
                                sohn_special_case = True
                                partner_idx = i
                                if partner_idx + 1 < len(words):
                                    next_word = words[partner_idx + 1]
                                    if (next_word.endswith('s') and
                                        next_word.lower() not in stand_synonyme and
                                        next_word.lower() not in ignoriere_woerter and
                                        next_word not in maennliche_vornamen):
                                        pass
                                break

                    partner_bereits_gesetzt = bool(partner)

                    if not partner:
                        if vorname:
                            partner = vorname
                        elif nachname:
                            partner = nachname

                    if not partner_bereits_gesetzt and not sohn_special_case:
                        vorname = None

    # === Hausfrau-Sonderfall ===
    weibliche_stände = ["hausfrau", "haußfrau", "wittwe", "wittib", "wittwe", "witbe", "widwe"]

    if stand and stand.lower() in weibliche_stände and vorname and ist_weiblich:
        search_start = vorname_start_idx + 1
        while search_start < len(words) and words[search_start] in weibliche_vornamen:
            search_start += 1
        while search_start < len(words) and words[search_start].lower() in ignoriere_woerter:
            search_start += 1

        if search_start < len(words):
            next_word = words[search_start]
            if next_word in maennliche_vornamen:
                partner = next_word
                search_start += 1
                while search_start < len(words) and words[search_start] in maennliche_vornamen:
                    partner += " " + words[search_start]
                    search_start += 1
                while search_start < len(words) and words[search_start].lower() in ignoriere_woerter:
                    search_start += 1
                if search_start < len(words):
                    potential_nachname = words[search_start]
                    if (potential_nachname.lower() not in stand_synonyme and
                        potential_nachname.lower() not in anreden and
                        potential_nachname.lower() not in ort_prae and
                        not potential_nachname.isdigit()):
                        nachname = entferne_genitiv(potential_nachname)
            elif (next_word.lower() not in stand_synonyme and
                  next_word.lower() not in anreden and
                  next_word.lower() not in ort_prae and
                  not next_word.isdigit()):
                nachname = next_word
                search_start += 1
                while search_start < len(words) and words[search_start].lower() in ignoriere_woerter:
                    search_start += 1
                if search_start < len(words):
                    potential_partner = words[search_start]
                    has_genitiv = (
                        (potential_partner.endswith('s') and len(potential_partner) > 2) or
                        (potential_partner.endswith('en') and len(potential_partner) > 3) or
                        (potential_partner.endswith('tts') and len(potential_partner) > 4)
                    )
                    if has_genitiv and potential_partner.lower() not in stand_synonyme:
                        partner = potential_partner

    if stand and stand.lower() in weibliche_stände and vorname and not partner:
        stand_idx = idx - 1
        for i in range(stand_idx - 1, -1, -1):
            w = words[i]
            has_genitiv = (
                (w.endswith('s') and len(w) > 2) or
                (w.endswith('en') and len(w) > 3) or
                (w.endswith('tts') and len(w) > 4)
            )
            if has_genitiv and w.lower() not in stand_synonyme and w not in anreden and w != nachname:
                partner = w
                break

    if stand and not vorname:
        stand_lower = stand.lower()
        stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
        is_tochter = stand_base in ["tochter", "dochter", "tochterlein", "töchterlein", "döchterlein"]
        is_witwe = stand_base in ["witwe", "wittib", "wittwe", "witbe", "widwe"]

        if is_tochter or is_witwe:
            for i in range(len(words)):
                if words[i].lower() in stand_synonyme:
                    j = i + 1
                    while j < len(words) and (words[j].lower() in ["von", "von der"] or words[j].isdigit() or words[j].lower() in ["jahren", "jahr"]):
                        j += 1
                    if j < len(words) and words[j] in weibliche_vornamen:
                        vorname = words[j]
                        j += 1
                        if j < len(words) and words[j] in weibliche_vornamen:
                            vorname += " " + words[j]
                        break

    if stand and not vorname and not partner:
        stand_lower = stand.lower()
        stand_base = stand_lower.split()[-1] if ' ' in stand_lower else stand_lower
        is_witwe_hausfrau = stand_base in ["witwe", "wittib", "wittwe", "witbe", "widwe", "hausfrau", "haußfrau"]

        if is_witwe_hausfrau:
            stand_idx = -1
            for i in range(len(words)):
                if words[i].lower() in stand_synonyme:
                    stand_idx = i
                    break

            if stand_idx >= 3:
                check_idx = stand_idx - 1
                while check_idx >= 0 and words[check_idx].lower() in STAND_PRAEFIXE:
                    check_idx -= 1

                if check_idx >= 0:
                    potential_genitiv = words[check_idx]
                    has_genitiv = (
                        (potential_genitiv.endswith('s') and len(potential_genitiv) > 2) or
                        (potential_genitiv.endswith('en') and len(potential_genitiv) > 3) or
                        (potential_genitiv.endswith('tts') and len(potential_genitiv) > 4)
                    )
                    if has_genitiv and potential_genitiv.lower() not in stand_synonyme:
                        nachname = entferne_genitiv(potential_genitiv)
                        check_idx -= 1
                        if check_idx >= 0:
                            partner = words[check_idx]
                            check_idx -= 1
                            if check_idx >= 0:
                                vorname = words[check_idx]
                                ist_weiblich = True

    # === Ort ===
    for i in range(idx, len(words)):
        if i + 1 < len(words) and words[i].lower() == "in" and words[i+1].lower() == "der":
            if i + 2 < len(words):
                ort = words[i+2]
                idx = i + 3
                break
        elif words[i].lower() in ort_prae:
            if i + 1 < len(words):
                potential_ort = words[i+1]
                if not potential_ort.isdigit():
                    ort = potential_ort
                    idx = i + 2
            break

    if partner:
        partner = entferne_genitiv(partner)

    def restore_original_case(value, words_cap, words_orig):
        if not value:
            return value
        result_parts = []
        value_words = value.split()
        for vw in value_words:
            found = False
            for i, cw in enumerate(words_cap):
                if cw == vw:
                    result_parts.append(words_orig[i])
                    words_cap = words_cap[:i] + words_cap[i+1:]
                    words_orig = words_orig[:i] + words_orig[i+1:]
                    found = True
                    break
            if not found:
                result_parts.append(vw)
        return " ".join(result_parts)

    if vorname:
        vorname = restore_original_case(vorname, words.copy(), words_original_case.copy())
    if nachname:
        nachname = restore_original_case(nachname, words.copy(), words_original_case.copy())
    if partner:
        partner = restore_original_case(partner, words.copy(), words_original_case.copy())

    vorname = expand_abbreviated_first_names(vorname, gender='unknown')
    partner = expand_abbreviated_first_names(partner, gender='unknown')

    result['vorname'] = vorname
    result['nachname'] = nachname
    result['partner'] = partner
    result['beruf'] = beruf
    result['stand'] = stand
    result['ort'] = ort

    # === Alters-Extraktion und Geburtsjahr-Berechnung ===
    alter_jahre = None
    geb_jahr_gesch = None

    alter_pattern = r'(?:aetat(?:is|isis)?|aet\.?|alters?)\s*(?:anno)?\s*(?:aetatis(?:is)?)?\s*[.:]*\s*(\d+)(?:[.,]?\s*(\d+)?)?\s*(?:jahr|ann(?:i)?|wochen|tag|monat|mens(?:is)?)?'

    alter_match = re.search(alter_pattern, text, re.IGNORECASE)
    if alter_match:
        alter_jahre = int(alter_match.group(1))
        if result.get('todestag') and alter_jahre is not None:
            try:
                jahr_match = re.match(r'(\d{4})', result['todestag'])
                if jahr_match:
                    todes_jahr = int(jahr_match.group(1))
                    geb_jahr_gesch = todes_jahr - alter_jahre
            except (ValueError, AttributeError):
                pass

    result['geb_jahr_gesch'] = geb_jahr_gesch

    return result
