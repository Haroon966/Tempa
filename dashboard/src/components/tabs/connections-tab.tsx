import { useCallback, useEffect, useState } from "react"
import {
  HashIcon,
  BrainIcon,
  CalendarIcon,
  DatabaseIcon,
  MailIcon,
  MessageCircleIcon,
  RefreshCwIcon,
  ServerIcon,
  TicketIcon,
  VideoIcon,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"
import type { DashboardPayload } from "@/types/dashboard"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  disconnectGmail,
  disconnectGoogle,
  fetchGroqModels,
  fetchMeetConsent,
  fetchMeetReadiness,
  fetchWhatsAppStatus,
  grantMeetConsent,
  revokeMeetConsent,
  saveGoogleCredentials,
  saveGroqKey,
  connectJira,
  disconnectJira,
  startGmailOAuth,
  startGoogleOAuth,
  type WhatsAppStatus,
} from "@/lib/api"

function isWhatsAppConnected(w: WhatsAppStatus): boolean {
  if (w.connected != null) return w.connected
  const state = w.connection_state as
    | { state?: string; instance?: { state?: string } }
    | undefined
  const name = state?.state ?? state?.instance?.state
  return name === "open"
}

function logWhatsApp(level: "info" | "warn" | "error", message: string, data?: unknown) {
  const tag = "[WhatsApp]"
  if (level === "error") console.error(tag, message, data ?? "")
  else if (level === "warn") console.warn(tag, message, data ?? "")
  else console.log(tag, message, data ?? "")
}

