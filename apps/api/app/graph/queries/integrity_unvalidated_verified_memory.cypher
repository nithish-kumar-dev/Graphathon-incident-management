// A memory may be 'verified' only by a human validator or accepted ground truth with grounding evidence,
// and never when it derives from an action that was only proposed (not executed). It must also record
// how and when it was validated (memories verified before Phase 3 lacked validation_method until re-seeded).
MATCH (m:AgentMemory {verification_status: 'verified'})
OPTIONAL MATCH (m)-[v:VALIDATED_BY]->(:Responder)
WITH m, count(v) AS validators
OPTIONAL MATCH (m)-[g:GROUNDED_IN]->(:Evidence)
WITH m, validators, count(g) AS grounded
OPTIONAL MATCH (m)-[:DERIVED_FROM]->(a:AgentAction)
WITH m, validators, grounded, collect(a.status) AS action_statuses
WHERE grounded = 0
   OR m.validation_method IS NULL OR m.validated_at_ms IS NULL
   OR NOT (validators > 0 OR m.validation_method = 'ground_truth')
   OR any(s IN action_statuses WHERE NOT s IN ['executed_simulated'])
RETURN m.id AS id
