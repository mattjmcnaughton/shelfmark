## Stage 1: Dependencies
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen

## Stage 2: Build
FROM deps AS build

COPY . .

## Stage 3: Production
FROM python:3.12-slim AS production

LABEL org.opencontainers.image.title="shelfmark"
LABEL org.opencontainers.image.description="A keyboard-first personal reading desk"

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home app

WORKDIR /app
COPY --from=build --chown=app:app /app /app

USER app

EXPOSE 8000

ENV SHELFMARK_DATA_DIR=/data
CMD ["uv", "run", "--no-dev", "python", "-m", "shelfmark"]
