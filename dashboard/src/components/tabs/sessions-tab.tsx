import {
  ExternalLinkIcon,
  GitBranchIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { useMemo, useState } from "react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { useCursorSessions } from "@/hooks/use-cursor-sessions"
import type {
  CursorAgentJob,
  CursorSessionActivity,
  CursorSessionDetail,
  SlackConversationTurn,
  SlackParticipant,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const ACTIVE = new Set(["queued", "running", "waiting_ci", "fixing_ci", "running_tests"])

type Filter = "all" | "active" | "done" | "failed"

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "active", label: "Working" },
  { id: "done", label: "Done" },
  { id: "failed", label: "Needs help" },
]

function statusOf(job: CursorAgentJob) {
  return job.status || job.phase || "unknown"
}

function isActive(job: CursorAgentJob) {
  return ACTIVE.has(statusOf(job))
}

function timeAgo(iso?: string): string {
  if (!iso) return ""
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return "just now"
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

function clock(iso?: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.replace("T", " ").slice(0, 19)
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

function slackThreadHref(job: CursorAgentJob): string | null {
  if (!job.channel_id || !job.thread_ts) return null
  return `https://app.slack.com/archives/${job.channel_id}/p${job.thread_ts.replace(".", "")}`
}

function initials(label: string) {
  const parts = label.replace(/[^a-zA-Z0-9\s/_-]/g, " ").trim().split(/[\s/_-]+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ")
}

function statusTone(status: string) {
  if (ACTIVE.has(status)) return "text-blue-700"
  if (status === "completed") return "text-green-700"
  if (["failed", "needs_help", "interrupted"].includes(status)) return "text-red-700"
  return "text-muted-foreground"
}

function Avatar({
  label,
  image,
  tone = "neutral",
  size = "md",
  className,
}: {
  label: string
  image?: string | null
  tone?: "user" | "bot" | "neutral" | "system"
  size?: "sm" | "md"
  className?: string
}) {
  const colors = {
    user: "bg-sky-100 text-sky-800",
    bot: "bg-primary/10 text-primary",
    neutral: "bg-muted text-muted-foreground",
    system: "bg-amber-50 text-amber-800",
  } as const
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-lg text-xs font-bold ring-2 ring-card",
        size === "sm" ? "size-7 text-[10px]" : "size-9",
        colors[tone],
        className,
      )}
      aria-hidden
    >
      {image ? (
        <img src={image} alt="" loading="lazy" className="size-full object-cover" />
      ) : tone === "bot" ? (
        "T"
      ) : tone === "system" ? (
        "C"
      ) : (
        initials(label)
      )}
    </div>
  )
}

function AvatarStack({
  people,
  size = "md",
  max = 3,
}: {
  people: SlackParticipant[]
  size?: "sm" | "md"
  max?: number
}) {
  if (people.length === 0) {
    return <Avatar label="?" tone="neutral" size={size} />
  }
  if (people.length === 1) {
    return <Avatar label={people[0].name} image={people[0].image} tone="user" size={size} />
  }
  const shown = people.slice(0, max)
  const extra = people.length - shown.length
  return (
    <div className="flex items-center" aria-hidden>
      {shown.map((p, i) => (
        <Avatar
          key={p.user_id}
          label={p.name}
          image={p.image}
          tone="user"
          size={size}
          className={cn(i > 0 && "-ml-2")}
        />
      ))}
      {extra > 0 ? (
        <div
          className={cn(
            "relative z-10 -ml-2 flex shrink-0 items-center justify-center rounded-lg bg-muted text-[10px] font-bold text-muted-foreground ring-2 ring-card",
            size === "sm" ? "size-7" : "size-9",
          )}
        >
          +{extra}
        </div>
      ) : null}
    </div>
  )
}

function jobParticipants(job: CursorAgentJob): SlackParticipant[] {
  if (job.participants && job.participants.length > 0) return job.participants
  if (job.user_id || job.user_name) {
    return [
      {
        user_id: job.user_id || "unknown",
        name: job.user_name || job.user_id || "Someone",
        image: job.user_image,
      },
    ]
  }
  return []
}

