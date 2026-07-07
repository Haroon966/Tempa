import { useEffect, useRef, useState } from "react"
import {
  ActivityIcon,
  ArrowRightIcon,
  CalendarIcon,
  ChevronDownIcon,
  DatabaseIcon,
  MessageCircleIcon,
  ServerIcon,
  ShieldCheckIcon,
  SparklesIcon,
  VideoIcon,
  WorkflowIcon,
} from "lucide-react"
import type { DashboardPayload, OrchestratorManifest } from "@/types/dashboard"
import { fetchOrchestrator } from "@/lib/api"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { PageHeader } from "@/components/dashboard/page-header"
import { StatCard } from "@/components/dashboard/stat-card"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function OverviewTab({ data }: { data: DashboardPayload }) {
  const navigateSection = useNavigateSection()
  const { overall, agents, calendar, whatsapp, data: stats } = data
  const [orchestrator, setOrchestrator] = useState<OrchestratorManifest | null>(null)
  const [workersOpen, setWorkersOpen] = useState(false)
  const [videoSrc, setVideoSrc] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    fetchOrchestrator()
      .then(setOrchestrator)
      .catch(() => setOrchestrator(null))
  }, [])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) {
        setVideoSrc((src) => src ?? new URL("../../assets/animated_tempa.mp4", import.meta.url).href)
        void video.play().catch(() => {})
      } else {
        video.pause()
      }
    })
    observer.observe(video)
    return () => observer.disconnect()
  }, [])

  const workerCards = orchestrator?.workers ?? agents.map((a) => ({
    id: a.id,
    name: a.name,
    role: a.role,
    runner: a.id,
    tools: [] as string[],
    skill: "",
    always_run: a.id === "rag",
  }))
  const readyPct = overall.total_components > 0
    ? Math.round((overall.healthy / overall.total_components) * 100)
    : 0

  const statusHeadline =
    overall.status === "healthy"
      ? "Your AI core is running"
      : overall.status === "degraded"
        ? `${overall.unhealthy + overall.degraded} area(s) need attention`
        : "System needs attention"

  return (
    <div className="flex flex-col gap-6 lg:gap-8">
      <PageHeader
        title="Overview"
        description="System health, stats, and quick status at a glance"
      />

      <div className="grid gap-4 lg:grid-cols-12 lg:gap-5">
        <div className="surface-card relative self-start overflow-hidden lg:col-span-3">
          <div className="relative aspect-square w-full bg-muted p-1.5">
            <video
              ref={videoRef}
              src={videoSrc ?? undefined}
              loop
              muted
              playsInline
              preload="none"
              className="h-full w-full rounded-xl object-cover"
              aria-label="Tempa mascot animation"
            />
          </div>
        </div>

        <div className="surface-card flex flex-col justify-between p-6 sm:p-8 lg:col-span-9">
          <div>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-primary">
                <SparklesIcon className="size-3" />
                Command center
              </span>
              <StatusBadge status={overall.status} />
            </div>

            <h2 className="text-2xl font-extrabold tracking-tight text-foreground sm:text-3xl">
              {statusHeadline}
            </h2>
            <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
              Personal AI agent — always-on, watching your calendar, inbox, and messages.
            </p>
          </div>

          <div className="mt-6 space-y-4">
            <div>
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-semibold text-muted-foreground">System readiness</span>
                <span className="text-lg font-extrabold text-primary">{readyPct}%</span>
              </div>
              <Progress
                value={readyPct}
                className="h-2.5 bg-muted [&>div]:rounded-full [&>div]:bg-primary [&>div]:transition-all [&>div]:duration-700"
              />
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <MetricChip count={overall.healthy} label="Healthy" tone="success" />
              <MetricChip count={overall.degraded} label="Degraded" tone="warning" />
              <MetricChip count={overall.unhealthy} label="Down" tone="destructive" />
              <MetricChip count={overall.total_components} label="Total" tone="muted" />
            </div>
          </div>
        </div>
      </div>

      <section>
        <SectionHeader label="At a glance" />
        <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="System health"
            value={`${readyPct}%`}
            hint={`${overall.healthy} healthy · ${overall.degraded} degraded · ${overall.unhealthy} down`}
            icon={ActivityIcon}
            status={overall.status}
            onClick={() => navigateSection("diagnostics")}
          />
          <StatCard
            label="Pending approvals"
            value={data.pending_actions?.length ?? 0}
            hint="actions awaiting your confirmation"
            icon={ShieldCheckIcon}
            accent="orange"
            onClick={() => navigateSection("inbox")}
          />
          <StatCard
            label="Active tasks"
            value={data.active_tasks?.length ?? 0}
            hint="coordinator jobs in progress"
            icon={ActivityIcon}
            accent="sky"
            onClick={() => navigateSection("activity")}
          />
          <StatCard
            label="RAG memory"
            value={stats.rag_chunks}
            hint="chunks indexed in memory"
            icon={DatabaseIcon}
            onClick={() => navigateSection("meetings")}
          />
        </div>
      </section>

      <section>
        <SectionHeader label="Integrations & meetings" />
        <div className="mt-3 grid gap-4 lg:grid-cols-12">
          <div className="grid gap-4 sm:grid-cols-2 lg:col-span-4">
            <StatCard
              label="Upcoming meets"
              value={calendar.upcoming.filter((e) => e.has_meet).length}
              hint="with Google Meet links (7 days)"
              icon={CalendarIcon}
              className="h-full"
              onClick={() => navigateSection("meetings")}
            />
            <StatCard
              label="WhatsApp"
              value={whatsapp.recent_messages.length}
              hint="recent messages buffered"
              icon={MessageCircleIcon}
              status={data.connections.whatsapp?.connected ? "connected" : "disconnected"}
              accent="sky"
              className="h-full"
              onClick={() => navigateSection("settings")}
            />
          </div>

          <PanelCard
            title="Health breakdown"
            description="Component readiness"
            icon={ActivityIcon}
            className="lg:col-span-3"
          >
            <div className="flex flex-col gap-5">
              <div>
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Readiness</span>
                  <span className="font-bold text-primary">{readyPct}%</span>
                </div>
                <Progress
                  value={readyPct}
                  className="h-2 bg-muted [&>div]:rounded-full [&>div]:bg-primary"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <HealthSegment count={overall.healthy} label="Healthy" tone="success" />
                <HealthSegment count={overall.degraded} label="Degraded" tone="warning" />
                <HealthSegment count={overall.unhealthy} label="Down" tone="destructive" />
              </div>
            </div>
          </PanelCard>

          <PanelCard
            title="Triggerable meets now"
            description="Meetings in the auto-join window"
            icon={VideoIcon}
            className="lg:col-span-5"
          >
            {calendar.triggerable_now.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
                <div className="flex size-12 items-center justify-center rounded-2xl border border-border bg-muted">
                  <VideoIcon className="size-5 text-primary/60" />
                </div>
                <p className="text-sm text-muted-foreground">No meetings in the join window right now.</p>
              </div>
            ) : (
              <ul className="flex flex-col gap-2">
                {calendar.triggerable_now.map((ev, i) => (
                  <li key={i} className="list-row">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="font-semibold text-foreground">{ev.summary}</div>
                        <div className="text-xs text-muted-foreground">{ev.start}</div>
                      </div>
                      {ev.meet_url && (
                        <a
                          className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-border bg-muted px-3 py-1.5 text-xs font-semibold text-primary transition-colors duration-200 hover:bg-accent"
                          href={ev.meet_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Join Meet <ArrowRightIcon className="size-3" />
                        </a>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </PanelCard>
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between">
          <p className="section-label">
            {orchestrator ? "Orchestrator & workers" : "Specialist agents"}
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="cursor-pointer text-xs font-semibold text-primary"
              onClick={() => setWorkersOpen((v) => !v)}
            >
              {workersOpen ? "Collapse" : "Expand"}
              <ChevronDownIcon className={cn("size-3.5 transition-transform", workersOpen && "rotate-180")} />
            </Button>
            <button
              type="button"
              onClick={() => navigateSection("diagnostics")}
              className="flex cursor-pointer items-center gap-1 text-xs font-semibold text-primary/70 transition-colors hover:text-primary"
            >
              View all <ArrowRightIcon className="size-3" />
            </button>
          </div>
        </div>

        {workersOpen && (
          <div className="mt-3 space-y-3">
            {orchestrator ? (
              <PanelCard
                title={orchestrator.orchestrator.name}
                description={orchestrator.orchestrator.role}
                icon={WorkflowIcon}
              >
                <p className="text-xs text-muted-foreground">
                  {orchestrator.skills.length} skills · {orchestrator.workers.length} workers ·{" "}
                  {orchestrator.tools.length} tools
                </p>
              </PanelCard>
            ) : null}
            <PanelCard
              title="Workers"
              description="Domain agents and bound tools"
              icon={ServerIcon}
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {workerCards.map((worker) => {
                  const agentStatus = agents.find((a) => a.id === worker.id)?.status ?? "healthy"
                  return (
                    <div key={worker.id} className="list-row flex flex-col gap-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-foreground">{worker.name}</div>
                          <div className="line-clamp-2 text-xs text-muted-foreground">{worker.role}</div>
                        </div>
                        <StatusBadge status={agentStatus} />
                      </div>
                      {worker.tools.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {worker.tools.slice(0, 3).map((tool) => (
                            <Badge
                              key={tool}
                              variant="outline"
                              className="border-border bg-muted text-[10px] font-medium text-muted-foreground"
                            >
                              {tool}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <Badge
                          variant="outline"
                          className="w-fit border-border bg-muted text-xs font-medium text-primary"
                        >
                          {agents.find((a) => a.id === worker.id)?.model_category ?? worker.runner}
                        </Badge>
                      )}
                    </div>
                  )
                })}
              </div>
            </PanelCard>
          </div>
        )}
      </section>
    </div>
  )
}

function SectionHeader({ label }: { label: string }) {
  return <p className="section-label">{label}</p>
}

function MetricChip({
  count,
  label,
  tone,
}: {
  count: number
  label: string
  tone: "success" | "warning" | "destructive" | "muted"
}) {
  const styles = {
    success: "border-success/30 bg-success/5 text-success",
    warning: "border-warning/30 bg-warning/5 text-warning",
    destructive: "border-destructive/30 bg-destructive/5 text-destructive",
    muted: "border-border bg-muted text-primary",
  }

  return (
    <div className={cn("flex flex-col items-center gap-0.5 rounded-xl border px-3 py-2.5 text-center", styles[tone])}>
      <span className="text-xl font-extrabold">{count}</span>
      <span className="text-[10px] font-semibold uppercase tracking-wide opacity-80">{label}</span>
    </div>
  )
}

function HealthSegment({
  count,
  label,
  tone,
}: {
  count: number
  label: string
  tone: "success" | "warning" | "destructive"
}) {
  const dot = {
    success: "bg-success glow-green",
    warning: "bg-warning glow-amber",
    destructive: "bg-destructive glow-red",
  }[tone]
  const color = {
    success: "text-success",
    warning: "text-warning",
    destructive: "text-destructive",
  }[tone]

  return (
    <div className="list-row flex flex-col items-center gap-1.5 py-4">
      <span className={cn("size-2 rounded-full", dot)} aria-hidden />
      <p className={cn("text-2xl font-extrabold", color)}>{count}</p>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
    </div>
  )
}
