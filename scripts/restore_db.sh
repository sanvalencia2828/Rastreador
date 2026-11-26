#!/usr/bin/env bash
# Restaura un respaldo de scripts/backup_db.sh en la base del contenedor db (docker-compose.prod.yml).
#
#   scripts/restore_db.sh /var/backups/rastreador/rastreador_AAAA-MM-DD_HHMMSS.dump [base_destino]
#
# Sin base_destino restaura sobre la base de producción (POSTGRES_DB): para la API mientras tanto y
# BORRA lo que haya. Con otra base (p. ej. restore_test) la crea si no existe y no toca producción:
# úsalo para probar los respaldos. Pide escribir el nombre de la base para confirmar.
# shellcheck disable=SC2016  # las '$VAR' entre comillas simples se expanden dentro del contenedor db
set -euo pipefail

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "uso: $0 ARCHIVO.dump [base_destino]" >&2
    exit 2
fi
file="$1"
[ -f "$file" ] && [ -r "$file" ] || { echo "no se puede leer $file" >&2; exit 1; }

cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f docker-compose.prod.yml)
# < /dev/null: docker compose exec -T lee stdin y se comería la confirmación de abajo
prod_db="$("${COMPOSE[@]}" exec -T db sh -c 'printf %s "$POSTGRES_DB"' < /dev/null)"
target="${2:-$prod_db}"
case "$target" in '' | *[!A-Za-z0-9_]*) echo "nombre de base inválido: $target" >&2; exit 2 ;; esac

"${COMPOSE[@]}" exec -T db pg_restore -l < "$file" > /dev/null || { echo "$file no es un respaldo válido" >&2; exit 1; }

if [ "$target" = "$prod_db" ]; then
    echo "ATENCIÓN: se va a REEMPLAZAR la base de producción '$target' con $file."
    echo "La API se detiene durante la restauración."
else
    echo "Se va a restaurar $file en la base de prueba '$target' (producción no se toca)."
fi
printf "Escribe el nombre de la base (%s) para continuar: " "$target"
read -r answer || answer=""
[ "$answer" = "$target" ] || { echo "cancelado: no coincide" >&2; exit 1; }

if [ "$target" = "$prod_db" ]; then
    "${COMPOSE[@]}" stop api
    trap '"${COMPOSE[@]}" start api' EXIT  # la API vuelve aunque la restauración falle
else
    # TARGET ya se validó (solo letras, números y _), así que puede ir entre comillas en el SQL
    exists="$("${COMPOSE[@]}" exec -T -e TARGET="$target" db sh -c \
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '"'"'$TARGET'"'"'"' < /dev/null)"
    [ "$exists" = "1" ] || "${COMPOSE[@]}" exec -T -e TARGET="$target" db sh -c 'createdb -U "$POSTGRES_USER" "$TARGET"' < /dev/null
fi

# --clean --if-exists: borra lo que existe antes de crearlo; --single-transaction: o todo o nada
"${COMPOSE[@]}" exec -T -e TARGET="$target" db sh -c \
    'pg_restore -U "$POSTGRES_USER" -d "$TARGET" --clean --if-exists --no-owner --single-transaction' < "$file"
echo "restauración terminada en '$target'."
