#!/usr/bin/env bash
# Snapshot FalkorDB to backups/falkordb-<UTC timestamp>.rdb. Never modifies graph data.
# BGSAVE SCHEDULE waits out an AOF rewrite in progress (common right after a restart).
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${FALKORDB_HOST_PORT:-56379}"
info() { redis-cli -p "$PORT" INFO persistence | tr -d '\r' | awk -F: -v k="$1" '$1==k{print $2}'; }

before=$(info rdb_saves)   # monotonic counter; rdb_last_save_time has 1s granularity
reply=$(redis-cli -p "$PORT" BGSAVE SCHEDULE)
case "$reply" in
  "Background saving started"|"Background saving scheduled") ;;
  *) echo "BGSAVE refused: $reply" >&2; exit 1 ;;
esac
for _ in $(seq 1 120); do
  if [ "$(info rdb_bgsave_in_progress)" = 0 ] && [ "$(info rdb_saves)" != "$before" ]; then
    break
  fi
  sleep 0.5
done
[ "$(info rdb_saves)" != "$before" ] || { echo "BGSAVE did not complete in 60s" >&2; exit 1; }
[ "$(info rdb_last_bgsave_status)" = ok ] || { echo "BGSAVE failed: $(info rdb_last_bgsave_status)" >&2; exit 1; }

mkdir -p backups
out="backups/falkordb-$(date -u +%Y%m%dT%H%M%SZ).rdb"
docker compose cp falkordb:/var/lib/falkordb/data/dump.rdb "$out" >/dev/null 2>&1
echo "$out ($(wc -c <"$out" | tr -d ' ') bytes)"
