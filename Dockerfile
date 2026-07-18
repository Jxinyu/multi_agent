FROM node:24-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY alembic.ini ./
COPY migrations/ migrations/
COPY config/ config/
COPY multi_domain_enterprise_project/ multi_domain_enterprise_project/
COPY --from=frontend /src/frontend/dist frontend/dist
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/data && chown app:app /app/data
USER app
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "multi_domain_enterprise_project.main:app", "--host", "0.0.0.0", "--port", "8080"]