function applyWhatsAppStatus(
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

function resolveWhatsAppStatusMessage(w: WhatsAppStatus): string | null {
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

export function ConnectionsTab({
  data,
  onRefresh,
}: {
  data: DashboardPayload
  onRefresh: () => void
}) {
  const groq     = data.connections.groq
  const google   = data.connections.google
  const gmail    = data.connections.gmail
  const whatsapp = data.connections.whatsapp
  const slack = data.connections.slack
  const jira = data.connections.jira
  const bridge = data.connections.whatsapp_bridge ?? data.connections.evolution_api
  const meetAutoJoin = data.connections.meet_auto_join

  const [groqKey, setGroqKey] = useState("")
  const [groqBusy, setGroqBusy] = useState(false)
  const [groqModels, setGroqModels] = useState<string[]>([])

  const [googleClientId, setGoogleClientId] = useState("")
  const [googleClientSecret, setGoogleClientSecret] = useState("")
  const [googleBusy, setGoogleBusy] = useState(false)

  const [gmailBusy, setGmailBusy] = useState(false)

  const [waQr, setWaQr] = useState<string | null>(null)
  const [waConnected, setWaConnected] = useState(!!whatsapp?.connected)
  const [waPairing, setWaPairing] = useState(false)
  const [waFailed, setWaFailed] = useState(false)
  const [waRefreshBusy, setWaRefreshBusy] = useState(false)
  const [waStatusMessage, setWaStatusMessage] = useState<string | null>(null)
  const [waLastLog, setWaLastLog] = useState("")

  const [consent, setConsent] = useState<boolean | null>(null)
  const [consentBusy, setConsentBusy] = useState(false)
  const [meetReadiness, setMeetReadiness] = useState<Awaited<
    ReturnType<typeof fetchMeetReadiness>
  > | null>(null)

  const [jiraBaseUrl, setJiraBaseUrl] = useState("")
  const [jiraEmail, setJiraEmail] = useState("")
  const [jiraToken, setJiraToken] = useState("")
  const [jiraProject, setJiraProject] = useState("")
  const [jiraBusy, setJiraBusy] = useState(false)

  const googleCredsConfigured =
    "credentials_configured" in google && google.credentials_configured === true

  const loadWhatsApp = useCallback(async () => {
    try {
      const w = await fetchWhatsAppStatus(true)
      applyWhatsAppStatus(w, setWaQr, setWaConnected)

      const payload = {
        status: w.status,
        connected: isWhatsAppConnected(w),
        hasQr: Boolean(w.qr_code),
        detail: w.detail,
        auto_action: (w as WhatsAppStatus & { auto_action?: string }).auto_action,
      }

      const autoAction = (w as WhatsAppStatus & { auto_action?: string }).auto_action
      const connecting = autoAction === "connecting" || w.status === "connecting"
      const isFetching = Boolean(
        w.detail?.includes("Fetching QR") ||
          w.detail?.includes("Waiting for QR") ||
          (connecting && !w.qr_code),
      )
      setWaPairing(!isWhatsAppConnected(w) && connecting)
      setWaStatusMessage(resolveWhatsAppStatusMessage(w))
      setWaFailed(
        !w.qr_code &&
          !isWhatsAppConnected(w) &&
          !connecting &&
          (w.status === "error" ||
            (w.status === "close" && Boolean(w.detail) && !isFetching)),
      )

      const logKey = `${w.status}|${Boolean(w.qr_code)}|${w.detail ?? ""}|${autoAction ?? ""}`
      if (w.status === "error") {
        logWhatsApp("error", w.detail ?? "WhatsApp connection error", payload)
      } else if (w.detail && w.detail !== "Generating QR — auto-refresh in progress") {
        logWhatsApp("info", w.detail, payload)
      } else if (w.qr_code && waLastLog !== logKey) {
        logWhatsApp("info", "QR code ready — scan with WhatsApp → Linked Devices")
      } else if (autoAction === "connecting") {
        logWhatsApp("info", "Pairing in progress — keep WhatsApp open on your phone")
      } else if (logKey !== waLastLog && autoAction === "restart") {
        logWhatsApp("warn", "Session reset — fetching new QR")
      }
      setWaLastLog(logKey)

      if (isWhatsAppConnected(w)) {
        logWhatsApp("info", "Connected — auto-replies active")
        onRefresh()
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load WhatsApp status"
      logWhatsApp("error", msg, e)
      setWaQr(null)
    }
  }, [onRefresh, waLastLog])

  async function handleRefreshQr() {
    if (waPairing && waQr) {
      toast.message("Pairing in progress — wait before refreshing QR")
      return
    }
    setWaRefreshBusy(true)
    setWaQr(null)
    setWaPairing(false)
    setWaStatusMessage("Refreshing QR code…")
    logWhatsApp("info", "Refreshing QR code…")
    try {
      const w = await fetchWhatsAppStatus(true, true)
      applyWhatsAppStatus(w, setWaQr, setWaConnected)
      setWaPairing(w.status === "connecting" && !isWhatsAppConnected(w))
      setWaStatusMessage(resolveWhatsAppStatusMessage(w))
      if (w.qr_code) {
        toast.success("QR code refreshed — scan with WhatsApp")
        logWhatsApp("info", "QR code refreshed")
      } else if (w.status === "error") {
        toast.error(w.detail ?? "Failed to refresh QR")
        logWhatsApp("error", w.detail ?? "Failed to refresh QR", w)
      } else {
        toast.message("Generating new QR…")
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to refresh QR"
      toast.error(msg)
      logWhatsApp("error", msg, e)
    } finally {
      setWaRefreshBusy(false)
    }
  }

  useEffect(() => { setWaConnected(!!whatsapp?.connected) }, [whatsapp?.connected])

  const loadMeetStatus = useCallback(async () => {
    try {
      const [consentRes, readiness] = await Promise.all([
        fetchMeetConsent(),
        fetchMeetReadiness(),
      ])
      setConsent(consentRes.consented)
      setMeetReadiness(readiness)
    } catch {
      setConsent(null)
      setMeetReadiness(null)
    }
  }, [])

  useEffect(() => {
    void loadMeetStatus()
  }, [loadMeetStatus])

  useEffect(() => {
    if (jira?.base_url) setJiraBaseUrl(String(jira.base_url))
    if (jira?.email) setJiraEmail(String(jira.email))
    if (jira?.default_project) setJiraProject(String(jira.default_project))
  }, [jira?.base_url, jira?.email, jira?.default_project])

  useEffect(() => {
    if (groq?.connected) {
      void fetchGroqModels()
        .then((m) => setGroqModels(m.categories ?? []))
        .catch(() => setGroqModels([]))
    }
  }, [groq?.connected])

  useEffect(() => {
    if (waConnected) return
    void loadWhatsApp()
    const id = setInterval(() => void loadWhatsApp(), 8000)
    return () => clearInterval(id)
  }, [waConnected, loadWhatsApp])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return
      const payload = event.data as { type?: string; status?: string; detail?: string }
      if (payload?.type !== "tempa-google-oauth") return
      if (payload.status === "success") { toast.success("Google Calendar connected"); onRefresh() }
      else if (payload.status === "error") toast.error(payload.detail ?? "Google connection failed")
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [onRefresh])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return
      const payload = event.data as { type?: string; status?: string; detail?: string }
      if (payload?.type !== "tempa-gmail-oauth") return
      if (payload.status === "success") { toast.success("Gmail connected"); onRefresh() }
      else if (payload.status === "error") toast.error(payload.detail ?? "Gmail connection failed")
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [onRefresh])

  async function handleSaveGroq() {
    if (!groqKey.trim()) { toast.error("Enter a Groq API key"); return }
    setGroqBusy(true)
    try {
      const result = await saveGroqKey(groqKey.trim())
      toast.success(`Groq connected (${result.model ?? "ok"})`)
      setGroqKey("")
      onRefresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Groq connection failed")
    } finally { setGroqBusy(false) }
  }

  async function handleSaveGoogleCreds() {
    if (!googleClientId.trim() || !googleClientSecret.trim()) {
      toast.error("Enter Google client ID and secret"); return
    }
    setGoogleBusy(true)
    try {
      await saveGoogleCredentials(googleClientId.trim(), googleClientSecret.trim())
      toast.success("Google OAuth credentials saved")
      setGoogleClientSecret("")
      onRefresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save credentials")
    } finally { setGoogleBusy(false) }
  }

  async function handleGoogleConnect() {
    setGoogleBusy(true)
    try {
      const result = await startGoogleOAuth()
      if (result.authorization_url) {
        const popup = window.open(result.authorization_url, "tempa-google-oauth", "width=520,height=720,menubar=no,toolbar=no")
        if (!popup) { toast.error("Allow popups to complete Google sign-in"); return }
        toast.message("Complete sign-in in the popup window")
      } else {
        toast.error(result.detail ?? "Could not start Google OAuth")
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Google OAuth failed")
    } finally { setGoogleBusy(false) }
  }

  async function handleGoogleDisconnect() {
    setGoogleBusy(true)
    try { await disconnectGoogle(); toast.success("Google Calendar disconnected"); onRefresh() }
    catch (e) { toast.error(e instanceof Error ? e.message : "Failed to disconnect Google") }
    finally { setGoogleBusy(false) }
  }

  async function handleGmailConnect() {
    setGmailBusy(true)
    try {
      const result = await startGmailOAuth()
      if (result.authorization_url) {
        const popup = window.open(result.authorization_url, "tempa-gmail-oauth", "width=520,height=720,menubar=no,toolbar=no")
        if (!popup) { toast.error("Allow popups to complete Gmail sign-in"); return }
        toast.message("Complete Gmail sign-in in the popup window")
      } else {
        toast.error(result.detail ?? "Could not start Gmail OAuth")
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Gmail OAuth failed")
    } finally { setGmailBusy(false) }
  }

  async function handleGmailDisconnect() {
    setGmailBusy(true)
    try { await disconnectGmail(); toast.success("Gmail disconnected"); onRefresh() }
    catch (e) { toast.error(e instanceof Error ? e.message : "Failed to disconnect Gmail") }
    finally { setGmailBusy(false) }
  }

  async function handleConsentGrant() {
    setConsentBusy(true)
    try {
      const r = await grantMeetConsent()
      setConsent(r.consented)
      await loadMeetStatus()
      onRefresh()
      toast.success("Recording consent granted")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to grant consent")
    } finally {
      setConsentBusy(false)
    }
  }

  async function handleConsentRevoke() {
    setConsentBusy(true)
    try {
      const r = await revokeMeetConsent()
      setConsent(r.consented)
      await loadMeetStatus()
      onRefresh()
      toast.message("Recording consent revoked")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to revoke consent")
    } finally {
      setConsentBusy(false)
    }
  }

  async function handleSaveJira() {
    if (!jiraBaseUrl.trim() || !jiraEmail.trim()) {
      toast.error("Enter Jira base URL and email")
      return
    }
    if (!jira?.connected && !jiraToken.trim()) {
      toast.error("Enter a Jira API token")
      return
    }
    setJiraBusy(true)
    try {
      const result = await connectJira({
        base_url: jiraBaseUrl.trim(),
        email: jiraEmail.trim(),
        api_token: jiraToken.trim() || undefined,
        default_project: jiraProject.trim(),
        enabled: true,
      })
      if (result.connected) {
        toast.success(`Jira connected${result.display_name ? ` (${result.display_name})` : ""}`)
        setJiraToken("")
        onRefresh()
      } else {
        toast.error(result.detail ?? "Jira connection failed")
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Jira connection failed")
    } finally {
      setJiraBusy(false)
    }
  }

  async function handleJiraDisconnect() {
    setJiraBusy(true)
    try {
      await disconnectJira()
      toast.success("Jira disconnected")
      setJiraToken("")
      onRefresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect Jira")
    } finally {
      setJiraBusy(false)
    }
  }

  const meetReady = meetReadiness?.ready ?? meetAutoJoin?.ready ?? false
  const meetAuth = meetReadiness?.meet_auth ?? meetAutoJoin?.meet_auth ?? false
  const meetDetail = meetReadiness?.detail ?? meetAutoJoin?.detail

  return (
    <div className="flex flex-col gap-8">
      {/* OAuth redirect URI notice */}
      <Alert className="border-border bg-muted">
        <AlertDescription className="text-sm text-muted-foreground">
          Google OAuth redirect URI must be{" "}
          <code>
            http://localhost:{data.connections.daemon?.port ?? 8787}/api/connections/google/callback
          </code>{" "}
          (used for Calendar and Gmail).
        </AlertDescription>
      </Alert>

      {/* Status strip */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <InfraCard title="Tempa Daemon" conn={data.connections.daemon} icon={ServerIcon} />
        <InfraCard title="Unified RAG"  conn={data.connections.rag}    icon={DatabaseIcon} />
        <InfraCard title="WhatsApp Bridge" conn={bridge}              icon={MessageCircleIcon} />
        <InfraCard title="Slack"          conn={slack}                icon={HashIcon} />
      </section>

      {/* Service cards */}
      <section className="grid gap-4 lg:grid-cols-2">
        {/* Groq */}
        <PanelCard
          title="Groq API"
          description="LLM, STT, and safety inference"
          icon={BrainIcon}
          action={<StatusBadge status={groq?.status ?? "disconnected"} />}
          contentClassName="flex flex-col gap-3"
        >
          {"detail" in (groq ?? {}) && typeof groq?.detail === "string" && groq.detail && (
            <p className="text-sm text-muted-foreground">{groq.detail}</p>
          )}
          {groqModels.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {groqModels.map((m) => (
                <Badge key={m} variant="outline" className="border-border bg-muted text-xs text-primary/70">
                  {m}
                </Badge>
              ))}
            </div>
          )}
          <Input
            type="password"
            placeholder="GROQ_API_KEY"
            value={groqKey}
            onChange={(e) => setGroqKey(e.target.value)}
            autoComplete="off"
            aria-label="Groq API key"
            className="focus:border-primary/40"
          />
          <Button className="cursor-pointer" onClick={() => void handleSaveGroq()} disabled={groqBusy}>
            {groqBusy ? "Testing…" : "Save & test"}
          </Button>
        </PanelCard>

        {/* Google Calendar */}
        <PanelCard
          title="Google Calendar"
          description="OAuth for calendar events and Meet links"
          icon={CalendarIcon}
          action={<StatusBadge status={google?.status ?? "disconnected"} />}
          contentClassName="flex flex-col gap-3"
        >
          {!googleCredsConfigured && (
            <>
              <Input
                placeholder="Google Client ID"
                value={googleClientId}
                onChange={(e) => setGoogleClientId(e.target.value)}
                autoComplete="off"
                aria-label="Google Client ID"
                className="focus:border-primary/40"
              />
              <Input
                type="password"
                placeholder="Google Client Secret"
                value={googleClientSecret}
                onChange={(e) => setGoogleClientSecret(e.target.value)}
                autoComplete="off"
                aria-label="Google Client Secret"
                className="focus:border-primary/40"
              />
              <Button variant="secondary" className="cursor-pointer" onClick={() => void handleSaveGoogleCreds()} disabled={googleBusy}>
                Save OAuth credentials
              </Button>
            </>
          )}
          {googleCredsConfigured && (
            <p className="text-sm text-muted-foreground">OAuth app credentials configured.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button className="cursor-pointer" onClick={() => void handleGoogleConnect()} disabled={googleBusy || !googleCredsConfigured}>
              {google?.connected ? "Reconnect Google" : "Connect with Google"}
            </Button>
            {google?.connected && (
              <Button variant="outline" className="cursor-pointer" onClick={() => void handleGoogleDisconnect()} disabled={googleBusy}>
                Disconnect
              </Button>
            )}
          </div>
        </PanelCard>

        {/* Gmail */}
        <PanelCard
          title="Gmail"
          description="Read, search, and send email on demand"
          icon={MailIcon}
          action={<StatusBadge status={gmail?.status ?? "disconnected"} />}
          contentClassName="flex flex-col gap-3"
        >
          {!googleCredsConfigured && (
            <p className="text-sm text-muted-foreground">
              Save Google OAuth credentials in the Calendar panel first.
            </p>
          )}
          {"email_address" in (gmail ?? {}) && typeof gmail?.email_address === "string" && gmail.email_address && (
            <p className="text-sm text-muted-foreground">Account: <span className="text-foreground">{gmail.email_address}</span></p>
          )}
          {"detail" in (gmail ?? {}) && typeof gmail?.detail === "string" && gmail.detail && (
            <p className="text-sm text-muted-foreground">{gmail.detail}</p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button className="cursor-pointer" onClick={() => void handleGmailConnect()} disabled={gmailBusy || !googleCredsConfigured}>
              {gmail?.connected ? "Reconnect Gmail" : "Connect Gmail"}
            </Button>
            {gmail?.connected && (
              <Button variant="outline" className="cursor-pointer" onClick={() => void handleGmailDisconnect()} disabled={gmailBusy}>
                Disconnect
              </Button>
            )}
          </div>
        </PanelCard>

        {/* WhatsApp — auto-connect, QR only */}
        <PanelCard
          title="WhatsApp"
          description="Personal WhatsApp — scan QR in your phone app: Settings → Linked devices → Link a device"
          icon={MessageCircleIcon}
          action={<StatusBadge status={waConnected ? "connected" : (whatsapp?.status ?? "disconnected")} />}
          contentClassName="flex flex-col items-center justify-center gap-4 py-2"
        >
          {!waConnected && waStatusMessage && (
            <Alert
              className={cn(
                "w-full border-green-200 bg-green-50 text-green-900",
                waFailed && "border-amber-200 bg-amber-50 text-amber-900",
                whatsapp?.status === "error" && "border-destructive/30 bg-destructive/5 text-destructive",
              )}
            >
              <AlertDescription className="text-center text-sm font-medium">
                {waStatusMessage}
              </AlertDescription>
            </Alert>
          )}
          {waQr ? (
            <img
              src={waQr}
              alt="WhatsApp QR code for device linking"
              className="h-64 w-64 rounded-2xl border border-white/10 bg-white p-3 shadow-lg"
            />
          ) : (
            <div className="flex h-64 w-64 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-muted/30">
              {waConnected ? (
                <>
                  <span className="size-4 rounded-full bg-green-400 shadow-[0_0_12px_rgba(34,197,94,0.9)]" />
                  <span className="text-base font-medium text-green-500">Connected</span>
                </>
              ) : waRefreshBusy ? (
                <>
                  <div className="size-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                  <span className="text-sm text-muted-foreground">Refreshing QR…</span>
                </>
              ) : waPairing ? (
                <>
                  <div className="size-8 animate-spin rounded-full border-2 border-green-400/30 border-t-green-400" />
                  <span className="text-sm text-green-500">Pairing…</span>
                  <span className="text-xs text-muted-foreground">Keep WhatsApp open on your phone</span>
                </>
              ) : waFailed ? (
                <>
                  <span className="text-sm font-medium text-amber-500">QR not available</span>
                  <span className="max-w-[220px] text-center text-xs text-muted-foreground">
                    Remove old linked devices on your phone, then click Refresh QR
                  </span>
                </>
              ) : (
                <>
                  <div className="size-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                  <span className="text-sm text-muted-foreground">Generating QR…</span>
                </>
              )}
            </div>
          )}
          {!waConnected && (
            <Button
              variant="outline"
              size="sm"
              className="cursor-pointer"
              onClick={() => void handleRefreshQr()}
              disabled={waRefreshBusy || waPairing}
            >
              <RefreshCwIcon className={cn("size-3.5", waRefreshBusy && "animate-spin")} />
              Refresh QR
            </Button>
          )}
        </PanelCard>

        {/* Slack */}
        <PanelCard
          title="Slack"
          description="Socket Mode — DM the bot or @mention in channels (tokens in .env)"
          icon={HashIcon}
          action={
            <StatusBadge
              status={
                slack?.connected
                  ? "connected"
                  : slack?.configured
                    ? "degraded"
                    : (slack?.status ?? "disconnected")
              }
            />
          }
          contentClassName="flex flex-col gap-3"
        >
          <p className="text-sm text-muted-foreground">
            Configured:{" "}
            <span className="font-semibold text-foreground">
              {slack?.configured ? "yes" : "no"}
            </span>
          </p>
          <p className="text-sm text-muted-foreground">
            Socket Mode:{" "}
            <span className="font-semibold text-foreground">
              {slack?.connected ? "connected" : "not connected"}
            </span>
          </p>
          <p className="text-sm text-muted-foreground">
            Owner user ID:{" "}
            <span className="font-semibold text-foreground">
              {slack?.owner_configured
                ? (slack?.owner_user_id ?? "set")
                : "not set (SLACK_OWNER_USER_ID)"}
            </span>
          </p>
          {slack?.detail && (
            <p className="text-sm text-muted-foreground">{slack.detail}</p>
          )}
          <p className="text-xs text-muted-foreground">
            Create a Slack app at{" "}
            <a
              href="https://api.slack.com/apps"
              target="_blank"
              rel="noreferrer"
              className="text-primary underline-offset-2 hover:underline"
            >
              api.slack.com
            </a>
            , enable Socket Mode, subscribe to <code>message.im</code> and{" "}
            <code>app_mention</code>, then set <code>SLACK_BOT_TOKEN</code> and{" "}
            <code>SLACK_APP_TOKEN</code> in <code>.env</code> and restart the daemon.
          </p>
        </PanelCard>

        {/* Jira */}
        <PanelCard
          title="Jira"
          description="Jira Cloud — issue search, sync, and approved writes"
          icon={TicketIcon}
          action={
            <StatusBadge
              status={
                jira?.connected
                  ? "connected"
                  : jira?.configured
                    ? "degraded"
                    : (jira?.status ?? "disconnected")
              }
            />
          }
          contentClassName="flex flex-col gap-3"
        >
          {"detail" in (jira ?? {}) && typeof jira?.detail === "string" && jira.detail && (
            <p className="text-sm text-muted-foreground">{jira.detail}</p>
          )}
          <Input
            placeholder="https://yourorg.atlassian.net"
            value={jiraBaseUrl}
            onChange={(e) => setJiraBaseUrl(e.target.value)}
            autoComplete="off"
            aria-label="Jira base URL"
            className="focus:border-primary/40"
          />
          <Input
            placeholder="you@company.com"
            value={jiraEmail}
            onChange={(e) => setJiraEmail(e.target.value)}
            autoComplete="off"
            aria-label="Jira email"
            className="focus:border-primary/40"
          />
          <Input
            type="password"
            placeholder={jira?.connected ? "API token (leave blank to keep)" : "JIRA API token"}
            value={jiraToken}
            onChange={(e) => setJiraToken(e.target.value)}
            autoComplete="off"
            aria-label="Jira API token"
            className="focus:border-primary/40"
          />
          <Input
            placeholder="Default project key (e.g. ENG)"
            value={jiraProject}
            onChange={(e) => setJiraProject(e.target.value)}
            autoComplete="off"
            aria-label="Jira default project"
            className="focus:border-primary/40"
          />
          <div className="flex flex-wrap gap-2">
            <Button className="cursor-pointer" onClick={() => void handleSaveJira()} disabled={jiraBusy}>
              {jiraBusy ? "Testing…" : "Save & test"}
            </Button>
            {jira?.connected && (
              <Button
                variant="outline"
                className="cursor-pointer"
                onClick={() => void handleJiraDisconnect()}
                disabled={jiraBusy}
              >
                Disconnect
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Create an API token at Atlassian account settings → Security → API tokens. Enable polling
            in <code>config/varys.yaml</code> with <code>jira_enabled: true</code> and{" "}
            <code>jira_projects</code>.
          </p>
        </PanelCard>

        {/* Google Meet bot */}
        <PanelCard
          title="Google Meet bot"
          description="Recording consent required before auto-join"
          icon={VideoIcon}
          action={
            <StatusBadge
              status={
                meetReady
                  ? "connected"
                  : consent
                    ? "degraded"
                    : "disconnected"
              }
            />
          }
          contentClassName="flex flex-col gap-3"
        >
          <p className="text-sm text-muted-foreground">
            Auto-join ready:{" "}
            <span className="font-semibold text-foreground">
              {meetReady ? "yes" : "no"}
            </span>
            {meetDetail && !meetReady && (
              <span className="mt-1 block text-xs">{meetDetail}</span>
            )}
          </p>
          <p className="text-sm text-muted-foreground">
            Consent:{" "}
            <span className="font-semibold text-foreground">
              {consent === null ? "unknown" : consent ? "granted" : "not granted"}
            </span>
          </p>
          <p className="text-sm text-muted-foreground">
            Browser auth:{" "}
            <span className="font-semibold text-foreground">
              {meetAuth ? "configured" : "missing"}
            </span>
          </p>
          {!meetAuth && (
            <p className="text-xs text-muted-foreground">
              After connecting Google, run <code>tempa meet-auth</code> once to enable Meet browser
              login (Playwright).
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button className="cursor-pointer" onClick={() => void handleConsentGrant()} disabled={consentBusy || consent === true}>
              Grant consent
            </Button>
            <Button variant="outline" className="cursor-pointer" onClick={() => void handleConsentRevoke()} disabled={consentBusy || consent !== true}>
              Revoke
            </Button>
          </div>
        </PanelCard>
      </section>
    </div>
  )
}

function InfraCard({
  title,
  conn,
  icon: Icon,
}: {
  title: string
  conn: DashboardPayload["connections"][string] | undefined
  icon: LucideIcon
}) {
  if (!conn) return null
  const connected = "connected" in conn ? conn.connected : "reachable" in conn ? conn.reachable : false
  const status = conn.status ?? (connected ? "connected" : "disconnected")
  const isGood = status === "connected" || status === "healthy"

  return (
    <div className={`rounded-xl border p-4 transition-all duration-200 ${isGood ? "border-green-200 bg-green-50" : "border-border bg-muted/30"}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className={`flex size-8 items-center justify-center rounded-lg border ${isGood ? "border-green-300 bg-green-100 text-green-700" : "border-border bg-card text-muted-foreground"}`}>
            <Icon className="size-4" aria-hidden />
          </div>
          <span className="text-sm font-medium text-foreground">{title}</span>
        </div>
        <StatusBadge status={status} />
      </div>
      {"detail" in conn && typeof conn.detail === "string" && conn.detail && (
        <p className="mt-2 text-xs text-muted-foreground">{conn.detail}</p>
      )}
      {"chunks" in conn && conn.chunks !== undefined && (
        <p className="mt-2 text-xs text-muted-foreground">Chunks: {conn.chunks}</p>
      )}
      {"port" in conn && typeof conn.port === "number" && (
        <p className="mt-2 text-xs text-muted-foreground">Port: {conn.port}</p>
      )}
    </div>
  )
}
