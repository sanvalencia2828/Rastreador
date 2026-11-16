# Pipeline de ML · riesgo de cierre de comercios

Para cada establecimiento activo, el pipeline estima la probabilidad de que pase a **baixada, inapta o suspensa en los próximos 12 meses**. Usa solo el volcado abierto de CNPJ de la Receita Federal y no depende de ninguna API paga.

```
ingest ─▶ validate ─▶ features ─▶ train ─▶ evaluate ─▶ predict
          (contrato)                         (gate)
   └─ si el esquema cambia: STOP (exit 2)     └─ si el modelo es peor que el umbral: no se promueve (exit 3)
```

| Paso | Qué hace | Artefactos (`artifacts/runs/<run_id>/`) |
|---|---|---|
| `ingest` | Lee `.data/*ESTABELE*` por bloques, se queda con la UF configurada y falla rápido si cambia el número de columnas | `data/ingest_summary.json` |
| `validate` | Comprueba el contrato `contracts/estabelecimentos_raw.yaml`: columnas, regex, valores permitidos, % de vacíos y mínimo de filas | `validation/raw_report.json` |
| `features` | Arma tres cohortes con etiqueta temporal (ver abajo) y valida la tabla de features | `features/{train,test,scoring}.pkl`, `validation/features_report.json` |
| `train` | Entrena un modelo de **backtest** (corte S−24m, sin las zonas hold-out) y otro de **producción** (corte S−12m) | `model/*.joblib`, `model/model_card.json` |
| `evaluate` | Evalúa el backtest fuera de tiempo y en zonas (CEP5) que nunca vio, y aplica el gate de calidad | `evaluation/metrics.json`, `report.md`, `feature_importance.csv`, `calibration_deciles.csv` |
| `predict` | Puntúa los comercios activos en la fecha del volcado | `predictions/business_scores.csv.gz` |

Cada corrida guarda además `manifest.json` (estado de cada paso, tiempos, commit de git, versiones de las librerías, huella de los archivos de entrada y métricas), `config.yaml.json` y `logs/pipeline.log`. `artifacts/latest.json` apunta a la última corrida que **terminó bien y pasó el gate**. Una corrida fallida o rechazada nunca reemplaza a `latest`.

## Cómo se construye la etiqueta con un solo volcado

Cada fila trae la fecha de su última situación cadastral, así que se puede reconstruir el pasado. Con S como fecha del volcado:

- **train**: los activos en S−24m, con etiqueta 1 si cerraron en [S−24m, S−12m).
- **test**: los activos en S−12m, con etiqueta 1 si cerraron en [S−12m, S). Es la validación fuera de tiempo.
- **scoring**: los activos en S. Es lo que se predice.

Todas las variables se calculan con información anterior a cada corte: edad, CNAE, densidad de activos y de competidores por CEP, aperturas y tasas de cierre del año previo por CEP5, CNAE y municipio, y datos de contacto.

## Uso

```bash
# Docker (recomendado)
docker compose run --rm ml                                   # corrida completa
docker compose run --rm ml run --steps ingest,validate       # solo validar un volcado nuevo
docker compose run --rm ml run --run-id <id> --from train    # retomar una corrida
docker compose run --rm ml status                            # últimas corridas
docker compose run --rm --entrypoint python ml -m pytest -q tests/test_ml_pipeline.py

# Programado: todos los lunes 03:17, y solo entrena si hay un volcado nuevo (ml/crontab)
docker compose --profile ml-scheduler up -d ml-scheduler
docker compose logs -f ml-scheduler

# Local sin Docker
pip install -r requirements-ml.txt
python -m ml run
```

Los códigos de salida son: `0` ok · `1` error · `2` datos que no cumplen el contrato · `3` gate de calidad no superado · `4` ya hay otra corrida en curso.

La configuración está en `ml/config.yaml`. Cualquier clave se puede sobrescribir con variables de entorno, por ejemplo `ML__DATA__UF=SP` o `ML__EVALUATION__MIN_ROC_AUC=0.65`.

## Cuando el contrato falla

Si la Receita cambia el layout del archivo (columnas nuevas o reordenadas, códigos de situación nuevos, otro formato de fecha), la corrida se detiene en `ingest` o en `validate` con `status: invalid_data`, y `validation/raw_report.json` dice qué columna falló y con qué ejemplos. Revisa el cambio, actualiza `contracts/estabelecimentos_raw.yaml` (sube `version`) y, si hace falta, `steps/features.py`.

## Limitaciones conocidas

- El volcado de la Receita viene partido en 10 archivos (`Estabelecimentos0`…`9`). Con uno solo se modela alrededor de una décima parte de los establecimientos de la UF. Copia todas las partes en `.data/` y el glob las toma juntas.
- La zona se aproxima con el CEP porque el pipeline todavía no usa coordenadas. Cuando exista `geocode_source` se pueden agregar features espaciales reales, excluyendo los puntos sintéticos del hash MD5.
- Email, teléfono y complemento son los valores actuales del registro, no los de la fecha de corte. Es una fuga pequeña y conocida.
- Las inaptidões llegan en olas administrativas (por ejemplo 2021-03, 2022-01 o 2022-11), lo que limita cuánto se puede predecir. Si interesa solo el cierre voluntario, usa `labels.closed_codes: ["08"]`.
- El scheduler entrena con lo que haya en `.data/`. Descargar el volcado nuevo (`download_cnpj_pr.py`) todavía es un paso manual.
