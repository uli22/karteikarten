"""Konfigurationsverwaltung für die Karteikarten-Anwendung."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """Verwaltet Anwendungseinstellungen in einer JSON-Datei."""
    
    DEFAULT_CONFIG = {
        "media_drive": "E:",
        "image_base_path": "",
        "kirchenbuch_base_path": "",
        "db_path": "",
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
            candidates = []

            # Im EXE-Betrieb liegt die gewünschte config.json typischerweise neben der EXE.
            if getattr(sys, "frozen", False):
                exe_dir = Path(sys.executable).resolve().parent
                candidates.extend([exe_dir / "config.json", Path.cwd() / "config.json"])
            else:
                # Entwicklungsbetrieb: Projekt-Root (ein Level über src/)
                project_root = Path(__file__).resolve().parent.parent
                candidates.extend([project_root / "config.json", Path.cwd() / "config.json"])

            # Nimm die erste vorhandene Datei, sonst den primären Zielpfad für spätere saves.
            config_path = next((p for p in candidates if p.exists()), candidates[0])
        
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


# Globale Config-Instanz (Singleton-Pattern)
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Gibt die globale Config-Instanz zurück (Singleton)."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
