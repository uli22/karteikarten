-- ============================================================
-- Bereinigung _cropped-Datensätze in der Online-MySQL-Datenbank
-- Ausführen via phpMyAdmin oder: mysql -u USER -p DB < cleanup_cropped_online.sql
-- ============================================================

-- Alle Datensätze löschen, bei denen _cropped im dateiname ODER dateipfad steht
DELETE FROM karteikarten
WHERE dateiname LIKE '%_cropped%'
   OR dateipfad LIKE '%_cropped%';

-- Kontrolle (sollte 0 zurückgeben)
SELECT COUNT(*) AS verbleibende_cropped
FROM karteikarten
WHERE dateiname LIKE '%_cropped%'
   OR dateipfad LIKE '%_cropped%';
