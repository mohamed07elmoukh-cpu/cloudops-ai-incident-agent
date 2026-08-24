FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY cloudops_agent ./cloudops_agent
COPY apps ./apps
COPY runbooks ./runbooks
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --no-cache-dir .

EXPOSE 8002

CMD ["python", "apps/incident-worker/worker_main.py"]
