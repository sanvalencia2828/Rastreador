# Desplegar Rastreador en un VPS (Hostinger, Ubuntu + Docker)

Guía paso a paso para poner en producción la **API + Postgres/PostGIS + Caddy** en un VPS. Caddy
pide y renueva solo el certificado HTTPS. El **frontend sigue en Vercel** y llama a la API por
`BACKEND_URL=https://<tu-subdominio>`.

Archivos que se usan (todos en la raíz del repo):

| Archivo | Para qué |
|---|---|
| `docker-compose.prod.yml` | Los tres servicios: `db`, `api` y `caddy`. Solo `caddy` publica puertos (80 y 443). |
| `Caddyfile` | HTTPS automático y proxy hacia la API. |
| `.env.prod.example` | Plantilla del `.env` del servidor (sin secretos reales). |
| `scripts/backup_db.sh`, `scripts/restore_db.sh` | Respaldo y restauración de la base. |

> **Cómo leer los comandos.** Los bloques que empiezan con `# en tu PC` se escriben en tu
> computadora (PowerShell o Git Bash en Windows). Todo lo demás se escribe **en el servidor**,
> después de conectarte con `ssh`. Donde aparece `<IP-DEL-VPS>`, `<tu-subdominio>`, etc.,
> reemplázalo por tu valor, **sin** los signos `< >`.

> **La base de datos nunca queda abierta a internet.** No tiene puertos publicados: se usa desde
> la API, con `docker compose exec` en el servidor o, si hace falta, con un túnel SSH (paso f).

---

## a) Preparar el VPS

En el panel de Hostinger elige la plantilla **Ubuntu con Docker**. Anota la **IP** del VPS y la
contraseña de `root`.

### 1. Primera conexión y actualización

```bash
# en tu PC
ssh root@<IP-DEL-VPS>
```

```bash
apt update && apt upgrade -y
```

Si al terminar te dice que hace falta reiniciar, ejecuta `reboot`, espera un minuto y vuelve a
conectarte.

### 2. Crear un usuario normal (no root)

Trabajar como `root` es peligroso: un error borra cualquier cosa. Crea el usuario `deploy` y
dale permisos de administración (`sudo`) y de Docker:

```bash
adduser deploy                 # pide una contraseña: guárdala, la usa sudo
usermod -aG sudo,docker deploy
```

### 3. Llave SSH (para entrar sin contraseña)

En tu PC, si todavía no tienes una llave:

```bash
# en tu PC
ssh-keygen -t ed25519 -C "mi-pc"
```

Pulsa Enter para aceptar la ruta por defecto y elige una frase de paso. Después copia la llave
pública al servidor:

```bash
# en tu PC (Git Bash, Linux o macOS)
ssh-copy-id deploy@<IP-DEL-VPS>
```

```powershell
# en tu PC con PowerShell (Windows no trae ssh-copy-id)
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh deploy@<IP-DEL-VPS> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**Abre otra terminal** y prueba que entras sin que te pida la contraseña del servidor:

```bash
# en tu PC
ssh deploy@<IP-DEL-VPS>
```

### 4. Desactivar el acceso por contraseña

Hazlo **solo cuando el paso anterior funcione**: si no, te quedas fuera del servidor. Desde la
sesión de `deploy`:

```bash
sudo tee /etc/ssh/sshd_config.d/00-solo-llave.conf > /dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -Ei 'passwordauthentication|permitrootlogin'
```

Las dos líneas deben decir `no`. El archivo empieza por `00-` a propósito: SSH se queda con el
primer valor que lee, y algunas imágenes traen otro archivo que activa la contraseña. **Sin cerrar
esta sesión**, abre otra terminal y comprueba que `ssh deploy@<IP-DEL-VPS>` sigue entrando.

### 5. Cortafuegos (ufw): solo 22, 80 y 443

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp          # HTTP/3, opcional
sudo ufw enable
sudo ufw status verbose
```

Si el panel de Hostinger tiene su propio **firewall**, abre ahí también 22, 80 y 443.

> Docker abre por su cuenta los puertos que publica un contenedor, sin pasar por ufw. Por eso
> `docker-compose.prod.yml` solo publica 80 y 443 (Caddy); la base y la API no publican ninguno.

