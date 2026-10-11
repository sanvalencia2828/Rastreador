"""FastAPI application assembly: middleware, startup schema checks and routers."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import cors_origins
from app.db.bootstrap import ensure_schema
from app.routes import (
    auth,
    businesses,
    cities,
    daily_routes,
    geo,
    planned_routes,
    visits,
)
from app.routes.routes import router as semimanual_routes_router

# ==============================================================================
# APP INSTANCE & CORS
# ==============================================================================
app = FastAPI(
    title="Londrina Radar Comercial API",
    description="Plataforma analítica geoespacial para rastreo de comercios en Londrina, PR",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_schema()

app.include_router(semimanual_routes_router, prefix="/api/v1")
app.include_router(geo.router)
app.include_router(businesses.router)
app.include_router(auth.router)
app.include_router(visits.router)
app.include_router(planned_routes.router)
app.include_router(daily_routes.router)
app.include_router(cities.router)
