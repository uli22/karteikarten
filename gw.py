"""
xlsx_to_gedcom.py.

Ein vollständiges, modularisiertes GEDCOM-Export-Skript
- Deduping: gleiche Personen (Vorname, Nachname, Geburtsdatum) werden wiederverwendet
- Media: M2-style separate OBJE-Records (0 @Mxxx@ OBJE ...), INDI referenziert mit 1 OBJE @Mxxx@
- Plugins: TNG / GRAMPS (leicht erweiterbar)
- Streaming: schreibt via gf.write(...)

letzte Änderungen: est_father_birth ist aber an der falschen Stelle!
Verschiebung des headers in make_gedcom

TO DO Vater bei mehreren Ehen 2x ?
Gramps alles OK
Modifiing TNG
TNG: Nur geburt: Karteikarte abschr
          taufe: Kirchenbuch abschr
          taufe: beide Bilder	

Die folgenden Vereinbarungen gelten nur für die TNG Version. Die GRAMPS version ist ok und soll so beibehalten werden.
Beide Abschriften hängen an der Quelle und diese am jeweiligen Ereignis.

TNG-spezifische Regeln (v1.07):
1. Wenn nur Taufereignis vorhanden (kein BIRT), wird ein BIRT Ereignis hinzugefügt mit:
   - Datum: ABT {Taufdatum}
   - Ort: Wetzlar (normalisiert via ORT_ZU_ORT)
   - Notiz: "Geschätzt aus Taufdatum"
2. Bei der gedcom Ausgabe soll die note mit der KK Abschrift an dieses, bzw alle Geb Ereignisse 
   angehängt werden, falls eine KB Abschrift als note existiert, soll diese an das Taufereignis 
   angehängt werden.

"""
import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, Set, Tuple, Union
from zoneinfo import ZoneInfo

import pandas as pd
from lib.OrteLDK import ORT_ZU_ORT
from version import __version__, get_header_version

# Skriptname automatisch aus Dateinamen
SCRIPT_NAME = Path(__file__).stem


def extract_year_range(filename: str) -> str:
    """
    Extrahiert den Jahresbereich aus einem Dateinamen.
    
    Beispiel:
        '00_KB_1614-1670_Taufen_EINGABE001_V8.xlsx' -> '1614-1670'
        '00_KB_1571-1613_Taufen_EINGABE001_V6.xlsx' -> '1571-1613'
    
    Args:
        filename: Vollständiger Dateipfad oder nur Dateiname
    
    Returns:
        Jahresbereich im Format 'YYYY-YYYY' oder leerer String wenn nicht gefunden
    """
    # Extrahiere nur den Dateinamen, falls ein Pfad übergeben wurde
    filename = Path(filename).name
    
    # Suche nach Muster: 4 Ziffern - 4 Ziffern
    match = re.search(r'(\d{4})-(\d{4})', filename)
    if match:
        return match.group(0)  # Gibt "YYYY-YYYY" zurück
    return ""


def read_excel_clean(input_file: str, tabellen_blatt: str, endlines: Optional[int] = None, skiprows=None) -> pd.DataFrame:
    df_gesamt = pd.read_excel(
        input_file,
        sheet_name=tabellen_blatt,
        header=0,
        nrows=endlines,
        skiprows=skiprows,
        dtype=str,
    )
    return df_gesamt


def clean_str(value: Any) -> str:
    """Bereinigt Werte: entfernt Leerzeichen, konvertiert zu String."""
    if pd.isna(value) or value is None:
        return ""
    return str(value).strip()


def create_allowed_values(df: pd.DataFrame) -> set:
    """
    Erstellt die Liste der erlaubten Werte aus den Formeln:
    - "{Klarname}, {Vorname Vater}"
    - "{Klarname}, {Vorname Vater} hausf. {Vorname Mutter}"
    
    Returns:
        Set mit allen eindeutigen erlaubten Werten
    """
    allowed = set()
    
    for idx, row in df.iterrows():
        klarname = clean_str(row.get("Klarname"))
        vorname_vater = clean_str(row.get("Vorname Vater"))
        vorname_mutter = clean_str(row.get("Vorname Mutter"))
        
        if klarname and vorname_vater:
            # Formel 1: "{Klarname}, {Vorname Vater}"
            value1 = f"{klarname}, {vorname_vater}"
            allowed.add(value1)
            
            # Formel 2: "{Klarname}, {Vorname Vater} hausf. {Vorname Mutter}"
            if vorname_mutter:
                value2 = f"{klarname}, {vorname_vater} hausf. {vorname_mutter}"
                allowed.add(value2)
    
    return allowed


def check_pk_columns(df: pd.DataFrame) -> List[Dict]:
    """
    Überprüft die PK1, PK2, PK3 Spalten gegen erlaubte Werte.
    Gibt Liste der Abweichungen zurück.
    """
    # Erstelle Liste erlaubter Werte
    print("PK-Validierung: Erstelle Liste der erlaubten Werte...")
    allowed_values = create_allowed_values(df)
    print(f"  → {len(allowed_values)} eindeutige erlaubte Werte gefunden")
    
    # Sammle Abweichungen
    deviations = []
    
    for idx, row in df.iterrows():
        lnr = clean_str(row.get("LNR")) or f"Index {idx}"
        klarname = clean(row.get("Klarname"))
        vorname_vater = clean(row.get("Vorname Vater"))
        vorname_mutter = clean(row.get("Vorname Mutter"))
        
        # Prüfe jede PK-Spalte
        for pk_col in ["PK1", "PK2", "PK3"]:
            pk_value = clean_str(row.get(pk_col))
            
            # Nur prüfen wenn Wert vorhanden und nicht "V" (= Marker für "nicht gefunden")
            if pk_value and pk_value != "V":
                if pk_value not in allowed_values:
                    # Finde ähnlichsten Wert aus allowed_values
                    close_matches = difflib.get_close_matches(
                        pk_value, 
                        allowed_values, 
                        n=1, 
                        cutoff=0.0  # Keine Mindest-Ähnlichkeit, gib immer den ähnlichsten zurück
                    )
                    expected_value = close_matches[0] if close_matches else ""
                    
                    deviations.append({
                        "LNR": lnr,
                        "Spalte": pk_col,
                        "Wert": pk_value,
                        "Erwarteter_Wert": expected_value,
                        "Klarname": klarname,
                        "Vorname Vater": vorname_vater,
                        "Vorname Mutter": vorname_mutter
                    })
    
    # Ausgabe der Ergebnisse
    if deviations:
        print(f"❌ {len(deviations)} Abweichungen in PK-Spalten gefunden:")
        print(f"{'LNR':<10} {'Spalte':<8} {'Abweichender Wert':<50}")
        print("=" * 70)
        
        for dev in deviations[:10]:  # Nur erste 10 anzeigen
            print(f"{dev['LNR']:<10} {dev['Spalte']:<8} {dev['Wert']:<50}")
        
        if len(deviations) > 10:
            print(f"... und {len(deviations) - 10} weitere")
        
        # Exportiere Abweichungen in CSV
        df_deviations = pd.DataFrame(deviations)
        output_file = "assets/pk_abweichungen.csv"
        df_deviations.to_csv(output_file, index=False, encoding='utf-8-sig', sep=';')
        print(f"\n✅ Alle Abweichungen wurden in '{output_file}' exportiert")
    else:
        print("✅ PK-Validierung erfolgreich: Keine Abweichungen gefunden!")
    
    return deviations

# -------------------------
# Konstanten
# -------------------------

HEADER = f"""0 HEAD
1 SOUR {get_header_version()}
2 VERS {__version__}
2 NAME pxtg Dialect {{}}
1 DATE {{}}
2 TIME {{}}
1 SUBM @SUBM@
1 GEDC
2 VERS 5.5.1
2 FORM LINEAGE-LINKED
1 CHAR UTF-8
1 LANG English
0 @SUBM@ SUBM
1 NAME {{}} /{{}}/"""

TRAILER = "0 TRLR"

reposTXT = """0 @REPO1@ REPO
1 NAME Genealogische Arbeitsgemeinschaft Lahn-Dill-Kreis e.V. - ARCHIV
1 ADR1 Kirchberg 12
1 CITY Mittenaar-Offenbach
1 STAE Hessen
1 POST 35766
1 CTRY Deutschland
1 EMAIL info@genealogie-lahndill.de
1 WWW https://genealogie-lahndill.de/
0 @REPO2@ REPO
1 NAME Stadtarchiv Wetzlar
1 ADR1 Historisches Archiv der Stadt Wetzlar
1 ADR2 Hauser Gasse 17
1 CITY Wetzlar
1 STAE Hessen
1 POST 35578
1 CTRY Deutschland
1 PHON +49 06441 99-1081
1 EMAIL christoph.franke@wetzlar.de
1 WWW https://www.wetzlar.de/vv/oe/188010100000023286.php
0 @REPO3@ REPO
1 NAME Evangelische Kirche im Rheinland - Archivstelle Boppard
1 ADR1 Dr. Andreas Metzing - Archivleiter
1 ADR2 Mainzer Straße 8
1 CITY Boppard
1 STAE Rheinland-Pfalz
1 POST 56154
1 CTRY Deutschland
1 PHON +49 6742 86194
1 EMAIL archivstelle.boppard@ekir.de
1 WWW https://www.archiv-ekir.de/index.php
0 @REPO4@ REPO
1 NAME TNG Datenbestand Hans-Jürgen Koob
1 ADR1 Helgenstraße 7
1 CITY Solms-Burgsolms
1 STAE Hessen
1 POST 35606
1 CTRY Deutschland
1 WWW www.koob-solms.de
"""

