import fs from "fs/promises";
import path from "path";
import { v4 as uuidv4 } from "uuid";
import QRCode from "qrcode";
import makeWASocket, {
  BufferJSON,
  DisconnectReason,
  downloadMediaMessage,
  initAuthCreds,
  fetchLatestBaileysVersion,
  Browsers,
  type AuthenticationState,
  type ConnectionState,
  type proto,
  type WASocket,
} from "baileys";
import { Boom } from "@hapi/boom";
import type { Instance, Webhook } from "@prisma/client";
import { config } from "../config.js";
import { prisma } from "../db.js";
import { createJid } from "../utils/jid.js";
import { emitWebhook } from "../webhook/emitter.js";

export type QrCache = {
  pairingCode: string | null;
  code: string | null;
  base64: string | null;
  count: number;
};

type LiveInstance = {
  db: Instance;
  socket: WASocket | null;
  qr: QrCache;
  webhook: Webhook | null;
  connecting: boolean;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  pairingActive: boolean;
};

const instances = new Map<string, LiveInstance>();
const recentInbound = new Map<string, proto.IWebMessageInfo[]>();
const contactIndex = new Map<string, Record<string, { jid: string; pushName: string; phone: string; updatedAt: number }>>();
const MAX_RECENT_INBOUND = 100;

function contactIndexPath(instanceName: string): string {
  return path.join(config.instanceDir, `contacts-${instanceName}.json`);
}

async function loadContactIndex(instanceName: string): Promise<void> {
  if (contactIndex.has(instanceName)) return;
  try {
    const raw = await fs.readFile(contactIndexPath(instanceName), "utf-8");
    const parsed = JSON.parse(raw) as Record<string, { jid: string; pushName: string; phone: string; updatedAt: number }>;
    contactIndex.set(instanceName, parsed);
  } catch {
    contactIndex.set(instanceName, {});
  }
}

async function persistContactIndex(instanceName: string): Promise<void> {
  const data = contactIndex.get(instanceName);
  if (!data) return;
  await fs.writeFile(contactIndexPath(instanceName), JSON.stringify(data, null, 2));
}

function rememberContact(instanceName: string, msg: proto.IWebMessageInfo): void {
  const jid = msg.key?.remoteJid || "";
  if (!jid || jid.includes("@g.us") || jid.includes("@broadcast")) return;
  const pushName = (msg.pushName || "").trim();
  const phone = jid.split("@")[0]?.split(":")[0] || "";
  const idx = contactIndex.get(instanceName) || {};
  idx[jid] = { jid, pushName, phone, updatedAt: Date.now() };
  if (pushName) {
    idx[`name:${pushName.toLowerCase()}`] = { jid, pushName, phone, updatedAt: Date.now() };
  }
  contactIndex.set(instanceName, idx);
  void persistContactIndex(instanceName);
}

function rememberInbound(instanceName: string, msg: proto.IWebMessageInfo): void {
  if (!hasAudio(msg.message) && !hasText(msg.message)) return;
  rememberContact(instanceName, msg);
  const list = recentInbound.get(instanceName) || [];
  list.unshift(msg);
  if (list.length > MAX_RECENT_INBOUND) list.length = MAX_RECENT_INBOUND;
  recentInbound.set(instanceName, list);
}

function unwrapMessageContent(message: proto.IMessage | null | undefined): proto.IMessage | null | undefined {
  let current = message;
  for (let i = 0; i < 5; i++) {
    if (!current) return current;
    const inner =
      current.ephemeralMessage?.message ||
      current.viewOnceMessage?.message ||
      current.viewOnceMessageV2?.message ||
      current.viewOnceMessageV2Extension?.message ||
      current.documentWithCaptionMessage?.message ||
      current.editedMessage?.message;
    if (!inner) break;
    current = inner;
  }
  return current;
}

function hasAudio(message: proto.IMessage | null | undefined): boolean {
  return Boolean(unwrapMessageContent(message)?.audioMessage);
}

function extractText(message: proto.IMessage | null | undefined): string {
  const content = unwrapMessageContent(message);
  if (!content) return "";
  if (content.conversation) return content.conversation;
  if (content.extendedTextMessage?.text) return content.extendedTextMessage.text;
  if (content.imageMessage?.caption) return content.imageMessage.caption || "";
  if (content.videoMessage?.caption) return content.videoMessage.caption || "";
  if (content.buttonsMessage?.contentText) return content.buttonsMessage.contentText;
  return "";
}

