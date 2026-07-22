import {
  Building2Icon,
  CalendarOffIcon,
  ClockIcon,
  HomeIcon,
  LayoutGridIcon,
  ListIcon,
  MapPinIcon,
  PlaneIcon,
  RefreshCwIcon,
  SignalLowIcon,
  UserMinusIcon,
  UsersIcon,
} from "lucide-react"
import { useMemo, useState } from "react"
import { PageHeader } from "@/components/dashboard/page-header"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatCard } from "@/components/dashboard/stat-card"
import { PresenceBoard } from "@/components/presence/presence-board"
import { flattenEntries } from "@/components/presence/presence-board-model"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { usePresence } from "@/hooks/use-presence"
import type { PresenceEntry, PresenceLocation, PresenceStatus } from "@/lib/api"
import { cn } from "@/lib/utils"

const STATUS_ORDER: PresenceStatus[] = [
  "leave",
  "half_day",
  "leave_early",
  "remote",
  "late",
  "partial_away",
  "ooo",
  "office",
  "field_visit",
  "travel",
  "limited",
  "back",
  "other",
]

const STATUS_LABEL: Record<PresenceStatus, string> = {
  leave: "On leave",
  half_day: "Half day",
  leave_early: "Leave early",
  remote: "Remote",
  late: "Late",
  partial_away: "Partial away",
  ooo: "Short OOO",
  back: "Back",
  office: "In office",
  field_visit: "Field visit",
  travel: "Travel",
  limited: "Limited",
  other: "Other",
}

const LOCATION_ORDER: PresenceLocation[] = [
  "i10",
  "niete",
  "h9",
  "rawalpindi",
  "moawin_hq",
  "other_site",
]

const LOCATION_LABEL: Record<PresenceLocation, string> = {
  i10: "I10",
  niete: "Niete",
  h9: "H9",
  rawalpindi: "Rawalpindi",
  moawin_hq: "Moawin HQ",
  other_site: "Other site",
}

const STATUS_BADGE: Record<PresenceStatus, string> = {
  leave: "border-red-200 bg-red-50 text-red-700",
  half_day: "border-orange-200 bg-orange-50 text-orange-700",
  leave_early: "border-amber-200 bg-amber-50 text-amber-700",
  remote: "border-sky-200 bg-sky-50 text-sky-700",
  late: "border-yellow-200 bg-yellow-50 text-yellow-800",
  partial_away: "border-violet-200 bg-violet-50 text-violet-700",
  ooo: "border-slate-200 bg-slate-50 text-slate-700",
  back: "border-emerald-200 bg-emerald-50 text-emerald-700",
  office: "border-teal-200 bg-teal-50 text-teal-700",
  field_visit: "border-indigo-200 bg-indigo-50 text-indigo-700",
  travel: "border-cyan-200 bg-cyan-50 text-cyan-700",
  limited: "border-rose-200 bg-rose-50 text-rose-700",
  other: "border-border bg-muted text-muted-foreground",
}

function todayLocalIso() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function relativeTime(ts: string) {
  if (!ts) return ""
  const t = Date.parse(ts)
  if (Number.isNaN(t)) return ts
  const diff = Date.now() - t
  const mins = Math.round(diff / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function PersonRow({ entry }: { entry: PresenceEntry }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/60 py-3 last:border-0">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          {entry.image ? (
            <img src={entry.image} alt="" loading="lazy" className="size-6 rounded-full object-cover" />
          ) : null}
          <span className="font-medium text-foreground">{entry.name}</span>
          <Badge variant="outline" className={cn("text-[11px]", STATUS_BADGE[entry.status])}>
            {STATUS_LABEL[entry.status]}
          </Badge>
          {entry.location ? (
            <Badge variant="outline" className="text-[11px]">
              {LOCATION_LABEL[entry.location] ?? entry.location}
            </Badge>
          ) : null}
          {entry.half ? (
            <Badge variant="outline" className="text-[11px] text-muted-foreground">
              {entry.half} half
            </Badge>
          ) : null}
          {entry.reason ? (
            <Badge variant="outline" className="text-[11px] text-muted-foreground">
              {entry.reason}
            </Badge>
          ) : null}
        </div>
        <p className="truncate text-sm text-muted-foreground">{entry.note || entry.raw_text}</p>
      </div>
      <div className="shrink-0 text-right text-xs text-muted-foreground">
        <div>{relativeTime(entry.ts)}</div>
        <div className="opacity-60">{entry.source}</div>
      </div>
    </div>
  )
}

