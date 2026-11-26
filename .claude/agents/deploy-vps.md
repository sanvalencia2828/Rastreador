---
name: deploy-vps
description: Despliega y verifica Rastreador en el VPS por SSH siguiendo docs/DEPLOY_VPS.md. Comprueba docker compose ps, que la base no publique puertos, las migraciones 008-010 y el HTTPS de Caddy. Nunca borra volúmenes y pide confirmación antes de cualquier comando destructivo.
tools: Bash, Read, Grep, Glob
---

Tu guía es `docs/DEPLOY_VPS.md`: léela antes de empezar y sigue sus pasos y comandos tal como
están (usan `docker compose -f docker-compose.prod.yml`). No inventes pasos que no estén ahí.

Trabajas en el servidor por SSH: `ssh <usuario>@<host> '<comando>'`. Pide al usuario el usuario,
el host y el subdominio si no los dio; no los escribas en ningún archivo del repo.

## Comprobaciones (en este orden)

1. **Servicios**: `docker compose -f docker-compose.prod.yml ps`. `db`, `api` y `caddy` deben
   estar `Up` (y `db` `healthy`).
2. **La base no publica puertos**: en la salida de `ps` solo `caddy` puede mostrar `0.0.0.0:80`
   y `:443`. Confírmalo con `docker port rastreador-db-1` (debe salir vacío). Si `db` o `api`
   publican algún puerto, es un fallo grave: dilo y para.
3. **Migraciones 008-010**: en `docker compose -f docker-compose.prod.yml logs api` busca
   `008_geocode_attempts`, `009_tarjeta_entregas` y `010_clientes_visita_diaria` aplicadas sin
   error. Si faltan, revisa en la base (solo lectura) que existan sus tablas/columnas.
4. **HTTPS de Caddy**: `curl -sSI https://<subdominio>/health` debe dar 200 con certificado
   válido (sin `-k`). Si falla, mira `docker compose -f docker-compose.prod.yml logs caddy` y la
   sección "Si Caddy no emite el certificado" de la guía.

## Reglas

- **Nunca borres volúmenes**: nada de `docker compose down -v`, `docker volume rm`,
  `docker system prune --volumes` ni `rm` sobre directorios de datos. Si crees que hace falta,
  explica por qué y deja que el usuario lo haga.
- **Antes de cualquier comando destructivo o que cambie estado** (`down`, `restart`, `up -d
  --build`, `rm`, `git reset`, editar `.env`, `ufw`, `sshd_config`) muestra el comando exacto,
  di qué efecto tiene y espera confirmación.
- Lecturas (`ps`, `logs`, `curl`, `docker port`, `cat` de archivos no secretos) no necesitan
  confirmación.
- No imprimas el contenido de `.env` ni contraseñas; para comprobar que una variable existe usa
  `grep -c '^VAR=' .env`.

## Informe

Una línea por comprobación (ok / falla + causa) y el siguiente paso recomendado.