sourcesTXT = """0 @S1@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 Gb Hb Sb 1613-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 Gb Hb Sb 1613-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599946; Aufnahmengruppen-Nummer (DGS) 102779709
1 REPO @REPO2@
0 @S2@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599704; Aufnahmengruppen-Nummer (DGS) 102779699
1 REPO @REPO2@
0 @S3@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599705; Aufnahmengruppen-Nummer (DGS) 102779700
1 REPO @REPO2@
0 @S4@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599706; Aufnahmengruppen-Nummer (DGS) 102779701
1 REPO @REPO2@
0 @S5@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599707; Aufnahmengruppen-Nummer (DGS) 102779702
1 REPO @REPO2@
0 @S6@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599708; Aufnahmengruppen-Nummer (DGS) 102779703
1 REPO @REPO2@
0 @S7@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599835; Aufnahmengruppen-Nummer (DGS) 102779704
1 REPO @REPO2@
0 @S8@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599836; Aufnahmengruppen-Nummer (DGS) 102779705
1 REPO @REPO2@
0 @S9@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599836; Aufnahmengruppen-Nummer (DGS) 102779706
1 REPO @REPO2@
0 @S10@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599838; Aufnahmengruppen-Nummer (DGS) 102779707
1 REPO @REPO2@
0 @S11@ SOUR
1 TITL Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798
1 ABBR Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798
1 AUTH Mikrofilme aufgenommen von Manuskripten im Historischen Archiv der Stadt Wetzlar.
1 PUBL FamilySearch; Film 1599945; Aufnahmengruppen-Nummer (DGS) 102779708
1 REPO @REPO2@
0 @S12@ SOUR
1 TITL Wetzlar Kirchenbuch Geburten/Taufen 1571-1613 lutherisch
1 ABBR Wetzlar KbGb 1571-1613 lutherisch
1 AUTH Evangelische Kirchengemeinde
1 REPO @REPO3@
2 CALN 408/1
1 TEXT Kompletter Kirchenbuchbestand auch auf Mikrofiches vorhanden!
0 @S13@ SOUR
1 TITL Wetzlar Kirchenbuch Heiraten 1564-1590 lutherisch
1 ABBR Wetzlar KbHb 1564-1590 lutherisch
1 AUTH Evangelische Kirchengemeinde
1 REPO @REPO3@
2 CALN 408/1
1 TEXT Kompletter Kirchenbuchbestand auch auf Mikrofiches vorhanden!
0 @S15@ SOUR
1 TITL Wetzlar Kirchenbuch Geburten 1614-1687 lutherisch
1 ABBR Wetzlar KbGb 1614-1687 lutherisch
1 AUTH Evangelische Kirchengemeinde
1 REPO @REPO3@
2 CALN 408/2
1 TEXT Kompletter Kirchenbuchbestand auch auf Mikrofiches vorhanden!
0 @S36@ SOUR
1 TITL Wetzlar Kirchenbuch Sterbefälle 1613-1693 lutherisch
1 ABBR Wetzlar KbSb 1613-1693 lutherisch
1 AUTH Evangelische Kirchengemeinde
1 REPO @REPO3@
2 CALN 408/20
1 TEXT Kompletter Kirchenbuchbestand auch auf Mikrofiches vorhanden!
"""

source_to_id = {

    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 Gb Hb Sb 1613-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831": "S1",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611": "S2",    
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632": "S3", 
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670": "S4",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695": "S5",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718": "S6",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734": "S7",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746": "S8",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761": "S9",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780": "S10",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798": "S11",
    "WETZLAR KbGb 1571-1613 lutherisch": "S12",
    "Wetzlar KbHb 1564-1590 lutherisch": "S13",
    "WETZLAR KbGb 1614-1687 lutherisch": "S15",
    "Wetzlar KbSb 1613-1693 lutherisch": "S36",
}

source_to_media_path_gramps = {

    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 Gb Hb Sb 1613-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831": "S1",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1564-1611\\Wetzlar Kirchenbuchkartei Gb 1564-1611\\",    
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1611-1632\\Wetzlar Kirchenbuchkartei Gb 1611-1632\\", 
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1633-1670\\Wetzlar Kirchenbuchkartei Gb 1633-1670\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1671-1695\\Wetzlar Kirchenbuchkartei Gb 1671-1695\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1695-1718\\Wetzlar Kirchenbuchkartei Gb 1695-1718\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1718-1734\\Wetzlar Kirchenbuchkartei Gb 1718-1734\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1735-1746\\Wetzlar Kirchenbuchkartei Gb 1735-1746\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1746-1761\\Wetzlar Kirchenbuchkartei Gb 1746-1761\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1761-1780\\Wetzlar Kirchenbuchkartei Gb 1761-1780\\",
    "Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798": "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1780-1798\\Wetzlar Kirchenbuchkartei Gb 1780-1798\\",
    "WETZLAR KbGb 1571-1613 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1571-1613 lutherisch - klein\\",
    "Wetzlar KbHb 1564-1590 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbHb 1564-1590 lutherisch - klein\\",
    "Wetzlar KbSb 1613-1693 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbSb 1613-1693 lutherisch - klein\\",
    "WETZLAR KbGb 1614-1687 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1614-1687 lutherisch - klein\\",
    "WETZLAR KbGb 1688-1744 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1688-1744 lutherisch - klein\\",
    "WETZLAR KbGb 1745-1810 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1745-1810 lutherisch - klein\\",
    "WETZLAR KbGb 1811-1820 lutherisch": "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1811-1820 lutherisch - klein\\",
}

media_id_to_source = {

    "F0000001" : "Hb Sb 161 Wetzlar Kirchenbuchkartei Gb Hb Sb 1798-1831 3-1798 (unsortiert) Ortsregister (nach Hauptstädten) Gb, Hb, Sb 1564-1831",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1564-1611",    
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1611-1632", 
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1633-1670",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1671-1695",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1695-1718",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1718-1734",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1735-1746",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1746-1761",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1761-1780",
    "F0000001" : "Wetzlar Kirchenbuchkartei Gb Hb Sb 1780-1798",
    # EKiR-IDs mit Buchtyp-Suffix (Gb/Hb/Sb) um Dopplungen zu vermeiden
    "EKiR_408_001_Gb" : "WETZLAR KbGb 1571-1613 lutherisch",
    "EKiR_408_001_Hb" : "Wetzlar KbHb 1564-1590 lutherisch",
    "EKiR_408_020_Sb" : "Wetzlar KbSb 1613-1693 lutherisch",
    "EKiR_408_002_Gb" : "WETZLAR KbGb 1614-1687 lutherisch",
    "EKiR_408_003_Gb" : "WETZLAR KbGb 1688-1744 lutherisch",
    "EKiR_408_004_Gb" : "WETZLAR KbGb 1745-1810 lutherisch",
    "EKiR_408_005_Gb" : "WETZLAR KbGb 1811-1820 lutherisch",
}

# -------------------------
# Utils / Date conversion
# -------------------------
EMPTY = "$"

# German month names mapping
MONTHS_DE = {
    "januar": "1",
    "jan": "1",
    "februar": "2",
    "feb": "2",
    "märz": "3",
    "mär": "3",
    "april": "4",
    "apr": "4",
    "mai": "5",
    "juni": "6",
    "jun": "6",
    "juli": "7",
    "jul": "7",
    "august": "8",
    "aug": "8",
    "september": "9",
    "sep": "9",
    "oktober": "10",
    "okt": "10",
    "november": "11",
    "nov": "11",
    "dezember": "12",
    "dez": "12",
}


def my_upper(to_convert: str) -> str:
    """Format ß in UPPERCASE as ß (not SS)."""
    return to_convert.strip().replace("ß", "ẞ").upper().replace("ẞ", "ß")


def get_common_date(gebdat: Optional[str], taufdat: Optional[str]) -> Optional[str]:
    return clean(taufdat) or clean(gebdat)


def get_common_place(gebort: Optional[str], taufort: Optional[str]) -> Optional[str]:
    return clean(taufort) or clean(gebort)


def clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip()
    if v.lower() == "nan" or v == "" or v == EMPTY:
        return None
    return v

def wrap_note(text: str, linelength: int = 80) -> List[str]:
    """
    Wrap note text into lines of maximum length for GEDCOM output.
    Returns a list of lines: [first_line, cont_line1, cont_line2, ...]
    """
    if len(text) <= linelength:
        return [text]
    
    lines = []
    # First line
    lines.append(text[:linelength])
    # Remaining text in chunks
    remaining = text[linelength:]
    while remaining:
        chunk = remaining[:linelength]
        lines.append(chunk)
        remaining = remaining[linelength:]
    
    return lines

def monthnum_to_name(monthnum: str) -> str:
    try:
        m = int(monthnum)
        return datetime(2000, m, 1).strftime("%b")
    except Exception:
        return monthnum

