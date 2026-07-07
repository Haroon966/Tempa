import { Router } from "express";
import type { proto } from "baileys";
import {
  fetchContactTextHistory,
  fetchVoiceByKey,
  fetchVoiceHistoryForJid,
  findJidByNameHint,
  findRecentVoiceByHint,
  getBase64FromMediaMessage,
  listKnownContacts,
  listRecentInboundVoice,
  markMessagesAsRead,
} from "../baileys/manager.js";
import { createJid } from "../utils/jid.js";

export const chatRouter = Router();

chatRouter.post("/markMessageAsRead/:instanceName", async (req, res) => {
  try {
    const body = req.body as {
      readMessages?: Array<{
        remoteJid?: string;
        id?: string;
        fromMe?: boolean;
        participant?: string;
      }>;
    };
    const readMessages = body.readMessages || [];
    if (!readMessages.length) {
      res.status(400).json({ error: "readMessages required" });
      return;
    }
    const result = await markMessagesAsRead(req.params.instanceName, readMessages);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

chatRouter.post("/getBase64FromMediaMessage/:instanceName", async (req, res) => {
  try {
    const body = req.body as { message?: proto.IWebMessageInfo };
    const message = body.message;
    if (!message) {
      res.status(400).json({ error: "message required" });
      return;
    }
    const result = await getBase64FromMediaMessage(req.params.instanceName, message);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

chatRouter.get("/recentVoice/:instanceName", (req, res) => {
  const limit = Number(req.query.limit || 20);
  res.json({ voices: listRecentInboundVoice(req.params.instanceName, limit) });
});

chatRouter.post("/fetchContactHistory/:instanceName", async (req, res) => {
  try {
    const body = req.body as { hint?: string; number?: string; jid?: string; limit?: number };
    const result = await fetchContactTextHistory(req.params.instanceName, {
      hint: body.hint,
      number: body.number,
      jid: body.jid,
      limit: body.limit,
    });
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

chatRouter.post("/matchContacts/:instanceName", (req, res) => {
  const body = req.body as { hint?: string };
  const hint = String(body.hint || "").trim().toLowerCase();
  const words = hint.split(/\s+/).filter(Boolean);
  const contacts = listKnownContacts(req.params.instanceName);
  const matches = contacts.filter((c) => {
    const name = (c.pushName || "").toLowerCase();
    return words.length ? words.every((w) => name.includes(w)) : name.includes(hint);
  });
  res.json({ matches });
});

chatRouter.get("/contacts/:instanceName", (req, res) => {
  res.json({ contacts: listKnownContacts(req.params.instanceName) });
});

chatRouter.post("/findVoice/:instanceName", async (req, res) => {
  try {
    const body = req.body as { hint?: string; jid?: string; number?: string; latest?: boolean };
    const hint = String(body.hint || "zeeshan").trim();
    const latest = Boolean(body.latest);
    const instanceName = req.params.instanceName;
    let msg: proto.IWebMessageInfo | null = findRecentVoiceByHint(instanceName, hint, { latest });
    const jid = body.jid || (body.number ? createJid(body.number) : "");
    if (!msg && jid) {
      msg = await fetchVoiceHistoryForJid(instanceName, jid, hint, { fromMe: true });
      if (!msg) {
        msg = await fetchVoiceHistoryForJid(instanceName, jid, hint, { fromMe: false });
      }
    }
    if (!msg) {
      res.status(404).json({ error: "no voice message found", hint });
      return;
    }
    res.json({
      pushName: msg.pushName || "",
      jid: msg.key?.remoteJid || "",
      id: msg.key?.id || "",
      message: msg,
    });
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

chatRouter.post("/fetchVoiceByKey/:instanceName", async (req, res) => {
  try {
    const body = req.body as {
      remoteJid?: string;
      id?: string;
      fromMe?: boolean;
      timestampMs?: number;
    };
    const remoteJid = String(body.remoteJid || "").trim();
    const id = String(body.id || "").trim();
    if (!remoteJid || !id) {
      res.status(400).json({ error: "remoteJid and id required" });
      return;
    }
    const msg = await fetchVoiceByKey(
      req.params.instanceName,
      { remoteJid, id, fromMe: Boolean(body.fromMe) },
      Number(body.timestampMs || 0),
    );
    if (!msg) {
      res.status(404).json({ error: "voice message not found", id });
      return;
    }
    res.json({
      pushName: msg.pushName || "",
      jid: msg.key?.remoteJid || "",
      id: msg.key?.id || "",
      message: msg,
    });
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});
