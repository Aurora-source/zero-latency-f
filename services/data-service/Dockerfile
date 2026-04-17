FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./main.py
COPY scripts ./scripts
RUN mkdir -p /app/data/graphs

EXPOSE 8001

CMD ["sh", "-c", "python scripts/predownload_graphs.py && uvicorn main:app --host 0.0.0.0 --port 8001"]