def convert_date(raw_date: Optional[str]) -> Optional[str]:
    if raw_date is None:
        return None
    s = str(raw_date).strip()
    if s == "" or s.lower() == "nan":
        return None

    # Preserve EST-prefixed dates like "EST 1234" (various casings and optional dot/sep)
    m = re.match(r"^\s*(?:EST|EST\.)\s*[:\-]?\s*(\d{3,4})\s*$", s, re.IGNORECASE)
    if m:
        return f"EST {m.group(1)}"

    # ISO yyyy-mm-dd or yyyy/mm/dd
    m = re.match(r"^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*$", s)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{d} {monthnum_to_name(mo)} {y}"
    # XX.mm.yyyy (unknown day, known month and year) -> "MON yyyy"
    m = re.match(r"^\s*XX?[.\-/ ]+(\d{1,2})[.\-/ ]+(\d{4})\s*$", s, re.IGNORECASE)
    if m:
        mo, y = m.group(1).zfill(2), m.group(2)
        return f"{monthnum_to_name(mo)} {y}"
    # dd.mm.yyyy or d.m.yyyy
    m = re.match(r"^\s*(\d{1,2})[.\-/ ]+(\d{1,2})[.\-/ ]+(\d{4})\s*$", s)
    if m:
        d, mo, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        return f"{d} {monthnum_to_name(mo)} {y}"
    # dd Month yyyy (German/English)
    m = re.match(r"^(\d{1,2})\s+([A-Za-zäöüÄÖÜß]+)\s+(\d{4})$", s)
    if m:
        d, mon, y = m.group(1).zfill(2), m.group(2).lower(), m.group(3)
        if mon in MONTHS_DE:
            return f"{d} {monthnum_to_name(MONTHS_DE[mon])} {y}"
        try:
            dt = datetime.strptime(f"{d} {mon} {y}", "%d %B %Y")
            return dt.strftime("%d %b %Y")
        except Exception:
            pass
    # year-only (also matches years inside strings)
    m = re.search(r"(\d{4})", s)
    if m:
        return m.group(1)
    return s


def print_families(df: pd.DataFrame, max_families: int = 3) -> None:
    """Print overview of first N families from dataframe grouped by GROUP_BY."""
    grouped = df.groupby(FamilyDataBuilder.GROUP_BY)
    print(f"\n=== Erste {max_families} Familien ===\n")
    
    for idx, (group_name, df_group) in enumerate(grouped):
        if idx >= max_families:
            break
        
        est_birth_year = get_fam_est_marr_year(df_group)
        
        # collect children names
        kinder_namen = []
        for _, row in df_group.iterrows():
            vorname = clean(row.get("Vorname Täufling"))
            if vorname:
                kinder_namen.append(vorname)
        
        print(f"Familie {idx + 1}:")
        print(f"  Gruppe: {group_name}")
        print(f"  Geschätztes frühestes Geburtsjahr (Kinder): {est_birth_year}")
        print(f"  Anzahl Kinder: {len(df_group)}")
        print(f"  Kinder: {', '.join(kinder_namen)}")
        print()


def get_fam_est_marr_year(df_group: pd.DataFrame) -> Optional[int]:
    """Estimate earliest child birth year from a family group."""
    birth_years: List[int] = []
    for _, row in df_group.iterrows():
        for datecol in ["Datum Geburt", "Datum Taufe"]:
            if datecol in row.index and clean(row.get(datecol)):
                conv = convert_date(clean(row.get(datecol)))
                if conv:
                    try:
                        y = int(str(conv)[-4:])
                        birth_years.append(y)
                    except Exception:
                        pass
    
    return min(birth_years) if birth_years else None


# -------------------------
# Models
# -------------------------
@dataclass
class Citation:
    text: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    quality: Optional[int] = None
    notes: List["Note"] = field(default_factory=list)


@dataclass
class Event:
    type: str
    date: Optional[str] = None
    place: Optional[str] = None
    note: Optional[str] = None
    source: Optional[str] = None
    role: Optional[str] = None
    citations: List[Citation] = field(default_factory=list)


@dataclass
class Person:
    pid: Optional[int] = None
    # Familienverweise: FAMS = als Ehepartner; FAMC = als Kind
    fams: List[int] = field(default_factory=list)
    famc: List[int] = field(default_factory=list)
    firstname: Optional[str] = None
    surname: Optional[str] = None
    sex: Optional[str] = None
    name_prefix: Optional[str] = None
    name_suffix: Optional[str] = None
    nickname: Optional[str] = None
    namevariant: Optional[str] = None
    marriage_name: Optional[str] = None
    godparents: Optional[str] = None
    religion: Optional[str] = None
    common_date: Optional[str] = None
    est_birth_year: Optional[int] = None  # Neues Feld für geschätztes Geburtsjahr
    events: List[Event] = field(default_factory=list)
    occupations: List[Tuple[str, str, str]] = field(default_factory=list)
    residences: List[Tuple[str, str]] = field(default_factory=list)
    name_variants: List[str] = field(default_factory=list)
    vorname_variants: List[str] = field(default_factory=list)
    paten_keys: List[str] = field(default_factory=list)
    paten_keys_pids: List[int] = field(default_factory=list)
    pate: Optional[str] = None
    media_refs: List[str] = field(default_factory=list)
    source: Optional[str] = None
    citation_notes: List["Note"] = field(default_factory=list)


@dataclass
class Family:
    fid: Optional[int] = None
    father: Optional[Person] = None
    mother: Optional[Person] = None
    children: List[Person] = field(default_factory=list)
    est_marr_year: Optional[int] = None


@dataclass
class Note:
    nid: Optional[int] = None
    book_type: Optional[str] = None
    text: Optional[str] = None


@dataclass
class Media:
    oid: Optional[int] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    type: Optional[str] = None


# -------------------------
# Helper functions that depend on models
# -------------------------
def print_families_with_pids(families: List[Family], max_families: int = 3) -> None:
    """Print overview of first N families with PIDs."""
    print(f"\n=== Erste {max_families} Familien (mit PIDs) ===\n")
    
    for idx, fam in enumerate(families[:max_families]):
        n_kinder = len(fam.children)
        est_year = fam.est_marr_year if fam.est_marr_year else "unbekannt"
        
        print(f"Familie {idx + 1} [FID: {fam.fid}] - {n_kinder} Kinder, geschätztes frühestes Geburtsjahr: {est_year}")
        
        if fam.father:
            father_date = fam.father.common_date if fam.father.common_date else "unbekannt"
            father_fams = getattr(fam.father, 'fams', [])
            father_famc = getattr(fam.father, 'famc', [])
            print(f"  Vater: {fam.father.firstname} {fam.father.surname} [PID: {fam.father.pid}] - {father_date}")
            print(f"         FAMS: {father_fams}, FAMC: {father_famc}")
        
        if fam.mother:
            mother_date = fam.mother.common_date if fam.mother.common_date else "unbekannt"
            mother_fams = getattr(fam.mother, 'fams', [])
            mother_famc = getattr(fam.mother, 'famc', [])
            print(f"  Mutter: {fam.mother.firstname} {fam.mother.surname} [PID: {fam.mother.pid}] - {mother_date}")
            print(f"         FAMS: {mother_fams}, FAMC: {mother_famc}")
        
        print(f"  Kinder ({n_kinder}):")
        for child in fam.children:
            birth_year = child.common_date if child.common_date else "unbekannt"
            child_fams = getattr(child, 'fams', [])
            child_famc = getattr(child, 'famc', [])
            child_paten = getattr(child, 'paten_keys', [])
            child_paten_pids = getattr(child, 'paten_keys_pids', [])
            
            # Sammle alle Quellen aus citations aller Events
            sources = []
            notes = []
            for event in child.events:
                for citation in event.citations:
                    if citation.source:
                        sources.append(citation.source)
                    if citation.text:
                        sources.append(citation.text)
                    # Sammle Notizen aus den Citations
                    for note in citation.notes:
                        if note.text:
                            notes.append(f"[NID: {note.nid}, {note.book_type}] {note.text[:80]}...")
            sources_str = ", ".join(set(sources)) if sources else "keine Quelle"
            
            print(f"    - {child.firstname} [PID: {child.pid}] - {birth_year} - Quellen: {sources_str}")
            print(f"      FAMS: {child_fams}, FAMC: {child_famc}")
            if child_paten:
                paten_mit_pids = []
                for i, pate in enumerate(child_paten):
                    if i < len(child_paten_pids):
                        paten_mit_pids.append(f"{pate} [PPID: {child_paten_pids[i]}]")
                    else:
                        paten_mit_pids.append(pate)
                print(f"      Paten: {', '.join(paten_mit_pids)}")
            if notes:
                print(f"      Notizen ({len(notes)}):")
                for note_str in notes:
                    print(f"        {note_str}")
        
        print()


# -------------------------
# Plugin base and implementations
# -------------------------
class DialectPlugin:
    def write_person_extra(self, gf: IO[str], person: Person, df_row: Optional[pd.Series]) -> None: ...
    def write_event_extra(self, gf: IO[str], person: Person, event: Event, df_row: Optional[pd.Series]) -> None: ...
    def write_family_extra(self, gf: IO[str], family: Family, df_row: Optional[pd.Series]) -> None: ...
    def get_baptism_tag(self) -> str: return "CHR"
    def get_fmt_media_tag(self) -> str: return "M"
    def handle_notes(self) -> bool: return True  # True = direkt schreiben, False = sammeln für späteren Block
    def handle_media(self) -> bool: return True  # True = TNG gibt 3 OBJE aus
    def handle_sources(self, *args: Any, **kwargs: Any) -> bool:
        """Generic interface, may be overridden by dialects."""
        return True
    def register_note(self, text: str, book_type: str) -> int:
        """Optional: von GRAMPS-Dialekt implementiert. Basis gibt Dummy zurück."""
        return 0
    def write_note_records(self, writer: "GedcomWriter") -> None:
        """Optional hook for writing NOTE records at the end of the file."""
        pass
    def write_media_records(self, writer: "GedcomWriter") -> None:
        """Optional hook for dialect-specific OBJE records."""
        # default implementation: no special path rewriting
        w = writer.gf.write
        print("PLUGIN at Dialect :")
        for filepath, mid in writer.media_registry.items():
            meta = writer.media_meta.get(mid, {})
            w(f"0 {writer._fmt_mid(mid)} OBJE\n")
            if meta.get("FORM"):
                w(f"1 FORM {meta['FORM']}\n")
            w(f"1 FILE {meta.get('FILE')}\n")
            if meta.get("TITL"):
                w(f"1 TITL {meta['TITL']}\n")
            if meta.get("_TYPE"):
                w(f"1 _TYPE {meta.get('_TYPE')}\n")