function hasText(message: proto.IMessage | null | undefined): boolean {
  return Boolean(extractText(message).trim());
}

function jidMatches(remoteJid: string | null | undefined, targetJid: string): boolean {
  const jid = remoteJid || "";
  if (!jid) return false;
  if (jid === targetJid) return true;
  const local = jid.split("@")[0]?.split(":")[0] || "";
  const targetLocal = targetJid.split("@")[0]?.split(":")[0] || "";
  return Boolean(local && targetLocal && (local.endsWith(targetLocal) || targetLocal.endsWith(local)));
}

function matchesHint(pushName: string | null | undefined, hint: string): boolean {
  const words = hint.toLowerCase().split(/\s+/).filter(Boolean);
  const name = (pushName || "").toLowerCase();
  if (!words.length) return true;
  return words.every((w) => name.includes(w));
}

const FALLBACK_WA_VERSION: [number, number, number] = [2, 3000, 1033893291];
let cachedWaVersion: [number, number, number] | null = null;

async function resolveWaVersion(): Promise<[number, number, number]> {
  if (cachedWaVersion) return cachedWaVersion;
  try {
    const { version } = await fetchLatestBaileysVersion();
    cachedWaVersion = version;
    return version;
  } catch (err) {
    console.warn("fetchLatestBaileysVersion failed, using fallback:", err);
    cachedWaVersion = FALLBACK_WA_VERSION;
    return FALLBACK_WA_VERSION;
  }
}

export async function ensureInstanceLoaded(name: string): Promise<LiveInstance | undefined> {
  const existing = instances.get(name);
  if (existing) return existing;
  const row = await prisma.instance.findUnique({
    where: { name },
    include: { Webhook: true },
  });
  if (!row || row.clientName !== config.clientName) return undefined;
  const live: LiveInstance = {
    db: row,
    socket: null,
    qr: { pairingCode: null, code: null, base64: null, count: 0 },
    webhook: row.Webhook,
    connecting: false,
    reconnectTimer: null,
    pairingActive: false,
  };
  instances.set(name, live);
  await loadContactIndex(name);
  return live;
}

function scheduleReconnect(name: string, delayMs = 5000): void {
  const live = instances.get(name);
  if (!live || live.pairingActive || live.connecting) return;
  if (live.reconnectTimer) return;
  live.reconnectTimer = setTimeout(() => {
    live.reconnectTimer = null;
    connectSocket(name).catch((err) => console.error("Reconnect failed:", err));
  }, delayMs);
}

function cancelReconnect(live: LiveInstance): void {
  if (live.reconnectTimer) {
    clearTimeout(live.reconnectTimer);
    live.reconnectTimer = null;
  }
}

function fixFileName(file: string): string | undefined {
  if (!file) return undefined;
  return file.replace(/\//g, "__").replace(/:/g, "-");
}

async function useMultiFileAuthState(sessionId: string): Promise<{
  state: AuthenticationState;
  saveCreds: () => Promise<void>;
  removeCreds: () => Promise<void>;
}> {
  const localFolder = path.join(config.instanceDir, sessionId);
  const localFile = (key: string) => path.join(localFolder, fixFileName(key)! + ".json");
  await fs.mkdir(localFolder, { recursive: true });

  async function writeData(data: unknown, key: string): Promise<void> {
    const dataString = JSON.stringify(data, BufferJSON.replacer);
    if (key !== "creds") {
      await fs.writeFile(localFile(key), dataString);
      return;
    }
    try {
      const instance = await prisma.instance.findUnique({ where: { id: sessionId } });
      if (!instance) {
        console.warn("Skipping creds save — instance %s no longer exists", sessionId);
        return;
      }
      await prisma.session.upsert({
        where: { sessionId },
        update: { creds: dataString },
        create: { sessionId, creds: dataString },
      });
    } catch (err) {
      console.error("Failed to persist session creds:", err);
    }
  }

  async function readData(key: string): Promise<unknown> {
    try {
      if (key !== "creds") {
        try {
          const raw = await fs.readFile(localFile(key), "utf-8");
          return JSON.parse(raw, BufferJSON.reviver);
        } catch {
          return null;
        }
      }
      const row = await prisma.session.findUnique({ where: { sessionId } });
      if (!row?.creds) return null;
      return JSON.parse(row.creds, BufferJSON.reviver);
    } catch {
      return null;
    }
  }

  async function removeData(key: string): Promise<void> {
    if (key !== "creds") {
      try {
        await fs.unlink(localFile(key));
      } catch {
        /* ignore */
      }
      return;
    }
    await prisma.session.deleteMany({ where: { sessionId } });
  }

  let creds = (await readData("creds")) as AuthenticationState["creds"] | null;
  if (!creds) {
    creds = initAuthCreds();
    await writeData(creds, "creds");
  }

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const data: Record<string, unknown> = {};
          await Promise.all(
            ids.map(async (id) => {
              data[id] = await readData(`${type}-${id}`);
            }),
          );
          // Baileys SignalDataTypeMap typing is strict; runtime values are correct.
          return data as never;
        },
        set: async (data) => {
          const tasks: Promise<void>[] = [];
          for (const category of Object.keys(data)) {
            for (const id of Object.keys(data[category as keyof typeof data] as object)) {
              const value = (data as Record<string, Record<string, unknown>>)[category][id];
              const key = `${category}-${id}`;
              tasks.push(value ? writeData(value, key) : removeData(key));
            }
          }
          await Promise.all(tasks);
        },
      },
    },
    saveCreds: async () => writeData(creds, "creds"),
    removeCreds: async () => removeData("creds"),
  };
}

