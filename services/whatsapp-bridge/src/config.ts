import dotenv from "dotenv";

dotenv.config();

export const config = {
  port: parseInt(process.env.SERVER_PORT || "8080", 10),
  serverUrl: process.env.SERVER_URL || "http://localhost:8080",
  apiKey: process.env.AUTHENTICATION_API_KEY || process.env.EVOLUTION_API_KEY || "tempa-evolution-key",
  databaseUri: process.env.DATABASE_CONNECTION_URI || "",
  clientName: process.env.DATABASE_CONNECTION_CLIENT_NAME || "tempa",
  instanceDir: process.env.INSTANCE_DIR || "./instances",
  qrcodeColor: process.env.QRCODE_COLOR || "#198754",
};
