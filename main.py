"""Haupteinstiegspunkt für die Wetzlar Karteikartenerkennung."""

from src.gui import run_gui


def main():
    """Startet die Karteikartenerkennung-Anwendung."""
    # Standardpfad und Startdatei
    base_path = r"E:\Karteikarten\nextcloud"
    start_file = "0008 Hb"
    
    print("Starte Wetzlar Karteikartenerkennung...")
    print(f"Basispfad: {base_path}")
    print(f"Startdatei: {start_file}")
    
    run_gui(base_path, start_file)


if __name__ == "__main__":
    main()
