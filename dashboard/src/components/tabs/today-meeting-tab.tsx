import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { CalendarIcon, RadioIcon, VideoIcon } from "lucide-react"
import { fetchTodaysMeetings, type TodayMeetingEvent } from "@/lib/api"
import type { MeetingRecord } from "@/types/dashboard"
import {
  assignOverlapColumns,
  eventBlockPosition,
  GRID_HEIGHT_PX,
  GRID_HOURS,
  HOUR_HEIGHT_PX,
} from "@/lib/day-timeline"
import { PageHeader } from "@/components/dashboard/page-header"
import { MeetingDetailModal } from "@/components/meeting-detail-modal"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

const POLL_MS = 45_000
const LIVE_STATUSES = new Set([
  "queued",
  "running",
  "finalizing",
  "waiting_to_record",
  "interrupted",
  "recording",
])

function parseLocalDayStart(dateStr: string): Date {
  const [y, m, d] = dateStr.split("-").map(Number)
  return new Date(y, m - 1, d, 0, 0, 0, 0)
}

function formatClock(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  } catch {
    return iso
  }
}

function formatDateLabel(dateStr: string): string {
  try {
    const [y, m, d] = dateStr.split("-").map(Number)
    return new Date(y, m - 1, d).toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    })
  } catch {
    return dateStr
  }
}

function statusLabel(status: string | null | undefined): string | null {
  if (!status) return null
  if (LIVE_STATUSES.has(status)) return status === "queued" ? "Queued" : "Live"
  if (status === "completed" || status === "done") return "Done"
  if (status === "scheduled") return "Upcoming"
  return status
}

