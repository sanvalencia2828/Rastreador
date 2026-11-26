#!/usr/bin/env bash
# Respaldo de la base de producción (docker-compose.prod.yml) con pg_dump en formato custom.
#
#   scripts/backup_db.sh
#
# Escribe /var/backups/rastreador/rastreador_AAAA-MM-DD_HHMMSS.dump (permisos 600) y conserva
# los 14 más recientes. Sale con código distinto de 0 si algo falla; nunca deja un respaldo a medias.
# Variables opcionales: BACKUP_DIR (carpeta destino) y KEEP (cuántos conservar).
#
# Cron de ejemplo (crontab -e del usuario que corre docker; no se instala solo), todos los días 03:15:
#   15 3 * * * /home/deploy/rastreador/scripts/backup_db.sh >> /home/deploy/backup_db.log 2>&1
# shellcheck disable=SC2016  # las '$VAR' entre comillas simples se expanden dentro del contenedor db
set -euo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-/var/backups/rastreador}"
KEEP="${KEEP:-14}"
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f docker-compose.prod.yml)

case "$KEEP" in '' | *[!0-9]* | 0) echo "KEEP debe ser un entero mayor que 0" >&2; exit 2 ;; esac
mkdir -p "$BACKUP_DIR"
[ -w "$BACKUP_DIR" ] || { echo "no se puede escribir en $BACKUP_DIR" >&2; exit 1; }

stamp="$(date +%Y-%m-%d_%H%M%S)"
final="$BACKUP_DIR/rastreador_${stamp}.dump"
tmp="$final.partial"
trap 'rm -f "$tmp"' EXIT

# -T: sin TTY (cron). Las variables se expanden dentro del contenedor, no en este shell.
"${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$tmp"
[ -s "$tmp" ] || { echo "pg_dump no produjo datos" >&2; exit 1; }
# comprueba que el archivo es un respaldo legible antes de darlo por bueno
"${COMPOSE[@]}" exec -T db pg_restore -l < "$tmp" > /dev/null

chmod 600 "$tmp"
mv "$tmp" "$final"
trap - EXIT

# conserva los KEEP más recientes (los nombres llevan la fecha, así que el orden alfabético es cronológico)
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'rastreador_*.dump' -print | sort -r | tail -n +"$((KEEP + 1))" |
    while IFS= read -r old; do rm -f -- "$old"; done

echo "$(date '+%F %T') respaldo listo: $final ($(du -h "$final" | cut -f1))"
