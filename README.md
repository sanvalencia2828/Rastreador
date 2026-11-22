# 🛰️ Rastreador

Plataforma de análisis geoespacial para negocios, rutas y cobertura comercial de Londrina, PR. La app combina un backend FastAPI con un frontend Next.js para explorar comercios, geocodificar direcciones, evaluar paradas y construir rutas operativas.

## 🏗️ Arquitectura actual

```text
┌──────────────────────────────────────────────────────────────┐
│                     Rastreador Stack                         │
├──────────────────────────────────────────────────────────────┤
│ PostgreSQL + PostGIS      │ FastAPI API                 │ Next.js 16 │
│ :5432                     │ :8000                       │ :3000      │
│  DB geoespacial           │ /api/*, /health, /auth    │ dashboard  │
│                           │ /api/routes, /api/businesses│           │
└──────────────────────────────────────────────────────────────┘
```

| Capa | Tecnología | Puerto |
|------|-----------|--------|
| Base de datos | PostgreSQL + PostGIS | 5432 |
| Backend API | Python 3.11, FastAPI, SQLAlchemy | 8000 |
| Frontend | Next.js 16, React 19, MapLibre / Leaflet | 3000 |
| ETL / Data | Python + Pandas / Polars + DuckDB | CLI |

## ✨ Qué incluye este proyecto

- Mapa de negocios con capas geoespaciales y heatmap
- Búsqueda y geocodificación de direcciones
- Consulta de comercios por radio (cercanía)
- Registro/login de usuarios autenticados
- Rutas planificadas y optimización de paradas
- Seguimiento de visitas y cobertura comercial
- Endpoints para ciudades, estadísticos y análisis de calles
- Las lecturas públicas usan JSON si no hay base de datos; el login y las rutas necesitan base de datos

## 🚀 Inicio rápido

### 1) Clonar y preparar entorno

```bash
git clone https://github.com/sanvalencia2828/Rastreador.git
cd rastreador
cp .env.example .env
```

### 2) Backend local

Requiere Python 3.11+.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
python api.py
```

La API queda disponible en:
- http://localhost:8000
- http://localhost:8000/docs

### 3) Frontend local

```bash
cd frontend
npm install
npm run dev
```

El dashboard queda en:
- http://localhost:3000

### 4) Base de datos opcional

Si quieres usar PostgreSQL/PostGIS localmente:

```bash
docker compose up db
```

> El archivo `docker-compose.yml` deja el servicio `db` activo y los servicios `api` / `frontend` comentados para ejecución local nativa. Las lecturas públicas usan JSON; el login y las rutas necesitan base de datos.

## 🧩 Ejecutar la API directamente

La app real se monta desde `app/main.py` y la entrada `api.py` re-exporta ese app para despliegues y uvicorn.

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

También funciona:

```bash
python api.py
```

## 🛣️ OSRM (opcional)

Sin `OSRM_URL` la app usa distancias Haversine. Para rutas por calle, levanta tu propio OSRM (el `docker-compose.yml` no incluye un servicio `osrm`):

```bash
# Descargar un .osm.pbf (p. ej. de https://download.geofabrik.de/south-america/brazil.html) a osrm-data/
# Perfil: foot.lua para rutas a pie, car.lua para auto
docker run -t --rm -v "$PWD/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /opt/car.lua /data/brazil-latest.osm.pbf
docker run -t --rm -v "$PWD/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/brazil-latest.osrm
docker run -t --rm -v "$PWD/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/brazil-latest.osrm
docker run -t --rm -v "$PWD/osrm-data:/data" -p 5000:5000 ghcr.io/project-osrm/osrm-backend osrm-routed --algorithm mld /data/brazil-latest.osrm
```

Luego en `.env`: `OSRM_URL=http://localhost:5000` (o el nombre del servicio si lo añades al compose).

## ☁️ Despliegue en Vercel

- **Backend (FastAPI)**: `pyproject.toml` define `[tool.vercel]` con `entrypoint = "api:app"` y `uvicorn api:app --host 0.0.0.0 --port ${PORT}` (Vercel inyecta `$PORT`).
- **Frontend (Next.js)**: `frontend/vercel.json` declara `"framework": "nextjs"`.
- El `vercel.json` de la raíz fue eliminado del repo; no hay reglas de rutas `/api/*` en la raíz. Antes de desplegar backend y frontend juntos, comprueba cómo se enruta `/api` en tu proyecto de Vercel.

Variables de entorno (*Settings → Environment Variables*):

