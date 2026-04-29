import sqlite3

conn = sqlite3.connect('karteireader.db')
cur = conn.cursor()

# Alle Datensätze löschen, bei denen _cropped im dateiname ODER dateipfad steht
cur.execute("SELECT COUNT(*) FROM karteikarten WHERE dateiname LIKE '%_cropped%' OR dateipfad LIKE '%_cropped%'")
anzahl = cur.fetchone()[0]
print(f'Zu löschende _cropped-Datensätze: {anzahl}')

cur.execute("DELETE FROM karteikarten WHERE dateiname LIKE '%_cropped%' OR dateipfad LIKE '%_cropped%'")
print(f'Gelöscht: {cur.rowcount}')

conn.commit()
conn.close()
print('Fertig.')
