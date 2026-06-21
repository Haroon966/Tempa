import type { Webhook } from "@prisma/client";

export type WebhookPayload = {
  event: string;
  instance: string;
  data: unknown;
};

export async function emitWebhook(
  webhook: Webhook | null,
  payload: WebhookPayload,
): Promise<void> {
  if (!webhook?.enabled || !webhook.url) return;
  const events = (webhook.events as string[] | null) || [];
  const eventNorm = payload.event.toUpperCase().replace(/[.-]/g, "_");
  if (events.length > 0 && !events.some((e) => e.toUpperCase().replace(/[.-]/g, "_") === eventNorm)) {
    return;
  }
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "User-Agent": "Tempa-WhatsApp-Bridge",
      ...(webhook.headers as Record<string, string> | null),
    };
    await fetch(webhook.url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(30000),
    });
  } catch (err) {
    console.error(`Webhook delivery failed for ${payload.event}:`, err);
  }
}