### 6. Actualizaciones de seguridad automáticas

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades    # responde "Sí"
```

### 7. Confirmar que Docker funciona

Sal y vuelve a entrar como `deploy` (`exit` y luego `ssh deploy@<IP-DEL-VPS>`) para que el grupo
`docker` se aplique, y después:

```bash
docker run --rm hello-world
docker compose version
```

Si `docker compose version` falla, instala el plugin con `sudo apt install -y docker-compose-plugin`.

---

## b) DNS: apuntar el subdominio al VPS

En el panel donde administras tu dominio, crea un **registro A**:

| Tipo | Nombre | Valor | TTL |
|---|---|---|---|
| A | `api` (para `api.tudominio.com`) | `<IP-DEL-VPS>` | 300 o el mínimo |

Si existe un registro **AAAA** para ese nombre que apunta a otro lado, bórralo: Let's Encrypt
puede intentar validar por IPv6 y fallar.

Comprueba desde tu PC que el nombre ya resuelve a la IP del VPS (puede tardar de minutos a unas
horas):

```bash
# en tu PC
nslookup api.tudominio.com
```

**Sin dominio propio:** Hostinger da un nombre del tipo `srvXXXX.hstgr.cloud` para el VPS. Puede
que Caddy consiga emitir un certificado para ese nombre, pero no está comprobado: pruébalo
poniéndolo en `API_DOMAIN` y revisa `docker compose -f docker-compose.prod.yml logs caddy`. Si
falla, usa un subdominio propio.

---

## c) Clonar el repo y preparar `.env`

```bash
cd ~
git clone https://github.com/Sanvalencia2828/rastreador.git
cd rastreador
git checkout <rama-a-desplegar>      # la rama o etiqueta aprobada para producción
```

Si el repo es privado, GitHub pide usuario y un **token** (Settings → Developer settings →
Personal access tokens) en lugar de tu contraseña. Dale solo permiso de lectura del repo.

Crea el `.env` del servidor a partir de la plantilla, con permisos solo para tu usuario:

```bash
cp .env.prod.example .env
chmod 600 .env
mkdir -p .data && chmod 700 .data     # aquí irán los CSV privados (paso f)
```

Genera los dos secretos y copia cada resultado:

```bash
openssl rand -hex 32                          # -> JWT_SECRET_KEY
openssl rand -base64 24 | tr '+/' '-_'        # -> POSTGRES_PASSWORD
```

La contraseña de la base va dentro de una URL (`DATABASE_URL`), por eso el `tr` cambia `+` y `/`
por `-` y `_`. No uses `$` ni comillas.

Edita el archivo:

```bash
nano .env
```

Rellena:

- `API_DOMAIN`: tu subdominio, p. ej. `api.tudominio.com` (sin `https://`).
- `POSTGRES_PASSWORD` y `JWT_SECRET_KEY`: los valores que acabas de generar.
- `CORS_ORIGINS`: la URL de Vercel (`https://tu-proyecto.vercel.app`) y tu dominio del frontend
  si tienes uno, separados por coma y sin barra final.
- Deja `OSRM_URL=` vacío y `REGISTRATION_ENABLED=true` por ahora.

Guarda con `Ctrl+O`, Enter, y sal con `Ctrl+X`. Comprueba que no quedó ningún `cambia-`:

```bash
grep -n 'cambia-' .env || echo "OK: sin valores de ejemplo"
```

Guarda una copia de estos secretos en tu gestor de contraseñas. **Nunca** subas `.env` a git
(ya está en `.gitignore`).

---

## d) Levantar todo

