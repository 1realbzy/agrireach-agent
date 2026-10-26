-- Synthetic pre-migration data. No personal contacts or credentials.
CREATE TABLE cases(id INTEGER PRIMARY KEY, question TEXT, crop TEXT, region TEXT,
 draft TEXT, farmer_draft TEXT, sources TEXT, status TEXT, officer TEXT,
 farmer_text TEXT, final_text TEXT, updated_at TEXT);
INSERT INTO cases VALUES(1,'Synthetic maize question','maize','', 'Internal draft',
 NULL,'[]','released','QA Officer','Historical published advice','Internal decision','2026-01-01');
CREATE TABLE tool_log(id INTEGER PRIMARY KEY, actor TEXT, output TEXT);
INSERT INTO tool_log VALUES(1,'QA Officer','Synthetic historical decision');
INSERT INTO cases VALUES(2,'Synthetic pending soybean question','soybean','Tamale',
 'Pending draft',NULL,'[]','pending_review',NULL,NULL,NULL,'2026-01-02');
INSERT INTO tool_log VALUES(2,'agent','Synthetic pending draft record');