async function updateStatus(name: string, status: "open" | "close" | "connecting", ownerJid?: string): Promise<void> {
  const live = instances.get(name);
  if (live) {
    live.db.connectionStatus = status;
    if (ownerJid) live.db.ownerJid = ownerJid;
  }
  await prisma.instance.update({
    where: { name },
    data: {
      connectionStatus: status,
      ...(ownerJid ? { ownerJid } : {}),
    },
  });
}

function isReadableJid(jid: string): boolean {
  return !jid.includes("@broadcast") && !jid.includes("@newsletter");
}

async function shouldAutoReadMessages(instanceId: string): Promise<boolean> {
  const row = await prisma.setting.findUnique({ where: { instanceId } });
  return row?.readMessages ?? true;
}

async function markInboundMessageRead(
  socket: WASocket,
  msg: proto.IWebMessageInfo,
): Promise<void> {
  const key = msg.key;
  if (!key?.remoteJid || !key.id || key.fromMe || !isReadableJid(key.remoteJid)) return;
  try {
    await socket.readMessages([
      {
        remoteJid: key.remoteJid,
        id: key.id,
        fromMe: false,
        ...(key.participant ? { participant: key.participant } : {}),
      },
    ]);
  } catch (err) {
    console.warn("Failed to mark message as read:", err);
  }
}

async function handleConnectionUpdate(name: string, update: Partial<ConnectionState>): Promise<void> {
  const live = instances.get(name);
  if (!live) return;
  const { connection, lastDisconnect, qr } = update;

  if (qr) {
    live.qr.count += 1;
    live.qr.code = qr;
    live.qr.pairingCode = null;
    try {
      live.qr.base64 = await QRCode.toDataURL(qr, {
        margin: 3,
        scale: 4,
        errorCorrectionLevel: "H",
        color: { light: "#ffffff", dark: config.qrcodeColor },
      });
    } catch (err) {
      console.error("QR encode failed:", err);
    }
    await updateStatus(name, "connecting");
    await emitWebhook(live.webhook, {
      event: "QRCODE_UPDATED",
      instance: name,
      data: {
        qrcode: {
          instance: name,
          pairingCode: live.qr.pairingCode,
          code: qr,
          base64: live.qr.base64,
        },
      },
    });
  }

  if (connection === "close") {
    const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
    const loggedOut = statusCode === DisconnectReason.loggedOut;
    await updateStatus(name, "close");
    await emitWebhook(live.webhook, {
      event: "CONNECTION_UPDATE",
      instance: name,
      data: { instance: name, state: "close", statusReason: statusCode ?? 200 },
    });
    live.socket = null;
    live.connecting = false;
    if (!loggedOut) {
      // Drop expired QR so clients never scan a stale code after "QR refs attempts ended".
      live.qr = { pairingCode: null, code: null, base64: null, count: live.qr.count };
    }
    if (!loggedOut && statusCode !== DisconnectReason.forbidden && !live.pairingActive) {
      scheduleReconnect(name, 3000);
    }
  }

  if (connection === "open" && live.socket?.user) {
    const ownerJid = live.socket.user.id.replace(/:\d+/, "");
    live.qr = { pairingCode: null, code: null, base64: null, count: 0 };
    await updateStatus(name, "open", ownerJid);
    await emitWebhook(live.webhook, {
      event: "CONNECTION_UPDATE",
      instance: name,
      data: { instance: name, state: "open" },
    });
  }
}

