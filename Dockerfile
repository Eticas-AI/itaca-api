# ITACA API — deployment image
#
# Minimal by design: ASSIST (DataPACT integration partner) may adapt or
# replace this Dockerfile for the shared deployment. All runtime
# configuration is environment-variable driven (see example.env); nothing
# in the image needs rebuilding to repoint Keycloak or storage paths.

FROM python:3.12-slim

WORKDIR /srv/itaca-api

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 itaca \
    && mkdir -p /data/datasets /data/results \
    && chown -R itaca:itaca /data

USER itaca

ENV DATA_DIR=/data/datasets \
    RESULTS_DIR=/data/results

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8080}"]
