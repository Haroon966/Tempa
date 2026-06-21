import { Router } from "express";
import { sendMedia, sendText } from "../baileys/manager.js";

export const messageRouter = Router();

messageRouter.post("/sendText/:instanceName", async (req, res) => {
  try {
    const { number, text } = req.body as { number?: string; text?: string };
    if (!number || !text) {
      res.status(400).json({ error: "number and text required" });
      return;
    }
    const result = await sendText(req.params.instanceName, number, text);
    res.json({ key: (result as { key?: unknown })?.key, message: result });
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

messageRouter.post("/sendMedia/:instanceName", async (req, res) => {
  try {
    const { number, media, mediatype, fileName, caption } = req.body as {
      number?: string;
      media?: string;
      mediatype?: string;
      fileName?: string;
      caption?: string;
    };
    if (!number || !media) {
      res.status(400).json({ error: "number and media required" });
      return;
    }
    const result = await sendMedia(
      req.params.instanceName,
      number,
      media,
      mediatype || "document",
      fileName || "file",
      caption || "",
    );
    res.json({ key: (result as { key?: unknown })?.key, message: result });
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});
