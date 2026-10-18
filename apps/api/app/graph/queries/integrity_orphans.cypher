// Domain nodes with no relationships at all.
MATCH (n) WHERE NOT n:SchemaMigration
OPTIONAL MATCH (n)-[r]-()
WITH n, count(r) AS degree
WHERE degree = 0
RETURN labels(n)[0] AS label, n.id AS id ORDER BY label, id
