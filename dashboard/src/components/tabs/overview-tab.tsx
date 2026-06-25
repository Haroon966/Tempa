import {
  ActivityIcon,
  ArrowRightIcon,
  CalendarIcon,
  DatabaseIcon,
  MessageCircleIcon,
  ServerIcon,
  ShieldCheckIcon,
  SparklesIcon,
  VideoIcon,
} from "lucide-react"
import tempaVideo from "@/assets/animated_tempa.mp4"
import type { DashboardPayload } from "@/types/dashboard"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { StatCard } from "@/components/dashboard/stat-card"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export function OverviewTab({ data }: { data: DashboardPayload }) {
  const navigateSection = useNavigateSection()
  const { overall, agents, calendar, whatsapp, data: stats } = data
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

      {/* ══ Bento hero grid ═════════════════════════════════ */}
      <div className="grid gap-4 lg:grid-cols-12 lg:gap-5">

        {/* Mascot tile — square 1:1 */}
        <div className="bento-tile relative self-start overflow-hidden rounded-2xl border border-white bg-[#f4f6f6] before:hidden hover:border-white hover:shadow-[0_1px_2px_rgba(19,78,74,0.04)] lg:col-span-3">
          <div className="relative aspect-square w-full bg-[#f4f6f6] p-[6px]">
            <video
              src={tempaVideo}
              autoPlay
              loop
              muted
              playsInline
              className="h-full w-full object-cover"
              aria-label="Tempa mascot animation"
            />
          </div>
        </div>

        {/* Status tile — wider command center */}
        <div className="bento-tile flex flex-col justify-between rounded-2xl p-6 sm:p-8 lg:col-span-9">
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
                className="h-2.5 bg-muted [&>div]:rounded-full [&>div]:bg-gradient-to-r [&>div]:from-primary [&>div]:to-secondary [&>div]:transition-all [&>div]:duration-700"
              />
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <MetricChip count={overall.healthy} label="Healthy" tone="emerald" />
              <MetricChip count={overall.degraded} label="Degraded" tone="amber" />
              <MetricChip count={overall.unhealthy} label="Down" tone="red" />
              <MetricChip count={overall.total_components} label="Total" tone="teal" />
            </div>
          </div>
        </div>
      </div>

      {/* ══ Quick stats bento row ═══════════════════════════ */}
      <section>
        <SectionHeader label="At a glance" />
        <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="System health"
            value={`${readyPct}%`}
            hint={`${overall.healthy} healthy · ${overall.degraded} degraded · ${overall.unhealthy} down`}
            icon={ActivityIcon}
            status={overall.status}
            onClick={() => navigateSection("components")}
          />
          <StatCard
            label="Pending approvals"
            value={data.pending_actions?.length ?? 0}
            hint="actions awaiting your confirmation"
            icon={ShieldCheckIcon}
            accent="orange"
            onClick={() => navigateSection("pending")}
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
            onClick={() => navigateSection("data")}
          />
        </div>
      </section>

      {/* ══ Integration + meetings bento ════════════════════ */}
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
              onClick={() => navigateSection("data")}
            />
            <StatCard
              label="WhatsApp"
              value={whatsapp.recent_messages.length}
              hint="recent messages buffered"
              icon={MessageCircleIcon}
              status={data.connections.whatsapp?.connected ? "connected" : "disconnected"}
              accent="sky"
              className="h-full"
              onClick={() => navigateSection("connections")}
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
                  className="h-2 bg-muted [&>div]:rounded-full [&>div]:bg-gradient-to-r [&>div]:from-primary [&>div]:to-secondary"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <HealthSegment count={overall.healthy} label="Healthy" color="text-emerald-700" dot="bg-emerald-500 glow-green" />
                <HealthSegment count={overall.degraded} label="Degraded" color="text-amber-700" dot="bg-amber-500 glow-amber" />
                <HealthSegment count={overall.unhealthy} label="Down" color="text-red-700" dot="bg-red-500 glow-red" />
              </div>
            </div>
          </PanelCard>

          <PanelCard
            title="Triggerable meets now"
            description="Meetings in the auto-join window"
            icon={VideoIcon}
            variant="featured"
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
                          className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-border bg-muted px-3 py-1.5 text-xs font-semibold text-primary transition-all duration-200 hover:bg-muted/80 hover:shadow-sm"
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

      {/* ══ Specialist agents ═════════════════════════════ */}
      <section>
        <SectionHeader
          label="Specialist agents"
          action={
            <button
              type="button"
              onClick={() => navigateSection("components")}
              className="flex cursor-pointer items-center gap-1 text-xs font-semibold text-primary/70 transition-colors hover:text-primary"
            >
              View all <ArrowRightIcon className="size-3" />
            </button>
          }
        />
        <div className="mt-3">
          <PanelCard
            title="Agents"
            description="Model-backed agents and their live status"
            icon={ServerIcon}
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {agents.map((agent) => (
                <div key={agent.id} className="list-row flex flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-foreground">{agent.name}</div>
                      <div className="line-clamp-2 text-xs text-muted-foreground">{agent.role}</div>
                    </div>
                    <StatusBadge status={agent.status} />
                  </div>
                  <Badge
                    variant="outline"
                    className="w-fit border-border bg-muted text-xs font-medium text-primary"
                  >
                    {agent.model_category}
                  </Badge>
                </div>
              ))}
            </div>
          </PanelCard>
        </div>
      </section>
    </div>
  )
}

function SectionHeader({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <p className="section-label">{label}</p>
      {action}
    </div>
  )
}

function MetricChip({
  count,
  label,
  tone,
}: {
  count: number
  label: string
  tone: "emerald" | "amber" | "red" | "teal"
}) {
  const styles = {
    emerald: "border-emerald-200/80 bg-emerald-50/80 text-emerald-800",
    amber: "border-amber-200/80 bg-amber-50/80 text-amber-800",
    red: "border-red-200/80 bg-red-50/80 text-red-700",
    teal: "border-border bg-muted text-primary",
  }

  return (
    <div className={cn("flex flex-col items-center gap-0.5 rounded-xl border px-3 py-2.5 text-center", styles[tone])}>
      <span className="text-xl font-extrabold">{count}</span>
      <span className="text-[10px] font-semibold uppercase tracking-wide opacity-80">{label}</span>
    </div>
  )
}

function HealthSegment({ count, label, color, dot }: {
  count: number; label: string; color: string; dot: string
}) {
  return (
    <div className="list-row flex flex-col items-center gap-1.5 py-4">
      <span className={cn("size-2 rounded-full", dot)} aria-hidden />
      <p className={cn("text-2xl font-extrabold", color)}>{count}</p>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
    </div>
  )
}
