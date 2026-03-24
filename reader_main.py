"""Haupteinstiegspunkt für den Wetzlar Karteikarten-Reader (Leseanwendung)."""

from src.reader_gui import run_reader


def main():
    """Startet den Karteikarten-Reader."""
    print("Starte Wetzlar Karteikarten-Reader...")
    run_reader()


if __name__ == "__main__":
    main()