async function connectSocket(name: string, phoneNumber?: string): Promise<WASocket> {
  const live = await ensureInstanceLoaded(name);
  if (!live) throw new Error(`Instance ${name} not loaded`);

  if (live.connecting) {
    for (let i = 0; i < 60 && live.connecting && !live.socket; i++) {
      await new Promise((r) => setTimeout(r, 500));
    }
    if (live.socket) return live.socket;
  }

  cancelReconnect(live);
  live.connecting = true;
  try {
    if (live.socket) {
      try {
        live.socket.ws?.close();
        live.socket.end(undefined);
      } catch {
        /* ignore */
      }
      live.socket = null;
    }

    const { state, saveCreds } = await useMultiFileAuthState(live.db.id);
    const version = await resolveWaVersion();
    const socket = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      browser: Browsers.macOS("Chrome"),
      syncFullHistory: false,
      markOnlineOnConnect: false,
      fireInitQueries: false,
      generateHighQualityLinkPreview: false,
      connectTimeoutMs: 60000,
      defaultQueryTimeoutMs: 60000,
      keepAliveIntervalMs: 30000,
    });

    live.socket = socket;
    socket.ev.on("creds.update", saveCreds);
    socket.ev.on("connection.update", (u) => {
      handleConnectionUpdate(name, u).catch(console.error);
    });

    socket.ev.on("messages.upsert", async ({ messages, type }) => {
      const autoRead = await shouldAutoReadMessages(live.db.id);
      for (const msg of messages) {
        if (type === "notify") {
          rememberInbound(name, msg);
          await emitWebhook(live.webhook, {
            event: "MESSAGES_UPSERT",
            instance: name,
            data: msg,
          });
        }
        if (autoRead) {
          void markInboundMessageRead(socket, msg);
        }
      }
    });

    if (phoneNumber) {
      try {
        live.qr.pairingCode = await socket.requestPairingCode(phoneNumber);
      } catch {
        /* pairing code optional */
      }
    }

    return socket;
  } finally {
    live.connecting = false;
  }
}

export async function bootstrapInstances(): Promise<void> {
  await fs.mkdir(config.instanceDir, { recursive: true });
  await prisma.setting.updateMany({ data: { readMessages: true } });
  const rows = await prisma.instance.findMany({
    where: { clientName: config.clientName },
    include: { Webhook: true },
  });
  for (const row of rows) {
    instances.set(row.name, {
      db: row,
      socket: null,
      qr: { pairingCode: null, code: null, base64: null, count: 0 },
      webhook: row.Webhook,
      connecting: false,
      reconnectTimer: null,
      pairingActive: false,
    });
    if (row.connectionStatus === "open" || row.connectionStatus === "connecting" || row.ownerJid) {
      connectSocket(row.name).catch(console.error);
    }
  }
}

export function getLive(name: string): LiveInstance | undefined {
  return instances.get(name);
}

export function getConnectionState(name: string): string {
  const live = instances.get(name);
  if (!live) return "close";
  if (live.socket?.user) return "open";
  return live.db.connectionStatus;
}

export function getQrResponse(name: string): Record<string, unknown> {
  const live = instances.get(name);
  if (!live) return { error: true, message: "Instance not found" };
  const state = getConnectionState(name);
  if (state === "open") {
    return { instance: { instanceName: name, state: "open" } };
  }
  return {
    pairingCode: live.qr.pairingCode,
    code: live.qr.code,
    base64: live.qr.base64,
    count: live.qr.count,
  };
}

export async function createInstanceRecord(body: {
  instanceName: string;
  integration?: string;
  token?: string;
}): Promise<Record<string, unknown>> {
  const name = body.instanceName;
  const existing = await prisma.instance.findUnique({ where: { name } });
  if (existing) {
    throw new Error("Instance already in use");
  }
  const instanceId = uuidv4();
  const token = body.token || uuidv4().toUpperCase();
  const row = await prisma.instance.create({
    data: {
      id: instanceId,
      name,
      integration: body.integration || "WHATSAPP-BAILEYS",
      token,
      clientName: config.clientName,
      connectionStatus: "close",
    },
  });
  await prisma.setting.create({
    data: {
      instanceId,
      rejectCall: false,
      groupsIgnore: false,
      alwaysOnline: false,
      readMessages: true,
      readStatus: false,
      syncFullHistory: false,
    },
  });
  instances.set(name, {
    db: row,
    socket: null,
    qr: { pairingCode: null, code: null, base64: null, count: 0 },
    webhook: null,
    connecting: false,
    reconnectTimer: null,
    pairingActive: false,
  });
  return {
    instance: {
      instanceName: name,
      instanceId,
      integration: row.integration,
      status: "close",
    },
    hash: token,
    settings: {
      rejectCall: false,
      groupsIgnore: false,
      alwaysOnline: false,
      readMessages: true,
      readStatus: false,
      syncFullHistory: false,
    },
  };
}

