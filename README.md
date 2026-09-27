# 🛰️ Londrina Radar Comercial

**Plataforma analítica geoespacial** para el rastreo y análisis de comercios y polos emergentes en Londrina, PR (Brasil). Dashboard interactivo 100% de código abierto, sin APIs comerciales.

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    DOCKER COMPOSE                       │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ PostGIS  │◄───│  FastAPI      │◄───│  Next.js 16  │  │
│  │ :5432    │    │  :8000        │    │  :3000       │  │
│  │          │    │              │    │              │  │
│  │ DB +     │    │ /api/heatmap │    │ MapLibre GL  │  │
│  │ GeoData  │    │ /api/clusters│    │ React 19     │  │
│  └──────────┘    └──────────────┘    └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

| Capa | Tecnología | Puerto |
|------|-----------|--------|
| **Base de Datos** | PostGIS 15 | 5432 |
| **Backend API** | Python 3.11, FastAPI, SQLAlchemy | 8000 |
| **Frontend** | Next.js 16, React 19, MapLibre GL, TailwindCSS 4 | 3000 |
| **ETL** | Python (Pandas / Polars) | CLI |

## ✨ Features

- **Mapa de calor (Heatmap)** — Visualización de densidad comercial en tiempo real con MapLibre GL
- **5 Polos Comerciales** — Clustering geográfico de los hubs comerciales más importantes de Londrina
- **Filtros de Sector** — Alterna entre Retail, Gastronomía o todos los comercios
- **Toggle de Capas** — Activa/desactiva el heatmap y los marcadores de cluster independientemente
- **Sidebar Interactivo** — Ranking de polos con métricas, búsqueda y navegación por click
- **Detalle de Cluster** — Panel flotante HUD con identidad de zona, densidad y coordenadas GIS
- **FlyTo Animado** — Navegación suave al hacer click en cualquier polo
- **Dark Mode Premium** — Diseño glassmorphism con efectos de radar y escaneo
- **Sin APIs comerciales** — No requiere Mapbox, Google Maps ni claves API pagas

## 🚀 Quick Start

### Opción 1: Docker Compose (Recomendado)

```bash
# Clonar el repositorio
git clone <url-del-repo> rastreador
cd rastreador

# Copiar configuración de entorno
cp .env.example .env

# Levantar todos los servicios
docker-compose up --build
```

Acceder a:
- **Dashboard**: http://localhost:3000
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### Opción 2: Desarrollo Local

#### 1. Base de Datos (opcional — la API funciona sin DB usando JSON)

```bash
docker-compose up db
```

#### 2. Backend API

```bash
# Instalar dependencias de Python
pip install -r requirements.txt

# Ejecutar el backend
python api.py
```

La API se levanta en http://localhost:8000 y automáticamente usa `londrina_businesses.json` si no hay PostgreSQL disponible.

#### 3. Frontend

```bash
cd frontend

# Instalar dependencias de Node.js
npm install

# Ejecutar en modo desarrollo
npm run dev
```

El dashboard se levanta en http://localhost:3000.

## Vercel + Render (arquitectura partida)

El frontend de producción es el proyecto Vercel (root `frontend/`). El backend es el Web Service de Render. `GET /` en Render puede ser 404: ahí no vive la app.

Diagnóstico del 2026-09-27:

- Vercel sirve el shell (mapa + “Buscar”), pero `/api/cities` responde `404 DNS_HOSTNAME_RESOLVED_PRIVATE`. El build había reescrito `/api/*` a `http://localhost:8001`.
- `/cities` muestra “No se pudieron cargar las ciudades”.
- Render `/health` sigue siendo el JSON viejo (`status`/`message`, sin `frontend_dist` en el log). Esa instancia no está en `arena/01a0e070-rastreador`.
- Render `GET /api/cities` responde `Database connection unavailable`: el Web Service no tiene `DATABASE_URL`.

El proxy de `frontend/src/app/api/[...path]/route.ts` lee, en runtime, `BACKEND_URL` o `VITE_API_URL`. No hay host de prod en el código. En Vercel hay que setear una de esas variables y redeployar. En Render hay que linkear la base y, si el browser llama a Render directo, `CORS_ORIGINS`.

## Por qué `GET /` sigue en 404

Si el log de Render dice `HEAD / HTTP/1.1" 404 Not Found` y **no** imprime `frontend_dist=...`, ese proceso no está corriendo esta branch. El 404 genérico es el FastAPI viejo, sin SPA. Con este código, `/` es HTML (200) o `503 frontend not built`, nunca el 404 pelado.

El servicio `rastreador-hcyy` arranca con `uvicorn api:app --host 0.0.0.0 --port $PORT` (runtime Python, no Docker). Para que ese comando sirva el frontend:

