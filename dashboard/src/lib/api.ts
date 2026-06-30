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

export interface SlackStatus {
  connected?: boolean
  configured?: boolean
  owner_configured?: boolean
  status?: string
  detail?: string | null
  last_event_at?: string | null
  owner_user_id?: string | null
}

export async function fetchSlackStatus() {
  return request<SlackStatus>("/api/connections/slack")
}

export interface JiraStatus {
  connected?: boolean
  configured?: boolean
  status?: string
  detail?: string
  base_url?: string
  email?: string
  default_project?: string
  display_name?: string
  enabled?: boolean
}

export async function fetchJiraStatus() {
  return request<JiraStatus>("/api/connections/jira")
}

export async function connectJira(body: {
  base_url: string
  email: string
  api_token?: string
  default_project?: string
  enabled?: boolean
}) {
  return request<{ status: string; connected: boolean; detail?: string; display_name?: string }>(
    "/api/connections/jira",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  )
}

export async function disconnectJira() {
  return request<{ status: string; connected: boolean }>("/api/connections/jira", {
    method: "DELETE",
  })
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

export interface ActiveMeetingLive {
  meeting_id: string
  title?: string
  meet_url?: string
  status?: string
  transcript_tail?: string
  live_notes?: string
  suggestions?: Array<{ id: string; text: string; rationale?: string }>
}

export async function fetchActiveMeetings() {
  return request<{ active: ActiveMeetingLive[]; sessions: unknown[] }>("/api/meetings/active")
}

export async function fetchMeetingDetail(meetingId: string) {
  return request<{
    meeting: import("@/types/dashboard").MeetingRecord
    transcript_raw?: string
    pending_followups?: PendingAction[]
    error?: string
  }>(`/api/meetings/${meetingId}`)
}

export async function sendMeetingChat(meetingId: string, text: string) {
  return request<{ status: string }>(`/api/meetings/${meetingId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
}

export async function fetchMeetReadiness() {
  return request<{
    ready: boolean
    consent: boolean
    meet_auth: boolean
    google_connected: boolean
    detail: string
  }>("/api/meetings/readiness")
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

export async function updatePendingAction(id: string, payload: Record<string, unknown>) {
  return request<PendingAction>(`/api/pending-actions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload }),
  })
}

export async function cancelChatRun(runId: string) {
  return request<{ status: string; run_id: string }>(`/api/chat/runs/${runId}/cancel`, {
    method: "POST",
  })
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
  return request<{ status: string; count?: number; identity_link_count?: number }>(
    "/api/contacts/sync",
    { method: "POST" },
  )
}

export async function syncAll(maxEmails = 500) {
  return request<{
    status: string
    jira_users?: { status: string; user_count?: number }
    identity_link_count?: number
  }>(`/api/sync/all?max_emails=${maxEmails}`, { method: "POST" })
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
  paused?: boolean
  pending_actions?: PendingActionPreview[]
  artifacts?: ChatArtifact[]
}

export interface PendingActionPreview {
  id: string
  type: string
  preview?: string
}

export interface ChatArtifact {
  type: string
  [key: string]: unknown
}

export interface StepEvent {
  subtask_id: string
  agent: string
  status: "start" | "done" | "error"
  detail?: string
  duration_ms?: number
  timestamp: string
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
  run_id?: string | null
}