function threadTitle(job: CursorAgentJob) {
  const people = jobParticipants(job)
  if (people.length === 0) return job.repo || "Conversation"
  if (people.length === 1) return people[0].name
  if (people.length === 2) return `${people[0].name}, ${people[1].name}`
  return `${people[0].name} +${people.length - 1}`
}

function threadSubtitle(job: CursorAgentJob) {
  const people = jobParticipants(job)
  if (people.length <= 2) return null
  return people.map((p) => p.name).join(", ")
}

function ThreadRow({
  job,
  selected,
  onSelect,
}: {
  job: CursorAgentJob
  selected: boolean
  onSelect: () => void
}) {
  const status = statusOf(job)
  const people = jobParticipants(job)
  const title = threadTitle(job)
  const preview = job.ask_text || job.label || job.repo || "No message yet"
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex w-full cursor-pointer items-start gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40",
        selected ? "bg-primary/10" : "hover:bg-muted/60",
      )}
    >
      <div className="relative mt-0.5">
        <AvatarStack people={people} size="md" />
        {isActive(job) ? (
          <span className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-card bg-green-500 pulse-live" />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold text-foreground" title={threadSubtitle(job) || title}>
            {title}
          </span>
          <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
            {timeAgo(job.updated_at)}
          </span>
        </div>
        <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{preview}</p>
        <div className="mt-1 flex items-center gap-1.5 text-[11px]">
          {people.length > 1 ? (
            <span className="shrink-0 text-muted-foreground">{people.length} people</span>
          ) : null}
          {job.repo ? (
            <span className="truncate font-medium text-foreground/70">{job.repo}</span>
          ) : null}
          <span className={cn("capitalize", statusTone(status))}>{statusLabel(status)}</span>
        </div>
      </div>
    </button>
  )
}

function MessageRow({ turn }: { turn: SlackConversationTurn }) {
  const assistant = turn.role === "assistant"
  const name = assistant ? "Tempa" : turn.user_name || turn.user_id || "User"
  return (
    <div className="group flex gap-3 px-4 py-2 transition-colors duration-150 hover:bg-muted/40">
      <Avatar
        label={name}
        image={assistant ? undefined : turn.user_image}
        tone={assistant ? "bot" : "user"}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-sm font-bold text-foreground">{name}</span>
          <span className="text-[11px] tabular-nums text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
            {clock(turn.timestamp)}
          </span>
        </div>
        <pre className="mt-0.5 whitespace-pre-wrap break-words font-sans text-[15px] leading-relaxed text-foreground">
          {turn.text || "—"}
        </pre>
      </div>
    </div>
  )
}

function ActivityRow({ item }: { item: CursorSessionActivity }) {
  return (
    <div className="flex gap-3 px-4 py-1.5">
      <Avatar label="Cursor" tone="system" />
      <div className="min-w-0 flex-1 rounded-lg border border-dashed border-border/80 bg-muted/30 px-3 py-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-900">
            <SparklesIcon className="size-3" aria-hidden />
            Cursor
          </span>
          <span className="text-[11px] tabular-nums text-muted-foreground">{clock(item.at)}</span>
        </div>
        <p className="mt-0.5 text-sm text-foreground">{item.label}</p>
        {item.detail ? (
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words font-sans text-xs leading-relaxed text-muted-foreground">
            {item.detail}
          </pre>
        ) : null}
      </div>
    </div>
  )
}

type TimelineItem =
  | { kind: "message"; at: number; turn: SlackConversationTurn; key: string }
  | { kind: "activity"; at: number; item: CursorSessionActivity; key: string }

