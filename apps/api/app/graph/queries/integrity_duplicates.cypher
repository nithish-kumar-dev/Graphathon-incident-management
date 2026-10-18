// Per label (__LABEL__ substituted from the allowlist): ids held by more than one node.
MATCH (n:__LABEL__)
WITH n.id AS id, count(n) AS copies
WHERE copies > 1
RETURN id, copies
