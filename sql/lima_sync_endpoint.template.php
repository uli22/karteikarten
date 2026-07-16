<?php
/*
 * Minimaler Sync-Endpunkt fuer Lima-City (MySQL 8, PHP 8+).
 *
 * Deployment:
 * 1) Diese Datei als lima_sync_endpoint.php kopieren
 * 2) DB-Zugang unten eintragen
 * 3) API-Key unten setzen
 * 4) In der Desktop-App Modus "api" + Endpoint-URL + API-Key eintragen
 */

declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

// === HIER EIGENE CREDENTIALS EINTRAGEN ===
const SYNC_API_KEY = 'DEIN_API_KEY_HIER';
const DB_HOST = 'localhost';
const DB_USER = 'DEIN_DB_USER';
const DB_PASSWORD = 'DEIN_DB_PASSWORT';
const DB_NAME = 'DEIN_DB_NAME';
const DB_PORT = 3306;
// =========================================

function out(array $payload, int $status = 200): void {
    http_response_code($status);
