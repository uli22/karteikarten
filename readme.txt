WetzlarReader - Erststart auf neuem Rechner
==========================================

1) Programm starten
- Starten Sie WetzlarReader.exe.
- Beim ersten Start wird automatisch eine config_reader.json angelegt.
- Die Synchronisation ist am Anfang absichtlich deaktiviert.

2) Datenbank festlegen
- Wechseln Sie in den Tab "Einstellungen".
- Bereich "Datenbankpfad":
  - Bei "Datenbank-Datei (.db)" den Pfad eintragen oder "📁 Wählen" nutzen.
  - Mit "💾 DB laden" übernehmen.

3) Online-Sync (API) einrichten
- Im Bereich "🌐 Online-Synchronisation":
  - Checkbox "Online-Sync aktivieren" einschalten.
  - "Sync-Modus" auf "api" stellen.
  - "Diese Instanz ist" auf "Reader" stellen.
  - "API-Endpoint" eintragen (z.B. https://wze.de.cool/lima_sync_endpoint.php). Die Eingabe kann ohne "https://" erfolgen, wird automatisch ergänzt.
  - "API-Key" eintragen.
  - Optional: "Intervall (Sek)" anpassen.
- Klicken Sie auf "🔌 Verbindung testen".
- Klicken Sie auf "💾 Speichern".
- Optional sofortiger Abgleich: "🔄 Jetzt synchronisieren".

Wichtig:
- "Verbindung testen" prueft nur die Erreichbarkeit.
- Erst mit aktivierter Checkbox + "Speichern" startet die laufende Synchronisation.

4) Bildpfade korrekt setzen
Im Tab "Einstellungen" gibt es zwei relevante Bereiche:

A) Kirchenbuch-Medien Pfade
- "Laufwerk": Basis-Laufwerk oder Basis-Ordner der Kirchenbuchdateien.
  Beispiele:
  - E:
  - D:\Dokumente\Kirchenbuecher
- Mit "💾 Speichern" uebernehmen.
- "Kirchenbuch-Basisverzeichnis": setzen, wenn Ordner auf einen neuen Root umgezogen sind.
  - "📁 Wählen" und dann "✅ Übernehmen".

B) Karteikarten-Bilder
- "Karteikarten-Basisverzeichnis" setzen, wenn Karteikartenbilder an neuem Ort liegen.
  - "📁 Wählen" und dann "✅ Übernehmen".

Hinweis zur Pfadauflösung:
- Wenn alte absolute Pfade nicht mehr existieren, versucht der Reader den gespeicherten Unterpfad
  unter den neuen Basisordnern wiederzufinden.

5) Typische Erststart-Pruefung
- In den Tab "Datenbank" wechseln.
- Einen Datensatz markieren.
- Rechtsklick -> "Karteikarte anzeigen" bzw. "Kirchenbuch anzeigen" pruefen.
- Wenn Bilder nicht gefunden werden, die Basispfade unter "Einstellungen" korrigieren.
