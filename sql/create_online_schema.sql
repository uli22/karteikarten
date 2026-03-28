-- ============================================================
-- Online-Schema fuer Wetzlar-Karteikarten (Lima-City MySQL)
-- Zeichensatz: utf8mb4_general_ci
-- Ausfuehren:  mysql -u <user> -p <datenbank> < create_online_schema.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS `karteikarten` (
    `global_id`         VARCHAR(36)    NOT NULL,
    `dateiname`         VARCHAR(512)   DEFAULT NULL,
    `dateipfad`         VARCHAR(1024)  DEFAULT NULL,
    `kirchengemeinde`   VARCHAR(256)   DEFAULT NULL,
    `ereignis_typ`      VARCHAR(64)    DEFAULT NULL,
    `jahr`              SMALLINT       DEFAULT NULL,
    `datum`             VARCHAR(32)    DEFAULT NULL,
    `iso_datum`         VARCHAR(16)    DEFAULT NULL,
    `seite`             VARCHAR(32)    DEFAULT NULL,
    `nummer`            VARCHAR(32)    DEFAULT NULL,
    `erkannter_text`    TEXT           DEFAULT NULL,
    `ocr_methode`       VARCHAR(64)    DEFAULT NULL,
    `kirchenbuchtext`   TEXT           DEFAULT NULL,
    `vorname`           VARCHAR(256)   DEFAULT NULL,
    `nachname`          VARCHAR(256)   DEFAULT NULL,
    `partner`           VARCHAR(256)   DEFAULT NULL,
    `beruf`             VARCHAR(256)   DEFAULT NULL,
    `todestag`          VARCHAR(64)    DEFAULT NULL,
    `ort`               VARCHAR(256)   DEFAULT NULL,
    `geb_jahr_gesch`    SMALLINT       DEFAULT NULL,
    `stand`             VARCHAR(128)   DEFAULT NULL,
    `braeutigam_stand`  VARCHAR(128)   DEFAULT NULL,
    `braeutigam_vater`  VARCHAR(256)   DEFAULT NULL,
    `braut_vater`       VARCHAR(256)   DEFAULT NULL,
    `braut_nachname`    VARCHAR(256)   DEFAULT NULL,
    `braut_ort`         VARCHAR(256)   DEFAULT NULL,
    `notiz`             VARCHAR(32)    DEFAULT NULL,
    `fid`               VARCHAR(64)    DEFAULT NULL,
    `gramps`            VARCHAR(32)    DEFAULT NULL,
    `fid_reader`        VARCHAR(256)   DEFAULT NULL,
    `fid_erkennung`     VARCHAR(256)   DEFAULT NULL,
    -- Sync-Metadaten
    `version`           INT            NOT NULL DEFAULT 1,
    `updated_by`        VARCHAR(64)    DEFAULT NULL,
    `aktualisiert_am`   DATETIME       DEFAULT NULL,
    `erstellt_am`       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`global_id`),
    INDEX `idx_aktualisiert_am` (`aktualisiert_am`),
    INDEX `idx_fid`             (`fid`),
    INDEX `idx_fid_reader`      (`fid_reader`),
    INDEX `idx_fid_erkennung`   (`fid_erkennung`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_general_ci;

-- Sync-Zustandstabelle (wird von OnlineSyncService genutzt)
CREATE TABLE IF NOT EXISTS `sync_state` (
    `state_key`   VARCHAR(64) NOT NULL,
    `state_value` TEXT        DEFAULT NULL,
    PRIMARY KEY (`state_key`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_general_ci;
