import type { WhatsAppStatus } from "@/lib/api"

export function isWhatsAppConnected(w: WhatsAppStatus): boolean {
  if (w.connected != null) return w.connected
  const state = w.connection_state as
    | { state?: string; instance?: { state?: string } }
    | undefined
  const name = state?.state ?? state?.instance?.state
  return name === "open"
}

export function logWhatsApp(level: "info" | "warn" | "error", message: string, data?: unknown) {
  const tag = "[WhatsApp]"
  if (level === "error") console.error(tag, message, data ?? "")
  else if (level === "warn") console.warn(tag, message, data ?? "")
  else console.log(tag, message, data ?? "")
}

export function applyWhatsAppStatus(
  w: WhatsAppStatus,
  setWaQr: (v: string | null) => void,
  setWaConnected: (v: boolean) => void,
) {
  const qr = w.qr_code
  if (qr) {
    setWaQr(qr.startsWith("data:") ? qr : `data:image/png;base64,${qr}`)
  }
  const connected = isWhatsAppConnected(w)
  setWaConnected(connected)
  if (connected) {
    setWaQr(null)
  }
}

export function resolveWhatsAppStatusMessage(w: WhatsAppStatus): string | null {
  const autoAction = (w as WhatsAppStatus & { auto_action?: string }).auto_action
  const connecting = autoAction === "connecting" || w.status === "connecting"

  if (isWhatsAppConnected(w)) return null
  if (w.status === "error") return w.detail ?? "WhatsApp connection error"
  if (connecting) {
    return w.detail ?? "Pairing in progress — keep WhatsApp open on your phone"
  }
  if (w.qr_code) return "QR code ready — scan with WhatsApp → Linked Devices"
  if (w.detail) return w.detail
  return null
}
