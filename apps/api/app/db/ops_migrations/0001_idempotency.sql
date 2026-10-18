-- ops.idempotency_records: one row per side effect the restricted executor performs.
-- key = "<action id>:<spec hash>"; request_hash is the spec hash, so a key reused for a different request is detected.
-- All times are epoch milliseconds from the orchestrator's injected clock.
CREATE TABLE ops.idempotency_records (
    key           text PRIMARY KEY,
    status        text   NOT NULL CHECK (status IN ('in_progress', 'succeeded', 'failed')),
    request_hash  text   NOT NULL,
    response      jsonb,
    attempts      integer NOT NULL DEFAULT 1,
    created_at_ms bigint NOT NULL,
    updated_at_ms bigint NOT NULL,
    expires_at_ms bigint NOT NULL
);
CREATE INDEX idempotency_records_expires_idx ON ops.idempotency_records (expires_at_ms);