class TNGPlugin(DialectPlugin):

    TNG_MEDIA_PATH_KB = "/tng_koob-solms_de/Kirchenbuchseiten/"
    TNG_MEDIA_PATH_KK = "/tng_koob-solms_de/Wetzlarkartei/"

    def get_baptism_tag(self) -> str:
        return "CHR"
    
    def get_fmt_media_tag(self) -> str:
        return ""
        
    def handle_notes(self) -> bool:
        return True  # Notes direkt bei Events ausgeben
    
    def handle_media(self) -> bool: 
        return True  # True = TNG gibt 2 OBJE aus
    
    def add_approximated_birth_if_needed(self, person: Person) -> Optional[Event]:
        """
        Erstellt ein approximiertes BIRT-Event für TNG, falls:
        - Kein BIRT-Event existiert
        - Ein Taufe-Event existiert
        
        Returns: Event oder None
        """
        # Hat Person ein BIRT?
        has_birth = any(ev.type == "BIRT" for ev in person.events)
        
        # Hat Person ein Taufe?
        baptism = next((ev for ev in person.events if ev.type == "Taufe"), None)
        
        if not has_birth and baptism:
            # Erstelle approximiertes BIRT aus Taufdatum
            approx_date = f"ABT {baptism.date}" if baptism.date and not baptism.date.startswith("ABT") else baptism.date
            
            # Normalisierter Ort für Wetzlar
            #normalized_wetzlar = ORT_ZU_ORT.get("Wetzlar", "Wetzlar")
            approx_place = "Wetzlar"
            
            # Kopiere Citations vom Taufe-Event (für Quellen und Karteikarten-Abschriften)
            baptism_citations = baptism.citations if baptism.citations else []
            
            # Erstelle Event mit Notiz und Citations
            approximated_birth = Event(
                type="BIRT",
                date=approx_date,
                place=approx_place,
                citations=baptism_citations,  # Übernehme Quellen vom Taufe-Event
                note="Geschätzt aus Taufdatum"
            )
            return approximated_birth
        
        return None
    
    def fmt_note(self, text: str, book_type: str) -> str:
        """Format note text with leader and cleaning."""
        LEADER = f"|Abschrift {'Kirchenbuch' if book_type == 'KB' else 'Karteikarte'}|"
        cleaned = str(clean(text))
        # Entferne alle Arten von Zeilenumbrüchen (Excel Soft-Breaks)
        cleaned = cleaned.replace("\r\n", " ")  # Windows
        cleaned = cleaned.replace("\r", " ")    # Mac
        cleaned = cleaned.replace("\n", " ")    # Unix
        # Entferne mehrfache Leerzeichen
        cleaned = " ".join(cleaned.split())
        cleaned = cleaned.strip()  # Remove leading/trailing whitespace
        return f"{LEADER} {cleaned}"
    
    """
    TNG plugin:
    - Collects media references from df_row or person.media_refs
    - Handles TNG-style inline source lines
    """

    def handle_sources(self, *args: Any, **kwargs: Any) -> bool:
        """
        Handle source blocks for TNG dialect.
        Accepts (writer, source_to_id, person) in practice.
        """
        w, source_to_id, person = args  # unpack dynamically for type checkers
               
        #if person.source and person.source in source_to_id:
        #    try:
        #        w(f"2 SOUR {source_to_id[person.source]}\n")
        #        w("3 DATA\n")
        #        if person.citation_date:
        #            w(f"4 DATE {person.citation_date}\n")
        #        if person.citation:
        #            w(f"3 PAGE {person.citation}\n")
        #        if person.citation_quality is not None:
        #            w(f"3 QUAY {person.citation_quality}\n")
        #    except Exception:
        #        pass
        return True

    def write_media_records(self, writer: "GedcomWriter") -> None:
        w = writer.gf.write
        print("PLUGIN at TNG :")
        for filepath, mid in writer.media_registry.items():
            meta = writer.media_meta.get(mid, {})
            mtype = (meta.get("_TYPE") or "").lower()
            if mtype == "kirchenbuchseiten":
                base = self.TNG_MEDIA_PATH_KB
                erf = ""
            elif mtype == "wetzlarkartei":
                base = self.TNG_MEDIA_PATH_KK
                erf = "_erf"
            else:
                base = ""
                erf = ""
            wrapped = f"{base.rstrip('/')}/{Path(filepath).name}{erf}.jpg" if base else f"{filepath}{erf}.jpg"
            w(f"0 {writer._fmt_mid(mid)} OBJE\n")
            if meta.get("FORM"):
                w(f"1 FORM {meta['FORM']}\n")
            w(f"1 FILE {wrapped}\n")
            if meta.get("TITL"):
                w(f"1 TITL {meta['TITL']}\n")
            if mtype:
                w(f"1 _TYPE {mtype}\n")


       
class GrampsPlugin(DialectPlugin):

    #Die Pfade sind durch ein Dict ersetzt.
    #GRAMPS_MEDIA_PATH_KB = "\\gramps_data\\Kirchenbuchseiten\\"
    #GRAMPS_MEDIA_PATH_KK = "\\gramps_data\\Wetzlarkartei\\"

    #GRAMPS_MEDIA_PATH_KB = "E:\\Wetzlar Kirchenbücher - NAS jpg\\WETZLAR KbGb 1614-1687 lutherisch - klein\\"
    #GRAMPS_MEDIA_PATH_KK = "E:\\Karteikarten\\nextcloud\\Wetzlar Kirchenbuchkartei - Heiraten Geburten Tote 1633-1670\\Wetzlar Kirchenbuchkartei Gb 1633-1670\\"

    def __init__(self):
        self.note_registry: Dict[str, int] = {}  # Text -> NID mapping
        self.next_note_id: int = 1
        
    def get_baptism_tag(self) -> str:
        return "BAPM"
    
    def get_fmt_media_tag(self) -> str:
        return "O"
        
    def handle_notes(self) -> bool:
        return False  # Notes sammeln für NOTE-Block
    
    def handle_media(self) -> bool: 
        return False  # False = GRAMPS gibt 3 OBJE aus
    
    def fmt_note(self, text: str, book_type: str) -> str:
        """Format note text with leader and cleaning."""
        LEADER = f"|Abschrift {'Kirchenbuch' if book_type == 'KB' else 'Karteikarte'}|"
        cleaned = str(clean(text))
        # Entferne alle Arten von Zeilenumbrüchen (Excel Soft-Breaks)
        cleaned = cleaned.replace("\r\n", " ")  # Windows
        cleaned = cleaned.replace("\r", " ")    # Mac
        cleaned = cleaned.replace("\n", " ")    # Unix
        # Entferne mehrfache Leerzeichen
        cleaned = " ".join(cleaned.split())
        cleaned = cleaned.strip()  # Remove leading/trailing whitespace
        return f"{LEADER} {cleaned}"
    
    def register_note(self, text: str, book_type: str) -> int:
        fmt_text = self.fmt_note(text, book_type)
        if fmt_text in self.note_registry:
            return self.note_registry[fmt_text]
        nid = self.next_note_id
        self.next_note_id += 1
        self.note_registry[fmt_text] = nid
        return nid


    def handle_sources(
        self,
        w: Any,
        norm_source: str | None = None,
        c_d: str | None = None,
        c: str | None = None,
        c_q: str | None = None,
    ) -> bool:
        w(f"2 SOUR {norm_source}\n")
        if c:
            w(f"3 PAGE {c}\n")
        if c_d or c_q:
            w("3 DATA\n")
        if c_d:
            w(f"4 DATE {c_d}\n")
        if c_q is not None:
            w(f"3 QUAY {c_q}\n")
        return False

    def write_media_records(self, writer: "GedcomWriter") -> None:
        w = writer.gf.write
        print("PLUGIN at Dialect at GRAMPS :")
        for filepath, mid in writer.media_registry.items():
            meta = writer.media_meta.get(mid, {})
            mtype = (meta.get("_TYPE") or "").lower()
            if mtype == "kirchenbuchseiten":
                # Der Pfad wird durch das Jahresintervall im Dateinamen über zwei dicts bestimmt
                match = re.search(r'(EKiR_\d+_\d+)', filepath)   # "EKiR_408_002"
                if match:
                    # Nutze Buchtyp-Suffix für eindeutiges Lookup (Gb/Hb/Sb)
                    booktype = meta.get("_BOOKTYPE", "")
                    lookup_key = f"{match.group(0)}_{booktype}" if booktype else match.group(0)
                    
                    # Fallback: Versuche erst mit Suffix, dann ohne
                    source_name = media_id_to_source.get(lookup_key)
                    if not source_name:
                        source_name = media_id_to_source.get(match.group(0))
                    
                    base = source_to_media_path_gramps.get(source_name, "") if source_name else ""
                else:
                    base = ""
                erf = ""
                wrapped = f"{base.rstrip(chr(92))}{chr(92)}{Path(filepath).name}{erf}.jpg" if base else filepath
            elif mtype == "wetzlarkartei":
                # Der Pfad wird durch das Jahresintervall im Dateinamen über das dict bestimmt
                match = re.search(r'(\d{4})-(\d{4})', filepath)   # 1671-1695
                if match:
                    base = source_to_media_path_gramps[f"Wetzlar Kirchenbuchkartei Gb Hb Sb {match.group(0)}"]
                else:
                    base = ""
                erf = "_erf"
            else:
                base = "+"
            
            wrapped = f"{base.rstrip(chr(92))}{chr(92)}{Path(filepath).name}{erf}.jpg" if base else f"{filepath}{erf}.jpg"
            #print("WR ",filepath[-10:], wrapped)

            w(f"0 {writer._fmt_mid(mid)} OBJE\n")
            if meta.get("FORM"):
                w(f"1 FORM {meta['FORM']}\n")
            w(f"1 FILE {wrapped}\n")
            if meta.get("TITL"):
                w(f"1 TITL {meta['TITL']}\n")
    
    def write_note_records(self, writer: "GedcomWriter") -> None:
        """Write all collected NOTE records at the end of the file."""
        w = writer.gf.write
        print(f"Writing {len(self.note_registry)} NOTE records...")
        # note_registry ist Dict[str, int] (Text -> NID)
        # Wir müssen umdrehen zu NID -> Text
        nid_to_text: Dict[int, str] = {nid: text for text, nid in self.note_registry.items()}
        
        for nid in sorted(nid_to_text.keys()):
            text = nid_to_text[nid]
            # GEDCOM 5.5.1: Zeilen maximal 255 Zeichen, bei längeren Texten CONC verwenden
            # Umbruch bei konfigurierter Länge für bessere Lesbarkeit
            lines = wrap_note(text, linelength=writer.wrap_length)
            
            # Erste Zeile als NOTE
            w(f"0 {writer._fmt_nid(nid)} NOTE {lines[0]}\n")
            
            # Weitere Zeilen als CONC
            for line in lines[1:]:
                w(f"1 CONC {line}\n")