function buildTimeline(detail: CursorSessionDetail | null): TimelineItem[] {
  if (!detail) return []
  const items: TimelineItem[] = []
  detail.conversation.forEach((turn, idx) => {
    const ts = turn.timestamp ? Date.parse(turn.timestamp) : NaN
    items.push({
      kind: "message",
      at: Number.isFinite(ts) ? ts : idx,
      turn,
      key: `m-${turn.id || turn.timestamp || idx}`,
    })
  })
  detail.activity.forEach((item, idx) => {
    const ts = item.at ? Date.parse(item.at) : NaN
    items.push({
      kind: "activity",
      at: Number.isFinite(ts) ? ts : idx + 0.5,
      item,
      key: `a-${item.kind}-${item.at}-${idx}`,
    })
  })
  items.sort((a, b) => a.at - b.at)
  return items
}

function ThreadPane({
  job,
  detail,
  loading,
}: {
  job: CursorAgentJob | null
  detail: CursorSessionDetail | null
  loading: boolean
}) {
  const timeline = useMemo(() => buildTimeline(detail), [detail])
  const thread = job ? slackThreadHref(job) : null
  const status = job ? statusOf(job) : ""

  if (!job) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <div className="flex size-14 items-center justify-center rounded-2xl bg-muted">
          <MessageSquareIcon className="size-6 text-muted-foreground" aria-hidden />
        </div>
        <div>
          <p className="text-base font-semibold">Pick a conversation</p>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Choose a thread on the left to read what the teammate asked and how Tempa / Cursor replied.
          </p>
        </div>
      </div>
    )
  }

  if (loading && !detail) {
    return (
      <div className="space-y-4 p-6" aria-busy="true" aria-label="Loading conversation">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="size-9 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          <AvatarStack people={jobParticipants(job)} size="md" max={4} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-bold tracking-tight">
                {threadTitle(job)}
              </h2>
              <span className={cn("text-xs font-medium capitalize", statusTone(status))}>
                {isActive(job) ? (
                  <span className="inline-flex items-center gap-1.5">
                    <LoaderCircleIcon className="size-3 animate-spin" aria-hidden />
                    {statusLabel(status)}
                  </span>
                ) : (
                  statusLabel(status)
                )}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {threadSubtitle(job) ? (
                <span className="truncate" title={threadSubtitle(job) || undefined}>
                  {threadSubtitle(job)}
                </span>
              ) : null}
              {job.repo ? <span className="font-medium text-foreground/80">{job.repo}</span> : null}
              {job.branch ? (
                <span className="inline-flex items-center gap-1">
                  <GitBranchIcon className="size-3" aria-hidden />
                  {job.branch}
                </span>
              ) : null}
              {job.mode ? <span className="capitalize">{job.mode}</span> : null}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {job.pr_url ? (
            <a
              href={job.pr_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
            >
              PR #{job.pr_number || ""}
              <ExternalLinkIcon className="size-3" aria-hidden />
            </a>
          ) : null}
          {thread ? (
            <a
              href={thread}
              target="_blank"
              rel="noreferrer"
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
            >
              Open in Slack
              <ExternalLinkIcon className="size-3" aria-hidden />
            </a>
          ) : null}
        </div>
      </header>

      {job.error ? (
        <div
          role="alert"
          className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800"
        >
          {job.error}
        </div>
      ) : null}

      <ScrollArea className="min-h-0 flex-1">
        <div className="py-3">
          {timeline.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              No messages stored for this thread yet.
              {job.ask_text ? (
                <div className="mx-auto mt-4 max-w-xl rounded-lg border border-border bg-muted/40 px-4 py-3 text-left">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Original ask
                  </p>
                  <pre className="mt-1 whitespace-pre-wrap break-words font-sans text-sm text-foreground">
                    {job.ask_text}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : (
            timeline.map((entry) =>
              entry.kind === "message" ? (
                <MessageRow key={entry.key} turn={entry.turn} />
              ) : (
                <ActivityRow key={entry.key} item={entry.item} />
              ),
            )
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

export function SessionsTab() {
  const {
    sessions,
    activeCount,
    selectedId,
    setSelectedId,
    detail,
    loading,
    detailLoading,
    error,
    refresh,
  } = useCursorSessions()
  const [filter, setFilter] = useState<Filter>("all")
  const [query, setQuery] = useState("")
  const [refreshing, setRefreshing] = useState(false)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return sessions.filter((job) => {
      const status = statusOf(job)
      if (filter === "active" && !ACTIVE.has(status)) return false
      if (filter === "done" && status !== "completed") return false
      if (filter === "failed" && !["failed", "interrupted", "needs_help"].includes(status)) {
        return false
      }
      if (!q) return true
      const names = (job.participants || []).map((p) => p.name).join(" ")
      const hay = [
        job.repo,
        job.label,
        job.ask_text,
        job.user_id,
        job.user_name,
        names,
        job.branch,
        status,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
      return hay.includes(q)
    })
  }, [sessions, filter, query])

  const selectedJob =
    detail?.job && detail.job.id === selectedId
      ? detail.job
      : sessions.find((s) => s.id === selectedId) ?? null

  async function onRefresh() {
    setRefreshing(true)
    try {
      await refresh()
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[560px] flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold tracking-tight">Sessions</h2>
          <p className="text-sm text-muted-foreground">
            Slack conversations with Tempa — same thread view, with Cursor work inline.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void onRefresh()}
          disabled={refreshing}
          className="cursor-pointer gap-1.5"
        >
          <RefreshCwIcon className={cn("size-3.5", refreshing && "animate-spin")} aria-hidden />
          Refresh
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive" className="shrink-0">
          <TriangleAlertIcon className="size-4" />
          <AlertTitle>Couldn’t load sessions</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>{error}</span>
            <Button size="sm" variant="outline" className="cursor-pointer" onClick={() => void onRefresh()}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid min-h-0 flex-1 overflow-hidden rounded-2xl border border-border bg-card shadow-sm lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* Slack-style sidebar */}
        <aside className="flex min-h-0 flex-col border-b border-border lg:border-b-0 lg:border-r">
          <div className="space-y-2 border-b border-border px-3 py-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-bold">Threads</p>
              {activeCount > 0 ? (
                <Badge variant="outline" className="gap-1.5 border-green-200 bg-green-50 text-[10px] text-green-700">
                  <span className="size-1.5 rounded-full bg-green-500 pulse-live" aria-hidden />
                  {activeCount} working
                </Badge>
              ) : (
                <span className="text-[11px] text-muted-foreground">{sessions.length} total</span>
              )}
            </div>
            <div className="relative">
              <SearchIcon
                className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search people or repos"
                className="h-9 border-border/80 bg-muted/40 pl-8 text-sm"
                aria-label="Search threads"
              />
            </div>
            <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Filter threads">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  role="tab"
                  aria-selected={filter === f.id}
                  onClick={() => setFilter(f.id)}
                  className={cn(
                    "cursor-pointer whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium transition-colors duration-150",
                    filter === f.id
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <ScrollArea className="min-h-0 flex-1">
            {loading && sessions.length === 0 ? (
              <div className="space-y-0 p-2" aria-busy="true">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex gap-3 px-2 py-2.5">
                    <Skeleton className="size-9 rounded-lg" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-3.5 w-28" />
                      <Skeleton className="h-3 w-full" />
                    </div>
                  </div>
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <div className="px-4 py-12 text-center">
                <p className="text-sm font-medium">No threads here</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {query
                    ? "Try another name or repo."
                    : "Slack asks that spin up Cursor will land in this list."}
                </p>
              </div>
            ) : (
              <div role="listbox" aria-label="Conversation threads">
                {filtered.map((job) => (
                  <ThreadRow
                    key={job.id}
                    job={job}
                    selected={job.id === selectedId}
                    onSelect={() => setSelectedId(job.id)}
                  />
                ))}
              </div>
            )}
          </ScrollArea>
        </aside>

        {/* Slack-style message pane */}
        <main className="min-h-0 min-w-0 bg-background">
          <ThreadPane job={selectedJob} detail={detail} loading={detailLoading} />
        </main>
      </div>
    </div>
  )
}
