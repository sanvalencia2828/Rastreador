# ==============================================================================
# Dockerfile.ml — Pipeline de ML (riesgo de cierre) + scheduler
# ==============================================================================
#   docker compose run --rm ml                      → corrida completa
#   docker compose --profile ml-scheduler up -d     → ejecución programada (ml/crontab)
# ==============================================================================
FROM python:3.13-slim

ARG TARGETARCH
ARG GIT_COMMIT=unknown
ARG SUPERCRONIC_VERSION=v0.2.33

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo \
    GIT_COMMIT=${GIT_COMMIT}

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# supercronic: cron pensado para contenedores (hereda el entorno y loguea a stdout)
RUN set -eux; \
    ARCH="${TARGETARCH:-amd64}"; \
    case "${ARCH}" in \
      amd64) SHA1=71b0d58cc53f6bd72cf2f293e09e294b79c666d8 ;; \
      arm64) SHA1=e0f0c06ebc5627e43b25475711e694450489ab00 ;; \
      *) echo "arquitectura no soportada: ${ARCH}"; exit 1 ;; \
    esac; \
    curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}"; \
    echo "${SHA1}  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic

WORKDIR /app

COPY requirements-ml.txt .
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY ml ./ml
COPY tests/test_ml_pipeline.py ./tests/test_ml_pipeline.py

RUN useradd --create-home --uid 1000 ml \
    && mkdir -p /app/artifacts /app/.data \
    && chown -R ml:ml /app/artifacts
USER ml

ENTRYPOINT ["python", "-m", "ml"]
CMD ["run"]