# -------------------------
# GedcomWriter with dedupe and M2 media records
# -------------------------
class GedcomWriter:
    def __init__(self, gf: IO[str], plugin: Optional[DialectPlugin], dialect: str = "TNG", start_media_id: int = 201000) -> None:
        self.gf: IO[str] = gf
        self.next_pid: int = 1
        self.next_fid: int = 1
        self.next_nid: int = 1
        self.next_mid: int = start_media_id
        self.wrap_length: int = 80  # Default wrap length for notes
        self.include_repos: bool = False  # REPO records flag (not for TNG)
        self.include_sources: bool = True  # SOURCES records flag (default enabled)
        if plugin:
            self.plugin = plugin
        else:
            self.plugin = TNGPlugin() if dialect.upper() == "TNG" else GrampsPlugin()

        # Paten-Dictionary
        self.paten_dict: Dict[str, int] = {}
        
        # Unbekannte Orte sammeln
        self.unknown_places: Set[str] = set()
        
        # Media registry
        self.media_registry: Dict[str, int] = {}  # filepath -> MID
        self.media_meta: Dict[int, Dict[str, str]] = {}  # MID -> metadata
    
    def _get_next_pid(self) -> int:
        """Vergebe nächste Person-ID."""
        pid = self.next_pid
        self.next_pid += 1
        return pid
    
    def _get_next_fid(self) -> int:
        """Vergebe nächste Familien-ID."""
        fid = self.next_fid
        self.next_fid += 1
        return fid
    
    def _get_next_nid(self) -> int:
        """Vergebe nächste Notiz-ID."""
        nid = self.next_nid
        self.next_nid += 1
        return nid
    
    def _get_next_mid(self) -> int:
        """Vergebe nächste Medien-ID."""
        mid = self.next_mid
        self.next_mid += 1
        return mid
    
    def _fmt_pid(self, pid: int) -> str:
        """Formatiere Person-ID für GEDCOM."""
        if isinstance(self.plugin, GrampsPlugin):
            return f"@I{pid:06d}@"
        return f"@I{pid}@"
    
    def _fmt_fid(self, fid: int) -> str:
        """Formatiere Familien-ID für GEDCOM."""
        if isinstance(self.plugin, GrampsPlugin):
            return f"@F{fid:06d}@"
        return f"@F{fid}@"
    
    def _fmt_sid(self, sid: str) -> str:
        """Formatiere Quellen-ID für GEDCOM."""
        # sid kommt bereits mit "S" prefix (z.B. "S15")
        return f"@{sid}@"
    
    def _fmt_nid(self, nid: int) -> str:
        """Formatiere Notizen-ID für GEDCOM."""
        if isinstance(self.plugin, GrampsPlugin):
            return f"@N{nid:06d}@"
        return f"@N{nid}@"
    
    def _fmt_mid(self, mid: int) -> str:
        """Formatiere Medien-ID für GEDCOM."""
        if isinstance(self.plugin, GrampsPlugin):
            return f"@O{mid:06d}@"
        return f"@{mid}@"
    
    def register_media(self, filepath: str, form: str = "JPG", title: Optional[str] = None, mtype: Optional[str] = None, source: Optional[str] = None) -> int:
        """Registriere Mediendatei und gib MID zurück."""
        if filepath in self.media_registry:
            return self.media_registry[filepath]
        mid = self._get_next_mid()
        
        # Extrahiere Buchtyp (Gb/Hb/Sb) aus QUELLE für GRAMPS-Pfadauflösung
        booktype = ""
        if source:
            if "KbGb" in source or "Geburten" in source:
                booktype = "Gb"
            elif "KbHb" in source or "Heiraten" in source:
                booktype = "Hb"
            elif "KbSb" in source or "Sterbe" in source or "Tote" in source:
                booktype = "Sb"
        
        self.media_registry[filepath] = mid
        self.media_meta[mid] = {
            "FILE": filepath,
            "FORM": form,
            "TITL": title or filepath,
            "_TYPE": mtype or "unknown",
            "_BOOKTYPE": booktype,
        }
        return mid
    
    def write_header(self) -> None:
        self.gf.write(
            HEADER.format(
                globals().get("DIALECT", "TNG"),
                datetime.now(tz=ZoneInfo("Europe/Berlin")).strftime("%d %b %Y").upper(),
                datetime.now(tz=ZoneInfo("Europe/Berlin")).strftime("%H:%M:%S"),
                globals().get("SUBMITTER_FIRSTNAME", ""),
                globals().get("SUBMITTER_LASTNAME", ""),
            )
            + "\n"
        )
    
    def write_sources(self) -> None:
        self.gf.write(sourcesTXT)

    def write_repos(self) -> None:
        """Write REPO records (only for GRAMPS)."""
        if isinstance(self.plugin, GrampsPlugin):
            self.gf.write(reposTXT)

    def write_media_records(self) -> None:
        """Write OBJE records via plugin."""
        self.plugin.write_media_records(self)

    def write_trailer(self) -> None:
        self.gf.write(TRAILER + "\n")
    
    def _write_person_block(self, person: Person) -> None:
        w = self.gf.write
        if person.pid is None:
            raise ValueError(f"Person without PID: {person.firstname} {person.surname}")
        w(f"0 {self._fmt_pid(person.pid)} INDI\n")
        name_line = ((person.firstname or "VN") + " /" + (my_upper(person.surname.strip()) if person.surname else "NN") + "/")
        w(f"1 NAME {name_line.strip()}\n")
        if person.firstname:
            w(f"2 GIVN {person.firstname.strip()}\n")
        if person.surname:
            w(f"2 SURN {my_upper(person.surname.strip())}\n")
        if person.name_suffix:
            w(f"2 NSFX {person.name_suffix.strip()}\n")
        if person.nickname:
            w(f"2 NICK {person.nickname.strip()}\n")
        if person.name_prefix:
            w(f"2 SPFX {person.name_prefix.strip()}\n")
        if person.marriage_name:
            if isinstance(self.plugin, TNGPlugin):
                w(f"1 _MARNM {my_upper(person.marriage_name)}\n")
            else:
                # GRAMPS: _MARN instead of _MARNM
                if person.common_date:
                    w(f"2 _MARN {my_upper(person.marriage_name)}\n")
                    match = re.search(r'EST\s+(\d{4})', person.common_date)
                    if match:
                        w(f"3 DATE {int(match.group(1)) + 15}\n")
        if person.sex:
            w(f"1 SEX {person.sex}\n")
        # Familienreferenzen innerhalb des INDI-Blocks ausgeben
        for fid in getattr(person, "fams", []):
            w(f"1 FAMS {self._fmt_fid(fid)}\n")
        for fid in getattr(person, "famc", []):
            w(f"1 FAMC {self._fmt_fid(fid)}\n")
        # Paten-Beziehungen (ASSO) innerhalb des INDI-Blocks, falls vorhanden
        if getattr(person, "paten_keys", None):
            for pk in person.paten_keys_pids:
                w(f"1 ASSO {self._fmt_pid(pk)}\n")
                w("2 RELA Pate\n")
        if isinstance(self.plugin, TNGPlugin):
            self.plugin.handle_sources(w, source_to_id, person)

        # TNG-spezifisch: Füge approximiertes BIRT hinzu wenn nötig
        events_to_write = person.events
        if isinstance(self.plugin, TNGPlugin):
            approximated_birth = self.plugin.add_approximated_birth_if_needed(person)
            if approximated_birth:
                # Temporär in events einfügen (nur für Ausgabe)
                events_to_write = [approximated_birth] + person.events

        # events
        order = ["BIRT", "Taufe", "DEAT", "OCCU", "RESI"]
        for evtype in order:
            for ev in events_to_write:
                if ev.type == evtype:
                    if ev.type == "BIRT":
                        w("1 BIRT\n")
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)

                        # MARR event with estimated date
                        if person.est_birth_year:
                            w("2 NOTE {Geburt erstes Kind}\n")


                    elif ev.type == "Taufe":
                        w(f"1 {self.plugin.get_baptism_tag()}\n")  # CHR oder BAPM je nach Plugin
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)
                    elif ev.type == "DEAT":
                        w("1 DEAT\n")
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)
                    elif ev.type == "BAPM":
                        w("1 BAPM\n")
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)
                        if ev.role:
                            w(f"2 ROLE {ev.role}\n")
                    elif ev.type == "OCCU":
                        w(f"1 OCCU {ev.note}\n")
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)
                    elif ev.type == "RESI":
                        w("1 RESI\n")
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)
                    else:
                        w(f"1 {ev.type}\n")
                        if ev.date:
                            w(f"2 DATE {ev.date}\n")
                        if ev.place:
                            normalized_place = ORT_ZU_ORT.get(ev.place)
                            if normalized_place:
                                w(f"2 PLAC {normalized_place}\n")
                            else:
                                w(f"2 PLAC {ev.place}\n")
                                self.unknown_places.add(ev.place)
                    
                    # Citations durchlaufen
                    for citation in ev.citations:
                        if citation.source and citation.source in source_to_id:
                            try:
                                w(f"2 SOUR {self._fmt_sid(source_to_id[citation.source])}\n")
                                if citation.text or citation.date or citation.quality:
                                    w("3 DATA\n")
                                if citation.date:
                                    w(f"4 DATE {citation.date}\n")
                                if citation.text:
                                    w(f"3 PAGE {citation.text}\n")
                                if citation.quality is not None:
                                    w(f"3 QUAY {citation.quality}\n")
                            except Exception:
                                pass
                        
                        # Notes aus der Citation
                        for n in citation.notes:
                            if n.nid is not None:
                                if self.plugin.handle_notes():
                                    #if (n.book_type == 'KB' and ev.type == 'Taufe') or (n.book_type == 'KK' and ev.type == 'BIRT'):
                                    if (n.book_type == 'KB' and ev.type == 'Taufe') or (n.book_type == 'KK' and ev.type == 'BIRT' and ev.date and not ev.date.startswith("EST")):
                                        # TNG: direkt ausgeben mit Zeilenumbruch
                                        note_text = n.text or ''
                                        lines = wrap_note(note_text, linelength=self.wrap_length)
                                        
                                        # Erste Zeile als NOTE
                                        w(f"2 NOTE {lines[0]}\n")
                                        
                                        # Weitere Zeilen als CONC
                                        for line in lines[1:]:
                                            w(f"3 CONC {line}\n")
                                else:
                                    # GRAMPS: nur Referenz ausgeben
                                    w(f"3 NOTE {self._fmt_nid(n.nid)}\n")

                        # media refs
                        for mp in person.media_refs:
                            # Heuristik: Erkenne Medientyp anhand Dateiname
                            # F102... = Karteikarte, EKiR_... oder andere = Kirchenbuchseite
                            if "F102" in mp:
                                mtype = "Wetzlarkartei"
                            elif "EKiR" in mp or "Gb" in mp or "Hb" in mp or "Sb" in mp:
                                mtype = "Kirchenbuchseiten"
                            else:
                                mtype = "unknown"
                            # Übergebe citation.source für Buchtyp-Extraktion (Gb/Hb/Sb)
                            mid = self.register_media(mp, form='JPG', title=mp, mtype=mtype, source=citation.source)

                            if self.plugin.handle_media():
                                # TNG: anderer Text
                                if ev.type == 'Taufe':
                                    w(f"2 OBJE {self._fmt_mid(mid)}\n")
                            else:
                                # GRAMPS: anderer Text
                                w(f"3 OBJE {self._fmt_mid(mid)}\n")
                    
                    # Notiz für approximiertes BIRT (nur TNG) - nach allen Citations
                    if ev.type == "BIRT" and hasattr(ev, 'note') and ev.note:
                        w(f"2 NOTE {ev.note}\n")


                            
        # godparents as text
        if person.godparents:
            if isinstance(self.plugin, TNGPlugin):
                # TNG: _GODP tag with full text
                w(f"1 _GODP {person.godparents}\n")
                w("2 NOTE {Taufpaten nicht als Personen angelegt}\n")
            else:
                # GRAMPS: Split by ";" and write individual FACT/TYPE PATE
                godparent_list = [g.strip() for g in person.godparents.split(";") if g.strip()]
                for g in godparent_list:
                    w(f"1 FACT {g}\n")
                    w("2 TYPE PATE\n")
        # religion
        if person.religion:
            w(f"1 RELI {person.religion}\n")
            if person.common_date:
                w(f"2 DATE {person.common_date}\n")
            
            # Add source citation for TNG (GRAMPS gets it via events)
            if isinstance(self.plugin, TNGPlugin):
                # Find first event with citation (usually birth or baptism)
                for ev in person.events:
                    if ev.citations:
                        citation = ev.citations[0]
                        if citation.source and citation.source in source_to_id:
                            w(f"2 SOUR {self._fmt_sid(source_to_id[citation.source])}\n")
                            if citation.text or citation.date or citation.quality:
                                w("3 DATA\n")
                            if citation.date:
                                w(f"4 DATE {citation.date}\n")
                            if citation.text:
                                w(f"3 PAGE {citation.text}\n")
                            if citation.quality is not None:
                                w(f"3 QUAY {citation.quality}\n")
                        break  # Only use first citation
        # name variants
        for namevariant in person.name_variants:
            name_line = ((person.firstname or "") + " / " + (namevariant or "") + " (Namensvariante) /")
            w(f"1 NAME {name_line.strip()}\n")
        try:
            self.plugin.write_person_extra(self.gf, person, None)
        except Exception:
            pass
    
    def _write_family_block(self, family: Family) -> None:
        """Write FAM record with HUSB, WIFE, CHIL and MARR event."""
        w = self.gf.write
        if family.fid is None:
            raise ValueError(f"Family without FID")
        w(f"0 {self._fmt_fid(family.fid)} FAM\n")
        
        # HUSB (father)
        if family.father and family.father.pid:
            w(f"1 HUSB {self._fmt_pid(family.father.pid)}\n")
        
        # WIFE (mother)
        if family.mother and family.mother.pid:
            w(f"1 WIFE {self._fmt_pid(family.mother.pid)}\n")
        
        # CHIL (children)
        for child in family.children:
            if child.pid:
                w(f"1 CHIL {self._fmt_pid(child.pid)}\n")
                w("2 _FREL Birth\n")
                w("2 _MREL Birth\n")
        
        # MARR event with estimated date
        if family.est_marr_year:
            w("1 MARR\n")
            w(f"2 DATE EST {family.est_marr_year}\n")
            w("2 TYPE RELI\n")
            w("2 NOTE {Geburt erstes Kind}\n")

    

