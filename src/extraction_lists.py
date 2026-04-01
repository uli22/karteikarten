"""
Datenlisten für die Extraktion von Feldern aus Kirchenbuch-Einträgen.

Dieses Modul enthält alle Listen und Mappings für:
- Vornamen (männlich/weiblich)
- Stand-Synonyme mit Normalisierung
- Orts-Präpositionen
- Berufseinleitungen
- Anreden
- Zu ignorierende Wörter
"""

import json
import sys
from pathlib import Path


def _get_lists_dir() -> Path:
    """Gibt das Verzeichnis zurück, in dem die JSON-Listendateien liegen."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _load_list(filename: str, default: list) -> list:
    """Lädt eine Liste aus einer JSON-Datei; gibt default zurück wenn nicht vorhanden."""
    path = _get_lists_dir() / filename
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return default


def _load_mapping(filename: str, default: dict) -> dict:
    """Lädt ein Dict aus einer JSON-Datei; gibt default zurück wenn nicht vorhanden."""
    path = _get_lists_dir() / filename
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return default

def get_sources_with_adjusted_paths(config=None):
    """
    Gibt die SOURCES-Liste mit angepassten media_path zurück.
    Die Pfade werden basierend auf der Config angepasst.
    """
    import re

    if config is None:
        from .config import get_config
        config = get_config()

    media_drive = config.media_drive
    
    adjusted_sources = []
    for source in _SOURCES_TEMPLATE:
        source_copy = source.copy()
        if source_copy.get("media_path"):
            # Ersetze Laufwerksbuchstaben (z.B. "E:" durch config.media_drive)
            original_path = source_copy["media_path"]
            # Pattern: Laufwerksbuchstabe am Anfang (z.B. "E:\\")
            adjusted_path = re.sub(r'^[A-Z]:', media_drive, original_path)
            source_copy["media_path"] = adjusted_path
        adjusted_sources.append(source_copy)
    
    return adjusted_sources


# Original SOURCES als Template (wird nicht direkt verwendet)
_SOURCES_TEMPLATE = [
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 Gb Hb Sb 1613-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831",
        "id": "S1",
        "media_path": None,
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611",
        "id": "S2",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1564-1611\\Wetzlar Kirchenbuchkartei Gb 1564-1611\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632",
        "id": "S3",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1611-1632\\Wetzlar Kirchenbuchkartei Gb 1611-1632\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670",
        "id": "S4",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1633-1670\\Wetzlar Kirchenbuchkartei Gb 1633-1670\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695",
        "id": "S5",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1671-1695\\Wetzlar Kirchenbuchkartei Gb 1671-1695\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718",
        "id": "S6",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1695-1718\\Wetzlar Kirchenbuchkartei Gb 1695-1718\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734",
        "id": "S7",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1718-1734\\Wetzlar Kirchenbuchkartei Gb 1718-1734\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746",
        "id": "S8",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1735-1746\\Wetzlar Kirchenbuchkartei Gb 1735-1746\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761",
        "id": "S9",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1746-1761\\Wetzlar Kirchenbuchkartei Gb 1746-1761\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780",
        "id": "S10",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1761-1780\\Wetzlar Kirchenbuchkartei Gb 1761-1780\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798",
        "id": "S11",
        "media_path": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1780-1798\\Wetzlar Kirchenbuchkartei Gb 1780-1798\\",
        "media_type": "wetzlarkartei"
    },
    {
        "source": "WETZLAR KbGb 1571-1613 lutherisch",
        "id": "S12",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1571-1613 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_001_Gb"
    },
    {
        "source": "Wetzlar KbHb 1564-1590 lutherisch",
        "id": "S13",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbHb 1564-1590 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_001_Hb"
    },
    {
        "source": "WETZLAR KbGb 1614-1687 lutherisch",
        "id": "S15",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1614-1687 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_002_Gb"
    },
    {
        "source": "Wetzlar KbHb 1608-1693 lutherisch",
        "id": "S35",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbHb 1608-1693 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_020_Hb"
    },
    {
        "source": "Wetzlar KbSb 1613-1693 lutherisch",
        "id": "S36",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbSb 1613-1693 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_020_Sb"
    },
    {
        "source": "Wetzlar KbHb 1694-1776 lutherisch",
        "id": "S37",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbHb 1694-1776 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_021_Hb",
        "OK":"OK"
    },
    {
        "source": "Wetzlar KbSb 1694-1776 lutherisch",
        "id": "S38",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbSb 1694-1776 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_021_Sb",
        "OK":"OK"
    },
    {
        "source": "WETZLAR KbGb 1688-1744 lutherisch",
        "id": "S16",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1688-1744 KbKb 1688-1735 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_003_Gb"
    },
    {
        "source": "WETZLAR KbGb 1745-1810 lutherisch",
        "id": "S18",
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1745-1810 KbKb 1759, 1764, 1802-1808 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_004_Gb"
    },
    {
        "source": "WETZLAR KbGb 1811-1820 lutherisch",
        "id": None,
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1811-1820 KbKb 1813-1820 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_005_Gb"
    }
]

# SOURCES wird dynamisch erzeugt mit angepassten Pfaden basierend auf Config
SOURCES = get_sources_with_adjusted_paths()

# =============================================================================
# VORNAMEN
# =============================================================================

WEIBLICHE_VORNAMEN = [
    "Agnes", "Ann", "Anna", "An-Elisabeth", "Annamagdt",
    "Appolonia", "Appoloniaa", "Appoloniae", "Appoloniaf", "Appoloniah", 
    "Appoloniai", "Appoloniao", "Appoloniap", "Appoloniar", "Appoloniat", 
    "Appoloniau", "Appoloniaz", "Appollonia", 
    "Barb", "Barbara", "Barben", 
    "Cath", "Cattarein", "Cathrina", "Catharina", "Cattarina", "Catharein", "Christina", "Creinmagt","Creinchen", "Causa",
    "Dor", "Dorothea", "Dorotheja",
    "Elis", "Elisabeth", "Elisabetha", "Elchen", "Elschen", "Elsbeth", "Elssbeth", "Eleonora", "Enchen", "Engel", "Eva", "Eyda", "Eyla", "Elss",
    "Felicitas", "Francoys",
    "Gertrud", "Gertraut", "Gerdraut", "Gela", "Giddert", "Gilchen", "Gritchen",
    "Johanna", "Juliana", "Justina",
    "Katharina",
    "Jul", "Leisa", 
    "Magdalena", "Marg", "Margaretha", "Margret", "Margreth", "Maria", 
    "Rachell", "Reg", "Regina", 
    "Sara", "Sabina", "Sophia", "Sus", "Susanna", "Susan",
    "Ursula", "Ursell",
    "Walpern",
]

MAENNLICHE_VORNAMEN = [
    "Abraham", "Adam", "Adolff", "Adrian", "Andr", "Andreas", "Andres", "Andreae", "Aegidius", "Albert",
    "Anton", "Antoni", "Antony", "Antonii", "Antonius", "Anthonius","Alexander","Anthonii", "Arnold", "August", 
    "Balthasar", "Balthasaris", "Burckgart", "Balther",  "Baltzer", "Braun", "Bernhard", "Bernhardt",
    "Carlen", "Carl", "Carle", "Caspar", "Christian", "Christoph", "Christophel", "Christophorus", "Claus", "Conrad", "Conradt", "Curt", "Crafft", "Chasper",
    "Daniel", "Daniell", "David", "Davidt", "Dietrich","Dieterich", "Diln",
    "Eberhard", "Eberhart", "Ebert", "Eckardt", "Eckhardt", "Elias", "Emrich", "Enders", "Enderß", "Ernst", 
    "Franz", "Frantz", "Frid", "Friedrich", "Friderich", "Friderich",
    "Gaebhart", "Geo", "Gebert", "Georg", "George", "Gebert", "Görg", "Gerhardt",
    "Hans", "Hanss", "Hanß", "Heinr", "Heinrich", "Henrich", "Hieronymus", "Herman",
    "Isaak",
    "Jacob", "Jean", "Joan", "Joachim", "Jochim", "Joh", "Joh.", "Johan", "Johann", "Johannes", "Joannes", "Jonas", "Joes", "Jost",  "Just", "Jurge", "Jörg", "jörg", "Jorg",
    "Karl", 
    "Conr", "Leonhard", "Ludwig", "Lorentz", 
    "Mart", "Martin", "Matth", "Matthias", "Matthäus", "Maximilian", "Michael", "Michel", 
    "Nikolaus", "Niclas",
    "Otto", 
    "Paul", "Pet", "Peter", "Petr", "Phil", "Philip", "Philipp", "Philips", "Paulus",
    "Reinhard", "Reinhart", "Rudolf", "Ruland",
    "Samuel", "Seb", "Sebastian", "Simon", "Stephan", 
    "Theis", "Theiss", "Theiß", "Theoph", "Thomas", "Theophilus", "Theophili", "Theophil", "Tongess",
    "Ulrich",
    "Valentin", "Veldten", "Velten", 
    "Weigand", "Wilh", "Wilhelm",
    "Zacharias", "Zerben",
]

# =============================================================================
# STAND-SYNONYME mit Normalisierung
# =============================================================================
# Schlüssel: Variante (lowercase), Wert: Normalisierte Schreibweise

STAND_MAPPING = {
    # Wittwe/Witwe
    "witwe": "Wittwe",
    "wittib": "Wittwe",
    "wittwe": "Wittwe",
    "wittbe": "Wittwe",
    "witbe": "Wittwe",
    "widwe": "Wittwe",
    "vidua": "Wittwe",
    "nachgelassene witwe": "Wittwe",
    "nachgelassene wittwe": "Wittwe",
    "hinterlassene wittib": "Wittwe",
    "hinterlassene wittwe": "Wittwe",
    "hinterlassene witwe": "Wittwe",
    "gewesene hausfrau": "Wittwe",
    "gewesener hausfrau": "Wittwe",

    # Wittwer/Witwer
    "witwer": "Wittwer",
    "wittwer": "Wittwer",
    
    
    # Hausfrau
    "frau": "Hausfrau",
    "fraw": "Hausfrau",
    "hausfrau": "Hausfrau",
    "haußfrau": "Hausfrau",
    "hausfraw": "Hausfrau",
    "hausfr": "Hausfrau",  # Abkürzung
    "hausfr.": "Hausfrau",  # Abkürzung mit Punkt
    "haußfr": "Hausfrau",  # Abkürzung alte Schreibweise
    "haußfr.": "Hausfrau",  # Abkürzung alte Schreibweise mit Punkt
    "uxor": "Hausfrau",
    
    # Tochter
    "tochter": "Tochter",
    "dochter": "Tochter",
    "tochterlein": "Tochter",  # ohne Umlaut
    "töchterlein": "Tochter",
    "döchterlein": "Tochter",
    "verlassener tochter": "verlassene Tochter",
    "verlassene tochter": "verlassene Tochter",
    "hinterlassene tochter": "hinterlassene Tochter",
    "relicta filia": "hinterlassene Tochter",  # lat.: hinterlassene Tochter
    "filia": "Tochter",                         # lat.: Tochter
    
    # Sohn
    "sohn": "Sohn",
    "sohnlein": "Sohn",
    "söhnlein": "Sohn",
    "son": "Sohn",
    
    # Eidam (Schwiegersohn)
    "eidam": "Eidam",
    
    # Schwiegersohn
    "schwiegersohn": "Schwiegersohn",
    
    # Schwiegertochter
    "schwiegertochter": "Schwiegertochter",
    
    # Stieftochter
    "stieftochter": "Stieftochter",

    # Stiefsohn
    "stiefsohn": "Stiefsohn",
    "stiffson": "Stiefsohn",  # historische Schreibweise
    
    # Enkel/Enkelin
    "enkel": "Enkel",
    "enkelin": "Enkelin",
    
    # Kind
    "kind": "Kind",
    "wochenkind": "Wochenkind",
    
    # Mädchen
    "medtgen": "Mädchen",
    "fraulein": "Fräulein",
    "fräulein": "Fräulein",
    "fraülein": "Fräulein",
}

# Liste aller Stand-Synonyme (für Prüfung ob Wort ein Stand ist)
STAND_SYNONYME = list(STAND_MAPPING.keys())

# Liste der Stände, bei denen der erkannte Name zum Partner gehört
# (z.B. "Johan Eberhard Frinck ein Töchterlein" -> Johan Eberhard Frinck = Partner/Vater)
PARTNER_STÄNDE = [
    "tochter", "dochter", "tochterlein", "töchterlein", "döchterlein",
    "sohn", "sohnlein", "söhnlein", "son",
    "kind", "wochenkind",
    "witwe", "wittib", "wittwe", "witbe", "widwe", "vidua",
    "witwer", "wittwer"
]

# =============================================================================
# ORTS-PRÄPOSITIONEN
# =============================================================================

ORTS_PRAEPOSITIONEN = [
    "in", 
    "in der", 
    "von", 
    "zu"
]

# =============================================================================
# BERUFSEINLEITUNGEN
# =============================================================================

BERUFS_EINLEITUNG = [
    "ein"
]

# =============================================================================
# BERUFE (typische Berufsbezeichnungen)
# =============================================================================

BERUFE = [
    "Schreiber", "Schreibern", "Schreibers",
    "Schreiner", "Schreinern", "Schreiners",
    "Schneider", "Schneidern", "Schneiders",
    "Schmied", "Schmiede", "Schmieds",
    "Bäcker", "Bäckern", "Bäckers", "becker", "Becker",  # historische Schreibweise und Großschreibung nach Normalisierung
    "Bürger", "Bürgern", "Bürgers", "bürger",  # kleingeschrieben für historische Schreibweise
    "Kannengießer",
    "Koch", "Kochen", "Kochs",
    "Metzger", "Metzgern", "Metzgers",
    "Müller", "Müllern", "Müllers",
    "Wagner", "Wagnern", "Wagners",
    "Zimmermann", "Zimmermanns",
    "Maurer", "Maurern", "Maurers",
    "Leinweber", "Leinwebern", "Leinwebers",
    "Weber", "Webern", "Webers",
    "Schuster", "Schustern", "Schusters",
    "Tischler", "Tischlern", "Tischlers",
    "Böttcher", "Böttchern", "Böttchers",
    "Küfer", "Küfern", "Küfers",
    "Färber", "Färbern", "Färbers",
    "Gerber", "Gerbern", "Gerbers",
    "Sattler", "Sattlern", "Sattlers",
    "Seiler", "Seilern", "Seilers",
    "Schuhmacher", "schuemacher",  # historische Schreibweise
    "Glaser", "Glasern", "Glasers",
    "Töpfer", "Töpfern", "Töpfers",
    "Schlosser", "Schlossern", "Schlossers",
    "Kaufmann", "Kaufmanns", "Kaufleute",
    "Krämer", "Krämern", "Krämers",
    "Wirt", "Wirtin", "Wirten", "Wirts",
    "Pfarrer", "Pfarrern", "Pfarrers",
    "Lehrer", "Lehrern", "Lehrers",
    "Schulmeister", "Schulmeisters",
    "Amtmann", "Amtmanns",
    "Bürgermeister", "Bürgermeisters",
    "Rentmeister", "Rentmeisters",
    "Förster", "Förstern", "Försters",
    "Jäger", "Jägern", "Jägers",
    "Knecht", "Knechte", "Knechts",
    "Magd", "Mägde",
    "Diener", "Dienern", "Dieners",
    "Dienerin", "Dienerinnen",
    "Kindfraw", "Kindfrau",  # Hebamme
    "Bruder", "Brüder",
    "Schöpff", "Schöpf", "Schöpffen",  # Schöffe
    "Rathsverwandter", "Rathsverwandte", "Rathsfreundt",
    "Not. Caes. publ.",
    "Advoc. Cam.",
    "Magister",
    "M.",  # Abkürzung für Magister
    "Wüllenknecht",
]

# =============================================================================
# KEINE BERUFE (Wörter die nach "ein" stehen können, aber keine Berufe sind)
# Z.B. Adjektive, Beschreibungen, etc.
# =============================================================================

KEINE_BERUFE = [
    "sieches",  # siech = krank
    "siechs",
    "siech",
    "krankes",
    "krank",
    "altes",
    "alt",
    "junges",
    "jung"
]

# =============================================================================
# ANREDEN (werden übersprungen)
# HINWEIS: "frau" ist NICHT hier, da es auch ein Stand sein kann (Hausfrau)
# "frau" wird kontextabhängig in der Extraktionslogik behandelt
# =============================================================================

ANREDEN = [
    "herrn", 
    "hern",  # Schreibvariante von "Herrn"
    "herr",
    "h",
    "h.",
    "m",
    "m.",  # Magister
    "Jungfr.",
    "Jfr.",
    "Jfr",
]

# =============================================================================
# ARTIKEL (markieren Berufe: "der Schreiner" = Beruf, "Schreiner" = Nachname)
# =============================================================================

ARTIKEL = [
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des"
]

# =============================================================================
# ZU IGNORIERENDE WÖRTER (bei Nachname/Stand-Erkennung)
# =============================================================================

IGNORIERE_WOERTER = [
    "seel", 
    "sel", 
    "sel.", 
    "selig", 
    "seelig", 
    "weiland",
    "weilandt",
    "weyland",
    "weil.",
    "hinterlassene", 
    "hinterlassen", 
    "hinterl.", 
    "hinterl", 
    "verlassen", 
    "verlassene",
    "sein",  # "sein Hausfraw" - Pronomen vor Stand
    "den",  # "Den 28. Januarii" - gehört zum Datum
    "dem",
    "der",
    "am",   # "am 19. Martii" - Präposition vor Datum
    "u",    # "und" Abkürzung zwischen Berufen
    "u.",
    "und",
    # Hochzeits-Stopwords (gehören nicht zu Namen)
    "hielten",
    "hilten",
    "hilt",
    "hochzeit",
    "Hochzeit",
    "copulirt",
    "copuliret",
    "copulati",
    "getraut",
    "getrauet",
    "proclamirt",
    "pclamirt",
    "feria",  # "feria 3tia Pasch" - Wochentag
    # Monatsnamen (können kein Personenname sein)
    "januar", "januarii", "january",
    "februar", "februarii", "february",
    "mertz", "martii", "march", "märz",
    "april", "aprilis",
    "may", "maii", "mai",
    "juni", "junii", "june",
    "juli", "julii", "july",
    "august", "augusti",
    "september", "septembris",
    "october", "octobris", "oktober",
    "november", "novembris", "novemb",
    "december", "decembris", "dezember",
    # Jahresbezeichnung
    "ao", "anno"
]

# =============================================================================
# STAND-PRÄFIXE (für "hinterlassene Wittwe" etc.)
# =============================================================================

STAND_PRAEFIXE = [
    "hinterlassener",
    "hinterlassene",
    "hinterlassen",
    "hinterl.",
    "hinterl",    
    # HINWEIS: "verlassen" wird bei Witwe/Witwer ignoriert (in IGNORIERE_WOERTER)
    # Bei Tochter/Sohn bleibt es als eigenständiges Präfix erhalten
]

# =============================================================================
# BENUTZERDEFINIERTE ANPASSUNGEN aus JSON-Dateien (überschreiben die Defaults)
# =============================================================================

WEIBLICHE_VORNAMEN = _load_list('vornamen_weiblich.json', WEIBLICHE_VORNAMEN)
MAENNLICHE_VORNAMEN = _load_list('vornamen_maennlich.json', MAENNLICHE_VORNAMEN)
BERUFE = _load_list('berufe.json', BERUFE)
STAND_MAPPING = _load_mapping('stand_mapping.json', STAND_MAPPING)
# Abgeleitete Listen nach möglichem JSON-Überschreiben aktualisieren
STAND_SYNONYME = list(STAND_MAPPING.keys())
