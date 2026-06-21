-- CreateEnum
CREATE TYPE "InstanceConnectionStatus" AS ENUM ('open', 'close', 'connecting');

-- CreateTable
CREATE TABLE "Instance" (
    "id" TEXT NOT NULL,
    "name" VARCHAR(255) NOT NULL,
    "connectionStatus" "InstanceConnectionStatus" NOT NULL DEFAULT 'close',
    "ownerJid" VARCHAR(100),
    "profileName" VARCHAR(100),
    "profilePicUrl" VARCHAR(500),
    "integration" VARCHAR(100),
    "number" VARCHAR(100),
    "token" VARCHAR(255),
    "clientName" VARCHAR(100),
    "disconnectionReasonCode" INTEGER,
    "disconnectionObject" JSONB,
    "disconnectionAt" TIMESTAMP,
    "createdAt" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP,

    CONSTRAINT "Instance_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" TEXT NOT NULL,
    "sessionId" TEXT NOT NULL,
    "creds" TEXT,
    "createdAt" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Webhook" (
    "id" TEXT NOT NULL,
    "url" VARCHAR(500) NOT NULL,
    "headers" JSONB,
    "enabled" BOOLEAN DEFAULT true,
    "events" JSONB,
    "webhookByEvents" BOOLEAN DEFAULT false,
    "webhookBase64" BOOLEAN DEFAULT false,
    "createdAt" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP NOT NULL,
    "instanceId" TEXT NOT NULL,

    CONSTRAINT "Webhook_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Setting" (
    "id" TEXT NOT NULL,
    "rejectCall" BOOLEAN NOT NULL DEFAULT false,
    "msgCall" VARCHAR(100),
    "groupsIgnore" BOOLEAN NOT NULL DEFAULT false,
    "alwaysOnline" BOOLEAN NOT NULL DEFAULT false,
    "readMessages" BOOLEAN NOT NULL DEFAULT false,
    "readStatus" BOOLEAN NOT NULL DEFAULT false,
    "syncFullHistory" BOOLEAN NOT NULL DEFAULT false,
    "wavoipToken" VARCHAR(100),
    "createdAt" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP NOT NULL,
    "instanceId" TEXT NOT NULL,

    CONSTRAINT "Setting_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Instance_name_key" ON "Instance"("name");

-- CreateIndex
CREATE UNIQUE INDEX "Session_sessionId_key" ON "Session"("sessionId");

-- CreateIndex
CREATE UNIQUE INDEX "Webhook_instanceId_key" ON "Webhook"("instanceId");

-- CreateIndex
CREATE INDEX "Webhook_instanceId_idx" ON "Webhook"("instanceId");

-- CreateIndex
CREATE UNIQUE INDEX "Setting_instanceId_key" ON "Setting"("instanceId");

-- CreateIndex
CREATE INDEX "Setting_instanceId_idx" ON "Setting"("instanceId");

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "Instance"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Webhook" ADD CONSTRAINT "Webhook_instanceId_fkey" FOREIGN KEY ("instanceId") REFERENCES "Instance"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Setting" ADD CONSTRAINT "Setting_instanceId_fkey" FOREIGN KEY ("instanceId") REFERENCES "Instance"("id") ON DELETE CASCADE ON UPDATE CASCADE;
