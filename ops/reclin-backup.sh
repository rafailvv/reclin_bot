#!/bin/sh
# Host-level recovery copies for all Reclin databases; no Telegram messages.
set -eu
umask 077
backup_root=${RECLIN_BACKUP_DIR:-/var/backups/reclin}
install -d -m 700 "$backup_root"
exec 9>"$backup_root/.lock"
flock -n 9 || exit 0
stamp=$(date -u +%Y%m%dT%H%M%SZ)
for container in reclin_postgres reclin_therapy_bot_db_1 reclin_neurology_bot_db_1 reclin_pediatrics_bot_db_1 reclin_endo_bot_db_1; do
    target="$backup_root/$stamp-$container.dump"
    trap 'rm -f -- "$target.partial"' EXIT HUP INT TERM
    docker exec "$container" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$target.partial"
    docker exec -i "$container" pg_restore --list < "$target.partial" > /dev/null
    mv "$target.partial" "$target"
    printf '%s: backup verified\n' "$container"
done
# Only remove completed archives from this job after a successful full run.
find "$backup_root" -maxdepth 1 -type f -name '*-reclin_*.dump' -mtime +14 -delete
