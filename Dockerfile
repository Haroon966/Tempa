FROM node:22-slim AS dashboard-build
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml prd.md ./
COPY config ./config
COPY src ./src
COPY --from=dashboard-build /dashboard/dist ./dashboard/dist

RUN pip install --no-cache-dir -e .

EXPOSE 8787
CMD ["tempa", "start"]
