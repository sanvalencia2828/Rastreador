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
| `PORT` | Puerto del frontend Next.js | `3000` |

## 📋 API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
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