| Variable | Valor |
|----------|-------|
| `DATABASE_URL` | `postgresql://user:pass@host:5432/dbname` |
| `JWT_SECRET_KEY` | Obligatorio y distinto de `change-me-in-production` si `APP_ENV≠development` |
| `CORS_ORIGINS` | Orígenes permitidos, p. ej. `https://<tu-proyecto>.vercel.app` |
| `NEXT_PUBLIC_API_URL` | URL pública del backend desplegado |
| `BACKEND_URL` | URL del backend para los rewrites del frontend |

Probar antes de subir: `npm i -g vercel`, `vercel build`, `vercel deploy --prod`.

## 📁 Estructura del repositorio

```text
rastreador/
├── app/                          # Backend principal FastAPI
│   ├── core/                    # config, DB, cache, security
│   ├── db/                      # bootstrap, modelos y esquema
│   ├── routes/                  # auth, businesses, geo, routes, visits...
│   ├── schemas/                 # modelos Pydantic
│   ├── services/                # carga de datos, rutas, geografía
│   └── main.py                  # aplicación FastAPI
├── frontend/                    # App Next.js
│   ├── src/
│   ├── package.json
│   └── next.config.ts
├── api.py                       # entrypoint para uvicorn/despliegue
├── main.py                      # entrypoint alternativo
├── requirements.txt             # dependencias Python
├── pyproject.toml               # metadata build + Vercel
├── docker-compose.yml           # PostgreSQL + ML job profiles
├── .env.example                 # variables de entorno
├── init.sql                    # schema Postgres
├── street_tracking_schema.sql   # schema de tracking geográfico
├── generate_sample_data.py      # datos de ejemplo
├── cnpj_etl.py                  # ETL con Pandas
├── cnpj_etl_polars.py           # ETL con Polars
├── enriquecer_lojas.py          # geocodificación / enriquecimiento
├── londrina_businesses.json     # fallback de negocios
├── tests/                       # validaciones del proyecto
├── ml/                          # pipeline de ML / riesgo de cierre
├── Dockerfile*                  # contenedores varios
├── .gitignore
├── README.md
└── package.json                 # wrapper para frontend dev
```

## 🌐 Endpoints principales

Lista completa e interactiva en http://localhost:8000/docs. Resumen por área (rutas tomadas de `app/routes/`):

| Área | Método y endpoint | Descripción |
|------|-------------------|-------------|
| Salud | `GET /health` | Estado del backend |
| Auth | `POST /auth/register`, `POST /auth/login` | Registro y login (requieren base de datos) |
| Mapa | `GET /api/heatmap` | GeoJSON de negocios |
| Mapa | `GET /api/clusters/emergentes` | Clusters comerciales |
| Mapa | `GET /api/corridor/br369` | Corredor BR-369 |
| Negocios | `GET /api/businesses`, `/api/businesses/near`, `/api/businesses/search`, `/api/businesses/tech`, `/api/businesses/clients` | Consulta de comercios (por radio, texto, tipo) |
| Negocios | `PATCH /api/businesses/{cnpj}/status` | Cambiar estado de un negocio (autenticado) |
| Estadísticas | `GET /api/stats/summary`, `/api/businesses/city-category` | Resúmenes |
| Ciudades | `GET/POST /api/cities`, `GET /api/cities/{id}/stats`, `/api/cities/{id}/routes` | Ciudades y sus rutas |
| Clientes | `GET/POST /api/clientes`, `GET /api/clientes/streets-nearby` | Clientes con GPS |
| Rutas | `GET/POST /api/routes`, `GET/PUT/DELETE /api/routes/{id}`, `POST /api/routes/optimize`, `POST /api/routes/generate-week` | Rutas planificadas y optimización |
| Rutas diarias | `GET/POST /api/daily-routes`, `GET/PUT/DELETE /api/daily-routes/{id}` | Rutas del día |
| Visitas | `GET/POST /api/visits`, `POST /api/sync/visits` | Visitas y sincronización |
| Calles | `GET /api/analytics/streets`, `/api/street-time`, `/api/segments`, `/api/street-coverage` | Análisis y cobertura por calle |

## 🔐 Variables de entorno

La configuración base se define en `.env.example` y se carga automáticamente por `app/core/config.py`.

