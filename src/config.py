"""Konfigurationsverwaltung für die Karteikarten-Anwendung."""

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union


def resolve_config_path(filename: str = "config.json") -> Path:
    """Ermittelt den Pfad einer Konfigurationsdatei analog zum App-Modus."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / filename, Path.cwd() / filename])
    else:
        project_root = Path(__file__).resolve().parent.parent
        candidates.extend([project_root / filename, Path.cwd() / filename])
    return next((p for p in candidates if p.exists()), candidates[0])


def bootstrap_config(target: Union[str, Path], template_filename: str = "config.json") -> Path:
    """Legt eine neue Konfigurationsdatei optional als Kopie einer bestehenden Vorlage an."""
    target_path = Path(target)
    if target_path.exists():
        return target_path

    template_path = resolve_config_path(template_filename)
    if template_path.exists() and template_path != target_path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_path, target_path)
    return target_path


class Config:
    """Verwaltet Anwendungseinstellungen in einer JSON-Datei."""
    
    DEFAULT_CONFIG = {
        "media_drive": "E:",
        "image_base_path": "",
        "kirchenbuch_base_path": "",
        "db_path": "",
        "online_sync": {
            "enabled": False,
            "mode": "mysql",
            "endpoint_url": "",
            "db_user": "",
            "db_password": "",
            "db_name": "",
            "db_host": "",
            "db_port": 3306,
            "api_key": "",
            "device_id": "",
            "last_pull_cursor": "",
            "last_pull_id": "",
            "source": "erkennung",
            "sync_interval_seconds": 20,
            "batch_size": 100
        },
        "column_widths": {
            "id": 20,
            "jahr": 40,
            "datum": 40,
            "iso_datum": 40,
            "typ": 10,
            "seite": 20,
            "nr": 20,
            "gemeinde": 60,
            "vorname": 80,
            "nachname": 80,
            "partner": 100,
            "beruf": 80,
            "ort": 80,
            "brautigam_vater": 100,
            "braut_vater": 100,
            "braut_nachname": 100,
            "braut_ort": 80,
            "brautigam_stand": 60,
            "braut_stand": 60,
            "todestag": 80,
            "geb_jahr_gesch": 60,
            "dateiname": 80,
            "notiz": 8,
            "erkannter_text": 400
        }
    }
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialisiert die Konfiguration.
        
        Args:
            config_path: Pfad zur Config-Datei. Standard: config.json im Projektverzeichnis
        """
        if config_path is None:
            config_path = resolve_config_path("config.json")
        
        self.config_path = Path(config_path)
        self.config = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """Lädt die Konfiguration aus der Datei oder erstellt Default-Config."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Merge mit Defaults (falls neue Felder hinzugefügt wurden)
                return {**self.DEFAULT_CONFIG, **config}
            except (json.JSONDecodeError, IOError) as e:
                print(f"Fehler beim Laden der Config: {e}. Verwende Standardwerte.")
                return self.DEFAULT_CONFIG.copy()
        else:
            return self.DEFAULT_CONFIG.copy()
    
    def save(self) -> None:
        """Speichert die aktuelle Konfiguration in die Datei."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            print(f"Konfiguration gespeichert: {self.config_path}")
        except IOError as e:
            print(f"Fehler beim Speichern der Config: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Gibt einen Konfigurationswert zurück."""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Setzt einen Konfigurationswert und speichert die Config."""
        self.config[key] = value
        self.save()
    
    @property
    def media_drive(self) -> str:
        """Gibt den konfigurierten Laufwerksbuchstaben zurück (z.B. 'E:')."""
        return self.config.get("media_drive", "E:")
    
    @media_drive.setter
    def media_drive(self, value: str) -> None:
        """Setzt den Laufwerksbuchstaben."""
        # Stelle sicher, dass es das Format 'X:' hat
        if not value.endswith(':'):
            value = value + ':'
        self.set("media_drive", value.upper())
    
    def get_column_width(self, column_name: str) -> Optional[int]:
        """Gibt die gespeicherte Breite einer Spalte zurück."""
        return self.config.get("column_widths", {}).get(column_name)

    @property
    def image_base_path(self) -> str:
        """Gibt den konfigurierten Bild-Basispfad zurück."""
        return self.config.get("image_base_path", "")

    @image_base_path.setter
    def image_base_path(self, value: str) -> None:
        """Setzt den Bild-Basispfad."""
        self.set("image_base_path", value)

    @property
    def db_path(self) -> str:
        """Gibt den konfigurierten Datenbankpfad zurück."""
        return self.config.get("db_path", "")

    @db_path.setter
    def db_path(self, value: str) -> None:
        """Setzt den Datenbankpfad."""
        self.set("db_path", value)
    
    def set_column_width(self, column_name: str, width: int) -> None:
        """Speichert die Breite einer Spalte."""
        if "column_widths" not in self.config:
            self.config["column_widths"] = {}
        self.config["column_widths"][column_name] = width
        self.save()
    
    def set_all_column_widths(self, widths: Dict[str, int]) -> None:
        """Speichert alle Spaltenbreiten auf einmal."""
        self.config["column_widths"] = widths
        self.save()

    @property
    def online_sync(self) -> Dict[str, Any]:
        """Gibt die Online-Sync-Konfiguration zurück."""
        value = self.config.get("online_sync", {})
        if not isinstance(value, dict):
            value = {}
        merged = {**self.DEFAULT_CONFIG["online_sync"], **value}
        return merged

    def set_online_sync(self, values: Dict[str, Any]) -> None:
        """Aktualisiert die Online-Sync-Konfiguration."""
        merged = {**self.online_sync, **values}
        self.set("online_sync", merged)


# Globale Config-Instanzen (pro Pfad)
_config_instances: Dict[str, Config] = {}


def get_config(config_path: Optional[Union[str, Path]] = None) -> Config:
    """Gibt eine Config-Instanz pro Pfad zurück."""
    resolved = Path(config_path).resolve() if config_path is not None else resolve_config_path("config.json").resolve()
    key = str(resolved)
    if key not in _config_instances:
        _config_instances[key] = Config(resolved)
    return _config_instances[key]
