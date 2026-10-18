MATCH (n) RETURN labels(n)[0] AS label, count(n) AS nodes ORDER BY label
