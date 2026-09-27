# Single-service image for Render: Next.js static export + FastAPI.
# start: uvicorn api:app --host 0.0.0.0 --port $PORT

FROM node:20-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
ENV NEXT_OUTPUT=export \
    NEXT_PUBLIC_API_URL=
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRONTEND_DIST=/app/frontend/out \
    APP_TIMEZONE=America/Sao_Paulo

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py main.py ./
COPY app ./app
COPY migrations ./migrations
COPY cnpj_etl_polars.py enriquecer_lojas.py generate_sample_data.py download_cnpj_pr.py ./
COPY --from=frontend /src/out /app/frontend/out

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health')" || exit 1

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
