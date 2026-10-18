// Index metadata (graph-wide, not tenant data). Retrieval checks it because a full-text query on a
// missing index returns no rows instead of an error (FalkorDB 4.22), which would hide a missing migration.
CALL db.indexes() YIELD label, types, options, entitytype
RETURN label, types, options, entitytype
