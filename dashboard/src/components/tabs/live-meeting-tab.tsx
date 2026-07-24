import { useCallback, useEffect, useRef, useState } from "react"
import { MessageSquareIcon, RadioIcon, SendIcon, SparklesIcon } from "lucide-react"
import { toast } from "sonner"
import {
  fetchActiveMeetings,
  sendMeetingChat,
  type ActiveMeetingLive,
} from "@/lib/api"
import { PageHeader } from "@/components/dashboard/page-header"
import { PanelCard } from "@/components/dashboard/panel-card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"

const LIVE_POLL_MS = 5000

function isLiveSession(m: ActiveMeetingLive): boolean {
  const status = m.status ?? ""
  return Boolean(m.meeting_id) && ["queued", "running", "finalizing", "waiting_to_record", "interrupted", "recording"].includes(status)
}

export function LiveMeetingTab() {
  const [active, setActive] = useState<ActiveMeetingLive[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const [chatText, setChatText] = useState("")
  const [sending, setSending] = useState(false)

  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const inFlight = useRef(false)

  useEffect(() => {
    selectedIdRef.current = selectedId
  }, [selectedId])

  const load = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const res = await fetchActiveMeetings()
      setActive(res.active)
      setLoadError(null)
      const currentSelected = selectedIdRef.current
      if (res.active.length > 0 && !currentSelected) {
        const first = res.active[0]
        setSelectedId(first.meeting_id || first.meet_url || null)
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Meet worker unavailable")
      setActive([])
    } finally {
      setLoading(false)
      inFlight.current = false
    }
  }, [])

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "hidden") return
      void load()
    }
    void load()
    const t = setInterval(tick, LIVE_POLL_MS)
    const onVisibility = () => {
      if (document.visibilityState === "visible") void load()
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      clearInterval(t)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [load])

  const current =
    active.find((m) => m.meeting_id === selectedId || m.meet_url === selectedId) ?? active[0]
  const currentIsLive = current ? isLiveSession(current) : false

  async function handleSend(text?: string) {
    const msg = (text ?? chatText).trim()
    if (!msg || !current || !currentIsLive) return
    setSending(true)
    try {
      await sendMeetingChat(current.meeting_id, msg)
      toast.success("Sent to Meet chat")
      setChatText("")
      void load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Send failed")
    } finally {
      setSending(false)
    }
  }

  const pageHeader = (
    <PageHeader
      title="Live meeting"
      description="Active Meet sessions — transcript, notes, and chat copilot"
    />
  )

  if (loading) {
    return (
      <div className="flex flex-col gap-5">
        {pageHeader}
        <PanelCard title="Live meeting" description="Loading…" icon={RadioIcon}>
          <p className="text-sm text-muted-foreground">Checking for active sessions…</p>
        </PanelCard>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="flex flex-col gap-5">
        {pageHeader}
        <PanelCard title="Live meeting" description="Worker unavailable" icon={RadioIcon}>
          <p className="text-sm text-destructive">{loadError}</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Ensure the Meet worker is running and calendar auto-join is configured.
          </p>
        </PanelCard>
      </div>
    )
  }

  if (active.length === 0) {
    return (
      <div className="flex flex-col gap-5">
        {pageHeader}
        <PanelCard
          title="Live meeting"
          description="No active meeting sessions"
          icon={RadioIcon}
        >
          <p className="text-sm text-muted-foreground">
            When Tempa joins a calendar Meet, transcript, notes, and suggested chat replies appear here.
            Check Overview for meetings in the auto-join window.
          </p>
        </PanelCard>
      </div>
    )
  }

  const statusHint = (status?: string) => {
    if (status === "scheduled") return "In the join window — Tempa will join automatically."
    if (status === "queued") return "Join queued — starting soon."
    if (status === "waiting_to_record") return "In call — waiting for calendar start or first human before recording."
    if (status === "interrupted") return "Prior session interrupted — finalizing artifacts."
    if (status === "completed") return "Speech captured for this event — Tempa will not re-join."
    if (status === "empty") return "Joined an empty room — Tempa will not keep re-joining this event."
    if (status === "failed") return "Last join attempt failed — will retry only if the event still needs coverage."
    return null
  }

  return (
    <div className="flex flex-col gap-6">
      {pageHeader}
      <div className="flex flex-wrap gap-2">
        {active.map((m) => {
          const key = m.meeting_id || m.meet_url || m.title
          const selected = current?.meeting_id
            ? current.meeting_id === m.meeting_id
            : current?.meet_url === m.meet_url
          return (
          <Button
            key={key}
            variant={selected ? "default" : "outline"}
            size="sm"
            className="cursor-pointer"
            onClick={() => setSelectedId(m.meeting_id || m.meet_url || null)}
          >
            {m.title || m.meeting_id?.slice(0, 8) || "Meeting"}
            <Badge variant="secondary" className="ml-2 text-xs">
              {m.status}
            </Badge>
          </Button>
        )})}
      </div>

      {current && (
        <div className="grid gap-4 lg:grid-cols-2">
          {statusHint(current.status) && (
            <p className="text-sm text-muted-foreground lg:col-span-2">{statusHint(current.status)}</p>
          )}
          <PanelCard title="Live transcript" description={current.title} icon={RadioIcon}>
            <ScrollArea className="h-64 rounded-md border border-border/60 bg-muted/20 p-3">
              <pre className="whitespace-pre-wrap text-xs text-foreground">
                {current.transcript_tail || "Waiting for speech…"}
              </pre>
            </ScrollArea>
          </PanelCard>

          <PanelCard title="Live notes" description="Auto-updated summary" icon={SparklesIcon}>
            <ScrollArea className="h-64 rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="whitespace-pre-wrap text-sm text-foreground">
                {current.live_notes || "Notes will appear as the meeting progresses."}
              </p>
            </ScrollArea>
          </PanelCard>
        </div>
      )}

      {current && currentIsLive && (current.suggestions?.length ?? 0) > 0 && (
        <PanelCard title="Suggested replies" description="Approve to send via Meet chat" icon={MessageSquareIcon}>
          <ul className="flex flex-col gap-3">
            {(current.suggestions ?? []).map((s) => (
              <li key={s.id} className="rounded-lg border border-border/60 bg-muted/20 p-3">
                <p className="text-sm text-foreground">{s.text}</p>
                {s.rationale && (
                  <p className="mt-1 text-xs text-muted-foreground">{s.rationale}</p>
                )}
                <Button
                  size="sm"
                  className="mt-2 cursor-pointer"
                  onClick={() => void handleSend(s.text)}
                  disabled={sending}
                >
                  Send to Meet chat
                </Button>
              </li>
            ))}
          </ul>
        </PanelCard>
      )}

      {current && currentIsLive && (
        <PanelCard title="Meet chat" description="Send a message on your behalf" icon={SendIcon}>
          <div className="flex flex-col gap-2">
            <textarea
              className="min-h-[80px] w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
              placeholder="Type a message for in-meeting chat…"
              value={chatText}
              onChange={(e) => setChatText(e.target.value)}
              rows={3}
            />
            <Button
              className="cursor-pointer self-end"
              onClick={() => void handleSend()}
              disabled={sending || !chatText.trim()}
            >
              <SendIcon className="mr-2 size-4" />
              Send
            </Button>
          </div>
        </PanelCard>
      )}
    </div>
  )
}