```bash
cd ~/rastreador
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

La primera compilación tarda unos minutos. En `ps` deben verse `db` y `api` como `healthy`, y
`caddy` como `Up`. En la columna de puertos solo `caddy` debe mostrar `0.0.0.0:80` y `:443`;
`db` y `api` solo muestran puertos internos (`5432/tcp`, `8000/tcp`).

Comprueba la API por HTTPS (desde el servidor o desde tu PC):

```bash
curl https://<tu-subdominio>/health
```

Debe responder `{"status":"ok",...}`. Si da error de certificado, mira la sección
[Si Caddy no emite el certificado](#si-caddy-no-emite-el-certificado).

Para ver qué pasa: `docker compose -f docker-compose.prod.yml logs -f api` (sal con `Ctrl+C`).
La API crea o actualiza las tablas sola al arrancar, migraciones incluidas.

---

## e) Crear tu cuenta y cerrar el registro

Crea tu usuario con `scripts/seed_demo_user.py` dentro del contenedor `api`. Con `read -s` la
contraseña no se ve en pantalla ni queda en el historial del shell (`-e DEMO_PASSWORD` sin `=`
toma el valor de la variable, sin escribirlo en el comando):

```bash
cd ~/rastreador
read -r -p "Usuario: " DEMO_USER
read -r -s -p "Contraseña (mínimo 12 caracteres): " DEMO_PASSWORD; echo
export DEMO_USER DEMO_PASSWORD
docker compose -f docker-compose.prod.yml exec -e DEMO_USER -e DEMO_PASSWORD api python scripts/seed_demo_user.py
unset DEMO_USER DEMO_PASSWORD
```

Debe decir `Demo user '<usuario>' ready`. Ahora cierra el registro de cuentas nuevas:

```bash
sed -i 's/^REGISTRATION_ENABLED=.*/REGISTRATION_ENABLED=false/' .env
docker compose -f docker-compose.prod.yml up -d api
```

Usa `up -d`, no `restart`: `restart` no vuelve a leer el `.env`. Compruébalo:

```bash
curl -s -X POST https://<tu-subdominio>/auth/register -H 'Content-Type: application/json' \
     -d '{"username":"prueba","password":"una-clave-cualquiera"}'
```

Debe responder `{"detail":"Registro cerrado"}`.

---

## f) Cargar clientes y negocios, y geocodificar

Los CSV tienen datos privados: van en `~/rastreador/.data/`, que está fuera de git y que el
contenedor `api` ve como `/app/.data` (solo lectura). Súbelos desde tu PC:

```bash
# en tu PC
scp clientes.csv deploy@<IP-DEL-VPS>:~/rastreador/.data/
scp filtered.csv deploy@<IP-DEL-VPS>:~/rastreador/.data/
```

Todas las cargas se corren **dentro del contenedor** con `docker compose exec`. La base no se
expone a internet.

> **Si escribes estos comandos en Git Bash en Windows** (por ejemplo, contra un Docker de prueba
> en tu PC), antepón `MSYS_NO_PATHCONV=1`: Git Bash reescribe rutas como `/app/...` o `/tmp/...`
> y el script no encuentra el archivo. En el servidor (Linux) no hace falta.

### Clientes (`scripts/seed_clientes.py`)

En producción el script exige `--confirm-production` **también para el ensayo**. Primero ensaya
(no escribe nada y solo muestra conteos):

```bash
cd ~/rastreador
docker compose -f docker-compose.prod.yml exec api \
  python scripts/seed_clientes.py --csv /app/.data/clientes.csv --user <tu-usuario> --confirm-production
```

Si dice `N filas validas` sin problemas, carga de verdad:

```bash
docker compose -f docker-compose.prod.yml exec api \
  python scripts/seed_clientes.py --csv /app/.data/clientes.csv --user <tu-usuario> --apply --confirm-production
```

Si muestra problemas `(línea, columna, código)`, corrige el CSV en tu PC, vuelve a subirlo y
repite el ensayo. Puedes cargar el mismo CSV varias veces sin duplicar filas.

### Negocios (`load_filtered_cnpj.py`)

Sin `--apply` es un ensayo de solo lectura:

```bash
docker compose -f docker-compose.prod.yml exec api python load_filtered_cnpj.py /app/.data/filtered.csv
```

Revisa los conteos de filas válidas y rechazadas, y después:

```bash
docker compose -f docker-compose.prod.yml exec api python load_filtered_cnpj.py /app/.data/filtered.csv --apply
```

### Geocodificar (`enriquecer_lojas.py`)

Consulta Nominatim con las direcciones de los negocios, a una consulta por segundo, así que con
muchos negocios tarda horas. Córrelo dentro de `tmux` para que siga aunque se corte tu conexión:

```bash
command -v tmux || sudo apt install -y tmux
tmux new -s geocode
cd ~/rastreador
docker compose -f docker-compose.prod.yml exec api python enriquecer_lojas.py
```

Para salir sin detenerlo: `Ctrl+B` y luego `D`. Para volver a verlo: `tmux attach -t geocode`. Si
se interrumpe, al volver a correrlo sigue con los que faltan.

### Consultar la base (opcional)

```bash
docker compose -f docker-compose.prod.yml exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Sal con `\q`. Si prefieres un programa gráfico en tu PC (DBeaver, pgAdmin), usa un **túnel SSH**
hacia la IP interna del contenedor, sin abrir puertos:

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' rastreador-db-1   # en el servidor
```

```bash
# en tu PC; deja esta terminal abierta mientras uses el programa
ssh -N -L 5433:<IP-INTERNA-DEL-CONTENEDOR>:5432 deploy@<IP-DEL-VPS>
```

Conecta el programa a `localhost:5433` con el usuario, la base y la contraseña del `.env`. La IP
interna puede cambiar cuando se recrea el contenedor: vuelve a consultarla si deja de conectar.

---

## g) Apuntar Vercel a la nueva API

En Vercel → tu proyecto → **Settings → Environment Variables**, cambia (en *Production*):

- `BACKEND_URL` = `https://<tu-subdominio>`

