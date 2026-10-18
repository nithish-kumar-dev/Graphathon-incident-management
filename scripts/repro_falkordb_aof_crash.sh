#!/usr/bin/env bash
# Minimal reproduction of the FalkorDB AOF-replay segfault (docs/schema/falkordb.md, "Known server issue").
# Uses a throwaway container on 127.0.0.1:56399 and never touches the project's volumes.
#   scripts/repro_falkordb_aof_crash.sh [image]     default: the image pinned in docker-compose.yml
# Exit 0 = bug NOT reproduced (safe to relax the guards); exit 1 = bug reproduced.
set -uo pipefail
IMAGE="${1:-falkordb/falkordb:v4.22.0}"
NAME=fdb-aof-repro; PORT=56399
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1; }
trap cleanup EXIT
cleanup
docker run -d --name "$NAME" -p 127.0.0.1:$PORT:6379 -e BROWSER=0 -e REDIS_ARGS="--appendonly yes" "$IMAGE" >/dev/null
wait_up() { for _ in $(seq 1 20); do redis-cli -p $PORT PING 2>/dev/null | grep -q PONG && return 0; sleep 0.5; done; return 1; }
wait_up || { echo "container did not start"; exit 2; }
for i in 1 2 3; do
  g="g$i"
  redis-cli -p $PORT GRAPH.QUERY "$g" "CREATE INDEX FOR (n:A) ON (n.id)" >/dev/null
  redis-cli -p $PORT GRAPH.CONSTRAINT CREATE "$g" UNIQUE NODE A PROPERTIES 1 id >/dev/null
  sleep 0.5
  redis-cli -p $PORT GRAPH.QUERY "$g" "CREATE (:A {id:'x'})" >/dev/null
  redis-cli -p $PORT GRAPH.DELETE "$g" >/dev/null          # drops the constraint with the graph
  docker restart "$NAME" >/dev/null
  if ! wait_up; then
    echo "REPRODUCED on $IMAGE: server crash-looping after restart $i"
    docker logs "$NAME" 2>&1 | grep -m1 -E "crashed by signal"
    exit 1
  fi
done
echo "NOT reproduced on $IMAGE after 3 cycles"
