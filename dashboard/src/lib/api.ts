const API_BASE = import.meta.env.VITE_TEMPA_API ?? ""

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  const ct = res.headers.get("content-type") ?? ""
  if (ct.includes("application/json")) return res.json() as Promise<T>
  return (await res.text()) as T
}

export async function saveGroqKey(apiKey: string) {
  return request<{ status: string; model?: string; reply?: string }>("/api/connections/groq", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  })
}

export async function saveGoogleCredentials(clientId: string, clientSecret: string) {
  return request<{ status: string; credentials_configured: boolean }>(
    "/api/connections/google/credentials",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
    },
  )
}

export async function startGoogleOAuth() {
  return request<{ authorization_url?: string; status?: string; detail?: string }>(
    "/api/connections/google",
    { method: "POST" },
  )
}

export async function disconnectGoogle() {
  return request<{ status: string; connected: boolean }>("/api/connections/google", {
    method: "DELETE",
  })
}

export async function startGmailOAuth() {
  return request<{ authorization_url?: string; status?: string; detail?: string }>(
    "/api/connections/gmail",
    { method: "POST" },
  )
}

export async function disconnectGmail() {
  return request<{ status: string; connected: boolean }>("/api/connections/gmail", {
    method: "DELETE",
  })
}

export interface WhatsAppStatus {
  qr_code?: string | null
  pairing_code?: string | null
  connection_state?: unknown
  connected?: boolean
  needs_qr_rescan?: boolean
  status?: string
  detail?: string
}

export async function fetchWhatsAppStatus(includeQr = false, refresh = false) {
  const params = new URLSearchParams()
  if (includeQr) params.set("qr", "1")
  if (refresh) params.set("refresh", "1")
  const qs = params.toString()
  return request<WhatsAppStatus>(`/api/connections/whatsapp${qs ? `?${qs}` : ""}`)
}

export async function connectWhatsApp() {
  return request<WhatsAppStatus>("/api/connections/whatsapp/connect", { method: "POST" })
}

export async function disconnectWhatsApp() {
  return request<WhatsAppStatus>("/api/connections/whatsapp", { method: "DELETE" })
}

export async function restartWhatsApp() {
  return request<WhatsAppStatus>("/api/connections/whatsapp/restart", { method: "POST" })
}

export interface WhatsAppAllowedNumbers {
  primary_number?: string | null
  additional_numbers: string[]
  allowed_numbers: string[]
}

export async function fetchWhatsAppAllowedNumbers() {
  return request<WhatsAppAllowedNumbers>("/api/connections/whatsapp/allowed-numbers")
}

export async function saveWhatsAppAllowedNumbers(additionalNumbers: string[]) {
  return request<WhatsAppAllowedNumbers>("/api/connections/whatsapp/allowed-numbers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ additional_numbers: additionalNumbers }),
  })
}

export async function fetchMeetConsent() {
  return request<{ consented: boolean }>("/api/meetings/consent")
}

export async function grantMeetConsent() {
  return request<{ consented: boolean }>("/api/meetings/consent", { method: "POST" })
}

export async function revokeMeetConsent() {
  return request<{ consented: boolean }>("/api/meetings/consent", { method: "DELETE" })
}

export async function fetchGroqModels() {
  return request<{ chains: Record<string, string[]>; categories: string[] }>(
    "/api/connections/groq/models",
  )
}

export interface PendingAction {
  id: string
  type: string
  payload: Record<string, unknown>
  status: string
  title?: string
  created_at?: string
  expires_at?: string
  risk_level?: string
}

export async function fetchPendingActions(status = "pending") {
  return request<{ actions: PendingAction[] }>(`/api/pending-actions?status=${status}`)
}

export async function approvePendingAction(id: string) {
  return request<{ status: string; result?: unknown }>(`/api/pending-actions/${id}/approve`, {
    method: "POST",
  })
}