1. Settings → Branch → `arena/01a0e070-rastreador` (esta sesión no puede pushear otra branch).
2. Dejá el start command como está.
3. Manual Deploy. En el log tiene que aparecer `frontend_dist=...`.
4. `GET /health` debe incluir `"frontend": true`. `GET /` debe ser HTML.

El snapshot está commiteado en `static/` para que el runtime Python no necesite Node. Si cambiás el UI, regeneralo con `bash scripts/export_static.sh` y commiteá `static/`.

## ☁️ Despliegue en Render (un solo servicio)

Producción (`rastreador-hcyy.onrender.com`) tiene que servir el frontend y la API en el mismo origen. FastAPI responde `GET /` con el `index.html` del export de Next; si el build no está, responde **503** `{"detail":"frontend not built"}` en lugar del 404 genérico.

No hay `Procfile` histórico ni `render.yaml` previo: el arranque del repo era `uvicorn api:app` (Docker) y el frontend Next.js corría aparte en `:3000`, con rewrites a `http://localhost:8001`. Eso deja `GET /` en 404 cuando Render solo levanta la API.

### Opción recomendada: Docker

Root `Dockerfile` (multi-stage): `npm ci && NEXT_OUTPUT=export npm run build` y `pip install -r requirements.txt`. El output queda en `/app/frontend/out`.

```bash
uvicorn api:app --host 0.0.0.0 --port $PORT
```

