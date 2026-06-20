import {
  ActivityIcon,
  ArrowRightIcon,
  CalendarIcon,
  DatabaseIcon,
  MessageCircleIcon,
  ServerIcon,
  ShieldCheckIcon,
  VideoIcon,
} from "lucide-react"
import tempaLogo from "@/assets/tempa.png"
import tempaVideo from "@/assets/animated_tempa.mp4"
import type { DashboardPayload } from "@/types/dashboard"
import type { NavSection } from "@/components/dashboard/nav"
import { StatCard } from "@/components/dashboard/stat-card"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

export function OverviewTab({
  data,
  onNavigate,
}: {
  data: DashboardPayload
  onNavigate: (section: NavSection) => void
}) {
  const { overall, agents, calendar, whatsapp, data: stats } = data
  const readyPct = overall.total_components > 0
    ? Math.round((overall.healthy / overall.total_components) * 100)
    : 0

  return (
    <div className="flex flex-col gap-8">

      {/* ══ TEMPA HERO — video is the star ══════════════════ */}
      <div className="relative overflow-hidden rounded-2xl border border-border bg-white shadow-sm">
        {/* blue radial glow behind mascot */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 55% 80% at 20% 50%, rgba(61,108,185,0.07) 0%, transparent 70%)",
          }}
          aria-hidden
        />

        <div className="relative flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-center sm:gap-8 sm:p-8">

          {/* ── Video mascot ──────────────────────────── */}
          <div className="flex flex-col items-center gap-3">
            {/* outer decorative ring */}
            <div
              className="mascot-glow relative rounded-3xl p-1"
              style={{
                background: "linear-gradient(135deg, rgba(61,108,185,0.15) 0%, rgba(61,108,185,0.05) 100%)",
                borderRadius: "1.5rem",
              }}
            >
              <div className="relative overflow-hidden rounded-[1.25rem] border-2 border-primary/20 bg-slate-50 shadow-inner"
                style={{ width: 220, height: 220 }}>
                <video
                  src={tempaVideo}
                  autoPlay
                  loop
                  muted
                  playsInline
                  className="h-full w-full object-cover"
                  aria-label="Tempa mascot animation"
                />
                {/* live indicator */}
                <span
                  className="absolute bottom-2.5 right-2.5 flex size-5 items-center justify-center rounded-full border-2 border-white bg-green-500 shadow-[0_0_10px_rgba(22,163,74,0.8)]"
                  aria-label="Online"
                >
                  <span className="size-2 rounded-full bg-white/80 pulse-live" aria-hidden />
                </span>
              </div>
            </div>
            {/* name tag */}
            <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/8 px-4 py-1.5">
              <img src={tempaLogo} alt="" className="size-4 rounded-full object-cover" aria-hidden />
              <span className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">
                Tempa
              </span>
              <Badge
                variant="outline"
                className="h-4 border-primary/25 bg-white px-1 text-[9px] font-semibold text-primary/70"
              >
                v{data.environment.tempa_version}
              </Badge>
            </div>
          </div>

          {/* ── Info panel ────────────────────────────── */}
          <div className="flex min-w-0 flex-1 flex-col gap-5">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-2xl font-bold text-foreground">Your AI core is running</h2>
                <StatusBadge status={overall.status} />
              </div>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Personal AI agent — always-on, always watching your world.
              </p>
            </div>

            {/* health progress */}
            <div>
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-medium text-muted-foreground">System readiness</span>
                <span className="font-bold text-foreground">{readyPct}%</span>
              </div>
              <Progress
                value={readyPct}
                className="h-2 bg-muted [&>div]:bg-primary [&>div]:transition-all [&>div]:duration-700"
              />
            </div>

            {/* quick stat pills */}
            <div className="flex flex-wrap gap-2">
              <StatPill
                label="Healthy"
                value={overall.healthy}
                color="border-green-200 bg-green-50 text-green-700"
                dot="bg-green-500 shadow-[0_0_6px_rgba(22,163,74,0.8)]"
              />
              <StatPill
                label="Degraded"
                value={overall.degraded}
                color="border-amber-200 bg-amber-50 text-amber-700"
                dot="bg-amber-500"
              />
              <StatPill
                label="Down"
                value={overall.unhealthy}
                color="border-red-200 bg-red-50 text-red-600"
                dot="bg-red-500"
              />
              <StatPill
                label="Total"
                value={overall.total_components}
                color="border-border bg-muted/60 text-foreground"
                dot="bg-primary/60"
              />
            </div>
          </div>
        </div>
      </div>
      {/* ══════════════════════════════════════════════════ */}

      {/* ── Primary stats ─────────────────────────────────── */}
      <section>
        <SectionHeader label="System status" />
        <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <StatCard
            label="System health"
            value={`${readyPct}%`}
            hint={`${overall.healthy} healthy · ${overall.degraded} degraded · ${overall.unhealthy} down`}
            icon={ActivityIcon}
            status={overall.status}
            onClick={() => onNavigate("components")}
          />
          <StatCard
            label="Pending approvals"
            value={data.pending_actions?.length ?? 0}
            hint="actions awaiting your confirmation"
            icon={ShieldCheckIcon}
            onClick={() => onNavigate("pending")}
          />
          <StatCard
            label="Active tasks"
            value={data.active_tasks?.length ?? 0}
            hint="coordinator jobs in progress"
            icon={ActivityIcon}
            onClick={() => onNavigate("activity")}
          />
        </div>
      </section>

      {/* ── Integration stats ─────────────────────────────── */}
      <section>
        <SectionHeader label="Integrations" />
        <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <StatCard
            label="Unified RAG"
            value={stats.rag_chunks}
            hint="chunks indexed in memory"
            icon={DatabaseIcon}
            onClick={() => onNavigate("data")}
          />
          <StatCard
            label="Upcoming meets"
            value={calendar.upcoming.filter((e) => e.has_meet).length}
            hint="with Google Meet links (7 days)"
            icon={CalendarIcon}
            onClick={() => onNavigate("data")}
          />
          <StatCard
            label="WhatsApp"
            value={whatsapp.recent_messages.length}
            hint="recent messages buffered"
            icon={MessageCircleIcon}
            status={data.connections.whatsapp?.connected ? "connected" : "disconnected"}
            onClick={() => onNavigate("connections")}
          />
        </div>
      </section>

      {/* ── Health breakdown + Meetings ───────────────────── */}
      <section>
        <SectionHeader label="At a glance" />
        <div className="mt-3 grid gap-4 lg:grid-cols-5">
          <PanelCard
            title="Health breakdown"
            description="Component readiness"
            icon={ActivityIcon}
            className="lg:col-span-2"
          >
            <div className="flex flex-col gap-5">
              <div>
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Readiness</span>
                  <span className="font-semibold text-foreground">{readyPct}%</span>
                </div>
                <Progress
                  value={readyPct}
                  className="h-1.5 bg-muted [&>div]:bg-primary [&>div]:transition-all [&>div]:duration-700"
                />
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <HealthSegment count={overall.healthy}   label="Healthy"  color="text-green-600" dot="bg-green-500 shadow-[0_0_6px_rgba(22,163,74,0.8)]" />
                <HealthSegment count={overall.degraded}  label="Degraded" color="text-amber-600" dot="bg-amber-500" />
                <HealthSegment count={overall.unhealthy} label="Down"     color="text-red-600"   dot="bg-red-500" />
              </div>
            </div>
          </PanelCard>

          <PanelCard
            title="Triggerable meets now"
            description="Meetings in the auto-join window"
            icon={VideoIcon}
            className="lg:col-span-3"
          >
            {calendar.triggerable_now.length === 0 ? (
              <p className="text-sm text-muted-foreground">No meetings in the join window right now.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {calendar.triggerable_now.map((ev, i) => (
                  <li key={i} className="list-row">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="font-medium text-foreground">{ev.summary}</div>
                        <div className="text-xs text-muted-foreground">{ev.start}</div>
                      </div>
                      {ev.meet_url && (
                        <a
                          className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-primary/30 bg-primary/8 px-2.5 py-1 text-xs text-primary transition-colors duration-200 hover:border-primary/50 hover:bg-primary/15"
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

      {/* ── Agents ────────────────────────────────────────── */}
      <section>
        <SectionHeader
          label="Specialist agents"
          action={
            <button
              type="button"
              onClick={() => onNavigate("components")}
              className="flex cursor-pointer items-center gap-1 text-xs text-primary/70 transition-colors hover:text-primary"
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
            <Table>
              <TableHeader>
                <TableRow className="border-border/60 hover:bg-transparent">
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Agent</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Model</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.map((agent) => (
                  <TableRow key={agent.id} className="border-border/40 transition-colors hover:bg-muted/30">
                    <TableCell>
                      <div className="font-medium text-foreground">{agent.name}</div>
                      <div className="text-xs text-muted-foreground">{agent.role}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="border-primary/25 bg-primary/8 text-xs text-primary/80">
                        {agent.model_category}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={agent.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </PanelCard>
        </div>
      </section>
    </div>
  )
}

/* ── Small helpers ──────────────────────────────────────── */

function SectionHeader({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
        {label}
      </p>
      {action}
    </div>
  )
}

function StatPill({
  label, value, color, dot,
}: {
  label: string; value: number; color: string; dot: string
}) {
  return (
    <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold ${color}`}>
      <span className={`size-2 rounded-full shrink-0 ${dot}`} aria-hidden />
      {value}
      <span className="text-xs font-normal opacity-80">{label}</span>
    </div>
  )
}

function HealthSegment({ count, label, color, dot }: {
  count: number; label: string; color: string; dot: string
}) {
  return (
    <div className="list-row flex flex-col items-center gap-1.5">
      <span className={`size-2 rounded-full ${dot}`} aria-hidden />
      <p className={`text-2xl font-bold ${color}`}>{count}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
