"""Offline-First Online-Sync Grundgeruest.

Diese Komponente ist bewusst schlank gehalten: Sie liest die Sync-Konfiguration,
arbeitet Pending-Eintraege aus der lokalen Queue ab und markiert sie bei Erfolg.
Die eigentliche HTTP-Synchronisation kann in der naechsten Ausbaustufe ergaenzt
werden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .config import get_config
from .database import KarteikartenDB


@dataclass
class SyncResult:
    processed: int = 0
    sent: int = 0
    failed: int = 0


class OnlineSyncService:
    """Verwaltet den lokalen Sync-Queue-Workflow."""

    def __init__(self) -> None:
        config = get_config().online_sync
        self.enabled = bool(config.get("enabled", False))
        self.endpoint_url = str(config.get("endpoint_url", "")).strip()
        self.api_key = str(config.get("api_key", "")).strip()
        self.source = str(config.get("source", "erkennung")).strip() or "erkennung"
        self.batch_size = int(config.get("batch_size", 100) or 100)

    def get_status(self, db: KarteikartenDB) -> Dict[str, int | bool]:
        """Liefert den aktuellen lokalen Sync-Status."""
        stats = db.get_sync_queue_stats()
        return {
            "enabled": self.enabled,
            "pending": stats["pending"],
            "sent": stats["sent"],
            "total": stats["total"],
        }

    def flush_once(self, db: KarteikartenDB) -> SyncResult:
        """Verarbeitet eine Queue-Batch.

        Aktuelles Verhalten:
        - Wenn Online-Sync deaktiviert ist, wird nichts gesendet.
        - Wenn Endpunkt fehlt, wird nichts gesendet.
        - Sonst werden Eintraege als verarbeitet markiert.

        Die konkrete Netzwerksynchronisation (HTTP push/pull) wird als naechster
        Schritt in dieser Klasse implementiert.
        """
        result = SyncResult()

        if not self.enabled:
            return result

        pending = db.get_pending_sync_items(limit=self.batch_size)
        result.processed = len(pending)

        if not pending:
            return result

        if not self.endpoint_url:
            for item in pending:
                db.mark_sync_item_error(item["id"], "endpoint_url fehlt")
                result.failed += 1
            return result

        for item in pending:
            try:
                # Platzhalter fuer echte HTTP-Synchronisation.
                db.mark_sync_item_sent(item["id"])
                result.sent += 1
            except Exception as exc:  # pragma: no cover
                db.mark_sync_item_error(item["id"], str(exc))
                result.failed += 1

        return result
