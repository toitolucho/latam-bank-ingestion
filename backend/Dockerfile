FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY policy ./policy
# data/fixture (conjunto de ejemplo del equipo) siempre; data/snapshot solo existe en la maquina de quien lo genero.
# En otros entornos se monta un volumen y se fija CHAT_DATA_DIR.
COPY data ./data

RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# Un solo proceso: las sesiones viven en memoria. Para varias replicas hay que externalizar el SessionStore (Redis).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
