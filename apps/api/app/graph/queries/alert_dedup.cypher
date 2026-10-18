// Sliding-window dedup in ONE write query (FalkorDB executes each query atomically, one writer per graph).
// Finds the nearest alert with the same fingerprint within [at - window, at + window].
//   replay = this exact event (same source_ref) was already ingested: nothing changes.
//   otherwise: count it as a repeat and remember its source_ref (bounded list) for future replays.
MATCH (a:Alert {fingerprint: $fingerprint})
WHERE a.tenant_id = $tenant_id AND a.env = $env AND a.fired_at_ms >= $lo AND a.fired_at_ms <= $hi
WITH a ORDER BY abs(a.fired_at_ms - $at), a.id LIMIT 1
WITH a, (a.source_ref = $source_ref OR $source_ref IN coalesce(a.dedup_source_refs, [])) AS replay
SET a.dedup_count = coalesce(a.dedup_count, 0) + CASE WHEN replay THEN 0 ELSE 1 END,
    a.dedup_source_refs = CASE
        WHEN replay OR size(coalesce(a.dedup_source_refs, [])) >= $max_refs THEN coalesce(a.dedup_source_refs, [])
        ELSE coalesce(a.dedup_source_refs, []) + $source_ref END,
    a.last_fired_at_ms = CASE
        WHEN replay THEN coalesce(a.last_fired_at_ms, a.fired_at_ms)
        WHEN $at > coalesce(a.last_fired_at_ms, a.fired_at_ms) THEN $at
        ELSE coalesce(a.last_fired_at_ms, a.fired_at_ms) END,
    a.updated_at_ms = CASE WHEN replay THEN a.updated_at_ms ELSE $now_ms END
RETURN a.id AS alert_id, replay, a.dedup_count AS dedup_count
