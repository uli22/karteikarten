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

SOURCES = [
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
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1688-1744 lutherisch\\",
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
        "media_path": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1811-1820 lutherisch\\",
        "media_type": "kirchenbuchseiten",
        "media_ID": "EKiR_408_005_Gb"
    }
]

# =============================================================================
# VORNAMEN
# =============================================================================

WEIBLICHE_VORNAMEN = [
    "Agnes", "Ann", "Anna", "An-Elisabeth",
    "Appolonia", "Appoloniaa", "Appoloniae", "Appoloniaf", "Appoloniah", 
    "Appoloniai", "Appoloniao", "Appoloniap", "Appoloniar", "Appoloniat", 
    "Appoloniau", "Appoloniaz", "Appollonia", 
    "Barbara", "Barben", 
    "Cathrina", "Catharina", "Christina", 
    "Elisabeth", "Enchen", "Engel", "Eva", 
    "Gertrud", 
    "Juliana", 
    "Katharina", 
    "Magdalena", "Margaretha", "Margreth", "Maria", 
    "Regina", 
    "Sara", "Sophia", "Susanna", 
    "Ursula"
]

MAENNLICHE_VORNAMEN = [
    "Abraham", "Adam", "Adolff", "Adrian", "Andreas", "Aegidius", "Albert",
    "Anton", "Antoni", "Antony", "Antonii", "Antonius", "Anthonius","Alexander","Anthonii",
    "August", 
    "Balthasar", "Burckgart", "Balther", "Braun",
    "Caspar", "Christian", "Christoph", "Christophorus", "Conrad", "Crafft", 
    "Daniel", "David",
    "Eberhart", "Ebert", "Emrich", "Enders", "Ernst", 
    "Franz", "Frantz", "Friedrich", "Friderich",
    "Georg", "George", "Gebert", "Görg",
    "Hans", "Hanß", "Heinrich", "Henrich", "Hieronymus",
    "Jacob", "Jean", "Joh.", "Johann", "Johannes", "Joannes", "Jonas", "Joes", "Jost", "Jurge", 
    "Karl", 
    "Leonhard", "Ludwig", 
    "Martin", "Matthias", "Matthäus", "Maximilian", "Michael", 
    "Nikolaus", 
    "Otto", 
    "Paul", "Peter", "Philipp", "Philips",
    "Rudolf", 
    "Samuel", "Sebastian", "Simon", "Stephan", 
    "Thomas", "Theophilus", "Theophili",
    "Valentin", "Veldten", "Velten", 
    "Wilhelm",
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
    "witbe": "Wittwe",

    # Wittwer/Witwer
    "witwer": "Wittwer",
    "wittwer": "Wittwer",
    
    
    # Hausfrau
    "frau": "Hausfrau",
    "fraw": "Hausfrau",
    "hausfrau": "Hausfrau",
    "hausfraw": "Hausfrau",
    "uxor": "Hausfrau",
    
    # Tochter
    "tochter": "Tochter",
    "töchterlein": "Tochter",
    
    # Sohn
    "sohn": "Sohn",
    "sohnlein": "Sohn",
    "söhnlein": "Sohn",
    
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
    
    # Enkel/Enkelin
    "enkel": "Enkel",
    "enkelin": "Enkelin",
    
    # Kind
    "kind": "Kind",
    "wochenkind": "Wochenkind",
    
    # Mädchen
    "medtgen": "Mädchen",
}

# Liste aller Stand-Synonyme (für Prüfung ob Wort ein Stand ist)
STAND_SYNONYME = list(STAND_MAPPING.keys())

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
    "Bäcker", "Bäckern", "Bäckers",
    "Koch", "Kochen", "Kochs",
    "Metzger", "Metzgern", "Metzgers",
    "Müller", "Müllern", "Müllers",
    "Wagner", "Wagnern", "Wagners",
    "Zimmermann", "Zimmermanns",
    "Maurer", "Maurern", "Maurers",
    "Weber", "Webern", "Webers",
    "Schuster", "Schustern", "Schusters",
    "Tischler", "Tischlern", "Tischlers",
    "Böttcher", "Böttchern", "Böttchers",
    "Küfer", "Küfern", "Küfers",
    "Färber", "Färbern", "Färbers",
    "Gerber", "Gerbern", "Gerbers",
    "Sattler", "Sattlern", "Sattlers",
    "Seiler", "Seilern", "Seilers",
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
    "Dienerin", "Dienerinnen"
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
    "herr",
    "h",
    "h."
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
    "hinterlassene", 
    "hinterlassen", 
    "hinterl.", 
    "hinterl", 
    "verlassen", 
    "verlassene"
]

# =============================================================================
# STAND-PRÄFIXE (für "hinterlassene Wittwe" etc.)
# =============================================================================

STAND_PRAEFIXE = [
    "hinterlassener",
    "hinterl.",
    "hinterl",
    "hinterlassen",
    "verlassen"
]