export async function connectInstance(name: string, number?: string | null): Promise<Record<string, unknown>> {
  const live = await ensureInstanceLoaded(name);
  if (!live) throw new Error(`The "${name}" instance does not exist`);
  const state = getConnectionState(name);
  if (state === "open") {
    return { instance: { instanceName: name, state: "open" } };
  }
  if (live.qr.base64) {
    return getQrResponse(name);
  }
  if (live.pairingActive || live.connecting) {
    for (let i = 0; i < 45; i++) {
      if (live.qr.base64) return getQrResponse(name);
      if (getConnectionState(name) === "open") {
        return { instance: { instanceName: name, state: "open" } };
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    return getQrResponse(name);
  }

  live.pairingActive = true;
  try {
    await connectSocket(name, number || undefined);
    for (let i = 0; i < 45; i++) {
      if (live.qr.base64) {
        return getQrResponse(name);
      }
      if (getConnectionState(name) === "open") {
        return { instance: { instanceName: name, state: "open" } };
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    return getQrResponse(name);
  } finally {
    live.pairingActive = false;
  }
}

export async function restartInstance(name: string): Promise<Record<string, unknown>> {
  const live = await ensureInstanceLoaded(name);
  if (!live) throw new Error(`The "${name}" instance does not exist`);
  cancelReconnect(live);
  if (live.socket) {
    try {
      live.socket.ws?.close();
      live.socket.end(new Error("restart"));
    } catch {
      /* ignore */
    }
    live.socket = null;
  }
  await updateStatus(name, "close");
  live.pairingActive = true;
  try {
    await connectSocket(name);
    for (let i = 0; i < 30; i++) {
      if (live.qr.base64 || getConnectionState(name) === "open") break;
      await new Promise((r) => setTimeout(r, 1000));
    }
  } finally {
    live.pairingActive = false;
  }
  return {
    instance: { instanceName: name, status: getConnectionState(name) },
    ...getQrResponse(name),
  };
}

export async function logoutInstance(name: string): Promise<Record<string, unknown>> {
  const live = instances.get(name);
  if (!live) return { status: "disconnected" };
  if (live.socket) {
    try {
      await live.socket.logout("User logout");
    } catch {
      /* ignore */
    }
    live.socket = null;
  }
  await updateStatus(name, "close");
  live.db.ownerJid = null;
  await prisma.instance.update({ where: { name }, data: { ownerJid: null } });
  return { status: "SUCCESS", response: { message: "Instance logged out" } };
}

export async function deleteInstance(name: string): Promise<Record<string, unknown>> {
  const live = instances.get(name);
  if (live?.socket) {
    try {
      live.socket.ws?.close();
      live.socket.end(undefined);
    } catch {
      /* ignore */
    }
  }
  const row = await prisma.instance.findUnique({ where: { name } });
  if (row) {
    const folder = path.join(config.instanceDir, row.id);
    await fs.rm(folder, { recursive: true, force: true }).catch(() => undefined);
    await prisma.instance.delete({ where: { name } });
  }
  instances.delete(name);
  return { status: "SUCCESS", response: { message: "Instance deleted" } };
}

export async function fetchAllInstances(): Promise<Instance[]> {
  return prisma.instance.findMany({ where: { clientName: config.clientName } });
}

export async function setWebhookConfig(
  name: string,
  webhook: {
    enabled?: boolean;
    url?: string;
    events?: string[];
    headers?: Record<string, string>;
    webhookByEvents?: boolean;
    webhookBase64?: boolean;
  },
): Promise<Webhook> {
  const live = instances.get(name);
  if (!live) throw new Error(`Instance ${name} not found`);
  const events = webhook.enabled === false ? [] : webhook.events || [];
  const row = await prisma.webhook.upsert({
    where: { instanceId: live.db.id },
    update: {
      enabled: webhook.enabled ?? true,
      url: webhook.url || "",
      events,
      headers: webhook.headers || {},
      webhookByEvents: webhook.webhookByEvents ?? false,
      webhookBase64: webhook.webhookBase64 ?? false,
    },
    create: {
      instanceId: live.db.id,
      enabled: webhook.enabled ?? true,
      url: webhook.url || "",
      events,
      headers: webhook.headers || {},
      webhookByEvents: webhook.webhookByEvents ?? false,
      webhookBase64: webhook.webhookBase64 ?? false,
    },
  });
  live.webhook = row;
  return row;
}

export async function markMessagesAsRead(
  name: string,
  readMessages: Array<{
    remoteJid: string;
    id: string;
    fromMe?: boolean;
    participant?: string;
  }>,
): Promise<{ message: string; read: string }> {
  const live = instances.get(name);
  if (!live?.socket) throw new Error("Instance not connected");
  const keys = readMessages
    .filter((item) => item.remoteJid && item.id && isReadableJid(item.remoteJid))
    .map((item) => ({
      remoteJid: item.remoteJid,
      id: item.id,
      fromMe: item.fromMe ?? false,
      ...(item.participant ? { participant: item.participant } : {}),
    }));
  if (!keys.length) {
    return { message: "No readable messages", read: "skipped" };
  }
  await live.socket.readMessages(keys);
  return { message: "Read messages", read: "success" };
}

export async function sendText(name: string, number: string, text: string): Promise<unknown> {
  const live = instances.get(name);
  if (!live?.socket) throw new Error("Instance not connected");
  const jid = createJid(number);
  return live.socket.sendMessage(jid, { text });
}

export async function sendMedia(
  name: string,
  number: string,
  media: string,
  mediatype: string,
  fileName: string,
  caption: string,
): Promise<unknown> {
  const live = instances.get(name);
  if (!live?.socket) throw new Error("Instance not connected");
  const jid = createJid(number);
  const buffer = Buffer.from(media, "base64");
  if (mediatype === "image") {
    return live.socket.sendMessage(jid, { image: buffer, caption: caption || undefined });
  }
  if (mediatype === "video") {
    return live.socket.sendMessage(jid, { video: buffer, caption: caption || undefined });
  }
  if (mediatype === "audio") {
    return live.socket.sendMessage(jid, { audio: buffer, mimetype: "audio/ogg; codecs=opus" });
  }
  return live.socket.sendMessage(jid, {
    document: buffer,
    mimetype: "application/octet-stream",
    fileName: fileName || "file",
    caption: caption || undefined,
  });
}

export async function getBase64FromMediaMessage(
  name: string,
  message: proto.IWebMessageInfo,
): Promise<{ base64: string; mimetype?: string }> {
  const live = instances.get(name);
  if (!live?.socket) throw new Error("Instance not connected");
  if (!message.key) throw new Error("Message key required");
  const waMessage = { ...message, key: message.key };
  const buffer = (await downloadMediaMessage(
    waMessage as Parameters<typeof downloadMediaMessage>[0],
    "buffer",
    {},
    { logger: undefined as never, reuploadRequest: live.socket.updateMediaMessage },
  )) as Buffer;
  const b64 = buffer.toString("base64");
  const msg = message.message;
  let mimetype = "application/octet-stream";
  if (msg?.audioMessage?.mimetype) mimetype = msg.audioMessage.mimetype;
  else if (msg?.imageMessage?.mimetype) mimetype = msg.imageMessage.mimetype;
  else if (msg?.videoMessage?.mimetype) mimetype = msg.videoMessage.mimetype;
  else if (msg?.documentMessage?.mimetype) mimetype = msg.documentMessage.mimetype;
  return { base64: b64, mimetype };
}

export function listRecentInboundVoice(instanceName: string, limit = 20): Array<{
  pushName: string;
  jid: string;
  id: string;
  timestamp: number | null | undefined;
}> {
  const list = recentInbound.get(instanceName) || [];
  const out: Array<{
    pushName: string;
    jid: string;
    id: string;
    timestamp: number | null | undefined;
  }> = [];
  for (const msg of list) {
    if (!hasAudio(msg.message)) continue;
    const ts = msg.messageTimestamp;
    out.push({
      pushName: msg.pushName || "",
      jid: msg.key?.remoteJid || "",
      id: msg.key?.id || "",
      timestamp: typeof ts === "number" ? ts : ts != null ? Number(ts) : undefined,
    });
    if (out.length >= limit) break;
  }
  return out;
}

export function findRecentVoiceByHint(
  instanceName: string,
  hint: string,
  options?: { latest?: boolean },
): proto.IWebMessageInfo | null {
  const latest = Boolean(options?.latest);
  const list = recentInbound.get(instanceName) || [];
  if (latest && !hint.trim()) {
    for (const msg of list) {
      if (hasAudio(msg.message)) return msg;
    }
    return null;
  }
  for (const msg of list) {
    if (!hasAudio(msg.message)) continue;
    if (matchesHint(msg.pushName, hint)) return msg;
  }
  if (latest) {
    for (const msg of list) {
      if (hasAudio(msg.message)) return msg;
    }
  }
  for (const msg of list) {
    if (!hasAudio(msg.message)) continue;
    if (!hint.trim()) return msg;
    const jid = msg.key?.remoteJid || "";
    if (jid.toLowerCase().includes(hint.replace(/\s+/g, ""))) return msg;
  }
  return null;
}

export async function fetchVoiceHistoryForJid(
  instanceName: string,
  jid: string,
  hint: string,
  options?: { fromMe?: boolean },
): Promise<proto.IWebMessageInfo | null> {
  const live = instances.get(instanceName);
  if (!live?.socket) throw new Error("Instance not connected");
  const sock = live.socket;
  const targetJid = jid.includes("@") ? jid : createJid(jid);
  const fromMe = Boolean(options?.fromMe);

  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      cleanup();
      resolve(findRecentVoiceByHint(instanceName, hint, { latest: true }));
    }, 15000);

    const onHistory = (events: { "messaging.history-set"?: { messages?: proto.IWebMessageInfo[] } }) => {
      const batch = events["messaging.history-set"]?.messages || [];
      for (const msg of batch) {
        if (msg.key?.remoteJid !== targetJid && !targetJid.endsWith(msg.key?.remoteJid || "xxx")) continue;
        if (!hasAudio(msg.message)) continue;
        if (fromMe && !msg.key?.fromMe) continue;
        if (!fromMe && msg.key?.fromMe) continue;
        if (hint.trim() && !matchesHint(msg.pushName, hint)) continue;
        cleanup();
        resolve(msg);
        return;
      }
    };

    const cleanup = () => {
      clearTimeout(timeout);
      sock.ev.off("messaging.history-set", onHistory);
    };

    sock.ev.on("messaging.history-set", onHistory);
    sock
      .fetchMessageHistory(30, { remoteJid: targetJid, fromMe, id: "", participant: undefined }, 0)
      .catch(() => {
        cleanup();
        resolve(findRecentVoiceByHint(instanceName, hint, { latest: true }));
      });
  });
}

