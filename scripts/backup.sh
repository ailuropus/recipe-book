#!/bin/bash
# Daily backup: the portable JSON bank, and a full pg_dump.
#
# Both, because they fail differently. The JSON survives a schema change or a
# move to another machine but carries only recipes. The pg_dump restores
# everything exactly — revisions, the cost log — but is tied to this schema.
#
# Every file is written from inside a container, which is what keeps this free
# of sudo: Docker creates ./backups owned by root, so a redirect from the host
# would be permission denied, while root inside the container writes there
# happily.
#
# From cron:
#   0 3 * * * /home/YOU/rakamakatui/scripts/backup.sh >> /home/YOU/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."

KEEP_JSON="${KEEP_JSON:-30}"
KEEP_DUMPS="${KEEP_DUMPS:-14}"

log() { printf '%s  %s\n' "$(date -Is)" "$*"; }

log "json export"
docker compose exec -T app recipebook backup --dir /app/backups --keep "$KEEP_JSON" >/dev/null

# Written to a dot-file and renamed on success. pipefail is the point: without
# it a failed pg_dump still leaves a valid gzip of nothing, which is worse than
# no backup because it looks like one.
log "pg_dump"
docker compose exec -T db bash -c '
    set -euo pipefail
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    tmp="/backups/.incomplete-$stamp.sql.gz"
    trap '"'"'rm -f "$tmp"'"'"' EXIT
    pg_dump -U recipebook recipebook | gzip > "$tmp"
    mv "$tmp" "/backups/rakamakatui-$stamp.sql.gz"
    trap - EXIT
    ls -1t /backups/rakamakatui-*.sql.gz | tail -n "+'"$((KEEP_DUMPS + 1))"'" | xargs -r rm -f
'

log "ok — $(ls -1 backups | wc -l | tr -d ' ') files, $(du -sh backups | cut -f1)"
