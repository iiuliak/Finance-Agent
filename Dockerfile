FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY finance_agent ./finance_agent
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home app
USER app

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m finance_agent.seed && exec uvicorn finance_agent.api.main:app --host 0.0.0.0 --port 8000"]
