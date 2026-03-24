# Google Cloud Vision API Setup (ohne Service Account Keys)

Da Ihre Organisation Service Account Keys blockiert, nutzen Sie **Application Default Credentials (ADC)**.

## 📥 Schritt 1: Google Cloud SDK installieren

1. Download: https://cloud.google.com/sdk/docs/install-sdk#windows
2. Führen Sie den Installer aus
3. Folgen Sie den Anweisungen

## 🔐 Schritt 2: Authentifizieren

Öffnen Sie PowerShell und führen Sie aus:

```powershell
# Initialisieren (beim ersten Mal)
gcloud init

# Wählen Sie Ihr Google-Konto und Projekt aus

# Dann: Application Default Credentials setzen
gcloud auth application-default login
```

Ein Browser-Fenster öffnet sich:
- Melden Sie sich mit Ihrem Google-Account an
- Gewähren Sie die Berechtigungen
- Sie sehen: "Authentication successful!"

## ✅ Schritt 3: Cloud Vision API aktivieren

Falls noch nicht geschehen:

```powershell
gcloud services enable vision.googleapis.com
```

Oder im Browser:
1. https://console.cloud.google.com/apis/library/vision.googleapis.com
2. Klicken Sie auf "AKTIVIEREN"

## 🖥️ Schritt 4: In der Anwendung nutzen

1. Starten Sie: `uv run main.py`
2. Wählen Sie: **"Cloud Vision (Google)"**
3. Klicken Sie auf: **"🔍 Text erkennen"**
4. Die App nutzt automatisch Ihre gcloud-Authentifizierung!

**Hinweis:** Der Button "📁 Credentials (optional)" ist nun optional und wird nicht mehr benötigt.

## 🔄 Credentials aktualisieren

Falls die Authentifizierung abläuft:

```powershell
gcloud auth application-default login
```

## ❓ Troubleshooting

### Fehler: "Could not automatically determine credentials"

```powershell
# Prüfen Sie, welches Projekt aktiv ist:
gcloud config list

# Setzen Sie das richtige Projekt:
gcloud config set project IHR_PROJEKT_ID

# Authentifizieren Sie erneut:
gcloud auth application-default login
```

### Fehler: "Permission denied"

Stellen Sie sicher, dass Ihr Google-Account Zugriff auf das Cloud-Projekt hat und die Cloud Vision API aktiviert ist.

## 💰 Kosten

- Erste 1.000 Anfragen/Monat: **KOSTENLOS**
- Danach: ~$1,50 pro 1.000 Bilder
- Details: https://cloud.google.com/vision/pricing

## 🔒 Sicherheit

Application Default Credentials sind sicherer als Service Account Keys, da:
- Keine JSON-Dateien mit Secrets gespeichert werden
- Die Credentials an Ihren User-Account gebunden sind
- Automatisches Ablaufen der Tokens
- Zentrale Verwaltung über gcloud CLI
