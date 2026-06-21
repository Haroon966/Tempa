import express from "express";
import cors from "cors";
import { config } from "./config.js";
import { authGuard } from "./middleware/auth.js";
import { bootstrapInstances } from "./baileys/manager.js";
import { instanceRouter } from "./routes/instance.js";
import { messageRouter } from "./routes/message.js";
import { chatRouter } from "./routes/chat.js";
import { webhookRouter } from "./routes/webhook.js";

const app = express();
app.use(cors());
app.use(express.json({ limit: "50mb" }));

app.get("/", (_req, res) => {
  res.json({
    status: 200,
    message: "Tempa WhatsApp Bridge is working!",
    version: "1.0.0",
    clientName: config.clientName,
  });
});

app.use(authGuard);

app.use("/instance", instanceRouter);
app.use("/message", messageRouter);
app.use("/chat", chatRouter);
app.use("/webhook", webhookRouter);

async function main(): Promise<void> {
  await bootstrapInstances();
  app.listen(config.port, () => {
    console.log(`WhatsApp bridge listening on http://0.0.0.0:${config.port}`);
  });
}

main().catch((err) => {
  console.error("Failed to start WhatsApp bridge:", err);
  process.exit(1);
});