Si existe `NEXT_PUBLIC_API_URL` con la URL vieja de Render, cámbiala también: el frontend la usa
cuando falta `BACKEND_URL`.

**Vuelve a desplegar** (Deployments → el último → *Redeploy*). Las rewrites del frontend
(`frontend/next.config.ts`) se fijan **al compilar**: si solo cambias la variable y no
redespliegas, el frontend sigue llamando a la API vieja.

> **Si el frontend llama a un prefijo nuevo, hay que agregarlo a `frontend/next.config.ts`**
> (arreglo `BACKEND_PREFIXES`); si no, Vercel responde el 404 de Next. La prueba
> `tests/test_frontend_rewrites.py` lo verifica.

Prueba en el sitio de Vercel, en este orden:

1. **Login** con la cuenta del paso e.
2. **Novo cliente**: guarda uno con tu ubicación y revisa que la ciudad salga bien.
3. **Gerar Semana**: genera la semana con tus ciudades; los clientes de visita diaria deben
   aparecer todos los días con la etiqueta "Diario".
4. **Tarjetas**: abre la ruta de tarjetas del día.

---

## h) Respaldos

### Programar el respaldo diario

```bash
sudo install -d -m 700 -o deploy -g deploy /var/backups/rastreador
~/rastreador/scripts/backup_db.sh          # pruébalo una vez a mano
ls -l /var/backups/rastreador
```

Cada respaldo es `rastreador_AAAA-MM-DD_HHMMSS.dump`, con permisos `600`, y se conservan los 14
más recientes. Si algo falla (por ejemplo, la base está caída) el script sale con código 1 y
**no deja archivos a medias**.

Prográmalo con `crontab -e` (como `deploy`) y agrega esta línea, que lo corre todos los días a
las 03:15:

```
15 3 * * * /home/deploy/rastreador/scripts/backup_db.sh >> /home/deploy/backup_db.log 2>&1
```

Revisa de vez en cuando `tail /home/deploy/backup_db.log`.

**Copia los respaldos fuera del servidor**: si el VPS se pierde, se pierden también los
respaldos que estén en él. Por ejemplo, una vez por semana:

```bash
# en tu PC
scp "deploy@<IP-DEL-VPS>:/var/backups/rastreador/*.dump" ./respaldos-rastreador/
```

### Probar una restauración (en una base de prueba)

Un respaldo que nunca se probó no es un respaldo. Restaura el último en una base aparte; esto
**no toca producción**:

```bash
cd ~/rastreador
ultimo="$(ls -1 /var/backups/rastreador/rastreador_*.dump | tail -1)"
scripts/restore_db.sh "$ultimo" restore_test
```

El script **pide escribir el nombre de la base** (`restore_test`) para continuar. Comprueba que
están los datos y borra la base de prueba:

```bash
docker compose -f docker-compose.prod.yml exec db sh -c 'psql -U "$POSTGRES_USER" -d restore_test -c "SELECT count(*) FROM clientes"'
docker compose -f docker-compose.prod.yml exec db sh -c 'dropdb -U "$POSTGRES_USER" restore_test'
```

**Restaurar sobre producción** (solo en una emergencia): `scripts/restore_db.sh <archivo.dump>`
sin segundo argumento. Detiene la API, **reemplaza todos los datos** por los del respaldo y
vuelve a arrancar la API, aunque la restauración falle. Pide escribir el nombre de la base de
producción.

---

## i) Actualizar a una versión nueva y volver atrás

Antes de actualizar, haz un respaldo:

```bash
cd ~/rastreador
scripts/backup_db.sh
git rev-parse --short HEAD > ~/version_anterior.txt      # anota la versión actual
git pull
docker compose -f docker-compose.prod.yml build api
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
curl https://<tu-subdominio>/health
```