# -------------------------
# FamilyDataBuilder
# -------------------------
class FamilyDataBuilder:
    GROUP_BY = ["Klarname", "Vorname Vater", "Vorname Mutter"]


# -------------------------
# DataTests - Validate data consistency
# -------------------------
class DataTests:
    @staticmethod
    def test_data(df: pd.DataFrame, sources: Dict[str, str]) -> None:
        """
        Test if Karteikarte year is within QUELLE interval.
        
        Example:
        - Karteikarte: "1336 Gb 1681 - 1671-1695 - F102779702"
        - QUELLE: "Wetzlar Kirchenbuchkartei Gb 1671-1695"
        - Extract year 1681 from Karteikarte and check if 1671 <= 1681 <= 1695
        
        Args:
            df: DataFrame with columns 'Karteikarte' and 'QUELLE'
            sources: Dictionary mapping source names to IDs (not used currently)
        """
        print("\n=== Testing Karteikarte Year vs QUELLE Interval ===")
        failures = []
        
        for idx, row in df.iterrows():
            karteikarte = clean(row.get("Karteikarte"))
            quelle = clean(row.get("QUELLE Kartei"))
            
            if not karteikarte or not quelle:
                continue
            
            # Extract year from Karteikarte (e.g., "1336 Gb 1681 - 1671-1695")
            # Pattern: Karteikarten-Nr (4 digits), "Gb", dann das eigentliche Jahr (4 digits)
            # We want the SECOND 4-digit year (the actual year, not the card number)
            karte_match = re.search(r'\bGb\s+(\d{4})\b', karteikarte)
            if not karte_match:
                continue
            
            karte_year = int(karte_match.group(1))
            
            # Extract year interval from QUELLE (e.g., "... Gb 1671-1695")
            # Pattern: 4-digit year - 4-digit year
            quelle_match = re.search(r'\b(1[4-9]\d{2})[-–](1[4-9]\d{2})\b', quelle)
            if not quelle_match:
                continue
            
            quelle_start = int(quelle_match.group(1))
            quelle_end = int(quelle_match.group(2))
            
            # Test if karte_year is within quelle interval
            if not (quelle_start <= karte_year <= quelle_end):
                row_num = int(idx) + 2 if isinstance(idx, (int, float)) else 0  # +2 because Excel is 1-indexed and has header row
                failures.append({
                    'row': row_num,
                    'karteikarte': karteikarte,
                    'karte_year': karte_year,
                    'quelle': quelle,
                    'quelle_start': quelle_start,
                    'quelle_end': quelle_end
                })
        
        # Report results
        if failures:
            print(f"\n❌ FAILED: {len(failures)} rows with year mismatch:\n")
            print(f"{'Row':<6} {'Karte Year':<12} {'Quelle Interval':<18} {'Karteikarte':<50} {'QUELLE'}")
            print("-" * 140)
            for f in failures:
                interval = f"{f['quelle_start']}-{f['quelle_end']}"
                karte_str = str(f['karteikarte'])[:48] if f['karteikarte'] else ""
                print(f"{f['row']:<6} {f['karte_year']:<12} {interval:<18} {karte_str:<50} {f['quelle']}")
        else:
            print("✅ PASSED: All Karteikarte years are within QUELLE intervals")
        
        print(f"\nTotal rows checked: {len(df)}")
        print(f"Failed rows: {len(failures)}\n")
    
    @staticmethod
    def test_unknown_places(unknown_places: Set[str]) -> None:
        """
        Print unknown places that are not in ORT_ZU_ORT normalization.
        
        Args:
            unknown_places: Set of place names that were not found in ORT_ZU_ORT
        """
        # Filter nur strings (keine NaN/None)
        str_places = {p for p in unknown_places if isinstance(p, str)}
        if str_places:
            print(f"\n=== Unbekannte Orte ({len(str_places)}) ===")
            for place in sorted(str_places):
                print(f"  - {place}")
        else:
            print("\n✅ All places are normalized")


