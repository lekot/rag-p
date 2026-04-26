FROM python:3.12-slim AS builder

RUN pip install uv

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN uv pip install --system --no-cache .

FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "ragp_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
