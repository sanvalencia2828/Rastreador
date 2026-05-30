# ==============================================================================
# main.py — FastAPI Default Entrypoint Router
# ==============================================================================
# This file serves as a default entrypoint for the 'fastapi dev' or 'fastapi run'
# CLI commands, which search for main.py by default. It forwards all requests to
# the core api.py implementation.

from api import app

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("API_PORT", 8000))
    host = os.environ.get("API_HOST", "0.0.0.0")
    print(f"Launching Rastreador CNPJ Backend API via main.py on http://{host}:{port}...")
    uvicorn.run("main:app", host=host, port=port, reload=True)