# -------------------------
# Constants for Note mapping
# -------------------------
NOTE_TYPE_MAP: Dict[str, str] = {
    "Kirchenbucheintrag": "KB",
    "Karteikartentext": "KK",
}


# -------------------------
# Top-level make_gedcom
# -------------------------
'''
main routine

writes data from Familybuilder and gedcomwriter
'''

def make_gedcom(df_gesamt: pd.DataFrame, gf: IO[str], dialect: str = "TNG", wrap_length: int = 80, include_repos: bool = False, include_sources: bool = True) -> Tuple[int, int, List[Family]]:
    plugin = TNGPlugin() if dialect.upper() == "TNG" else GrampsPlugin()
    gwriter = GedcomWriter(gf=gf, dialect=dialect, plugin=plugin, start_media_id=201000)
    gwriter.wrap_length = wrap_length  # Set wrap length for the writer
    gwriter.include_repos = include_repos  # Set REPO flag for the writer
    gwriter.include_sources = include_sources  # Set SOURCES flag for the writer
    gwriter.write_header()
    # use the actual DataFrame passed in
    grouped = df_gesamt.groupby(FamilyDataBuilder.GROUP_BY)
    print(f"\n=== Building family structures ===")
    print(f"Total families to process: {len(grouped)}")

    families: List[Family] = [] # für print
    
    # Globales Paten-Lookup Dictionary: Name -> PID
    # Format: "Nachname, Vorname" -> PID
    global_paten_lookup: Dict[str, int] = {}
    
    total_groups = len(grouped)
    for group_idx, (group_name, df_group) in enumerate(grouped, start=1):
        
        est_birth_year = get_fam_est_marr_year(df_group)
        
        # Erstelle Family-Objekt und vergebe fid
        fam = Family(fid=gwriter._get_next_fid())
        fam.est_marr_year = est_birth_year
        
        # Erstelle Vater und Mutter aus erstem Datensatz
        sample = df_group.iloc[0]

        nv_vater = clean(sample.get("Namensvariante Vater"))
        vv_vater = clean(sample.get("Vornamensvariante Vater"))
        
        # Erstelle gemeinsame Citation für Vater (aus erstem Kind-Datensatz)
        quay_value = sample.get("QUAY")
        quality = int(quay_value) if quay_value and str(quay_value).strip() else None
        
        parents_event_citation = Citation(
            text=f"Seite {sample.get('Seite')}; Nr. {sample.get('Nummer')}; Bild {clean(sample.get('Bild'))}",
            date=convert_date(get_common_date(sample.get("Datum Geburt"), sample.get("Datum Taufe"))),
            source=sample.get("QUELLE"),
            quality=quality,
        )

        # Füge Notes hinzu TO DO auch bei commondate?
        if sample.get("Datum Taufe"):
            # Füge Notizen zur Citation hinzu
            for f in ["Kirchenbucheintrag", "Karteikartentext"]:
                note_text = clean(sample.get(f))
                if note_text:
                    # Für GRAMPS: Registriere Notiz im Plugin
                    if isinstance(plugin, GrampsPlugin):
                        nid = plugin.register_note(note_text, NOTE_TYPE_MAP[f])
                        formatted_text = note_text  # GRAMPS verwendet Rohtext, Formatierung erfolgt in write_note_records
                    else:
                        # TNG: Formatiere Text direkt mit fmt_note
                        nid = gwriter._get_next_nid()
                        formatted_text = plugin.fmt_note(note_text, NOTE_TYPE_MAP[f])
                    n = Note(nid=nid, book_type=NOTE_TYPE_MAP[f], text=formatted_text)
                    parents_event_citation.notes.append(n)

        # Sammle Media-Referenzen aus Bild und Karteikarte Spalten (nur nicht-None)
        parents_media_refs = [m for m in [clean(sample.get("Bild")), clean(sample.get("Karteikarte"))] if m]

        # Stelle sicher, dass Family eine FID hat
        if fam.fid is None:
            raise ValueError(f"Family without FID for father {sample.get('Vorname Vater')} {sample.get('Klarname')}")
        
        # Vater
        father = Person(
            pid=gwriter._get_next_pid(),
            firstname=clean(sample.get("Vorname Vater")),
            surname=clean(sample.get("Klarname")),
            sex="M",
            name_prefix=clean(sample.get("Prefix")),
            name_suffix=clean(sample.get("Suffix")),
            nickname=clean(sample.get("Vater NICK")),
            name_variants=[nv_vater] if nv_vater is not None else [],
            vorname_variants=[vv_vater] if vv_vater is not None else [],
            media_refs=parents_media_refs,
            fams=[fam.fid]
        )

        if est_birth_year:
            father.common_date = f"EST {est_birth_year - 20}"
            father.est_birth_year = est_birth_year - 20

            father.events.append(
                Event(
                    type="BIRT",
                    date=father.common_date,  # Bereits mit EST prefix
                    citations=[parents_event_citation],
                )
            )

        if clean(sample.get("Beruf")):
            # Use Wohnort if available, otherwise fall back to common_place
            beruf_place = clean(sample.get("Wohnort")) or get_common_place(sample.get("Geburtsort"), sample.get("Taufort"))
            father.events.append(
                Event(
                    type="OCCU",
                    note=clean(sample.get("Beruf")),
                    date=convert_date(get_common_date(sample.get("Datum Geburt"), sample.get("Datum Taufe"))),
                    place=beruf_place,
                    citations=[parents_event_citation],
                )
            )


        
        if clean(sample.get("Wohnort")):
            # Use Wohnort if available, otherwise fall back to common_place
            wohnort_place = clean(sample.get("Wohnort")) or get_common_place(sample.get("Geburtsort"), sample.get("Taufort"))
            father.events.append(
                Event(
                    type="RESI",
                    date=convert_date(get_common_date(sample.get("Datum Geburt"), sample.get("Datum Taufe"))),
                    place=wohnort_place,
                    citations=[parents_event_citation],
                )
            )

        fam.father = father
        
        # Füge Vater zu globalem Paten-Lookup hinzu
        if father.firstname and father.surname and father.pid:
            #father_key = f"{father.surname}, {father.firstname}"
            father_key = clean(sample.get("V"))
            if father_key and father.pid:  # Sicherstellen, dass Key nicht None ist
                global_paten_lookup[father_key] = father.pid
        
        # Mutter (nutzt gleiche fam wie Vater, FID bereits geprüft)
        vv_mutter = clean(sample.get("Vornamensvariante Mutter"))
        mother = Person(
            pid=gwriter._get_next_pid(),
            firstname=clean(sample.get("Vorname Mutter")),
            surname=clean(sample.get("Nachname Mutter")),
            sex="F",
            nickname=clean(sample.get("Mutter NICK")),
            vorname_variants=[vv_mutter] if vv_mutter is not None else [],
            marriage_name=clean(sample.get("Klarname")),
            media_refs=parents_media_refs,
            fams=[fam.fid]
        )

        if est_birth_year:
            mother.common_date = f"EST {est_birth_year - 15}"
            mother.est_birth_year = est_birth_year - 15

            mother.events.append(
                Event(
                    type="BIRT",
                    date=mother.common_date,  # Bereits mit EST prefix
                    citations=[parents_event_citation],
                )
            )

        if clean(sample.get("Wohnort")):
            # Use Wohnort if available, otherwise fall back to common_place
            wohnort_place = clean(sample.get("Wohnort")) or get_common_place(sample.get("Geburtsort"), sample.get("Taufort"))
            mother.events.append(
                Event(
                    type="RESI",
                    date=convert_date(get_common_date(sample.get("Datum Geburt"), sample.get("Datum Taufe"))),
                    place=wohnort_place,
                    citations=[parents_event_citation],
                )
            )
        
        fam.mother = mother
        
        # Füge Mutter zu globalem Paten-Lookup hinzu
        if mother.firstname and father.surname and father.firstname and mother.pid:
            #mother_key = f"{father.surname}, {father.firstname} hausf. {mother.firstname}"
            mother_key = clean(sample.get("M"))
            if mother_key and mother.pid:  # Sicherstellen, dass Key nicht None ist
                global_paten_lookup[mother_key] = mother.pid
        
        # Erstelle Kinder
        children: List[Person] = []
        for _, row in df_group.iterrows():
            geschlecht = clean(row.get("Geschlecht Täufling") or "U")
            
            # Sammle Paten aus PK1, PK2, PK3 (nur nicht-None Werte)
            paten_keys = [k for k in [clean(row.get(pk)) for pk in ("PK1", "PK2", "PK3")] if k]
            
            # Finde PIDs der Paten (wird im zweiten Durchlauf gefüllt)
            paten_keys_pids: List[int] = []
            
            # Sammle Media-Referenzen aus Bild und Karteikarte Spalten (nur nicht-None)
            media_refs = [m for m in [clean(row.get("Bild")), clean(row.get("Karteikarte"))] if m]
            
            # Stelle sicher, dass Family eine FID hat
            if fam.fid is None:
                raise ValueError(f"Family without FID for child {row.get('Vorname Täufling')} {row.get('Klarname')}")
            
            child = Person(
                pid=gwriter._get_next_pid(),
                firstname=clean(row.get("Vorname Täufling")),
                surname=clean(row.get("Klarname")),
                sex=geschlecht.upper() if geschlecht else "U",
                godparents=clean(row.get("Paten/Bemerkung")),
                religion=clean(row.get("Religion Täufling")),
                common_date=convert_date(get_common_date(row.get("Datum Geburt"), row.get("Datum Taufe"))),
                paten_keys=paten_keys,
                paten_keys_pids=paten_keys_pids,
                media_refs=media_refs,
                famc=[fam.fid]
            )

            # Erstelle gemeinsame Citation für Geburt und Taufe
            quay_value_child = row.get("QUAY")
            quality_child = int(quay_value_child) if quay_value_child and str(quay_value_child).strip() else None
            
            event_citation = Citation(
                text=f"Seite {row.get('Seite')}; Nr. {row.get('Nummer')}; Bild {clean(row.get('Bild'))}",
                date=convert_date(get_common_date(row.get("Datum Geburt"), row.get("Datum Taufe"))),
                source=row.get("QUELLE"),
                quality=quality_child,
            )

            if clean(row.get("Datum Geburt")):
                child.events.append(
                    Event(
                        type="BIRT",
                        date=convert_date(row.get("Datum Geburt")),
                        place=clean(row.get("Geburtsort")),
                        source=clean(row.get("QUELLE")),
                        citations=[event_citation],
                    )
                )
            if row.get("Datum Taufe"):
                # Füge Notizen zur Citation hinzu
                for f in ["Kirchenbucheintrag", "Karteikartentext"]:
                    note_text = clean(row.get(f))
                    if note_text:
                        # Für GRAMPS: Registriere Notiz im Plugin
                        if isinstance(plugin, GrampsPlugin):
                            nid = plugin.register_note(note_text, NOTE_TYPE_MAP[f])
                            formatted_text = note_text  # GRAMPS verwendet Rohtext, Formatierung erfolgt in write_note_records
                        else:
                            # TNG: Formatiere Text direkt mit fmt_note
                            nid = gwriter._get_next_nid()
                            formatted_text = plugin.fmt_note(note_text, NOTE_TYPE_MAP[f])
                        n = Note(nid=nid, book_type=NOTE_TYPE_MAP[f], text=formatted_text)
                        event_citation.notes.append(n)
                
                child.events.append(
                    Event(
                        type="Taufe",
                        date=convert_date(row.get("Datum Taufe")),
                        place=clean(row.get("Taufort")),
                        source=row.get("QUELLE"),
                        citations=[event_citation],
                    )
                )
            if row.get("K1_STERBEDAT"):
                child.events.append(
                    Event(
                        type="DEAT",
                        date=convert_date(row.get("Datum Tod")),
                        place=clean(row.get("Sterbeort")),
                    )
                )

            children.append(child)
        
        fam.children = children
        families.append(fam)
        
        # Fortschrittsanzeige alle 500 Familien
        if group_idx % 500 == 0:
            print(f"  ... {group_idx}/{total_groups} families processed ({group_idx/total_groups*100:.1f}%)")
    
    print(f"✓ Built {len(families)} families with parents and children")
    
    # Zweiter Durchlauf: Paten-PIDs zuordnen
    print("Linking godparents (Paten) to persons...")
    for fam in families:
        for child in fam.children:
            if child.paten_keys:
                paten_keys_pids = []
                for pate_name in child.paten_keys:
                    # pate_name kann str oder Tuple sein, wir brauchen nur str
                    if isinstance(pate_name, str) and pate_name in global_paten_lookup:
                        paten_keys_pids.append(global_paten_lookup[pate_name])
                child.paten_keys_pids = paten_keys_pids
    
    print(f"✓ Linked godparents for {sum(1 for fam in families for child in fam.children if child.paten_keys_pids)} children")
    
    # Zähle INDIs
    total_indis = 0
    for fam in families:
        if fam.father:
            total_indis += 1
        if fam.mother:
            total_indis += 1
        total_indis += len(fam.children)
    
    # Schreibe alle INDI-Records
    print(f"Writing {total_indis} INDI records for {len(families)} families...")
    for fam in families:
        # Schreibe Vater
        if fam.father:
            gwriter._write_person_block(fam.father)
        # Schreibe Mutter
        if fam.mother:
            gwriter._write_person_block(fam.mother)
        # Schreibe Kinder
        for child in fam.children:
            gwriter._write_person_block(child)
    
    # Schreibe alle FAM-Records
    print(f"Writing FAM records for {len(families)} families...")
    for fam in families:
        gwriter._write_family_block(fam)
    
    # Schreibe SOUR-Records (nur wenn aktiviert)
    if gwriter.include_sources:
        print("Writing SOUR records...")
        gwriter.write_sources()
    else:
        print("Skipping SOUR records (not enabled)")
    
    # Schreibe REPO-Records (nur wenn aktiviert)
    if gwriter.include_repos:
        print("Writing REPO records...")
        gwriter.write_repos()
    else:
        print("Skipping REPO records (not enabled)")

    # Schreibe NOTE-Records (für GRAMPS)
    plugin.write_note_records(gwriter)

    gwriter.write_media_records()
    
    # Schreibe TRAILER
    gwriter.write_trailer()

    # Test unbekannte Orte
    DataTests.test_unknown_places(gwriter.unknown_places)
    
    last_fid = gwriter.next_fid - 1
    last_pid = gwriter.next_pid - 1
    return last_fid, last_pid, families


