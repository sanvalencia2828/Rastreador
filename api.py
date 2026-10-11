#!/usr/bin/env python3
"""
FastAPI Backend Server for Rastreador CNPJ ETL
Provides GeoJSON endpoints for MapLibre/react-map-gl integrations.

Deployment entrypoint (`uvicorn api:app`). The application lives in `app/`.
"""

import os

from app.main import app  # noqa: F401

# ==============================================================================
# MAIN METHOD
# ==============================================================================
if __name__ == "__main__":
    import uvicorn

    # Read config from environment variables
    port = int(os.environ.get("API_PORT", "8000"))
    host = os.environ.get("API_HOST", "0.0.0.0")
    print(f"Launching Rastreador CNPJ Backend API on http://{host}:{port}...")
    uvicorn.run("api:app", host=host, port=port, reload=True)
