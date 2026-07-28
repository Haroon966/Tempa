import { useCallback, useEffect, useState } from "react"
import {
  HashIcon,
  CalendarIcon,
  MailIcon,
  MessageCircleIcon,
  RefreshCwIcon,
  TicketIcon,
  UploadCloudIcon,
  ServerIcon,
  VideoIcon,
} from "lucide-react"
import { toast } from "sonner"
import type { DashboardPayload } from "@/types/dashboard"
import { PageHeader } from "@/components/dashboard/page-header"
import { PanelCard } from "@/components/dashboard/panel-card"
import { InfraStrip } from "@/components/settings/infra-strip"
import { GroqSection } from "@/components/settings/groq-section"
import {
  applyWhatsAppStatus,
  isWhatsAppConnected,
  logWhatsApp,
  resolveWhatsAppStatusMessage,
} from "@/components/settings/helpers"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription } from "@/components/ui/alert"
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
  connectCoolify,
  disconnectCoolify,
  syncAll,
  startGmailOAuth,
  startGoogleOAuth,
  fetchYoutubeStatus,
  runYoutubeBackfill,
  type WhatsAppStatus,
  type YoutubeUploadStatus,
} from "@/lib/api"

export function SettingsTab({
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
  const coolify = data.connections.coolify
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
  const [identitySyncBusy, setIdentitySyncBusy] = useState(false)

  const [coolifyBaseUrl, setCoolifyBaseUrl] = useState("http://host.docker.internal:8000")
  const [coolifyToken, setCoolifyToken] = useState("")
  const [coolifyServerUuid, setCoolifyServerUuid] = useState("")
  const [coolifyProjectUuid, setCoolifyProjectUuid] = useState("")
  const [coolifyGithubAppUuid, setCoolifyGithubAppUuid] = useState("")
  const [coolifyBusy, setCoolifyBusy] = useState(false)

  const [youtube, setYoutube] = useState<YoutubeUploadStatus | null>(null)
  const [youtubeBusy, setYoutubeBusy] = useState(false)

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

  const loadYoutube = useCallback(async () => {
    try {
      setYoutube(await fetchYoutubeStatus())
    } catch {
      setYoutube(null)
    }
  }, [])

  useEffect(() => {
    void loadYoutube()
  }, [loadYoutube])

  async function handleYoutubeBackfill() {
    setYoutubeBusy(true)
    try {
      const r = await runYoutubeBackfill()
      if (r.status === "disabled") {
        toast.error("Enable MEET_YOUTUBE_UPLOAD_ENABLED first")
      } else if (r.status === "no_credentials") {
        toast.error("Reconnect Google to grant YouTube upload access")
      } else {
        toast.success(
          `Uploaded ${r.uploaded}, already on YouTube ${r.already}, failed ${r.failed} of ${r.total}`,
        )
      }
      await loadYoutube()
      onRefresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "YouTube backfill failed")
    } finally {
      setYoutubeBusy(false)
    }
  }

  useEffect(() => {
    if (jira?.base_url) setJiraBaseUrl(String(jira.base_url))
    if (jira?.email) setJiraEmail(String(jira.email))
    if (jira?.default_project) setJiraProject(String(jira.default_project))
  }, [jira?.base_url, jira?.email, jira?.default_project])

  useEffect(() => {
    if (coolify?.base_url) setCoolifyBaseUrl(String(coolify.base_url))
    if (coolify?.server_uuid) setCoolifyServerUuid(String(coolify.server_uuid))
    if (coolify?.project_uuid) setCoolifyProjectUuid(String(coolify.project_uuid))
    if (coolify?.github_app_uuid) setCoolifyGithubAppUuid(String(coolify.github_app_uuid))
  }, [
    coolify?.base_url,
    coolify?.server_uuid,
    coolify?.project_uuid,
    coolify?.github_app_uuid,
  ])

  useEffect(() => {
    if (groq?.connected) {
      void fetchGroqModels()
        .then((m) => setGroqModels(m.categories ?? []))
        .catch(() => setGroqModels([]))
    }
  }, [groq?.connected])

  useEffect(() => {
    if (waConnected) return
    const tick = () => {
      if (document.visibilityState === "hidden") return
      void loadWhatsApp()
    }
    void loadWhatsApp()
    const id = setInterval(tick, 8000)
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

  async function handleSaveCoolify() {
    if (!coolifyBaseUrl.trim()) {
      toast.error("Enter Coolify base URL")
      return
    }
    if (!coolify?.connected && !coolifyToken.trim()) {
      toast.error("Enter a Coolify API token")
      return
    }
    setCoolifyBusy(true)
    try {
      const result = await connectCoolify({
        base_url: coolifyBaseUrl.trim(),
        api_token: coolifyToken.trim() || undefined,
        server_uuid: coolifyServerUuid.trim(),
        project_uuid: coolifyProjectUuid.trim(),
        github_app_uuid: coolifyGithubAppUuid.trim(),
        enabled: true,
      })
      if (result.connected) {
        toast.success(`Coolify connected${result.version ? ` (${result.version})` : ""}`)
        setCoolifyToken("")
        onRefresh()
      } else {
        toast.error(result.detail ?? "Coolify connection failed")
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Coolify connection failed")
    } finally {
      setCoolifyBusy(false)
    }
  }

  async function handleCoolifyDisconnect() {
    setCoolifyBusy(true)
    try {
      await disconnectCoolify()
      toast.success("Coolify disconnected")
      setCoolifyToken("")
      onRefresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect Coolify")
    } finally {
      setCoolifyBusy(false)
    }
  }

  async function handleIdentitySync() {
    setIdentitySyncBusy(true)
    try {
      const result = await syncAll()
      const links = result.identity_link_count ?? 0
      const users = result.jira_users?.user_count
      toast.success(
        users != null
          ? `Identity directory synced — ${users} Jira users, ${links} linked emails`
          : `Identity directory synced — ${links} linked emails`,
      )
      onRefresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Identity sync failed")
    } finally {
      setIdentitySyncBusy(false)
    }
  }

  const meetReady = meetReadiness?.ready ?? meetAutoJoin?.ready ?? false
  const meetAuth = meetReadiness?.meet_auth ?? meetAutoJoin?.meet_auth ?? false
  const meetDetail = meetReadiness?.detail ?? meetAutoJoin?.detail

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Settings"
        description="Connect external services, API keys, and integrations"
      />

      <Alert className="border-border bg-muted">
        <AlertDescription className="text-sm text-muted-foreground">
          Google OAuth redirect URI must be{" "}
          <code>
            http://localhost:{data.connections.daemon?.port ?? 8787}/api/connections/google/callback
          </code>{" "}
          (used for Calendar and Gmail).
        </AlertDescription>
      </Alert>

      <InfraStrip data={data} />

      {/* Service cards */}
      <section className="grid gap-4 lg:grid-cols-2">
        <GroqSection
          groq={groq}
          groqKey={groqKey}
          setGroqKey={setGroqKey}
          groqBusy={groqBusy}
          groqModels={groqModels}
          onSave={() => void handleSaveGroq()}
        />

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
                "w-full border-success/30 bg-success/5 text-foreground",
                waFailed && "border-warning/30 bg-warning/5",
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
                  <span className="size-4 rounded-full bg-success glow-green" />
                  <span className="text-base font-medium text-success">Connected</span>
                </>
              ) : waRefreshBusy ? (
                <>
                  <div className="size-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                  <span className="text-sm text-muted-foreground">Refreshing QR…</span>
                </>
              ) : waPairing ? (
                <>
                  <div className="size-8 animate-spin rounded-full border-2 border-success/30 border-t-success" />
                  <span className="text-sm text-success">Pairing…</span>
                  <span className="text-xs text-muted-foreground">Keep WhatsApp open on your phone</span>
                </>
              ) : waFailed ? (
                <>
                  <span className="text-sm font-medium text-warning">QR not available</span>
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
              <>
                <Button
                  variant="outline"
                  className="cursor-pointer"
                  onClick={() => void handleIdentitySync()}
                  disabled={identitySyncBusy}
                >
                  <RefreshCwIcon className={cn("mr-1.5 size-3.5", identitySyncBusy && "animate-spin")} />
                  {identitySyncBusy ? "Syncing…" : "Sync identity directory"}
                </Button>
                <Button
                  variant="outline"
                  className="cursor-pointer"
                  onClick={() => void handleJiraDisconnect()}
                  disabled={jiraBusy}
                >
                  Disconnect
                </Button>
              </>
            )}
          </div>
          {jira?.connected && (jira.jira_users != null || jira.identity_links != null) && (
            <p className="text-xs text-muted-foreground">
              {jira.jira_users != null && <span>{jira.jira_users} Jira users synced</span>}
              {jira.jira_users != null && jira.identity_links != null && " · "}
              {jira.identity_links != null && <span>{jira.identity_links} identity links</span>}
              {jira.user_sync?.last_sync_at && (
                <span> · last sync {new Date(jira.user_sync.last_sync_at).toLocaleString()}</span>
              )}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Create an API token at Atlassian account settings → Security → API tokens. Enable polling
            in <code>config/varys.yaml</code> with <code>jira_enabled: true</code> and{" "}
            <code>jira_projects</code>. When connected, all Slack users can create and assign tickets
            via DM (in-thread confirmation — no owner approval required).
          </p>
        </PanelCard>

        {/* Coolify */}
        <PanelCard
          title="Coolify"
          description="Deploy teammate GitHub repos onto this machine"
          icon={ServerIcon}
          action={
            <StatusBadge
              status={
                coolify?.connected
                  ? "connected"
                  : coolify?.configured
                    ? "degraded"
                    : (coolify?.status ?? "disconnected")
              }
            />
          }
          contentClassName="flex flex-col gap-3"
        >
          {"detail" in (coolify ?? {}) && typeof coolify?.detail === "string" && coolify.detail && (
            <p className="text-sm text-muted-foreground">{coolify.detail}</p>
          )}
          <Input
            placeholder="http://host.docker.internal:8000"
            value={coolifyBaseUrl}
            onChange={(e) => setCoolifyBaseUrl(e.target.value)}
            autoComplete="off"
            aria-label="Coolify base URL"
            className="focus:border-primary/40"
          />
          <Input
            type="password"
            placeholder={coolify?.connected ? "API token (leave blank to keep)" : "Coolify API token"}
            value={coolifyToken}
            onChange={(e) => setCoolifyToken(e.target.value)}
            autoComplete="off"
            aria-label="Coolify API token"
            className="focus:border-primary/40"
          />
          <Input
            placeholder="Server UUID (optional)"
            value={coolifyServerUuid}
            onChange={(e) => setCoolifyServerUuid(e.target.value)}
            autoComplete="off"
            aria-label="Coolify server UUID"
            className="focus:border-primary/40"
          />
          <Input
            placeholder="Project UUID (optional)"
            value={coolifyProjectUuid}
            onChange={(e) => setCoolifyProjectUuid(e.target.value)}
            autoComplete="off"
            aria-label="Coolify project UUID"
            className="focus:border-primary/40"
          />
          <Input
            placeholder="GitHub App UUID (for private repos)"
            value={coolifyGithubAppUuid}
            onChange={(e) => setCoolifyGithubAppUuid(e.target.value)}
            autoComplete="off"
            aria-label="Coolify GitHub App UUID"
            className="focus:border-primary/40"
          />
          <div className="flex flex-wrap gap-2">
            <Button className="cursor-pointer" onClick={() => void handleSaveCoolify()} disabled={coolifyBusy}>
              {coolifyBusy ? "Testing…" : "Save & test"}
            </Button>
            {coolify?.connected && (
              <Button
                variant="outline"
                className="cursor-pointer"
                onClick={() => void handleCoolifyDisconnect()}
                disabled={coolifyBusy}
              >
                Disconnect
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Create a token in Coolify → Keys & Tokens (read + write + deploy). From Docker, use{" "}
            <code>host.docker.internal:8000</code>. Private repos use an SSH deploy key (no Coolify
            GitHub App) — Tempa adds it via your GitHub token. Slack:{" "}
            <code>deploy github.com/owner/repo</code> or <code>deploy … private</code>.
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

        {/* YouTube upload */}
        <PanelCard
          title="YouTube upload"
          description="Upload meeting recordings to YouTube, then remove the local copy"
          icon={UploadCloudIcon}
          action={
            <StatusBadge
              status={
                !youtube?.enabled
                  ? "disconnected"
                  : youtube.scope_ok
                    ? "connected"
                    : "degraded"
              }
            />
          }
          contentClassName="flex flex-col gap-3"
        >
          <p className="text-sm text-muted-foreground">
            Upload enabled:{" "}
            <span className="font-semibold text-foreground">
              {youtube?.enabled ? "yes" : "no"}
            </span>
          </p>
          <p className="text-sm text-muted-foreground">
            Privacy:{" "}
            <span className="font-semibold text-foreground">{youtube?.privacy ?? "unlisted"}</span>
          </p>
          <p className="text-sm text-muted-foreground">
            YouTube access:{" "}
            <span className="font-semibold text-foreground">
              {youtube?.scope_ok ? "granted" : "not granted"}
            </span>
          </p>
          <p className="text-sm text-muted-foreground">
            Local videos pending upload:{" "}
            <span className="font-semibold text-foreground">
              {youtube?.pending_local_videos ?? 0}
            </span>
          </p>
          {!youtube?.enabled && (
            <p className="text-xs text-muted-foreground">
              Set <code>MEET_YOUTUBE_UPLOAD_ENABLED=true</code> and{" "}
              <code>MEET_YOUTUBE_PRIVACY=unlisted</code> in <code>.env</code>, then restart the
              daemon.
            </p>
          )}
          {youtube?.enabled && !youtube.scope_ok && (
            <p className="text-xs text-muted-foreground">
              Reconnect Google in the Calendar panel so the token includes YouTube upload access.
              YouTube Data API v3 must be enabled in Google Cloud Console.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              className="cursor-pointer"
              onClick={() => void handleYoutubeBackfill()}
              disabled={
                youtubeBusy ||
                !youtube?.enabled ||
                !youtube?.scope_ok ||
                (youtube?.pending_local_videos ?? 0) === 0
              }
            >
              {youtubeBusy ? (
                <>
                  <RefreshCwIcon className="mr-1.5 size-3.5 animate-spin" />
                  Uploading…
                </>
              ) : (
                "Upload all & remove local"
              )}
            </Button>
          </div>
        </PanelCard>
      </section>
    </div>
  )
}