def run_gedcom_export():
    """Hauptlogik für GEDCOM-Export - aufrufbar vom Menu oder direkt"""
    global SUBMITTER_FIRSTNAME, SUBMITTER_LASTNAME, DIALECT
    
    # Konfiguration - kann von außen überschrieben werden (z.B. durch wetzlar_gui.py)
    INPUT_FILE = globals().get('INPUT_FILE', r"D:\projects\Wetzlar_csv\input\Merge\00_KB_1614-1687_Taufen_EINGABE001_V8.xlsx")
    TIMESTAMP = globals().get('TIMESTAMP', None)
    DIALECT = globals().get('DIALECT', "TNG")
    INCLUDE_SOURCES_TEXT = globals().get('INCLUDE_SOURCES_TEXT', True)
    INCLUDE_REPOPART = globals().get('INCLUDE_REPOPART', True)
    ENDLINES = globals().get('ENDLINES', 4836)
    TABELLENBLATT = globals().get('TABELLENBLATT', "Taufen")
    
    SUBMITTER_FIRSTNAME = "Taufen 1614-1692"
    SUBMITTER_LASTNAME = "xls"
    input_file = INPUT_FILE
    tabellen_blatt = TABELLENBLATT
    df = read_excel_clean(input_file, tabellen_blatt, endlines=ENDLINES)
    
    # PK-Validierung vor der GEDCOM-Auswertung
    print("=" * 80)
    pk_errors = check_pk_columns(df)
    print("=" * 80)
    
    if pk_errors:
        print("\n⛔ FEHLER: PK-Validierung fehlgeschlagen!")
        print(f"   {len(pk_errors)} Abweichung(en) in PK-Spalten gefunden.")
        print("   Bitte korrigieren Sie die Fehler in 'pk_abweichungen.csv' vor dem Export.")
        print("\nProgramm wird beendet.\n")
        exit(1)
    
    print("\n")
    DataTests.test_data(df, source_to_id)
    sources_suffix = "_SOUR" if INCLUDE_SOURCES_TEXT else ""
    repo_suffix = "_REPO" if INCLUDE_REPOPART else ""
    dialect_folder = "gramps" if DIALECT.upper() == "GRAMPS" else "tng"
    
    # Extrahiere Jahresbereich aus Input-Datei
    year_range = extract_year_range(input_file)
    year_range_suffix = f"_{year_range}" if year_range else ""
    
    # Füge Zeitstempel hinzu falls vorhanden
    timestamp_suffix = f"_{TIMESTAMP}" if TIMESTAMP else "_N"
    
    outfile = Path(f"output/{dialect_folder}/output{year_range_suffix}_{DIALECT}{sources_suffix}{repo_suffix}{timestamp_suffix}.ged")
    with outfile.open("w", encoding="utf8") as gf:
        fid, pid, families = make_gedcom(df, gf, dialect=DIALECT, include_repos=INCLUDE_REPOPART, include_sources=INCLUDE_SOURCES_TEXT)
    print(f"Written: {outfile} last fid {fid}, last pid {pid}")
    
    return outfile, fid, pid, families


def main():
    """Hauptfunktion - kann vom Menu oder direkt aufgerufen werden"""
    return run_gedcom_export()


if __name__ == "__main__":
    main()