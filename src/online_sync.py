"""Offline-First Online-Sync fuer MySQL (Lima-City o.ae.).

Architektur:
  - Lokale SQLite-DB ist primaere Datenquelle (offline-first).
  - Aenderungen landen in der lokalen sync_queue.
  - flush_once() sendet Pending-Eintraege zur MySQL-Online-DB (PUSH).
  - pull_once() holt neue Eintraege vom Server und merged sie lokal (PULL).
  - Konfliktregel: Wenn updated_at auf dem Server neuer ist, gewinnt der Server
    - AUSNAHME: fid_reader wird lokal nicht ueberschrieben, fid_erkennung nicht vom Reader.
  - Abhängigkeit: pymysql (wird nur importiert wenn sync aktiv).

Installation:
    pip install pymysql
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import get_config
from .database import KarteikartenDB

logger = logging.getLogger("online_sync")

# Felder die NICHT von der Remote-Seite ueberschrieben werden duerfen,
# wenn sie von der lokalen Gegenseite gesetzt wurden.
# Schluessel: source der lokalen App  → geschuetzte Felder dieser App
_PROTECTED_FIELDS: Dict[str, List[str]] = {
    "reader": ["fid_reader"],
    "erkennung": ["fid_erkennung"],
}

# Alle Felder die synchronisiert werden (ausser Sync-Meta und lokale ID)
_SYNC_FIELDS = [
    "dateiname", "dateipfad", "kirchengemeinde", "ereignis_typ",
    "jahr", "datum", "iso_datum", "seite", "nummer",
    "erkannter_text", "ocr_methode", "kirchenbuchtext",
    "vorname", "nachname", "partner", "beruf", "todestag", "ort",
    "geb_jahr_gesch", "stand", "braeutigam_stand", "braeutigam_vater",
    "braut_vater", "braut_nachname", "braut_ort",
    "notiz", "fid", "gramps",
    "fid_reader", "fid_erkennung",
    "version", "updated_by", "aktualisiert_am",
]


@dataclass
class SyncResult:
    pushed: int = 0
    pulled: int = 0
    conflicts: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)


class MySQLConnection:
    """Duenne Wrapper-Klasse um pymysql-Verbindung."""

    def __init__(self, host: str, port: int, user: str, password: str,
                 database: str, charset: str = "utf8mb4") -> None:
        try:
            import pymysql  # type: ignore
            import pymysql.cursors  # type: ignore
        except ImportError as e:
            raise ImportError(
                "pymysql ist nicht installiert. Bitte 'pip install pymysql' ausführen."
            ) from e

        self._conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset=charset,
            autocommit=False,
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def cursor(self):
        return self._conn.cursor()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def ping(self) -> bool:
        try:
            self._conn.ping(reconnect=True)
            return True
        except Exception:
            return False

    def ensure_schema(self) -> None:
        """Legt die Online-Tabellen an, falls sie noch nicht existieren."""
        cur = self.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS karteikarten (
                global_id VARCHAR(36) NOT NULL PRIMARY KEY,
                dateiname VARCHAR(512),
                dateipfad VARCHAR(1024),
                kirchengemeinde VARCHAR(256),
                ereignis_typ VARCHAR(64),
                jahr SMALLINT,
                datum VARCHAR(32),
                iso_datum VARCHAR(16),
                seite VARCHAR(32),
                nummer VARCHAR(32),
                erkannter_text TEXT,
                ocr_methode VARCHAR(64),
                kirchenbuchtext TEXT,
                vorname VARCHAR(256),
                nachname VARCHAR(256),
                partner VARCHAR(256),
                beruf VARCHAR(256),
                todestag VARCHAR(64),
                ort VARCHAR(256),
                geb_jahr_gesch SMALLINT,
                stand VARCHAR(128),
                braeutigam_stand VARCHAR(128),
                braeutigam_vater VARCHAR(256),
                braut_vater VARCHAR(256),
                braut_nachname VARCHAR(256),
                braut_ort VARCHAR(256),
                notiz VARCHAR(32),
                fid VARCHAR(64),
                gramps VARCHAR(32),
                fid_reader VARCHAR(256),
                fid_erkennung VARCHAR(256),
                version INT DEFAULT 1,
                updated_by VARCHAR(64),
                aktualisiert_am DATETIME,
                erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                state_key VARCHAR(64) NOT NULL PRIMARY KEY,
                state_value TEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        self._conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        cur = self.cursor()
        cur.execute("SELECT state_value FROM sync_state WHERE state_key = %s", (key,))
        row = cur.fetchone()
        return row["state_value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        cur = self.cursor()
        cur.execute(
            """INSERT INTO sync_state (state_key, state_value) VALUES (%s, %s)
               ON DUPLICATE KEY UPDATE state_value = VALUES(state_value)""",
            (key, value),
        )
        self._conn.commit()


class OnlineSyncService:
    """Offline-First Sync: lokale SQLite ↔ MySQL Online-DB."""

    MAX_RETRIES = 5

    def __init__(self) -> None:
        cfg = get_config().online_sync
        self.enabled: bool = bool(cfg.get("enabled", False))
        self.source: str = str(cfg.get("source", "erkennung")).strip() or "erkennung"
        self.batch_size: int = int(cfg.get("batch_size", 100) or 100)
        self.interval: int = int(cfg.get("sync_interval_seconds", 20) or 20)

        # Verbindungsparameter (explizite Felder, kein URL-Parsen mehr)
        self._host: str = str(cfg.get("db_host", "")).strip()
        self._port: int = int(cfg.get("db_port", 3306) or 3306)
        self._user: str = str(cfg.get("db_user", "")).strip()
        self._password: str = str(cfg.get("db_password", ""))
        self._database: str = str(cfg.get("db_name", "")).strip()

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_result: Optional[SyncResult] = None
        self._last_sync_ts: str = ""
        self._db: Optional[KarteikartenDB] = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def get_status(self, db: Optional[KarteikartenDB] = None) -> Dict[str, Any]:
        db = db or self._db
        if db is not None:
            try:
                stats = db.get_sync_queue_stats()
            except Exception:
                stats = {"pending": 0, "sent": 0, "total": 0}
        else:
            stats = {"pending": 0, "sent": 0, "total": 0}
        return {
            "enabled": self.enabled,
            "pending": stats.get("pending", 0),
            "sent": stats.get("sent", 0),
            "total": stats.get("total", 0),
            "last_sync": self._last_sync_ts or "–",
            "last_result": self._last_result,
        }

    def start_background(self, db: KarteikartenDB) -> None:
        """Startet den Hintergrund-Sync-Thread (idempotent)."""
        self._db = db
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._background_loop,
            args=(db,),
            name="OnlineSync",
            daemon=True,
        )
        self._thread.start()
        logger.info("Online-Sync Hintergrund-Thread gestartet (Intervall: %ds)", self.interval)

    def stop_background(self) -> None:
        """Stoppt den Hintergrund-Thread sauber."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            logger.info("Online-Sync Hintergrund-Thread gestoppt.")

    def sync_now(self, db: KarteikartenDB) -> SyncResult:
        """Führt sofort einen vollständigen Push+Pull-Zyklus durch."""
        with self._lock:
            return self._run_cycle(db)

    def flush_once(self, db: KarteikartenDB) -> SyncResult:
        """Abwärtskompatible Methode – führt sync_now aus."""
        return self.sync_now(db)

    # ------------------------------------------------------------------
    # Interner Sync-Zyklus
    # ------------------------------------------------------------------

    def _background_loop(self, db: KarteikartenDB) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    result = self._run_cycle(db)
                    self._last_result = result
                    self._last_sync_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                if result.failed or result.errors:
                    logger.warning(
                        "Sync-Zyklus: %d gepusht, %d gepullt, %d Fehler",
                        result.pushed, result.pulled, result.failed,
                    )
                else:
                    logger.debug(
                        "Sync-Zyklus OK: %d gepusht, %d gepullt",
                        result.pushed, result.pulled,
                    )
            except Exception as exc:
                logger.exception("Unerwarteter Fehler im Sync-Thread: %s", exc)
            self._stop_event.wait(timeout=self.interval)

    def _run_cycle(self, db: KarteikartenDB) -> SyncResult:
        result = SyncResult()

        if not self.enabled or not self._host:
            return result

        try:
            mysql = self._connect()
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"Verbindungsfehler: {exc}")
            logger.warning("MySQL-Verbindung fehlgeschlagen: %s", exc)
            return result

        try:
            mysql.ensure_schema()
            self._push(db, mysql, result)
            self._pull(db, mysql, result)
        except Exception as exc:
            result.failed += 1
            result.errors.append(str(exc))
            logger.exception("Sync-Zyklus Fehler: %s", exc)
            try:
                mysql.rollback()
            except Exception:
                pass
        finally:
            try:
                mysql.close()
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # PUSH: lokale Queue → MySQL
    # ------------------------------------------------------------------

    def _push(self, db: KarteikartenDB, mysql: MySQLConnection, result: SyncResult) -> None:
        pending = db.get_pending_sync_items(limit=self.batch_size)
        for item in pending:
            if item.get("retries", 0) >= self.MAX_RETRIES:
                logger.warning("Queue-Eintrag %d hat max. Retries erreicht, wird übersprungen.", item["id"])
                continue
            try:
                self._push_one(db, mysql, item)
                db.mark_sync_item_sent(item["id"])
                result.pushed += 1
            except Exception as exc:
                db.mark_sync_item_error(item["id"], str(exc))
                result.failed += 1
                result.errors.append(f"push {item['global_id']}: {exc}")
                logger.warning("Push fehlgeschlagen für %s: %s", item["global_id"], exc)

    def _push_one(self, db: KarteikartenDB, mysql: MySQLConnection, queue_item: Dict) -> None:
        global_id = queue_item["global_id"]
        op = queue_item.get("op", "upsert")

        # Lokalen Datensatz laden
        cur_local = db.conn.cursor()
        cur_local.execute("SELECT * FROM karteikarten WHERE global_id = ?", (global_id,))
        row = cur_local.fetchone()
        if not row:
            return  # Wurde zwischenzeitlich lokal gelöscht

        record = dict(row)

        if op == "delete":
            cur = mysql.cursor()
            cur.execute("DELETE FROM karteikarten WHERE global_id = %s", (global_id,))
            mysql.commit()
            return

        # Server-Version prüfen
        cur = mysql.cursor()
        cur.execute("SELECT version, aktualisiert_am FROM karteikarten WHERE global_id = %s", (global_id,))
        server_row = cur.fetchone()

        if server_row:
            # Konflikt prüfen: Ist Server neuer als unsere base_version?
            server_version = int(server_row["version"] or 1)
            base_version = int(queue_item.get("base_version") or 1)
            if server_version > base_version:
                # Server hat neuere Daten → fieldweiser Merge
                result_dummy = SyncResult()
                self._merge_conflict(db, record, server_row, mysql, result_dummy)
                return

        # UPSERT zum Server
        fields = [f for f in _SYNC_FIELDS if f in record]
        values = [record.get(f) for f in fields]
        placeholders = ", ".join(["%s"] * len(values))
        col_names = ", ".join(fields)
        updates = ", ".join([f"{f} = VALUES({f})" for f in fields if f not in ("global_id",)])

        cur.execute(
            f"""INSERT INTO karteikarten (global_id, {col_names})
                VALUES (%s, {placeholders})
                ON DUPLICATE KEY UPDATE {updates}""",
            [global_id, *values],
        )
        mysql.commit()

    # ------------------------------------------------------------------
    # PULL: MySQL → lokale DB
    # ------------------------------------------------------------------

    def _pull(self, db: KarteikartenDB, mysql: MySQLConnection, result: SyncResult) -> None:
        state_key = f"last_pull_{self.source}"
        last_pull = mysql.get_state(state_key) or "1970-01-01 00:00:00"

        cur = mysql.cursor()
        cur.execute(
            "SELECT * FROM karteikarten WHERE aktualisiert_am > %s ORDER BY aktualisiert_am LIMIT %s",
            (last_pull, self.batch_size),
        )
        rows = cur.fetchall()

        if not rows:
            return

        newest_ts = last_pull
        for server_row in rows:
            try:
                updated = self._apply_pull(db, server_row, result)
                ts = str(server_row.get("aktualisiert_am") or "")
                if ts and ts > newest_ts:
                    newest_ts = ts
                if updated:
                    result.pulled += 1
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"pull {server_row.get('global_id')}: {exc}")
                logger.warning("Pull fehlgeschlagen für %s: %s", server_row.get("global_id"), exc)

        mysql.set_state(state_key, newest_ts)

    def _apply_pull(self, db: KarteikartenDB, server_row: Dict, result: SyncResult) -> bool:
        """Wendet einen Server-Datensatz lokal an. Gibt True zurück wenn ein Update erfolgte."""
        global_id = server_row.get("global_id")
        if not global_id:
            return False

        cur = db.conn.cursor()
        cur.execute("SELECT * FROM karteikarten WHERE global_id = ?", (global_id,))
        local_row = cur.fetchone()

        if not local_row:
            # Neuer Datensatz vom Server → lokal anlegen
            self._insert_from_server(db, server_row)
            return True

        local_row_dict = dict(local_row)
        local_version = int(local_row_dict.get("version") or 1)
        server_version = int(server_row.get("version") or 1)

        if server_version <= local_version:
            # Lokaler Stand ist aktueller oder gleich → nichts tun
            return False

        # Server ist neuer → Merge mit Schutz der eigenen Felder
        protected = _PROTECTED_FIELDS.get(self.source, [])
        update_fields = []
        update_vals = []

        for f in _SYNC_FIELDS:
            if f in ("version", "updated_by"):
                continue
            if f in protected and local_row_dict.get(f):
                # Lokales Feld ist gesetzt und geschützt → nicht überschreiben
                continue
            if f in server_row:
                update_fields.append(f"{f} = ?")
                update_vals.append(server_row[f])

        if not update_fields:
            return False

        # Merge der geschützten Felder: behalte lokal, schreibe nicht 0/None rein
        for f in protected:
            if local_row_dict.get(f) and not server_row.get(f):
                # Lokaler Wert vorhanden, Server leer → Server-Update mit lokalem Wert verzögert
                pass

        update_fields.append("version = ?")
        update_vals.append(server_version)
        update_fields.append("sync_status = ?")
        update_vals.append("synced")
        update_vals.append(global_id)

        cur.execute(
            f"UPDATE karteikarten SET {', '.join(update_fields)} WHERE global_id = ?",
            update_vals,
        )
        db.conn.commit()
        result.conflicts += 1
        return True

    def _insert_from_server(self, db: KarteikartenDB, server_row: Dict) -> None:
        import uuid as _uuid
        global_id = server_row.get("global_id") or str(_uuid.uuid4())
        fields = ["global_id"] + [f for f in _SYNC_FIELDS if f in server_row]
        values = [global_id] + [server_row.get(f) for f in fields[1:]]
        placeholders = ", ".join(["?"] * len(values))
        col_names = ", ".join(fields)
        cur = db.conn.cursor()
        cur.execute(
            f"INSERT OR IGNORE INTO karteikarten ({col_names}) VALUES ({placeholders})",
            values,
        )
        db.conn.commit()

    def _merge_conflict(self, db: KarteikartenDB, local_record: Dict,
                        server_row: Dict, mysql: MySQLConnection, result: SyncResult) -> None:
        """Merge-Strategie bei Versionskonflikt beim Push."""
        # Server gewinnt bei Konflikt, außer bei geschützten Feldern
        protected = _PROTECTED_FIELDS.get(self.source, [])
        cur = mysql.cursor()
        update_parts = []
        update_vals = []
        for f in _SYNC_FIELDS:
            if f in protected and local_record.get(f):
                update_parts.append(f"{f} = %s")
                update_vals.append(local_record[f])
        if update_parts:
            update_vals.append(local_record["global_id"])
            cur.execute(
                f"UPDATE karteikarten SET {', '.join(update_parts)} WHERE global_id = %s",
                update_vals,
            )
            mysql.commit()
        result.conflicts += 1

    # ------------------------------------------------------------------
    # Konfiguration parsen
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_endpoint(url: str):
        """Parst 'host:port/datenbank' oder 'user:pw@host:port/db'."""
        host = ""
        port = 3306
        user = ""
        password = ""
        database = ""
        if not url:
            return host, port, user, password, database
        try:
            # Format: user:pw@host:port/database
            if "@" in url:
                creds, rest = url.split("@", 1)
                if ":" in creds:
                    user, password = creds.split(":", 1)
                else:
                    user = creds
            else:
                rest = url
            if "/" in rest:
                host_part, database = rest.rsplit("/", 1)
            else:
                host_part = rest
            if ":" in host_part:
                host, port_str = host_part.rsplit(":", 1)
                port = int(port_str)
            else:
                host = host_part
        except Exception:
            pass
        return host, port, user, password, database

    def _connect(self) -> MySQLConnection:
        return MySQLConnection(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
        )