export function TodayMeetingTab() {
  const [date, setDate] = useState<string>("")
  const [events, setEvents] = useState<TodayMeetingEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [archiveMeeting, setArchiveMeeting] = useState<MeetingRecord | null>(null)
  const [lightEvent, setLightEvent] = useState<TodayMeetingEvent | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrolledOnce = useRef(false)
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const res = await fetchTodaysMeetings()
      setDate(res.date)
      setEvents(res.events)
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load today’s meetings")
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
    const t = setInterval(tick, POLL_MS)
    const onVisibility = () => {
      if (document.visibilityState === "visible") void load()
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      clearInterval(t)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [load])

  const dayStart = useMemo(() => (date ? parseLocalDayStart(date) : null), [date])

  const allDay = useMemo(() => events.filter((e) => e.all_day), [events])
  const timed = useMemo(() => events.filter((e) => !e.all_day), [events])

  const overlap = useMemo(() => {
    if (!dayStart) return new Map<string, { column: number; columnCount: number }>()
    return assignOverlapColumns(
      timed.map((e) => ({
        id: e.id,
        startMs: new Date(e.start).getTime(),
        endMs: new Date(e.end).getTime(),
      })),
    )
  }, [timed, dayStart])

  const nowTop = useMemo(() => {
    if (!dayStart || !date) return null
    const now = new Date()
    const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`
    if (todayStr !== date) return null
    const { top } = eventBlockPosition(now, new Date(now.getTime() + 60_000), dayStart)
    return top
  }, [dayStart, date, events])

  useEffect(() => {
    if (scrolledOnce.current || !scrollRef.current || nowTop == null) return
    scrolledOnce.current = true
    scrollRef.current.scrollTop = Math.max(0, nowTop - 120)
  }, [nowTop, loading])

  function onEventClick(ev: TodayMeetingEvent) {
    if (ev.archive?.id) {
      setArchiveMeeting(ev.archive)
      return
    }
    setLightEvent(ev)
  }

  const hours = useMemo(() => Array.from({ length: GRID_HOURS }, (_, i) => i), [])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <PageHeader
        title="Today"
        description={date ? formatDateLabel(date) : "Meetings for the current day"}
      />

      {loading && events.length === 0 ? (
        <p className="text-sm text-muted-foreground">Loading schedule…</p>
      ) : loadError && events.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          <p>{loadError}</p>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card">
          {allDay.length > 0 && (
            <div className="flex gap-2 border-b border-border px-3 py-2">
              <span className="w-14 shrink-0 pt-1 text-[11px] font-medium text-muted-foreground">
                All day
              </span>
              <ul className="flex min-w-0 flex-1 flex-wrap gap-1.5">
                {allDay.map((ev) => (
                  <li key={ev.id}>
                    <button
                      type="button"
                      onClick={() => onEventClick(ev)}
                      className="rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1 text-left text-xs font-medium text-foreground transition-colors hover:bg-primary/15"
                    >
                      {ev.summary}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {timed.length === 0 && allDay.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-16 text-center">
              <CalendarIcon className="size-8 text-muted-foreground/50" aria-hidden />
              <p className="text-sm font-medium text-foreground">No meetings today</p>
              <p className="text-xs text-muted-foreground">
                Calendar events for today will show up here as a day timeline.
              </p>
            </div>
          ) : (
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
              <div className="relative flex" style={{ height: GRID_HEIGHT_PX }}>
                <div className="sticky left-0 z-10 w-14 shrink-0 border-r border-border bg-card">
                  {hours.map((h) => (
                    <div
                      key={h}
                      className="relative"
                      style={{ height: HOUR_HEIGHT_PX }}
                    >
                      {h > 0 && (
                        <span className="absolute -top-2.5 right-2 text-[11px] tabular-nums text-muted-foreground">
                          {new Date(2000, 0, 1, h).toLocaleTimeString(undefined, {
                            hour: "numeric",
                          })}
                        </span>
                      )}
                    </div>
                  ))}
                </div>

                <div className="relative min-w-0 flex-1">
                  {hours.map((h) => (
                    <div
                      key={h}
                      className="border-b border-border/60"
                      style={{ height: HOUR_HEIGHT_PX }}
                    />
                  ))}

                  {nowTop != null && (
                    <div
                      className="pointer-events-none absolute right-0 left-0 z-20 flex items-center"
                      style={{ top: nowTop }}
                      aria-hidden
                    >
                      <span className="size-2.5 -ml-1 shrink-0 rounded-full bg-red-500" />
                      <span className="h-0.5 flex-1 bg-red-500" />
                    </div>
                  )}

                  {dayStart &&
                    timed.map((ev) => {
                      const start = new Date(ev.start)
                      const end = new Date(ev.end)
                      const { top, height } = eventBlockPosition(start, end, dayStart)
                      const layout = overlap.get(ev.id) ?? { column: 0, columnCount: 1 }
                      const widthPct = 100 / layout.columnCount
                      const leftPct = layout.column * widthPct
                      const live = statusLabel(ev.status)
                      const isLive = ev.status != null && LIVE_STATUSES.has(ev.status)

                      return (
                        <button
                          key={ev.id}
                          type="button"
                          onClick={() => onEventClick(ev)}
                          title={ev.summary}
                          className={cn(
                            "absolute z-10 overflow-hidden rounded-md border px-2 py-1 text-left shadow-sm transition-colors",
                            "hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            isLive
                              ? "border-red-500/40 bg-red-500/15 text-foreground"
                              : ev.archive
                                ? "border-primary/25 bg-primary/10 text-foreground"
                                : "border-border bg-muted/80 text-foreground",
                          )}
                          style={{
                            top,
                            height,
                            left: `calc(${leftPct}% + 2px)`,
                            width: `calc(${widthPct}% - 4px)`,
                          }}
                        >
                          <div className="flex items-start gap-1">
                            <span className="min-w-0 flex-1 truncate text-xs font-semibold leading-tight">
                              {ev.summary}
                            </span>
                            {ev.has_meet && (
                              <VideoIcon className="mt-0.5 size-3 shrink-0 opacity-70" aria-hidden />
                            )}
                          </div>
                          <p className="truncate text-[10px] text-muted-foreground">
                            {formatClock(ev.start)} – {formatClock(ev.end)}
                          </p>
                          {live && (
                            <Badge
                              variant="outline"
                              className={cn(
                                "mt-0.5 h-4 gap-0.5 px-1 text-[9px]",
                                isLive && "border-red-500/40 text-red-600 dark:text-red-400",
                              )}
                            >
                              {isLive && <RadioIcon className="size-2.5" aria-hidden />}
                              {live}
                            </Badge>
                          )}
                        </button>
                      )
                    })}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      <MeetingDetailModal
        meeting={archiveMeeting}
        open={archiveMeeting != null}
        onOpenChange={(open) => !open && setArchiveMeeting(null)}
      />

      <Dialog open={lightEvent != null} onOpenChange={(open) => !open && setLightEvent(null)}>
        <DialogContent>
          {lightEvent && (
            <>
              <DialogHeader>
                <DialogTitle>{lightEvent.summary}</DialogTitle>
                <DialogDescription>
                  {lightEvent.all_day
                    ? "All day"
                    : `${formatClock(lightEvent.start)} – ${formatClock(lightEvent.end)}`}
                  {statusLabel(lightEvent.status) ? ` · ${statusLabel(lightEvent.status)}` : ""}
                </DialogDescription>
              </DialogHeader>
              <DialogBody className="flex flex-col gap-3">
                {lightEvent.has_meet && lightEvent.meet_url ? (
                  <a
                    href={lightEvent.meet_url}
                    target="_blank"
                    rel="noreferrer"
                    className={cn(buttonVariants(), "cursor-pointer gap-1.5")}
                  >
                    <VideoIcon className="size-4" aria-hidden />
                    Join Meet
                  </a>
                ) : (
                  <p className="text-sm text-muted-foreground">No Google Meet link on this event.</p>
                )}
                {!lightEvent.archive && (
                  <p className="text-xs text-muted-foreground">
                    Recording and transcript appear here after Tempa joins and the meeting is archived.
                  </p>
                )}
              </DialogBody>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
