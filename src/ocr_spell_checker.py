"""Hover-Korrektur-Tool für den OCR-Texteditor.

Zeigt beim Hovern über Wörter im Text-Widget kontextabhängige
Korrekturvorschläge basierend auf Kirchenbuch-Wortlisten an.
"""

import difflib
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Optional


def _get_data_dir() -> Path:
    """Gibt das Verzeichnis mit den JSON-Listendateien zurück."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class OCRWordLists:
    """Lädt und verwaltet alle Wortlisten für die OCR-Korrektur."""

    def __init__(self) -> None:
        data_dir = _get_data_dir()

        # Vornamen laden
        vornamen: set[str] = set()
        for fname in ('vornamen_maennlich.json', 'vornamen_weiblich.json'):
            path = data_dir / fname
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                    if isinstance(data, list):
                        vornamen.update(str(v) for v in data)
                except (json.JSONDecodeError, OSError):
                    pass

        # kirchenbuch_vocabulary aus ocr_corrections.json
        # Format: { "KorrekteForm": ["Variante1", "Variante2", ...] }
        self._vocab_variants: dict[str, list[str]] = {}
        corrections_path = data_dir / 'ocr_corrections.json'
        if corrections_path.exists():
            try:
                data = json.loads(corrections_path.read_text(encoding='utf-8'))
                self._vocab_variants = data.get('kirchenbuch_vocabulary', {})
            except (json.JSONDecodeError, OSError):
                pass

        # Häufige Kirchenbuchbegriffe
        begriffe: set[str] = set()
        begriffe_path = data_dir / 'kirchenbuch_begriffe.json'
        if begriffe_path.exists():
            try:
                data = json.loads(begriffe_path.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    begriffe.update(str(v) for v in data)
            except (json.JSONDecodeError, OSError):
                pass

        # Alle korrekten Wörter zusammenführen (Vornamen + Vocab-Keys + Begriffe)
        self._all_correct: list[str] = sorted(
            vornamen | set(self._vocab_variants.keys()) | begriffe
        )
        self._all_correct_set: set[str] = set(self._all_correct)
        # Lookup: lower → Originalschreibung (für Case-insensitiven Vergleich)
        self._lower_to_orig: dict[str, str] = {w.lower(): w for w in self._all_correct}

    def find_suggestions(self, word: str) -> list[str]:
        """Findet Korrekturvorschläge für ein Wort.

        Gibt eine leere Liste zurück, wenn das Wort bereits korrekt ist
        oder keine sinnvollen Vorschläge gefunden werden.
        """
        if not word:
            return []

        # Satzzeichen am Rand abschneiden (aber nicht im Wort)
        word_stripped = word.strip('.,;:!?()[]"\'\u2019\u2018\u201c\u201d')
        if not word_stripped or len(word_stripped) < 3:
            return []

        word_lower = word_stripped.lower()
        suggestions: dict[str, float] = {}  # suggestion → score

        # 1. Direkte Variante in kirchenbuch_vocabulary → korrekte Form vorschlagen
        for correct, variants in self._vocab_variants.items():
            for variant in variants:
                if word_lower == variant.lower() and word_stripped != correct:
                    suggestions[correct] = 1.0
                    break

        # 2. Wort ist bereits korrekt → nur Varianten-Vorschläge zurückgeben
        if word_stripped in self._all_correct_set:
            return [s for s in suggestions if s != word_stripped]

        # 3. Case-insensitiver Exakt-Treffer → Großschreibung korrigieren
        if word_lower in self._lower_to_orig:
            correct_form = self._lower_to_orig[word_lower]
            if correct_form != word_stripped:
                suggestions[correct_form] = 0.99

        # 4. Fuzzy-Matching (Levenshtein-ähnlich via difflib)
        close = difflib.get_close_matches(
            word_stripped, self._all_correct, n=5, cutoff=0.72
        )
        for m in close:
            if m not in suggestions:
                score = difflib.SequenceMatcher(None, word_stripped, m).ratio()
                suggestions[m] = score

        # 5. Noch Case-insensitives Fuzzy-Matching als Fallback
        if len(suggestions) < 2:
            close_ci = difflib.get_close_matches(
                word_lower, list(self._lower_to_orig.keys()), n=5, cutoff=0.72
            )
            for lw in close_ci:
                orig = self._lower_to_orig[lw]
                if orig not in suggestions and orig != word_stripped:
                    score = difflib.SequenceMatcher(None, word_lower, lw).ratio()
                    suggestions[orig] = score * 0.95  # leicht abgewichtet

        # Sortiert nach Score, Eingabewort ausschließen
        result = sorted(
            [(s, sc) for s, sc in suggestions.items() if s != word_stripped],
            key=lambda x: -x[1],
        )
        return [s for s, _ in result[:5]]


class OCRCorrectionTooltip:
    """Zeigt beim Hovern über Wörter im tk.Text-Widget Korrekturvorschläge.

    Verwendung:
        word_lists = OCRWordLists()
        tooltip = OCRCorrectionTooltip(text_widget, word_lists)
    """

    HOVER_DELAY_MS = 600
    _HIGHLIGHT_TAG = 'ocr_hover_highlight'

    def __init__(self, text_widget: tk.Text, word_lists: OCRWordLists) -> None:
        self.text_widget = text_widget
        self.word_lists = word_lists
        self._tooltip_win: Optional[tk.Toplevel] = None
        self._hover_timer: Optional[str] = None
        self._hide_timer: Optional[str] = None
        self._active_word_range: Optional[tuple[str, str]] = None

        # Hervorhebungs-Tag konfigurieren
        text_widget.tag_configure(
            self._HIGHLIGHT_TAG, background='#fffacd', underline=True
        )

        # Events binden
        text_widget.bind('<Motion>', self._on_motion)
        text_widget.bind('<Leave>', self._schedule_hide)  # verzögert, damit Popup erreichbar ist
        text_widget.bind('<Button-1>', self._cancel_and_hide)
        text_widget.bind('<Key>', self._cancel_and_hide)

    # ------------------------------------------------------------------
    # Event-Handler
    # ------------------------------------------------------------------

    def _on_motion(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Debounced Hover-Logik: Tooltip erscheint nach HOVER_DELAY_MS."""
        word_range = self._get_word_range(event.x, event.y)

        # Wort hat sich nicht verändert → nichts tun
        if word_range == self._active_word_range:
            # Maus bewegt sich immer noch über demselben Wort → laufenden
            # Hide-Timer abbrechen, falls Maus kurz das Wort verlassen hatte
            self._cancel_hide_timer()
            return

        # Hover-Timer für neues Wort zurücksetzen
        if self._hover_timer:
            self.text_widget.after_cancel(self._hover_timer)
            self._hover_timer = None

        self._active_word_range = word_range

        if word_range:
            # Neues Wort gefunden: laufendes Popup sofort schließen,
            # dann nach Delay neues anzeigen
            self._hide_tooltip()
            self._cancel_hide_timer()
            x_root, y_root = event.x_root, event.y_root
            self._hover_timer = self.text_widget.after(
                self.HOVER_DELAY_MS,
                lambda: self._show_tooltip(x_root, y_root, word_range),
            )
        else:
            # Kein Wort unter Cursor (Leerzeile, Rand) → verzögert ausblenden
            # damit die Maus noch zum Popup fahren kann
            self._schedule_hide()

    def _schedule_hide(self, event: Optional[tk.Event] = None, delay_ms: int = 1400) -> None:  # type: ignore[type-arg]
        """Plant verzögertes Ausblenden – gibt Zeit zum Einfahren ins Popup."""
        if self._hide_timer:
            self.text_widget.after_cancel(self._hide_timer)
        self._hide_timer = self.text_widget.after(delay_ms, self._cancel_and_hide)

    def _cancel_hide_timer(self, event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        """Bricht geplantes Ausblenden ab (Maus ist ins Popup gefahren)."""
        if self._hide_timer:
            self.text_widget.after_cancel(self._hide_timer)
            self._hide_timer = None

    def _cancel_and_hide(self, event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        """Bricht laufenden Hover-Timer ab und versteckt den Tooltip sofort."""
        if self._hide_timer:
            self.text_widget.after_cancel(self._hide_timer)
            self._hide_timer = None
        if self._hover_timer:
            self.text_widget.after_cancel(self._hover_timer)
            self._hover_timer = None
        self._hide_tooltip()
        self._active_word_range = None

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _hide_tooltip(self) -> None:
        if self._tooltip_win:
            try:
                self._tooltip_win.destroy()
            except tk.TclError:
                pass
            self._tooltip_win = None
        try:
            self.text_widget.tag_remove(self._HIGHLIGHT_TAG, '1.0', tk.END)
        except tk.TclError:
            pass

    def _get_word_range(self, x: int, y: int) -> Optional[tuple[str, str]]:
        """Gibt (start_index, end_index) des Worts unter (x, y) zurück."""
        try:
            index = self.text_widget.index(f'@{x},{y}')
            word_start = self.text_widget.index(f'{index} wordstart')
            word_end = self.text_widget.index(f'{index} wordend')
            word = self.text_widget.get(word_start, word_end)
            # Nur echte Wörter (keine Leerzeilen, Satzzeichen)
            if not word.strip() or not any(c.isalpha() for c in word):
                return None
            return (word_start, word_end)
        except tk.TclError:
            return None

    def _show_tooltip(
        self, x_root: int, y_root: int, word_range: tuple[str, str]
    ) -> None:
        """Erstellt und platziert das Korrektur-Popup."""
        if self._tooltip_win:
            return

        word_start, word_end = word_range
        try:
            word = self.text_widget.get(word_start, word_end)
        except tk.TclError:
            return

        suggestions = self.word_lists.find_suggestions(word)
        if not suggestions:
            return

        # Wort hervorheben
        try:
            self.text_widget.tag_add(self._HIGHLIGHT_TAG, word_start, word_end)
        except tk.TclError:
            return

        # Toplevel-Fenster (kein Rahmen, immer im Vordergrund)
        win = tk.Toplevel(self.text_widget)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg='#fffde7')

        # Kopfzeile
        word_display = word.strip()[:20] + ('…' if len(word.strip()) > 20 else '')
        header = tk.Label(
            win,
            text=f'Vorschläge für „{word_display}"',
            bg='#fff9c4',
            fg='#555',
            font=('Arial', 8, 'bold'),
            padx=6,
            pady=3,
            anchor='w',
        )
        header.pack(fill=tk.X)

        ttk.Separator(win, orient='horizontal').pack(fill=tk.X)

        # Vorschlag-Buttons
        for suggestion in suggestions:
            btn = tk.Button(
                win,
                text=suggestion,
                bg='#fffff0',
                activebackground='#e3f2fd',
                activeforeground='#1565c0',
                relief=tk.FLAT,
                font=('Arial', 10),
                padx=10,
                pady=3,
                anchor='w',
                cursor='hand2',
                command=lambda s=suggestion, ws=word_start, we=word_end:  # type: ignore[arg-type]
                    self._apply_correction(s, ws, we),
            )
            btn.pack(fill=tk.X, padx=1, pady=0)
            # Hover-Effekt für den Button
            btn.bind('<Enter>', lambda e, b=btn: b.configure(bg='#bbdefb'))  # type: ignore[misc]
            btn.bind('<Leave>', lambda e, b=btn: b.configure(bg='#fffff0'))  # type: ignore[misc]

        self._tooltip_win = win

        # Fenster positionieren
        win.update_idletasks()
        win_w = win.winfo_reqwidth()
        win_h = win.winfo_reqheight()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()

        tip_x = x_root + 12
        tip_y = y_root + 18

        if tip_x + win_w > screen_w:
            tip_x = x_root - win_w - 8
        if tip_y + win_h > screen_h:
            tip_y = y_root - win_h - 8

        win.geometry(f'+{tip_x}+{tip_y}')

        # Maus fährt ins Popup → Hide-Timer abbrechen
        # Maus verlässt Popup → Hide-Timer starten
        for widget in [win] + list(win.winfo_children()):
            widget.bind('<Enter>', self._cancel_hide_timer)  # type: ignore[misc]
            widget.bind('<Leave>', self._schedule_hide)  # type: ignore[misc]

    def _apply_correction(
        self, suggestion: str, word_start: str, word_end: str
    ) -> None:
        """Ersetzt das Wort mit dem gewählten Vorschlag."""
        self._hide_tooltip()
        self._active_word_range = None
        try:
            self.text_widget.delete(word_start, word_end)
            self.text_widget.insert(word_start, suggestion)
        except tk.TclError:
            pass
