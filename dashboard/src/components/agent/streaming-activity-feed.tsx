import { useEffect, useRef, useState } from "react"
import {
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleDotIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react"
import type { StepEvent } from "@/lib/api"
import type { ActivityEvent } from "@/types/dashboard"
import { cn } from "@/lib/utils"

function StepStatusIcon({ status }: { status: StepEvent["status"] }) {
  if (status === "start") {
    return <Loader2Icon className="size-3.5 shrink-0 motion-safe:animate-spin text-primary" />
  }
  if (status === "done") {
    return <CheckCircle2Icon className="size-3.5 shrink-0 text-green-600" />
  }
  if (status === "error") {
    return <XCircleIcon className="size-3.5 shrink-0 text-destructive" />
  }
  return <CircleDotIcon className="size-3.5 shrink-0 text-muted-foreground" />
}

type FeedItem = {
  key: string
  agent: string
  headline: string
  detail?: string
  status?: StepEvent["status"]
  durationMs?: number
  kind: "step" | "activity"
  running: boolean
}

type StreamingActivityFeedProps = {
  steps: StepEvent[]
  activity: ActivityEvent[]
  className?: string
  live?: boolean
}

function truncate(text: string, max = 48) {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1)}…`
}

function stepHeadline(step: StepEvent, activity: ActivityEvent[]) {
  if (step.status === "start" && step.detail?.trim()) {
    return truncate(step.detail)
  }
  const startAct = activity.find((a) => a.agent === step.agent && a.action === "start")
  if (startAct?.detail?.trim()) return truncate(startAct.detail)
  if (step.status === "error") return "failed"
  if (step.status === "done") return "completed"
  return step.status
}

function friendlyActivity(ev: ActivityEvent): { headline: string; detail?: string } {
  const d = ev.detail || ""
  if (d.startsWith("plan:")) {
    try {
      const steps = JSON.parse(d.slice(5)) as Array<{ agent?: string; task?: string }>
      return {
        headline: "Plan",
        detail: steps.map((s) => `• ${s.agent}: ${s.task ?? ""}`).join("\n"),
      }
    } catch {
      return { headline: "Plan", detail: d.slice(5) }
    }
  }
  if (d.startsWith("understand:")) return { headline: "Understand", detail: d.slice(11) }
  if (d.startsWith("step_start:")) return { headline: "Running", detail: d.slice(11) }
  if (d.startsWith("step_done:")) return { headline: "Done", detail: d.slice(10) }
  if (d === "replan" || d === "goal_replan") return { headline: "Replanning" }
  if (d.startsWith("clarify:")) return { headline: "Clarify", detail: d.slice(8) }
  const wave = d.match(/^wave (\d+)\/(\d+)$/)
  if (wave) return { headline: `Wave ${wave[1]}/${wave[2]}` }
  return { headline: ev.action, detail: d || undefined }
}

function plannedTotal(activity: ActivityEvent[]): number {
  for (const ev of activity) {
    if (ev.detail?.startsWith("plan:")) {
      try {
        const steps = JSON.parse(ev.detail.slice(5)) as unknown[]
        if (Array.isArray(steps)) return steps.length
      } catch {
        return 0
      }
    }
  }
  return 0
}

function buildFeedItems(steps: StepEvent[], activity: ActivityEvent[], live: boolean): FeedItem[] {
  const stepAgents = new Set(steps.map((s) => s.agent))

  const activityItems: FeedItem[] = activity
    .filter((ev) => {
      // ponytail: skip redundant specialist start/completed when a step row exists
      if (stepAgents.has(ev.agent) && (ev.action === "start" || ev.action === "completed")) {
        return false
      }
      return true
    })
    .map((ev, i) => {
      const friendly = friendlyActivity(ev)
      return {
        key: `act-${ev.timestamp}-${i}`,
        agent: ev.agent,
        headline: friendly.headline,
        detail: friendly.detail,
        kind: "activity" as const,
        running: false,
      }
    })

  const stepItems: FeedItem[] = steps.map((step, i) => ({
    key: `step-${step.subtask_id}-${i}`,
    agent: step.agent,
    headline: stepHeadline(step, activity),
    detail: step.detail?.trim() || undefined,
    status: step.status,
    durationMs: step.duration_ms,
    kind: "step" as const,
    running: false,
    sortAt: step.timestamp,
  }))

  const items: (FeedItem & { sortAt?: string })[] = [
    ...activityItems.map((item, i) => ({ ...item, sortAt: activity[i]?.timestamp })),
    ...stepItems,
  ]
  items.sort((a, b) => String(a.sortAt ?? "").localeCompare(String(b.sortAt ?? "")))
  const hasRunningStep = items.some((item) => item.kind === "step" && item.status === "start")

  for (let i = 0; i < items.length; i++) {
    const item = items[i]!
    if (item.kind === "step") {
      item.running = item.status === "start"
    } else if (live && !hasRunningStep && i === items.length - 1) {
      item.running = true
    }
  }

  return items
}

function ActivityAccordionItem({ item }: { item: FeedItem }) {
  const hasDetail = Boolean(item.detail?.trim())
  const [open, setOpen] = useState(item.running)
  const wasRunning = useRef(item.running)

  useEffect(() => {
    if (item.running) {
      setOpen(true)
      wasRunning.current = true
    } else if (wasRunning.current) {
      setOpen(false)
      wasRunning.current = false
    }
  }, [item.running])

  const icon =
    item.kind === "step" ? (
      <StepStatusIcon status={item.status!} />
    ) : item.running ? (
      <Loader2Icon className="size-3.5 shrink-0 motion-safe:animate-spin text-primary" />
    ) : (
      <CircleDotIcon className="size-3.5 shrink-0 text-muted-foreground" />
    )

  const summary = (
    <div
      className={cn(
        "flex items-center gap-2 py-1.5 text-xs",
        item.running && "text-primary",
        hasDetail && "cursor-pointer",
      )}
      onClick={hasDetail ? () => setOpen((v) => !v) : undefined}
      onKeyDown={
        hasDetail
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                setOpen((v) => !v)
              }
            }
          : undefined
      }
      role={hasDetail ? "button" : undefined}
      tabIndex={hasDetail ? 0 : undefined}
      aria-expanded={hasDetail ? open : undefined}
    >
      {icon}
      <span className="min-w-0 flex-1 font-medium capitalize text-foreground">
        {item.agent} {item.headline}
      </span>
      {item.durationMs != null && (
        <span className="shrink-0 tabular-nums text-muted-foreground">{item.durationMs}ms</span>
      )}
      {hasDetail && (
        <ChevronDownIcon
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180",
          )}
          aria-hidden
        />
      )}
    </div>
  )

  if (!hasDetail) return <li>{summary}</li>

  return (
    <li>
      {summary}
      {open && (
        <p className="mb-1 break-words pl-5 text-xs leading-relaxed text-muted-foreground">
          {item.detail}
        </p>
      )}
    </li>
  )
}

export function StreamingActivityFeed({
  steps,
  activity,
  className,
  live = false,
}: StreamingActivityFeedProps) {
  const items = buildFeedItems(steps, activity, live)

  if (items.length === 0) return null

  const doneCount = steps.filter((s) => s.status === "done" || s.status === "error").length
  const planned = plannedTotal(activity)
  const runningStep = [...steps].reverse().find((s) => s.status === "start")

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {live ? "Live activity" : "Activity"}
        </p>
        {planned > 0 && (
          <p className="text-[10px] tabular-nums text-muted-foreground">
            {doneCount}/{planned}
          </p>
        )}
      </div>
      {live && runningStep && (
        <p className="text-xs text-primary">Running {runningStep.agent}…</p>
      )}
      <ol className="flex flex-col divide-y divide-border/40">
        {items.map((item) => (
          <ActivityAccordionItem key={item.key} item={item} />
        ))}
      </ol>
    </div>
  )
}