```env
DB_USER=postgres
DB_PASSWORD=postgres_secure_pass
DB_HOST=db
DB_PORT=5432
DB_NAME=rastreador_db
DATABASE_URL=postgresql://postgres:postgres_secure_pass@db:5432/rastreador_db

APP_ENV=development
API_PORT=8000
API_HOST=0.0.0.0
# Obligatorio y distinto de change-me-in-production si APP_ENV≠development
JWT_SECRET_KEY=change-me-in-production
DEV_USER_ID=00000000-0000-0000-0000-000000000001
CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:8000

# La API local corre en API_PORT (8000 por defecto, ver api.py)
NEXT_PUBLIC_API_URL=http://localhost:8000
BACKEND_URL=http://localhost:8000
PORT=3000

# Opcionales
# OSRM autoalojado para rutas por calle (vacío = distancias Haversine). Ver sección OSRM.
OSRM_URL=
# Cantidad de paradas movibles a partir de la cual el optimizador añade OR-Tools (si está instalado). Por defecto 30.
OPTIMIZER_THRESHOLD_ORTOOLS=30
```

| Variable | Descripción |
|----------|-------------|
| `OSRM_URL` | URL de un OSRM **propio**. Solo se usa si apunta a un host privado (localhost, IP privada, `.local`/`.internal`, nombre de servicio docker); un servidor público se ignora para no enviarle coordenadas de clientes (`app/services/geo.py`). |
| `OPTIMIZER_THRESHOLD_ORTOOLS` | Umbral de paradas movibles (30 por defecto) desde el cual `app/optimizer.py` resuelve también con OR-Tools y devuelve la mejor solución. |

## Tests

- Local, sin variables extra: `python -m pytest -q`
- Postgres en CMD: `docker run -d --rm --name rastreador-test-pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=test_rastreador -p 55432:5432 postgis/postgis:15-3.4 && set "TEST_PG_URL=postgresql://postgres:x@localhost:55432/test_rastreador" && python -m pytest -q tests/test_tarjetas_pg.py tests/test_clientes_pg.py`
- Postgres en PowerShell: `docker run -d --rm --name rastreador-test-pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=test_rastreador -p 55432:5432 postgis/postgis:15-3.4; $env:TEST_PG_URL="postgresql://postgres:x@localhost:55432/test_rastreador"; python -m pytest -q tests/test_tarjetas_pg.py tests/test_clientes_pg.py`

## 🧪 Flujo de trabajo recomendado

### Desarrollo local

1. Levantar `db` con Docker si se necesita PostGIS.
2. Instalar dependencias de Python con `pip install -r requirements.txt`.
3. Arrancar backend con `python api.py` o `uvicorn app.main:app --reload`.
4. Ejecutar frontend con `cd frontend && npm install && npm run dev`.
5. Probar endpoints con Swagger en http://localhost:8000/docs.

### ETL / preparación de datos

Orden de los pasos:

1. **Datos de partida** — `python download_cnpj_pr.py` (DuckDB → PostgreSQL, sector tech y repairs) o, solo para pruebas, `python generate_sample_data.py` y luego `python cnpj_etl.py` / `python cnpj_etl_polars.py`.
2. *(Opcional)* **Carga desde un CSV filtrado de la Receita** — `python load_filtered_cnpj.py <filtered.csv>`. Es dry-run por defecto; `--apply` escribe; `--no-db` solo valida el CSV. Rechaza filas cortas o de municipio desconocido (con `--apply` se niega salvo `--skip-bad`) e ignora las inactivas.
3. **Migración** `migrations/008_geocode_attempts.sql` (columnas `geocode_attempts`, `geocode_last_try`), aplicada una vez a mano.
4. **Geocodificar** — `python enriquecer_lojas.py` (Nominatim, 1 petición/s). Las direcciones sin resultado quedan pendientes y se dejan de reintentar tras 3 intentos; 5 errores de red seguidos abortan la corrida.

Las ciudades procesadas están definidas en `cities.py`.

### Machine Learning / analytics

El repositorio incluye un pipeline de ML y artefactos en `ml/` y `artifacts/` para análisis de riesgo / cierre de comercios.

## 🗺️ Fuente de datos

Los datos base provienen de la Receita Federal do Brasil (CNPJ) y se filtran por:
- municipio: Londrina / PR
- situación cadastral activa
- actividades asociadas a retail y gastronomía
- enriquecimiento geográfico para visualización y rutas

## 📜 Licencia

El proyecto se entrega con fines de investigación, análisis y desarrollo local. Verifica siempre los términos de uso de los datasets públicos antes de reutilizarlos fuera del contexto académico o de investigación.

## 🔎 Notas importantes

- El proyecto no depende de Mapbox/Google como fuente principal.
- Las lecturas públicas usan JSON; el login y las rutas necesitan base de datos.
- El backend actual es más completo que la versión clásica de "heatmap" y cubre autenticación, rutas y visitas.
- El frontend en `frontend/` usa componentes modernos de React/Next y no requiere un backend externo para funcionar con datos locales.
