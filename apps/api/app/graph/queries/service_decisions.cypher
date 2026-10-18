// Every Decision governing a service, with its documents and what it supersedes.
// "In effect" is decided by the caller from status + effective dates at a given time.
MATCH (d:Decision)-[:GOVERNS]->(s:Service {id: $service_id})
WHERE s.tenant_id = $tenant_id AND s.env = $env AND d.tenant_id = $tenant_id AND d.env = $env
OPTIONAL MATCH (d)-[:DOCUMENTED_IN]->(doc:Document)
WHERE doc.tenant_id = $tenant_id
WITH d, collect(DISTINCT {id: doc.id, title: doc.title, uri: doc.uri, doc_type: doc.doc_type}) AS documents
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
WHERE old.tenant_id = $tenant_id
RETURN properties(d) AS decision, documents, collect(DISTINCT old.id) AS supersedes
ORDER BY decision.effective_from_ms DESC