export type ChatStreamEvent =
  | { type: "run_started"; run_id: string; session_id: string }
  | { type: "token"; delta: string }
  | { type: "activity"; event: { agent: string; action: string; detail: string; timestamp: string } }
  | {
      type: "step"
      step: StepEvent
    }
  | {
      type: "message"
      content: string
      sources: ChatSource[]
      paused: boolean
      session_id: string | null
      pending_actions: PendingActionPreview[]
      artifacts: ChatArtifact[]
      run_id: string | null
    }
  | { type: "error"; error: string; code?: string; recoverable?: boolean }
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
  let sawDone = false

  const classifyEvent = (
    eventType: string,
    data: Record<string, unknown>,
  ): ChatStreamEvent | null => {
    let kind = eventType
    if (!kind) {
      if ("delta" in data) kind = "token"
      else if ("agent" in data && "action" in data) kind = "activity"
      else if ("error" in data) kind = "error"
      else if ("content" in data || "session_id" in data || "sources" in data || "paused" in data) {
        kind = "message"
      } else if ("run_id" in data && "session_id" in data) {
        kind = "run_started"
      } else if ("subtask_id" in data && "status" in data) {
        kind = "step"
      } else if (Object.keys(data).length === 0) kind = "done"
    }

    if (kind === "token") {
      return { type: "token", delta: String(data.delta ?? "") }
    }
    if (kind === "run_started") {
      return {
        type: "run_started",
        run_id: String(data.run_id ?? ""),
        session_id: String(data.session_id ?? ""),
      }
    }
    if (kind === "step") {
      return {
        type: "step",
        step: data as unknown as StepEvent,
      }
    }
    if (kind === "activity") {
      return {
        type: "activity",
        event: data as { agent: string; action: string; detail: string; timestamp: string },
      }
    }
    if (kind === "message") {
      return {
        type: "message",
        content: String(data.content ?? ""),
        sources: (data.sources as ChatSource[]) ?? [],
        paused: Boolean(data.paused),
        session_id: (data.session_id as string) ?? null,
        pending_actions: (data.pending_actions as PendingActionPreview[]) ?? [],
        artifacts: (data.artifacts as ChatArtifact[]) ?? [],
        run_id: (data.run_id as string) ?? null,
      }
    }
    if (kind === "error") {
      return {
        type: "error",
        error: String(data.error ?? "Unknown error"),
        code: data.code ? String(data.code) : undefined,
        recoverable: data.recoverable !== false,
      }
    }
    if (kind === "done") {
      return { type: "done" }
    }
    return null
  }

  const parsePart = (part: string): ChatStreamEvent | null => {
    const normalized = part.replace(/\r\n/g, "\n").trim()
    if (!normalized) return null

    let eventType = ""
    const dataLines: string[] = []
    for (const line of normalized.split("\n")) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim()
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
    const dataStr = dataLines.join("\n")
    if (!dataStr) return null

    try {
      const data = JSON.parse(dataStr) as Record<string, unknown>
      return classifyEvent(eventType, data)
    } catch {
      return null
    }
  }

  const flush = function* (final = false) {
    buffer = buffer.replace(/\r\n/g, "\n")
    const parts = buffer.split("\n\n")
    buffer = final ? "" : (parts.pop() ?? "")
    for (const part of parts) {
      const event = parsePart(part)
      if (!event) continue
      if (event.type === "done") sawDone = true
      yield event
    }
    if (final && buffer.trim()) {
      const event = parsePart(buffer)
      if (event) {
        if (event.type === "done") sawDone = true
        yield event
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    yield* flush()
  }
  buffer += decoder.decode()
  yield* flush(true)
  if (!sawDone) {
    yield { type: "done" }
  }
}

export interface QaRepoEntry {
  repo: string
  source: "env" | "config" | "dashboard" | "github_app"
  removable: boolean
}

export interface QaSummary {
  enabled: boolean
  configured: boolean
  groq_configured?: boolean
  github_configured?: boolean
  github_auth_mode?: "pat" | "app" | null
  qa_engine?: string
  repos_monitored?: number
  branches_scanned?: number
  failing_branches?: number
  open_findings?: number
  critical_findings?: number
  queue_depth?: number
  last_scan_at?: string | null
}

export interface QaBranchStatus {
  repo: string
  branch: string
  commit_sha?: string
  ci_status?: string
  lint_status?: string
  test_status?: string
  security_count?: number
  finding_count?: number
  grade?: string
  last_scan_at?: string
}

export interface QaFinding {
  id: string
  repo: string
  branch: string
  commit_sha?: string
  category: string
  severity: string
  title: string
  body?: string
  suggestion?: string
  file?: string
  line?: number
  status?: string
  github_comment_url?: string | null
  pr_number?: number | null
  created_at?: string
}

export interface QaJob {
  id: string
  repo: string
  branch?: string | null
  job_type?: string
  status: string
  enqueued_at?: string
  error?: string
}

export async function fetchQaRepos() {
  return request<{ repos: QaRepoEntry[] }>("/api/qa/repos")
}

export async function postQaRepo(repo: string) {
  return request<{ status: string; repo: { repo: string } }>("/api/qa/repos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo }),
  })
}

export async function deleteQaRepo(repo: string) {
  return request<{ status: string; repo: string }>(`/api/qa/repos/${encodeURIComponent(repo)}`, {
    method: "DELETE",
  })
}

export async function fetchQaSummary() {
  return request<QaSummary>("/api/qa/summary")
}

export async function fetchQaBranches(repo?: string) {
  const qs = repo ? `?repo=${encodeURIComponent(repo)}` : ""
  return request<{ branches: QaBranchStatus[] }>(`/api/qa/branches${qs}`)
}

export async function fetchQaFindings() {
  return request<{ findings: QaFinding[] }>("/api/qa/findings")
}

export async function fetchQaJobs() {
  return request<{ jobs: QaJob[] }>("/api/qa/jobs")
}

export async function postQaScan(repo: string, branch?: string, prNumber?: number) {
  return request<{ status: string; job_id?: string; action_id?: string; message?: string }>("/api/qa/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, branch: branch ?? null, pr_number: prNumber ?? null }),
  })
}

export async function postQaComment(findingId: string) {
  return request<{ status: string; url?: string }>(`/api/qa/findings/${findingId}/comment`, {
    method: "POST",
  })
}

export async function postQaFix(findingId: string) {
  return request<{ status: string; action_id: string }>(`/api/qa/findings/${findingId}/fix`, {
    method: "POST",
  })
}

export interface QaAgentPlaybook {
  target: "claude" | "cursor"
  finding_id: string
  api_base: string
  project_root: string
  prompt: string
  launch_hint: string
  terminal_command: string | null
  curl_commands: Record<string, string>
}

export async function fetchQaAgentPlaybook(findingId: string, target: "claude" | "cursor") {
  return request<QaAgentPlaybook>(
    `/api/qa/findings/${findingId}/agent-playbook?target=${encodeURIComponent(target)}`,
  )
}

export async function fetchOrchestrator() {
  return request<import("@/types/dashboard").OrchestratorManifest>("/api/orchestrator")
}
