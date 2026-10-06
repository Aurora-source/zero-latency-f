FROM python:3.11.16-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
ENV VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
COPY services/data-service/requirements.lock /tmp/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && /opt/venv/bin/python -m pip uninstall -y pip setuptools \
    && /usr/local/bin/python -m pip uninstall -y pip setuptools
RUN python -c "from fastapi import FastAPI; from fastapi.middleware.cors import CORSMiddleware; import numpy; assert callable(FastAPI) and callable(CORSMiddleware) and numpy.zeros(1).size == 1; print('Runtime dependencies import successfully')"
COPY runtime/entrypoint.py /opt/runtime/entrypoint.py
COPY services/data-service/main.py services/data-service/api_key_manager.py services/data-service/tile_loader.py services/data-service/tower_ingestion_worker.py services/data-service/geocoding.py ./
RUN python -c "from pathlib import Path; files=[Path('/opt/runtime/entrypoint.py'),*Path('/app').glob('*.py')]; assert all(p.stat().st_size for p in files); [compile(p.read_text(),str(p),'exec') for p in files]"
RUN LOCAL_DATA_ONLY=1 ENV_FILE_PATH=/dev/null ALLOW_MODEL_TRAINING=0 PREDICTION_DEVICE=cpu APP_CACHE_DIR=/tmp/build-check python -c "import main; assert main.app; print('Service imports without artifacts')"
RUN groupadd --gid 10001 application && useradd --uid 10001 --gid 10001 --no-create-home application \
    && mkdir -p /runtime/graphs /runtime/towers /runtime/scores \
    && chown -R application:application /runtime
USER 10001:10001
EXPOSE 8001
CMD ["python", "/opt/runtime/entrypoint.py", "data-service"]
