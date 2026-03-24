SELECT
    f.familyID,
    f.marrdate AS fam_marrdate,
    c.citetext AS cited_marrdate,
    f.husband,
    f.wife,
    f.changedate,
    ph.lastname  AS husband_lastname,
    ph.firstname AS husband_firstname,
    pw.lastname  AS wife_lastname,
    pw.firstname AS wife_firstname
FROM tng_families AS f
LEFT JOIN tng_people AS ph
       ON ph.personID = f.husband
      AND ph.gedcom   = f.gedcom
LEFT JOIN tng_people AS pw
       ON pw.personID = f.wife
      AND pw.gedcom   = f.gedcom
LEFT JOIN tng_citations AS c
       ON c.persfamID = f.familyID
      AND c.eventID   = 'MARR'
      AND c.gedcom    = f.gedcom
      AND c.citetext REGEXP
          '^(0?[1-9]|[12][0-9]|3[01]) (JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC) [0-9]{4}$'
WHERE f.marrdate IS NOT NULL
  AND f.marrdate <> ''
  AND f.marrdate REGEXP
      '^[0-9]{1,2} (JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC) [0-9]{4}$'
  AND f.gedcom LIKE '%OFB_Wetzlar%'
GROUP BY f.familyID
ORDER BY f.changedate DESC;