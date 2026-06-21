import { Router } from "express";
import type { proto } from "baileys";
import { getBase64FromMediaMessage, markMessagesAsRead } from "../baileys/manager.js";

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
