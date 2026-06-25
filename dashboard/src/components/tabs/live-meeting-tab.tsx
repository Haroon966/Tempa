import { useCallback, useEffect, useState } from "react"
import { MessageSquareIcon, RadioIcon, SendIcon, SparklesIcon } from "lucide-react"
import { toast } from "sonner"
import {
  fetchActiveMeetings,
  sendMeetingChat,
  type ActiveMeetingLive,
} from "@/lib/api"
import { PanelCard } from "@/components/dashboard/panel-card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"

export function LiveMeetingTab() {
  const [active, setActive] = useState<ActiveMeetingLive[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [chatText, setChatText] = useState("")
  const [sending, setSending] = useState(false)

  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const res = await fetchActiveMeetings()
      setActive(res.active)
      setLoadError(null)
      if (res.active.length > 0 && !selectedId) {
        setSelectedId(res.active[0].meeting_id)
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Meet worker unavailable")
      setActive([])
    } finally {
      setLoading(false)
    }
  }, [selectedId])

  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), 5000)
    return () => clearInterval(t)
  }, [load])

  const current = active.find((m) => m.meeting_id === selectedId) ?? active[0]

  async function handleSend(text?: string) {
    const msg = (text ?? chatText).trim()
    if (!msg || !current) return
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

  if (loading) {
    return (
      <PanelCard title="Live meeting" description="Loading…" icon={RadioIcon}>
        <p className="text-sm text-muted-foreground">Checking for active sessions…</p>
      </PanelCard>
    )
  }

  if (loadError) {
    return (
      <PanelCard title="Live meeting" description="Worker unavailable" icon={RadioIcon}>
        <p className="text-sm text-destructive">{loadError}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          Ensure the Meet worker is running and calendar auto-join is configured.
        </p>
      </PanelCard>
    )
  }

  if (active.length === 0) {
    return (
      <PanelCard
        title="Live meeting"
        description="No active meeting sessions"
        icon={RadioIcon}
      >
        <p className="text-sm text-muted-foreground">
          When Tempa joins a calendar Meet, transcript, notes, and suggested chat replies appear here.
        </p>
      </PanelCard>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap gap-2">
        {active.map((m) => (
          <Button
            key={m.meeting_id}
            variant={current?.meeting_id === m.meeting_id ? "default" : "outline"}
            size="sm"
            className="cursor-pointer"
            onClick={() => setSelectedId(m.meeting_id)}
          >
            {m.title || m.meeting_id.slice(0, 8)}
            <Badge variant="secondary" className="ml-2 text-xs">
              {m.status}
            </Badge>
          </Button>
        ))}
      </div>

      {current && (
        <div className="grid gap-4 lg:grid-cols-2">
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

      {current && (current.suggestions?.length ?? 0) > 0 && (
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

      {current && (
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
