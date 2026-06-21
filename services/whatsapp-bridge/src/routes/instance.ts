import { Router } from "express";
import {
  connectInstance,
  createInstanceRecord,
  deleteInstance,
  fetchAllInstances,
  getConnectionState,
  getQrResponse,
  logoutInstance,
  restartInstance,
} from "../baileys/manager.js";

export const instanceRouter = Router();

instanceRouter.post("/create", async (req, res) => {
  try {
    const result = await createInstanceRecord(req.body);
    res.status(201).json(result);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ status: 400, error: "Bad Request", response: { message: [msg] } });
  }
});

instanceRouter.get("/connect/:instanceName", async (req, res) => {
  try {
    const number = typeof req.query.number === "string" ? req.query.number : null;
    const result = await connectInstance(req.params.instanceName, number);
    res.json(result);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("does not exist")) {
      res.status(404).json({ status: 404, error: "Not Found", response: { message: [msg] } });
      return;
    }
    res.status(400).json({ error: true, message: msg });
  }
});

instanceRouter.get("/connectionState/:instanceName", (req, res) => {
  const name = req.params.instanceName;
  res.json({
    instance: {
      instanceName: name,
      state: getConnectionState(name),
    },
  });
});

instanceRouter.get("/fetchInstances", async (_req, res) => {
  try {
    const rows = await fetchAllInstances();
    res.json(
      rows.map((r) => ({
        instanceName: r.name,
        name: r.name,
        instanceId: r.id,
        ownerJid: r.ownerJid,
        connectionStatus: r.connectionStatus,
        integration: r.integration,
        profileName: r.profileName,
      })),
    );
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

instanceRouter.post("/restart/:instanceName", async (req, res) => {
  try {
    const result = await restartInstance(req.params.instanceName);
    res.json(result);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ error: true, message: msg });
  }
});

instanceRouter.delete("/logout/:instanceName", async (req, res) => {
  try {
    const result = await logoutInstance(req.params.instanceName);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

instanceRouter.delete("/delete/:instanceName", async (req, res) => {
  try {
    const result = await deleteInstance(req.params.instanceName);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: String(err) });
  }
});

// Evolution returns cached QR on connect — expose for debugging
instanceRouter.get("/qr/:instanceName", (req, res) => {
  res.json(getQrResponse(req.params.instanceName));
});