**Volver atrás** si algo sale mal:

```bash
cd ~/rastreador
git checkout "$(cat ~/version_anterior.txt)"
docker compose -f docker-compose.prod.yml build api
docker compose -f docker-compose.prod.yml up -d
```

Las migraciones de este proyecto solo agregan tablas o columnas, así que la versión anterior
funciona con la base ya migrada. Si lo que se rompió son los **datos**, restaura el respaldo
que hiciste antes de actualizar (paso h, sobre producción). Para volver a la rama normal después:
`git checkout <rama-a-desplegar> && git pull`.

---

## j) Cuándo apagar Render

Solo cuando **todo** lo anterior esté verificado: HTTPS funcionando, login y las cuatro pruebas
del paso g bien en Vercel, clientes y negocios cargados, al menos un respaldo automático hecho
**y una restauración de prueba exitosa**. Recomendado: usar el VPS unos días con Render todavía
encendido como plan B.

Si la base de Render tiene datos que quieres conservar, expórtalos antes de apagarla (con
`pg_dump -Fc` desde tu PC usando la URL externa que da el panel de Render) y restáuralos con
`scripts/restore_db.sh`. Si la versión de Postgres de Render es más nueva que la 15 del VPS,
`pg_restore` puede rechazar el archivo; en ese caso exporta en SQL plano (`pg_dump` sin `-Fc`).

---

## Lista de comprobación

- [ ] Entras como `deploy` con llave; `root` y la contraseña por SSH están desactivados.
- [ ] `sudo ufw status` muestra solo 22, 80 y 443 abiertos.
- [ ] `unattended-upgrades` instalado.
- [ ] El registro A del subdominio resuelve a la IP del VPS.
- [ ] `.env` con permisos `600`, sin valores `cambia-` y con los secretos guardados aparte.
- [ ] `docker compose -f docker-compose.prod.yml ps`: `db` y `api` healthy; solo `caddy` publica puertos.
- [ ] `curl https://<tu-subdominio>/health` responde `ok`, con certificado válido.
- [ ] Tu cuenta creada; `/auth/register` responde `Registro cerrado`.
- [ ] Clientes y negocios cargados (primero ensayo, luego `--apply`); geocodificación corrida.
- [ ] `BACKEND_URL` cambiado en Vercel **y redesplegado**; login, Novo cliente, Gerar Semana y Tarjetas funcionan.
- [ ] Cron del respaldo instalado; hay al menos un `.dump` en `/var/backups/rastreador`.
- [ ] Restauración probada en `restore_test` (y borrada después).
- [ ] Una copia de los respaldos fuera del servidor.
- [ ] Recién entonces, Render apagado.

## Si Caddy no emite el certificado

Mira primero qué dice Caddy:

```bash
docker compose -f docker-compose.prod.yml logs --tail 100 caddy
```

Causas habituales, en orden:

1. **El DNS todavía no apunta al VPS.** `nslookup <tu-subdominio>` debe dar la IP del VPS. Si no,
   espera a que propague o revisa el registro A. Borra cualquier AAAA que apunte a otro lado.
2. **Los puertos 80 o 443 están cerrados.** Revisa `sudo ufw status` y el firewall del panel de
   Hostinger. Let's Encrypt necesita entrar por el **80** (o el 443) para validar.
3. **`API_DOMAIN` mal escrito** en `.env`: va sin `https://`, sin espacios y sin barra final.
   Después de corregirlo: `docker compose -f docker-compose.prod.yml up -d caddy`.
4. **Otro programa ocupa el 80 o el 443** (por ejemplo un Apache o nginx que traía la plantilla):
   `sudo ss -tlnp | grep -E ':80 |:443 '`. Detenlo y desactívalo (`sudo systemctl disable --now apache2` o `nginx`).
5. **Demasiados intentos.** Let's Encrypt limita las emisiones fallidas por hora. No reinicies
   Caddy en bucle: corrige la causa, espera una hora y vuelve a intentar. Tampoco borres el
   volumen `caddy_data`: ahí se guardan los certificados ya emitidos.
6. **Nombre `srvXXXX.hstgr.cloud` de Hostinger**: si con él no se emite, usa un subdominio propio (paso b).

Mientras tanto la API sigue funcionando dentro del servidor (`docker compose ps` la muestra
healthy); lo único que falta es el acceso por HTTPS.
