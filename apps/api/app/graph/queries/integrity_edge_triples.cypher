MATCH (a)-[r]->(b)
RETURN labels(a)[0] AS src, type(r) AS rel, labels(b)[0] AS dst, count(r) AS edges
ORDER BY src, rel, dst
