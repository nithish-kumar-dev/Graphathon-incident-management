// Chunks with their parent document (authorization is re-checked on the parent's classification at
// read time) and how the document links to the graph.
MATCH (d:Document)-[:HAS_CHUNK]->(c:DocumentChunk)
WHERE c.id IN $ids AND c.tenant_id = $tenant_id AND c.env = $env AND d.tenant_id = $tenant_id
OPTIONAL MATCH (dec:Decision)-[:DOCUMENTED_IN]->(d)
WHERE dec.tenant_id = $tenant_id
WITH c, d, collect(DISTINCT {id: dec.id, status: dec.status}) AS decisions
OPTIONAL MATCH (d)-[:RELATES_TO]->(x)
WHERE x.tenant_id = $tenant_id
RETURN properties(c) AS chunk, properties(d) AS document, decisions,
       collect(DISTINCT {id: x.id, label: labels(x)[0]}) AS relates_to
