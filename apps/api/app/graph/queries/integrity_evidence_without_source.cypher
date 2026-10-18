MATCH (e:Evidence) WHERE e.source_ref IS NULL OR e.source_ref = '' RETURN e.id AS id
