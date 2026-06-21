import { Router } from "express";
import { setWebhookConfig } from "../baileys/manager.js";

export const webhookRouter = Router();

webhookRouter.post("/set/:instanceName", async (req, res) => {
  try {
    const body = req.body as {
      webhook?: {
        enabled?: boolean;
        url?: string;
        events?: string[];
        headers?: Record<string, string>;
        webhookByEvents?: boolean;
        webhookBase64?: boolean;
      };
    };
    const webhook = body.webhook || body;
    const row = await setWebhookConfig(req.params.instanceName, webhook as Parameters<typeof setWebhookConfig>[1]);
    res.json({ webhook: row });
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});
