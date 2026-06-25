# syntax=docker/dockerfile:1
FROM node:22-slim AS dashboard-build
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY dashboard ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml prd.md ./
RUN mkdir -p src/tempa && touch src/tempa/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e .

COPY config ./config
COPY src ./src
COPY --from=dashboard-build /dashboard/dist ./dashboard/dist
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e . --no-deps

EXPOSE 8787
CMD ["tempa", "start"]