export function findJidByNameHint(
  instanceName: string,
  hint: string,
): { jid: string; pushName: string } | null {
  const words = hint.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const list = recentInbound.get(instanceName) || [];
  for (const msg of list) {
    const jid = msg.key?.remoteJid || "";
    if (!jid || jid.includes("@g.us") || jid.includes("@broadcast")) continue;
    if (!matchesHint(msg.pushName, hint)) continue;
    return { jid, pushName: msg.pushName || hint };
  }
  const idx = contactIndex.get(instanceName) || {};
  for (const entry of Object.values(idx)) {
    if (entry?.pushName && matchesHint(entry.pushName, hint)) {
      return { jid: entry.jid, pushName: entry.pushName };
    }
  }
  return null;
}

export function listKnownContacts(instanceName: string): Array<{ jid: string; pushName: string; phone: string }> {
  const idx = contactIndex.get(instanceName) || {};
  const seen = new Set<string>();
  const out: Array<{ jid: string; pushName: string; phone: string }> = [];
  for (const entry of Object.values(idx)) {
    if (!entry?.jid || seen.has(entry.jid)) continue;
    seen.add(entry.jid);
    out.push({ jid: entry.jid, pushName: entry.pushName || "", phone: entry.phone || "" });
  }
  out.sort((a, b) => a.pushName.localeCompare(b.pushName));
  return out;
}