También vale `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

### Opción nativa (el runtime de Python tiene que tener Node)

| Campo | Valor |
|-------|--------|
| **buildCommand** | `bash scripts/render_build.sh` |
| **startCommand** | `uvicorn api:app --host 0.0.0.0 --port $PORT` |
| **health check** | `/health` → `{"ok": true}` |

### Variables de entorno

| Variable | Obligatoria | Notas |
|----------|-------------|--------|
| `DATABASE_URL` | sí, para persistir rutas | URL **interna** de Render. No commitearla. |
| `JWT_SECRET_KEY` | sí en prod | |
| `CORS_ORIGINS` | no | Same-origin no la necesita. Lista explícita, sin `*`. |
| `OSRM_URL` | no | Si está, completa `eta_s` / `distance_m`. Si no, la distancia es línea recta. |
| `APP_TIMEZONE` | no | Default `America/Sao_Paulo` (“hoy” del import de Maps). |
| `FRONTEND_DIST` | no | Default `frontend/out`. En la imagen Docker: `/app/frontend/out`. |
| `ROOT_PATH` | no | Vacío. Render no publica la app bajo un prefijo. |

La migración `migrations/021_planner_routes.sql` corre al arrancar y es idempotente. No existe una migración numerada 020: el baseline es `init.sql` + `street_tracking_schema.sql` + el DDL de `api.py`. `cities.id` es INTEGER. `routes.id` es UUID. `planned` se mapea a `locked`.

El planner vive en `/routes` y llama `/api/v1/...` con paths relativos (no `localhost`).

Verificación local:

```bash
NEXT_OUTPUT=export npm run build --prefix frontend
DATABASE_URL= uvicorn api:app --host 0.0.0.0 --port 8000
# GET /            → HTML
# GET /routes      → HTML del planner
# GET /api/v1/docs → JSON
# GET /health      → {"ok": true}
```

## ☁️ Despliegue en Vercel

El proyecto soporta despliegue en Vercel con el backend FastAPI como **serverless function** y el frontend Next.js como build estático.

### Archivos de configuración

| Archivo | Propósito |
|---------|-----------|
| [`vercel.json`](vercel.json) | Rutas: `/api/*` → `api.py`, `/` → frontend |
| [`pyproject.toml`](pyproject.toml) | `[tool.vercel]` con entrypoint `api:app` |

### Variables de entorno en Vercel

En el panel de Vercel → *Settings → Environment Variables*, configurar:

| Variable | Valor |
|----------|-------|
| `DATABASE_URL` | `postgresql://user:pass@host:5432/dbname` |
| `JWT_SECRET_KEY` | Valor secreto para firmar tokens JWT | 
| `CORS_ORIGINS` | Orígenes permitidos, por ejemplo `https://<tu-proyecto>.vercel.app` |
| `NEXT_PUBLIC_API_URL` | `https://<tu-proyecto>.vercel.app` |
| `BACKEND_URL` | URL del backend para el rewritting del frontend en Vercel |

> **Nota:** Vercel asigna `$PORT` dinámicamente. El comando de arranque es:
> ```bash
> uvicorn api:app --host 0.0.0.0 --port ${PORT}
> ```

### Verificar localmente antes de subir

```bash
# 1. Instalar Vercel CLI (una sola vez)
npm i -g vercel

# 2. Probar el build localmente
vercel build

# 3. Desplegar a producción
vercel deploy --prod
```

### Confirmar el frontend apunta al backend desplegado

En [`frontend/.env`](frontend/.env) (o en las variables de Vercel):

```env
NEXT_PUBLIC_API_URL=https://<tu-proyecto>.vercel.app
```

---

## 📊 Pipeline ETL

### Generar datos de muestra

```bash
python generate_sample_data.py
```

### Ejecutar el ETL

```bash
# Versión Pandas
python cnpj_etl.py

# Versión Polars (recomendada para datasets grandes)
python cnpj_etl_polars.py
```

### Enriquecer datos con geocodificación

```bash
python enriquecer_lojas.py
```

## 📁 Estructura del Proyecto

```
rastreador/
├── api.py                    # FastAPI backend (endpoints GeoJSON)
├── cnpj_etl.py               # ETL con Pandas
├── cnpj_etl_polars.py         # ETL con Polars
├── generate_sample_data.py    # Generador de datos de prueba
├── enriquecer_lojas.py        # Enriquecimiento geográfico (Nominatim)
├── init.sql                   # Schema PostgreSQL + PostGIS
├── requirements.txt           # Dependencias Python
├── docker-compose.yml         # Stack completo (DB + API + Frontend)
├── Dockerfile.api             # Imagen Docker del backend
├── Dockerfile.frontend        # Imagen Docker del frontend
├── londrina_businesses.json   # Datos procesados (fallback sin DB)
├── .env.example               # Variables de entorno
│
└── frontend/                  # Next.js 16 App
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx     # Root layout (Inter font, metadata SEO)
    │   │   ├── page.tsx       # Dashboard principal (SWR + state)
    │   │   └── globals.css    # Design system (glassmorphism, animations)
    │   └── components/
    │       ├── map-view.tsx   # MapLibre GL canvas + heatmap + markers
    │       └── sidebar.tsx    # Panel lateral con ranking y controles
    ├── package.json
    └── next.config.ts
```

## 🔧 Configuración

Todas las variables de configuración están documentadas en [`.env.example`](.env.example):

| Variable | Descripción | Default |
|----------|-------------|---------|
| `DB_USER` | Usuario de PostgreSQL | `postgres` |
| `DB_PASSWORD` | Contraseña de PostgreSQL | `postgres_secure_pass` |
| `DB_HOST` | Host de la base de datos | `db` (Docker) / `localhost` |
| `DB_PORT` | Puerto de PostgreSQL | `5432` |
| `DB_NAME` | Nombre de la base de datos | `rastreador_db` |
| `API_PORT` | Puerto del backend FastAPI | `8000` |
| `NEXT_PUBLIC_API_URL` | URL pública del backend | `http://localhost:8000` |
| `BACKEND_URL` | URL del backend para rewrites del frontend | `http://localhost:8000` |
| `JWT_SECRET_KEY` | Secreto para JWT | `change-me-in-production` |
| `CORS_ORIGINS` | Orígenes permitidos por CORS | `http://localhost:3000,http://localhost:3001,http://localhost:8000` |
| `PORT` | Puerto del frontend Next.js | `3000` |

## 📋 API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/health` | Health check `{"ok": true}` |
| `GET` | `/api/v1/docs` | Índice JSON de la API v1 |
| `GET/POST` | `/api/v1/routes` | Rutas del planner (UUID, draft/locked/committed) |
| `POST` | `/api/v1/routes/import-maps` | Importa links de Google Maps con `visit_date` |
| `PATCH` | `/api/v1/routes/{id}/stops/{stop_id}/tarjeta` | Estado de tarjeteo (`TT TS TC VV TF PT VS`) |
| `GET` | `/api/heatmap` | GeoJSON FeatureCollection de todos los comercios |
| `GET` | `/api/clusters/emergentes` | Ranking de los 5 polos comerciales con totales |

## 🗺️ Fuente de Datos CNPJ

Los datos provienen de la **Receita Federal do Brasil**:
http://receita.economia.gov.br/orientacao/tributaria/cadastros/cadastro-nacional-de-pessoas-juridicas-cnpj/DadosPublicosCNPJ

Se filtran para:
- Municipio: **Londrina/PR** (IBGE: 4113700)
- Situação Cadastral: **Ativa** (2)
- CNAE: Códigos de **retail** (47xxxxx) y **gastronomía** (56xxxxx)

## 📜 Licencia

Este proyecto se provee con fines educativos y de investigación. Asegúrese de cumplir con los términos de uso de los datos públicos del CNPJ.