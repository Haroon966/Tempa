# syntax=docker/dockerfile:1
FROM node:22-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm install

COPY prisma ./prisma
RUN --mount=type=cache,target=/root/.npm \
    npx prisma generate

COPY tsconfig.json ./
COPY src ./src

RUN mkdir -p /app/instances

ENV SERVER_PORT=8080
ENV INSTANCE_DIR=/app/instances

EXPOSE 8080

CMD ["sh", "-c", "npx prisma migrate deploy && npx tsx src/main.ts"]