export async function rejectPendingAction(id: string) {
  return request<PendingAction>(`/api/pending-actions/${id}/reject`, { method: "POST" })
}

export async function fetchTasks() {
  return request<{ active: unknown[]; recent: unknown[]; meet_jobs: unknown[] }>("/api/tasks")
}

export async function fetchNotifications(limit = 30) {
  return request<{ notifications: unknown[] }>(`/api/notifications?limit=${limit}`)
}

export async function fetchGmailMessages(limit = 20) {
  return request<{ messages: GmailMessage[]; last_sync_at?: string }>(
    `/api/gmail/messages?limit=${limit}`,
  )
}

export async function syncGmail() {
  return request<{ status: string }>("/api/gmail/sync", { method: "POST" })
}

export interface GmailMessage {
  id: string
  subject: string
  from: string
  date: string
  snippet: string
  unread: boolean
}

export async function fetchContacts(q = "") {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ""
  return request<{ contacts: Contact[]; total: number }>(`/api/contacts${qs}`)
}

export async function syncContacts() {
  return request<{ status: string; count?: number }>("/api/contacts/sync", { method: "POST" })
}

export interface Contact {
  id: string
  name: string
  email: string
  phone: string
  source: string
}

// ── Chat sessions ──────────────────────────────────────────────────────────

export interface ChatSource {
  label?: string
  tool?: string
  content?: string
  [key: string]: unknown
}

export interface ChatMessageRecord {
  id: string
  role: "user" | "assistant"
  content: string
  sources: ChatSource[]
  created_at: string
}

export interface ChatSessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ChatSession extends ChatSessionSummary {
  messages: ChatMessageRecord[]
}

export async function fetchChatSessions() {
  return request<{ sessions: ChatSessionSummary[] }>("/api/chat/sessions")
}

export async function createChatSession(title = "") {
  return request<ChatSession>("/api/chat/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
}

export async function fetchChatSession(id: string) {
  return request<ChatSession>(`/api/chat/sessions/${id}`)
}

export async function deleteChatSession(id: string) {
  return request<{ status: string; id: string }>(`/api/chat/sessions/${id}`, {
    method: "DELETE",
  })
}

export interface ChatStreamRequest {
  message: string
  session_id?: string | null
  context?: Record<string, unknown>
}

export type ChatStreamEvent =
  | { type: "token"; delta: string }
  | { type: "activity"; event: { agent: string; action: string; detail: string; timestamp: string } }
  | { type: "message"; content: string; sources: ChatSource[]; paused: boolean; session_id: string | null }
  | { type: "error"; error: string }
  | { type: "done" }

export async function* streamChat(
  body: ChatStreamRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  if (!res.body) {
    throw new Error("No response body")
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split("\n\n")
    buffer = parts.pop() ?? ""

    for (const part of parts) {
      if (!part.trim()) continue
      let eventType = "message"
      let dataStr = ""
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) {
          eventType = line.slice(6).trim()
        } else if (line.startsWith("data:")) {
          dataStr = line.slice(5).trim()
        }
      }
      if (!dataStr) continue
      try {
        const data = JSON.parse(dataStr) as Record<string, unknown>
        if (eventType === "token") {
          yield { type: "token", delta: String(data.delta ?? "") }
        } else if (eventType === "activity") {
          yield {
            type: "activity",
            event: data as { agent: string; action: string; detail: string; timestamp: string },
          }
        } else if (eventType === "message") {
          yield {
            type: "message",
            content: String(data.content ?? ""),
            sources: (data.sources as ChatSource[]) ?? [],
            paused: Boolean(data.paused),
            session_id: (data.session_id as string) ?? null,
          }
        } else if (eventType === "error") {
          yield { type: "error", error: String(data.error ?? "Unknown error") }
        } else if (eventType === "done") {
          yield { type: "done" }
        }
      } catch {
        /* ignore malformed chunks */
      }
    }
  }
  yield { type: "done" }
}