export function PresenceTab() {
  const [date, setDate] = useState(todayLocalIso)
  const [view, setView] = useState<"board" | "list">("board")
  const { data, loading, error, syncing, sync } = usePresence(date)

  const total = useMemo(() => {
    if (!data) return 0
    return Object.values(data.counts).reduce((a, b) => a + b, 0)
  }, [data])

  const boardEntries = useMemo(() => (data ? flattenEntries(data) : []), [data])

  const filledGroups = useMemo(() => {
    if (!data) return []
    return STATUS_ORDER.filter((s) => (data.groups[s]?.length ?? 0) > 0)
  }, [data])

  const filledLocations = useMemo(() => {
    if (!data) return []
    return LOCATION_ORDER.filter((l) => (data.by_location[l]?.length ?? 0) > 0)
  }, [data])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Presence"
        description="Live board from Slack #presence — leave, remote, office sites, and field visits"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg border border-border p-0.5">
              <Button
                variant={view === "board" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("board")}
              >
                <LayoutGridIcon className="size-4" />
                Board
              </Button>
              <Button
                variant={view === "list" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("list")}
              >
                <ListIcon className="size-4" />
                List
              </Button>
            </div>
            <Input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-40"
            />
            <Button variant="outline" size="sm" onClick={() => void sync()} disabled={syncing}>
              <RefreshCwIcon className={cn("size-4", syncing && "animate-spin")} />
              Sync
            </Button>
          </div>
        }
      />

      {error ? (
        <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      ) : null}

      {loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      ) : null}

      {data ? (
        <>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span>
              #{data.channel.name} · {total} update{total === 1 ? "" : "s"} on {data.date}
            </span>
            {data.updated_at ? <span>Last sync {relativeTime(data.updated_at)}</span> : null}
            <span className="opacity-70">{data.llm_model}</span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
            <StatCard label="Leave" value={data.counts.leave} icon={CalendarOffIcon} />
            <StatCard label="Half day" value={data.counts.half_day} icon={UserMinusIcon} />
            <StatCard label="Leave early" value={data.counts.leave_early} icon={ClockIcon} />
            <StatCard label="Remote" value={data.counts.remote} icon={HomeIcon} accent="sky" />
            <StatCard label="Late" value={data.counts.late} icon={ClockIcon} accent="orange" />
            <StatCard label="Partial away" value={data.counts.partial_away} icon={UsersIcon} />
            <StatCard label="OOO" value={data.counts.ooo} icon={UserMinusIcon} />
            <StatCard label="Office" value={data.counts.office} icon={Building2Icon} />
            <StatCard label="Field visit" value={data.counts.field_visit} icon={MapPinIcon} accent="sky" />
            <StatCard label="Travel" value={data.counts.travel} icon={PlaneIcon} />
            <StatCard label="Limited" value={data.counts.limited} icon={SignalLowIcon} accent="orange" />
            <StatCard label="Back" value={data.counts.back} icon={Building2Icon} />
          </div>

          {view === "board" ? (
            <PresenceBoard entries={boardEntries} />
          ) : (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                {filledGroups.map((status) => (
                  <PanelCard key={status} title={STATUS_LABEL[status]} description={`${data.groups[status].length} people`}>
                    {data.groups[status].map((entry) => (
                      <PersonRow key={`${entry.user_id}-${entry.message_ts}`} entry={entry} />
                    ))}
                  </PanelCard>
                ))}
              </div>

              {filledLocations.length > 0 ? (
                <div className="space-y-3">
                  <h2 className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">By location</h2>
                  <div className="grid gap-4 lg:grid-cols-2">
                    {filledLocations.map((loc) => (
                      <PanelCard key={loc} title={LOCATION_LABEL[loc]} description={`${data.by_location[loc].length} people`}>
                        {data.by_location[loc].map((entry) => (
                          <PersonRow key={`${loc}-${entry.user_id}-${entry.message_ts}`} entry={entry} />
                        ))}
                      </PanelCard>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}

          {filledGroups.length === 0 ? (
            <PanelCard title="No updates" description="No classified presence posts for this date yet. Try Sync.">
              <p className="text-sm text-muted-foreground">
                Tempa reads Slack #{data.channel.name} and classifies leave, remote, office sites, and field visits.
              </p>
            </PanelCard>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
