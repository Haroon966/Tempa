import { useEffect, useState } from "react"
import { RadioIcon } from "lucide-react"
import type { ActivityEvent, DashboardPayload } from "@/types/dashboard"
import { formatTime } from "@/lib/format"
import { PanelCard } from "@/components/dashboard/panel-card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { statusDot } from "@/components/status-badge"
import { cn } from "@/lib/utils"

export function ActivityTab({ data }: { data: DashboardPayload }) {
  const [live, setLive] = useState<ActivityEvent[]>(data.recent_activity)
  const [connected, setConnected] = useState(false)

  useEffect(() => { setLive(data.recent_activity) }, [data.recent_activity])

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws"
    const ws = new WebSocket(`${proto}://${window.location.host}/api/agents/activity`)
    ws.onopen  = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as ActivityEvent
        setLive((prev) => [...prev.slice(-99), event])
      } catch { /* ignore */ }
    }
    return () => ws.close()
  }, [])

  useEffect(() => {
    if (connected) return
    const id = setInterval(() => {
      setLive((prev) => (prev.length ? prev : data.recent_activity))
    }, 10000)
    return () => clearInterval(id)
  }, [connected, data.recent_activity])

  const events = [...(live.length ? live : data.recent_activity)].reverse()

  return (
    <PanelCard
      title="Agent activity stream"
      description="Live orchestrator plan, delegate, merge, and worker events"
      icon={RadioIcon}
      action={
        <Badge
          variant="outline"
          className={cn(
            "gap-1.5 border",
            connected
              ? "border-green-300 bg-green-50 text-green-700"
              : "border-border bg-muted/60 text-muted-foreground",
          )}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              connected ? cn(statusDot("connected"), "pulse-live") : statusDot("disconnected"),
            )}
            aria-hidden
          />
          {connected ? "Live" : "Polling"}
        </Badge>
      }
    >
      <ScrollArea className="h-[520px] pr-2">
        {events.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <RadioIcon className="size-8 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">No agent activity yet.</p>
          </div>
        ) : (
          <ol className="flex flex-col gap-0">
            {events.map((event, i) => (
              <li key={`${event.timestamp}-${i}`} className="relative flex gap-4 pb-5 last:pb-0">
                {/* connector line */}
                {i < events.length - 1 && (
                  <span
                    className="absolute left-[11px] top-6 h-[calc(100%-12px)] w-px bg-gradient-to-b from-border to-transparent"
                    aria-hidden
                  />
                )}

                {/* dot */}
                <span
                  className="relative z-10 mt-1 flex size-[22px] shrink-0 items-center justify-center rounded-full border border-border bg-muted"
                  aria-hidden
                >
                  <span className="size-1.5 rounded-full bg-primary" />
                </span>

                {/* card */}
                <div className="min-w-0 flex-1 rounded-lg border border-border bg-muted/30 p-3 transition-colors duration-200 hover:border-primary/25 hover:bg-muted/60">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="border-border bg-muted text-xs text-primary">
                      {event.agent === "orchestrator" ? "Orchestrator" : event.agent}
                    </Badge>
                    <span className="text-sm font-medium text-foreground">{event.action}</span>
                    <span className="ml-auto shrink-0 text-[11px] text-muted-foreground/70">
                      {formatTime(event.timestamp)}
                    </span>
                  </div>
                  {event.detail && (
                    <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                      {event.detail}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </ScrollArea>
    </PanelCard>
  )
}
