<?php
/*
 * Minimaler Sync-Endpunkt fuer Lima-City (MySQL 8, PHP 8+).
 *
 * Deployment:
 * 1) Datei auf den Webspace laden (z.B. /sync/lima_sync_endpoint.php)
 * 2) DB-Zugang unten eintragen
 * 3) API-Key unten setzen
 * 4) In der Desktop-App Modus "api" + Endpoint-URL + API-Key eintragen
 */

declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

## const SYNC_API_KEY = 'JtrMbGcHUANrVBTShi52WZaUvYDGsZCX';
## const DB_HOST = 'localhost';
## const DB_USER = 'USER408012_WZE';
## const DB_PASSWORD = 'WETZLAR#22#';
## const DB_NAME = 'db_408012_26';
## const DB_PORT = 3306;

const SYNC_API_KEY = 'JtrMbGcHUANrVBTShi52WZaUvYDGsZCX';
const DB_HOST = 'localhost';
const DB_USER = 'USER408012_wze';
const DB_PASSWORD = 'WETZLAR#22#';
const DB_NAME = 'db_408012_26';
const DB_PORT = 3306;

function out(array $payload, int $status = 200): void {
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

// Robuste Eingabe: form-encoded Feld "payload" bevorzugt (funktioniert auf allen Shared-Hosts),
// Fallback auf raw JSON body (fuer direkte API-Clients).
$raw = '';
if (isset($_POST['payload']) && $_POST['payload'] !== '') {
    $raw = (string)$_POST['payload'];
} else {
    $raw = (string)file_get_contents('php://input');
}
if ($raw === '') {
    out(['ok' => false, 'error' => 'Leerer Request-Body'], 400);
}

$data = json_decode($raw, true);
if (!is_array($data)) {
    out(['ok' => false, 'error' => 'Ungültiges JSON'], 400);
}

$providedKey = (string)($data['api_key'] ?? '');
if ($providedKey === '' || !hash_equals(SYNC_API_KEY, $providedKey)) {
    out(['ok' => false, 'error' => 'Unauthorized'], 401);
}

if (($data['action'] ?? '') === 'ping') {
    out(['ok' => true, 'pong' => true, 'server_time' => gmdate('Y-m-d H:i:s')]);
}

$batchSize = max(1, min(500, (int)($data['batch_size'] ?? 100)));
$lastPull = (string)($data['last_pull'] ?? '1970-01-01 00:00:00');
$lastPullId = (string)($data['last_pull_id'] ?? '');
$pending = $data['pending'] ?? [];
if (!is_array($pending)) {
    out(['ok' => false, 'error' => 'pending muss ein Array sein'], 400);
}

if (!class_exists('mysqli')) {
    out(['ok' => false, 'error' => 'PHP-Erweiterung mysqli fehlt auf dem Server'], 500);
}

try {
    $mysqli = new mysqli(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT);
} catch (Throwable $e) {
    out(['ok' => false, 'error' => 'DB init failed: ' . $e->getMessage()], 500);
}

if ($mysqli->connect_errno) {
    out(['ok' => false, 'error' => 'DB connect failed: ' . $mysqli->connect_error], 500);
}
if (!$mysqli->set_charset('utf8mb4')) {
    out(['ok' => false, 'error' => 'set_charset fehlgeschlagen: ' . $mysqli->error], 500);
}

$allFields = [
    'dateiname', 'dateipfad', 'kirchengemeinde', 'ereignis_typ',
    'jahr', 'datum', 'iso_datum', 'seite', 'nummer',
    'erkannter_text', 'ocr_methode', 'kirchenbuchtext',
    'vorname', 'nachname', 'partner', 'beruf', 'todestag', 'ort',
    'geb_jahr_gesch', 'stand', 'braeutigam_stand', 'braeutigam_vater',
    'braut_vater', 'braut_nachname', 'braut_ort',
    'notiz', 'fid', 'gramps',
    'fid_reader', 'fid_erkennung',
    'version', 'updated_by', 'aktualisiert_am'
];

$acked = [];
$errors = [];

$mysqli->begin_transaction();
try {
    foreach ($pending as $item) {
        $queueId = (int)($item['queue_id'] ?? 0);
        $globalId = (string)($item['global_id'] ?? '');
        $op = (string)($item['op'] ?? 'upsert');
        $baseVersion = max(1, (int)($item['base_version'] ?? 1));

        if ($globalId === '') {
            $errors[] = ['id' => $queueId, 'error' => 'global_id fehlt'];
            continue;
        }

        if ($op === 'delete') {
            $stmt = $mysqli->prepare('DELETE FROM karteikarten WHERE global_id = ?');
            if (!$stmt) {
                $errors[] = ['id' => $queueId, 'error' => $mysqli->error];
                continue;
            }
            $stmt->bind_param('s', $globalId);
            if (!$stmt->execute()) {
                $errors[] = ['id' => $queueId, 'error' => $stmt->error];
            } else {
                $acked[] = $queueId;
            }
            $stmt->close();
            continue;
        }

        $record = $item['record'] ?? null;
        if (!is_array($record)) {
            $errors[] = ['id' => $queueId, 'error' => 'record fehlt'];
            continue;
        }

        $sv = 0;
        $gidEsc = $mysqli->real_escape_string($globalId);
        $resVersion = $mysqli->query("SELECT version FROM karteikarten WHERE global_id = '" . $gidEsc . "' LIMIT 1");
        if ($resVersion instanceof mysqli_result) {
            $row = $resVersion->fetch_assoc();
            if ($row && isset($row['version'])) {
                $sv = (int)$row['version'];
            }
            $resVersion->close();
        }

        if ($sv > $baseVersion) {
            $errors[] = ['id' => $queueId, 'error' => 'Versionkonflikt', 'server_version' => $sv];
            continue;
        }

        $cols = ['global_id'];
        $vals = [$globalId];
        foreach ($allFields as $f) {
            if ($f === 'aktualisiert_am') continue; // wird server-seitig mit NOW() gesetzt
            if (array_key_exists($f, $record)) {
                $cols[] = $f;
                $vals[] = $record[$f];
            }
        }

        // aktualisiert_am immer mit Server-NOW() setzen, damit der Pull-Cursor korrekt
        // funktioniert unabhaengig von lokaler Client-Zeitzone (UTC vs. UTC+1).
        $colsWithNow = array_merge($cols, ['aktualisiert_am']);
        $placeholders = implode(', ', array_fill(0, count($cols), '?')) . ', NOW()';

        $updates = [];
        foreach ($cols as $c) {
            if ($c !== 'global_id') {
                $updates[] = "`$c` = VALUES(`$c`)";
            }
        }
        $updates[] = '`aktualisiert_am` = NOW()';

        $sql = 'INSERT INTO karteikarten (`' . implode('`,`', $colsWithNow) . '`) VALUES (' . $placeholders . ') '
             . 'ON DUPLICATE KEY UPDATE ' . implode(', ', $updates);

        $stmt = $mysqli->prepare($sql);
        if (!$stmt) {
            $errors[] = ['id' => $queueId, 'error' => $mysqli->error];
            continue;
        }

        $intFields = [
            'jahr' => true,
            'geb_jahr_gesch' => true,
            'version' => true,
        ];

        $typeChars = [];
        $bound = [];
        foreach ($vals as $k => $v) {
            $col = $cols[$k] ?? '';
            if (isset($intFields[$col])) {
                if ($v === null || $v === '') {
                    $bound[$k] = null;
                    $typeChars[] = 's';
                } else {
                    $bound[$k] = (int)$v;
                    $typeChars[] = 'i';
                }
            } else {
                $bound[$k] = ($v === null) ? null : (string)$v;
                $typeChars[] = 's';
            }
        }
        $types = implode('', $typeChars);
        $refs = [];
        $refs[] = &$types;
        foreach ($bound as $k => &$v) {
            $refs[] = &$v;
        }
        call_user_func_array([$stmt, 'bind_param'], $refs);

        if (!$stmt->execute()) {
            $errors[] = ['id' => $queueId, 'error' => $stmt->error];
        } else {
            $acked[] = $queueId;
        }
        $stmt->close();
    }

    $pull = [];
    $newCursor = $lastPull;
    $newCursorId = $lastPullId;

    $lastPullEsc = $mysqli->real_escape_string($lastPull);
    $lastPullIdEsc = $mysqli->real_escape_string($lastPullId);
    $limit = (int)$batchSize;
    $resPull = $mysqli->query(
        "SELECT * FROM karteikarten "
        . "WHERE (aktualisiert_am > '" . $lastPullEsc . "') "
        . "   OR (aktualisiert_am = '" . $lastPullEsc . "' AND global_id > '" . $lastPullIdEsc . "') "
        . "ORDER BY aktualisiert_am ASC, global_id ASC LIMIT " . $limit
    );
    if ($resPull instanceof mysqli_result) {
        while ($row = $resPull->fetch_assoc()) {
            $pull[] = $row;
            $rowTs = (string)($row['aktualisiert_am'] ?? '');
            $rowId = (string)($row['global_id'] ?? '');
            if ($rowTs !== '') {
                if ($rowTs > $newCursor || ($rowTs === $newCursor && $rowId > $newCursorId)) {
                    $newCursor = $rowTs;
                    $newCursorId = $rowId;
                }
            }
        }
        $resPull->close();
    }

    $mysqli->commit();

    $remoteTotal = 0;
    $resCount = $mysqli->query("SELECT COUNT(*) AS c FROM karteikarten");
    if ($resCount instanceof mysqli_result) {
        $rowCount = $resCount->fetch_assoc();
        if ($rowCount && isset($rowCount['c'])) {
            $remoteTotal = (int)$rowCount['c'];
        }
        $resCount->close();
    }

    out([
        'ok' => true,
        'acked_ids' => $acked,
        'errors' => $errors,
        'pull' => $pull,
        'last_pull' => $newCursor,
        'last_pull_id' => $newCursorId,
        'remote_total' => $remoteTotal,
    ]);
} catch (Throwable $e) {
    $mysqli->rollback();
    out(['ok' => false, 'error' => 'Serverfehler: ' . $e->getMessage()], 500);
} finally {
    $mysqli->close();
}
