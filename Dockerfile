# Use python:3.12-slim as base
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Set working directory
WORKDIR /app

# Copy uv binary from official ghcr.io image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/uv

# Add uv to PATH
ENV PATH="/uv/bin:${PATH}"

# Copy pyproject.toml and uv.lock (if it exists)
COPY pyproject.toml uv.lock* ./

# Install project dependencies system-wide using uv
RUN uv pip install --system --no-cache-dir .

# Copy API implementation and utility ETL scripts
COPY api.py ./
COPY cnpj_etl_polars.py ./
COPY enriquecer_lojas.py ./
COPY generate_sample_data.py ./

# Expose port 8000
EXPOSE 8000

# Run uvicorn on startup
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
