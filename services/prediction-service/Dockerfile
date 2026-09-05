FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv $VIRTUAL_ENV \
    && $VIRTUAL_ENV/bin/pip install --no-cache-dir --upgrade pip

COPY requirements.txt requirements-gpu.txt ./
ARG INSTALL_GPU_REQUIREMENTS=0
RUN $VIRTUAL_ENV/bin/pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_GPU_REQUIREMENTS" = "1" ]; then \
         $VIRTUAL_ENV/bin/pip install --no-cache-dir -r requirements-gpu.txt; \
       fi

COPY main.py ./main.py

RUN mkdir -p /app/models

EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
