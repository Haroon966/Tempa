import { useMemo, useState } from "react"
import {
  ArchiveIcon,
  ArrowRightIcon,
  AudioLinesIcon,
  CalendarIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ClockIcon,
  DatabaseIcon,
  FileTextIcon,
  FilterIcon,
  FolderIcon,
  HardDriveIcon,
  MessageCircleIcon,
  MinusCircleIcon,
  SearchIcon,
  ServerIcon,
  VideoIcon,
  XCircleIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { DashboardPayload, MeetingRecord } from "@/types/dashboard"
import { PageHeader } from "@/components/dashboard/page-header"
import { MeetingDetailModal } from "@/components/meeting-detail-modal"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { formatBytes, formatTime } from "@/lib/format"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

type MeetingFilter = "all" | "summarized" | "media"

const FILTER_OPTIONS: { id: MeetingFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "summarized", label: "Summarized" },
  { id: "media", label: "Has media" },
]

export function DataTab({ data }: { data: DashboardPayload }) {
  const navigateSection = useNavigateSection()
  const { data: stats, meetings, calendar, whatsapp } = data
  const [selectedMeeting, setSelectedMeeting] = useState<MeetingRecord | null>(null)
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<MeetingFilter>("all")

  const rag = data.connections.rag
  const totalBytes = stats.vector_db_bytes + stats.meetings_bytes
  const vectorPct = totalBytes > 0 ? Math.round((stats.vector_db_bytes / totalBytes) * 100) : 0
  const summariesReady = useMemo(
    () => meetings.filter((m) => isSummaryReady(m.minutes_status)).length,
    [meetings],
  )
  const withMedia = useMemo(
    () => meetings.filter((m) => hasMediaArtifacts(m)).length,
    [meetings],
  )

  const filteredMeetings = useMemo(() => {
    const q = query.trim().toLowerCase()
    return meetings.filter((meeting) => {
      if (filter === "summarized" && !isSummaryReady(meeting.minutes_status)) return false
      if (filter === "media" && !hasMediaArtifacts(meeting)) return false
      if (!q) return true
      const haystack = [
        meeting.title,
        meeting.id,
        ...(meeting.participants ?? []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
      return haystack.includes(q)
    })
  }, [meetings, query, filter])

  return (
    <div className="flex flex-col gap-5 lg:gap-6">
      <PageHeader
        title="Meeting archive"
        description="Searchable meeting library, transcripts, and media"
      />
      {rag?.error != null && (
        <AlertBanner
          title="Memory search offline"
          message={`Tempa cannot search saved context. ${String(rag.error)}`}
        />
      )}

      {/* ── KPI strip ───────────────────────────────────────── */}
      <section aria-label="Data overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          label="Memories indexed"
          value={stats.rag_chunks.toLocaleString()}
          hint="searchable text chunks"
          icon={DatabaseIcon}
        />
        <KpiTile
          label="Meetings saved"
          value={String(meetings.length)}
          hint={`${summariesReady} summarized`}
          icon={ArchiveIcon}
          accent="orange"
        />
        <KpiTile
          label="Disk used"
          value={formatBytes(totalBytes)}
          hint={`${vectorPct}% index · ${100 - vectorPct}% files`}
          icon={HardDriveIcon}
          accent="sky"
        />
        <KpiTile
          label="Incoming items"
          value={String(calendar.upcoming.length + whatsapp.recent_messages.length)}
          hint="calendar + WhatsApp"
          icon={MessageCircleIcon}
        />
      </section>

      {/* ── Main workspace ──────────────────────────────────── */}
      <div className="grid gap-5 xl:grid-cols-12 xl:gap-6">
        {/* Meetings library */}
        <section
          aria-labelledby="data-library-heading"
          className="bento-tile overflow-hidden before:hidden hover:translate-y-0 xl:col-span-8"
        >
          <div className="border-b border-border/60 px-4 py-4 sm:px-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 id="data-library-heading" className="text-lg font-bold tracking-tight text-foreground">
                  Meeting library
                </h2>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Search, filter, and open recordings with transcripts and summaries.
                </p>
              </div>
              <Badge variant="outline" className="w-fit shrink-0 border-border bg-muted font-medium">
                {filteredMeetings.length} shown
              </Badge>
            </div>

            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative min-w-0 flex-1">
                <SearchIcon
                  className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search by title, people, or ID…"
                  className="cursor-text pl-8"
                  aria-label="Search meetings"
                />
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <FilterIcon className="mr-0.5 size-3.5 text-muted-foreground" aria-hidden />
                {FILTER_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setFilter(option.id)}
                    className={cn(
                      "cursor-pointer rounded-full border px-3 py-1 text-xs font-semibold transition-colors duration-200",
                      filter === option.id
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-muted/40 text-muted-foreground hover:border-border hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {meetings.length === 0 ? (
            <EmptyBlock
              icon={ArchiveIcon}
              title="No recordings yet"
              description="When Tempa joins a meeting, it will appear here with media and an AI summary."
            />
          ) : filteredMeetings.length === 0 ? (
            <EmptyBlock
              icon={SearchIcon}
              title="No matches"
              description="Try a different search term or filter."
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="cursor-pointer"
                  onClick={() => {
                    setQuery("")
                    setFilter("all")
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-border/60 hover:bg-transparent">
                    <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                      Meeting
                    </TableHead>
                    <TableHead className="hidden text-[11px] font-bold uppercase tracking-wider text-muted-foreground md:table-cell">
                      Summary
                    </TableHead>
                    <TableHead className="hidden text-[11px] font-bold uppercase tracking-wider text-muted-foreground lg:table-cell">
                      Files
                    </TableHead>
                    <TableHead className="text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                      Open
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredMeetings.map((meeting) => (
                    <MeetingTableRow
                      key={meeting.id}
                      meeting={meeting}
                      selected={selectedMeeting?.id === meeting.id}
                      onOpen={() => setSelectedMeeting(meeting)}
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        {/* Context sidebar */}
        <aside className="flex flex-col gap-4 xl:col-span-4">
          <SidebarPanel title="Storage" icon={HardDriveIcon}>
            <div className="space-y-3">
              <div className="flex items-end justify-between gap-2">
                <div>
                  <p className="text-2xl font-extrabold tracking-tight text-foreground">
                    {formatBytes(totalBytes)}
                  </p>
                  <p className="text-xs text-muted-foreground">total on disk</p>
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  <p>{stats.rag_chunks.toLocaleString()} memories</p>
                  <p>{withMedia} with media</p>
                </div>
              </div>
              {totalBytes > 0 && (
                <>
                  <div className="flex h-2 overflow-hidden rounded-full bg-muted">
                    <div className="bg-primary" style={{ width: `${vectorPct}%` }} />
                    <div className="bg-cta/60" style={{ width: `${100 - vectorPct}%` }} />
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-primary" aria-hidden />
                      Index {formatBytes(stats.vector_db_bytes)}
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-cta/60" aria-hidden />
                      Files {formatBytes(stats.meetings_bytes)}
                    </span>
                  </div>
                </>
              )}
            </div>
          </SidebarPanel>

          <SidebarPanel
            title="Calendar"
            icon={CalendarIcon}
            action={
              calendar.upcoming.length > 0 ? (
                <span className="text-[11px] font-medium text-muted-foreground">7 days</span>
              ) : null
            }
          >
            {calendar.upcoming.length === 0 ? (
              <SidebarEmpty
                text="No upcoming events"
                actionLabel="Connect calendar"
                onAction={() => navigateSection("settings")}
              />
            ) : (
              <ul className="flex flex-col gap-1.5">
                {calendar.upcoming.slice(0, 5).map((event) => (
                  <li key={event.id} className="list-row px-2.5 py-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{event.summary}</p>
                        <p className="text-[11px] text-muted-foreground">{formatTime(event.start)}</p>
                      </div>
                      {event.has_meet ? (
                        <VideoIcon className="size-3.5 shrink-0 text-primary" aria-label="Has Meet link" />
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SidebarPanel>

          <SidebarPanel title="WhatsApp" icon={MessageCircleIcon}>
            {whatsapp.recent_messages.length === 0 ? (
              <SidebarEmpty
                text="No messages buffered"
                actionLabel="Set up WhatsApp"
                onAction={() => navigateSection("settings")}
              />
            ) : (
              <ul className="flex max-h-44 flex-col gap-1.5 overflow-auto pr-0.5">
                {whatsapp.recent_messages.slice(0, 4).map((msg) => (
                  <li key={msg.id} className="list-row px-2.5 py-2">
                    <p className="truncate text-sm font-medium text-foreground">{msg.from}</p>
                    <p className="line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{msg.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </SidebarPanel>

          <details className="group bento-tile before:hidden open:pb-0 hover:translate-y-0">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3.5 [&::-webkit-details-marker]:hidden">
              <div className="flex items-center gap-2">
                <ServerIcon className="size-4 text-primary" aria-hidden />
                <span className="text-sm font-semibold text-foreground">System paths</span>
              </div>
              <ChevronDownIcon
                className="size-4 text-muted-foreground transition-transform duration-200 group-open:rotate-180"
                aria-hidden
              />
            </summary>
            <div className="space-y-2 border-t border-border/60 px-4 py-3">
              {[
                { label: "Search index", path: stats.vector_db_path, icon: DatabaseIcon },
                { label: "Recordings", path: stats.meetings_path, icon: VideoIcon },
                { label: "Sessions", path: stats.sessions_path, icon: FolderIcon },
                { label: "Database", path: stats.db_path, icon: ServerIcon },
              ].map(({ label, path, icon: Icon }) => (
                <div key={label} className="rounded-lg border border-border/70 bg-muted/20 px-2.5 py-2">
                  <div className="flex items-center gap-1.5">
                    <Icon className="size-3 text-primary" aria-hidden />
                    <span className="text-xs font-medium text-foreground">{label}</span>
                  </div>
                  <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={path}>
                    {path}
                  </p>
                </div>
              ))}
              <div className="flex items-center justify-between rounded-lg border border-border/70 bg-muted/20 px-2.5 py-2">
                <span className="text-xs font-medium text-foreground">Automation & memory</span>
                <div className="flex gap-1.5">
                  <StatusBadge status={stats.playwright_installed ? "healthy" : "unhealthy"} />
                  <StatusBadge status={rag?.error ? "unhealthy" : "healthy"} />
                </div>
              </div>
            </div>
          </details>
        </aside>
      </div>

      <MeetingDetailModal
        meeting={selectedMeeting}
        open={selectedMeeting != null}
        onOpenChange={(open) => !open && setSelectedMeeting(null)}
      />
    </div>
  )
}

function KpiTile({
  label,
  value,
  hint,
  icon: Icon,
  accent = "teal",
}: {
  label: string
  value: string
  hint: string
  icon: LucideIcon
  accent?: "teal" | "orange" | "sky"
}) {
  const iconStyles = {
    teal: "border-border bg-muted text-primary",
    orange: "border-cta/25 bg-cta/10 text-cta",
    sky: "border-sky-200 bg-sky-50 text-sky-700",
  }

  return (
    <div className="bento-tile p-4 before:hidden hover:translate-y-0 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <div
          className={cn(
            "flex size-9 items-center justify-center rounded-xl border",
            iconStyles[accent],
          )}
        >
          <Icon className="size-4" aria-hidden />
        </div>
      </div>
      <p className="mt-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-extrabold tracking-tight text-foreground">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function MeetingTableRow({
  meeting,
  selected,
  onOpen,
}: {
  meeting: MeetingRecord
  selected: boolean
  onOpen: () => void
}) {
  const summary = summaryLabel(meeting.minutes_status)
  const hasAudio = meeting.artifacts?.audio === true

  return (
    <TableRow
      className={cn(
        "cursor-pointer border-border/50 transition-colors duration-200 hover:bg-muted/50",
        selected && "bg-primary/5 hover:bg-primary/8",
      )}
      onClick={onOpen}
    >
      <TableCell className="max-w-[320px]">
        <p className="truncate font-semibold text-foreground">{meeting.title || "Untitled meeting"}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {meeting.started_at ? formatTime(meeting.started_at) : "Unknown date"}
        </p>
        {meeting.participants && meeting.participants.length > 0 && (
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground/80">
            {meeting.participants.slice(0, 3).join(", ")}
            {meeting.participants.length > 3 ? ` +${meeting.participants.length - 3}` : ""}
          </p>
        )}
        {hasAudio && (
          <Badge variant="outline" className="mt-2 gap-1 border-border bg-muted/50 text-[10px] font-medium text-muted-foreground">
            <AudioLinesIcon className="size-3" aria-hidden />
            Audio
          </Badge>
        )}
      </TableCell>
      <TableCell className="hidden md:table-cell">
        <SummaryBadge label={summary.label} tone={summary.tone} />
      </TableCell>
      <TableCell className="hidden lg:table-cell">
        <ArtifactIcons artifacts={meeting.artifacts} />
      </TableCell>
      <TableCell className="text-right">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="cursor-pointer gap-1 text-primary hover:text-primary"
          onClick={(event) => {
            event.stopPropagation()
            onOpen()
          }}
        >
          View <ArrowRightIcon className="size-3" />
        </Button>
      </TableCell>
    </TableRow>
  )
}

function ArtifactIcons({ artifacts }: { artifacts?: Record<string, boolean> }) {
  if (!artifacts) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  const items = [
    { key: "audio", icon: AudioLinesIcon, label: "Audio" },
    { key: "video", icon: VideoIcon, label: "Video" },
    { key: "transcript", icon: FileTextIcon, label: "Transcript" },
  ].filter(({ key }) => artifacts[key])

  if (items.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  return (
    <div className="flex flex-wrap gap-1">
      {items.map(({ key, icon: Icon, label }) => (
        <Badge
          key={key}
          variant="outline"
          className="gap-1 border-border bg-muted/50 text-[10px] font-medium text-muted-foreground"
        >
          <Icon className="size-3" aria-hidden />
          {label}
        </Badge>
      ))}
    </div>
  )
}

function SidebarPanel({
  title,
  icon: Icon,
  action,
  children,
}: {
  title: string
  icon: LucideIcon
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="bento-tile p-4 before:hidden hover:translate-y-0">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-lg border border-border bg-muted text-primary">
            <Icon className="size-3.5" aria-hidden />
          </div>
          <h3 className="text-sm font-bold text-foreground">{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

function SidebarEmpty({
  text,
  actionLabel,
  onAction,
}: {
  text: string
  actionLabel: string
  onAction: () => void
}) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-muted/20 px-3 py-4 text-center">
      <p className="text-xs text-muted-foreground">{text}</p>
      <button
        type="button"
        onClick={onAction}
        className="mt-2 inline-flex cursor-pointer items-center gap-1 text-xs font-semibold text-primary transition-colors duration-200 hover:underline"
      >
        {actionLabel} <ArrowRightIcon className="size-3" />
      </button>
    </div>
  )
}

function AlertBanner({ title, message }: { title: string; message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3"
    >
      <XCircleIcon className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-destructive">{title}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-destructive/80">{message}</p>
      </div>
    </div>
  )
}

function EmptyBlock({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl border border-border bg-muted">
        <Icon className="size-5 text-primary/60" aria-hidden />
      </div>
      <div>
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}

function SummaryBadge({
  label,
  tone,
}: {
  label: string
  tone: "ready" | "progress" | "missing" | "error"
}) {
  const icons: Record<typeof tone, LucideIcon> = {
    ready: CheckCircle2Icon,
    progress: ClockIcon,
    missing: MinusCircleIcon,
    error: XCircleIcon,
  }
  const styles: Record<typeof tone, string> = {
    ready: "border-emerald-200/80 bg-emerald-50/80 text-emerald-800",
    progress: "border-amber-200/80 bg-amber-50/80 text-amber-800",
    missing: "border-border bg-muted text-muted-foreground",
    error: "border-red-200/80 bg-red-50/80 text-red-700",
  }
  const Icon = icons[tone]

  return (
    <Badge variant="outline" className={cn("gap-1 text-[11px] font-medium", styles[tone])}>
      <Icon className="size-3" aria-hidden />
      {label}
    </Badge>
  )
}

function isSummaryReady(status?: string) {
  const key = (status || "none").toLowerCase()
  return key === "complete" || key === "done" || key === "ready"
}

function hasMediaArtifacts(meeting: MeetingRecord) {
  const artifacts = meeting.artifacts
  if (!artifacts) return false
  return Boolean(artifacts.audio || artifacts.video || artifacts.transcript)
}

function summaryLabel(status?: string): { label: string; tone: "ready" | "progress" | "missing" | "error" } {
  const key = (status || "none").toLowerCase()
  if (isSummaryReady(status)) return { label: "Ready", tone: "ready" }
  if (key === "partial") return { label: "Partial", tone: "progress" }
  if (key === "pending" || key === "processing") return { label: "Generating", tone: "progress" }
  if (key === "failed" || key === "error") return { label: "Failed", tone: "error" }
  return { label: "None", tone: "missing" }
}