async function fetchHistoryBatch(
  sock: ReturnType<typeof makeWASocket>,
  targetJid: string,
  fromMe: boolean,
  count: number,
): Promise<proto.IWebMessageInfo[]> {
  return new Promise((resolve) => {
    const collected: proto.IWebMessageInfo[] = [];
    const timeout = setTimeout(() => {
      cleanup();
      resolve(collected);
    }, 15000);

    const onHistory = (events: { "messaging.history-set"?: { messages?: proto.IWebMessageInfo[] } }) => {
      const batch = events["messaging.history-set"]?.messages || [];
      for (const msg of batch) {
        if (!jidMatches(msg.key?.remoteJid, targetJid)) continue;
        if (Boolean(msg.key?.fromMe) !== fromMe) continue;
        if (!hasText(msg.message) && !hasAudio(msg.message)) continue;
        collected.push(msg);
      }
    };

    const cleanup = () => {
      clearTimeout(timeout);
      sock.ev.off("messaging.history-set", onHistory);
    };

    sock.ev.on("messaging.history-set", onHistory);
    sock
      .fetchMessageHistory(count, { remoteJid: targetJid, fromMe, id: "", participant: undefined }, 0)
      .catch(() => {
        cleanup();
        resolve(collected);
      });
  });
}

export type ContactTextMessage = {
  text: string;
  fromMe: boolean;
  pushName: string;
  jid: string;
  id: string;
  timestamp: number | null;
};

