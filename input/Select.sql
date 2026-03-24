SELECT s.title, 
    c.page, 
    c.citedate, 
    c.persfamID, 
    c.eventID, 
    n.note 
FROM tng_citations AS c 
INNER JOIN tng_sources AS s ON (c.sourceID=s.sourceID AND c.gedcom=s.gedcom) 
INNER JOIN tng_notelinks AS l ON (c.persfamID=l.persfamID AND c.gedcom=l.gedcom) 
INNER JOIN tng_xnotes AS n ON (l.xnoteID=n.ID AND c.gedcom=l.gedcom) 
WHERE c.gedcom LIKE "OFB_Wetzlar" 
    AND s.title LIKE "%Kirchenbuchkartei %" 
    AND NOT (n.note LIKE '%{%') 
    AND (n.note LIKE '%|Abschrift Karteikarte|%') 
GROUP BY c.page, n.note 
ORDER BY s.title, c.page, c.citedate, n.note