export async function fetchContactTextHistory(
  instanceName: string,
  options: { hint?: string; number?: string; jid?: string; limit?: number },
): Promise<{ contact: string; jid: string; messages: ContactTextMessage[] }> {
  const live = instances.get(instanceName);
  if (!live?.socket) throw new Error("Instance not connected");
  const sock = live.socket;
  const limit = Math.min(Math.max(options.limit ?? 50, 1), 100);
  const hint = String(options.hint || "").trim();

  let targetJid = String(options.jid || "").trim();
  let contact = hint || "Contact";
  if (!targetJid && options.number) {
    targetJid = createJid(options.number);
  }
  if (!targetJid && hint) {
    const found = findJidByNameHint(instanceName, hint);
    if (found) {
      targetJid = found.jid;
      contact = found.pushName || hint;
    }
  }
  if (!targetJid) {
    throw new Error(`Could not find WhatsApp chat for '${hint || options.number || "contact"}'`);
  }
  if (!targetJid.includes("@")) {
    targetJid = createJid(targetJid);
  }

  const batches = await Promise.all([
    fetchHistoryBatch(sock, targetJid, false, limit),
    fetchHistoryBatch(sock, targetJid, true, limit),
  ]);
  const byId = new Map<string, ContactTextMessage>();
  const ingest = (msg: proto.IWebMessageInfo) => {
    const id = msg.key?.id || "";
    if (!id || byId.has(id)) return;
    const text = extractText(msg.message);
    if (!text.trim()) return;
    const ts = msg.messageTimestamp;
    byId.set(id, {
      text: text.trim(),
      fromMe: Boolean(msg.key?.fromMe),
      pushName: msg.pushName || contact,
      jid: msg.key?.remoteJid || targetJid,
      id,
      timestamp: typeof ts === "number" ? ts : ts != null ? Number(ts) : null,
    });
  };
  for (const msg of recentInbound.get(instanceName) || []) {
    if (!jidMatches(msg.key?.remoteJid, targetJid)) continue;
    ingest(msg);
  }
  for (const msg of [...batches[0], ...batches[1]]) ingest(msg);

  const messages = [...byId.values()].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
  if (messages.length && !hint) {
    contact = messages.find((m) => !m.fromMe)?.pushName || contact;
  }
  return { contact, jid: targetJid, messages: messages.slice(-limit) };
}

export async function fetchVoiceByKey(
  instanceName: string,
  key: { remoteJid: string; id: string; fromMe?: boolean },
  timestampMs = 0,
): Promise<proto.IWebMessageInfo | null> {
  const live = instances.get(instanceName);
  if (!live?.socket) throw new Error("Instance not connected");
  const sock = live.socket;
  const targetKey = {
    remoteJid: key.remoteJid,
    id: key.id,
    fromMe: Boolean(key.fromMe),
    participant: undefined as string | undefined,
  };

  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      cleanup();
      resolve(null);
    }, 15000);

    const onHistory = (events: { "messaging.history-set"?: { messages?: proto.IWebMessageInfo[] } }) => {
      const batch = events["messaging.history-set"]?.messages || [];
      for (const msg of batch) {
        if (msg.key?.id !== targetKey.id) continue;
        if (msg.key?.remoteJid !== targetKey.remoteJid) continue;
        if (!hasAudio(msg.message)) continue;
        cleanup();
        resolve(msg);
        return;
      }
    };

    const cleanup = () => {
      clearTimeout(timeout);
      sock.ev.off("messaging.history-set", onHistory);
    };

    sock.ev.on("messaging.history-set", onHistory);
    sock.fetchMessageHistory(30, targetKey, timestampMs).catch(() => {
      cleanup();
      resolve(null);
    });
  });
}
